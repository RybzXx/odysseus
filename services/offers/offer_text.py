"""
services/offers/offer_text.py

Turns a sent attachment into text, and text into days.

Deterministic by design: no model is involved, so re-running the extraction on
the same attachment always yields the same corpus. The offer as sent is the
authority (ws-03 invariant 1.1), and an extraction that varied between runs
would put that authority behind a moving target.
"""
from __future__ import annotations

import io
import re
import zipfile

from services.offers.models import OfferDay

# A day block ends where the offer's closing matter begins. Without this the
# final day swallows the whole trailer — inclusions, pricing tables, visa notes,
# currency advice, office addresses.
#
#     MEASURED over 164 offers: 158 day blocks exceeded 400 words, all 158 were
#     the last day of their offer, one per offer. These markers terminate 158 of
#     158. Median last-day length falls from 1186 words to 78.
_TRAILER_MARKER_RE = re.compile(
    r"(?im)^\s*(?:end\s+of\s+(?:the\s+)?tour"
    r"|includes?\s*:"
    r"|inclusions?\s*:"
    r"|pricing\s*:"
    r"|price\s*:"
    r"|optional\s*:"
    r"|general\s+information\s*:"
    r"|notes?\s*:)\s*$"
)

# PDF extraction flattens the closing matter onto the same line as the last
# day, so the anchored markers never fire. Only the unambiguous section
# headings are matched loosely: "Optional:" and "Notes:" can legitimately
# appear inside a day and would truncate it, while "End of tour" and
# "General Information" cannot.
_LOOSE_TRAILER_MARKER_RE = re.compile(
    r"(?i)\b(?:end\s+of\s+(?:the\s+)?tour"
    r"|includes?\s*:"
    r"|inclusions?\s*:"
    r"|general\s+information\s*:?)"
)

# A .docx offer puts each day heading on its own line. A PDF often does not:
# extraction can flatten a whole itinerary onto one line, with the day marker
# buried mid-sentence and its spacing doubled. The strict form is preferred
# because it cannot mistake prose for a heading; the loose form covers the rest.
_DAY_HEADER_RE = re.compile(r"(?im)^\s*Day\s+(\d+)\b")
_LOOSE_DAY_HEADER_RE = re.compile(r"(?i)\bDay\s{1,4}(\d{1,2})\b")

_WHITESPACE_RUN_RE = re.compile(r"\s+")
_OVERNIGHT_RE = re.compile(r"(?i)Overnight:\s*([^/\n]+?)\s*(?:/|night|$)")
_GROUP_HINT_RE = re.compile(r"(?i)\bgroup\b")

_XML_PARAGRAPH_END_RE = re.compile(r"</w:p>")
_XML_TAG_RE = re.compile(r"<[^>]+>")
_BLANK_RUN_RE = re.compile(r"\n{3,}")

_XML_ENTITIES = (
    ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'"),
)


class OfferTextError(Exception):
    """Raised when an attachment cannot be turned into text at all."""


def _docx_text(data: bytes) -> str:
    """A .docx is a zip; the visible prose lives in word/document.xml."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", "ignore")
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise OfferTextError(f"unreadable .docx: {exc}") from exc
    text = _XML_PARAGRAPH_END_RE.sub("\n", xml)
    text = _XML_TAG_RE.sub("", text)
    for entity, char in _XML_ENTITIES:
        text = text.replace(entity, char)
    return _BLANK_RUN_RE.sub("\n\n", text)


def _pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:                                  # pragma: no cover
        raise OfferTextError("pypdf is not installed") from exc
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:
        raise OfferTextError(f"unreadable .pdf: {exc}") from exc
    return _BLANK_RUN_RE.sub("\n\n", "\n".join(pages))


def extract_offer_text(data: bytes, filename: str) -> str:
    """
    Return the visible text of one offer attachment.

    Pre:  `data` is the attachment's bytes, `filename` carries its extension.
    Post: a non-empty string, or OfferTextError naming why not.

    Blame: an OfferTextError is a property of the attachment, not of the caller.
    The caller records it in the exclusions list and moves to the next offer.
    """
    lowered = (filename or "").lower()
    if lowered.endswith(".docx"):
        text = _docx_text(data)
    elif lowered.endswith(".pdf"):
        text = _pdf_text(data)
    elif lowered.endswith((".txt", ".md")):
        text = data.decode("utf-8", "ignore")
    else:
        raise OfferTextError(f"unsupported attachment type: {filename}")
    if not text.strip():
        raise OfferTextError(f"no text recovered from {filename}")
    return text


# PDF extraction leaves layout debris in the prose: bullet glyphs that were
# list markers, runs of spaces where the page had columns, and line breaks
# dropped mid-sentence so single words sit alone between newlines. None of it
# is content, and all of it would reach a customer's document verbatim if a day
# went into the catalogue unclean.
_BULLET_GLYPH_RE = re.compile(r"[◆●▪▶•‣⁃]")
_LEADING_PUNCTUATION_RE = re.compile(r"^[\s/|,;:.–—-]+")
_LINE_BREAK_SENTINEL = "\x00"


def tidy_day_text(block: str) -> str:
    """
    Remove layout debris from one day's prose, changing no words.

    Pre:  `block` is a day's text **as extracted**, not text this function has
          already returned. Applying it twice is a caller bug: a PDF's newlines
          are noise to be joined while this function's newlines are structure to
          be kept, and once the bullets are gone the two are indistinguishable.
          Nothing in this package re-tidies — `reparse_stored` always starts
          from the stored raw extraction, so the result depends on the
          attachment alone and not on how many passes have run.
    Post: bullet glyphs become line breaks, every other whitespace run becomes a
          single space, and leading punctuation is dropped. Word content is
          untouched — this repairs typography, it does not rewrite prose, so it
          is safe to run without a model and without review.
    """
    text = _BULLET_GLYPH_RE.sub(_LINE_BREAK_SENTINEL, block or "")
    text = _WHITESPACE_RUN_RE.sub(" ", text)
    lines = [_LEADING_PUNCTUATION_RE.sub("", part).strip()
             for part in text.split(_LINE_BREAK_SENTINEL)]
    return "\n".join(line for line in lines if line)


def trim_trailer(block: str) -> str:
    """
    Cut a day block where the offer's closing matter begins.

    Post: the returned text contains no trailer marker on its own line, and no
          unambiguous section heading anywhere once the anchored form has found
          nothing. The anchored form is preferred because it cannot mistake a
          sentence for a heading.
    """
    block = block or ""
    match = _TRAILER_MARKER_RE.search(block) or _LOOSE_TRAILER_MARKER_RE.search(block)
    return block[:match.start()] if match else block


def day_number_run(numbers: list) -> list:
    """
    The itinerary hiding in a list of day numbers.

    Post: the indices of a run that starts at 1 and only ever holds or advances
          by one. Anything that does not fit is dropped rather than fatal — a
          real offer can mention "Day 6" inside a hotel table, and vetoing the
          whole document over one stray number loses the offer entirely.

    An itinerary is "Day 1 ... Day 2 ..."; a catalogue that happens to name
    several day counts produces no run at all.
    """
    kept, current = [], None
    for index, number in enumerate(numbers):
        if current is None:
            if number == 1:
                kept.append(index)
                current = 1
        elif number in (current, current + 1):
            kept.append(index)
            current = number
    return kept


def is_day_sequence(numbers: list) -> bool:
    """Post: True when these numbers contain an itinerary of at least two days."""
    return len(day_number_run(numbers)) >= 2


def _day_headers(text: str) -> list:
    """
    Post: the matches that delimit this offer's days, strict form preferred.
          Empty when neither form contains an itinerary.

    A single day is accepted from the strict form but not the loose one. A line
    that begins with "Day 1" is unambiguous, so a one-day offer is real; a
    "Day 1" found mid-sentence needs a second day to corroborate it, or every
    brochure that mentions a day would enter the corpus as an itinerary.
    """
    best = []
    for matches, minimum in ((list(_DAY_HEADER_RE.finditer(text)), 1),
                             (list(_LOOSE_DAY_HEADER_RE.finditer(text)), 2)):
        run = day_number_run([int(m.group(1)) for m in matches])
        # The longer itinerary wins. Taking the strict form's answer just
        # because it came first would settle for one stray "Day 1" line in a
        # PDF whose remaining days are all mid-line.
        if len(run) >= minimum and len(run) > len(best):
            best = [matches[index] for index in run]
    return best


def split_days(text: str) -> list[OfferDay]:
    """
    Split an offer's text into its day blocks.

    Pre:  `text` is one offer's full extracted text.
    Post: days in document order, numbered as the document numbers them, each
          trimmed at the trailer and each carrying its overnight city ("" when
          the day is a day trip or a departure).

          An empty list means the document has no itinerary in it. That is a
          fact about the document — a catalogue, a rooming list, a company
          profile — not a parse failure, and the caller records it as such
          rather than storing a nought-day offer.
    """
    text = text or ""
    headers = _day_headers(text)
    days = []
    for index, header in enumerate(headers):
        start = header.end()
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        block = text[start:end].strip()
        overnight = _OVERNIGHT_RE.search(block)
        days.append(OfferDay(
            day_number=int(header.group(1)),
            text=tidy_day_text(trim_trailer(block)),
            overnight_city=overnight.group(1).strip() if overnight else "",
        ))
    return days


def detect_tour_type(text: str, subject: str = "") -> str:
    """
    Post: "group" when either the subject or the opening of the offer says so,
          "individual" otherwise — the majority case, 142 of 164 in the corpus.
    """
    head = (text or "")[:600]
    return "group" if _GROUP_HINT_RE.search(subject or "") or _GROUP_HINT_RE.search(head) \
        else "individual"
