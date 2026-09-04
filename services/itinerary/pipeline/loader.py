"""
BilWeekend — Data Loader
Loads itinerary templates and pricing data from local JSON files.
Future: when PRICING_SHEET_ID or TEMPLATES_FOLDER_ID are set in config,
        reads from Google Sheets / Google Drive instead.
"""
import json
import os
from services.itinerary.pipeline.models import DayTemplate
from services.itinerary.pipeline import config


# ── Template Loading ──────────────────────────────────────────────────────────

def load_day_template(code: str) -> DayTemplate:
    path = os.path.join(config.TEMPLATES_DIR, f"{code}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"No template file found for code '{code}': {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return DayTemplate(
        code=data["code"],
        title=data["title"],
        city=data["city"],
        region=data["region"],
        overnight_city=data.get("overnight_city", ""),
        full_text=data["full_text"],
        included_sites=data.get("included_sites", []),
        pricing_tags=data.get("pricing_tags", []),
        active=data.get("active", True),
        needs_review=data.get("needs_review", False),
        internal_notes=data.get("internal_notes", ""),
    )


def load_all_templates() -> dict:
    """Returns dict of {code: DayTemplate} for all active templates."""
    templates = {}
    if not os.path.isdir(config.TEMPLATES_DIR):
        raise FileNotFoundError(f"Templates directory not found: {config.TEMPLATES_DIR}")
    for filename in os.listdir(config.TEMPLATES_DIR):
        if not filename.endswith(".json"):
            continue
        code = filename[:-5]
        try:
            tmpl = load_day_template(code)
            templates[code] = tmpl
        except Exception as e:
            print(f"  [WARNING] Could not load template {filename}: {e}")
    return templates


# ── Pricing Loading ───────────────────────────────────────────────────────────

def _load_json(filename: str) -> any:
    path = os.path.join(config.PRICING_DIR, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Pricing file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


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


def _build_legacy_hotel_bundle() -> dict:
    hotels_payload = _load_json("hotels.json")
    hotel_tiers = _load_json("hotel_tiers.json")
    hotels = hotels_payload.get("hotels", [])

    hotels_by_code = {
        str(h.get("hotel_code", "")): h
        for h in hotels
        if h.get("hotel_code")
    }
    hotels_by_city_name = {}
    for hotel in hotels:
        city = _normalize_city_name(hotel.get("city", ""))
        name = _normalize_hotel_name(hotel.get("hotel_name", "")).lower()
        if not city or not name:
            continue
        hotels_by_city_name.setdefault(city, {})[name] = hotel

    defaults = {}
    city_tier_rates = {}
    for city, tiers in hotel_tiers.items():
        if str(city).startswith("_"):
            continue
        canon_city = _normalize_city_name(city)
        defaults.setdefault(canon_city, {})
        city_tier_rates.setdefault(canon_city, {})
        for tier, tier_data in tiers.items():
            default_hotel = str(tier_data.get("default_hotel", "") or "").strip()
            hotel_name = ""
            if default_hotel in hotels_by_code:
                hotel_name = _normalize_hotel_name(hotels_by_code[default_hotel].get("hotel_name", ""))
            else:
                matched = hotels_by_city_name.get(canon_city, {}).get(default_hotel.lower())
                if matched:
                    hotel_name = _normalize_hotel_name(matched.get("hotel_name", ""))

            defaults[canon_city][tier] = hotel_name or default_hotel
            city_tier_rates[canon_city][tier] = {
                "single": tier_data.get("single", 0),
                "double": tier_data.get("double", 0),
                "team_fee": tier_data.get("team_fee", 0),
                "default_hotel": default_hotel,
                "hotel_name": hotel_name or default_hotel,
                "currency": "USD",
                "notes": tier_data.get("review_note", ""),
            }

    return {
        "hotels": hotels,
        "defaults": defaults,
        "city_tier_rates": city_tier_rates,
        "hotels_by_city_name": hotels_by_city_name,
    }


def _load_new_hotels_bundle() -> dict:
    try:
        bundle = _load_json("new_hotels.json")
        if isinstance(bundle, dict) and bundle.get("city_tier_rates"):
            return bundle
    except FileNotFoundError:
        pass
    return _build_legacy_hotel_bundle()


def load_pricing() -> dict:
    """
    Returns a unified pricing dict with keys:
      settings, entry_tickets, hotels, hotel_tiers, hotel_defaults, transport, guides, extras
    """
    hotel_bundle = _load_new_hotels_bundle()
    pricing = {
        "settings":      _load_json("settings.json"),
        "entry_tickets": _load_json("entry_tickets.json"),
        "hotels":        hotel_bundle.get("hotels", []),
        "hotel_tiers":   hotel_bundle.get("city_tier_rates", {}),
        "hotel_defaults": hotel_bundle.get("defaults", {}),
        "new_hotels":    hotel_bundle,
        "transport":     _load_json("transport.json"),
        "guides":        _load_json("guides.json"),
        "extras":        _load_json("extras.json"),
    }
    # Normalise entry tickets: ensure every row has a closed_on list
    _VALID_DAYS = {"MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"}
    for ticket in pricing["entry_tickets"]:
        raw = ticket.get("closed_on", [])
        if not isinstance(raw, list):
            raw = []
        ticket["closed_on"] = [d.strip().upper() for d in raw if isinstance(d, str) and d.strip().upper() in _VALID_DAYS]

    # Build lookup indexes for fast access
    pricing["_tickets_by_code"] = {t["site_code"]: t for t in pricing["entry_tickets"]}
    pricing["_hotels_by_code"]  = {
        h["hotel_code"]: h for h in pricing["hotels"] if h.get("hotel_code")
    }
    pricing["_hotels_by_city_name"] = {}
    for hotel in pricing["hotels"]:
        city = _normalize_city_name(hotel.get("city", ""))
        name = _normalize_hotel_name(hotel.get("hotel_name", "")).lower()
        if not city or not name:
            continue
        pricing["_hotels_by_city_name"].setdefault(city, {})[name] = hotel
    pricing["_transport_by_code"] = {v["vehicle_code"]: v for v in pricing["transport"]}
    return pricing


def load_general_info() -> dict:
    if not os.path.exists(config.GENERAL_INFO_FILE):
        raise FileNotFoundError(f"General info file not found: {config.GENERAL_INFO_FILE}")
    with open(config.GENERAL_INFO_FILE, "r", encoding="utf-8") as f:
        return json.load(f)
