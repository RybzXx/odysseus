"""
services/itinerary

Odysseus Itinerary Prediction, Document Generation, and Automated Replies module.
"""
from services.itinerary.models import (
    NormalizedRequest,
    RouteDay,
    RouteRecord,
    ItineraryPreviewResult,
    ItineraryGenerationResult,
)
from services.itinerary.normalizer import (
    normalize_from_dict,
    normalize_curated_record,
    normalize_queue_record,
)
from services.itinerary.matcher import (
    load_routes,
    find_best_route,
    score_route,
    region_coverage,
)
from services.itinerary.binder import (
    bind_route_to_templates,
)
from services.itinerary.generator import (
    load_templates,
    build_tour_request,
    preview_itinerary,
    execute_generation,
)
from services.itinerary.reply_builder import (
    compose_email_reply,
    compose_whatsapp_reply,
)

__all__ = [
    "NormalizedRequest",
    "RouteDay",
    "RouteRecord",
    "ItineraryPreviewResult",
    "ItineraryGenerationResult",
    "normalize_from_dict",
    "normalize_curated_record",
    "normalize_queue_record",
    "load_routes",
    "find_best_route",
    "score_route",
    "region_coverage",
    "bind_route_to_templates",
    "load_templates",
    "build_tour_request",
    "preview_itinerary",
    "execute_generation",
    "compose_email_reply",
    "compose_whatsapp_reply",
]
