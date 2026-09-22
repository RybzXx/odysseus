"""
layer2.market_note — Gemini's research note for one product.

Who buys it in Iraq, when, and on what angle to sell it. The note is internal:
it is stored on the draft for the owner, and it feeds ranking and the caption
line. It never reaches a customer directly, so no customer-text check applies;
the caption check downstream still catches anything it carries over.
"""
from __future__ import annotations

from typing import Any, Optional

from mahdawi.fedshi.models import ProductRecord
from mahdawi.layer2 import settings, voice
from mahdawi.layer2.gateway import Gateway

FIELDS = ("buyer", "season", "angle")

_TASK = """\
Research note for the product in FACTS, for selling it to Iraqi customers on
Instagram and TikTok. Answer with JSON only, no prose:
{"buyer": "<who in Iraq buys this and why, one sentence>",
 "season": "<when demand is highest in Iraq: season, occasion, or all year>",
 "angle": "<the one selling angle to lead with, one sentence>"}
Write each value in Iraqi Arabic. Use only what FACTS and general knowledge of
Iraqi households support; do not invent product specifications.
"""


def product_facts(record: ProductRecord) -> dict:
    """Post: the product facts Layer Two may use. Prices are not among them."""
    return {"title": record.title, "category": record.category,
            "description": (record.description or "")[:800],
            "colors": record.colors}


def check_note(data: Any) -> Optional[str]:
    """Post: None when data has each field as non-empty text within the size limit."""
    if not isinstance(data, dict):
        return "note is not an object"
    for f in FIELDS:
        if not isinstance(data.get(f), str) or not data[f].strip():
            return "note field %r missing or empty" % f
    if len(format_note(data)) > settings.MARKET_NOTE_MAX_CHARS:
        return "note longer than %d characters" % settings.MARKET_NOTE_MAX_CHARS
    return None


def format_note(data: dict) -> str:
    """Post: the note as three labelled lines, the form stored on the row."""
    return "المشتري: %s\nالموسم: %s\nزاوية البيع: %s" % (
        data["buyer"].strip(), data["season"].strip(), data["angle"].strip())


def write_note(gateway: Gateway, record: ProductRecord) -> str:
    """
    Post: a checked note in its stored form.
    Raises: Layer2Failure — the product waits for Layer Two.
    """
    data = gateway.complete_json(settings.MODEL_WRITER,
                                 voice.messages(_TASK, product_facts(record)),
                                 check_note)
    return format_note(data)
