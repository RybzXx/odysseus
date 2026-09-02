"""
services/itinerary/matcher.py

Route corpus loading and multi-factor matching for customized tour requests.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from services.itinerary.models import NormalizedRequest, RouteDay, RouteRecord

CITY_REGION_MAP = {
    "baghdad": "Central Iraq",
    "samarra": "Central Iraq",
    "babylon": "Central Iraq",
    "karbala": "Central Iraq",
    "najaf": "Central Iraq",
    "kufa": "Central Iraq",
    "nasiriyah": "Southern Iraq",
    "ur": "Southern Iraq",
    "chibayish": "Southern Iraq",
    "marshes": "Southern Iraq",
    "basra": "Southern Iraq",
    "erbil": "Northern Iraq",
    "sulaymaniyah": "Northern Iraq",
    "duhok": "Northern Iraq",
    "mosul": "Northern Iraq",
    "nineveh": "Northern Iraq",
    "lalish": "Northern Iraq",
    "akre": "Northern Iraq",
    "amadiya": "Northern Iraq",
    "al qosh": "Northern Iraq",
}

SCORER_WEIGHTS = {
    "region": 0.50,
    "day_count": 0.35,
    "tour_type": 0.15,
}

_ROUTES_CACHE: Optional[list[RouteRecord]] = None


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
        region_set = set()
        for city in city_seq:
            c_norm = str(city).strip().lower()
            if c_norm in CITY_REGION_MAP:
                region_set.add(CITY_REGION_MAP[c_norm])

        all_text = " ".join(d.text.lower() for d in days)
        for c_norm, reg in CITY_REGION_MAP.items():
            if c_norm in all_text:
                region_set.add(reg)

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
