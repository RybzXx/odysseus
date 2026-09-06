"""
services/offers/catalogue.py

The day-template catalogue, read from data vendored into this repo.

The catalogue's master copy is the `templates` tab of the `Pricing_information`
Google Sheet; `data/templates/*.json` is a snapshot of it. Nothing here writes
to either — appends are ws-03 WP1.5, and land inactive by invariant 1.3.
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(_HERE, "data", "templates")

# ── What a catalogue row's wording looks like ────────────────────────────────
#
# A sent day carries the date it was sent for and the night it ended on. A
# catalogue row carries neither: it is used again on other dates, and the
# overnight city lives in its own column. The 28 rows already in the sheet hold
# no date and no trailer, so this is the catalogue's own convention rather than
# a preference.

_WEEKDAY = r"(?:Mon|Tues?|Wed(?:nes)?|Thur?s?|Fri|Sat(?:ur)?|Sun)(?:day)?"
_MONTH = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
          r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?"
          r"|Dec(?:ember)?)")

# The date at the head of a day, stripped as a prefix rather than by dropping
# the whole line. A heading can carry a real note beside its date, such as
# "(Lunch OR Dinner is included)", and that note is content.
_DATE_PREFIX_RE = re.compile(
    rf"^\s*(?:{_WEEKDAY}\b\s*,?\s*)?"
    rf"(?:\d{{1,2}}\s*{_MONTH}\b|{_MONTH}\b\s*\d{{0,2}})?"
    rf"\s*,?\s*\d{{0,4}}\s*,?\s*", re.I)

_OVERNIGHT_TRAILER_RE = re.compile(
    r"\s*Overnight\s*(?::\s*|\s+in\s+)[^.\n]*?(?:/\s*(?:night|Night)\s*\d+)?\s*\.?\s*$",
    re.I | re.M)

# A period does not always end a sentence. "approx." and "Intl." carry one and
# continue, and a period inside a number is no break at all. Splitting on either
# would leave half a measurement on its own line.
_ABBREVIATIONS = ("approx", "Intl", "Int", "St", "Mt", "No", "Mr", "Mrs", "Dr", "etc")
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z“\"(])")


def as_catalogue_text(day_text: str) -> str:
    """
    A sent day's wording in the form a catalogue row holds it.

    Pre:  `day_text` is one day as it was written to a client.
    Post: no date heading, no overnight trailer, one sentence on one line, and
          no run of two spaces. Every other word is exactly as it was sent.

    Blame: this changes form and never content. A caller that needs the day as
    sent reads the corpus, which is the record; this is the derivative.
    """
    lines = [line.strip() for line in (day_text or "").splitlines()]
    kept = []
    for index, line in enumerate(lines):
        if not line:
            continue
        if index == 0:
            match = _DATE_PREFIX_RE.match(line)
            if match and match.end() > 0:
                line = line[match.end():].strip()
            if not line:
                continue
        kept.append(line)

    joined = _OVERNIGHT_TRAILER_RE.sub("", "\n".join(kept))

    out = []
    for line in joined.splitlines():
        line = re.sub(r"\s{2,}", " ", line).strip()
        if not line:
            continue
        parts, buffer = [], ""
        for piece in _SENTENCE_END_RE.split(line):
            buffer = f"{buffer} {piece}".strip() if buffer else piece
            tail = buffer.rstrip(".").rsplit(" ", 1)[-1] if buffer.endswith(".") else ""
            if tail in _ABBREVIATIONS:
                continue
            parts.append(buffer)
            buffer = ""
        if buffer:
            parts.append(buffer)
        out.extend(part.strip() for part in parts if part.strip())
    return "\n".join(out)

# The 11 columns of the `templates` sheet tab, in live header order. A drafted
# template row must supply exactly these keys.
TEMPLATE_FIELDS = (
    "code", "title", "city", "region", "overnight_city", "full_text",
    "included_sites_json", "pricing_tags_json", "active", "needs_review",
    "internal_notes",
)

_cache: Optional[dict] = None


def load_templates(refresh: bool = False) -> dict:
    """
    Return {code: template dict} for every template on disk.

    Post: keys are template codes; a file whose JSON is unreadable is skipped
          rather than failing the load, because one bad row must not blind the
          whole gap analysis.
    """
    global _cache
    if _cache is not None and not refresh:
        return _cache
    templates = {}
    if os.path.isdir(TEMPLATES_DIR):
        for name in sorted(os.listdir(TEMPLATES_DIR)):
            if not name.endswith(".json"):
                continue
            path = os.path.join(TEMPLATES_DIR, name)
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (json.JSONDecodeError, OSError):
                continue
            code = data.get("code") or name[:-5]
            templates[code] = data
    _cache = templates
    return templates


def catalogue_regions(refresh: bool = False) -> list:
    """
    The regions the catalogue uses, sorted.

    Post: distinct non-empty `region` values across every template row. Today
          that is Central Iraq, Northern Iraq and Southern Iraq.

    The catalogue owns this list, so it is read here rather than typed into the
    review page. A region the sheet stops using disappears from the page on the
    next load, and a region it adds appears without a code change.
    """
    return sorted({(row.get("region") or "").strip()
                   for row in load_templates(refresh).values()
                   if (row.get("region") or "").strip()})


def load_template_texts(refresh: bool = False) -> dict:
    """Return {code: full_text} — the shape day_match.rank_templates expects."""
    return {code: (t.get("full_text") or "") for code, t in load_templates(refresh).items()}


def active_template_texts(refresh: bool = False) -> dict:
    """
    Same, restricted to templates marked active.

    Matching against inactive templates would recover codes the renderer will
    not build, so anything that feeds generation uses this rather than the
    unfiltered map.
    """
    return {code: (t.get("full_text") or "")
            for code, t in load_templates(refresh).items()
            if t.get("active", True)}
