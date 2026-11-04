from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

from .collectors import validate_job
from .model import normalize
from .store import Store


def main():
    parser = argparse.ArgumentParser(description="Яндекс + 2ГИС → EspoCRM")
    parser.add_argument("--data", default=os.environ.get("LEADGEN_DATA", "./var"))
    sub = parser.add_subparsers(dest="command", required=True)
    collect = sub.add_parser("collect", help="собрать и автоматически передать лиды в CRM")
    collect.add_argument("source", choices=["yandex", "2gis"])
    collect.add_argument("city")
    collect.add_argument("query")
    collect.add_argument("--limit", type=int, default=100)
    collect.add_argument("--delay", type=float, default=2)
    collect.add_argument("--url", default="")
    collect.add_argument("--headful", action="store_true")
    collect.add_argument("--no-grid", dest="grid", action="store_false")
    sub.add_parser("sync", help="повторить передачу ожидающих лидов")
    sub.add_parser("status")
    resume = sub.add_parser("resume")
    resume.add_argument("job_id")
    imp = sub.add_parser("import-file", help="импорт CSV Яндекса или JSON 2ГИС")
    imp.add_argument("source", choices=["yandex", "2gis"])
    imp.add_argument("path")
    imp.add_argument("--city", default="")
    serve = sub.add_parser("serve", help="панель запуска сбора")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    os.environ["LEADGEN_DATA"] = str(Path(args.data).resolve())
    store = Store(Path(args.data) / "leads.sqlite3")
    if args.command == "serve":
        from .server import serve
        serve(store, args.host, args.port)
        return 0
    if args.command == "status":
        print(json.dumps({"companies": len(store.companies()), "pending": len(store.companies(True)),
                          "jobs": store.jobs()}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "import-file":
        with open(args.path, encoding="utf-8-sig", newline="") as f:
            records = list(csv.DictReader(f)) if args.source == "yandex" else json.load(f)
        if isinstance(records, dict):
            records = [records]
        if args.source == "2gis":
            # The original JSON writer stores raw API documents inside an array.
            from .importers import import_2gis
            for record in records:
                for item in import_2gis(record, args.city):
                    store.ingest(item)
        else:
            for record in records:
                if not record.get("id"):
                    raise ValueError("В CSV Яндекса отсутствует поле id; используйте исходную выгрузку парсера")
                store.ingest(normalize(record | {"source": "yandex", "source_id": record["id"], "city": args.city}))
    if args.command in ("collect", "resume"):
        from .worker import run
        job_id = store.create_job(validate_job(vars(args))) if args.command == "collect" else args.job_id
        print("Задание:", job_id, flush=True)
        code = run(args.data, job_id)
    else:
        code = 0
    from .crm import sync
    try:
        result = sync(store)
        print(json.dumps(result, ensure_ascii=False))
        return code or (1 if result["errors"] else 0)
    except ValueError as exc:
        print(str(exc) + "; данные сохранены в " + args.data, file=sys.stderr)
        return code or 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError) as exc:
        sys.exit(str(exc))
