from __future__ import annotations

import importlib.util
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from urllib.parse import quote, urlsplit

from .model import normalize
from .importers import import_2gis

ROOT = Path(__file__).resolve().parent.parent


def validate_job(config):
    if config.get("source") not in ("yandex", "2gis"):
        raise ValueError("Выберите Яндекс или 2ГИС")
    if not str(config.get("city", "")).strip():
        raise ValueError("Укажите город (для 2ГИС: slug, например moscow)")
    if not str(config.get("query", "")).strip() and not config.get("url"):
        raise ValueError("Укажите категорию или поисковый запрос")
    limit = int(config.get("limit", 100))
    delay = float(config.get("delay", 2))
    if not 1 <= limit <= 10000 or not 1 <= delay <= 120:
        raise ValueError("Лимит: 1–10000 компаний; пауза: 1–120 секунд")
    url = config.get("url", "").strip()
    if url:
        parts = urlsplit(url)
        allowed = {"yandex.ru", "yandex.com"} if config["source"] == "yandex" else {"2gis.ru", "2gis.com"}
        if parts.scheme != "https" or parts.hostname not in allowed or parts.username or parts.port:
            raise ValueError("Нужен HTTPS URL поиска выбранного сервиса карт")
    return {"source": config["source"], "city": str(config["city"]).strip(),
            "query": str(config.get("query", "")).strip(), "limit": limit, "delay": delay,
            "url": url, "headful": bool(config.get("headful", False)),
            "grid": bool(config.get("grid", True))}


def yandex_module():
    name = "leadgen_yamaps"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / "yamaps_parser/yamaps_parser.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def collect(config, emit, checkpoint, seen_sources=None):
    if config["source"] == "yandex":
        module = yandex_module()

        def receive(org):
            emit(normalize(asdict(org) | {"source": "yandex", "source_id": org.id, "city": config["city"]}))

        if Path(checkpoint).exists():
            saved = json.loads(Path(checkpoint).read_text(encoding="utf-8"))["signature"]
            url, bbox = saved["url"], tuple(saved["bbox"])
        elif config["url"]:
            url, bbox = config["url"], None
        else:
            geo = module.geocode(config["city"])
            url = module.build_search_url(config["query"], center=geo["center"], span=geo["span"])
            bbox = geo["bbox"] if config["grid"] else None
        if bbox:
            module.search_grid(url, bbox, limit=config["limit"], delay=config["delay"],
                               headless=not config["headful"], checkpoint=str(checkpoint), on_organization=receive)
        else:
            module.search_all_browser(url, limit=config["limit"], headless=not config["headful"],
                                      settle_ms=int(config["delay"] * 1000), on_organization=receive)
        return

    sys.path.insert(0, str(ROOT / "parser-2gis-new"))
    from parser_2gis.config import Configuration
    from parser_2gis.parser import get_parser
    from parser_2gis.writer.writers import FileWriter

    class LeadWriter(FileWriter):
        def write(self, doc):
            if not self._check_catalog_doc(doc):
                return
            for record in import_2gis(doc, config["city"]):
                emit(record)
                collected.append(record)

    options = Configuration()
    collected = []
    options.chrome.headless = not config["headful"]
    # Use the Chromium installed by Playwright in the shared environment/container.
    if not options.chrome.binary_path:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            options.chrome.binary_path = Path(pw.chromium.executable_path)
    options.parser.delay_between_clicks = int(config["delay"] * 1000)
    options.parser.max_records = config["limit"]
    options.parser.skip_ids = {item_id for source, item_id in (seen_sources or set()) if source == "2gis"}
    options.chrome.memory_limit = 1024
    url = config["url"] or f"https://2gis.ru/{quote(config['city'], safe='')}/search/{quote(config['query'], safe='')}"
    with get_parser(url, options.chrome, options.parser) as parser:
        parser.parse(LeadWriter("", options.writer))
    api_key = os.environ.get("DGIS_API_KEY", "").strip()
    if api_key and collected:
        try:
            from .dgis import add_catalog_dates
            for record in add_catalog_dates(collected, api_key):
                if record.get("gis_created_at"):
                    emit(record)
        except Exception as exc:
            print(f"Не удалось получить даты 2ГИС API; компании сохранены без дат: {exc}", file=sys.stderr)
