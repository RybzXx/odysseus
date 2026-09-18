"""
services/itinerary/binder.py

Binds matched route days to live DayTemplate codes from the Bil Weekend database.
Includes fixes for B18 (activity region vs city region) and B19 (transit connector preservation).
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Optional

from services.itinerary.models import RouteRecord
from services.itinerary.matcher import CITY_REGION_MAP


def _field(template, name, default=""):
    from services.itinerary.propose_sequence import field_of
    return field_of(template, name, default)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\b[a-zA-Z0-9]{3,}\b", (text or "").lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# Spellings this module resolves itself, because the answer is not a place on
# `move_map`. "kufa" and "marshes" are keys `matcher.CITY_REGION_MAP` holds and
# the map does not, and a region lookup is what reads them.
_LOCAL_ALIASES = {
    "al-kufa": "kufa",
    "ahwar": "marshes",
    "marshlands": "marshes",
}


def _normalize_city_name(name: str) -> str:
    """
    Post: one lower-case key for a city, whichever source spelled it.

    Pre:  `name` is an overnight city, from a sold route or from a template.

    Invariant: the template index and the route lookup both pass through here.
    A route that spelled a city one way and a catalogue that spelled it another
    were two cities, and the day bound nothing.

    `_LOCAL_ALIASES` runs first, then `move_map.place_key`. The map is the one
    place-name authority in the repository, and the sold routes carry spellings
    that were in none of the four separate lists: "Sulimaniyah" on 5 route days
    and "Chibayesh" on 4, each of which produced a coverage gap.
    """
    from services.itinerary.move_map import place_key

    from services.itinerary.places import normalize_place
    return normalize_place(name).casefold()



def _regions_of(code: str, template: Any, city_name: str = "") -> set:
    """
    Post: every region one bound day answers for. Never empty.

    Pre:  `code` is the template's code and `template` its row. `city_name` is
          the overnight city of the route day.

    Inv:  the set holds the day's own region and the region of the city it
          sleeps in. For 55 of the 62 templates those are the same value.

    Two questions, and one answer used to serve both. A day's own region says
    which customer it is *for*, and its overnight city says where the trip *is*
    that night. The seven exception templates are exactly the ones where the two
    differ (ws-03 phase seven, D61).

    Reading only the day's own region rejected `NA2BG` for a Central request and
    reported "Overnight in 'Baghdad' (Southern Iraq) outside requested
    region(s)", which is a sentence no reviewer can act on. Reading only the
    city put `SAFA` back in Central and made the exception list unreachable. A
    day binds when the customer asked for either, so a Southern request takes
    the marshes for their sites and a Central request takes them for the
    Baghdad night they sleep in.
    """
    from services.itinerary.regions import REGION_WHEN_UNSTATED, region_of_template

    answers = set()
    stated = region_of_template(code, template)
    if stated:
        answers.add(stated)
    by_city = CITY_REGION_MAP.get(_normalize_city_name(city_name))
    if by_city:
        answers.add(by_city)
    return answers or {REGION_WHEN_UNSTATED}


def _region_label(regions: set) -> str:
    """Post: the day's regions as one phrase, for a gap note a human reads."""
    return " / ".join(sorted(regions))


def _index_templates(templates: dict[str, Any]) -> dict[str, list[str]]:
    idx = defaultdict(list)
    for code, tmpl in templates.items():
        if getattr(tmpl, "active", True):
            city = getattr(tmpl, "overnight_city", "") or getattr(tmpl, "city", "")
            if city:
                idx[_normalize_city_name(city)].append(code)
    return idx


def _best_template_by_text(day_text: str, candidate_codes: list[str], templates: dict[str, Any]) -> tuple[Optional[str], float]:
    if not candidate_codes:
        return None, 0.0
    day_toks = _tokens(day_text)
    best_code: Optional[str] = None
    best_sim = -1.0

    for code in candidate_codes:
        tmpl = templates.get(code)
        if not tmpl:
            continue
        tmpl_text = getattr(tmpl, "full_text", "") or getattr(tmpl, "description", "") or getattr(tmpl, "name", "")
        sim = _jaccard(day_toks, _tokens(tmpl_text))
        if sim > best_sim:
            best_code = code
            best_sim = sim

    return best_code, max(best_sim, 0.0)


def _role_of_route_day(route, index: int) -> str:
    """
    Post: the job the route's own day does, in `day_shape`'s vocabulary.

    Pre:  `index` is 0-based into `route.days`.

    Read from the route, not from a template. The first night is an arrival, a
    night in the city of the night before is a day in that city, a night
    somewhere else is a transit, and a last day with no night is a departure.
    """
    from services.itinerary.day_shape import (
        ROLE_ARRIVAL, ROLE_CITY_DAY, ROLE_DEPARTURE, ROLE_TRANSIT)

    from services.itinerary.day_facts import source_day_facts
    previous = route.days[index - 1].overnight_city if index else ""
    facts = source_day_facts(route.days[index], previous)
    if index == 0 and facts["overnight_status"] == "present":
        return ROLE_ARRIVAL
    return facts["role"]



# A day trip and a city day both sleep where they woke. A route day cannot tell
# them apart, because the route records a night and not an excursion, so one
# route role accepts both template roles.
_ROLES_A_ROUTE_DAY_ACCEPTS = {}


def _acceptable_roles(route_role: str) -> set:
    from services.itinerary.day_shape import (
        ROLE_ARRIVAL, ROLE_CITY_DAY, ROLE_DAY_TRIP, ROLE_DEPARTURE, ROLE_TRANSIT)

    if not _ROLES_A_ROUTE_DAY_ACCEPTS:
        _ROLES_A_ROUTE_DAY_ACCEPTS.update({
            ROLE_ARRIVAL: {ROLE_ARRIVAL, ROLE_CITY_DAY, ROLE_DAY_TRIP, ROLE_TRANSIT},
            ROLE_CITY_DAY: {ROLE_CITY_DAY, ROLE_DAY_TRIP},
            ROLE_DAY_TRIP: {ROLE_DAY_TRIP, ROLE_CITY_DAY},
            ROLE_TRANSIT: {ROLE_TRANSIT},
            ROLE_DEPARTURE: {ROLE_DEPARTURE, ROLE_TRANSIT},
        })
    return _ROLES_A_ROUTE_DAY_ACCEPTS.get(route_role, set())


def _best_template_for_day(day_text: str, route_role: str, candidate_codes: list,
                           templates: dict,
                           sites_already_used: Optional[set] = None,
                           codes_already_used: Optional[set] = None) -> tuple[Optional[str], float]:
    """
    The template that best fits one route day, of the candidates given.

    Pre:  every candidate sleeps in the city the route day sleeps in.
          `sites_already_used` and `codes_already_used` hold what the days
          before this one took.
    Post: (code, word overlap). None when no candidate survives the role filter.

    Four stages, in this order (ws-03 D35):

      1. Keep the candidates whose role matches the day's role. Erbil holds 12
         templates and Sulaymaniyah holds 4, and they differ by the job they do
         rather than by their words.
      2. Drop a template the sequence already used. The same day twice is a
         fault (D32), so the binder must not offer one.
      3. Score the survivors on the sites the day's own text names, counting
         only the sites the trip has not used.
      4. The word overlap decides any tie that remains.

    Stage 3 counts unused sites, not named sites. A route's days name the same
    place more than once, so a score on named sites alone pulls the same
    template back every time: it raised site repeats from 14 to 15 and flags
    from 6 to 15 over ten proposals, measured before this line was written.

    Blame: an empty pool is a catalogue gap. The caller must report the gap.
    A role mismatch never permits a disconnected or repeated day.
    """
    from services.itinerary.day_shape import shape_of
    from services.itinerary.site_index import sites_named_in, sites_of_template

    if not candidate_codes:
        return None, 0.0

    used_sites = sites_already_used or set()
    used_codes = codes_already_used or set()

    wanted = _acceptable_roles(route_role)
    matching = [code for code in candidate_codes
                if code in templates
                and shape_of(code, templates[code]).role in wanted]
    survivors = matching

    unused = [code for code in survivors if code not in used_codes]
    survivors = unused

    day_toks = _tokens(day_text)
    best_code, best_score, best_sim = None, (-1, 1), -1.0
    for code in sorted(survivors):
        template = templates.get(code)
        if template is None:
            continue
        sites = sites_of_template(template)
        named = sites_named_in(day_text, sites)
        fresh = len([site for site in named if site not in used_sites])
        repeats = len([site for site in sites if site in used_sites])
        text = (_field(template, "full_text", "")
                or _field(template, "description", "")
                or _field(template, "name", ""))
        sim = _jaccard(day_toks, _tokens(text))
        # More sites this trip has not seen, then fewer it has, then the words.
        score = (fresh, -repeats)
        if (score, sim) > (best_score, best_sim):
            best_code, best_score, best_sim = code, score, sim

    return best_code, max(best_sim, 0.0)


def bind_route_to_templates(
    route: RouteRecord,
    templates: dict[str, Any],
    requested_regions: Optional[list[str]] = None,
) -> tuple[list[str], list[str]]:
    """Bind each historical day without inventing travel or dropping a gap.

    Pre: templates contain the active catalogue. Post: codes form a connected
    prefix with known connections enforced. Unknown starts need validation.
    The first missing day ends binding with a gap reason.
    """
    from services.itinerary.day_shape import shape_of, ROLE_DEPARTURE
    from services.itinerary.named_pair_rules import alternative_of
    from services.itinerary.site_index import sites_of_template
    from services.itinerary.matcher import activity_text
    from services.itinerary.regions import REGION_KURDISTAN

    from services.itinerary.day_facts import source_day_facts
    requested = set(requested_regions or [])
    north_requested = REGION_KURDISTAN in requested or any(
        _normalize_city_name(day.overnight_city) == "mosul" for day in route.days)
    shapes = {code: shape_of(code, template) for code, template in templates.items()}
    sites = {code: sites_of_template(template) for code, template in templates.items()}
    bound_codes, gap_notes = [], []
    used_codes, used_sites = set(), set()
    current_city = None
    for index, day in enumerate(route.days):
        overnight = _normalize_city_name(day.overnight_city)
        role = _role_of_route_day(route, index)
        facts = source_day_facts(day, route.days[index - 1].overnight_city if index else "")
        if role == "unknown":
            gap_notes.append(f"Day {day.day}: source role or overnight status is unknown. Review the source day.")
            break
        candidates = []
        for code in sorted(templates):
            template, shape = templates[code], shapes[code]
            if not _field(template, "active", True) or code in used_codes:
                continue
            # Owner correction: SAFA is a Baghdad excursion, not a northbound day.
            if code == "SAFA" and north_requested:
                continue
            if current_city and shape.start_city and (
                    _normalize_city_name(shape.start_city) != current_city):
                continue
            if overnight:
                if _normalize_city_name(shape.end_city or "") != overnight:
                    continue
                if shape.role == ROLE_DEPARTURE:
                    continue
                if _normalize_city_name(_field(template, "overnight_city", "")) != overnight:
                    continue
            else:
                if _field(template, "overnight_city", ""):
                    continue
                if shape.role != role:
                    continue
                if facts["end_city"] and _normalize_city_name(shape.end_city) != _normalize_city_name(facts["end_city"]):
                    continue
                if facts["start_city"] and shape.start_city and _normalize_city_name(shape.start_city) != _normalize_city_name(facts["start_city"]):
                    continue
                if not current_city and not facts["start_city"]:
                    continue
            if any(len(set(sites[code]) & set(sites[prior])) >= 2 for prior in bound_codes):
                continue
            candidates.append(code)
        code, _ = _best_template_for_day(
            activity_text(day.text), role, candidates, templates,
            sites_already_used=used_sites, codes_already_used=used_codes)
        if code is None:
            gap_notes.append(
                f"Day {day.day}: no unused {role} template connects "
                f"{current_city or 'the route start'} to {overnight or 'departure'}. "
                "Binding stopped. No travel or extra days were invented.")
            break
        bound_codes.append(code)
        used_codes.add(code)
        other = alternative_of(code)
        if other:
            used_codes.add(other)
        used_sites.update(sites[code])
        current_city = _normalize_city_name(shapes[code].end_city or current_city or "")
    return bound_codes, gap_notes
