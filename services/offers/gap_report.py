"""
services/offers/gap_report.py

Measures what the day catalogue covers, and groups what it does not.

The output separates two populations that a single "unmatched" count merges,
and that demand opposite work:

  near miss   — a known template that was edited after generation. Closing it
                is a revision to an existing row.
  no match    — a day the catalogue cannot express. Closing it is a new row.

Grouping the no-match days is what turns hundreds of individual days into a
countable number of candidate templates: a day written once is bespoke, a day
written thirty times is a template nobody has created yet.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Iterable, Optional

from src.constants import GAP_SUMMARY_FILE

from services.offers.day_match import (
    MATCH_THRESHOLD,
    jaccard_lower_bound,
    normalize_day_text,
    rank_templates,
    similarity,
    token_overlap,
)
from services.offers.models import (
    BAND_MATCH,
    BAND_NEAR_MISS,
    DayPattern,
    GapReport,
    OfferDay,
    SentOffer,
)

# Skip the full comparison when token overlap alone rules a pair out. Exact, not
# heuristic: see day_match.jaccard_lower_bound. No true match is lost to it.
_PREFILTER_FLOOR = jaccard_lower_bound(MATCH_THRESHOLD)


def day_key(offer: SentOffer, day: OfferDay) -> str:
    """Addresses one day inside one offer, stable across runs."""
    return f"{offer.message_id}#{day.day_number}"


def _pattern_id(text: str) -> str:
    """Content-addressed, so a pattern keeps its identity between passes."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def classify_days(offers: Iterable[SentOffer], template_texts: dict) -> list[tuple]:
    """
    Score every day in every offer against the catalogue, in place.

    Pre:  `template_texts` maps template code to full text.
    Post: each OfferDay carries `best_score`, `band`, and either `matched_code`
          (band match) or `near_miss_code` (band near miss). Returns
          [(offer, day)] for days in no band above no-match, in corpus order.
    """
    unmatched = []
    for offer in offers:
        for day in offer.days:
            ranked = rank_templates(day.text, template_texts)
            best = ranked[0] if ranked else None
            day.best_score = best.score if best else 0.0
            day.band = best.band if best else day.band
            day.matched_code = best.code if best and best.band == BAND_MATCH else None
            day.near_miss_code = best.code if best and best.band == BAND_NEAR_MISS else None
            if day.matched_code is None and day.near_miss_code is None:
                unmatched.append((offer, day))
    return unmatched


def cluster_days(day_pairs: list[tuple]) -> list[DayPattern]:
    """
    Group days that say the same thing into one pattern each.

    Pre:  `day_pairs` is [(offer, day)], typically the no-match days.
    Post: patterns ordered by descending occurrence count; every input day
          belongs to exactly one pattern; a pattern's representative is the
          first day that created it.

    Greedy against representatives rather than all-pairs: the comparison is
    quadratic in patterns, not in days, which is the difference between seconds
    and minutes at corpus scale.
    """
    representatives: list[dict] = []
    for offer, day in day_pairs:
        normalized = normalize_day_text(day.text)
        if not normalized:
            continue
        tokens = set(normalized.split())
        placed = False
        for rep in representatives:
            if token_overlap(tokens, rep["tokens"]) < _PREFILTER_FLOOR:
                continue
            if similarity(day.text, rep["text"]) >= MATCH_THRESHOLD:
                rep["members"].append(day_key(offer, day))
                placed = True
                break
        if not placed:
            representatives.append({
                "text": day.text,
                "normalized": normalized,
                "tokens": tokens,
                "overnight_city": day.overnight_city,
                "members": [day_key(offer, day)],
            })

    patterns = [
        DayPattern(
            pattern_id=_pattern_id(rep["normalized"]),
            representative_text=rep["text"],
            occurrences=len(rep["members"]),
            overnight_city=rep["overnight_city"],
            member_keys=rep["members"],
        )
        for rep in representatives
    ]
    patterns.sort(key=lambda p: (-p.occurrences, p.pattern_id))
    return patterns


def analyse_catalogue_gap(offers: Iterable[SentOffer], template_texts: dict) -> GapReport:
    """
    Full pass: classify every day, group what the catalogue cannot express.

    Post: `report.total_days` equals every day in every offer, and
          `matched + near_miss + unmatched` equals it exactly — no day is
          counted twice and none is dropped.
    """
    offers = list(offers)
    unmatched_pairs = classify_days(offers, template_texts)

    report = GapReport()
    for offer in offers:
        for day in offer.days:
            report.total_days += 1
            if day.matched_code:
                report.matched += 1
            elif day.near_miss_code:
                report.near_miss += 1
                report.near_miss_by_code.setdefault(day.near_miss_code, []).append(
                    day_key(offer, day)
                )
            else:
                report.unmatched += 1

    report.patterns = cluster_days(unmatched_pairs)

    matched_codes = {day.matched_code for offer in offers for day in offer.days if day.matched_code}
    referenced = matched_codes | set(report.near_miss_by_code)
    report.never_matched_codes = sorted(c for c in template_texts if c not in matched_codes)
    report.never_referenced_codes = sorted(c for c in template_texts if c not in referenced)
    return report


def format_gap_report(report: GapReport, top_patterns: int = 15) -> str:
    """A plain-text summary for a terminal or a log; no side effects."""
    lines = [
        f"days: {report.total_days}",
        f"  matched   {report.matched:>5} ({report.coverage:.1%})",
        f"  near miss {report.near_miss:>5}  (edits to existing templates)",
        f"  unmatched {report.unmatched:>5}  (candidates for new templates)",
        f"patterns: {len(report.patterns)} distinct, "
        f"{len(report.recurring_patterns)} seen more than once",
    ]
    if report.near_miss_by_code:
        ranked = sorted(report.near_miss_by_code.items(), key=lambda kv: -len(kv[1]))
        lines.append("near misses by template: " + ", ".join(
            f"{code} x{len(keys)}" for code, keys in ranked[:10]
        ))
    edited_only = [c for c in report.never_matched_codes if c not in report.never_referenced_codes]
    if edited_only:
        lines.append("templates only ever used in edited form: " + ", ".join(edited_only))
    if report.never_referenced_codes:
        lines.append("templates no offer references at all: "
                     + ", ".join(report.never_referenced_codes))
    for pattern in report.patterns[:top_patterns]:
        preview = " ".join(pattern.representative_text.split())[:80]
        lines.append(f"  x{pattern.occurrences:<4} {pattern.overnight_city or '(day trip)':<14} {preview}")
    return "\n".join(lines)


def summarise(report: GapReport, offer_count: int) -> dict:
    """The report reduced to what a reviewer needs, in a form that survives JSON."""
    return {
        "offers": offer_count,
        "total_days": report.total_days,
        "matched": report.matched,
        "near_miss": report.near_miss,
        "unmatched": report.unmatched,
        "coverage": round(report.coverage, 4),
        "patterns": len(report.patterns),
        "recurring_patterns": len(report.recurring_patterns),
        "near_miss_by_code": {code: len(keys)
                              for code, keys in report.near_miss_by_code.items()},
        "never_matched_codes": report.never_matched_codes,
        "never_referenced_codes": report.never_referenced_codes,
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def save_summary(summary: dict, path: Optional[str] = None) -> str:
    """
    Post: the summary is on disk, written atomically.

    Persisted rather than recomputed because the analysis takes minutes over a
    full corpus, and because the number a reviewer reads should be the one the
    proposal queue was derived from. A fresh measurement beside a stale queue
    would show two different gaps and give no way to tell which is which.
    """
    # Resolved at call time, not bound as a default: a default argument captures
    # the constant when this module is imported, which makes the location
    # impossible to redirect and silently reads the real corpus during tests.
    path = path or GAP_SUMMARY_FILE
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    os.replace(temporary, path)
    return path


def load_summary(path: Optional[str] = None) -> Optional[dict]:
    """Post: the last saved summary, or None when the gap has never been measured."""
    path = path or GAP_SUMMARY_FILE
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None
