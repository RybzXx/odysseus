"""
BilWeekend — Itinerary Reader
Reads a generated itinerary Google Doc back into structured form, and recovers
each day's template code by matching its prose against data/templates/.

The document is authoritative: itineraries are routinely hand-edited after
generation, so nothing here trusts the generator's own records.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from services.itinerary.pipeline import config
from services.itinerary.pipeline import google_clients

# Scoring lives in services.offers.day_match, and only there. Two copies of a
# similarity formula is exactly how the earlier port acquired five regressions:
# each side drifts, and a day scores differently depending on which code path
# reached it. Reading a document back and measuring the catalogue gap are the
# same question — "which template is this day?" — so they share one answer.
from services.offers.day_match import (      # noqa: E402
    AMBIGUITY_MARGIN,
    MATCH_THRESHOLD,
    NEAR_MISS_FLOOR,
    ambiguous_rivals,
    normalize_day_text,
    rank_templates,
    similarity,
)
from services.offers.models import (         # noqa: E402
    BAND_MATCH,
    BAND_NEAR_MISS,
    BAND_NO_MATCH,
    TemplateMatch,
)

_DAY_HEADER_RE = re.compile(
    r"^Day\s+(\d+)"                                  # Day 7
    r"(?:\s*[—–-]\s*"                      # em dash, en dash or hyphen
    r"(?P<weekday>[A-Za-z]+),\s*"                    # Tuesday,
    r"(?P<day>\d{1,2})\s+"                           # 29
    r"(?P<month>[A-Za-z]+))?"                        # September
)
_OVERNIGHT_RE = re.compile(r"^Overnight:\s*(?P<city>.+?)\s*/\s*night\s*(?P<night>\d+)\s*\.?\s*$")
_CITY_HOTEL_RE = re.compile(r"^(?P<city>[A-Z][A-Za-z \-]{1,24}):\s*(?P<hotel>\S.*)$")
_HOTEL_BLOCK_RE = re.compile(r"^(?:Selected Hotels|\d\s*-?\s*star Hotels?)\s*$", re.IGNORECASE)
_PAX_BAND_RE = re.compile(r"^\s*\d+\s*-\s*\d+\s*PAX")

_MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"], start=1)}


@dataclass
class ItineraryDay:
    day_number: int
    date: Optional[date]
    header: str
    body: str
    overnight_city: Optional[str]
    night_number: Optional[int]
    template_code: Optional[str] = None
    match_score: float = 0.0
    # Set only when no template cleared MATCH_THRESHOLD but one cleared
    # NEAR_MISS_FLOOR: the template this day most likely started life as.
    near_miss_code: Optional[str] = None


@dataclass
class HotelStay:
    """One unbroken run of nights in a single city."""
    city: str
    hotel: str
    check_in: Optional[date]
    check_out: Optional[date]
    nights: int


@dataclass
class ExtractedItinerary:
    doc_id: str
    doc_url: str
    title: str
    tour_type: str                       # "individual" or "group"
    days: list = field(default_factory=list)
    hotels_by_city: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    @property
    def day_code_string(self) -> str:
        """Ops' Destination format: day-of-month prefixed codes, e.g. 23ARRBG-24BG1CT."""
        parts = []
        for day in self.days:
            prefix = str(day.date.day) if day.date else ""
            parts.append(f"{prefix}{day.template_code or ''}")
        return "-".join(part for part in parts if part)

    def stays(self) -> list:
        """Collapse the overnight sequence into one HotelStay per run of nights in a city."""
        out = []
        for index, day in enumerate(self.days):
            city = day.overnight_city
            if not city:
                continue
            next_date = self._next_date(index)
            if out and out[-1].city == city and out[-1].check_out == day.date:
                out[-1].nights += 1
                out[-1].check_out = next_date
                continue
            out.append(HotelStay(
                city=city,
                hotel=self.hotels_by_city.get(city, ""),
                check_in=day.date,
                check_out=next_date,
                nights=1,
            ))
        return out

    def _next_date(self, index: int) -> Optional[date]:
        if index + 1 < len(self.days):
            return self.days[index + 1].date
        return None


class ItineraryReadError(RuntimeError):
    """The document could not be fetched, or no document ID was supplied."""


def parse_doc_id(url_or_id: str) -> str:
    """
    Accept a full Docs URL or a bare document ID.

    Pre:  a non-empty string.
    Post: returns the document ID; raises ItineraryReadError when none is present.
    """
    raw = (url_or_id or "").strip()
    if not raw:
        raise ItineraryReadError("No document link or ID provided.")
    match = re.search(r"/document/d/([A-Za-z0-9_-]+)", raw)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{20,}", raw):
        return raw
    raise ItineraryReadError(f"Could not find a document ID in: {raw[:80]}")


def read_itinerary(doc_id: str) -> ExtractedItinerary:
    """
    Fetch and parse one itinerary document.

    Pre:  doc_id names a document the service account can read.
    Post: returns an ExtractedItinerary; structural gaps land in .warnings
          rather than raising. Only a failed fetch raises.
    """
    try:
        document = google_clients.documents().get(
            documentId=doc_id,
        ).execute(http=google_clients.http())
    except Exception as exc:
        raise ItineraryReadError(f"Could not open the document: {exc}") from exc
    return extract_itinerary(document, doc_id)


def extract_itinerary(document: dict, doc_id: str) -> ExtractedItinerary:
    """Parse an already-fetched Docs payload. Never raises on odd structure."""
    itinerary = ExtractedItinerary(
        doc_id=doc_id,
        doc_url=f"https://docs.google.com/document/d/{doc_id}/edit",
        title=(document.get("title") or "").strip(),
        tour_type="individual",
    )

    blocks = _flatten(document.get("body", {}).get("content", []))
    _collect_days(blocks, itinerary)
    _collect_hotels(blocks, itinerary)
    if any(_PAX_BAND_RE.match(text) for _, text in blocks):
        itinerary.tour_type = "group"

    _assign_dates(itinerary)
    _assign_template_codes(itinerary)

    if not itinerary.days:
        itinerary.warnings.append(
            "No 'Day N' headings found — this may not be an itinerary document."
        )
    if not itinerary.hotels_by_city:
        itinerary.warnings.append(
            "No hotel block found ('Selected Hotels' or 'N-star Hotels')."
        )
    return itinerary


# ── Document flattening ───────────────────────────────────────────────────────

def _flatten(content: list) -> list:
    """Return [(named_style, text)] for every non-empty paragraph, tables included."""
    out = []
    for element in content:
        if "paragraph" in element:
            paragraph = element["paragraph"]
            style = paragraph.get("paragraphStyle", {}).get("namedStyleType", "NORMAL_TEXT")
            text = "".join(
                run.get("textRun", {}).get("content", "")
                for run in paragraph.get("elements", [])
            ).strip()
            if text:
                out.append((style, text))
        elif "table" in element:
            for row in element["table"].get("tableRows", []):
                for cell in row.get("tableCells", []):
                    out.extend(_flatten(cell.get("content", [])))
    return out


def _collect_days(blocks: list, itinerary: ExtractedItinerary) -> None:
    """A day runs from its 'Day N' heading until the next HEADING_2 of any kind."""
    current = None
    body_lines = []

    def close_current():
        if current is not None:
            current.body = "\n".join(body_lines)
            itinerary.days.append(current)

    for style, text in blocks:
        if style == "HEADING_2":
            close_current()
            body_lines = []
            match = _DAY_HEADER_RE.match(text)
            if match:
                current = ItineraryDay(
                    day_number=int(match.group(1)),
                    date=None,
                    header=text,
                    body="",
                    overnight_city=None,
                    night_number=None,
                )
            else:
                current = None
            continue
        if current is None:
            continue
        overnight = _OVERNIGHT_RE.match(text)
        if overnight:
            current.overnight_city = overnight.group("city").strip()
            current.night_number = int(overnight.group("night"))
            continue                     # kept out of the matched body on purpose
        body_lines.append(text)
    close_current()


def _collect_hotels(blocks: list, itinerary: ExtractedItinerary) -> None:
    """Read 'City: Hotel' lines under a hotel-block marker, in either of its two forms."""
    in_block = False
    for style, text in blocks:
        if _HOTEL_BLOCK_RE.match(text):
            in_block = True
            continue
        if not in_block:
            continue
        pair = _CITY_HOTEL_RE.match(text)
        if pair:
            itinerary.hotels_by_city.setdefault(
                pair.group("city").strip(), pair.group("hotel").strip()
            )
            continue
        if style == "HEADING_2" or text.endswith(":"):
            in_block = False


# ── Dates ─────────────────────────────────────────────────────────────────────

def _assign_dates(itinerary: ExtractedItinerary) -> None:
    """
    Headings carry weekday, day and month but never a year.

    Resolve the first dated day by finding the nearby year whose weekday agrees,
    then walk forward, rolling the year over whenever the calendar moves back.
    """
    parsed = []
    for day in itinerary.days:
        match = _DAY_HEADER_RE.match(day.header)
        if match and match.group("month"):
            month = _MONTHS.get(match.group("month").lower())
            if month:
                parsed.append((day, month, int(match.group("day")), match.group("weekday").lower()))
                continue
        parsed.append((day, None, None, None))

    dated = [entry for entry in parsed if entry[1] is not None]
    if not dated:
        itinerary.warnings.append(
            "Day headings carry no dates — start and end dates are unknown."
        )
        return

    first_day, month, day_number, weekday = dated[0]
    year = _resolve_year(month, day_number, weekday)
    if year is None:
        itinerary.warnings.append(
            f"Could not resolve a year for '{first_day.header}' — check the weekday."
        )
        return

    previous = None
    for day, month, day_number, _ in parsed:
        if month is None:
            continue
        if previous is not None and (month, day_number) < previous:
            year += 1
        try:
            day.date = date(year, month, day_number)
        except ValueError:
            itinerary.warnings.append(f"Invalid date in '{day.header}'.")
            continue
        previous = (month, day_number)


def _resolve_year(month: int, day_number: int, weekday: str) -> Optional[int]:
    """Pick the nearby year whose weekday matches the heading."""
    base = date.today().year
    for candidate in (base, base + 1, base - 1, base + 2, base + 3):
        try:
            attempt = date(candidate, month, day_number)
        except ValueError:
            continue
        if attempt.strftime("%A").lower() == weekday:
            return candidate
    return None


# ── Template matching ─────────────────────────────────────────────────────────

def load_template_texts() -> dict:
    """{code: full_text} for every template on disk."""
    texts = {}
    directory = Path(config.TEMPLATES_DIR)
    if not directory.is_dir():
        return texts
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        texts[data.get("code") or path.stem] = data.get("full_text", "")
    return texts


def match_template_code(day_body: str, template_texts: dict) -> tuple:
    """Return (code, score) for the best match, or (None, best_score) below threshold."""
    ranked = rank_templates(day_body, template_texts)
    if not ranked:
        return None, 0.0
    best = ranked[0]
    if best.band != BAND_MATCH:
        return None, best.score
    return best.code, best.score


def _assign_template_codes(itinerary: ExtractedItinerary, template_texts: dict | None = None) -> None:
    # The catalogue is a parameter so a caller can pin it; production passes
    # nothing and reads the same templates the renderer uses.
    if template_texts is None:
        template_texts = load_template_texts()
    if not template_texts:
        itinerary.warnings.append(
            "No day templates on disk — day codes cannot be recovered."
        )
        return
    for day in itinerary.days:
        ranked = rank_templates(day.body, template_texts)
        best = ranked[0] if ranked else None
        day.match_score = best.score if best else 0.0

        if best is not None and best.band == BAND_MATCH:
            day.template_code = best.code
            # Two templates tying on the same day is a catalogue defect, not a
            # matching one. Naming both is the only way it reaches a human.
            rivals = ambiguous_rivals(ranked)
            if rivals:
                itinerary.warnings.append(
                    f"Day {day.day_number}: {best.code} ({best.score:.2f}) chosen over "
                    f"{', '.join(rivals)} — more than one template accepts this day."
                )
            continue

        near = next((m for m in ranked if m.band == BAND_NEAR_MISS), None)
        if near is not None:
            day.near_miss_code = near.code

        is_departure = day.overnight_city is None and day is itinerary.days[-1]
        if is_departure:
            day.template_code = "TRF"    # departure transfer; no template exists for it
        elif near is not None:
            itinerary.warnings.append(
                f"Day {day.day_number}: closest template {near.code} scored {near.score:.2f}, "
                f"below {MATCH_THRESHOLD:.2f} — reads as {near.code} edited after generation, "
                f"not as a new day."
            )
        else:
            itinerary.warnings.append(
                f"Day {day.day_number}: no template matched (best {day.match_score:.2f}) "
                f"— code left blank."
            )
