"""
services/itinerary/named_pair_rules.py

Pairs of templates that sell the same work two ways, and what holding both means.

`sequence_check` counts sites. It knows that two days sharing three sites is a
fault, and it knows nothing about which two days. Some pairs carry more than a
count: they are one day with two endings, and a trip takes one or the other.

    SAFA / BGFA    the same west day, with Samarra and without it
    MO1 / MO1EB    the same Old Mosul day, staying in Mosul or driving to Erbil
    NA2BA / NA2BG  the same Chibayish day, ending in Basra or in Baghdad

Holding both of a pair is always a fault. It is structural rather than
conditional, so no request can lift it and there is nothing to calibrate
(ws-03 phase seven, D63).

This replaces the judged rule that softened `SAFA` beside `SAMO`. That rule
asked whether the request named the west and the north, and `"nineveh plain"`
sat in both of its word lists, so one label satisfied both halves of an `and`.
It then allowed the repeat from eight days, where the one sold precedent runs
eleven. The corpus answers the same question better: 258 of 335 sold offers
visit Samarra and exactly one visits it twice (D64).

`BGFA` is what makes the retirement safe. A west request that already reaches
Samarra through `SAMO` now has a Samarra-free west day to bind, so the repeat
the old rule argued about does not arise.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# What a named-pair rule does to a fault about that pair.
#
# One effect remains. `EFFECT_PENALTY` and `EFFECT_ALLOW` both softened a fault
# into a flag, and neither survives: an alternative pair is a fault and stays
# one.
EFFECT_ALTERNATIVE = "alternative"

# The pairs, and why each is one day rather than two.
#
# Keyed by the frozen pair so a lookup does not care which came first.
ALTERNATIVE_PAIRS = {
    frozenset({"SAFA", "BGFA"}): (
        "SAFA and BGFA are the same west day. SAFA takes Samarra on the way and "
        "BGFA does not, so a trip takes one of them"),
    frozenset({"MO1", "MO1EB"}): (
        "MO1 and MO1EB are the same Old Mosul day. MO1 sleeps in Mosul and "
        "MO1EB drives on to Erbil, so a trip takes one of them"),
    frozenset({"NA2BA", "NA2BG"}): (
        "NA2BA and NA2BG are the same Chibayish day. NA2BA ends in Basra and "
        "NA2BG ends in Baghdad, so a trip takes one of them"),
}

# How often a sold offer repeats Samarra, which is what the retired rule argued
# about. Measured 2026-09-08 over the 335 offers in the corpus: 258 visit
# Samarra and 1 visits it on two days.
#
# Kept here because a reader of the retirement should see the number that
# replaced the rule, not be told to go and count it again.
SAMARRA_REPEAT_IN_CORPUS = (1, 258)


@dataclass
class PairVerdict:
    """What a named rule says about one fault the checker raised."""
    rule_id: str
    effect: str
    statement: str

    @property
    def softens(self) -> bool:
        """
        Post: whether the fault becomes a flag. No effect does any more.

        `sequence_check._apply_named_pair_rules` reads this. An alternative pair
        is a fault the reviewer must see, so nothing here lowers one.
        """
        return False

    @property
    def lowers_the_score(self) -> bool:
        """Post: whether the candidate carrying this should rank lower."""
        return True


def alternative_of(code: str) -> Optional[str]:
    """
    Post: the code this one is an alternative to, or None.

    Pre:  `code` is a template code.

    The binder reads this: a day already bound rules its alternative out, so a
    proposal cannot hold both and the fault below never has to fire.
    """
    for pair in ALTERNATIVE_PAIRS:
        if code in pair:
            other = pair - {code}
            return next(iter(other))
    return None


def pairs_in(day_codes) -> list:
    """
    Post: one entry per alternative pair the sequence holds both halves of, as
          (first_code, second_code, statement). Empty when it holds none.

    Pre:  `day_codes` is the proposal in order.
    """
    codes = set(day_codes or [])
    found = []
    for pair, statement in ALTERNATIVE_PAIRS.items():
        if pair <= codes:
            first, second = sorted(pair, key=lambda c: list(day_codes).index(c))
            found.append((first, second, statement))
    return found


def verdict_for_fault(fault, day_codes, request_row: dict,
                      day_count: int) -> Optional[PairVerdict]:
    """
    Post: the named rule that speaks about this fault, or None.

    Pre:  `fault` is a SequenceFault the checker raised.

    Every verdict this returns is an alternative pair, and no verdict softens.
    The signature keeps `request_row` and `day_count` because the checker passes
    them and a later rule may need them. Nothing reads them today, and a rule
    that read the raw region text is what phase seven retired.
    """
    statement = getattr(fault, "statement", "") or ""
    for pair, words in ALTERNATIVE_PAIRS.items():
        if all(re.search(rf"\b{re.escape(code)}\b", statement) for code in pair):
            return PairVerdict(rule_id=f"alternative--{'-'.join(sorted(pair)).lower()}",
                               effect=EFFECT_ALTERNATIVE, statement=words)
    return None
