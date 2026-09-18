"""
services/itinerary/matcher.py

Route corpus loading and multi-factor matching for customized tour requests.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

from services.itinerary.models import NormalizedRequest, RouteDay, RouteRecord

# The one city-to-region map lives in `regions`. It is re-exported here because
# `binder` and `request_brief` import it from this module, and a second copy is
# how "Western Iraq & Nineveh Plains" and "Iraqi Kurdistan" became one region
# (ws-03 phase seven, D60).
from services.itinerary.regions import CITY_REGION_MAP  # noqa: E402,F401

SCORER_WEIGHTS = {
    "region": 0.50,
    "day_count": 0.35,
    "tour_type": 0.15,
}

_ROUTES_CACHE: Optional[list[RouteRecord]] = None


def activity_text(text: str) -> str:
    """Return day activities without the offer's pricing and general information."""
    return re.split(
        r"(?im)(?:\bend of (?:the )?tour\b|\bfor the designed itinerary\b|"
        r"^\s*(?:includes?|excludes?|inclusions?|exclusions?|general information|"
        r"terms (?:and|&) conditions|price includes)\s*[:\n])", text or "", maxsplit=1)[0]


def activity_regions(days) -> set[str]:
    """Read actual visits. A city substring in another word is not a visit."""
    from services.itinerary.move_map import place_key
    regions = set()
    for day in days:
        city = place_key(day.overnight_city).lower()
        if city in CITY_REGION_MAP:
            regions.add(CITY_REGION_MAP[city])
        text = activity_text(day.text).lower()
        for city, region in CITY_REGION_MAP.items():
            if re.search(r"(?<!\w)" + re.escape(city) + r"(?!\w)", text):
                regions.add(region)
    return regions


def get_routes_path() -> str:
    here = Path(__file__).resolve().parent
    return str(here / "data" / "routes.json")


def load_routes(force_reload: bool = False) -> list[RouteRecord]:
    global _ROUTES_CACHE
    if _ROUTES_CACHE is not None and not force_reload:
        return _ROUTES_CACHE

    routes_file = get_routes_path()
    if not os.path.isfile(routes_file):
        _ROUTES_CACHE = []
        return _ROUTES_CACHE

    with open(routes_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    route_items = data.get("routes", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])

    records: list[RouteRecord] = []
    for item in route_items:
        days = [
            RouteDay(
                day=d.get("day", i + 1),
                overnight_city=d.get("overnight_city", "").strip(),
                text=d.get("text", "").strip(),
            )
            for i, d in enumerate(item.get("days", []))
        ]
        city_seq = item.get("city_sequence", [])
        region_set = activity_regions(days)

        record = RouteRecord(
            id=item.get("id", item.get("source_file", "offer")),
            source_file=item.get("source_file", "offer.docx"),
            day_count=int(item.get("day_count", len(days))),
            tour_type=item.get("tour_type", "individual"),
            city_sequence=city_seq,
            themes=item.get("themes", []),
            days=days,
            region_set=region_set,
        )
        records.append(record)

    _ROUTES_CACHE = records
    return _ROUTES_CACHE


def score_route(request: NormalizedRequest, route: RouteRecord) -> float:
    w = SCORER_WEIGHTS
    req_regions = {r.strip() for r in request.requested_regions if r.strip()}
    route_regions = {r.strip() for r in route.region_set if r.strip()}

    union = req_regions | route_regions
    region_score = (len(req_regions & route_regions) / len(union)) if union else 0.0

    span = max(request.day_count, route.day_count, 1)
    day_score = 1.0 - min(abs(request.day_count - route.day_count) / span, 1.0)

    type_score = 1.0 if request.tour_type == route.tour_type else 0.5

    return (
        w["region"] * region_score
        + w["day_count"] * day_score
        + w["tour_type"] * type_score
    )


def region_coverage(request: NormalizedRequest, route: RouteRecord) -> float:
    req_regions = {r.strip() for r in request.requested_regions if r.strip()}
    if not req_regions:
        return 1.0
    route_regions = {r.strip() for r in route.region_set if r.strip()}
    return len(req_regions & route_regions) / len(req_regions)


def find_best_route(request: NormalizedRequest, routes: Optional[list[RouteRecord]] = None) -> tuple[Optional[RouteRecord], float]:
    corpus = routes if routes is not None else load_routes()
    if not corpus:
        return None, 0.0

    best_r: Optional[RouteRecord] = None
    best_s = -1.0

    for r in corpus:
        s = score_route(request, r)
        if s > best_s:
            best_r = r
            best_s = s

    return best_r, max(best_s, 0.0)
