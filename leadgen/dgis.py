"""Optional 2GIS Places API enrichment for browser-collected branch IDs."""
from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def add_catalog_dates(records, api_key, opener=urlopen):
    """Return records enriched with the 2GIS catalog insertion timestamp.

    The API allows up to 100 IDs per request. We deliberately preserve the raw
    browser-parser data and treat an absent date as unknown, not as an error.
    """
    by_id = {str(record["source_id"]).split("_")[0]: record
             for record in records if record.get("source") == "2gis" and record.get("source_id")}
    dates = {}
    ids = list(by_id)
    for offset in range(0, len(ids), 100):
        batch = ids[offset:offset + 100]
        query = urlencode({"key": api_key, "id": ",".join(batch), "fields": "items.dates"})
        request = Request("https://catalog.api.2gis.com/3.0/items/byid?" + query,
                          headers={"Accept": "application/json"})
        try:
            with opener(request, timeout=30) as response:
                payload = json.load(response)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            # Never include the request URL in errors: it contains the API key.
            raise RuntimeError("Places API не вернул данные (сеть, ключ или лимит)") from None
        meta = payload.get("meta") or {}
        if meta.get("code") != 200:
            raise RuntimeError(f"Places API вернул код {meta.get('code', 'неизвестен')}")
        for item in (payload.get("result") or {}).get("items") or []:
            item_id = str(item.get("id", "")).split("_")[0]
            created_at = ((item.get("dates") or {}).get("created_at") or "").strip()
            if item_id in by_id and created_at:
                dates[item_id] = created_at
    result = []
    for record in records:
        enriched = dict(record)
        if enriched.get("source") == "2gis":
            created_at = dates.get(str(enriched.get("source_id", "")).split("_")[0])
            if created_at:
                enriched["gis_created_at"] = created_at
                result.append(enriched)
        # Preserve the input list's semantics: records without dates are not
        # returned as enrichment updates.
    return result
