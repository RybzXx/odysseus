"""
services/itinerary/propose_sequence.py

Two proposers of a day-code sequence, behind one shape.

The rules proposer is what Operations Automation already runs: score the request
against the routes actually sold, then bind that route's days to live templates.
The model proposer reads the request and answers with codes directly.

Neither is authoritative. They run on every request and the desk shows both, so
a disagreement is a note rather than a hidden choice.

The model may name only a code the active catalogue holds. A code it invents is
dropped and recorded against the answer, because an invention is evidence about
the proposer and hiding it would waste that evidence.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from services.itinerary.binder import bind_route_to_templates
from services.itinerary.drafts import SOURCE_MODEL, SOURCE_RULES, ProposedSequence
from services.itinerary.matcher import find_best_route, load_routes, region_coverage
from services.itinerary.models import NormalizedRequest

logger = logging.getLogger(__name__)

# Long enough for a 31b model to read the catalogue and answer. Not measured.
PROPOSE_TIMEOUT_SECONDS = 120

# Below this a route match is weak, and the note says so. Carried over from the
# standalone Operations Automation project, which had it and this repository's
# own matcher did not. Without it a 0.12 match and a 1.00 match read alike.
MATCH_MIN_SCORE = 0.30

# How many sold routes go into the prompt. Chosen by nearness in day count, so
# the model sees what a trip of this length actually looks like. Enough to show
# the shape, short enough to leave room for the catalogue.
ROUTE_EXAMPLES = 4

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.S)


class ProposalError(Exception):
    """The model could not be reached, or did not answer with a usable sequence."""


def field_of(template, name: str, default: str = "") -> str:
    """
    Post: one field of a template, whichever shape it arrives in.

    The pipeline hands out DayTemplate objects and the offers catalogue hands
    out dicts. Both carry the same field names. A reader that knows only one
    shape returns the default for every field of the other, and an empty
    overnight city binds no day at all, in silence.
    """
    if isinstance(template, dict):
        value = template.get(name, default)
    else:
        value = getattr(template, name, default)
    return default if value is None else value


def active_day_templates() -> dict:
    """
    Post: {code: DayTemplate} for the templates a build can actually use.

    Read through the generation pipeline's own loader, so the desk proposes over
    exactly the vocabulary the generator can build. A separate reader would
    drift from it, and the drift would appear as a proposal that fails to
    generate.

    Inactive rows are excluded here rather than filtered later. A code the
    pipeline refuses must never reach a proposal, because the reviewer would be
    reading an itinerary that cannot be generated.
    """
    from services.itinerary.generator import load_templates
    return {code: row for code, row in load_templates().items()
            if field_of(row, "active", True)}


# ── the rules proposer ────────────────────────────────────────────────────────

def propose_by_rules(request: NormalizedRequest, templates: dict) -> ProposedSequence:
    """
    The sequence Operations Automation would produce today.

    Pre:  `templates` maps code to a live template row.
    Post: a sequence carrying the route it matched, that route's score, and any
          day the binder could not cover.

    Deterministic by design. It is the fixed second opinion a thread is read
    against, so it must answer the same way however many comments follow.
    """
    route, score = find_best_route(request)
    if route is None:
        return ProposedSequence(source=SOURCE_RULES, day_codes=[],
                                note="the route corpus is empty")

    day_codes, gap_notes = bind_route_to_templates(
        route, templates, requested_regions=list(request.requested_regions))
    coverage = region_coverage(request, route)

    parts = [f"matched {route.source_file} at {score:.2f}"]
    if score < MATCH_MIN_SCORE:
        parts.append(f"below the {MATCH_MIN_SCORE:.2f} floor, so the match is weak")
    parts.append(f"region coverage {coverage:.2f}" if coverage >= 0
                 else "no region evidence either way")
    if gap_notes:
        parts.append(f"{len(gap_notes)} day(s) not covered")
    return ProposedSequence(source=SOURCE_RULES, day_codes=list(day_codes),
                            note=". ".join(parts) + ".")


# ── the model proposer ────────────────────────────────────────────────────────

def _route_examples(day_count: int, limit: int = ROUTE_EXAMPLES) -> list:
    """
    Post: a few sold routes, nearest in length first, as city sequences.

    Cities rather than day prose: the model is choosing a shape, and a full
    offer would fill the prompt with wording it is not asked to write.
    """
    routes = list(load_routes())
    routes.sort(key=lambda r: (abs(r.day_count - day_count), r.day_count))
    return [{"days": r.day_count, "cities": r.city_sequence} for r in routes[:limit]]


def build_prompt(request: NormalizedRequest, templates: dict) -> list:
    """
    Post: the messages for one sequence, carrying the request, the codes that
          may be used, and a few routes of about this length.
    """
    catalogue = [
        f"{code} | {field_of(row, 'title')} | {field_of(row, 'city')} | "
        f"overnight: {field_of(row, 'overnight_city') or 'none'} | "
        f"{field_of(row, 'region')}"
        for code, row in sorted(templates.items())
    ]
    examples = json.dumps(_route_examples(request.day_count), ensure_ascii=False)

    system = (
        "You plan a tour by choosing day templates from a fixed catalogue.\n"
        "Answer with one JSON object and nothing else.\n\n"
        "Keys:\n"
        '  day_codes  an ordered list of codes, one per day of the tour\n'
        '  reason     one sentence on why this order\n\n'
        "Rules:\n"
        "1. Use only the codes listed below. Never invent one.\n"
        "2. Return exactly as many codes as the request asks for days.\n"
        "3. The first day should arrive and the last should depart, where the "
        "catalogue offers such a day.\n"
        "4. A day's overnight city should be reachable from the day before it.\n"
        "5. Stay inside the requested regions unless the day count forces "
        "otherwise.\n\n"
        "Codes:\n" + "\n".join(catalogue) + "\n\n"
        "Routes of about this length that were actually sold:\n" + examples
    )
    user = (
        f"Days: {request.day_count}\n"
        f"Party size: {request.pax}\n"
        f"Tour type: {request.tour_type}\n"
        f"Regions: {', '.join(request.requested_regions) or 'not stated'}\n"
        f"Hotel tier: {request.hotel_tier}\n"
        f"Notes: {'. '.join(request.special_notes) or 'none'}"
    )
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]


def parse_answer(raw: str, templates: dict) -> tuple:
    """
    Post: (day_codes, rejected_codes, reason). Every returned code is in
          `templates`; everything else is rejected and named.

    Blame: unparsable text is a model failure and raises. A code outside the
    catalogue is a model error, reported rather than dropped in silence.
    """
    match = _JSON_BLOCK_RE.search(raw or "")
    if not match:
        raise ProposalError("the model did not answer with JSON")
    try:
        answer = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ProposalError(f"the model's JSON did not parse: {exc}") from exc
    if not isinstance(answer, dict):
        raise ProposalError("the model answered with JSON that is not an object")

    asked = answer.get("day_codes") or []
    if isinstance(asked, str):
        asked = [asked]
    kept = [code for code in asked if code in templates]
    rejected = [str(code) for code in asked if code not in templates]
    return kept, rejected, str(answer.get("reason") or "").strip()


async def propose_by_model(request: NormalizedRequest, templates: dict,
                           comment: str = "", previous: Optional[list] = None,
                           owner: Optional[str] = None) -> ProposedSequence:
    """
    Ask the configured model for a sequence.

    Pre:  `templates` holds only active codes. `comment` and `previous` are the
          feedback and the answer it is about, on a second and later turn.
    Post: a sequence carrying the model's codes, whatever it invented, its
          reason, and the model and endpoint that produced it.

    Blame: an unreachable model or an unusable answer raises ProposalError. The
    desk reports it and stays usable, because a proposal is an offer.
    """
    from src.endpoint_resolver import resolve_endpoint
    from src.llm_core import llm_call_async

    url, model, headers = resolve_endpoint("default", owner=owner)
    if not url or not model:
        raise ProposalError("no model endpoint is configured")

    messages = build_prompt(request, templates)
    if comment:
        # The previous answer and the comment about it, so the model revises
        # rather than starting again and losing what the reviewer accepted.
        messages.append({"role": "assistant",
                         "content": json.dumps({"day_codes": previous or []})})
        messages.append({"role": "user", "content": comment})

    try:
        raw = await llm_call_async(url, model, messages, headers=headers,
                                   timeout=PROPOSE_TIMEOUT_SECONDS)
    except Exception as exc:
        logger.warning("sequence proposal failed on %s: %s", model, exc)
        raise ProposalError(f"the model did not answer: {exc}") from exc

    day_codes, rejected, reason = parse_answer(raw, templates)
    return ProposedSequence(
        source=SOURCE_MODEL,
        day_codes=day_codes,
        rejected_codes=rejected,
        note=reason,
        in_reply_to=comment,
        model=model,
        endpoint=url,
    )
