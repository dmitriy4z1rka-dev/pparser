"""Check saved CRM and collector state across a complete local service restart.

Run on the Docker host: python3 scripts/check_persistence.py
Creates a synthetic company/task, restarts the stack without removing volumes,
checks both databases through their HTTP APIs, and removes the synthetic records.
"""
import json
import os
import subprocess
import time
import uuid
from urllib.parse import urlencode
from urllib.request import Request, urlopen


CRM = os.environ.get("ESPO_PUBLIC_URL", "http://localhost:8080").rstrip("/") + "/api/v1/"
PANEL = os.environ.get("LEADGEN_PUBLIC_URL", "http://localhost:8090").rstrip("/")


def request(method, url, payload=None):
    req = Request(url, method=method, headers={"Content-Type": "application/json"},
                  data=json.dumps(payload).encode() if payload is not None else None)
    with urlopen(req, timeout=30) as response:
        body = response.read()
        return json.loads(body) if body else None


def panel_state():
    data = request("GET", PANEL + "/api/status")
    return {
        "companies": sorted((r["id"], r["crm_id"], r["revision"], r["synced_revision"]) for r in data["companies"]),
        "jobs": sorted((j["id"], j["status"], j["count"]) for j in data["jobs"]),
        "total": data["total"], "pending": data["pending"],
    }


def main():
    original_panel = panel_state()
    if any(j[1] in ("running", "queued") for j in original_panel["jobs"]) or original_panel["pending"]:
        raise SystemExit("Wait for collection and synchronization to finish before this restart test.")
    original_leads = request("GET", CRM + "Lead?" + urlencode({"searchParams": json.dumps({
        "maxSize": 200, "select": ["id", "accountName", "status", "description", "cLeadgenId"]})}))["list"]
    name = "CRM persistence test " + uuid.uuid4().hex[:12]
    lead = task = None
    try:
        lead = request("POST", CRM + "Lead", {"accountName": name, "status": "In Process",
                       "description": "Сохранённая заметка между сессиями", "website": "https://example.invalid/"})
        task = request("POST", CRM + "Task", {"name": name + " follow-up", "status": "Started",
                       "parentType": "Lead", "parentId": lead["id"], "description": "Сохранённая задача"})
        print("Saved a company, status, note and unassigned task; restarting services and MariaDB.", flush=True)
        subprocess.run(["docker", "compose", "stop", "collectors", "crm-daemon", "espocrm", "db"], check=True)
        subprocess.run(["docker", "compose", "up", "-d", "--no-build"], check=True)
        for attempt in range(30):
            try:
                restored_panel = panel_state()
                restored = request("GET", CRM + "Lead/" + lead["id"])
                break
            except OSError:
                if attempt == 29:
                    raise
                time.sleep(1)
        assert restored_panel == original_panel, "Collector database changed after restart"
        for field in ("accountName", "status", "description", "website"):
            assert restored[field] == lead[field], "Company field was lost: " + field
        restored_task = request("GET", CRM + "Task/" + task["id"])
        for field in ("name", "status", "description", "parentType", "parentId"):
            assert restored_task[field] == task[field], "Task field was lost: " + field
        assert not restored_task.get("assignedUserId"), "Task unexpectedly requires an owner"
        for existing in original_leads:
            actual = request("GET", CRM + "Lead/" + existing["id"])
            for field in ("accountName", "status", "description", "cLeadgenId"):
                assert actual.get(field) == existing.get(field), "An existing lead changed: " + field
        print("Persistence check passed: CRM records, notes, tasks, SQLite results and job states survived.", flush=True)
    finally:
        for entity_type, entity in (("Task", task), ("Lead", lead)):
            if entity:
                request("DELETE", CRM + entity_type + "/" + entity["id"])


if __name__ == "__main__":
    main()
