"""
services/itinerary/sequence_check.py

What is wrong with a proposed sequence, judged against the map and the sites.

`sequence_grade` marks a proposal against an offer that was sent, which needs an
answer key and only exists for the 289 offers in the corpus. This asks a
different question, and asks it of any sequence: does this itinerary hold
together on its own terms.

Nine faults are found here, and two more are named and not found.

Three of the nine arrived on 2026-09-08. `day_start` catches a day that begins
where the night before did not end, `role_order` catches a departure day with
days after it, and `alternative_pair` catches two templates that sell one day
two ways. They waited on a start city per template, and `day_shape` now holds
one for all 62: the owner settled 21 on 2026-09-07 and read the 32 the
catalogue derives on 2026-09-08 (ws-03 phase seven, WP33).

`day_start` is what saw the two routing faults the owner's own comments named
and this module reported as clean: a day 10 starting in Mosul after a Baghdad
night, and a Mosul to Sulaymaniyah move that the night chain cannot see because
the day making it carries no overnight city.

A named rule may add its words to a fault about a pair of codes. It never
refuses anything this module did not already refuse (ws-03 D36), and since
phase seven it never excuses one either (D63, D64).

Nothing here repairs. It reports, and a repair is a separate decision that has
to know which of three route candidates it is repairing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from services.itinerary.move_map import DAY_CEILING_KM, leg
from services.itinerary.site_index import load_sites, repeated_sites, sites_of_template

# What one fault is. Each names the owner's own words for it.
FAULT_SITE_REPEAT = "site_repeat"          # two or more sites on one day pair
FAULT_DAY_REPEAT = "day_repeat"            # the same template on two days
FAULT_FLAG_CAP = "flag_cap"                # too many one-site overlaps in a trip
FAULT_MOVE_NOT_JOINED = "move_not_joined"  # a pair the work has never carried
FAULT_LEG_TOO_LONG = "leg_too_long"        # further in one day than the work drives
FAULT_SITE_CLOSED = "site_closed"          # the site is shut on the day it lands
FAULT_DAY_START = "day_start"              # it begins where the last night did not end
FAULT_ROLE_ORDER = "role_order"            # an arrival or a departure out of place
FAULT_ALTERNATIVE_PAIR = "alternative_pair"  # both halves of one day sold two ways
FAULT_KINDS = (FAULT_SITE_REPEAT, FAULT_DAY_REPEAT, FAULT_FLAG_CAP,
               FAULT_MOVE_NOT_JOINED, FAULT_LEG_TOO_LONG, FAULT_SITE_CLOSED,
               FAULT_DAY_START, FAULT_ROLE_ORDER, FAULT_ALTERNATIVE_PAIR,
               "day_count", "region_coverage", "northbound_excursion", "default_route", "southern_return",
               "bakhdida_unrequested")

# One site shared by two days is a flag, not a fault. The owner reads it and
# decides, and the candidate that carries it scores lower than one that does not
# (ws-03 D30).
#
# Two or more shared sites is a fault. Measured over ten proposals: 24 day pairs
# share a site, 17 of them share two or more, and 7 share exactly one.
FLAG_SHARED_SITES = 1

# How many flags one trip may carry before the flags become a fault (D31).
#
# Two. The worst of the ten proposals carries two flags, and every other one
# carries none or one. The owner set the number. Nothing measures a better one,
# and a cap that fires on nothing today is a cap that fires as the desk changes.
FLAG_CAP = 2

# Faults this module does not find yet, and what each one waits on. Named here
# so a reader of a clean report knows what "clean" covers.
#
# `day_start` left this list on 2026-09-08, once the owner had read the 32 start
# cities the catalogue derived and corrected six of them. It found the two
# routing faults the owner's own comments named and the checker could not see:
# a day 10 that starts in Mosul after a Baghdad night, and a Mosul to
# Sulaymaniyah move hidden because a departure day carries no overnight city
# (ws-03 phase seven, WP33.2).
FAULTS_NOT_YET_FOUND = {
    "sites_skipped": "a leg whose richer template was passed over",
    "day_trip_on_a_moving_day": "a day trip used on the day the trip moves on",
}
BLOCKED_ON = ("nothing. `day_shape` holds a start, an end and a role for all 62 "
              "templates, so both are buildable")


@dataclass
class SequenceFault:
    """One thing wrong with one sequence, and where."""
    kind: str
    day: int                     # 1-based day of the sequence; 0 when it spans none
    statement: str
    day_code: str = ""
    from_city: str = ""
    to_city: str = ""
    km: Optional[float] = None
    site_code: str = ""


@dataclass
class SequenceFlag:
    """
    One thing worth stating that is not a fault.

    A flag never refuses a sequence. It states what the reviewer would otherwise
    have to find, and it lowers the score of the candidate that carries it
    (ws-03 D30). Two flags on one trip raise a fault instead (D31).
    """
    kind: str
    day: int
    statement: str
    day_code: str = ""
    site_code: str = ""


@dataclass
class SequenceCheck:
    """One sequence, every fault found in it, and every flag raised on it."""
    day_codes: list = field(default_factory=list)
    faults: list = field(default_factory=list)
    flags: list = field(default_factory=list)       # stated, never refused
    nights: list = field(default_factory=list)      # overnight city per night
    unknown_codes: list = field(default_factory=list)
    untested: list = field(default_factory=list)    # why a check could not run

    @property
    def is_fully_checked(self) -> bool:
        """Post: whether every check this module runs could run."""
        return not self.untested

    @property
    def found_no_fault(self) -> bool:
        """Post: whether the checks that ran found nothing. Says nothing about
        the checks that did not run."""
        return not self.faults and not self.unknown_codes

    @property
    def is_clean(self) -> bool:
        """
        Post: whether every check ran and none of them found anything.

        Both halves. A sequence whose closing days were never tested, because
        the request carries no start date, is not clean: it is unchecked, and a
        caller that gated on faults alone would treat the two the same and send
        an itinerary to a customer on the strength of three checks out of four.
        """
        return self.found_no_fault and self.is_fully_checked

    def of_kind(self, kind: str) -> list:
        return [fault for fault in self.faults if fault.kind == kind]

    @property
    def statement(self) -> str:
        if self.unknown_codes:
            unknown = f", {len(self.unknown_codes)} code(s) not in the catalogue"
        else:
            unknown = ""
        return (f"{len(self.day_codes)} day(s), {len(self.nights)} night(s), "
                f"{len(self.faults)} fault(s), {len(self.flags)} flag(s){unknown}")


def _overnight_city(template) -> str:
    """Post: the template's overnight city in the corpus spelling, or ""."""
    from services.itinerary.propose_sequence import field_of
    from services.offers.rule_counter import canonical_city

    raw = str(field_of(template, "overnight_city", "") or "").strip()
    if not raw:
        return ""
    return canonical_city(raw) or raw


def _weekday_of(start: date, day_number: int) -> str:
    """Post: the weekday a 1-based day of the trip lands on, upper case."""
    return (start + timedelta(days=day_number - 1)).strftime("%A").upper()


def _apply_named_pair_rules(check: SequenceCheck, request_row: Optional[dict],
                            day_count: int) -> None:
    """
    Post: every fault stands. A named rule may add its own words to one, and no
          rule lowers a fault to a flag any more.

    Pre:  `request_row` is the raw submitted record, and `day_count` is what the
          customer asked for. Both reach `named_pair_rules` unread today.

    Inv:  a rule never refuses what the checker did not already refuse (D36),
          and since phase seven it never excuses one either. The three rules
          left name alternative pairs, which are faults by construction (D63).

    This kept the loop because the shape is the extension point: a later rule
    that softens will re-use it, and `PairVerdict.softens` is where that
    decision lives rather than here.
    """
    from services.itinerary.named_pair_rules import verdict_for_fault

    kept = []
    for fault in check.faults:
        verdict = verdict_for_fault(fault, check.day_codes, request_row or {},
                                    day_count)
        if verdict is None or not verdict.softens:
            kept.append(fault)
            continue
        check.flags.append(SequenceFlag(
            kind=fault.kind, day=fault.day,
            statement=f"{fault.statement}. {verdict.statement}",
            day_code=fault.day_code, site_code=fault.site_code))
    check.faults = kept


def check_sequence(day_codes, templates: dict,
                   start_date: Optional[date] = None,
                   request_row: Optional[dict] = None,
                   day_count: int = 0, normalized_request=None, plan=None) -> SequenceCheck:
    """
    Every fault this module can find in one proposed sequence.

    Pre:  `day_codes` is the proposal in order, and `templates` maps a code to
          its template row. `start_date` is the trip's first day, or None.
    Post: a SequenceCheck naming each fault against the day it sits on, plus
          every check that could not run and why. Nothing is changed.

    The night chain checks distances and historical connections. The day-start
    check also includes templates without an overnight city.

    Blame: a code the catalogue does not hold is named in `unknown_codes` and
    contributes nothing. A missing template is a catalogue problem, and scoring
    it as a fault would blame the proposer for it.
    """
    check = SequenceCheck(day_codes=list(day_codes or []))
    from services.itinerary.resolved_plan import resolve_plan
    plan = plan or resolve_plan(check.day_codes, templates, normalized_request)
    templates = plan.templates
    check.untested.extend(plan.issues)
    if normalized_request is None and request_row:
        from services.itinerary.normalizer import normalize_from_dict, SOURCE_UNKNOWN
        normalized_request = normalize_from_dict("check", request_row, source=SOURCE_UNKNOWN)
    if normalized_request is not None:
        day_count = normalized_request.day_count
    if day_count and len(check.day_codes) != day_count:
        check.faults.append(SequenceFault(
            kind="day_count", day=0,
            statement=f"Requested {day_count} days, received {len(check.day_codes)}."))
    if not check.day_codes:
        # Nothing was checked, because there is nothing to check. Reporting a
        # clean sequence here says the four checks ran and found nothing, and a
        # reviewer would read an empty proposal as a passed one.
        check.untested.append(
            "nothing was checked: the sequence holds no day codes")
        return check

    from services.itinerary.propose_sequence import field_of

    nights = []          # (day_number, code)
    for position, code in enumerate(check.day_codes, start=1):
        template = templates.get(code)
        if template is None or not field_of(template, "active", True):
            check.unknown_codes.append(code)
            continue
        city = _overnight_city(template)
        if city:
            nights.append((position, code))
            check.nights.append(city)

    _check_site_repeats(check, templates)
    _check_night_chain(check, nights, templates)
    _check_day_starts(check, templates)
    _check_role_order(check, templates)
    _check_alternative_pairs(check)
    _check_closures(check, templates, start_date)
    # Last, because a judged rule speaks about a fault the checker raised.
    _apply_named_pair_rules(check, request_row, day_count)
    if normalized_request is not None:
        _check_request_requirements(check, templates, normalized_request)
    return check


def _check_request_requirements(check, templates, request):
    """Reject unsatisfied request requirements. Missing evidence stays unresolved."""
    from services.itinerary.regions import (
        sequence_regions, REGION_CENTRAL, REGION_KURDISTAN, REGION_WEST_NINEVEH, REGION_SOUTH,
        region_of_template)
    from services.itinerary.day_shape import shape_of, ROLE_DEPARTURE, OWNER_SETTLED_SHAPES
    from services.itinerary.move_map import place_key
    from services.itinerary.places import normalize_place
    from services.itinerary.site_index import load_sites, canonical_site_code
    from services.itinerary.day_preferences import bakhdida_requested
    if any(code in ('MOBKHEB', 'MOBKEB') for code in check.day_codes) and not bakhdida_requested(request):
        check.faults.append(SequenceFault(kind='bakhdida_unrequested', day=0,
            statement='Use BAEB. MOBKHEB is available only when the request asks for Bakhdida.'))
    cities = set()
    site_codes = set()
    index = load_sites()
    for code in check.day_codes:
        if code not in templates:
            continue
        shape = shape_of(code, templates[code])
        cities.update(filter(None, (normalize_place(shape.start_city), normalize_place(shape.end_city))))
        for site in sites_of_template(templates[code]):
            site_codes.add(site)
            if site in index:
                cities.add(normalize_place(index[site].city))
    for city in request.required_cities:
        if not normalize_place(city) or normalize_place(city) not in cities:
            check.faults.append(SequenceFault(kind="required_city", day=0,
                statement=f"Missing required city: {city}."))
    for site in request.required_sites:
        code = canonical_site_code(site)
        if code not in site_codes:
            check.faults.append(SequenceFault(kind="required_site", day=0,
                statement=f"Missing required site: {site}."))
    endpoints = [shape_of(code, templates[code]) for code in check.day_codes if code in templates]
    for label, value, actual in (
        ("arrival", request.arrival_city, endpoints[0].start_city if endpoints else ""),
        ("departure", request.departure_city, endpoints[-1].end_city if endpoints else ""),
    ):
        if value and (not normalize_place(value) or normalize_place(value) != normalize_place(actual)):
            check.faults.append(SequenceFault(kind="required_endpoint", day=0,
                statement=f"The {label} city must be {value}."))
    check.untested.extend(request.parse_warnings)
    missing = set(request.requested_regions) - sequence_regions(check.day_codes, templates)
    if missing:
        check.faults.append(SequenceFault(
            kind="region_coverage", day=0,
            statement="Missing requested regions: " + ", ".join(sorted(missing))))
    shapes = [(i, shape_of(c, templates[c]))
              for i, c in enumerate(check.day_codes) if c in templates]
    northbound = REGION_KURDISTAN in request.requested_regions or any(
        place_key(shape.end_city or "").lower() == "mosul" for _, shape in shapes)
    if "SAFA" in check.day_codes and northbound:
        check.faults.append(SequenceFault(
            kind="northbound_excursion", day=check.day_codes.index("SAFA") + 1,
            day_code="SAFA", statement="SAFA is a Baghdad excursion. The northbound request needs a connected transit day."))
    for field in ("day_count",):
        if request.was_defaulted(field):
            check.untested.append(f"The customer did not supply {field}.")
    for _, shape in shapes:
        if not shape.start_city and shape.code not in OWNER_SETTLED_SHAPES:
            check.untested.append(f"{shape.code}: the catalogue has no established start city.")
        if not shape.end_city:
            check.untested.append(f"{shape.code}: the catalogue has no established end city.")
    if set(request.requested_regions) == {REGION_CENTRAL, REGION_SOUTH} and shapes:
        cities = [place_key(shape.end_city or "").lower() for _, shape in shapes]
        sites = {site for code in check.day_codes if code in templates
                 for site in sites_of_template(templates[code])}
        if "nasiriyah" not in cities or "NA_MARSHES" not in sites or cities[-1] != "baghdad":
            check.faults.append(SequenceFault(
                kind="southern_return", day=0,
                statement="The Central and Southern route must reach Nasiriyah and the marshes, then return to Baghdad."))
    if request.was_defaulted("requested_regions") and shapes:
        south = [i for i, c in enumerate(check.day_codes)
                 if region_of_template(c, templates.get(c)) == REGION_SOUTH]
        mosul = [i for i, shape in shapes
                 if place_key(shape.end_city or "").lower() == "mosul"]
        ordered = bool(south and mosul and min(south) < min(mosul))
        endpoints = (place_key(shapes[0][1].start_city or "").lower() == "baghdad"
                     and place_key(shapes[-1][1].end_city or "").lower() == "erbil"
                     # BAEB offers the final-night/airport-departure options in pricing.
                     and (shapes[-1][1].role == ROLE_DEPARTURE or shapes[-1][1].code == 'BAEB'))
        if not ordered or not endpoints:
            check.faults.append(SequenceFault(
                kind="default_route", day=0,
                statement="The operator default requires Baghdad, then south, then Mosul, then departure from Erbil."))


def _shapes_for(check: SequenceCheck, templates: dict) -> dict:
    """
    Post: {code: DayShape} for the codes this sequence holds, or {} when the
          shapes cannot be read.

    Blame: an unreadable shape table is recorded on `untested` by the caller, so
    a reader of a clean report is not told a check ran that did not.
    """
    from services.itinerary.day_shape import all_shapes

    try:
        return all_shapes(templates)
    except Exception:                                   # noqa: BLE001
        check.untested.append(
            "the day shapes could not be read, so the day's start and the role "
            "order were not checked")
        return {}


def _check_day_starts(check: SequenceCheck, templates: dict) -> None:
    """
    Post: one fault per day that begins in a city the night before did not end
          in.

    Pre:  `check.day_codes` is the proposal in order.

    A day with no confirmed start passes. Some templates have more than one
    confirmed start because operations sells the day from either city.

    This sees what the night chain cannot. A day trip and a departure day carry
    no overnight city, so they take no position in that chain, and the two
    routing faults the owner named both sat on such a day.
    """
    from services.itinerary.day_shape import allowed_start_cities

    shapes = _shapes_for(check, templates)
    if not shapes:
        return

    where_the_night_ended = None
    for position, code in enumerate(check.day_codes, start=1):
        shape = shapes.get(code)
        if shape is None:
            continue
        starts = allowed_start_cities(code, templates[code])
        if (where_the_night_ended and starts
                and where_the_night_ended not in starts):
            named_starts = " / ".join(starts)
            check.faults.append(SequenceFault(
                kind=FAULT_DAY_START, day=position,
                statement=(f"day {position} ({code}) begins in "
                           f"{named_starts}, and the night before ended in "
                           f"{where_the_night_ended}"),
                day_code=code, from_city=where_the_night_ended,
                to_city=named_starts))
        where_the_night_ended = shape.end_city or where_the_night_ended


def _check_role_order(check: SequenceCheck, templates: dict) -> None:
    """
    Post: one fault per arrival day after the first, and one per departure day
          before the last.

    A departure day ends the trip. `SUEBDEP` sat on day 9 of a 12-day proposal
    and no check spoke, because it carries no overnight city and reaches neither
    the night chain nor the site counts in a way that says so (WP33.1).
    """
    from services.itinerary.day_shape import ROLE_ARRIVAL, ROLE_DEPARTURE

    shapes = _shapes_for(check, templates)
    if not shapes:
        return

    last = len(check.day_codes)
    for position, code in enumerate(check.day_codes, start=1):
        shape = shapes.get(code)
        if shape is None:
            continue
        if shape.role == ROLE_ARRIVAL and position > 1:
            check.faults.append(SequenceFault(
                kind=FAULT_ROLE_ORDER, day=position,
                statement=(f"day {position} ({code}) is an arrival day, and the "
                           f"trip started on day 1"),
                day_code=code))
        elif shape.role == ROLE_DEPARTURE and position < last:
            check.faults.append(SequenceFault(
                kind=FAULT_ROLE_ORDER, day=position,
                statement=(f"day {position} ({code}) is a departure day, and "
                           f"{last - position} day(s) follow it"),
                day_code=code))


def _check_alternative_pairs(check: SequenceCheck) -> None:
    """
    Post: one fault per alternative pair the sequence holds both halves of.

    Two templates that sell one day two ways are alternatives, not a pair to
    combine. The fault is structural, so no request lifts it (D63).
    """
    from services.itinerary.named_pair_rules import pairs_in

    for first, second, statement in pairs_in(check.day_codes):
        day = list(check.day_codes).index(second) + 1
        check.faults.append(SequenceFault(
            kind=FAULT_ALTERNATIVE_PAIR, day=day,
            statement=f"the sequence holds {first} and {second}. {statement}",
            day_code=second))


def _check_site_repeats(check: SequenceCheck, templates: dict) -> None:
    """
    Post: one fault per day pair sharing two sites or more, one flag per pair
          sharing exactly one, and one fault when the flags reach FLAG_CAP.
          One fault per day pair that names the same template twice.

    The unit is the day pair, not the site. Four sites shared by days 3 and 4 is
    one fault about those two days, not four faults about four sites. A reviewer
    reads a day pair and decides about a day pair.

    Any two days, not adjacent days alone (D30). `SAMO` on day 2 and `SAFA` on
    day 9 send a customer to Samarra twice, and seven days between them changes
    nothing about that.
    """
    seen_codes = set()
    for day, code in enumerate(check.day_codes, 1):
        if code in seen_codes:
            check.faults.append(SequenceFault(
                kind=FAULT_DAY_REPEAT, day=day, day_code=code,
                statement=f"Day {day} repeats template {code}."))
        seen_codes.add(code)
    shared: dict = {}
    for repeat in repeated_sites(check.day_codes, templates):
        key = (repeat.first_day, repeat.later_day)
        shared.setdefault(key, {"codes": (repeat.first_code, repeat.later_code),
                                "sites": [], "names": []})
        shared[key]["sites"].append(repeat.site_code)
        shared[key]["names"].append(repeat.site_name or repeat.site_code)

    for (first_day, later_day), found in sorted(shared.items()):
        first_code, later_code = found["codes"]
        names = ", ".join(found["names"])

        # The same template twice is a fault whatever the site count, because
        # the customer gets the same day again (D32).
        if first_code == later_code:
            continue

        if len(found["sites"]) > FLAG_SHARED_SITES:
            check.faults.append(SequenceFault(
                kind=FAULT_SITE_REPEAT, day=later_day,
                statement=(f"day {first_day} ({first_code}) and day {later_day} "
                           f"({later_code}) share {len(found['sites'])} sites: {names}"),
                day_code=later_code, site_code=found["sites"][0]))
        else:
            check.flags.append(SequenceFlag(
                kind=FAULT_SITE_REPEAT, day=later_day,
                statement=(f"day {first_day} ({first_code}) and day {later_day} "
                           f"({later_code}) share one site: {names}"),
                day_code=later_code, site_code=found["sites"][0]))

    if len(check.flags) >= FLAG_CAP:
        days = ", ".join(str(flag.day) for flag in check.flags)
        check.faults.append(SequenceFault(
            kind=FAULT_FLAG_CAP, day=check.flags[-1].day,
            statement=(f"{len(check.flags)} day pairs each share a site, at the "
                       f"cap of {FLAG_CAP}. Days {days} repeat something")))


def _check_night_chain(check: SequenceCheck, nights: list, templates: dict) -> None:
    """
    Post: one fault per consecutive pair of nights the work has never joined in
          either direction, and one per pair further apart than the work drives
          in a day.

    A pair can raise both. They say different things: never joined is what the
    corpus knows about permits and roads, and too long is what distance knows.
    A reader needs to see which of the two refused a leg, so neither is folded
    into the other.

    Direction does not decide the first fault. A road the corpus drives one way
    is a road, and `Leg.is_joined` reads both counts.
    """
    from services.itinerary.move_map import Leg, counted_moves, road_km

    try:
        corpus_available = bool(counted_moves())
    except (OSError, ValueError):
        corpus_available = False
    if len(nights) > 1 and not corpus_available:
        check.untested.append("City connections were not checked: the offer corpus has no usable connection evidence.")

    for (first_day, first_code), (next_day, next_code) in zip(nights, nights[1:]):
        here = _overnight_city(templates[first_code])
        there = _overnight_city(templates[next_code])
        if here == there:
            continue

        move = leg(here, there) if corpus_available else Leg(
            from_city=here, to_city=there, km=road_km(here, there), count=0)
        if corpus_available and not move.is_joined:
            check.faults.append(SequenceFault(
                kind=FAULT_MOVE_NOT_JOINED, day=next_day,
                statement=(f"day {next_day} sleeps in {there} after a night in "
                           f"{here}, and the corpus has never carried that "
                           f"pair, in either direction"),
                day_code=next_code, from_city=here, to_city=there, km=move.km))
        if move.is_over_ceiling:
            check.faults.append(SequenceFault(
                kind=FAULT_LEG_TOO_LONG, day=next_day,
                statement=(f"day {next_day} runs {here} to {there}, about "
                           f"{move.km:.0f} km, over the {DAY_CEILING_KM:.0f} km "
                           f"the work drives in a day"),
                day_code=next_code, from_city=here, to_city=there, km=move.km))
        if move.km is None:
            check.untested.append(
                f"day {next_day}: {here} to {there} has no distance, because a "
                f"place carries no coordinate")


def _check_closures(check: SequenceCheck, templates: dict,
                    start_date: Optional[date]) -> None:
    """
    Post: one fault per site that is shut on the weekday its day lands on.

    Blame: with no start date the check cannot run, and records itself as
    untested rather than passing. A silent pass would read as "no site is shut".
    """
    if start_date is None:
        check.untested.append(
            "no closing day was tested: the request carries no start date")
        return

    index = load_sites()
    for position, code in enumerate(check.day_codes, start=1):
        template = templates.get(code)
        if template is None:
            continue
        weekday = _weekday_of(start_date, position)
        for site_code in sites_of_template(template):
            site = index.get(site_code)
            if site is None or weekday not in site.closed_on:
                continue
            check.faults.append(SequenceFault(
                kind=FAULT_SITE_CLOSED, day=position,
                statement=(f"{site.site_name or site_code} is shut on "
                           f"{weekday.title()}, and day {position} ({code}) "
                           f"lands on one"),
                day_code=code, site_code=site_code))


def check_to_dict(check: SequenceCheck) -> dict:
    """
    One check as a reader over HTTP receives it.

    Post: the faults in day order, the codes the catalogue does not hold, the
          checks that could not run, and the two halves of "clean" kept apart.
          `day_codes` is left out: the sequence this check belongs to already
          carries them, and a second copy is a second thing to keep in step.

    The shape lives here rather than in the route, because this module decides
    what a fault is and a route that built its own shape would drift from it.
    """
    return {
        "faults": [
            {"kind": fault.kind, "day": fault.day, "statement": fault.statement,
             "day_code": fault.day_code, "from_city": fault.from_city,
             "to_city": fault.to_city, "km": fault.km, "site_code": fault.site_code}
            for fault in sorted(check.faults, key=lambda f: (f.day, f.kind))
        ],
        "fault_count": len(check.faults),
        "flags": [
            {"kind": flag.kind, "day": flag.day, "statement": flag.statement,
             "day_code": flag.day_code, "site_code": flag.site_code}
            for flag in sorted(check.flags, key=lambda f: (f.day, f.kind))
        ],
        "flag_count": len(check.flags),
        "flag_cap": FLAG_CAP,
        "unknown_codes": list(check.unknown_codes),
        "untested": list(check.untested),
        "nights": list(check.nights),
        "found_no_fault": check.found_no_fault,
        "is_fully_checked": check.is_fully_checked,
        "is_clean": check.is_clean,
        "not_yet_found": dict(FAULTS_NOT_YET_FOUND),
    }


def format_check(check: SequenceCheck) -> str:
    """The check as a reader marks it, day by day."""
    lines = [check.statement]
    for fault in sorted(check.faults, key=lambda f: (f.day, f.kind)):
        lines.append(f"  day {fault.day:2d}  {fault.kind:16s} {fault.statement}")
    for flag in sorted(check.flags, key=lambda f: (f.day, f.kind)):
        lines.append(f"  day {flag.day:2d}  flag             {flag.statement}")
    for code in check.unknown_codes:
        lines.append(f"  ----     unknown_code      {code} is not in the catalogue")
    for note in check.untested:
        lines.append(f"  ----     not tested        {note}")
    if not check.faults:
        lines.append("  no fault found by the four checks this module runs")
    for name, description in FAULTS_NOT_YET_FOUND.items():
        lines.append(f"  ----     not yet found     {name}: {description}")
    lines.append(f"           waiting on          {BLOCKED_ON}")
    return "\n".join(lines)
