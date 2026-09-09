"""
services/itinerary/day_shape.py

Where a template's day starts, where it ends, and what job it does.

The catalogue says where a day sleeps and what it visits. It does not say where
the day sets off. `SAFA` reads "Samarra / Baghdad area" and sleeps in Baghdad,
and it truly begins in Baghdad and comes back. Read as a chain, it looks like a
transit out of Samarra.

That one missing field blocked four things at once: a check on the day's start,
a check on a skipped template, a check on a day trip used to move on, and the
binder's choice between templates that share an overnight city. Erbil holds
twelve of those and the binder could reach ten, because the words of a day and
the words of a template agree at a median of 0.250 (ws-03 phase four, 3).

39 shapes come from the catalogue. 21 came from the owner, who read each one and
gave a start and an end. Two more carry a role and no start, because their own
titles say they drive in from somewhere the catalogue does not name.

Nothing here reads a route or a sequence. It describes one template.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# What job a day does. A day has exactly one.
ROLE_ARRIVAL = "arrival"        # the customer lands, and the trip starts here
ROLE_CITY_DAY = "city_day"      # it stays in one city all day
ROLE_DAY_TRIP = "day_trip"      # it leaves the city and comes back to it
ROLE_TRANSIT = "transit"        # it starts in one city and sleeps in another
ROLE_DEPARTURE = "departure"    # the customer leaves, and the trip ends here
ROLES = (ROLE_ARRIVAL, ROLE_CITY_DAY, ROLE_DAY_TRIP, ROLE_TRANSIT, ROLE_DEPARTURE)

# Where a shape came from. A reader of a wrong shape needs to know who to ask.
SOURCE_OWNER = "owner"          # the owner read the template and said so
SOURCE_CATALOGUE = "catalogue"  # derived from overnight_city and the city chain
SOURCE_TITLE = "title"          # the title says what the chain does not

# The shapes the owner settled by hand, as (start, end, role).
#
# 21 came on 2026-09-07. On 2026-09-08 he read the 32 the catalogue derives and
# corrected six of them, and the two new templates arrived with their shapes
# stated. The other 26 derivations he confirmed, so they stay derived: a rule
# that answers 26 templates correctly should keep answering for the 27th
# (ws-03 phase seven, WP34.1).
#
# A start of None means the day carries no fixed start, and `day_start` stays
# quiet on it either way. Four carry one:
#   BB           Babylon is 44 km from Karbala and 99 km from Baghdad, and a
#                trip reaches it from either.
#   BGNJURUKNA   it sets off from Baghdad or from Karbala.
#   DaMOZKDU     sold both as a Duhok day trip and as a transit out of Mosul.
#   EBSORA       is a day trip out of Erbil, and the catalogue read its chain
#                backwards as a transit that starts in Soran.
OWNER_SETTLED_SHAPES = {
    "SAFA":      ("Baghdad", "Baghdad", ROLE_DAY_TRIP),
    "BAMaMNV":   ("Mosul", "Mosul", ROLE_DAY_TRIP),
    "BB":        (None, None, ROLE_DAY_TRIP),
    "SAMO":      ("Baghdad", "Mosul", ROLE_TRANSIT),
    "SAASMO":    ("Baghdad", "Mosul", ROLE_TRANSIT),
    "BANA":      ("Basra", "Nasiriyah", ROLE_TRANSIT),
    "MOBKHEB":   ("Mosul", "Erbil", ROLE_DEPARTURE),
    "MaMEB":     ("Mosul", "Erbil", ROLE_TRANSIT),
    "MaMJEFADU": ("Mosul", "Duhok", ROLE_TRANSIT),
    "QOLANOW":   ("Mosul", "Duhok", ROLE_TRANSIT),
    "BBKA":      ("Baghdad", "Karbala", ROLE_TRANSIT),
    "BBNJ":      ("Baghdad", "Najaf", ROLE_TRANSIT),
    "NA2BG":     ("Nasiriyah", "Baghdad", ROLE_TRANSIT),
    "URUK":      ("Karbala", "Nasiriyah", ROLE_TRANSIT),
    "URUKNA":    ("Karbala", "Nasiriyah", ROLE_TRANSIT),
    "UrukErUR":  ("Karbala", "Nasiriyah", ROLE_TRANSIT),
    "UrukNJ":    ("Nasiriyah", "Najaf", ROLE_TRANSIT),
    "EBKOSU":    ("Erbil", "Sulaymaniyah", ROLE_TRANSIT),
    "ChHkEB":    ("Soran", "Erbil", ROLE_TRANSIT),
    "SHAKSOEB":  ("Duhok", "Erbil", ROLE_TRANSIT),
    "SHAMBASO":  ("Duhok", "Korek Mountain", ROLE_TRANSIT),
    # Read on 2026-09-08, from the 32 the catalogue had derived.
    "NJ":         ("Najaf", "Najaf", ROLE_DAY_TRIP),
    "KA":         ("Karbala", "Karbala", ROLE_DAY_TRIP),
    "EBSORA":     ("Erbil", "Erbil", ROLE_DAY_TRIP),
    "BGNJURUKNA": (None, "Nasiriyah", ROLE_TRANSIT),
    "NA2BA":      ("Nasiriyah", "Basra", ROLE_TRANSIT),
    "DaMOZKDU":   (None, "Duhok", ROLE_TRANSIT),
    # The day sets off from Shush village, which `move_map` holds without a
    # coordinate. Akre is the nearest place it can measure, 71 km from Erbil,
    # and a leg the map cannot measure reports nothing at all (WP34.4).
    "SHSOKO":     ("Akre", "Korek Mountain", ROLE_TRANSIT),
    # The two templates phase seven adds.
    "BGFA":       ("Baghdad", "Baghdad", ROLE_DAY_TRIP),
    "MO1EB":      ("Mosul", "Erbil", ROLE_TRANSIT),
}

# Two templates the catalogue would read as a city day, whose own titles say
# they drive in. The role is knowable and the start is not, so the start stays
# empty and a role filter still works on them.
#
#   ArrSU  "Drive to Sulaymaniyah & Amna Suraka"
#   NA1    "Drive South & Great Ziggurat of Ur"
#
# The owner has not given a start for either. Until he does, a check on the
# day's start passes them rather than refuse a template that may be right.
ROLE_FROM_TITLE = {
    "ArrSU": ROLE_TRANSIT,
    "NA1": ROLE_TRANSIT,
}

# Words in a title that name a role the chain cannot show.
_ARRIVAL_WORDS = ("arrival", "arrive")
_DEPARTURE_WORDS = ("departure", "depart")


@dataclass
class DayShape:
    """One template's day: where it starts, where it ends, and what it does."""
    code: str
    start_city: Optional[str]    # None where the day has no fixed start
    end_city: Optional[str]      # None where the day sleeps nowhere
    role: str
    source: str

    @property
    def has_fixed_start(self) -> bool:
        return bool(self.start_city)

    @property
    def statement(self) -> str:
        start = self.start_city or "anywhere"
        end = self.end_city or "nowhere"
        return (f"{self.code}: {self.role}, {start} to {end}, "
                f"from the {self.source}")


def _chain_of(template) -> list:
    """
    Post: the places a template's `city` field names, in order, in the map's
          spelling. A name the map cannot place is left out.
    """
    from services.itinerary.move_map import resolve_place
    from services.itinerary.propose_sequence import field_of

    raw = str(field_of(template, "city", "") or "")
    places = (resolve_place(part) for part in raw.split("/"))
    return [place for place in places if place]


def _role_from_title(template) -> Optional[str]:
    """Post: the role a title states, or None where it states none."""
    from services.itinerary.propose_sequence import field_of

    title = str(field_of(template, "title", "") or "").lower()
    if any(word in title for word in _ARRIVAL_WORDS):
        return ROLE_ARRIVAL
    if any(word in title for word in _DEPARTURE_WORDS):
        return ROLE_DEPARTURE
    return None


def shape_of(code: str, template) -> DayShape:
    """
    The shape of one template's day.

    Pre:  `code` names the template and `template` is its row.
    Post: a DayShape whose `source` says where each value came from. The owner's
          21 always win, because he read the template and the catalogue did not
          record what he read.

    Order: the owner, then the title, then the catalogue. A title that says
    "Arrival" or "Departure" states a role the chain cannot show, and a chain of
    one city cannot tell an arrival from a city day.

    Blame: a wrong shape hides a template that fits, and nothing reports it.
    That is why `source` is on the record: a reader of a wrong filter can see
    whether to ask the owner or to read the catalogue row.
    """
    from services.itinerary.move_map import resolve_place
    from services.itinerary.propose_sequence import field_of

    settled = OWNER_SETTLED_SHAPES.get(code)
    if settled is not None:
        start, end, role = settled
        return DayShape(code=code, start_city=start, end_city=end,
                        role=role, source=SOURCE_OWNER)

    overnight = resolve_place(str(field_of(template, "overnight_city", "") or ""))
    chain = _chain_of(template)

    titled = _role_from_title(template)
    if code in ROLE_FROM_TITLE:
        return DayShape(code=code, start_city=None, end_city=overnight or None,
                        role=ROLE_FROM_TITLE[code], source=SOURCE_TITLE)
    if titled is not None:
        if titled == ROLE_ARRIVAL:
            start, end = overnight, overnight
        else:
            # A departure sleeps nowhere, so the last place the chain names is
            # where the customer leaves from. `SUEBDEP` runs Sulaymaniyah to
            # Erbil and flies out of Erbil.
            start = chain[0] if chain else None
            end = overnight or (chain[-1] if chain else None)
        return DayShape(code=code, start_city=start, end_city=end or None,
                        role=titled, source=SOURCE_TITLE)

    if not overnight:
        # It sleeps nowhere and no title says why. The chain's first place is
        # the best statement of where it sets off.
        return DayShape(code=code, start_city=chain[0] if chain else None,
                        end_city=chain[-1] if chain else None,
                        role=ROLE_DEPARTURE, source=SOURCE_CATALOGUE)

    if chain and chain[0] != overnight:
        return DayShape(code=code, start_city=chain[0], end_city=overnight,
                        role=ROLE_TRANSIT, source=SOURCE_CATALOGUE)

    # It starts and ends in the city it sleeps in. One place is a city day, and
    # more than one is a day trip that comes back.
    role = ROLE_DAY_TRIP if len(chain) > 1 else ROLE_CITY_DAY
    return DayShape(code=code, start_city=overnight, end_city=overnight,
                    role=role, source=SOURCE_CATALOGUE)


_SHAPES: Optional[dict] = None


def all_shapes(templates: dict, force_reload: bool = False) -> dict:
    """
    Post: {code: DayShape} for every template given.

    Pre:  `templates` maps a code to its row.

    Cached on the first call, because a sequence check asks for a shape once
    per day and the desk checks eleven drafts in one request.
    """
    global _SHAPES
    if _SHAPES is not None and not force_reload and set(_SHAPES) == set(templates):
        return _SHAPES
    _SHAPES = {code: shape_of(code, row) for code, row in templates.items()}
    return _SHAPES


def shapes_without_a_start(templates: dict) -> list:
    """
    Post: every code that carries no start city, with its role, sorted.

    A gap report. `BB` is here because the owner said it needs no start.
    `ArrSU` and `NA1` are here because nobody has given them one.
    """
    shapes = all_shapes(templates)
    return sorted((code, shapes[code].role) for code in shapes
                  if not shapes[code].has_fixed_start)


def summary(templates: dict) -> dict:
    """Post: how many shapes came from where, and how many of each role."""
    shapes = all_shapes(templates)
    by_source: dict = {}
    by_role: dict = {}
    for shape in shapes.values():
        by_source[shape.source] = by_source.get(shape.source, 0) + 1
        by_role[shape.role] = by_role.get(shape.role, 0) + 1
    return {"count": len(shapes), "by_source": by_source, "by_role": by_role,
            "without_a_start": len(shapes_without_a_start(templates))}
