"""Read explicit arrival statements from customer entry notes without a model."""
from __future__ import annotations

import re

from services.itinerary.places import normalize_place, places_in

_ARRIVAL = re.compile(
    r"\b(?:arriv(?:e|es|ed|ing|al)\b|land(?:ing|s|ed)?\s+(?:in|at)\b)", re.I)
_STATEMENT = re.compile(
    r"^(?:(?:i|we|they|the customer|the client|customer|client)\s+)?"
    r"(?:(?:will|am|are|is)\s+)?"
    r"(?:arriv(?:e|es|ing|al)|land(?:ing|s)?)\s+(?:in|at)\s+(.+)$", re.I)
_UNCERTAIN = re.compile(
    r"\b(?:not|never|no|may|might|could|maybe|perhaps|possibly|possible|"
    r"optional|option|if|unless|either|or|instead|previous|previously|old|"
    r"last|example|sample|cancelled|canceled|changed|unconfirmed)\b|[?\"“”]", re.I)


def arrival_from_entry_notes(value) -> tuple[str, list[str]]:
    """Return one explicit city, or a review warning for unresolved arrival text.

    Only a complete, affirmative arrival clause is authoritative. Generic city
    mentions, intermediate destinations, and model summaries supply no arrival.
    This is a small supported grammar, not a general conversation interpreter.
    """
    if not isinstance(value, str) or not _ARRIVAL.search(value):
        return "", []
    cities = set()
    unresolved = False
    for sentence in re.split(r"[.!;\n]+", value):
        if not _ARRIVAL.search(sentence):
            continue
        # May followed by a calendar day is a month, not an uncertain verb.
        wording = re.sub(r"\bMay\s+\d{1,2}(?:st|nd|rd|th)?\b", "[date]", sentence, flags=re.I)
        if _UNCERTAIN.search(wording):
            unresolved = True
            continue
        for clause in sentence.split(","):
            if not _ARRIVAL.search(clause):
                continue
            match = _STATEMENT.fullmatch(clause.strip())
            if not match:
                unresolved = True
                continue
            # A date or time follows the destination. It is not part of its name.
            destination = re.split(r"\s+(?:on|at)\s+", match[1], maxsplit=1, flags=re.I)[0]
            destination = re.sub(r"\s+(?:international\s+)?airport$", "", destination, flags=re.I)
            city = normalize_place(destination)
            if not city or places_in(destination) != {city}:
                unresolved = True
                continue
            cities.add(city)
    if unresolved or len(cities) != 1:
        return "", ["Confirm the arrival city in entry notes. The arrival wording is "
                    "uncertain, conflicting, or outside the supported format."]
    return cities.pop(), []
