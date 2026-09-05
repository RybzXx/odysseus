"""
services/offers/suggest_row.py

Asks a model for the catalogue columns a drafted proposal leaves empty.

A proposal carries eleven columns and the analysis fills three of them. The
reviewer sets the code, the region and the overnight city. Four are left blank,
and a row written with them blank builds into an itinerary and prices at zero:
`title`, `city`, `included_sites_json` and `pricing_tags_json`.

The model is asked for four things and nothing else: title, city, included
sites, and a cleaned wording. It never decides. Its answer lands in the
proposal's `suggested` block, marked as machine text, and only the reviewer's
accept moves a value into `fields`.

Pricing tags are not asked for. Canon carries `guide_day` on 28 of 28 rows,
`transport_day` on 28 of 28, and `hotel_night` on 26 of 28 — the two without it
are the two with no overnight city. That is a rule, and asking a model for a
rule only adds a way to be wrong.

Invariant 1.4 forbade any model over this corpus. The owner lifted it on
2026-09-05, knowing that a cleaned wording is no longer a verbatim sent day and
that the day text carries client names, dates and prices to wherever the
configured model runs.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from services.offers.catalogue import catalogue_regions, load_templates

logger = logging.getLogger(__name__)

# Long enough for a 31b model to read one day and answer. Not yet measured
# against the configured endpoint.
SUGGEST_TIMEOUT_SECONDS = 120

CONFIDENCE_HIGH = "high"
CONFIDENCE_LOW = "low"

# How many canon rows go into the prompt as the style reference. Enough to show
# the shape of a title and the size of a site list, short enough to leave room
# for the day itself.
CANON_EXAMPLES = 6

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.S)


class SuggestionError(Exception):
    """The model could not be reached, or did not answer with a usable row."""


def pricing_tags_for(overnight_city: str) -> list:
    """
    The pricing tags a day carries, by rule rather than by judgement.

    Post: ["guide_day", "transport_day"], plus "hotel_night" when the day ends
          somewhere.

    Blame: a disagreement with canon is a defect here. The rule reproduces all
    28 catalogue rows exactly, and a test holds it to that.
    """
    tags = ["guide_day", "transport_day"]
    if (overnight_city or "").strip():
        tags.append("hotel_night")
    return tags


def known_site_codes() -> dict:
    """
    Post: {site_code: {"name", "city", "region"}} for every active entry ticket.

    The catalogue references these codes and the pricing pass reads them, so the
    model may choose from them and may not invent one.
    """
    from services.itinerary.pipeline import config

    path = config.__dict__.get("ENTRY_TICKETS_FILE")
    if not path:
        import os
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "offers", "data", "pricing", "entry_tickets.json")
    try:
        with open(path, encoding="utf-8") as fh:
            rows = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    return {row["site_code"]: {"name": row.get("site_name", ""),
                               "city": row.get("city", ""),
                               "region": row.get("region", "")}
            for row in rows
            if row.get("site_code") and row.get("active", True)}


def _canon_examples(limit: int = CANON_EXAMPLES) -> list:
    """Post: a few catalogue rows, shortest first, as the style to match."""
    rows = [r for r in load_templates().values() if (r.get("title") or "").strip()]
    rows.sort(key=lambda r: len(r.get("full_text") or ""))
    return [{"title": r.get("title", ""),
             "city": r.get("city", ""),
             "included_sites": r.get("included_sites") or [],
             "full_text": r.get("full_text", "")}
            for r in rows[:limit]]


def build_prompt(day_text: str, overnight_city: str = "") -> list:
    """
    Post: the messages for one suggestion, carrying the day, the catalogue rows
          that set the style, and the two closed lists the answer must use.

    The lists are in the prompt so the model chooses from them. They are checked
    again on the way back, because a prompt is a request and not a guarantee.
    """
    sites = known_site_codes()
    site_lines = [f"{code} = {meta['name']} ({meta['city']}, {meta['region']})"
                  for code, meta in sorted(sites.items())]
    examples = json.dumps(_canon_examples(), ensure_ascii=False, indent=2)

    system = (
        "You complete rows for a tour operator's day-template catalogue.\n"
        "Answer with one JSON object and nothing else.\n\n"
        "Keys:\n"
        '  title           a short name for the day, in the style of the examples\n'
        '  city            the places the day covers, as the examples write them\n'
        '  included_sites  a list of site codes taken ONLY from the list below\n'
        '  cleaned_text    the day text with grammar, spacing and line breaks corrected\n'
        '  confidence      {"title": "high"|"low", "city": ..., "included_sites": ...}\n\n'
        "Rules:\n"
        "1. cleaned_text corrects only form. Add no place, price, time or fact "
        "that the day text does not already state, and remove none.\n"
        "2. If the day text is already correct, return it unchanged.\n"
        "3. Use a site code only when the day clearly visits that site.\n"
        "4. Never invent a site code.\n"
        "5. Mark a field low when you are unsure. Answer it anyway.\n\n"
        f"Regions in use: {', '.join(catalogue_regions()) or 'none'}\n\n"
        "Site codes:\n" + "\n".join(site_lines) + "\n\n"
        "Catalogue rows for style:\n" + examples
    )
    user = (f"Overnight city: {overnight_city or '(none)'}\n\n"
            f"Day text:\n{day_text}")
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]


def parse_answer(raw: str, day_text: str, overnight_city: str = "") -> dict:
    """
    Turn a model's reply into a suggestion, keeping only what it is allowed to say.

    Pre:  `raw` is the model's text. `day_text` is the wording it was given.
    Post: {"title", "city", "included_sites", "pricing_tags", "cleaned_text",
           "confidence", "dropped"}. `dropped` names every site code the model
           invented, so a silent invention becomes a visible one.

    Blame: unparsable text is a model failure and raises. A site code outside
    the catalogue is a model error, reported rather than stored.
    """
    match = _JSON_BLOCK_RE.search(raw or "")
    if not match:
        raise SuggestionError("the model did not answer with JSON")
    try:
        answer = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise SuggestionError(f"the model's JSON did not parse: {exc}") from exc
    if not isinstance(answer, dict):
        raise SuggestionError("the model answered with JSON that is not an object")

    known = known_site_codes()
    asked = answer.get("included_sites") or []
    if isinstance(asked, str):
        asked = [asked]
    sites = [code for code in asked if code in known]
    dropped = [str(code) for code in asked if code not in known]

    confidence = answer.get("confidence")
    if not isinstance(confidence, dict):
        confidence = {}

    cleaned = answer.get("cleaned_text")
    if not isinstance(cleaned, str) or not cleaned.strip():
        cleaned = day_text

    return {
        "title": str(answer.get("title") or "").strip(),
        "city": str(answer.get("city") or "").strip(),
        "included_sites": sites,
        # Never from the model. The rule reproduces canon exactly.
        "pricing_tags": pricing_tags_for(overnight_city),
        "cleaned_text": cleaned,
        "confidence": {key: (CONFIDENCE_LOW if str(confidence.get(key, "")).lower() == "low"
                             else CONFIDENCE_HIGH)
                       for key in ("title", "city", "included_sites")},
        "dropped_sites": dropped,
    }


async def suggest_catalogue_row(day_text: str, overnight_city: str = "",
                                owner: Optional[str] = None) -> dict:
    """
    Ask the configured model to complete one row.

    Pre:  `day_text` is the wording the reviewer is judging.
    Post: the parsed suggestion, plus the model and endpoint that produced it
          and the moment it ran. A caller stores it as machine text and never
          merges it into a proposal's fields.

    Blame: an unreachable model or an unusable answer raises SuggestionError.
    The card reports it and stays usable, because a suggestion is an offer and
    never a requirement.
    """
    from src.endpoint_resolver import resolve_endpoint
    from src.llm_core import llm_call_async

    url, model, headers = resolve_endpoint("default", owner=owner)
    if not url or not model:
        raise SuggestionError("no model endpoint is configured")

    try:
        raw = await llm_call_async(
            url, model, build_prompt(day_text, overnight_city),
            headers=headers, timeout=SUGGEST_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.warning("suggestion call failed on %s: %s", model, exc)
        raise SuggestionError(f"the model did not answer: {exc}") from exc

    suggestion = parse_answer(raw, day_text, overnight_city)
    suggestion["model"] = model
    suggestion["endpoint"] = url
    suggestion["suggested_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return suggestion
