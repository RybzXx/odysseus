"""
services/itinerary/named_pair_rules.py

Rules that name two template codes, and what they do to a fault about them.

`sequence_check` counts sites. It knows that two days sharing three sites is a
fault, and it knows nothing about which two days. The owner knows more: `SAFA`
and `SAMO` both work Samarra, so they are alternatives rather than a pair, and a
proposal that holds both is worse rather than wrong.

That is one rule about one pair, and it belongs in the judged rule book. A code
written into the checker is a rule nobody can find and nobody can overrule
(ws-03 D36, and the shape invariant 1.4 already asks for).

The judged book stores it. This module reads it back and says what it does to a
fault the checker already raised. Nothing here counts anything, and nothing here
refuses anything the checker did not already refuse.

One rule stands today. The owner said the shape is unique: every other pair that
shares sites has a clear routing answer, so no second rule generalises from it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# What a named-pair rule does to a fault about that pair.
#
# Neither effect refuses. The owner said `SAFA` is penalised and never rejected,
# so a fault about this pair always becomes a flag. The two effects differ in
# what the flag says and in whether the candidate's score drops.
EFFECT_PENALTY = "penalty"   # a flag, and the candidate scores lower
EFFECT_ALLOW = "allow"       # a flag that states why the repeat is right here
EFFECTS = (EFFECT_PENALTY, EFFECT_ALLOW)

# The judged rule id the owner's `SAFA` rule is stored under.
SAFA_RULE_ID = "judged--safa-with-samo"

# The regions the condition needs, as a customer writes them. Read from the raw
# request text and never from `requested_regions`.
#
# `normalizer.REGION_NAME_MAP` maps "western iraq" and "nineveh plains" both to
# "Northern Iraq", and that mapping is correct: the west holds no hotel and no
# overnight, so operations bunches it with Mosul. It also means the west and the
# north are one value by the time a proposal is made, and a condition that asked
# for both would never be true.
_WEST_WORDS = ("western iraq", "west of iraq", "nineveh plain")
_NORTH_WORDS = ("northern iraq", "north of iraq", "kurdistan", "nineveh plain")

# Below this many days the penalty stands. At it and above, a trip has days to
# fill and the pair is allowed (ws-03, the owner's Q1 answer).
MIN_DAYS_TO_LIFT = 8


@dataclass
class PairVerdict:
    """What a named rule says about one fault the checker raised."""
    rule_id: str
    effect: str
    statement: str

    @property
    def softens(self) -> bool:
        """Post: whether the fault becomes a flag. Both effects do."""
        return self.effect in EFFECTS

    @property
    def lowers_the_score(self) -> bool:
        """Post: whether the candidate carrying this should rank lower."""
        return self.effect == EFFECT_PENALTY


def _raw_region_text(request_row: dict) -> str:
    """
    Post: every region the customer wrote, as one lower-case string.

    Pre:  `request_row` is the submitted record, not the normalised request.

    The raw text is the only place the west and the north stay apart.
    """
    for key in ("regions", "Regions", "region", "Region"):
        raw = (request_row or {}).get(key)
        if raw is None:
            continue
        if isinstance(raw, (list, tuple, set)):
            return " , ".join(str(part) for part in raw).lower()
        return str(raw).lower()
    return ""


def names_west_and_north(request_row: dict) -> bool:
    """
    Post: whether the customer asked for the west and the north.

    Blame: a customer who writes "north Iraq" and means the west gets the
    penalty. Nothing in this repository measures how often that happens, and the
    raw text is the best evidence there is.
    """
    text = _raw_region_text(request_row)
    if not text:
        return False
    return (any(word in text for word in _WEST_WORDS)
            and any(word in text for word in _NORTH_WORDS))


def safa_verdict(day_codes, request_row: dict, day_count: int) -> Optional[PairVerdict]:
    """
    What the owner's rule says about a sequence holding both `SAFA` and `SAMO`.

    Pre:  `day_codes` is the proposal, `request_row` is the submitted record,
          and `day_count` is what the customer asked for.
    Post: a PairVerdict when the sequence holds both codes, or None when it does
          not. The verdict never refuses. It always lowers the fault to a flag,
          and it says whether the candidate's score should drop with it.

    The penalty lifts on a long trip through the west and the north, where the
    desk must fill days with relevant sites and Samarra is what there is. The
    flag stays either way, because the customer still sees Samarra twice and the
    reviewer should read that before selling it.

    Blame: the caller owes the raw record. Passing the normalised request would
    make the condition unreachable, because normalisation folds the west into
    the north on purpose.
    """
    codes = set(day_codes or [])
    if not {"SAFA", "SAMO"} <= codes:
        return None

    if names_west_and_north(request_row) and (day_count or 0) >= MIN_DAYS_TO_LIFT:
        return PairVerdict(
            rule_id=SAFA_RULE_ID, effect=EFFECT_ALLOW,
            statement=(f"The request names the west and the north over "
                       f"{MIN_DAYS_TO_LIFT - 1} days, so the days have to be "
                       f"filled with relevant sites. The repeat stands, and it "
                       f"costs this candidate nothing."))
    return PairVerdict(
        rule_id=SAFA_RULE_ID, effect=EFFECT_PENALTY,
        statement=("SAFA sits with SAMO, and both work Samarra. They are "
                   "alternatives rather than a pair, so this scores lower. It "
                   "is not refused."))


def verdict_for_fault(fault, day_codes, request_row: dict,
                      day_count: int) -> Optional[PairVerdict]:
    """
    Post: the named rule that speaks about this fault, or None.

    Pre:  `fault` is a SequenceFault the checker raised.

    Only a site repeat between `SAFA` and `SAMO` has a rule today. Every other
    fault passes through, which is what the owner meant by calling the shape
    unique.
    """
    statement = getattr(fault, "statement", "") or ""
    if not re.search(r"\bSAFA\b", statement) or not re.search(r"\bSAMO\b", statement):
        return None
    return safa_verdict(day_codes, request_row, day_count)


def judged_rule_record():
    """
    Post: the owner's rule as the judged book stores it.

    Its `family` and `subject` are empty, because the counter measures first
    nights, last nights, moves and trip lengths, and none of those is a pair of
    template codes. The corpus verdict is then `silent`, which is the truthful
    answer rather than a missing one.
    """
    from services.offers.rule_book import JudgedRule

    return JudgedRule(
        rule_id=SAFA_RULE_ID,
        statement=(
            "SAFA scores lower when SAMO is already in the sequence, because "
            "both work the Samarra sites. The penalty lifts when the request "
            f"names Western Iraq and Northern Iraq over {MIN_DAYS_TO_LIFT - 1} "
            "days, where the days have to be filled with relevant sites."),
        comment_text=(
            "if SAMO exists then SAFA has less likelyhood of being implemented "
            "unless the requested itinerary is West of Iraq and north of iraq "
            "with more than a 7 days request. where we are forced to fill "
            "itinerary days with relevant sites."),
        corrected_sequence=[],
    )
