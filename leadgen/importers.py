from .model import normalize


def import_2gis(document, city=""):
    # Accept raw API responses and individual catalog items from JsonWriter.
    items = document.get("result", {}).get("items", [document])
    for item in items:
        if item.get("type") not in (None, "branch", "firm"):
            continue
        contacts = {}
        for group in item.get("contact_groups") or []:
            for contact in group.get("contacts") or []:
                value = (contact.get("value") if contact.get("type") in ("phone", "email") else
                         contact.get("url") or contact.get("value"))
                if value:
                    contacts.setdefault(contact["type"], []).append(value)
        item_id = str(item.get("id", "")).split("_")[0]
        yield normalize({"source": "2gis", "source_id": item_id,
                         "name": (item.get("name_ex") or {}).get("primary") or item.get("name"),
                         "address": item.get("address_name"),
                         "city": next((a["name"] for a in item.get("adm_div", []) if a.get("type") == "city"), city),
                         "category": "; ".join(r["name"] for r in item.get("rubrics", []) if r.get("name")),
                         "phones": contacts.get("phone", []), "emails": contacts.get("email", []),
                         "websites": contacts.get("website", []),
                         "social": [v for k, vs in contacts.items() if k not in ("phone", "email", "website", "fax") for v in vs],
                         "source_url": f"https://2gis.ru/firm/{item_id}",
                         "rating": (item.get("reviews") or {}).get("general_rating"),
                         "reviews": (item.get("reviews") or {}).get("general_review_count")})
