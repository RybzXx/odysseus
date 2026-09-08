"""
services/itinerary/candidates.py

Several itineraries for one request, all built by the rules.

`find_best_route` returns the first route of the several that tie at the top
score. Phase four measured the tie at five to eleven routes and ruled a repair
out of scope, because the tie holds the larger part of the 50 percent night
accuracy.

This module does not repair it. It reads the tie the function already has, and
it treats every tied route as a candidate (ws-03 D40).

That gives a model something to choose between without letting a model invent
anything. Every day code here comes from `bind_route_to_templates`, which is
the phase four binder with its role filter and its unused-site score. A code no
active template holds cannot appear (invariant 3.6).

Each candidate carries its own check. A ranker that received the sequences and
not the faults would rank on wording.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from services.itinerary.matcher import (
    load_routes,
    region_coverage,
    score_route,
)
from services.itinerary.models import NormalizedRequest

# How close to the top score a route must sit to count as tied. Float scores
# rarely repeat exactly, and a route 0.001 below the best is the same answer
# with a rounding difference.
TIE_WIDTH = 0.02

# How many candidates one request may produce.
#
# Five. Phase four measured the exact tie at five to eleven routes. Measured
# again on 2026-09-07 with TIE_WIDTH applied, over the four live queue drafts:
# 7, 7, 14 and 20 routes tie. A ceiling of five keeps the prompt readable, and
# the order below decides which five. Spec item 19.2 records the number as open.
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
    tied_routes: int = 0            # how many tied before the ceiling applied
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
                f"tied at {self.top_score:.2f}{weak}")


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
    One candidate per tied route, each bound by the phase four binder.

    Pre:  `templates` holds only active codes, as `active_day_templates()`
          returns them.
    Post: a CandidateSet of at most `ceiling` candidates, best match first.
          Every day code names an active template. A route that binds to no day
          leaves a note in `untested` rather than an empty candidate.

    Blame: an empty corpus is a data problem and gives an empty set with a
    stated reason, not an exception. The desk stays usable, and a proposal is
    an offer rather than a promise.
    """
    found = CandidateSet()
    routes_tied, top = tied_routes(request, routes)
    found.tied_routes = len(routes_tied)
    found.top_score = top
    if not routes_tied:
        found.untested.append("the route corpus is empty, so nothing matched")
        return found

    from services.itinerary.binder import bind_route_to_templates

    for route in routes_tied:
        if len(found.candidates) >= max(ceiling, 1):
            break
        day_codes, gap_notes = bind_route_to_templates(
            route, templates, requested_regions=list(request.requested_regions))
        if not day_codes:
            found.untested.append(
                f"{route.source_file} bound to no day, so it is not a candidate")
            continue
        found.candidates.append(Candidate(
            index=len(found.candidates) + 1,
            route_id=route.id,
            route_name=route.source_file,
            route_days=route.day_count,
            match_score=score_route(request, route),
            region_coverage=region_coverage(request, route),
            asked_days=request.day_count,
            day_codes=list(day_codes),
            gap_notes=list(gap_notes),
        ))

    if found.tied_routes > len(found.candidates) + len(found.untested):
        found.untested.append(
            f"{found.tied_routes} routes tied and the ceiling is {ceiling}, so "
            f"{found.tied_routes - len(found.candidates)} were not built")
    return found


def check_candidates(found: CandidateSet, templates: dict,
                     start_date: Optional[date] = None,
                     request_row: Optional[dict] = None,
                     day_count: int = 0) -> CandidateSet:
    """
    Run the phase four checks over every candidate.

    Pre:  `request_row` is the raw submitted record. The named-pair rules read
          the regions a customer wrote, and normalisation folds the west into
          the north on purpose (ws-03 D37).
    Post: every candidate carries a SequenceCheck. Nothing is removed, whatever
          it found. A candidate with faults is still a candidate, because layer
          3 never refuses and the human is the gate (ws-03 D41, D15).
    """
    from services.itinerary.sequence_check import check_sequence

    for candidate in found.candidates:
        candidate.check = check_sequence(
            candidate.day_codes, templates, start_date=start_date,
            request_row=request_row, day_count=day_count)
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
