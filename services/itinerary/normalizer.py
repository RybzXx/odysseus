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

# The region names and the words customers write for them live in one module.
#
# They used to live here, folded onto the three names the catalogue modelled.
# "Western Iraq & Nineveh Plains" and "Iraqi Kurdistan" both became "Northern
# Iraq", so a request for Mosul matched an Erbil route and reported full
# coverage. `services.itinerary.regions` now holds the four the intake form
# offers (ws-03 phase seven, D60).
#
# Re-exported because `request_brief` and the tests import them from here.
from services.itinerary.regions import (  # noqa: E402,F401
    CITY_REGION_MAP,
    REGION_NAME_MAP,
    REGION_WHEN_UNSTATED,
    REGIONS,
    normalize_region_label,
)

# What the data-entry team types into a region column the submitter left blank.
# It is an empty cell, not a region, and reading it as one filtered every day
# out of ten-day trips.
_REGION_PLACEHOLDERS = {"not known", "none", "n/a", "-", "unknown", "any"}

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


# What a request may hold, before it stops describing a trip.
#
# The catalogue holds 60 active day templates and the longest sold route is far
# below that, so a request over 60 days is a misreading rather than a trip.
# `DEFAULT_GROUP_SIZES` tops out at 22 travellers, and 100 leaves room for a
# charter.
#
# The ceilings bound the request, not the reader that filled it. A record
# holding a billion days reached the candidate builder before this, and
# `tied_routes` then sorted every route by its distance from a billion
# (measured 2026-09-08).
MAX_DAY_COUNT = 60
MAX_PARTY_SIZE = 100


def _parse_int_safe(val: Any, default: int = 1, ceiling: int = MAX_PARTY_SIZE) -> int:
    """
    Post: a whole number between 1 and `ceiling`.

    Blame: a list, a dict or a boolean is not a number and answers the default.
    `str({"n": 8})` holds an 8, so a container used to read as eight.
    """
    if isinstance(val, bool) or isinstance(val, (list, tuple, set, dict)):
        return default
    if val is None or val == "":
        return default
    if isinstance(val, int):
        return min(max(val, 1), ceiling)
    m = re.search(r"\d+", str(val))
    if m:
        try:
            return min(max(int(m.group(0)), 1), ceiling)
        except ValueError:
            return default
    return default


def _resolve_day_count(val: Any) -> int:
    if isinstance(val, bool) or isinstance(val, (list, tuple, set, dict)):
        return 5
    if val is None or val == "":
        return 5
    if isinstance(val, int):
        return min(max(val, 1), MAX_DAY_COUNT)
    s = str(val).strip()
    range_match = re.search(r"(\d+)\s*[-–—to]+\s*(\d+)", s, re.IGNORECASE)
    if range_match:
        try:
            low, high = int(range_match.group(1)), int(range_match.group(2))
            return min(max(round((low + high) / 2), 1), MAX_DAY_COUNT)
        except ValueError:
            pass
    return _parse_int_safe(s, default=5, ceiling=MAX_DAY_COUNT)


def _holds_a_number(value: Any) -> bool:
    """
    Post: whether a record value gives a whole number a resolver can read.

    Emptiness is not the test. `_resolve_day_count` answers 5 for "eight" as
    well as for "", and a caller told that the record gave a value would then
    refuse a brief that read the real number (measured 2026-09-08).
    """
    if isinstance(value, bool) or isinstance(value, (list, tuple, set, dict)):
        return False
    if isinstance(value, (int, float)):
        return True
    text = str(value or "").strip()
    if not text or text.casefold() in _QUEUE_PLACEHOLDERS:
        return False
    return bool(re.search(r"\d", text))


def _names_a_region(value: Any) -> bool:
    """
    Post: whether a record value names at least one region the catalogue holds.

    `_normalize_regions` answers ["Central Iraq"] for an empty list and for a
    list of placeholders alike, so its result cannot say whether a customer
    named anything. Reading the raw value here is what tells the two apart.
    """
    if value is None:
        return False
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace(";", ",").split(",")]
    elif isinstance(value, (list, set, tuple)):
        parts = [str(p).strip() for p in value]
    else:
        return False
    return any(p and p.casefold() not in _REGION_PLACEHOLDERS for p in parts)


def defaulted_fields_of(record: dict, *, day_value: Any, pax_value: Any,
                        raw_regions: Any, date_value: Any) -> list:
    """
    Post: the names of the request fields that carry a default, because the
          record gave nothing a resolver could use.

    Pre:  each argument is the raw value the branch read out of the record,
          before any resolver ran. `raw_regions` is the record's own value and
          never the normalised list, which is never empty.

    A resolved value cannot answer this question: `_resolve_day_count` returns
    5 for an empty cell, for a placeholder and for unreadable text. A caller
    that needs to know asks here rather than guessing a column name, because a
    record shape this module was not told about would read as blank and let a
    model overwrite a real value (ws-03 D39).
    """
    defaulted = []
    if not _holds_a_number(day_value):
        defaulted.append("day_count")
    if not _holds_a_number(pax_value):
        defaulted.append("pax")
    if not _names_a_region(raw_regions):
        defaulted.append("requested_regions")
    if _parse_exact_date(date_value) is None:
        defaulted.append("start_date")
    return defaulted


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
    """
    Post: "3star", "4star" or "5star". A value the map has no word for answers
          the lowest tier, because a guess upward would price a trip the
          customer did not ask for.

    Pre:  `val` is whatever the record holds: a string, or a list of one.

    The Curated form sends `["5_star"]`. `str(["5_star"])` is `"['5_star']"`,
    which matched nothing, so every Curated request priced at three star,
    including the four-star and the five-star ones (ws-03 phase seven, WP38.1).
    """
    if isinstance(val, (list, tuple, set)):
        val = next((item for item in val if str(item).strip()), "")
    if not val:
        return "3star"
    s = str(val).strip().lower().replace("_", " ")
    return HOTEL_TIER_MAP.get(s, HOTEL_TIER_MAP.get(s.replace(" ", ""), "3star"))


def unmapped_regions(regions: list[str]) -> list[str]:
    """
    Post: the region names the catalogue has no word for.

    Pre: `regions` is the output of `_normalize_regions`, so a mapped name is
         already one of the catalogue's own.

    Blame: an unrecognised region is kept rather than dropped, and it then
    matches no route. Silence about it would read as a weak match instead of a
    request the catalogue cannot answer. The caller records it as a warning.
    """
    return [r for r in regions if r not in REGIONS]


def _normalize_regions(raw_regions: Any) -> list[str]:
    if not raw_regions:
        return [REGION_WHEN_UNSTATED]
    if isinstance(raw_regions, str):
        parts = [p.strip() for p in raw_regions.replace(";", ",").split(",") if p.strip()]
    elif isinstance(raw_regions, (list, set, tuple)):
        parts = [str(p).strip() for p in raw_regions if str(p).strip()]
    else:
        parts = []

    res: list[str] = []
    for p in parts:
        if p.strip().casefold() in _REGION_PLACEHOLDERS:
            continue
        mapped = normalize_region_label(p)
        if mapped not in res:
            res.append(mapped)
    return res or [REGION_WHEN_UNSTATED]


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


# The Curated columns that describe the trip rather than book it, and the label
# each becomes. The Queue branch has had its equivalent since phase four.
#
# Three of these were read under names the form does not send: `dietaryNeeds`,
# `heatWalkingComfort` and `hotelChangePreference` resolved to nothing on all
# five live records. `journeyTypes` was never read at all, and it is the richest
# field the form carries — four of the five records hold it, two of them with
# five values each.
#
# So the kind that needs no follow-up reached the matcher with one note, and the
# kind that does reached it with ten (ws-03 phase seven, WP38.2, WP38.3).
_CURATED_NOTE_COLUMNS = (
    ("comments", "Comments"),
    ("journeyTypes", "Interests"),
    ("journeyParameters", "Journey parameters"),
    ("transport", "Transport"),
    ("dietaryRestrictions", "Diet"),
    ("otherDietaryNeeds", "Diet"),
    ("walkingDifficulty", "Mobility/Pacing"),
    ("climateSensitivity", "Climate"),
    ("hotelChangeTolerance", "Hotel change preference"),
)


def _curated_value(data: dict, column: str) -> str:
    """
    Post: the column's text, or "" when it holds nothing a reviewer can use.

    Pre:  `data` is the submitted Curated record.

    A list becomes a comma-separated line, because the form sends `journeyTypes`
    and `transport` as lists and `str(["Food"])` is not a note anybody wants to
    read in an itinerary.
    """
    raw = data.get(column)
    if isinstance(raw, (list, tuple, set)):
        parts = [str(item).strip() for item in raw if str(item).strip()]
    else:
        parts = [str(raw).strip()] if raw is not None else []
    kept = [p for p in parts if p.casefold() not in _REGION_PLACEHOLDERS]
    return ", ".join(kept)


def normalize_curated_record(key: str, data: dict) -> NormalizedRequest:
    name = data.get("name") or "Valued Traveler"
    email = data.get("email") or None
    country_code = data.get("countryCode") or ""
    phone_raw = data.get("phone") or ""
    phone = f"{country_code} {phone_raw}".strip() if phone_raw else None

    # A graded record names its length `day_count`, because `sequence_grade`
    # writes it, not the intake form. Without this a sold eight-day trip
    # normalised to the five-day default and the rules proposed three days for
    # every graded request (measured 2026-09-07 over ten of them).
    raw_days = data.get("tripDays")
    if raw_days is None or str(raw_days).strip() == "":
        raw_days = data.get("day_count")
    raw_pax = data.get("numberOfPeople")

    pax = _parse_int_safe(raw_pax, default=2)
    day_count = _resolve_day_count(raw_days)
    tour_type = "group" if pax >= 10 else "individual"
    hotel_tier = _resolve_hotel_tier(data.get("accommodation"))
    vehicle_type = _resolve_vehicle(pax)
    raw_regions = data.get("regions")
    regions = _normalize_regions(raw_regions)

    date_mode = (data.get("travelDateMode") or "").strip().lower()
    exact_date = _parse_exact_date(data.get("exactDate")) if date_mode == "exact" else None
    travel_month = str(data.get("travelMonth") or "")
    travel_year = str(data.get("travelYear") or "")

    special_notes: list[str] = []
    for column, label in _CURATED_NOTE_COLUMNS:
        value = _curated_value(data, column)
        if value:
            special_notes.append(f"{label}: {value}")

    for region in unmapped_regions(regions):
        special_notes.append(f"Region not in the catalogue: {region}")

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
        parse_warnings=[f"the catalogue has no region called {r}"
                        for r in unmapped_regions(regions)],
        defaulted_fields=defaulted_fields_of(
            data, day_value=raw_days, pax_value=raw_pax, raw_regions=raw_regions,
            date_value=data.get("exactDate") if date_mode == "exact" else None),
        raw_record=data,
    )


# What Bil Weekend's data-entry team types into a queue column the submitter
# left blank. It carries the same absence of information as an empty cell, and
# reading it as a value puts "Not known" into an itinerary. Mirrors
# `_is_empty_value` in mcp_servers/ops_server.py, which does this for the
# worklist's own summary.
_QUEUE_PLACEHOLDERS = {"not known", "none", "n/a", "-"}


def _queue_value(record: dict, column: str) -> str:
    """Post: the column's text, or "" when it holds a placeholder."""
    raw = str(record.get(column) or "").strip()
    return "" if raw.casefold() in _QUEUE_PLACEHOLDERS else raw


# The queue columns that describe the trip rather than book it. Each becomes a
# note, so a request's own words reach the reviewer instead of being dropped.
_QUEUE_NOTE_COLUMNS = (
    ("service_type", "Service"),
    ("request_type", "Type"),
    ("trip_focus", "Focus"),
    ("additional_interests", "Interests"),
    ("dietary_restrictions", "Diet"),
    ("other_dietary_needs", "Diet"),
    ("walking_comfort", "Mobility/Pacing"),
    ("climate_sensitivity", "Climate"),
    ("hotel_change_preference", "Hotel change preference"),
    ("entry_notes", "Entry notes"),
)


def normalize_queue_record(key: str, record: dict) -> NormalizedRequest:
    name = record.get("full_name") or "Valued Traveler"
    email = record.get("customer_email") or record.get("respondent_email") or None
    phone = _queue_value(record, "phone") or None

    raw_days = _queue_value(record, "trip_days")
    raw_pax = _queue_value(record, "number_of_people")
    day_count = _resolve_day_count(record.get("trip_days"))
    # Read, not assumed. This branch used to hard-code pax 2, tier 3star and an
    # individual tour whatever the record said, so a request for one traveller
    # priced a trip for two and a group of twelve did the same. The columns are
    # there and have been all along.
    pax = _parse_int_safe(_queue_value(record, "number_of_people"), default=2)
    tour_type = "group" if pax >= 10 else "individual"
    hotel_tier = _resolve_hotel_tier(_queue_value(record, "accommodation"))
    vehicle_type = _resolve_vehicle(pax)
    regions = _normalize_regions(record.get("regions"))

    travel_date_str = str(record.get("travel_date") or "").strip()
    exact_date = _parse_exact_date(travel_date_str)
    travel_month = ""
    travel_year = ""
    if not exact_date and travel_date_str:
        travel_month = travel_date_str

    special_notes = []
    for column, label in _QUEUE_NOTE_COLUMNS:
        value = _queue_value(record, column)
        if value:
            special_notes.append(f"{label}: {value}")
    for region in unmapped_regions(regions):
        special_notes.append(f"Region not in the catalogue: {region}")

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
        parse_warnings=[f"the catalogue has no region called {r}"
                        for r in unmapped_regions(regions)],
        defaulted_fields=defaulted_fields_of(
            record, day_value=raw_days, pax_value=raw_pax,
            raw_regions=record.get("regions"), date_value=travel_date_str),
        raw_record=record,
    )


# The two request kinds, and what a caller answers when it cannot tell.
#
# A Curated request comes from a preset form and carries every field the office
# needs. A Queue request comes from a chat, and a data-entry team types what it
# can read out of a photograph. They need different work, and the desk could not
# tell them apart because the kind stopped existing after this module.
SOURCE_CURATED = "curated"
SOURCE_QUEUE = "queue"
SOURCE_UNKNOWN = "unknown"
REQUEST_SOURCES = (SOURCE_CURATED, SOURCE_QUEUE)


def request_kind(request_id: str) -> str:
    """
    Post: "curated", "queue", or "unknown" for a request id that names neither.

    Pre:  `request_id` is a draft's `request_id`, which the worklist writes as
          "curated:<id>" or "queue:<row_id>". A typed or pasted draft has none.

    Five call sites used to pass a draft's `origin` where this belongs, and
    `origin` holds "sheet" or "typed". They landed on the shape detection below
    and worked by accident: a Curated record that ever gained a `full_name` key
    would have been read as a Queue row, in silence (ws-03 phase seven, D59).
    """
    prefix = str(request_id or "").split(":", 1)[0].strip().lower()
    return prefix if prefix in REQUEST_SOURCES else SOURCE_UNKNOWN


def normalize_from_dict(key: str, data: dict, source: str = SOURCE_CURATED) -> NormalizedRequest:
    """
    Post: the record read as its kind says, or as its shape says when the kind
          is unknown.

    Pre:  `source` is one of REQUEST_SOURCES, or SOURCE_UNKNOWN. A caller that
          holds a draft passes `request_kind(draft.request_id)`.

    Blame: a caller that passes an origin gets shape detection, which is right
    for a typed request and a guess for anything else.
    """
    if source == SOURCE_QUEUE:
        return normalize_queue_record(key, data)
    if source == SOURCE_CURATED:
        return normalize_curated_record(key, data)
    # Nothing said which kind this is, so the record's own shape answers.
    if "row_id" in data or "full_name" in data:
        return normalize_queue_record(key, data)
    return normalize_curated_record(key, data)
