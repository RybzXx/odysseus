"""
services/bookings/tour_day_codes.py

Which Odysseus day templates a website tour is made of.

A tour on bilweekend.com carries its itinerary as prose — `dayLabel`, `title`,
`description`, written for a reader. Odysseus prices template codes. Nothing
mapped one to the other, so a registration could not be priced at all.

This is that map. It holds only the tours that need pricing: a
`Group Expedition` sells at a published price and never reaches here
(ws-bd D2).

A tour may carry its own `templateCodes` field, and that field wins. The map
below is the default for a tour that names none, which is every tour today
(ws-bd D4).

Read against the six tours on 2026-09-09. Five match day for day. One does not,
and `TOUR_DAY_CODES_SHORTFALL` says which and why — a reader pricing a Baghdad
day trip should know the museum is not in the quote before a customer does.
"""
from __future__ import annotations

from typing import Optional, Sequence

# Slug to day codes, in the order the tour runs them.
#
# The slug is the key, not the tour id: four tours carry an opaque id
# (`tour-mpvjhpdj`) and the slug is what a person can recognise. A renamed slug
# drops out of this map and prices nothing, which is the loud failure. Matching
# on the id instead would keep pricing a tour whose days had changed.
TOUR_DAY_CODES: dict[str, tuple[str, ...]] = {
    # The Marshes & Ur, 2 days. Ur on the way down, the Ahwar on the way back.
    "marshes-ur-2-days": ("NA1", "NA2BG"),

    # Babylon Day Trip, 1 day. `BB` is the no-overnight Babylon day.
    "babylon-day-trip": ("BB",),

    # Baghdad Day Trip, 1 day. See TOUR_DAY_CODES_SHORTFALL.
    "baghdad-day-trip": ("BG1",),

    # Central Iraq in 5 Days.
    "center-south-5-days": ("ARRBG", "BG1", "SAFA", "BB", "BG3"),

    # UNESCO World Heritage. Nine days, whatever the slug says.
    "center-north-5-days": (
        "ARRBG", "BG1", "BBNJ", "NJUkKA", "UrukErUR", "NA2BG", "SAASMO", "MO1", "MOBKHEB"),

    # The Original Tour, private. The group version of the same eight days
    # sells at a published price and is never priced here.
    "the-original-tour-private": (
        "ARRBG", "BG1", "MUCTAGKDHBG", "BBKA", "NA1", "NA2BG", "SAMO", "MOBKHEB"),
}

# Where the map is known to under-deliver, and by how much.
#
# Kept beside the map rather than in a commit message, because the person who
# reads a quote is the person who needs to know it is short.
TOUR_DAY_CODES_SHORTFALL: dict[str, str] = {
    "baghdad-day-trip": (
        "The tour sells Old Baghdad, the Iraq Museum and the Tigris on one day. "
        "`BG1` covers Old Baghdad and `BG3` covers the museum, and no single "
        "template covers both. The quote prices `BG1` alone, so the museum "
        "entry is missing from it."),
}


def day_codes_for(slug: str, tour_codes: Optional[Sequence[str]] = None) -> tuple[str, ...]:
    """
    Post: the day codes to price, in order. Empty when neither source names any.

    Pre:  `slug` is the tour's slug. `tour_codes` is the tour's own
          `templateCodes` field, or None where it carries none.

    The tour's own field wins whenever it holds anything, so an operator can
    correct a wrong default without a deploy. An empty list is not "nothing to
    price" — it is a tour that names no codes, and the map answers instead.
    """
    if tour_codes:
        return tuple(str(c).strip() for c in tour_codes if str(c).strip())
    return TOUR_DAY_CODES.get(str(slug or "").strip(), ())


def shortfall_for(slug: str) -> str:
    """
    Post: what the map does not cover for this tour, or "" when it covers it.

    Pre:  `slug` is the tour's slug.

    A caller that prices a tour must show this to whoever reads the price.
    """
    return TOUR_DAY_CODES_SHORTFALL.get(str(slug or "").strip(), "")
