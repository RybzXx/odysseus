"""
services/itinerary/normalizer.py

Normalizes requests from Supabase (curated_requests JSONB, queue_requests flat),
Google Sheets, and manual dictionaries into canonical NormalizedRequest objects.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Optional

from services.itinerary.models import NormalizedRequest

REGION_NAME_MAP = {
    "central iraq": "Central Iraq",
    "central": "Central Iraq",
    "southern iraq": "Southern Iraq",
    "southern": "Southern Iraq",
    "south": "Southern Iraq",
    "kurdistan": "Northern Iraq",
    "northern iraq": "Northern Iraq",
    "northern iraq / kurdistan": "Northern Iraq",
    "western iraq & nineveh plains": "Northern Iraq",
    "western iraq": "Northern Iraq",
    "nineveh plains": "Northern Iraq",
}

HOTEL_TIER_MAP = {
    "3 star": "3star",
    "3star": "3star",
    "standard": "3star",
    "mid-range": "3star",
    "4 star": "4star",
    "4star": "4star",
    "comfort": "4star",
    "deluxe": "4star",
    "5 star": "5star",
    "5star": "5star",
    "luxury": "5star",
}


def _parse_int_safe(val: Any, default: int = 1) -> int:
    if val is None or val == "":
        return default
    if isinstance(val, int):
        return max(val, 1)
    m = re.search(r"\d+", str(val))
    if m:
        try:
            return max(int(m.group(0)), 1)
        except ValueError:
            return default
    return default


def _resolve_day_count(val: Any) -> int:
    if val is None or val == "":
        return 5
    if isinstance(val, int):
        return max(val, 1)
    s = str(val).strip()
    range_match = re.search(r"(\d+)\s*[-–—to]+\s*(\d+)", s, re.IGNORECASE)
    if range_match:
        try:
            low, high = int(range_match.group(1)), int(range_match.group(2))
            return max(round((low + high) / 2), 1)
        except ValueError:
            pass
    return _parse_int_safe(s, default=5)


def _resolve_vehicle(pax: int) -> str:
    if pax <= 3:
        return "SMALL_CAR"
    elif pax <= 6:
        return "VAN"
    elif pax <= 14:
        return "COASTER"
    else:
        return "VIP_BUS"


def _resolve_hotel_tier(val: Any) -> str:
    if not val:
        return "3star"
    s = str(val).strip().lower()
    return HOTEL_TIER_MAP.get(s, "3star")


def _normalize_regions(raw_regions: Any) -> list[str]:
    if not raw_regions:
        return ["Central Iraq"]
    if isinstance(raw_regions, str):
        parts = [p.strip() for p in raw_regions.replace(";", ",").split(",") if p.strip()]
    elif isinstance(raw_regions, (list, set, tuple)):
        parts = [str(p).strip() for p in raw_regions if str(p).strip()]
    else:
        parts = []

    res: list[str] = []
    for p in parts:
        mapped = REGION_NAME_MAP.get(p.lower(), p)
        if mapped not in res:
            res.append(mapped)
    return res or ["Central Iraq"]


def _parse_exact_date(val: Any) -> Optional[date]:
    if not val:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    s = str(val).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def normalize_curated_record(key: str, data: dict) -> NormalizedRequest:
    name = data.get("name") or "Valued Traveler"
    email = data.get("email") or None
    country_code = data.get("countryCode") or ""
    phone_raw = data.get("phone") or ""
    phone = f"{country_code} {phone_raw}".strip() if phone_raw else None

    pax = _parse_int_safe(data.get("numberOfPeople"), default=2)
    day_count = _resolve_day_count(data.get("tripDays"))
    tour_type = "group" if pax >= 10 else "individual"
    hotel_tier = _resolve_hotel_tier(data.get("accommodation"))
    vehicle_type = _resolve_vehicle(pax)
    regions = _normalize_regions(data.get("regions"))

    date_mode = (data.get("travelDateMode") or "").strip().lower()
    exact_date = _parse_exact_date(data.get("exactDate")) if date_mode == "exact" else None
    travel_month = str(data.get("travelMonth") or "")
    travel_year = str(data.get("travelYear") or "")

    special_notes: list[str] = []
    if data.get("comments"):
        special_notes.append(f"Comments: {data['comments']}")
    if data.get("dietaryNeeds"):
        special_notes.append(f"Diet: {data['dietaryNeeds']}")
    if data.get("heatWalkingComfort"):
        special_notes.append(f"Mobility/Pacing: {data['heatWalkingComfort']}")
    if data.get("hotelChangePreference"):
        special_notes.append(f"Hotel change preference: {data['hotelChangePreference']}")

    return NormalizedRequest(
        key=key,
        source="curated",
        customer_name=name,
        customer_email=email,
        customer_phone=phone,
        pax=pax,
        day_count=day_count,
        tour_type=tour_type,
        hotel_tier=hotel_tier,
        vehicle_type=vehicle_type,
        requested_regions=regions,
        start_date=exact_date,
        travel_month=travel_month,
        travel_year=travel_year,
        special_notes=special_notes,
        raw_record=data,
    )


def normalize_queue_record(key: str, record: dict) -> NormalizedRequest:
    name = record.get("full_name") or "Valued Traveler"
    email = record.get("customer_email") or record.get("respondent_email") or None
    phone = record.get("phone") or None

    day_count = _resolve_day_count(record.get("trip_days"))
    pax = 2
    tour_type = "individual"
    hotel_tier = "3star"
    vehicle_type = _resolve_vehicle(pax)
    regions = _normalize_regions(record.get("regions"))

    travel_date_str = str(record.get("travel_date") or "").strip()
    exact_date = _parse_exact_date(travel_date_str)
    travel_month = ""
    travel_year = ""
    if not exact_date and travel_date_str:
        travel_month = travel_date_str

    special_notes = []
    if record.get("service_type"):
        special_notes.append(f"Service: {record['service_type']}")
    if record.get("request_type"):
        special_notes.append(f"Type: {record['request_type']}")

    return NormalizedRequest(
        key=key,
        source="queue",
        customer_name=name,
        customer_email=email,
        customer_phone=phone,
        pax=pax,
        day_count=day_count,
        tour_type=tour_type,
        hotel_tier=hotel_tier,
        vehicle_type=vehicle_type,
        requested_regions=regions,
        start_date=exact_date,
        travel_month=travel_month,
        travel_year=travel_year,
        special_notes=special_notes,
        raw_record=record,
    )


def normalize_from_dict(key: str, data: dict, source: str = "curated") -> NormalizedRequest:
    if source == "queue" or "row_id" in data or "full_name" in data:
        return normalize_queue_record(key, data)
    return normalize_curated_record(key, data)
