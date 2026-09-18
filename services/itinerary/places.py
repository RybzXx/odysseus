"""Shared place spelling for itinerary inputs and outputs. Never fuzzy-match."""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

PLACE_INPUT_ALIASES = {"al-kufa": "Kufa", "ahwar": "Chibayish", "marshlands": "Chibayish",
                       "nasiriya": "Nasiriyah", "sulayma": "Sulaymaniyah"}


def normalize_place(value: str) -> str:
    """Return a canonical name, or empty for an ambiguous alternative.

    Unknown names remain visible. This does not infer a nearby destination.
    """
    return _normalize_place(str(value or ""))


@lru_cache(maxsize=2048)
def _normalize_place(value: str) -> str:
    # The spelling vocabulary is code-owned and stays fixed for this process.
    from services.offers.rule_counter import canonical_city
    from services.itinerary.move_map import resolve_place
    text = unicodedata.normalize("NFC", str(value or ""))
    text = re.sub(r"^(?:city of|overnight in|night in)\s+", "", text.strip(), flags=re.I)
    name = canonical_city(text)
    name = PLACE_INPUT_ALIASES.get(name.casefold(), name)
    return resolve_place(name) or name


@lru_cache(maxsize=1)
def _place_patterns():
    from services.itinerary.move_map import PLACE_ALIASES, PLACE_COORDINATES
    from services.itinerary.regions import CITY_REGION_MAP
    from services.offers.rule_counter import _ALIASES
    names = set(PLACE_ALIASES) | set(PLACE_COORDINATES) | set(CITY_REGION_MAP) | set(_ALIASES) | set(PLACE_INPUT_ALIASES)
    return [(normalize_place(name), re.compile(r"(?<!\w)" + re.escape(name.casefold()) + r"(?!\w)"))
            for name in names]


def places_in(text: str) -> set[str]:
    """Read complete place names and known aliases from activity prose."""
    lowered = unicodedata.normalize("NFC", text or "").casefold()
    return {name for name, pattern in _place_patterns() if pattern.search(lowered)} - {""}
