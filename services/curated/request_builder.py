"""
curated.request_builder — NormalizedRequest + day-codes -> TourRequest (§6).

Starts from the pipeline's own build_default_request so every field the
generator expects is present, then overrides only what the curated request
determines. Pricing math stays entirely in the pipeline.
"""
import math
from dataclasses import replace

from services.curated.models import NormalizedRequest
from services.itinerary.pipeline.app_core import build_default_request


def _rooms(pax: int) -> tuple:
    """(single_rooms, double_rooms). Solo -> 1 single; else ceil(pax/2) doubles."""
    if pax <= 1:
        return 1, 0
    return 0, math.ceil(pax / 2)


def build_request(req: NormalizedRequest, day_codes: list, route_name: str, exchange_rate: float):
    """
    Build a TourRequest for the individual flow.

    Pre: day_codes is non-empty, every code is a valid active template, and
         exchange_rate > 0 (resolved by the caller from parameters!B1).
    Post: returned TourRequest has exchange_rate > 0 and tour_type=='individual'.
    """
    single_rooms, double_rooms = _rooms(req.pax)
    doc_name = f"{req.name} - {req.day_count} Days in Iraq" if req.name else f"{req.day_count} Days in Iraq"

    base = build_default_request(exchange_rate=exchange_rate)
    return replace(
        base,
        doc_name=doc_name,
        day_codes=day_codes,
        start_date=req.start_date,
        tour_type="individual",
        num_people=req.pax,
        single_rooms=single_rooms,
        double_rooms=double_rooms,
        hotel_tier=req.hotel_tier,
        selected_vehicle=req.vehicle,
    )
