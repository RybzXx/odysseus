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
import hashlib
import logging
import re
from datetime import date, datetime
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from typing import Callable, Iterator, Optional

from routes.email_helpers import _detect_sent_folder, _imap

from services.offers.models import SentOffer
from services.offers.offer_store import (
    is_stored,
    offers_of_message,
    store_offer,
    store_thread_source,
)
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

# One message id inside a References or In-Reply-To header.
_MESSAGE_ID_RE = re.compile(r"<[^<>\s]+@[^<>\s]+>")

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


def _message_key(message) -> str:
    """
    The id both walks store an offer under.

    Post: the Message-ID as the sender wrote it, or a digest of the headers that
          identify the message when it carries none.

    The digest replaces an IMAP sequence number. A number is assigned by the
    server per session and changes between them, so an offer stored under one
    could never be found again, and the thread walk could never reach it. Date,
    subject, recipient and sender together do not move.
    """
    message_id = _header_text(message.get("Message-ID"))
    if message_id:
        return message_id
    identifying = "\x1f".join(
        _header_text(message.get(header))
        for header in ("Date", "Subject", "To", "From")
    )
    return "nomsgid-" + hashlib.sha1(identifying.encode("utf-8")).hexdigest()[:16]


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


def _own_parts(part) -> Iterator:
    """
    Yield the message's own parts, and never the parts of one it carries.

    `Message.walk` descends into a `message/rfc822` part, and the message inside
    has text parts with no filename. A forwarded-as-attachment mail would then
    hand its sender's words back as ours. The traversal stops at that boundary.
    """
    content_type = part.get_content_type()
    if content_type == "message/rfc822":
        return
    if part.get_content_maintype() == "multipart":
        for child in part.get_payload():
            yield from _own_parts(child)
        return
    yield part


def _message_body(message) -> tuple:
    """
    Yield (plain, html) for the message's own body.

    Post: the first non-attachment text part of each kind, decoded. A message
          with no body of a kind gives "" for that kind. A message the sender
          forwarded as an attachment contributes nothing.

    The body is what the quoted history lives in, and the quoted history is the
    only surviving copy of the request the offer answered. A part with a
    filename is an attachment and is skipped here, whatever its content type —
    an .html attachment is not the message's body.
    """
    plain, html = "", ""
    for part in _own_parts(message):
        if _header_text(part.get_filename()):
            continue
        content_type = part.get_content_type()
        if content_type not in ("text/plain", "text/html"):
            continue
        if content_type == "text/plain" and plain:
            continue
        if content_type == "text/html" and html:
            continue
        try:
            data = part.get_payload(decode=True)
        except Exception:
            continue
        if not data:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            decoded = data.decode(charset, errors="replace")
        except LookupError:
            decoded = data.decode("utf-8", errors="replace")
        if content_type == "text/plain":
            plain = decoded
        else:
            html = decoded
    return plain, html


def _message_ids(raw: str) -> list:
    """
    Every message id in one header, each written `<id>`.

    Post: ids in the order the header names them, with no repeats.

    Two shapes reach this. RFC 5322 allows a comment after an id, and mailers
    write them — "<parent@x> (message from Simone)". Others omit the angle
    brackets. An id kept in either shape matches no stored offer, so both are
    normalised here rather than at every reader.
    """
    if not raw:
        return []
    ordered, seen = [], set()
    bracketed = _MESSAGE_ID_RE.findall(raw)
    if bracketed:
        candidates = bracketed
    else:
        candidates = [piece.strip("<>,;") for piece in raw.split() if "@" in piece]
    for candidate in candidates:
        identifier = candidate.strip().strip("<>")
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        ordered.append(f"<{identifier}>")
    return ordered


def _thread_headers(message) -> tuple:
    """
    Post: (in_reply_to, references) as message ids, each written `<id>`.
          `in_reply_to` is "" when the header names none.

    `References` names the whole chain and `In-Reply-To` names the parent. Both
    are recorded because a mailer that writes one and not the other is common,
    and the pair is what ws-03 D20 walks backwards through.
    """
    parents = _message_ids(_header_text(message.get("In-Reply-To")))
    references = _message_ids(_header_text(message.get("References")))
    return (parents[0] if parents else ""), references


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

            message_id = _message_key(message)
            body_text, body_html = _message_body(message)
            in_reply_to, references = _thread_headers(message)

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
                    in_reply_to=in_reply_to,
                    references=references,
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
                    store_offer(offer, data_bytes, text, body_text, body_html)
                manifest["offers_stored"] += 1
                manifest["stored"].append(message_id)
                if on_offer is not None:
                    on_offer(offer)

    return manifest


def fetch_sent_threads(
    account_id: str,
    owner: str,
    since: date,
    before: date,
    on_message: Optional[Callable] = None,
    dry_run: bool = False,
) -> dict:
    """
    Add the body and thread headers to offers the corpus already holds.

    The first walk kept the attachment and discarded the message it arrived on.
    The quoted request lives in that message, and INBOX holds nothing older than
    five weeks, so the Sent folder is the only place it survives (ws-03 D22).

    Pre:  `account_id` names a configured account owned by `owner`;
          `since` < `before`; the corpus already holds the offers.
    Post: every stored offer whose message falls in the window carries
          `body.txt`, `body.html`, `in_reply_to` and `references`. No
          `source.<ext>` and no `text.txt` is written, so invariant 1.1 holds
          and the extracted text is untouched. With `dry_run`, nothing is
          written and the counts report what a real run would write.

    Blame: a message the corpus does not hold is skipped, not stored — this
    walk adds context to known offers and never adds an offer. A message the
    server will not return is recorded in `failures` and does not stop the walk.

    Returns a manifest: counts, plus the message ids updated and skipped.
    """
    if since >= before:
        raise ValueError(f"empty window: since {since} is not before {before}")

    manifest = {
        "account_id": account_id,
        "since": since.isoformat(),
        "before": before.isoformat(),
        "messages_scanned": 0,
        "messages_in_corpus": 0,
        "records_updated": 0,
        "bodies_empty": 0,
        "with_headers": 0,
        "updated": [],
        "not_in_corpus": 0,
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

        for number in (data[0] or b"").split():
            manifest["messages_scanned"] += 1
            try:
                status, payload = conn.fetch(number, "(RFC822)")
                if status != "OK" or not payload or not isinstance(payload[0], tuple):
                    continue
                message = email.message_from_bytes(payload[0][1])
            except Exception as exc:
                manifest["failures"].append({"message": number.decode(), "reason": str(exc)})
                continue

            message_id = _message_key(message)
            if not offers_of_message(message_id):
                manifest["not_in_corpus"] += 1
                continue
            manifest["messages_in_corpus"] += 1

            body_text, body_html = _message_body(message)
            in_reply_to, references = _thread_headers(message)
            if not (body_text or body_html):
                manifest["bodies_empty"] += 1
            if in_reply_to or references:
                manifest["with_headers"] += 1

            if dry_run:
                written = offers_of_message(message_id)
            else:
                written = store_thread_source(
                    message_id, body_text, body_html, in_reply_to, references)
            manifest["records_updated"] += len(written)
            manifest["updated"].append(message_id)
            if on_message is not None:
                on_message(message_id, len(written))

    return manifest
