"""
services/itinerary/site_index.py

Which sites a day holds, where each one is, and when it is shut.

The handover records that nothing compares two templates in one proposal, and
that no site index exists. The first is true. The second is not: the index has
been in the pricing data all along, at `services/offers/data/pricing/
entry_tickets.json`, where 76 sites each carry a city, a region and a list of
closing days. It was written to price a ticket, and it answers a routing
question for free.

54 of the 57 site codes the templates use resolve against it. Two of the other
three are misspellings of codes that are in it, and this module joins them. A
check that compared raw strings would miss both collisions, and a missed
collision is a customer sent to one site twice.

Nothing here reads a sequence's geography. `move_map` holds that, and
`sequence_check` puts the two together.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Optional

# One site code written two ways. Both spellings are live in the catalogue, and
# each names a site the index already holds under the other spelling.
#
# Measured on 2026-09-07 over all 60 active templates:
#   NVHMARK   used by 1 template, against NVH_MARK used by 3
#   EB_SORA   used by 1 template, against ERB_SORA used by 5
#
# The catalogue keeps its spelling. This maps to the index's spelling at read
# time, so a repair to the sheet is not needed before a repeat can be found.
SITE_CODE_ALIASES = {
    "NVHMARK": "NVH_MARK",
    "EB_SORA": "ERB_SORA",
}

# A site the templates use and the index does not hold. Named rather than
# guessed at: it has no price row, so it also has no city and no closing day.
UNINDEXED_SITE_CODES = ("EBL_KOYA",)

_INDEX: Optional[dict] = None


@dataclass
class Site:
    """One site as the ticket index holds it."""
    site_code: str
    site_name: str = ""
    city: str = ""
    region: str = ""
    closed_on: tuple = ()        # weekday names, upper case, as the sheet has them
    active: bool = True

    @property
    def statement(self) -> str:
        shut = f", shut {'/'.join(self.closed_on)}" if self.closed_on else ""
        return f"{self.site_name or self.site_code} in {self.city or 'nowhere named'}{shut}"


def index_path() -> str:
    from pathlib import Path
    here = Path(__file__).resolve().parent.parent
    return str(here / "offers" / "data" / "pricing" / "entry_tickets.json")


def load_sites(force_reload: bool = False) -> dict:
    """
    Every site the ticket index holds, by code.

    Post: {site_code: Site}. An unreadable or missing file gives {}, so a
          sequence check still runs and reports what it could not test, rather
          than refusing to run at all.

    Blame: a malformed row is skipped and the rest of the file is kept. One bad
    row must not hide 75 good ones.
    """
    global _INDEX
    if _INDEX is not None and not force_reload:
        return _INDEX

    path = index_path()
    rows = []
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as handle:
                loaded = json.load(handle)
            rows = loaded if isinstance(loaded, list) else []
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            rows = []

    sites = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("site_code") or "").strip()
        if not code:
            continue
        closed = row.get("closed_on") or []
        sites[code] = Site(
            site_code=code,
            site_name=str(row.get("site_name") or "").strip(),
            city=str(row.get("city") or "").strip(),
            region=str(row.get("region") or "").strip(),
            closed_on=tuple(str(day).strip().upper() for day in closed if str(day).strip()),
            active=bool(row.get("active", True)),
        )
    _INDEX = sites
    return _INDEX


def canonical_site_code(code: str) -> str:
    """
    Post: one spelling for a site, so two templates naming it agree.

    A code outside SITE_CODE_ALIASES passes through as it was typed. This never
    guesses at a near neighbour: a new code enters under its own name and shows
    up in `unindexed_codes` rather than being folded into something else.
    """
    cleaned = (code or "").strip()
    return SITE_CODE_ALIASES.get(cleaned, cleaned)


def site_of(code: str) -> Optional[Site]:
    """Post: the indexed site, or None when the index does not hold the code."""
    return load_sites().get(canonical_site_code(code))


def sites_of_template(template) -> list:
    """
    Post: the template's site codes, each in the index's spelling, in order.

    Pre:  `template` is a DayTemplate or the catalogue's dict for one.
    """
    from services.itinerary.propose_sequence import field_of

    codes = field_of(template, "included_sites", None) or []
    if isinstance(codes, str):
        codes = [codes]
    return [canonical_site_code(str(code)) for code in codes if str(code).strip()]


@dataclass
class SiteRepeat:
    """One site that two days of a sequence both hold."""
    site_code: str
    site_name: str
    first_day: int               # 1-based day of the sequence
    first_code: str
    later_day: int
    later_code: str

    @property
    def statement(self) -> str:
        name = self.site_name or self.site_code
        return (f"{name} is on day {self.first_day} ({self.first_code}) and again "
                f"on day {self.later_day} ({self.later_code})")


def repeated_sites(day_codes, templates: dict) -> list:
    """
    Every site a sequence sends a customer to more than one time.

    Pre:  `day_codes` is the proposal in order, and `templates` maps a code to
          its template row.
    Post: one SiteRepeat per extra visit, in the order the repeats occur. A site
          on three days gives two records, each naming the first day and the day
          that repeats it.

    Codes are compared after `canonical_site_code`, so the two live misspellings
    do not read as different sites.

    Blame: a day code the catalogue does not hold contributes no sites and is
    not a repeat. A missing template is a catalogue problem, and counting it as
    a clean day is the same choice `sequence_grade` makes.
    """
    first_seen: dict = {}
    repeats = []
    for position, code in enumerate(day_codes or [], start=1):
        template = templates.get(code)
        if template is None:
            continue
        for site_code in sites_of_template(template):
            if site_code in first_seen:
                earlier_day, earlier_code = first_seen[site_code]
                site = load_sites().get(site_code)
                repeats.append(SiteRepeat(
                    site_code=site_code,
                    site_name=site.site_name if site else "",
                    first_day=earlier_day, first_code=earlier_code,
                    later_day=position, later_code=code))
            else:
                first_seen[site_code] = (position, code)
    return repeats


# Words that name a kind of place rather than a place. "Erbil Citadel" and
# "Akre Citadel" are two sites and one of these words. A match on "citadel"
# alone would call them the same.
#
# Measured on 2026-09-07: an exact name match finds 24 of 55 sites in the sold
# route text, and a match on the words left after this list finds 44.
_GENERIC_NAME_WORDS = {
    "the", "and", "old", "city", "route", "ancient", "great", "site",
    "museum", "palace", "shrine", "tomb", "mosque", "memorial", "gates",
    "cemetery", "relief", "reliefs", "fortress", "citadel", "mountain",
    "day", "tour", "visit", "free", "fee", "transfer", "breakfast", "lunch",
}

_WORD_RE = re.compile(r"[A-Za-z]{4,}")


def distinctive_words(site_name: str) -> set:
    """
    Post: the words of a site name that name this site and no other kind.

    "Grand Malwiyah" gives {"malwiyah"}. "Old City" gives the empty set, and a
    caller that receives it knows the name cannot be matched.

    Four letters or more, because "Ur" and "Al" name nothing on their own.
    """
    words = {word.lower() for word in _WORD_RE.findall(site_name or "")}
    return words - _GENERIC_NAME_WORDS


def sites_named_in(text: str, site_codes) -> list:
    """
    Which of these sites a piece of text names.

    Pre:  `text` is a day's own prose. `site_codes` are codes in any spelling.
    Post: the codes the text names, in the order given.

    Matched on the distinctive word rather than the whole string, because the
    route text says "Abbas shrine" where the index says "Abbass Shrine". An
    exact match finds 24 of 55 sites and this finds 44.

    Blame: a site whose name carries no distinctive word can never match, and it
    is left out rather than counted. `distinctive_words` names those three.
    """
    lowered = (text or "").lower()
    if not lowered:
        return []
    index = load_sites()
    found = []
    for code in site_codes:
        site = index.get(canonical_site_code(code))
        if site is None:
            continue
        words = distinctive_words(site.site_name)
        if words and any(word in lowered for word in words):
            found.append(canonical_site_code(code))
    return found


def unmatchable_sites(templates: dict) -> list:
    """
    Post: every site an active template uses whose name carries no distinctive
          word, sorted. A gap report for `sites_named_in`.
    """
    index = load_sites()
    found = set()
    for template in templates.values():
        for code in sites_of_template(template):
            site = index.get(code)
            if site is not None and not distinctive_words(site.site_name):
                found.add(code)
    return sorted(found)


def sites_in_city(city: str) -> list:
    """
    Post: every indexed site in one city, by code.

    This is what turns `move_map.cities_on_the_way` into an answer about sites.
    """
    wanted = (city or "").strip().casefold()
    if not wanted:
        return []
    return sorted(site.site_code for site in load_sites().values()
                  if site.city.casefold() == wanted)


def cities_the_templates_visit(templates: dict) -> set:
    """
    Every city an active template actually takes a customer to.

    Pre:  `templates` maps a code to its template row.
    Post: the set of city names the indexed sites of those templates sit in.

    This is the set a caller hands `move_map.cities_on_the_way`, and it is what
    keeps Kirkuk out of a proposal. Kirkuk lies between Baghdad and Erbil and
    the index holds a Kirkuk site, and no active template uses it. The catalogue
    already records that the work does not stop there, so nothing else has to
    state it.

    Names come back in the map's spelling, because the index spells four places
    its own way — Baashiqa, Chibayesh, Suli and Qosh — and a caller comparing
    them to a coordinate would find nothing. A city the map does not hold is
    left out, and `unplaceable_cities` names it.
    """
    from services.itinerary.move_map import resolve_place

    index = load_sites()
    cities = set()
    for template in templates.values():
        for code in sites_of_template(template):
            site = index.get(code)
            if site is None or not site.city:
                continue
            placed = resolve_place(site.city)
            if placed:
                cities.add(placed)
    return cities


def unplaceable_cities(templates: dict) -> list:
    """
    Post: every city an active template visits that the map cannot place,
          sorted, as [(city, [site codes])].

    A gap report beside `cities_the_templates_visit`. Each name here is a stop
    whose sites can never be found on the way, because nothing knows where it is.
    """
    from services.itinerary.move_map import resolve_place

    index = load_sites()
    stranded: dict = {}
    for template in templates.values():
        for code in sites_of_template(template):
            site = index.get(code)
            if site is None or not site.city:
                continue
            if not resolve_place(site.city):
                stranded.setdefault(site.city, set()).add(code)
    return [(city, sorted(codes)) for city, codes in sorted(stranded.items())]


def unindexed_codes(templates: dict) -> list:
    """
    Post: every site code the templates use that the index does not hold, sorted.

    A gap report. Each code here is a site whose city and closing day are unknown
    to every check in this package.
    """
    index = load_sites()
    missing = set()
    for template in templates.values():
        for code in sites_of_template(template):
            if code not in index:
                missing.add(code)
    return sorted(missing)
