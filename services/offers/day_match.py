"""
services/offers/day_match.py

Scores a day's prose against the day-template catalogue.

The formula is the one the operations pipeline shipped and validated:
half token overlap, half sequence ratio, over normalized text. What differs
here is the normalization — dates, weekdays and clock times are stripped,
because an offer writes the same day differently every trip and the calendar
noise is not part of the day's identity.

    MEASURED over 1087 real offer days: without date stripping 219 days match
    the catalogue; with it, 377 do. The largest single gap collapses from two
    clusters into one 50-occurrence Mosul day.

MATCH_THRESHOLD keeps the shipped value but rests on new evidence. Its original
justification — a wide empty gap between template days at 1.000 and the best
hand-written day at 0.703 — does not survive the scoring fix: the distribution
is now continuous from 0.60 to 1.00. It was re-validated instead against
overnight-city agreement (ws-03 §8), which puts 0.85 well inside the reliable
region. That measurement also shows 0.80 performing identically, which is left
open for the catalogue's owner rather than changed here.
"""
from __future__ import annotations

import difflib
import re

from services.offers.models import (
    BAND_MATCH,
    BAND_NEAR_MISS,
    BAND_NO_MATCH,
    TemplateMatch,
)

# Accepts a template match. Template-derived days score 1.000.
#
# Set to 0.80 by the catalogue's owner on 2026-09-04, from measurement rather
# than intuition. Overnight-city agreement — evidence the scorer never sees —
# is 82% across [0.80, 0.85) and 83% across [0.85, 0.90), against a chance
# level near 20%. The band behaves like the accepted band, so the previous
# 0.85 was refusing 72 days that look exactly like the ones it took.
MATCH_THRESHOLD = 0.80

# Below the threshold but at or above this floor, a day reads as a known
# template edited after generation, not as a new day. The two demand opposite
# work: a revision to an existing row, or a new row.
#
# Settled by ws-03 WP1.1.4 on overnight-city agreement — whether a day's own
# Overnight city matches its best template's, which is evidence the scorer never
# sees. MEASURED over 1087 days: agreement is 82-96% above 0.80, 58-65% across
# 0.70-0.80, and 36-44% below 0.70 against a chance level near 20%. The middle
# band is exactly the signature of a template edited after generation.
NEAR_MISS_FLOOR = 0.70

# Two templates both clearing the threshold is not ambiguity — a day scoring
# 1.000 for one and 0.850 for another has an obvious winner. Only a near-tie is
# a coin flip. MEASURED: the closest distinct template pair (BANMEB/BAEB) sits
# at 0.850, so a verbatim day of either wins by 0.150 and is not flagged.
AMBIGUITY_MARGIN = 0.05

_WEEKDAYS = "monday|tuesday|wednesday|thursday|friday|saturday|sunday"
_MONTHS = ("january|february|march|april|may|june|"
           "july|august|september|october|november|december")

_OVERNIGHT_LINE_RE = re.compile(r"(?im)^\s*overnight\s*:.*$")
_WEEKDAY_RE = re.compile(rf"\b({_WEEKDAYS})\b")
_DAY_MONTH_RE = re.compile(rf"\b\d{{1,2}}(st|nd|rd|th)?\s+({_MONTHS})\b")
_MONTH_DAY_RE = re.compile(rf"\b({_MONTHS})\s+\d{{1,2}}(st|nd|rd|th)?\b")
_CLOCK_RE = re.compile(r"\b\d{1,2}[:.\s]?\d{0,2}\s*(am|pm)\b")
_NIGHT_NUMBER_RE = re.compile(r"\bnight\s*\d+\b")
_YEAR_RE = re.compile(r"\b\d{4}\b")
_NON_WORD_RE = re.compile(r"[^a-z0-9\s]")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_day_text(text: str) -> str:
    """
    Reduce a day's prose to its comparable content.

    Removes, in order: the Overnight line (boilerplate that inflates similarity
    between unrelated days), weekdays, dates in either order, clock times, night
    numbers, bare years, punctuation, and repeated whitespace.

    Post: the result is lowercase, single-spaced, and free of calendar tokens.
    """
    lowered = (text or "").lower()
    lowered = _OVERNIGHT_LINE_RE.sub(" ", lowered)
    lowered = _WEEKDAY_RE.sub(" ", lowered)
    lowered = _DAY_MONTH_RE.sub(" ", lowered)
    lowered = _MONTH_DAY_RE.sub(" ", lowered)
    lowered = _CLOCK_RE.sub(" ", lowered)
    lowered = _NIGHT_NUMBER_RE.sub(" ", lowered)
    lowered = _YEAR_RE.sub(" ", lowered)
    lowered = _NON_WORD_RE.sub(" ", lowered)
    return _WHITESPACE_RE.sub(" ", lowered).strip()


# A route driven in the opposite direction uses almost the same words in almost
# the opposite order. Token overlap stays high while the sequence ratio falls,
# and the combined score lands too low to match but too high to be unrelated —
# so the day looks new when it is really an existing template, reversed.
#
#     MEASURED over 577 days against 28 templates: 7 pairs show this signature,
#     and every one is the Najaf/Uruk mirror. NAURUKNJ scores jaccard 0.94
#     against sequence 0.43; URUKNA scores 0.84 against 0.53. Their combined
#     scores are 0.62 to 0.68 — below the near-miss floor, so without this they
#     become proposals for templates that already exist in the other direction.
REORDER_TOKEN_FLOOR = 0.75
REORDER_SEQUENCE_GAP = 0.25


def similarity_parts(day_text: str, template_text: str) -> tuple:
    """
    The two halves of the score, kept apart.

    Post: (jaccard, sequence), each 0.0 to 1.0. Their mean is `similarity`.
          Apart they say something the mean hides: high overlap with a low
          sequence ratio means the same content in a different order.
    """
    left, right = normalize_day_text(day_text), normalize_day_text(template_text)
    left_tokens, right_tokens = set(left.split()), set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0, 0.0
    jaccard = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    sequence = difflib.SequenceMatcher(None, left, right, autojunk=False).ratio()
    return jaccard, sequence


def is_reordered(jaccard: float, sequence: float) -> bool:
    """Post: True when two texts share their words but not their order."""
    return jaccard >= REORDER_TOKEN_FLOOR and (jaccard - sequence) >= REORDER_SEQUENCE_GAP


def reordered_templates(day_text: str, template_texts: dict) -> list:
    """
    Templates this day matches in content but not in order.

    Pre:  `template_texts` maps template code to full text.
    Post: [(code, jaccard, sequence)] for every template that shares this day's
          words in a different order, strongest overlap first. Empty for a day
          that is genuinely new.

    A caller uses this to warn before a reversed route becomes a second
    template for a journey the catalogue already describes.
    """
    found = []
    for code, text in template_texts.items():
        if not (text or "").strip():
            continue
        jaccard, sequence = similarity_parts(day_text, text)
        if is_reordered(jaccard, sequence):
            found.append((code, round(jaccard, 3), round(sequence, 3)))
    found.sort(key=lambda entry: -entry[1])
    return found


def similarity(day_text: str, template_text: str) -> float:
    """
    Half token overlap, half sequence ratio, over normalized text.

    Post: 1.0 for identical prose, 0.0 when either side normalizes to nothing,
          and symmetric — similarity(a, b) == similarity(b, a).
    Changing this formula invalidates every threshold in this module.

    `autojunk=False` is load-bearing, not a tuning knob. SequenceMatcher's
    autojunk heuristic discards any element appearing in more than 1% of a
    sequence longer than 200 elements. Over character sequences that means the
    space and most common letters, and every day template is longer than 200
    characters. It also junks only the second argument, which makes the ratio
    depend on argument order.

        MEASURED on one day against the template it was edited from:
        jaccard 0.827, sequence ratio 0.205 with autojunk and 0.924 without —
        a combined score of 0.516 against 0.875 for the same pair.
    """
    jaccard, sequence = similarity_parts(day_text, template_text)
    return round(0.5 * jaccard + 0.5 * sequence, 3)


def jaccard_lower_bound(threshold: float) -> float:
    """
    The smallest token overlap that could still reach `threshold`.

    Exact, not heuristic. The score is `0.5·jaccard + 0.5·sequence` and the
    sequence ratio cannot exceed 1, so reaching `threshold` requires
    `jaccard >= 2·threshold - 1`. A pair below that cannot clear the threshold
    however similar its character sequence is, which makes this a safe filter
    to run before the expensive half of the comparison.

    Post: never negative — a threshold at or below 0.5 admits everything.
    """
    return max(0.0, 2.0 * threshold - 1.0)


def token_overlap(left_tokens: set, right_tokens: set) -> float:
    """Jaccard over token sets, the cheap half of `similarity`."""
    union = left_tokens | right_tokens
    return len(left_tokens & right_tokens) / len(union) if union else 0.0


def band_for(score: float, reordered: bool = False) -> str:
    """
    Post: exactly one of BAND_MATCH, BAND_NEAR_MISS, BAND_NO_MATCH.

    A reordered pair is neither a match nor an edit, whatever it scores. Two
    itineraries with the same words in the opposite order are opposite journeys.
    The score cannot see that: token overlap is blind to order and carries half
    the weight. MEASURED on a reversed three-sentence day: jaccard 1.000,
    sequence 0.671, score 0.836 — above the 0.80 threshold, so without this rule
    the catalogue would accept a route as its own mirror.

    It is not an edit either. Calling it one would propose replacing the mirror
    template with the reversed wording, which is worse than creating a
    duplicate. It is a day the catalogue does not express, and the proposal
    built from it carries the mirror's code so a human decides whether the
    reversed route deserves its own row.
    """
    if reordered:
        return BAND_NO_MATCH
    if score >= MATCH_THRESHOLD:
        return BAND_MATCH
    if score >= NEAR_MISS_FLOOR:
        return BAND_NEAR_MISS
    return BAND_NO_MATCH


def rank_templates(day_text: str, template_texts: dict) -> list[TemplateMatch]:
    """
    Score every template against one day and return the results ranked.

    Pre:  `template_texts` maps template code to its full text.
    Post: one TemplateMatch per template with non-empty text, ordered by
          descending score then ascending code. Templates with blank text are
          omitted, not scored as zero.

    Ties break on code so the ranking is stable across runs — dictionary order
    follows directory listing order, which is not a property to depend on.

    Ranking rather than taking the maximum exposes two things a single winner
    hides: a day two templates both accept, and a day none accepts but one
    nearly does.
    """
    matches = []
    for code, text in template_texts.items():
        if not (text or "").strip():
            continue
        jaccard, sequence = similarity_parts(day_text, text)
        score = round(0.5 * jaccard + 0.5 * sequence, 3)
        reordered = is_reordered(jaccard, sequence)
        matches.append(TemplateMatch(
            code=code, score=score, band=band_for(score, reordered),
            jaccard=round(jaccard, 3), sequence=round(sequence, 3),
            reordered=reordered,
        ))
    matches.sort(key=lambda m: (-m.score, m.code))
    return matches


def ambiguous_rivals(ranked: list[TemplateMatch]) -> list[str]:
    """
    Codes that tie the winner closely enough to be a coin flip.

    Pre:  `ranked` is the output of rank_templates.
    Post: empty unless the top match is a BAND_MATCH and another match is both
          a BAND_MATCH and within AMBIGUITY_MARGIN of it.
    """
    if not ranked or ranked[0].band != BAND_MATCH:
        return []
    best = ranked[0]
    return [m.code for m in ranked[1:]
            if m.band == BAND_MATCH and best.score - m.score <= AMBIGUITY_MARGIN]
