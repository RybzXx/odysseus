"""
curated.normalize — Sheet row -> NormalizedRequest (§2).

Reads by header name so blank/reserved columns are ignored (§2.1). Resolves the
day range and date mode; routes soft fields to notes only (§2.5, walking dropped).
"""
import re
from datetime import date

from services.curated import settings
from services.curated.models import NormalizedRequest

_MONTHS = {m.lower(): i for i, m in enumerate(
    ["", "January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"])}


def _split_multi(value: str) -> list:
    """Split a pipe-separated cell into trimmed, non-empty parts."""
    return [p.strip() for p in (value or "").split("|") if p.strip()]


def _map_regions(raw_regions: list, warnings: list) -> list:
    """
    Customize-app region names -> template-DB region names (B16/B17).

    Post: every returned name is a key the scorer/binder can compare directly
    against RouteRecord.region_set / DayTemplate.region. An unrecognized raw
    value is passed through unchanged (it will simply never match a route).
    """
    mapped = []
    for r in raw_regions:
        m = settings.REGION_NAME_MAP.get(r.strip().lower())
        if m is None:
            warnings.append(f"Unrecognized region '{r}'; left unmapped (won't match any route region).")
            mapped.append(r)
        else:
            mapped.append(m)
    return mapped


def _resolve_days(raw: str, warnings: list) -> int:
    """'7' -> 7; '5–10'/'5-10' -> min or max per settings. Defaults to 1 on junk."""
    text = (raw or "").strip()
    nums = re.findall(r"\d+", text)
    if not nums:
        warnings.append(f"Could not read day count from '{raw}'; defaulted to 1.")
        return 1
    if len(nums) == 1:
        return int(nums[0])
    lo, hi = int(nums[0]), int(nums[1])
    return min(lo, hi) if settings.DAY_RANGE_RESOLUTION == "min" else max(lo, hi)


def _resolve_date(row: dict, warnings: list):
    """
    Returns (start_date, month, year).
    Exact mode -> parsed start_date. Approximate -> month/year retained, no date.
    """
    mode = (row.get("range/exact") or "").strip().lower()
    exact = (row.get("exact date") or "").strip()
    month = (row.get("month") or "").strip()
    year = (row.get("year") or "").strip()

    if mode == "exact" and exact:
        try:
            return date.fromisoformat(exact[:10]), "", ""
        except ValueError:
            warnings.append(f"Unparseable exact date '{exact}'; treated as undated.")
    return None, month, year


def normalize_row(row: dict, row_number: int) -> NormalizedRequest:
    """
    Pre: row is a dict keyed by sheet header names (blanks ignored).
    Post: a NormalizedRequest with day_count>=1 and a valid hotel_tier/vehicle
          (unknown inputs fall back to defaults and add a parse_warning).
    """
    warnings = []
    pax = int(re.sub(r"\D", "", row.get("pax") or "") or 1)
    if pax < 1:
        warnings.append(f"pax resolved to {pax} (< 1); needs review — no valid traveller count.")
    tour_type = "individual" if pax < settings.GROUP_PAX_THRESHOLD else "group"

    hotel_raw = (row.get("hotel") or "").strip()
    hotel_tier = settings.HOTEL_TO_TIER.get(hotel_raw, "3star")
    if hotel_raw and hotel_raw not in settings.HOTEL_TO_TIER:
        warnings.append(f"Unknown hotel value '{hotel_raw}'; defaulted to 3star.")

    transport_raw = (row.get("transportation") or "").strip().lower()
    vehicle = settings.TRANSPORT_TO_VEHICLE.get(transport_raw, "SMALL_CAR")
    if transport_raw and transport_raw not in settings.TRANSPORT_TO_VEHICLE:
        warnings.append(f"Unknown transportation '{transport_raw}'; defaulted to SMALL_CAR.")

    start_date, month, year = _resolve_date(row, warnings)

    soft = []
    for label, key in (("Hotel-change", "hotelchange"), ("Climate", "heat")):
        val = (row.get(key) or "").strip()
        if val:
            soft.append(f"{label}: {val.replace('_', ' ')}")
    comments = (row.get("extra comments") or "").strip()
    if comments:
        soft.append(f"Customer comments: {comments}")

    return NormalizedRequest(
        request_id=(row.get("Customize") or "").strip(),
        row_number=row_number,
        name=(row.get("name") or "").strip(),
        pax=pax,
        day_count=_resolve_days(row.get("days"), warnings),
        tour_type=tour_type,
        hotel_tier=hotel_tier,
        vehicle=vehicle,
        regions=_map_regions(_split_multi(row.get("regions")), warnings),
        interests=_split_multi(row.get("interests")),
        start_date=start_date,
        travel_month=month,
        travel_year=year,
        soft_notes=soft,
        parse_warnings=warnings,
    )


def month_number(name: str) -> int:
    """Month name (full or 3-letter abbrev) or numeric 1..12 -> 1..12, else 0."""
    s = (name or "").strip().lower()
    if not s:
        return 0
    if s.isdigit():
        n = int(s)
        return n if 1 <= n <= 12 else 0
    if s in _MONTHS:
        return _MONTHS[s]
    return next((num for mon, num in _MONTHS.items() if mon and mon[:3] == s[:3]), 0)
