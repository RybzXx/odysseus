"""
services/offers/models.py

Data models for the sent-offer corpus and the day-catalogue gap analysis.

The corpus is authoritative: an offer as sent to a customer outranks the
generator's own records, which are known to disagree with what was delivered.
Every derived record therefore names the message it came from.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# ── Match bands ───────────────────────────────────────────────────────────────
# A day's best score against the catalogue falls in exactly one band, and the
# band decides the work: a match needs nothing, a near miss is an edit to an
# existing template, and no match is a candidate for a new one.
BAND_MATCH = "match"
BAND_NEAR_MISS = "near_miss"
BAND_NO_MATCH = "no_match"


@dataclass(frozen=True)
class TemplateMatch:
    """One catalogue template scored against one day's prose."""
    code: str
    score: float
    band: str
    # The two halves of the score, kept so a caller can see what the mean hides.
    jaccard: float = 0.0
    sequence: float = 0.0
    # Same words, different order — the route driven the other way. Such a pair
    # is never a match, whatever it scores.
    reordered: bool = False


@dataclass
class OfferDay:
    """One day inside a sent offer."""
    day_number: int
    text: str
    overnight_city: str = ""             # "" for a day trip or a departure day
    # Filled by the gap analysis, not by extraction.
    matched_code: Optional[str] = None
    near_miss_code: Optional[str] = None
    best_score: float = 0.0
    band: str = BAND_NO_MATCH

    @property
    def word_count(self) -> int:
        return len(self.text.split())


@dataclass
class SentOffer:
    """One offer document recovered from the Sent folder, with its provenance."""
    message_id: str
    subject: str
    sent_at: Optional[datetime]
    recipients: list[str] = field(default_factory=list)
    attachment_name: str = ""
    attachment_mime: str = ""
    attachment_bytes: int = 0
    tour_type: str = "individual"        # "individual" | "group"
    days: list[OfferDay] = field(default_factory=list)
    extraction_warnings: list[str] = field(default_factory=list)

    @property
    def day_count(self) -> int:
        return len(self.days)

    @property
    def city_sequence(self) -> list[str]:
        """Overnight cities in order, day trips and departures omitted."""
        return [d.overnight_city for d in self.days if d.overnight_city]


@dataclass
class DayPattern:
    """
    A recurring day shape among days the catalogue does not cover.

    One pattern is one candidate template row. `occurrences` is how many sent
    offers wrote this same day, which is the whole argument for templating it.
    """
    pattern_id: str
    representative_text: str
    occurrences: int
    overnight_city: str
    member_keys: list[str] = field(default_factory=list)   # "<message_id>#<day_number>"

    @property
    def is_recurring(self) -> bool:
        return self.occurrences > 1


@dataclass
class GapReport:
    """What the catalogue covers, and what closing the rest would cost."""
    total_days: int = 0
    matched: int = 0
    near_miss: int = 0
    unmatched: int = 0
    patterns: list[DayPattern] = field(default_factory=list)
    near_miss_by_code: dict = field(default_factory=dict)   # code -> day keys
    # A template no day matched outright. It may still be in daily use — every
    # offer that used it edited it. Distinguishing the two is the difference
    # between retiring a template and revising it.
    never_matched_codes: list[str] = field(default_factory=list)
    # A template no day matched and no day even came close: unused in fact.
    never_referenced_codes: list[str] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        return self.matched / self.total_days if self.total_days else 0.0

    @property
    def recurring_patterns(self) -> list:
        return [p for p in self.patterns if p.is_recurring]
