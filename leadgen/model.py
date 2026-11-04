from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

SOCIAL_HOSTS = {"vk.com", "vk.ru", "t.me", "telegram.me", "wa.me", "whatsapp.com",
                "instagram.com", "facebook.com", "ok.ru", "youtube.com", "youtu.be",
                "viber.com", "twitter.com", "x.com", "2gis.ru", "yandex.ru"}


def text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def phone(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    return "+" + digits if 7 <= len(digits) <= 15 else ""


def branch_key(city, address):
    """Compare common Russian address spellings without losing house/branch numbers."""
    city = re.sub(r"\b(?:город|г)\b", "", text(city).casefold().replace("ё", "е"))
    city = re.sub(r"[^\w]+", " ", city).strip()
    address = text(address).casefold().replace("ё", "е")
    address = re.sub(r"\b(?:россия|рф|russia)\b", "", address)
    if city:
        address = re.sub(r"\b" + re.escape(city) + r"\b", "", address)
    address = re.sub(r"\bпр-т\b", "проспект", address)
    address = re.sub(r"\bул\b", "улица", address)
    address = re.sub(r"\b(?:дом|д|город|г)\b", "", address)
    address = re.sub(r"(?<!\w)\d{6}(?!\w)", "", address)
    address = re.sub(r"[^\w/-]+", " ", address).strip()
    return city, re.sub(r"\s+", " ", address)


def website(value):
    value = text(value)
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    try:
        parts = urlsplit(value)
        host = (parts.hostname or "").lower().removeprefix("www.").encode("idna").decode("ascii")
        port = parts.port
        _ = parts.port  # Validate malformed ports too.
        if parts.scheme not in ("http", "https") or "." not in host or parts.username or parts.password:
            return ""
        # Keep meaningful query parameters (some company sites need them).
        query = urlencode([(k, v) for k, v in parse_qsl(parts.query)
                           if not k.lower().startswith("utm_") and k.lower() not in {"yclid", "gclid", "fbclid"}])
        netloc = host + (f":{port}" if port is not None else "")
        return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", query, ""))
    except ValueError:
        return ""


def is_social(url):
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    return any(host == item or host.endswith("." + item) for item in SOCIAL_HOSTS)


def values(value):
    return value if isinstance(value, list) else str(value or "").split(";")


def normalize(record):
    source = record.get("source")
    source_id = text(record.get("source_id"))
    name = text(record.get("name"))
    if source not in ("yandex", "2gis") or not source_id or not name:
        raise ValueError("Нужны source (yandex/2gis), source_id и название компании")
    urls = [website(x) for x in values(record.get("websites", record.get("site")))]
    social = [website(x) for x in values(record.get("social"))]
    social += [u for u in urls if u and is_social(u)]
    sites = sorted({u for u in urls if u and not is_social(u)})
    emails = sorted({text(x).lower() for x in values(record.get("emails", record.get("email")))
                     if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", text(x))})
    return {
        "source": source, "source_id": source_id,
        "source_url": website(record.get("source_url", record.get("url"))),
        "name": name, "city": text(record.get("city")), "address": text(record.get("address")),
        "category": text(record.get("category")),
        "phones": sorted({p for x in values(record.get("phones", record.get("phone"))) if (p := phone(x))}),
        "emails": emails, "websites": sites, "social": sorted({u for u in social if u}),
        "website_status": "Present" if sites else "NotListed",
        "gis_created_at": text(record.get("gis_created_at")),
        "rating": record.get("rating"), "reviews": record.get("reviews"),
    }
