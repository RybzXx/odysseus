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
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(_HERE, "data", "templates")

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
