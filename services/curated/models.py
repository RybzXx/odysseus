"""
services.curated.models — Dataclasses for the curated-request flow.

NormalizedRequest : a sheet row parsed into typed generation inputs (§2).
RouteDay / RouteRecord : one extracted offer, stored as cities + prose, with
    day-codes bound at request time, not stored (design C2).
ProcessResult : the outcome written back to the sheet (§7).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class NormalizedRequest:
    request_id: str              # the cr-... id in column "Customize"
    row_number: int              # 1-based sheet row (header is row 1)
    name: str
    pax: int
    day_count: int               # range already resolved to one int (§2.3)
    tour_type: str               # "individual" | "group"
    hotel_tier: str              # "3star" | "4star" | "5star"
    vehicle: str                 # vehicle_code
    regions: list                # customize region names
    interests: list              # theme names (stored; unused by v1 scorer)
    start_date: Optional[date]   # set only when date mode == "exact" (§2.4)
    travel_month: str            # "" unless approximate
    travel_year: str             # "" unless approximate
    soft_notes: list = field(default_factory=list)   # heat/hotelchange/diet/comments (§2.5)
    parse_warnings: list = field(default_factory=list)


@dataclass
class RouteDay:
    day: int
    overnight_city: str          # normalized; "" for day-trip / departure days
    text: str                    # the day's prose


@dataclass
class RouteRecord:
    id: str                      # slug of source file
    source_file: str
    day_count: int
    tour_type: str               # "individual" | "group"
    city_sequence: list          # ordered overnight cities (normalized)
    themes: list                 # populated later by the LLM seam; empty in v1
    days: list                   # list[RouteDay]
    region_set: set = field(default_factory=set)     # derived at load from templates


@dataclass
class ProcessResult:
    request_id: str
    status: str
    doc_link: str
    matched_route: str
    confidence: str
    notes: list
    processed_at: str
