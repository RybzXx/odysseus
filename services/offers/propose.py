"""
services/offers/propose.py

Turns a catalogue gap into reviewable proposals.

Two kinds come out, and the difference is the whole point of the near-miss band:

  revision — days that are a known template someone edited. The proposal carries
             the dominant edited wording, so the catalogue can be brought back
             in line with what is actually being sent.
  new      — days no template expresses, written enough times to be worth a
             template. The proposal carries the most representative wording.

No model is involved. Every proposed wording is a verbatim day that a human
actually sent, and the reviewer edits it. That keeps this step runnable before
any model delegation is approved, and it keeps the evidence trail exact: the
proposed text is not a paraphrase of the days, it is one of them.

A proposal is never given a code. A code carries operational meaning that only
the catalogue's owner can assign, so naming is left to the review.
"""
from __future__ import annotations

from typing import Iterable, Optional

from services.offers.day_match import NEAR_MISS_FLOOR, rank_templates, reordered_templates
from services.offers.gap_report import cluster_days, day_key
from services.offers.models import GapReport, SentOffer
from services.offers.proposals import (
    FREQUENCY_RARE,
    FREQUENCY_RECURRING,
    KIND_NEW,
    KIND_REVISION,
    TemplateProposal,
    build_proposal,
)

# A recurring day must be written at least this many times to earn a template.
MIN_OCCURRENCES_FOR_NEW = 2

# At or below this, the day is rare: written once or twice, usually for one
# client. Above it, the day recurs and the catalogue mostly already speaks for
# it. The two sets meet at this line and do not overlap.
MAX_OCCURRENCES_FOR_RARE = 2


def _blank_fields(full_text: str, overnight_city: str, note: str) -> dict:
    return {
        "code": "",                      # named by the reviewer, never generated
        "title": "",
        "city": overnight_city,
        "region": "",                    # assigned under the WP1.6 region rule
        "overnight_city": overnight_city,
        "full_text": full_text,
        "included_sites_json": "[]",
        "pricing_tags_json": "[]",
        "active": False,                 # invariant 1.3
        "needs_review": True,            # invariant 1.3
        "internal_notes": note,
    }


def _index_days(offers: Iterable[SentOffer]) -> dict:
    return {day_key(offer, day): day for offer in offers for day in offer.days}


def propose_revisions(offers: Iterable[SentOffer], report: GapReport,
                      template_texts: dict,
                      corpus: Optional[dict] = None) -> list[TemplateProposal]:
    """
    One proposal per template whose sent wording has drifted from the catalogue.

    Pre:  `report` came from `analyse_catalogue_gap` over these same offers;
          `corpus` is the stamp of the corpus those offers came from, or None.
    Post: for each template with near-miss days, a KIND_REVISION proposal whose
          `full_text` is the dominant variant among those days, carrying every
          near-miss day key as evidence. A template whose near misses do not
          agree with each other produces no proposal — there is no single
          revision to make, and guessing one would misrepresent the evidence.
    """
    offers = list(offers)
    by_key = _index_days(offers)
    proposals = []

    for code, day_keys in sorted(report.near_miss_by_code.items()):
        clusters = cluster_days([(_owner_of(by_key, key), by_key[key])
                                 for key in day_keys if key in by_key])
        if not clusters:
            continue
        dominant = clusters[0]
        if dominant.occurrences < 2:
            continue

        note = (f"Revision proposed from {dominant.occurrences} of {len(day_keys)} sent days "
                f"that read as {code} edited after generation.")
        proposals.append(build_proposal(
            kind=KIND_REVISION,
            fields=_blank_fields(dominant.representative_text,
                                 dominant.overnight_city, note),
            evidence_day_keys=dominant.member_keys,
            occurrences=dominant.occurrences,
            weight=dominant.weight,
            target_code=code,
            nearest_code=code,
            nearest_score=_score_against(dominant.representative_text, code, template_texts),
            corpus=corpus,
        ))
    return proposals


def propose_new_templates(report: GapReport, template_texts: dict,
                          min_occurrences: int = MIN_OCCURRENCES_FOR_NEW,
                          corpus: Optional[dict] = None,
                          counts: Optional[dict] = None) -> list[TemplateProposal]:
    """
    One proposal per day the catalogue cannot express, rare and recurring alike.

    Pre:  `corpus` is the stamp of the corpus `report` measured, or None.
          `counts`, when given, is filled with what each test admitted.
    Post: proposals ordered by evidence, each naming the nearest existing
          template and its score so a near-duplicate is visible before it is
          created. Every proposal carries the frequency of the day behind it.

    A day written once or twice is rare, and a rare day earns a row only when
    the catalogue is far from it. The owner asked for exactly those: the days
    that do not show usually, which canon cannot express. A rare day close to a
    row is an edit to that row, not a new one, so it is left out.

    A recurring day keeps the older rule and only has to clear
    `min_occurrences`. The two sets do not overlap, because rare stops at
    MAX_OCCURRENCES_FOR_RARE and recurring starts above it.
    """
    proposals = []
    tally = counts if counts is not None else {}
    tally.setdefault("rare", 0)
    tally.setdefault("far_from_canon", 0)
    tally.setdefault("rare_and_far", 0)
    tally.setdefault("recurring", 0)

    for pattern in report.patterns:
        ranked = rank_templates(pattern.representative_text, template_texts)
        nearest = ranked[0] if ranked else None
        nearest_score = nearest.score if nearest else 0.0

        mirrors = reordered_templates(pattern.representative_text, template_texts)

        is_rare = pattern.occurrences <= MAX_OCCURRENCES_FOR_RARE
        # A mirror is far from canon whatever it scores. Token overlap is blind
        # to order and carries half the score, so a route driven the other way
        # reads as 0.836 against the row it reverses. The catalogue still cannot
        # express it: a reordered pair is neither a match nor an edit. Judging it
        # by score alone would drop the very day this warning exists to catch.
        is_far = nearest_score < NEAR_MISS_FLOOR or bool(mirrors)
        tally["rare"] += int(is_rare)
        tally["far_from_canon"] += int(is_far)

        if is_rare:
            if not is_far:
                continue
            tally["rare_and_far"] += 1
            frequency = FREQUENCY_RARE
        else:
            if pattern.occurrences < min_occurrences:
                continue
            tally["recurring"] += 1
            frequency = FREQUENCY_RECURRING

        note = (f"Written {pattern.occurrences} times across sent offers with no template "
                f"that expresses it. Age-weighted evidence: {pattern.weight:.1f}.")
        if mirrors:
            note += (" Shares its content with "
                     + ", ".join(code for code, _, _ in mirrors)
                     + " in a different order — check whether this is that route reversed.")
        proposals.append(build_proposal(
            kind=KIND_NEW,
            fields=_blank_fields(pattern.representative_text, pattern.overnight_city, note),
            evidence_day_keys=pattern.member_keys,
            occurrences=pattern.occurrences,
            weight=pattern.weight,
            nearest_code=nearest.code if nearest else None,
            nearest_score=nearest_score,
            reordered_codes=[code for code, _, _ in mirrors],
            corpus=corpus,
            frequency=frequency,
        ))
    return proposals


def _owner_of(by_key: dict, key: str):
    """The offer a day key belongs to, reconstructed as a stand-in for clustering."""
    from services.offers.models import SentOffer as _SentOffer
    message_id = key.rsplit("#", 1)[0]
    return _SentOffer(message_id=message_id, subject="", sent_at=None)


def _score_against(text: str, code: str, template_texts: dict) -> float:
    for match in rank_templates(text, template_texts):
        if match.code == code:
            return match.score
    return 0.0
