"""
services/itinerary/models.py

Data models and contracts for the Odysseus Itinerary & Automated Replies service.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional


@dataclass
class NormalizedRequest:
    key: str                              # "curated:UUID" | "queue:ROW_ID" | "sheet:N"
    source: str                           # "curated" | "queue" | "sheet"
    customer_name: str
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    pax: int = 1
    day_count: int = 1
    tour_type: str = "individual"         # "individual" | "group"
    hotel_tier: str = "3star"             # "3star" | "4star" | "5star"
    vehicle_type: str = "SMALL_CAR"       # "SMALL_CAR" | "VAN" | "COASTER" | "VIP_BUS"
    requested_regions: list[str] = field(default_factory=list)
    start_date: Optional[date] = None
    travel_month: str = ""
    travel_year: str = ""
    special_notes: list[str] = field(default_factory=list)
    parse_warnings: list[str] = field(default_factory=list)
    raw_record: dict[str, Any] = field(default_factory=dict)


@dataclass
class RouteDay:
    day: int
    overnight_city: str                  # normalized city name; "" for day-trip / departure
    text: str                            # the day's narrative


@dataclass
class RouteRecord:
    id: str
    source_file: str
    day_count: int
    tour_type: str                       # "individual" | "group"
    city_sequence: list[str]
    themes: list[str]
    days: list[RouteDay]
    region_set: set[str] = field(default_factory=set)


@dataclass
class ItineraryPreviewResult:
    key: str
    matched_route_id: str
    matched_route_name: str
    confidence_score: float
    confidence_level: str                # "high" | "moderate" | "low"
    requested_day_count: int
    delivered_day_count: int
    bound_day_codes: list[str]
    coverage_gaps: list[str]
    calendar_warnings: list[str]
    estimated_quote: Optional[dict] = None
    can_generate_document: bool = False
    validation_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "matched_route_id": self.matched_route_id,
            "matched_route_name": self.matched_route_name,
            "confidence_score": round(self.confidence_score, 3),
            "confidence_level": self.confidence_level,
            "requested_day_count": self.requested_day_count,
            "delivered_day_count": self.delivered_day_count,
            "bound_day_codes": self.bound_day_codes,
            "coverage_gaps": self.coverage_gaps,
            "calendar_warnings": self.calendar_warnings,
            "estimated_quote": self.estimated_quote,
            "can_generate_document": self.can_generate_document,
            "validation_errors": self.validation_errors,
        }


@dataclass
class ItineraryGenerationResult:
    key: str
    status: str                          # "success" | "error"
    doc_id: Optional[str] = None
    doc_url: Optional[str] = None
    quote: Optional[dict] = None
    preview: Optional[ItineraryPreviewResult] = None
    draft_email: Optional[dict] = None   # {"subject": str, "body_text": str, "body_html": str}
    draft_whatsapp: Optional[str] = None
    staged_change_id: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "status": self.status,
            "doc_id": self.doc_id,
            "doc_url": self.doc_url,
            "quote": self.quote,
            "preview": self.preview.to_dict() if self.preview else None,
            "draft_email": self.draft_email,
            "draft_whatsapp": self.draft_whatsapp,
            "staged_change_id": self.staged_change_id,
            "error_message": self.error_message,
        }
