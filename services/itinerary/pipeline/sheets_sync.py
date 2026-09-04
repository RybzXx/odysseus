"""
BilWeekend — Google Sheets Sync
Synchronizes local JSON databases with Google Sheets and keeps local cache files updated.
"""
import json
import os
import re
from typing import Any

from googleapiclient.discovery import build

from services.itinerary.pipeline import config
from services.itinerary.pipeline import google_clients


def _ensure_tab_exists(spreadsheet_id: str, tab_name: str):
    meta = google_clients.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets.properties.title",
    ).execute(http=google_clients.http())
    existing = {
        s.get("properties", {}).get("title", "")
        for s in meta.get("sheets", [])
    }
    if tab_name in existing:
        return
    google_clients.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": tab_name}}}]},
    ).execute(http=google_clients.http())


def _safe_json_load(raw: str, default: Any):
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _to_bool(val: Any, default: bool = False) -> bool:
    if isinstance(val, bool):
        return val
    if val is None:
        return default
    s = str(val).strip().lower()
    return s in ("1", "true", "yes", "y")


def _to_int(val: Any, default: int = 0) -> int:
    if val is None or val == "":
        return default
    return int(float(val))


def _to_float(val: Any, default: float = 0.0) -> float:
    if val is None or val == "":
        return default
    return float(val)


def _clear_and_write_tab(spreadsheet_id: str, tab_name: str, rows: list[list[Any]]):
    _ensure_tab_exists(spreadsheet_id, tab_name)
    google_clients.sheet_values().clear(
        spreadsheetId=spreadsheet_id,
        range=tab_name,
        body={},
    ).execute(http=google_clients.http())
    google_clients.sheet_values().update(
        spreadsheetId=spreadsheet_id,
        range=tab_name,
        valueInputOption="RAW",
        body={"values": rows},
    ).execute(http=google_clients.http())


def _read_tab(spreadsheet_id: str, tab_name: str) -> list[list[str]]:
    res = google_clients.sheet_values().get(
        spreadsheetId=spreadsheet_id,
        range=tab_name,
    ).execute(http=google_clients.http())
    return res.get("values", [])


def _normalize_city_name(value: str) -> str:
    raw = " ".join(str(value or "").strip().split())
    if not raw:
        return ""
    city_map = {
        "BAGHDAD": "Baghdad",
        "NASIRIYA": "Nasiriyah",
        "KARBALA": "Karbala",
        "NAJAF": "Najaf",
        "BASRA": "Basra",
        "SULAYMA": "Sulaymaniyah",
        "SULAYMANIYAH": "Sulaymaniyah",
        "MOSUL": "Mosul",
        "ERBIL": "Erbil",
        "DUHOK": "Duhok",
        "SORAN": "Soran",
        "KIRKUK": "Kirkuk",
    }
    return city_map.get(raw.upper(), raw.title())


def _normalize_hotel_name(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "")).strip("_")
    return slug.upper() or "HOTEL"


def _parse_money(value: str) -> float:
    if value is None:
        return 0.0
    text = str(value).strip().replace("$", "").replace(",", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except Exception:
        return 0.0


def _load_legacy_team_fees() -> dict:
    path = os.path.join(config.PRICING_DIR, "hotel_tiers.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_new_hotels_bundle_from_sheet() -> dict:
    rates_values = _read_tab(config.PRICING_DB_SHEET_ID, f"{config.PRICING_DB_TABS['new_hotels']}!A1:F120")
    defaults_values = _read_tab(config.PRICING_DB_SHEET_ID, f"{config.PRICING_DB_TABS['new_hotels']}!J3:M120")
    legacy_tiers = _load_legacy_team_fees()

    hotels = []
    hotels_by_code = {}
    hotels_by_city_name = {}
    current_city = ""

    for row in rates_values[2:]:
        if not any(str(cell).strip() for cell in row):
            continue
        city_cell = row[0] if len(row) > 0 else ""
        if city_cell:
            current_city = _normalize_city_name(city_cell)
        city = current_city
        hotel_name = _normalize_hotel_name(row[1] if len(row) > 1 else "")
        if not city or not hotel_name:
            continue
        rates = [_parse_money(row[idx]) if len(row) > idx else 0.0 for idx in range(2, 6)]
        if not any(rates):
            continue
        hotel_code = _slugify(f"{city}_{hotel_name}")
        hotel = {
            "hotel_code": hotel_code,
            "hotel_name": hotel_name,
            "city": city,
            "star_level": 0,
            "currency": "USD",
            "single_rate": rates[0],
            "double_rate": rates[1],
            "twin_rate": rates[2],
            "triple_rate": rates[3],
            "active": True,
            "notes": "",
        }
        hotels.append(hotel)
        hotels_by_code[hotel_code] = hotel
        hotels_by_city_name.setdefault(city, {})[_normalize_hotel_name(hotel_name).lower()] = hotel

    defaults = {}
    for row in defaults_values:
        if not any(str(cell).strip() for cell in row):
            continue
        city = _normalize_city_name(row[0] if len(row) > 0 else "")
        if not city:
            continue
        defaults[city] = {
            "3star": _normalize_hotel_name(row[1] if len(row) > 1 else ""),
            "4star": _normalize_hotel_name(row[2] if len(row) > 2 else ""),
            "5star": _normalize_hotel_name(row[3] if len(row) > 3 else ""),
        }

    city_tier_rates = {}
    cities = set(defaults) | set(legacy_tiers)
    for city in sorted(cities):
        city_tier_rates[city] = {}
        for tier in ("3star", "4star", "5star"):
            default_name = defaults.get(city, {}).get(tier, "")
            legacy_data = legacy_tiers.get(city, {}).get(tier, {})
            matched = None
            if default_name:
                matched = hotels_by_city_name.get(city, {}).get(default_name.lower())
            if matched is None:
                legacy_default = legacy_data.get("default_hotel", "")
                if legacy_default:
                    matched = hotels_by_code.get(legacy_default)
                if matched is None and legacy_default:
                    matched = hotels_by_city_name.get(city, {}).get(_normalize_hotel_name(legacy_default).lower())

            hotel_name = ""
            hotel_code = ""
            single_rate = legacy_data.get("single", 0)
            double_rate = legacy_data.get("double", 0)
            twin_rate = 0
            triple_rate = 0
            currency = "USD"
            if matched:
                hotel_name = matched.get("hotel_name", "")
                hotel_code = matched.get("hotel_code", "")
                single_rate = matched.get("single_rate", single_rate)
                double_rate = matched.get("double_rate", double_rate)
                twin_rate = matched.get("twin_rate", 0)
                triple_rate = matched.get("triple_rate", 0)
                currency = matched.get("currency", "USD")
            elif default_name:
                hotel_name = default_name
            elif legacy_data.get("default_hotel"):
                hotel_name = legacy_data.get("default_hotel", "")

            city_tier_rates[city][tier] = {
                "single": single_rate,
                "double": double_rate,
                "team_fee": legacy_data.get("team_fee", 0),
                "default_hotel": hotel_code or hotel_name,
                "hotel_name": hotel_name,
                "currency": currency,
                "notes": legacy_data.get("review_note", ""),
                "twin": twin_rate,
                "triple": triple_rate,
            }

    return {
        "hotels": hotels,
        "defaults": defaults,
        "city_tier_rates": city_tier_rates,
    }


def upload_local_json_db_to_sheets():
    tabs = config.JSON_DB_TABS

    # general_info tab
    with open(config.GENERAL_INFO_FILE, "r", encoding="utf-8") as f:
        general_info = json.load(f)
    general_rows = [
        ["json_payload"],
        [json.dumps(general_info, ensure_ascii=False)],
    ]
    _clear_and_write_tab(config.JSON_DB_SHEET_ID, tabs["general_info"], general_rows)

    # templates tab
    header = [
        "code",
        "title",
        "city",
        "region",
        "overnight_city",
        "full_text",
        "included_sites_json",
        "pricing_tags_json",
        "active",
        "needs_review",
        "internal_notes",
    ]
    rows = [header]
    for filename in sorted(os.listdir(config.TEMPLATES_DIR)):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(config.TEMPLATES_DIR, filename)
        with open(path, "r", encoding="utf-8") as f:
            t = json.load(f)
        rows.append([
            t.get("code", ""),
            t.get("title", ""),
            t.get("city", ""),
            t.get("region", ""),
            t.get("overnight_city", ""),
            t.get("full_text", ""),
            json.dumps(t.get("included_sites", []), ensure_ascii=False),
            json.dumps(t.get("pricing_tags", []), ensure_ascii=False),
            str(bool(t.get("active", True))).lower(),
            str(bool(t.get("needs_review", False))).lower(),
            t.get("internal_notes", ""),
        ])

    _clear_and_write_tab(config.JSON_DB_SHEET_ID, tabs["templates"], rows)


def upload_local_pricing_db_to_sheets():
    tabs = config.PRICING_DB_TABS

    with open(os.path.join(config.PRICING_DIR, "settings.json"), "r", encoding="utf-8") as f:
        settings = json.load(f)
    settings_rows = [["key", "value_json"]]
    for key in sorted(settings.keys()):
        settings_rows.append([key, json.dumps(settings[key], ensure_ascii=False)])
    _clear_and_write_tab(config.PRICING_DB_SHEET_ID, tabs["settings"], settings_rows)

    with open(os.path.join(config.PRICING_DIR, "entry_tickets.json"), "r", encoding="utf-8") as f:
        entry_tickets = json.load(f)
    entry_rows = [[
        "site_code", "site_name", "city", "region", "price_per_person", "price_flat",
        "active", "needs_review", "review_note", "closed_on",
    ]]
    for r in entry_tickets:
        closed_on_val = r.get("closed_on", [])
        if not isinstance(closed_on_val, list):
            closed_on_val = []
        entry_rows.append([
            r.get("site_code", ""),
            r.get("site_name", ""),
            r.get("city", ""),
            r.get("region", ""),
            r.get("price_per_person", 0),
            r.get("price_flat", 0),
            str(bool(r.get("active", True))).lower(),
            str(bool(r.get("needs_review", False))).lower(),
            r.get("review_note", ""),
            json.dumps(closed_on_val, ensure_ascii=False) if closed_on_val else "",
        ])
    _clear_and_write_tab(config.PRICING_DB_SHEET_ID, tabs["entry_tickets"], entry_rows)

    def _upload_simple_list(filename: str, tab_name: str):
        with open(os.path.join(config.PRICING_DIR, filename), "r", encoding="utf-8") as f:
            data = json.load(f)
        headers = sorted({k for item in data for k in item.keys()})
        rows = [headers]
        for item in data:
            rows.append([item.get(h, "") for h in headers])
        _clear_and_write_tab(config.PRICING_DB_SHEET_ID, tab_name, rows)

    _upload_simple_list("transport.json", tabs["transport"])
    _upload_simple_list("guides.json", tabs["guides"])
    _upload_simple_list("extras.json", tabs["extras"])


def sync_json_db_from_sheets_to_local():
    tabs = config.JSON_DB_TABS

    # general_info
    values = _read_tab(config.JSON_DB_SHEET_ID, tabs["general_info"])
    if len(values) < 2 or len(values[1]) < 1:
        raise ValueError("general_info tab is empty or invalid")
    payload = _safe_json_load(values[1][0], {})
    with open(config.GENERAL_INFO_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # templates
    values = _read_tab(config.JSON_DB_SHEET_ID, tabs["templates"])
    if not values:
        raise ValueError("templates tab is empty")

    header = values[0]
    idx = {name: i for i, name in enumerate(header)}

    for filename in os.listdir(config.TEMPLATES_DIR):
        if filename.endswith(".json"):
            os.remove(os.path.join(config.TEMPLATES_DIR, filename))

    for row in values[1:]:
        code = row[idx["code"]].strip() if idx.get("code") is not None and len(row) > idx["code"] else ""
        if not code:
            continue
        tpl = {
            "code": code,
            "title": row[idx["title"]] if len(row) > idx.get("title", 9999) else "",
            "city": row[idx["city"]] if len(row) > idx.get("city", 9999) else "",
            "region": row[idx["region"]] if len(row) > idx.get("region", 9999) else "",
            "overnight_city": row[idx["overnight_city"]] if len(row) > idx.get("overnight_city", 9999) else "",
            "full_text": row[idx["full_text"]] if len(row) > idx.get("full_text", 9999) else "",
            "included_sites": _safe_json_load(row[idx["included_sites_json"]] if len(row) > idx.get("included_sites_json", 9999) else "[]", []),
            "pricing_tags": _safe_json_load(row[idx["pricing_tags_json"]] if len(row) > idx.get("pricing_tags_json", 9999) else "[]", []),
            "active": _to_bool(row[idx["active"]] if len(row) > idx.get("active", 9999) else True, True),
            "needs_review": _to_bool(row[idx["needs_review"]] if len(row) > idx.get("needs_review", 9999) else False, False),
            "internal_notes": row[idx["internal_notes"]] if len(row) > idx.get("internal_notes", 9999) else "",
        }
        with open(os.path.join(config.TEMPLATES_DIR, f"{code}.json"), "w", encoding="utf-8") as f:
            json.dump(tpl, f, ensure_ascii=False, indent=2)


def sync_pricing_from_sheets_to_local():
    tabs = config.PRICING_DB_TABS

    # settings
    values = _read_tab(config.PRICING_DB_SHEET_ID, tabs["settings"])
    if not values:
        raise ValueError("settings tab is empty")
    settings = {}
    for row in values[1:]:
        if len(row) < 2:
            continue
        settings[row[0]] = _safe_json_load(row[1], row[1])
    with open(os.path.join(config.PRICING_DIR, "settings.json"), "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)

    # entry_tickets
    values = _read_tab(config.PRICING_DB_SHEET_ID, tabs["entry_tickets"])
    raw_header = values[0] if values else []
    # Normalise header: lowercase + alias Code_Name → site_code
    _HEADER_ALIASES = {"code_name": "site_code"}
    header = [_HEADER_ALIASES.get(h.strip().lower(), h.strip().lower()) for h in raw_header]
    idx = {name: i for i, name in enumerate(header)}
    entry_tickets = []
    for row in values[1:]:
        if len(row) <= idx.get("site_code", 10) or not row[idx["site_code"]].strip():
            continue
        raw_closed_on = row[idx["closed_on"]] if idx.get("closed_on") is not None and len(row) > idx["closed_on"] else ""
        parsed_closed_on = _safe_json_load(raw_closed_on, [])
        if not isinstance(parsed_closed_on, list):
            parsed_closed_on = []
        # Normalise to uppercase weekday names and strip unknowns
        _VALID_DAYS = {"MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"}
        parsed_closed_on = [d.strip().upper() for d in parsed_closed_on if isinstance(d, str) and d.strip().upper() in _VALID_DAYS]
        entry_tickets.append({
            "site_code": row[idx.get("site_code", 0)] if len(row) > idx.get("site_code", 9999) else "",
            "site_name": row[idx.get("site_name", 0)] if len(row) > idx.get("site_name", 9999) else "",
            "city": row[idx.get("city", 0)] if len(row) > idx.get("city", 9999) else "",
            "region": row[idx.get("region", 0)] if len(row) > idx.get("region", 9999) else "",
            "price_per_person": _to_float(row[idx.get("price_per_person", 0)] if len(row) > idx.get("price_per_person", 9999) else 0, 0),
            "price_flat": _to_float(row[idx.get("price_flat", 0)] if len(row) > idx.get("price_flat", 9999) else 0, 0),
            "active": _to_bool(row[idx.get("active", 0)] if len(row) > idx.get("active", 9999) else True, True),
            "needs_review": _to_bool(row[idx.get("needs_review", 0)] if len(row) > idx.get("needs_review", 9999) else False, False),
            "review_note": row[idx.get("review_note", 0)] if len(row) > idx.get("review_note", 9999) else "",
            "closed_on": parsed_closed_on,
        })
    with open(os.path.join(config.PRICING_DIR, "entry_tickets.json"), "w", encoding="utf-8") as f:
        json.dump(entry_tickets, f, ensure_ascii=False, indent=2)

    new_hotels = _build_new_hotels_bundle_from_sheet()
    with open(config.NEW_HOTELS_FILE, "w", encoding="utf-8") as f:
        json.dump(new_hotels, f, ensure_ascii=False, indent=2)

    def _sync_simple_list(filename: str, tab_name: str):
        values = _read_tab(config.PRICING_DB_SHEET_ID, tab_name)
        if not values:
            data = []
        else:
            header = values[0]
            data = []
            for row in values[1:]:
                if not any(str(c).strip() for c in row):
                    continue
                item = {}
                for i, h in enumerate(header):
                    v = row[i] if i < len(row) else ""
                    if h.endswith("_usd") or h.startswith("daily_rate") or h.startswith("capacity_"):
                        try:
                            item[h] = float(v) if "." in str(v) else int(float(v))
                        except Exception:
                            item[h] = v
                    elif h == "active":
                        item[h] = _to_bool(v, True)
                    else:
                        item[h] = v
                data.append(item)
        with open(os.path.join(config.PRICING_DIR, filename), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    _sync_simple_list("transport.json", tabs["transport"])
    _sync_simple_list("guides.json", tabs["guides"])
    _sync_simple_list("extras.json", tabs["extras"])


def one_time_upload_local_databases():
    upload_local_json_db_to_sheets()
    upload_local_pricing_db_to_sheets()


def sync_all_from_sheets_to_local():
    sync_json_db_from_sheets_to_local()
    sync_pricing_from_sheets_to_local()
