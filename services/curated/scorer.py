"""
curated.scorer — Match a request to a route (§4, design B1).

score() is a single pure function so the rules-based body can later be swapped
for a Gemini-Flash-Lite call without touching callers (the B1->B3 seam, §8.5).
Themes carry zero weight in v1 (decision D).
"""
from services.curated import settings
from services.curated.models import NormalizedRequest, RouteRecord


def score(request: NormalizedRequest, route: RouteRecord) -> float:
    """
    Weighted overlap in [0, 1] across region coverage, day-count proximity,
    and tour-type. Higher is better.

    Pre: request.day_count >= 1.
    Post: 0.0 <= return <= 1.0.
    """
    w = settings.SCORER_WEIGHTS

    req_regions = {r.strip().lower() for r in request.regions if r.strip()}
    route_regions = {r.strip().lower() for r in route.region_set if r.strip()}
    # Jaccard, not recall: a route that also touches unrequested regions (e.g.
    # a Mosul overnight on a Central+Southern request) must score lower than
    # one that stays inside the requested regions, even with identical overlap
    # (B17 — recall-only let "covers everything requested, plus extras" win).
    union = req_regions | route_regions
    region_score = (len(req_regions & route_regions) / len(union)) if union else 0.0

    span = max(request.day_count, route.day_count, 1)
    day_score = 1.0 - min(abs(request.day_count - route.day_count) / span, 1.0)

    type_score = 1.0 if request.tour_type == route.tour_type else 0.0

    return (w["region"] * region_score
            + w["day_count"] * day_score
            + w["tour_type"] * type_score)


def region_coverage(request: NormalizedRequest, route: RouteRecord) -> float:
    """
    Fraction of requested regions the route covers, in [0, 1].

    Returns -1.0 when the request names no regions, so the caller can tell
    "no region evidence either way" apart from "zero overlap" (§B4).
    """
    req_regions = {r.strip().lower() for r in request.regions if r.strip()}
    if not req_regions:
        return -1.0
    route_regions = {r.strip().lower() for r in route.region_set if r.strip()}
    return len(req_regions & route_regions) / len(req_regions)


def best_match(request: NormalizedRequest, routes: list) -> tuple:
    """
    Return (best_route, best_score). (None, 0.0) if the corpus is empty.

    Post: best_score is the maximum score over routes; caller compares it to
    settings.MATCH_MIN_SCORE to decide confidence (§4.3).
    """
    best_route, best_score = None, 0.0
    for route in routes:
        s = score(request, route)
        if s > best_score or best_route is None:
            best_route, best_score = route, s
    return best_route, best_score
