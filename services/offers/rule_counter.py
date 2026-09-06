"""
services/offers/rule_counter.py

Rules found by counting the sent offers, not by asking a model.

A rule of this kind is a count. "194 of 288 trips spend the first night in
Baghdad" is checkable by anyone holding the corpus. A model saying the same
sentence is not checkable, and it can be wrong in a way nobody notices. So the
counting happens here, alone, and the model only words the result later
(decision D7).

Four families come out of the overnight city each day already carries:

  first night   where a trip sleeps on its first night
  last night    where it sleeps on its last
  move          where it goes next, given where it is now
  trip length   how many days a trip runs

Rules describe the whole corpus rather than a slice (decision D8). The one
restriction is structural: a trip with fewer than two nights has no move, and
its first night is also its last. Counting it would state the same fact twice
under two family names. That population is named in the result, never assumed.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Optional

FAMILY_FIRST_NIGHT = "first_night"
FAMILY_LAST_NIGHT = "last_night"
FAMILY_MOVE = "move"
FAMILY_TRIP_LENGTH = "trip_length"

FAMILIES = (FAMILY_FIRST_NIGHT, FAMILY_LAST_NIGHT, FAMILY_MOVE,
            FAMILY_TRIP_LENGTH)

# A trip needs two nights before it can move, and before its first and last
# night are different facts.
MIN_NIGHTS_TO_COUNT = 2

# Below ten observations one more offer moves the share by more than ten points,
# so the share is a description of the sample rather than of the work. Measured
# on 2026-09-06 over 288 offers: this floor keeps every city that appears as a
# real habit and drops a tail of one-off wordings.
MIN_OBSERVATIONS = 10

# A rule states what a trip usually does. Below fifteen percent the statement
# describes the exception, and five other outcomes are each more likely.
MIN_SHARE = 0.15

# Trip length is the exception, and the share floor does not apply to it.
#
# A share floor asks whether one outcome dominates the others. That question
# only means something when the outcomes are few. A trip runs any of 15 lengths,
# so the mass spreads and the commonest length holds 17 percent. At a 15 percent
# floor the family produced one rule and hid the shape of the demand, which is
# the part an itinerary planner needs. Here the observation floor alone decides,
# and the family reports the distribution.
MIN_SHARE_BY_FAMILY = {
    FAMILY_FIRST_NIGHT: MIN_SHARE,
    FAMILY_LAST_NIGHT: MIN_SHARE,
    FAMILY_MOVE: MIN_SHARE,
    FAMILY_TRIP_LENGTH: 0.0,
}

# ── Naming a city ────────────────────────────────────────────────────────────
#
# The corpus holds 38 distinct overnight strings for perhaps a dozen places. Most
# of the difference is punctuation and spelling. A variant left alone splits one
# real habit into two counts, and both then fall under the floor.

# The places the corpus stays in, as they are spelled in the catalogue.
_CANONICAL_CITIES = (
    "Baghdad", "Mosul", "Nasiriyah", "Karbala", "Erbil", "Basra", "Najaf",
    "Duhok", "Sulaymaniyah", "Soran", "Rezan", "Serzan", "Chibayish",
    "Barzan", "Rawanduz", "Korek Mountain", "Shush Village", "Samawa",
)

_ALIASES = {
    "sulaymaniya": "Sulaymaniyah",
    "sulaymaniah": "Sulaymaniyah",
    "sulimaniyah": "Sulaymaniyah",
    "chibayesh": "Chibayish",
    "korek": "Korek Mountain",
    "the marshes chibayish": "Chibayish",
    "homestay (chibayish)": "Chibayish",
}

# One lookup for both. A name typed in another case splits a count exactly as a
# misspelling does, so the known spellings are matched without regard to case.
_BY_LOWER = {city.lower(): city for city in _CANONICAL_CITIES}
_BY_LOWER.update(_ALIASES)

# "Duhok or Erbil" names two places. Counting it as either would invent evidence
# the offer does not carry, so it is refused and reported.
_ALTERNATIVE_RE = re.compile(r"\b(?:or)\b", re.I)

# A note after the city: "Baghdad (Not Included)".
_PARENTHETICAL_RE = re.compile(r"\s*\([^)]*\)\s*$")

# A day marker after the city: "Baghdad  1".
_TRAILING_NUMBER_RE = re.compile(r"\s+\d+$")

# Longer than this and the cell holds a sentence, not a place.
MAX_CITY_WORDS = 3


def canonical_city(raw: str) -> str:
    """
    One place name, or "" when the text names no single place.

    Pre:  `raw` is the `overnight_city` of one day, as extraction left it.
    Post: a trimmed name with its note, trailing number and trailing mark gone,
          and a known spelling or case variant mapped to one spelling. "" when
          the text offers a choice of places, runs longer than MAX_CITY_WORDS
          words, or holds no letter.

    A name outside `_CANONICAL_CITIES` passes through as it was typed. This does
    not guess at a near neighbour, so a new place enters the corpus under its own
    name. It stays under the observation floor until it is really used.

    Blame: this never guesses which of two places an offer meant. A refusal is
    counted and reported by `count_rules`, so a corpus that grows unreadable
    shows up as a rising refusal count rather than as quietly smaller rules.
    """
    text = re.sub(r"\s+", " ", (raw or "")).strip()
    if not text:
        return ""

    text = _PARENTHETICAL_RE.sub("", text).strip()
    text = text.rstrip(".,:;").strip()
    text = _TRAILING_NUMBER_RE.sub("", text).strip()
    if not text or not re.search(r"[A-Za-z]", text):
        return ""

    if _ALTERNATIVE_RE.search(text):
        return ""
    if len(text.split()) > MAX_CITY_WORDS:
        return ""

    return _BY_LOWER.get(text.lower(), text)


def nights_of(offer) -> list:
    """
    Post: the overnight cities of one offer, in order, each one named.

    A day the normalizer refuses drops out of the sequence. That shortens the
    trip rather than joining two nights that were never adjacent, which would
    invent a move.
    """
    return [city for city in
            (canonical_city(day.overnight_city) for day in offer.days)
            if city]


@dataclass
class CountedRule:
    """
    One rule, with the count that produced it.

    `share` is `count / total`, and `total` is the population the rule is about.
    For a move that population is the transitions out of one city, not every
    transition, because the rule answers "given a night here, where next".
    """
    family: str
    subject: str
    count: int
    total: int
    statement: str
    from_city: str = ""
    to_city: str = ""

    @property
    def share(self) -> float:
        return self.count / self.total if self.total else 0.0

    @property
    def rule_key(self) -> str:
        """A stable name for this rule across runs, so a record can track it."""
        return f"{self.family}:{self.subject}"


@dataclass
class RuleReport:
    """Everything one counting pass produced, including what it could not read."""
    rules: list = field(default_factory=list)
    offers_read: int = 0
    offers_counted: int = 0
    nights_named: int = 0
    nights_refused: int = 0
    refused_examples: list = field(default_factory=list)

    def of_family(self, family: str) -> list:
        return [rule for rule in self.rules if rule.family == family]


def _rules_from_counter(family: str, counts: Counter, total: int,
                        phrase) -> list:
    """
    Post: one rule per subject that clears both floors, commonest first.

    Pre:  `total` is the population every count is out of. The share floor comes
          from the family, because a wide outcome space makes any share small.
    """
    min_share = MIN_SHARE_BY_FAMILY[family]
    rules = []
    for subject, count in counts.most_common():
        if count < MIN_OBSERVATIONS:
            continue
        if total and count / total < min_share:
            continue
        rules.append(CountedRule(
            family=family,
            subject=str(subject),
            count=count,
            total=total,
            statement=phrase(subject, count, total),
        ))
    return rules


def count_rules(offers: Optional[Iterable] = None) -> RuleReport:
    """
    Count every rule the corpus supports.

    Pre:  `offers` yields SentOffer records. It defaults to the whole stored
          corpus, because a rule describes all of it (decision D8).
    Post: a RuleReport whose rules all clear MIN_OBSERVATIONS and MIN_SHARE, and
          whose counts name the population they came out of.

    Invariant: every number in a statement is reproducible from the corpus by
    counting. Nothing here estimates, smooths or predicts.

    Blame: an offer of fewer than MIN_NIGHTS_TO_COUNT named nights is left out
    of all four families and counted in `offers_read` minus `offers_counted`. A
    reader who sees those two differ knows how much of the corpus stayed silent.
    """
    if offers is None:
        from services.offers.offer_store import iter_offers
        offers = iter_offers()

    report = RuleReport()
    first_night, last_night, trip_length = Counter(), Counter(), Counter()
    moves_out = Counter()
    moves_by_pair = defaultdict(Counter)

    for offer in offers:
        report.offers_read += 1
        for day in offer.days:
            raw = (day.overnight_city or "").strip()
            if not raw:
                continue
            if canonical_city(raw):
                report.nights_named += 1
            else:
                report.nights_refused += 1
                if raw not in report.refused_examples:
                    report.refused_examples.append(raw)

        nights = nights_of(offer)
        if len(nights) < MIN_NIGHTS_TO_COUNT:
            continue

        report.offers_counted += 1
        first_night[nights[0]] += 1
        last_night[nights[-1]] += 1
        trip_length[offer.day_count] += 1
        for here, next_city in zip(nights, nights[1:]):
            moves_out[here] += 1
            moves_by_pair[here][next_city] += 1

    counted = report.offers_counted
    report.rules.extend(_rules_from_counter(
        FAMILY_FIRST_NIGHT, first_night, counted,
        lambda city, n, t: f"{n} of {t} trips spend the first night in {city}."))
    report.rules.extend(_rules_from_counter(
        FAMILY_LAST_NIGHT, last_night, counted,
        lambda city, n, t: f"{n} of {t} trips spend the last night in {city}."))
    report.rules.extend(_rules_from_counter(
        FAMILY_TRIP_LENGTH, trip_length, counted,
        lambda days, n, t: f"{n} of {t} trips run {days} days."))

    for here in sorted(moves_by_pair):
        out_total = moves_out[here]
        for rule in _rules_from_counter(
                FAMILY_MOVE, moves_by_pair[here], out_total,
                lambda to, n, t, _here=here: (
                    f"After a night in {_here}, the next night is in {to} "
                    f"{n} times out of {t}." if to != _here else
                    f"After a night in {_here}, the next night is in {_here} "
                    f"again {n} times out of {t}.")):
            rule.from_city = here
            rule.to_city = rule.subject
            rule.subject = f"{here} -> {rule.subject}"
            report.rules.append(rule)

    return report


def format_report(report: RuleReport) -> str:
    """The counting pass as the owner reads it, family by family."""
    lines = [
        f"offers read     {report.offers_read}",
        f"offers counted  {report.offers_counted}"
        f"  ({report.offers_read - report.offers_counted} held under "
        f"{MIN_NIGHTS_TO_COUNT} named nights)",
        f"nights named    {report.nights_named}",
        f"nights refused  {report.nights_refused}",
        f"rules found     {len(report.rules)}"
        f"  (floor: {MIN_OBSERVATIONS} observations, then the family's share)",
    ]
    if report.refused_examples:
        lines.append("  refused wording: "
                     + "; ".join(repr(x) for x in report.refused_examples[:6]))

    for family in FAMILIES:
        rules = report.of_family(family)
        share = MIN_SHARE_BY_FAMILY[family]
        floor = f"{share:.0%} share" if share else "no share floor"
        lines.append(f"\n{family}  ({len(rules)} rule(s), {floor})")
        for rule in sorted(rules, key=lambda r: -r.share):
            lines.append(f"  {rule.share:5.1%}  {rule.count:4d}/{rule.total:<4d}"
                         f"  {rule.statement}")
    return "\n".join(lines)


def main(argv=None) -> int:
    print(format_report(count_rules()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
