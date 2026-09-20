"""Bind and check every historical route before ranking distinct candidates.

Validation and request coverage outrank historical text similarity.
The display ceiling never limits the route search.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from services.itinerary.matcher import (
    load_routes,
    score_route,
)
from services.itinerary.models import NormalizedRequest

# How close to the top score a route must sit to count as tied. Float scores
# rarely repeat exactly, and a route 0.001 below the best is the same answer
# with a rounding difference.
TIE_WIDTH = 0.02

# Maximum distinct candidates to display after all routes have been checked.
CANDIDATE_CEILING = 5


@dataclass
class Candidate:
    """One itinerary the rules produced, and what the checks found in it."""
    index: int                      # 1-based, as the ranker names it
    route_id: str
    route_name: str                 # the source file, which is how a route is named
    route_days: int
    match_score: float
    region_coverage: float
    asked_days: int = 0             # what the customer asked for
    day_codes: list = field(default_factory=list)
    gap_notes: list = field(default_factory=list)
    check: Optional[object] = None  # SequenceCheck, set by check_candidates
    plan: Optional[object] = None

    @property
    def fault_count(self) -> int:
        return len(getattr(self.check, "faults", []) or [])

    @property
    def flag_count(self) -> int:
        return len(getattr(self.check, "flags", []) or [])

    @property
    def day_shortfall(self) -> int:
        """
        Post: how many days short of the request this candidate is, or 0.

        Carried on the candidate because a ranker that sees faults alone would
        take a one-day itinerary for a four-day request: it repeats nothing, so
        it has no faults. Measured on 2026-09-07 over the four live queue
        drafts, where candidates delivered 1 to 7 days against 4 and 10 asked.
        """
        if not self.asked_days:
            return 0
        return max(self.asked_days - len(self.day_codes), 0)

    @property
    def statement(self) -> str:
        short = (f", {self.day_shortfall} day(s) short"
                 if self.day_shortfall else "")
        return (f"{len(self.day_codes)} day(s) from {self.route_name} at "
                f"{self.match_score:.2f}, {self.fault_count} fault(s), "
                f"{self.flag_count} flag(s){short}")


@dataclass
class CandidateSet:
    """Every candidate for one request, and why there are that many."""
    candidates: list = field(default_factory=list)
    tied_routes: int = 0            # historical routes evaluated (legacy API field name)
    top_score: float = 0.0
    untested: list = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.candidates

    @property
    def spread(self) -> dict:
        """
        Post: how far apart the candidates are, by fault and by flag.

        A spread of zero says the ranker is choosing between equals, which is
        the measurement that decides whether layer 2 earns its place (spec
        item 14.7).
        """
        if not self.candidates:
            return {"faults": [], "flags": [], "days": [], "differ": False}
        faults = [c.fault_count for c in self.candidates]
        flags = [c.flag_count for c in self.candidates]
        days = [len(c.day_codes) for c in self.candidates]
        return {"faults": faults, "flags": flags, "days": days,
                "differ": (len(set(faults)) > 1 or len(set(flags)) > 1
                           or len(set(days)) > 1)}

    @property
    def is_weak_match(self) -> bool:
        """
        Post: whether the best route scores below the floor the rules use.

        `propose_by_rules` says "below the 0.30 floor, so the match is weak"
        and the candidate path said nothing, so a proposal built on a 0.18
        match read like one built on 0.83.
        """
        from services.itinerary.propose_sequence import MATCH_MIN_SCORE

        # The score is what is weak, not the candidate list. A set that built
        # nothing from a 0.18 match is the weakest case there is.
        return self.tied_routes > 0 and self.top_score < MATCH_MIN_SCORE

    @property
    def statement(self) -> str:
        from services.itinerary.propose_sequence import MATCH_MIN_SCORE

        weak = (f", below the {MATCH_MIN_SCORE:.2f} floor, so the match is weak"
                if self.is_weak_match else "")
        return (f"{len(self.candidates)} candidate(s) of {self.tied_routes} "
                f"historical routes evaluated; best historical score {self.top_score:.2f}{weak}")


def tied_routes(request: NormalizedRequest, routes: Optional[list] = None,
                width: float = TIE_WIDTH) -> tuple:
    """
    The routes that tie at the top match score.

    Pre:  `request` is normalized. `routes` is the corpus, or None to load it.
    Post: (routes, top score), best first, every route within `width` of the
          best. An empty corpus gives ([], 0.0).
    Inv:  `score_route` is untouched. This reads the scores it already gives
          (spec item 19.7).

    Blame: a caller that wants one route calls `find_best_route`, which is
    unchanged and still returns the first of these.
    """
    corpus = routes if routes is not None else load_routes()
    if not corpus:
        return [], 0.0

    scored = [(score_route(request, route), route) for route in corpus]
    top = max((score for score, _ in scored), default=0.0)
    top = max(top, 0.0)
    tied = [(score, route) for score, route in scored if score >= top - width]

    # Nearest in length first, and the score decides the rest. `score_route`
    # weights day count at 0.35 against region at 0.50, so a route half the
    # asked length ties with one of the right length whenever the regions
    # match. Ordering the tie by length puts the candidates a customer could
    # actually be sold in front of the ceiling. `_route_examples` already
    # orders the model's examples this way.
    tied.sort(key=lambda pair: (abs(pair[1].day_count - request.day_count),
                                -pair[0], pair[1].source_file))
    return [route for _, route in tied], top


def build_candidates(request: NormalizedRequest, templates: dict,
                     routes: Optional[list] = None,
                     ceiling: int = CANDIDATE_CEILING) -> CandidateSet:
    """
    Evaluate every historical route, then display the strongest distinct bindings.

    Pre:  `templates` holds only active codes, as `active_day_templates()`
          returns them.
    Post: a CandidateSet of at most `ceiling` candidates, best match first.
          Every day code names an active template. A route that binds to no day
          leaves a note in `untested` rather than an empty candidate.

    Blame: an empty corpus is a data problem and gives an empty set with a
    stated reason, not an exception. The desk stays usable, and a proposal is
    an offer rather than a promise.
    """
    from services.itinerary.binder import bind_route_to_templates
    from services.itinerary.sequence_check import check_sequence
    from services.itinerary.regions import sequence_regions
    from services.itinerary.resolved_plan import resolve_plan

    found = CandidateSet()
    corpus = list(load_routes() if routes is None else routes)
    if not corpus:
        found.untested.append("The route corpus is empty.")
        return found
    found.tied_routes = len(corpus)
    found.top_score = max(score_route(request, route) for route in corpus)
    for route in sorted(corpus, key=lambda r: (r.source_file, r.id)):
        codes, gaps = bind_route_to_templates(route, templates, request.requested_regions)
        if not codes:
            if not found.untested:
                found.untested.append(f"{route.source_file} bound to no day. " + "; ".join(gaps))
            continue
        coverage = sequence_regions(codes, templates)
        requested = set(request.requested_regions)
        plan = resolve_plan(codes, templates, request, route)
        check = check_sequence(codes, templates, start_date=request.start_date,
                               normalized_request=request, plan=plan)
        found.candidates.append(Candidate(
            index=0, route_id=route.id, route_name=route.source_file,
            route_days=route.day_count, match_score=score_route(request, route),
            region_coverage=len(requested & coverage) / len(requested) if requested else 1.0,
            asked_days=request.day_count, day_codes=codes, gap_notes=gaps, check=check, plan=plan))
    # Respect fixed endpoints even when every candidate still needs repair.
    # The ceiling limits display only; a wrong starting city cannot hide the
    # available routes that start where the customer arrives.
    found.candidates.sort(key=lambda c: (
        not c.check.is_clean, len(c.check.of_kind("required_endpoint")),
        not c.check.found_no_fault,
        abs(c.asked_days - len(c.day_codes)), c.fault_count,
        len(c.check.untested), -c.region_coverage, c.flag_count,
        -c.match_score, c.route_name, c.route_id, tuple(c.day_codes)))
    unique = []
    seen = set()
    for candidate in found.candidates:
        signature = tuple(candidate.day_codes)
        if signature in seen:
            continue
        seen.add(signature)
        candidate.index = len(unique) + 1
        unique.append(candidate)
        if len(unique) >= max(ceiling, 1):
            break
    found.candidates = unique
    if not any(c.check.is_clean for c in unique):
        found.untested.append(
            f"No fully validated itinerary after checking all {len(corpus)} historical routes. "
            "Review the candidate gaps, missing requirements, and unresolved checks.")
    return found


def check_candidates(found: CandidateSet, templates: dict,
                     start_date: Optional[date] = None,
                     request_row: Optional[dict] = None,
                     day_count: int = 0, normalized_request=None) -> CandidateSet:
    """Refresh candidate checks against the exact normalized request.

    Post: incomplete candidates remain available for diagnosis. The caller must
    select only a candidate whose check is clean.
    """
    from services.itinerary.sequence_check import check_sequence

    for candidate in found.candidates:
        candidate.check = check_sequence(
            candidate.day_codes, templates, start_date=start_date,
            request_row=request_row, day_count=day_count or candidate.asked_days,
            normalized_request=normalized_request, plan=candidate.plan)
    return found


def candidate_to_dict(candidate: Candidate) -> dict:
    """One candidate as a reader over HTTP receives it, check and all."""
    from services.itinerary.sequence_check import check_to_dict

    return {
        "index": candidate.index,
        "route_id": candidate.route_id,
        "route_name": candidate.route_name,
        "route_days": candidate.route_days,
        "match_score": round(candidate.match_score, 4),
        "region_coverage": round(candidate.region_coverage, 4),
        "asked_days": candidate.asked_days,
        "day_shortfall": candidate.day_shortfall,
        "day_codes": list(candidate.day_codes),
        "gap_notes": list(candidate.gap_notes),
        "statement": candidate.statement,
        "check": check_to_dict(candidate.check) if candidate.check else None,
        "plan": candidate.plan.to_dict() if candidate.plan else None,
    }


def candidate_set_to_dict(found: CandidateSet) -> dict:
    """The whole set as a reader over HTTP receives it."""
    return {
        "candidates": [candidate_to_dict(c) for c in found.candidates],
        "count": len(found.candidates),
        "tied_routes": found.tied_routes,
        "top_score": round(found.top_score, 4),
        "is_weak_match": found.is_weak_match,
        "ceiling": CANDIDATE_CEILING,
        "spread": found.spread,
        "untested": list(found.untested),
        "statement": found.statement,
    }
