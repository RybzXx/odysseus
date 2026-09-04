"""
services/offers/sent_offers.py

Recovers sent offers from the mailbox they were sent from.

This is the only path by which the corpus gains an offer. The attachment as
delivered is the authority for everything downstream (ws-03 invariant 1.1), and
the mailbox is the only surviving copy — the folder of source documents the
previous corpus was built from no longer exists.

Reads only the Sent folder, only within an explicit date window, and never
marks, moves or deletes anything.
"""
from __future__ import annotations

import email
import logging
import re
from datetime import date, datetime
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from typing import Callable, Iterator, Optional

from routes.email_helpers import _detect_sent_folder, _imap

from services.offers.models import SentOffer
from services.offers.offer_store import is_stored, store_offer
from services.offers.offer_text import (
    OfferTextError,
    detect_tour_type,
    extract_offer_text,
    split_days,
)

logger = logging.getLogger(__name__)

# Only these carry an offer. Signature logos and inline images are attachments
# too, and pulling them would fill the corpus with noise.
OFFER_EXTENSIONS = (".docx", ".pdf")

_IMAP_DATE_FORMAT = "%d-%b-%Y"

# Matches a filename ending in an offer extension anywhere in a BODYSTRUCTURE
# response. Deliberately loose: it decides only whether the message is worth
# downloading, and `_offer_attachments` makes the real decision on the parsed
# message. A false positive costs one wasted fetch; a false negative would lose
# an offer, so the pattern errs toward fetching.
_BODYSTRUCTURE_OFFER_RE = re.compile(rb'\.(?:docx|pdf)"', re.IGNORECASE)
_BODYSTRUCTURE_NUMBER_RE = re.compile(rb"\s*(\d+)\s+\(")

# Messages per BODYSTRUCTURE request. One request for the whole folder is a
# single opaque call that reports no progress and cannot be resumed; one per
# message is 340 round trips. Chunking keeps both costs bounded.
_BODYSTRUCTURE_CHUNK = 50


class SentOfferFetchError(Exception):
    """Raised when the mailbox cannot be searched at all."""


def _header_text(raw) -> str:
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw))).strip()
    except Exception:
        return str(raw).strip()


def _sent_at(message) -> Optional[datetime]:
    raw = message.get("Date")
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None


def _offer_attachments(message) -> Iterator[tuple]:
    """
    Yield (filename, mime_type, data) for every part that could be an offer.

    Post: only parts with an explicit filename ending in OFFER_EXTENSIONS, so a
          logo or an inline image never reaches the corpus.
    """
    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        filename = _header_text(part.get_filename())
        if not filename or not filename.lower().endswith(OFFER_EXTENSIONS):
            continue
        try:
            data = part.get_payload(decode=True)
        except Exception:
            continue
        if data:
            yield filename, part.get_content_type(), data


def _search_criteria(since: date, before: date) -> str:
    return (f'(SINCE "{since.strftime(_IMAP_DATE_FORMAT)}" '
            f'BEFORE "{before.strftime(_IMAP_DATE_FORMAT)}")')


def _numbers_with_offer_attachment(conn, numbers: list) -> set:
    """
    Ask the server, in one round trip, which messages name a .docx or .pdf part.

    Downloading every message to find out would move hundreds of megabytes
    across a live mailbox to discard most of it, and asking per message is one
    round trip each — 315 of them on a real Sent folder. BODYSTRUCTURE over the
    whole message set answers it once.

    Post: fails open. Any parse or protocol trouble returns every number, so an
          unreadable structure costs a wasted download rather than a lost offer.
    """
    if not numbers:
        return set()

    hits, examined = set(), 0
    for start in range(0, len(numbers), _BODYSTRUCTURE_CHUNK):
        chunk = numbers[start:start + _BODYSTRUCTURE_CHUNK]
        try:
            status, payload = conn.fetch(b",".join(chunk), "(BODYSTRUCTURE)")
        except Exception:
            logger.warning("BODYSTRUCTURE chunk failed; fetching those messages in full",
                           exc_info=True)
            hits.update(chunk)
            continue
        if status != "OK" or not payload:
            hits.update(chunk)
            continue

        current = None
        for part in payload:
            blob = part if isinstance(part, bytes) else b"".join(
                piece for piece in part if isinstance(piece, bytes)
            )
            header = _BODYSTRUCTURE_NUMBER_RE.match(blob)
            if header:
                current = header.group(1)
            if current and _BODYSTRUCTURE_OFFER_RE.search(blob):
                hits.add(current)
        examined += len(chunk)
        logger.info("scanned %d/%d messages, %d carry an offer attachment",
                    examined, len(numbers), len(hits))

    if examined and not hits:
        # Either genuinely nothing, or the parse missed every chunk. The two are
        # indistinguishable here and only one of them is safe to assume.
        logger.info("BODYSTRUCTURE matched nothing; fetching all %d messages", len(numbers))
        return set(numbers)
    return hits


def fetch_sent_offers(
    account_id: str,
    owner: str,
    since: date,
    before: date,
    on_offer: Optional[Callable] = None,
    skip_stored: bool = True,
    dry_run: bool = False,
) -> dict:
    """
    Walk the Sent folder and store every offer attachment found in the window.

    Pre:  `account_id` names a configured account owned by `owner`;
          `since` < `before`.
    Post: every message in the window with a .docx or .pdf attachment has a
          directory in the offer store, or appears in the returned `failures`
          with the reason it does not. The mailbox is unchanged — the folder is
          opened read-only and no flag is set. With `dry_run`, nothing is
          written to disk and the counts report what a real run would store.

    Blame: a message that yields no text is an attachment problem and is
    recorded, not raised; an inability to select the folder is a configuration
    problem and is raised.

    Returns a manifest: counts, plus the ids stored, skipped and failed.
    """
    if since >= before:
        raise ValueError(f"empty window: since {since} is not before {before}")

    manifest = {
        "account_id": account_id,
        "since": since.isoformat(),
        "before": before.isoformat(),
        "messages_scanned": 0,
        "messages_with_attachment": 0,
        "offers_stored": 0,
        "offers_skipped": 0,
        "stored": [],
        "skipped": [],
        "failures": [],
    }

    with _imap(account_id=account_id, owner=owner) as conn:
        folder = _detect_sent_folder(conn)
        status, _ = conn.select(f'"{folder}"', readonly=True)
        if status != "OK":
            raise SentOfferFetchError(f"cannot select sent folder {folder!r}")

        status, data = conn.search(None, _search_criteria(since, before))
        if status != "OK":
            raise SentOfferFetchError(f"search failed in {folder!r}")
        message_numbers = (data[0] or b"").split()
        candidates = _numbers_with_offer_attachment(conn, message_numbers)
        manifest["messages_with_attachment"] = len(candidates)

        for number in message_numbers:
            manifest["messages_scanned"] += 1
            if number not in candidates:
                continue
            try:
                status, payload = conn.fetch(number, "(RFC822)")
                if status != "OK" or not payload or not isinstance(payload[0], tuple):
                    continue
                message = email.message_from_bytes(payload[0][1])
            except Exception as exc:
                manifest["failures"].append({"message": number.decode(), "reason": str(exc)})
                continue

            message_id = _header_text(message.get("Message-ID")) or f"nomsgid-{number.decode()}"

            for filename, mime_type, data_bytes in _offer_attachments(message):
                if skip_stored and is_stored(message_id, filename):
                    manifest["offers_skipped"] += 1
                    manifest["skipped"].append(f"{message_id}#{filename}")
                    continue
                offer = SentOffer(
                    message_id=message_id,
                    subject=_header_text(message.get("Subject")),
                    sent_at=_sent_at(message),
                    recipients=[r for r in (_header_text(message.get("To")) or "").split(",") if r],
                    attachment_name=filename,
                    attachment_mime=mime_type,
                    attachment_bytes=len(data_bytes),
                )
                try:
                    text = extract_offer_text(data_bytes, filename)
                except OfferTextError as exc:
                    manifest["failures"].append(
                        {"message_id": message_id, "attachment": filename, "reason": str(exc)}
                    )
                    continue

                offer.tour_type = detect_tour_type(text, offer.subject)
                offer.days = split_days(text)
                if not offer.days:
                    # A catalogue, a rooming list, a company profile. It was
                    # attached to a sent mail but it is not an offer, and
                    # storing it would put documents with no itinerary into a
                    # corpus whose whole purpose is itineraries.
                    manifest["failures"].append(
                        {"message_id": message_id, "attachment": filename,
                         "reason": "no itinerary in this document"}
                    )
                    continue

                if not dry_run:
                    store_offer(offer, data_bytes, text)
                manifest["offers_stored"] += 1
                manifest["stored"].append(message_id)
                if on_offer is not None:
                    on_offer(offer)

    return manifest
