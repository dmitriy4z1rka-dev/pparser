from __future__ import annotations

import os
import signal
import sys
from pathlib import Path

from .collectors import collect
from .store import Store


def run(data_dir, job_id):
    store = Store(Path(data_dir) / "leads.sqlite3")
    job = next((j for j in store.jobs() if j["id"] == job_id), None)
    if not job:
        raise ValueError("Задание не найдено")
    previous = store.job_records(job_id)
    seen = {r["company_id"] for r in previous}
    seen_sources = {(r["source"], r["source_id"]) for r in previous}

    def receive(record):
        key = (record["source"], record["source_id"])
        if key not in seen_sources and len(seen) >= job["config"]["limit"]:
            return
        company_id = store.ingest(record, job_id)
        seen.add(company_id)
        seen_sources.add(key)
        store.update_job(job_id, "running", len(seen))

    def stop(signum, frame):
        raise KeyboardInterrupt

    previous_handler = signal.signal(signal.SIGTERM, stop)
    store.update_job(job_id, "running", error=None)
    try:
        if len(seen) < job["config"]["limit"]:
            collect(job["config"], receive, Path(data_dir) / "checkpoints" / (job_id + ".json"), seen_sources)
        if not seen:
            raise RuntimeError("Компании не получены. Проверьте запрос, доступ к картам и разметку сайта.")
        store.update_job(job_id, "done", len(seen))
        return 0
    except KeyboardInterrupt:
        store.update_job(job_id, "stopped", len(seen))
        return 130
    except Exception as exc:
        status = "blocked" if any(word in str(exc).casefold() for word in ("огранич", "captcha", "капч")) else "error"
        store.update_job(job_id, status, len(seen), str(exc))
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous_handler)


if __name__ == "__main__":
    sys.exit(run(os.environ.get("LEADGEN_DATA", "./var"), sys.argv[1]))
