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

    s = (name or "").strip().lower()
    s = re.sub(r"^(city of|overnight in|night in)\s+", "", s)
    if s in _LOCAL_ALIASES:
        return _LOCAL_ALIASES[s]
    return place_key(s).lower()


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

    here = _normalize_city_name(route.days[index].overnight_city)
    if not here:
        return ROLE_DEPARTURE
    if index == 0:
        return ROLE_ARRIVAL
    before = _normalize_city_name(route.days[index - 1].overnight_city)
    return ROLE_CITY_DAY if before == here else ROLE_TRANSIT


# A day trip and a city day both sleep where they woke. A route day cannot tell
# them apart, because the route records a night and not an excursion, so one
# route role accepts both template roles.
_ROLES_A_ROUTE_DAY_ACCEPTS = {}


def _acceptable_roles(route_role: str) -> set:
    from services.itinerary.day_shape import (
        ROLE_ARRIVAL, ROLE_CITY_DAY, ROLE_DAY_TRIP, ROLE_DEPARTURE, ROLE_TRANSIT)

    if not _ROLES_A_ROUTE_DAY_ACCEPTS:
        _ROLES_A_ROUTE_DAY_ACCEPTS.update({
            ROLE_ARRIVAL: {ROLE_ARRIVAL, ROLE_CITY_DAY, ROLE_DAY_TRIP},
            ROLE_CITY_DAY: {ROLE_CITY_DAY, ROLE_DAY_TRIP},
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

    Blame: a filter that empties the pool falls back to the wider one. A day
    bound to nothing is worse than a day bound to a second-best template, and a
    wrong role in `day_shape` would otherwise empty a day in silence.
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
    survivors = matching or list(candidate_codes)

    unused = [code for code in survivors if code not in used_codes]
    survivors = unused or survivors

    day_toks = _tokens(day_text)
    best_code, best_score, best_sim = None, (-1, 1), -1.0
    for code in survivors:
        template = templates.get(code)
        if template is None:
            continue
        sites = sites_of_template(template)
        named = sites_named_in(day_text, sites)
        fresh = len([site for site in named if site not in used_sites])
        repeats = len([site for site in sites if site in used_sites])
        text = (getattr(template, "full_text", "")
                or getattr(template, "description", "")
                or getattr(template, "name", ""))
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
    from services.itinerary.regions import (
        REGION_CENTRAL,
        REGION_KURDISTAN,
        REGION_SOUTH,
        REGION_WEST_NINEVEH,
    )

    req_regions = {r.strip() for r in (requested_regions or []) if r.strip()}
    # A trip from the far north to the far south passes through Baghdad whether
    # the customer named it or not, so a Central night is kept as a connector.
    #
    # Both tests used to read the literal "Northern Iraq", which stopped
    # existing when the catalogue took the intake form's four names. A test for
    # a region nobody can request is a test that never fires (D60).
    is_multi_region_non_contiguous = (
        bool(req_regions & {REGION_KURDISTAN, REGION_WEST_NINEVEH})
        and REGION_SOUTH in req_regions
        and REGION_CENTRAL not in req_regions
    )
    # Departures run through Erbil. Mosul takes no departing flight, so a trip
    # through the plains leaves from Erbil as a Kurdistan trip does.
    force_erbil_departure = bool(
        req_regions & {REGION_KURDISTAN, REGION_WEST_NINEVEH})

    overnight_idx = _index_templates(templates)
    bound_codes: list[str] = []
    gap_notes: list[str] = []
    # What the days before this one already took. Without it the site score
    # pulls the same template back whenever two days name one place.
    used_sites: set = set()
    used_codes: set = set()

    def take(code: str) -> None:
        """
        Post: the code is bound, its sites count as used, and so does the
              template it is an alternative to.

        Marking the alternative here rather than at every read is what stops a
        proposal holding both halves of one day. `SAFA` and `BGFA` are the same
        west day with and without Samarra, and a binder that offered both would
        sell Samarra twice and then report it as a fault of its own making
        (ws-03 phase seven, D63).
        """
        from services.itinerary.named_pair_rules import alternative_of
        from services.itinerary.site_index import sites_of_template
        bound_codes.append(code)
        used_codes.add(code)
        other = alternative_of(code)
        if other:
            used_codes.add(other)
        used_sites.update(sites_of_template(templates[code]))

    last_day_idx = len(route.days) - 1

    for i, rd in enumerate(route.days):
        oc = _normalize_city_name(rd.overnight_city)

        if oc:
            candidates = overnight_idx.get(oc, [])
            if candidates:
                best_code, _ = _best_template_for_day(
                    rd.text, _role_of_route_day(route, i), candidates, templates,
                    sites_already_used=used_sites, codes_already_used=used_codes)
                if best_code:
                    tmpl = templates[best_code]
                    day_regions = _regions_of(best_code, tmpl, oc)

                    if not req_regions or (day_regions & req_regions):
                        take(best_code)
                    elif is_multi_region_non_contiguous and REGION_CENTRAL in day_regions:
                        take(best_code)
                        gap_notes.append(
                            f"Day {rd.day} ({rd.overnight_city}): Retained as required Central Iraq transit connector."
                        )
                    else:
                        gap_notes.append(
                            f"Day {rd.day}: Overnight in '{rd.overnight_city}' "
                            f"({_region_label(day_regions)}) outside requested "
                            f"region(s); omitted."
                        )
            else:
                gap_notes.append(f"Day {rd.day}: No active template found for overnight city '{rd.overnight_city}'.")
            continue

        if i == last_day_idx and force_erbil_departure:
            erbil_departures = [
                code for code, t in templates.items()
                if getattr(t, "active", True)
                and not getattr(t, "overnight_city", "")
                and "erbil" in _normalize_city_name(getattr(t, "city", ""))
            ]
            best_code, _ = _best_template_by_text(rd.text, erbil_departures, templates)
            if best_code:
                take(best_code)
            else:
                gap_notes.append(
                    f"Day {rd.day}: Kurdistan departure should be from Erbil; fallback needed."
                )
            continue

        day_toks = _tokens(rd.text)
        no_overnight_candidates = [
            code for code, t in templates.items()
            if getattr(t, "active", True)
            and not getattr(t, "overnight_city", "")
            and _tokens(getattr(t, "city", "") or "") & day_toks
        ]
        best_code, sim = _best_template_by_text(rd.text, no_overnight_candidates, templates)
        if best_code and sim >= 0.05:
            tmpl = templates[best_code]
            day_regions = _regions_of(best_code, tmpl, getattr(tmpl, "city", ""))
            if not req_regions or (day_regions & req_regions):
                take(best_code)
            else:
                gap_notes.append(
                    f"Day {rd.day}: Day trip in '{_region_label(day_regions)}' "
                    f"outside requested region(s); omitted.")
        else:
            gap_notes.append(f"Day {rd.day}: Day trip / departure has no confident template match.")

    return bound_codes, gap_notes
