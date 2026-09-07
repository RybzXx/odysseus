"""
services/itinerary/move_map.py

Which cities the work joins, how far apart they are, and what sits between them.

The desk knew one overnight city per code and nothing else about geography. That
is enough to bind a day and not enough to judge a sequence: it cannot say that a
car does not drive Mosul to Sulaymaniyah, and it cannot say that Erbil is what
belongs between them.

Two sources answer that, and neither answers it alone.

  The corpus says which pairs the work has really joined, and how often. It is
  measured, it needs no map, and it carries the road facts nobody wrote down.
  Mosul to Sulaymaniyah is 288 km of road and the corpus joins it zero times,
  because the short road runs through Kirkuk and a foreign group cannot use it.

  Distance says how far, and which city lies on the way. It knows nothing about
  a checkpoint, a permit or a closed road, so it is never asked whether a leg is
  allowed. It is asked only how long an allowed leg is.

So: the corpus decides whether a move exists, and distance decides what it
costs. A map built the other way round passes Mosul to Sulaymaniyah, which is
the fault this module was written to catch.

Nothing here reads a template or a day code. It speaks about cities. The caller
turns a code into a city, and `sequence_check` is that caller.
"""
from __future__ import annotations

import heapq
import math
from collections import Counter
from dataclasses import dataclass
from typing import Optional

# Where each place is. Latitude and longitude, in degrees.
#
# Entered by hand from general geographic knowledge, then checked against six
# measured road distances: Baghdad-Mosul 408 against 410, Karbala-Najaf 86
# against 76, Baghdad-Karbala 97 against 112, Najaf-Basra 422 against 371,
# Baghdad-Erbil 370 against 312, Mosul-Sulaymaniyah 260 against 288. The model
# runs about 20 percent either way, which is a ceiling and not a schedule.
#
# A place the corpus names and this table does not hold reads as unknown rather
# than as far away, because a guessed coordinate would produce a confident wrong
# distance. Five such names stand today: Rezan (14 nights), Serzan (7), Shush
# Village (2), Choman Glamping (2), and Rawanduz, which is here. Three more are
# parse noise rather than places: "Over", "Homestay", "Wherever suits you".
PLACE_COORDINATES = {
    # the twelve cities that carry a night
    "Baghdad": (33.315, 44.366),
    "Mosul": (36.335, 43.119),
    "Erbil": (36.191, 44.009),
    "Duhok": (36.867, 42.988),
    "Sulaymaniyah": (35.561, 45.437),
    "Najaf": (32.000, 44.335),
    "Karbala": (32.616, 44.024),
    "Nasiriyah": (31.043, 46.259),
    "Basra": (30.508, 47.783),
    "Soran": (36.653, 44.545),
    "Korek Mountain": (36.660, 44.450),
    "Chibayish": (30.966, 46.965),
    # places a day passes through, which no template uses as an overnight
    "Samarra": (34.198, 43.874),
    "Babylon": (32.542, 44.421),
    "Samawa": (31.332, 45.283),
    "Uruk": (31.322, 45.638),
    "Ur": (30.963, 46.103),
    "Qurna": (31.008, 47.437),
    "Hatra": (35.588, 42.718),
    "Ashur": (35.457, 43.263),
    "Bashiqa": (36.457, 43.376),
    "Bakhdida": (36.271, 43.378),
    "Alqosh": (36.737, 43.093),
    "Lalish": (36.770, 43.310),
    "Akre": (36.741, 43.887),
    "Amedi": (37.090, 43.490),
    "Zakho": (37.144, 42.682),
    "Barzan": (36.920, 44.160),
    "Choman": (36.630, 44.900),
    "Rawanduz": (36.608, 44.530),
    "Koya": (36.083, 44.628),
    "Halabja": (35.178, 45.986),
    "Salman Pak": (33.100, 44.590),
    "Nimrud": (36.098, 43.328),
    "Jerwan": (36.780, 43.400),
    "Zubair": (30.393, 47.708),
    "Kirkuk": (35.468, 44.392),
}

# One place, spelled as each source spells it.
#
# Four sources name a place and none of them agrees with the others. The corpus
# says "Chibayish", the ticket index says "Chibayesh", the catalogue says
# "Chibayesh" too, and `binder` carries a fourth list of its own. A place that
# reads as two places is two nights that never join, and a site that is missed
# on the way.
#
# The key is lower case, so a caller does not have to know which source it holds.
PLACE_ALIASES = {
    "baashiqa": "Bashiqa",
    "bashiqa": "Bashiqa",
    "chibayesh": "Chibayish",
    "chibaish": "Chibayish",
    "al-chibayish": "Chibayish",
    "ahwar": "Chibayish",
    "marshes": "Chibayish",
    "marshlands": "Chibayish",
    "suli": "Sulaymaniyah",
    "sulimaniyah": "Sulaymaniyah",
    "sulaimani": "Sulaymaniyah",
    "sulaymaniya": "Sulaymaniyah",
    "suleymaniyah": "Sulaymaniyah",
    "qosh": "Alqosh",
    "al qosh": "Alqosh",
    "alqosh": "Alqosh",
    "bagdad": "Baghdad",
    "arbil": "Erbil",
    "hewler": "Erbil",
    "basrah": "Basra",
    "al-basra": "Basra",
    "an-najaf": "Najaf",
    "al-najaf": "Najaf",
    "nasiriya": "Nasiriyah",
    "an-nasiriyah": "Nasiriyah",
    "warka": "Uruk",
    "amadiya": "Amedi",
    "bakhdida": "Bakhdida",
    "qaraqosh": "Bakhdida",
    # The catalogue names a governorate or an area where it means the city that
    # a day works out of. Left unresolved, the name drops out of the day's
    # chain, and "Nineveh / Erbil" reads as an Erbil day trip rather than as the
    # Mosul-to-Erbil transit it is.
    "nineveh": "Mosul",
    "nineveh governorate": "Mosul",
    "erbil governorate": "Erbil",
    "baghdad area": "Baghdad",
}

# A place a source names that carries no coordinate, and why none was entered.
# Recorded rather than guessed at, because a wrong coordinate produces a
# confident wrong distance and nothing would show it up.
PLACES_WITHOUT_A_COORDINATE = {
    "Salahdin": "the ticket index says Salahdin, which is a governorate and a "
                "resort above Erbil, and the row does not say which",
    "General": "the ticket index uses it for a fee row, and it names no place",
    "Rezan": "14 nights in the corpus, and no source in this repository places it",
    "Serzan": "7 nights in the corpus, and no source in this repository places it",
    "Shush Village": "2 nights in the corpus, and no source places it",
    "Choman Glamping": "2 nights in the corpus; Choman is on the map and the "
                       "camp's own position is not",
}


def resolve_place(name: str) -> str:
    """
    One place name, in the spelling PLACE_COORDINATES uses.

    Pre:  `name` is a place as any one source spells it.
    Post: the map's spelling, or "" when the map holds no such place.

    A name outside both tables gives "" rather than passing through. A caller
    that receives "" can say the map does not hold the place; a caller that
    received the name back would ask for a distance and get None, one step
    later and with less to say about why.
    """
    cleaned = (name or "").strip()
    if not cleaned:
        return ""
    if cleaned in PLACE_COORDINATES:
        return cleaned
    resolved = PLACE_ALIASES.get(cleaned.lower(), "")
    if resolved:
        return resolved
    for place in PLACE_COORDINATES:
        if place.lower() == cleaned.lower():
            return place
    return ""

# Straight line to road. Six measured pairs put the true factor between 0.97 and
# 1.33; 1.15 is the middle and the error is stated above rather than hidden.
ROAD_FACTOR = 1.15

# Average road speed over a whole leg, in km per hour. Measured: Baghdad-Mosul
# runs 410 km in about 5h36, which is 73 km/h, and Najaf-Basra runs 371 km in
# 4h15, which is 87 km/h.
AVERAGE_KMH = 75.0

# The longest leg the work really drives in one day, in km.
#
# Measured over the 1,098 legs in the corpus that move to a different city: the
# 90th percentile is 408 km, 19.6 percent of legs run over 400 km, and 2.6
# percent run over 450. The cliff sits between those two, and Baghdad to Mosul
# at 410 km is what fills the band, 171 times.
#
# Every leg above this in the corpus is one of seven pairs, and two of the seven
# say in their own day text that they were flown.
DAY_CEILING_KM = 410.0

# How much longer a route through C may be than the direct route, before C stops
# counting as on the way. A fifth longer: the distance model itself runs about
# 20 percent either way, so a tighter limit would be false precision.
DETOUR_LIMIT = 1.20

_COUNTED_MOVES: Optional[Counter] = None


@dataclass
class Leg:
    """One city to the next, as the map reads it."""
    from_city: str
    to_city: str
    km: Optional[float]          # None when either place has no coordinate
    count: int                   # times the corpus drove this way, unfloored
    reverse_count: int = 0       # times the corpus drove the other way

    @property
    def hours(self) -> Optional[float]:
        return None if self.km is None else self.km / AVERAGE_KMH

    @property
    def is_joined(self) -> bool:
        """
        Post: whether the corpus has carried this pair, in either direction.

        A road carries traffic both ways. The corpus drives Mosul to Duhok 61
        times and Duhok to Mosul never, and that is one road of 69 km rather
        than a road and a refusal. A leg is refused only where neither
        direction appears, which still refuses Mosul to Sulaymaniyah: the
        corpus carries that pair zero times each way.

        `count` stays the count in the direction asked. Nothing here changes a
        measurement, because a rule that says "61 of 256" must keep meaning it.
        """
        return self.count > 0 or self.reverse_count > 0

    @property
    def joined_direction(self) -> str:
        """
        Post: which way the corpus carried the pair. "" when neither way.

        A leg joined only in reverse is worth naming. It is the difference
        between a road the work drives and a road the work drives one way.
        """
        if self.count > 0:
            return "as proposed"
        if self.reverse_count > 0:
            return "in reverse only"
        return ""

    @property
    def is_over_ceiling(self) -> bool:
        """Post: whether the leg is longer than the work's own longest day."""
        return self.km is not None and self.km > DAY_CEILING_KM

    @property
    def statement(self) -> str:
        distance = "distance unknown" if self.km is None else (
            f"{self.km:.0f} km, about {self.hours:.1f} h")
        reverse = (f", and {self.reverse_count} time(s) the other way"
                   if self.reverse_count else "")
        return (f"{self.from_city} to {self.to_city}: {distance}, "
                f"the corpus joins it {self.count} time(s){reverse}")


def road_km(from_city: str, to_city: str) -> Optional[float]:
    """
    Post: estimated road distance in km, or None when either place is unknown.

    Great-circle distance times ROAD_FACTOR. None rather than a guess, because a
    caller that receives a number treats it as measured, and a caller that
    receives None can say so.

    Both names pass through `resolve_place`, so a caller holding the corpus
    spelling, the ticket index's spelling or the catalogue's gets one answer.

    Blame: an unknown place is a gap in PLACE_COORDINATES, not a caller error.
    """
    here = PLACE_COORDINATES.get(resolve_place(from_city))
    there = PLACE_COORDINATES.get(resolve_place(to_city))
    if here is None or there is None:
        return None
    if here == there:
        return 0.0

    lat1, lon1 = map(math.radians, here)
    lat2, lon2 = map(math.radians, there)
    seed = (math.sin((lat2 - lat1) / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 6371 * math.asin(math.sqrt(seed)) * ROAD_FACTOR


def place_key(name: str) -> str:
    """
    Post: the one name a place is stored and looked up under, for any spelling.

    `resolve_place` where the map holds the place, and the trimmed name where it
    does not. Rezan carries 14 nights and no coordinate, and it must still count
    its own moves under its own name rather than collapse into "".

    Invariant: `counted_moves` stores under this key and `move_count` reads
    under it. A lookup that resolved while the store did not would answer zero
    for a move the corpus carries, and the distance beside it would prove the
    place was understood.

    `binder` reads this too, so a spelling the sold routes use reaches the same
    template the catalogue files it under. Four spellings of one place were
    four places before, across four separate lists.
    """
    return resolve_place(name) or (name or "").strip()


def counted_moves(force_reload: bool = False) -> Counter:
    """
    Every night-to-night move the corpus carries, with no floor applied.

    Pre:  the offer corpus is readable.
    Post: {(from_city, to_city): times}, keyed by `place_key`. 79 ordered pairs
          over 289 offers, as measured on 2026-09-07.

    Unfloored on purpose. `rule_counter` keeps a rule only above 10 observations
    and a 15 percent share, which is right for a rule that describes the work
    and wrong for a question about whether a move has ever happened at all. A
    pair carried three times is not a rule, and it is not nothing.

    The nights come from `rule_counter.nights_of`, so this counts exactly what
    the rule book counts and the two can never drift apart.
    """
    global _COUNTED_MOVES
    if _COUNTED_MOVES is not None and not force_reload:
        return _COUNTED_MOVES

    from services.offers.offer_store import iter_offers
    from services.offers.rule_counter import MIN_NIGHTS_TO_COUNT, nights_of

    moves: Counter = Counter()
    for offer in iter_offers():
        nights = nights_of(offer)
        if len(nights) < MIN_NIGHTS_TO_COUNT:
            continue
        for here, next_city in zip(nights, nights[1:]):
            moves[(place_key(here), place_key(next_city))] += 1
    _COUNTED_MOVES = moves
    return _COUNTED_MOVES


def move_count(from_city: str, to_city: str) -> int:
    """
    Post: how many times the corpus put `to_city` after `from_city`, whichever
          spelling of either place the caller holds.
    """
    return counted_moves().get((place_key(from_city), place_key(to_city)), 0)


def leg(from_city: str, to_city: str) -> Leg:
    """
    Post: one leg, carrying both what the corpus says and what distance says.

    The two are kept apart on the record. A reader of a refusal needs to see
    that the corpus joins the pair zero times and the road is only 260 km,
    because that is the difference between "too far" and "not done".

    Both directions are counted and kept apart. `is_joined` reads them together
    and each stays readable on its own.
    """
    return Leg(from_city=from_city, to_city=to_city,
               km=road_km(from_city, to_city),
               count=move_count(from_city, to_city),
               reverse_count=move_count(to_city, from_city))


def path_between(from_city: str, to_city: str) -> list:
    """
    The shortest joined path from one city to another.

    Pre:  both names are places, in any spelling a source of this repository
          uses. `resolve_place` reconciles them.
    Post: the cities in order, in the map's spelling, `from_city` first and
          `to_city` last. [] when either end is not on the map, or when no path
          of joined moves reaches. A direct joined move returns two cities, so a
          caller tells "already fine" from "insert one" by length.

    Blame: a place the map does not hold gives [], including when both ends name
    it. A path of one through a place nobody can find reads as success, and a
    caller would insert a city that does not exist.

    Weighted by road distance, and restricted to pairs the corpus has carried.
    Both halves matter. Without the restriction the path Mosul to Sulaymaniyah
    runs through Kirkuk, which is the road no foreign group may take. Without
    the weight the path is the one with fewest stops, which is not the one a
    driver would take.

    A pair carried in one direction is walked in both, which is the same rule
    `Leg.is_joined` applies. A path that refused a leg the check accepts would
    tell a reviewer to insert a city and then refuse the result.

    Blame: a leg with no coordinate cannot be weighted, and is left out of the
    search. A path that needs such a leg reads as no path, which is honest: the
    map cannot cost it.
    """
    start, finish = resolve_place(from_city), resolve_place(to_city)
    if not start or not finish:
        return []
    if start == finish:
        return [start]

    moves = counted_moves()
    neighbours: dict = {}
    for (here, there), times in moves.items():
        if times <= 0:
            continue
        distance = road_km(here, there)
        if distance is None:
            continue
        first, second = resolve_place(here), resolve_place(there)
        neighbours.setdefault(first, []).append((second, distance))
        neighbours.setdefault(second, []).append((first, distance))

    queue = [(0.0, start, [start])]
    settled = set()
    while queue:
        cost, city, route = heapq.heappop(queue)
        if city == finish:
            return route
        if city in settled:
            continue
        settled.add(city)
        for there, distance in neighbours.get(city, ()):
            if there not in settled:
                heapq.heappush(queue, (cost + distance, there, route + [there]))
    return []


def cities_on_the_way(from_city: str, to_city: str,
                      among: Optional[set] = None) -> list:
    """
    The cities a driver passes, or nearly passes, between two others.

    Pre:  both places carry a coordinate. `among` is the set of places the
          caller will accept as a stop, or None for every place on the map.
    Post: [(city, added_km)] for every place where the detour stays inside
          DETOUR_LIMIT, nearest first. [] when either place is unknown.

    This is what answers "the itinerary skips sites that are on the way", so the
    places it must find are Samarra, Ashur, Hatra, Babylon and Samawa — none of
    which ever carries a night. A test against the counted moves would drop
    every one of them, because the corpus counts nights and these are day stops.

    `among` is how a caller keeps a place the work does not stop at. Kirkuk sits
    between Baghdad and Erbil and no active template visits it, so a caller that
    passes the cities its templates reach never sees it offered. The judgement
    belongs to the caller, which holds the catalogue; this module holds only
    where things are.
    """
    direct = road_km(from_city, to_city)
    if direct is None or direct <= 0:
        return []

    ends = {resolve_place(from_city), resolve_place(to_city)}
    found = []
    for city in PLACE_COORDINATES:
        if city in ends:
            continue
        if among is not None and city not in among:
            continue
        first = road_km(from_city, city)
        second = road_km(city, to_city)
        if first is None or second is None:
            continue
        if first + second > direct * DETOUR_LIMIT:
            continue
        found.append((city, first + second - direct))
    found.sort(key=lambda pair: pair[1])
    return found


def unmapped_cities() -> list:
    """
    Post: every city the corpus names that carries no coordinate, commonest
          first, as [(city, nights)].

    A gap report rather than a failure. Each name here is a leg the map cannot
    cost, and a reader who sees Rezan at 14 nights knows what one coordinate
    would buy.
    """
    from services.offers.offer_store import iter_offers
    from services.offers.rule_counter import MIN_NIGHTS_TO_COUNT, nights_of

    seen: Counter = Counter()
    for offer in iter_offers():
        nights = nights_of(offer)
        if len(nights) < MIN_NIGHTS_TO_COUNT:
            continue
        for city in nights:
            if city not in PLACE_COORDINATES:
                seen[city] += 1
    return seen.most_common()
