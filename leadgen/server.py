from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .collectors import ROOT, validate_job
from .crm import sync


class Runner:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.process = None
        self.job_id = None
        self.done = threading.Event()
        # A worker cannot survive a service restart; leave an explicit resumable status.
        for job in store.jobs():
            if job["status"] == "running":
                store.update_job(job["id"], "interrupted", error="Сервис был перезапущен. Можно продолжить задание.")

    def start(self):
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()

    def loop(self):
        while not self.done.is_set():
            try:
                with self.lock:
                    queued = [j for j in self.store.jobs() if j["status"] == "queued"]
                    if queued:
                        job = queued[-1]
                        self.job_id = job["id"]
                        self.store.update_job(self.job_id, "running")
                        log_path = Path(self.store.path).parent / "logs" / (self.job_id + ".log")
                        log_path.parent.mkdir(parents=True, exist_ok=True)
                        with log_path.open("a", encoding="utf-8") as log:
                            self.process = subprocess.Popen([sys.executable, "-m", "leadgen.worker", self.job_id],
                                                            cwd=ROOT, stdout=log, stderr=log, start_new_session=True)
                if self.process:
                    self.process.wait()
                    with self.lock:
                        current = next(j for j in self.store.jobs() if j["id"] == self.job_id)
                        if current["status"] == "running":
                            self.store.update_job(self.job_id, "interrupted", error="Процесс сбора завершился неожиданно.")
                        self.process = None
                        self.job_id = None
                with self.lock:
                    if self.store.companies(pending=True):
                        sync(self.store)
            except Exception as exc:
                if self.job_id and not self.process:
                    self.store.update_job(self.job_id, "error", error=str(exc))
                    self.job_id = None
                print("Ошибка очереди:", str(exc), file=sys.stderr, flush=True)
            self.done.wait(5)

    def stop_job(self, job_id):
        with self.lock:
            job = next((j for j in self.store.jobs() if j["id"] == job_id), None)
            if not job:
                raise ValueError("Задание не найдено")
            if self.process and self.job_id == job_id:
                os.killpg(self.process.pid, signal.SIGTERM)
                self.store.update_job(job_id, "stopped")
            elif job["status"] == "queued":
                self.store.update_job(job_id, "stopped")

    def close(self):
        self.done.set()
        if self.job_id:
            self.stop_job(self.job_id)


def serve(store, host, port):
    runner = Runner(store)

    class Handler(BaseHTTPRequestHandler):
        def local_request(self):
            try:
                hostname = urlsplit("//" + self.headers.get("Host", "")).hostname
            except ValueError:
                hostname = None
            if hostname not in {"localhost", "127.0.0.1", "::1", "collectors"}:
                self.reply({"error": "Панель доступна только локально"}, 403)
                return False
            return True

        def reply(self, data, status=200, content_type="application/json; charset=utf-8"):
            body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.local_request():
                return
            if self.path == "/":
                return self.reply((ROOT / "leadgen/static/index.html").read_bytes(), content_type="text/html; charset=utf-8")
            if self.path == "/api/status":
                companies = store.companies()
                return self.reply({"jobs": store.jobs(), "companies": companies[:500],
                                   "total": len(companies), "pending": len(store.companies(True)),
                                   "crm_url": os.environ.get("ESPO_PUBLIC_URL", "http://localhost:8080")})
            self.reply({"error": "Не найдено"}, 404)

        def do_POST(self):
            if not self.local_request():
                return
            # A local workspace still rejects requests from unrelated websites.
            origin = self.headers.get("Origin")
            if (origin and urlsplit(origin).netloc != self.headers.get("Host")) or \
                    self.headers.get("Sec-Fetch-Site") == "cross-site" or \
                    self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.reply({"error": "Недопустимый запрос"}, 403)
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 16384:
                    raise ValueError("Некорректный размер запроса")
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise ValueError("Ожидается JSON объект")
                if self.path == "/api/jobs":
                    config = validate_job(body)
                    return self.reply({"id": store.create_job(config)}, 201)
                if self.path == "/api/sync":
                    with runner.lock:
                        return self.reply(sync(store))
                if self.path == "/api/stop":
                    runner.stop_job(body["id"])
                    return self.reply({"ok": True})
                if self.path == "/api/resume":
                    with runner.lock:
                        job = next((j for j in store.jobs() if j["id"] == body["id"]), None)
                        if not job or job["status"] in ("running", "queued", "done"):
                            raise ValueError("Это задание нельзя продолжить")
                        store.update_job(job["id"], "queued")
                    return self.reply({"ok": True})
                self.reply({"error": "Не найдено"}, 404)
            except (ValueError, KeyError, TypeError) as exc:
                self.reply({"error": str(exc)}, 400)
            except Exception:
                self.reply({"error": "Операция не выполнена. Данные сохранены; проверьте журнал сервиса."}, 503)

    server = ThreadingHTTPServer((host, port), Handler)
    runner.start()
    print(f"Панель сбора: http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    finally:
        runner.close()
        server.server_close()
