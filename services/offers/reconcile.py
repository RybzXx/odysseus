"""
services/offers/reconcile.py

Compares the recovered corpus against the legacy one, so the mail recovery can
be shown to have lost nothing.

The legacy corpus was extracted from a folder of `.docx` offers that no longer
exists. If the mailbox holds every offer that folder held, the legacy file is
redundant and can be retired. If it does not, the difference is the part of the
company's history that survives only in a derived artefact — worth knowing
before anyone deletes it (ws-03 WP0.7).

Offers are matched on their day text, not their filenames. Filenames drift
between the `.docx` era and the PDF era for the same trip, and a filename is a
label while the itinerary is the thing itself.
"""
from __future__ import annotations

from typing import Iterable, Optional

from services.offers.day_match import (
    jaccard_lower_bound,
    normalize_day_text,
    similarity,
    token_overlap,
)
from services.offers.models import SentOffer

# Two offers are the same offer when their itineraries agree this closely. The
# same threshold the catalogue uses, for the same reason: it is the point above
# which two texts are the same text with edits rather than two different texts.
SAME_OFFER_THRESHOLD = 0.85


# How much of a legacy offer's itinerary must be present for it to be the same
# offer. Not all of it: the PDF era re-cut some trips by a day, and demanding
# every day would report a trip as lost because its departure day moved.
SAME_OFFER_DAY_COVERAGE = 0.7


def _day_tokens(offer: SentOffer) -> list:
    """Post: one (text, token set) per day, normalized once rather than per comparison."""
    prepared = []
    for day in offer.days:
        normalized = normalize_day_text(day.text)
        if normalized:
            prepared.append((normalized, set(normalized.split())))
    return prepared


def _offer_tokens(days: list) -> set:
    tokens = set()
    for _, day_tokens in days:
        tokens |= day_tokens
    return tokens


def _day_coverage(legacy_days: list, recovered_days: list, threshold: float,
                  floor: float) -> float:
    """
    The share of a legacy offer's days that appear in a recovered offer.

    Comparing whole offers character by character is quadratic in offer length
    and does not finish at corpus scale. Days are the unit the corpus is built
    from and are two orders of magnitude shorter, so the same question is asked
    of them instead.
    """
    if not legacy_days:
        return 0.0
    taken, found = set(), 0
    for legacy_text, legacy_tokens in legacy_days:
        for index, (recovered_text, recovered_tokens) in enumerate(recovered_days):
            if index in taken or token_overlap(legacy_tokens, recovered_tokens) < floor:
                continue
            # Both sides are already normalized; normalize_day_text is
            # idempotent, so similarity() re-running it costs nothing but
            # keeps one definition of the score.
            if similarity(legacy_text, recovered_text) >= threshold:
                taken.add(index)
                found += 1
                break
    return found / len(legacy_days)


def reconcile(recovered: Iterable[SentOffer],
              legacy: Iterable[SentOffer],
              threshold: float = SAME_OFFER_THRESHOLD) -> dict:
    """
    Three-way count between the two corpora.

    Pre:  both iterables yield offers carrying days.
    Post: every legacy offer appears in exactly one of `in_both` or
          `legacy_only`, and every recovered offer in exactly one of `in_both`
          or `recovered_only` — the counts sum to their inputs, so nothing is
          quietly dropped from the comparison.
    """
    recovered = [o for o in recovered if o.days]
    legacy = [o for o in legacy if o.days]

    # Whole offers are thousands of characters, and the sequence half of the
    # comparison is quadratic in their length. Token overlap rules most pairs
    # out for the cost of a set intersection, and does so exactly — see
    # day_match.jaccard_lower_bound — so nothing that could have matched is
    # skipped. Without it, 164 x 68 offers does not finish in nine minutes.
    floor = jaccard_lower_bound(threshold)
    recovered_days = [_day_tokens(o) for o in recovered]
    recovered_vocab = [_offer_tokens(days) for days in recovered_days]

    matched_recovered = set()
    in_both, legacy_only = [], []

    for legacy_offer in legacy:
        legacy_days = _day_tokens(legacy_offer)
        legacy_vocab = _offer_tokens(legacy_days)
        best_index, best_coverage = None, 0.0
        for index in range(len(recovered)):
            if index in matched_recovered:
                continue
            # Two offers that share almost no vocabulary share no days either.
            if token_overlap(legacy_vocab, recovered_vocab[index]) < 0.2:
                continue
            coverage = _day_coverage(legacy_days, recovered_days[index], threshold, floor)
            if coverage > best_coverage:
                best_index, best_coverage = index, coverage
                if coverage == 1.0:
                    break
        if best_index is not None and best_coverage >= SAME_OFFER_DAY_COVERAGE:
            matched_recovered.add(best_index)
            in_both.append({
                "legacy": legacy_offer.attachment_name,
                "recovered": recovered[best_index].attachment_name,
                "day_coverage": round(best_coverage, 3),
            })
        else:
            legacy_only.append({"legacy": legacy_offer.attachment_name,
                                "best_day_coverage": round(best_coverage, 3)})

    recovered_only = [offer.attachment_name for index, offer in enumerate(recovered)
                      if index not in matched_recovered]

    return {
        "recovered_offers": len(recovered),
        "legacy_offers": len(legacy),
        "in_both": in_both,
        "legacy_only": legacy_only,
        "recovered_only": recovered_only,
        "threshold": threshold,
    }


def format_reconciliation(result: dict, examples: int = 10) -> str:
    """A plain-text summary; no side effects."""
    lines = [
        f"recovered {result['recovered_offers']} offers, legacy {result['legacy_offers']}",
        f"  in both        {len(result['in_both']):>4}",
        f"  legacy only    {len(result['legacy_only']):>4}  (survives nowhere else)",
        f"  recovered only {len(result['recovered_only']):>4}  (newer than the legacy extract)",
    ]
    for entry in result["legacy_only"][:examples]:
        lines.append(f"  legacy only: {entry['legacy'][:58]} "
                     f"(best day coverage {entry['best_day_coverage']})")
    return "\n".join(lines)
