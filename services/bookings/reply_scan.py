"""
services/bookings/reply_scan.py

Which registrations book@bilweekend.com has already answered.

The admin panel holds a follow-up status an operator sets by hand. On
2026-09-09 it marked 21 of 23 bookings 'Replied', and 8 of those had never been
answered — they were test submissions somebody had tidied away. The mailbox
disagreed with the panel on every row where the two differed, and the mailbox
was right each time.

So this reads the mailbox. A registration counts as answered when a message in
the Sent folder is addressed to it, after it was submitted. That rule found all
13 real registrations and none of the 10 test rows, with no reference code, no
subject rule and no thread header. Lag ran 0 to 17 days, median 2.

Why the match runs on a hash
---------------------------
Matching needs the registrants' addresses, and an address is customer data the
`attention` endpoint carries only in its `full` mode — the mode that arms the
external-context gate. A run that fetched the list that way could match and
would then be forbidden to report what it found.

So the website sends an HMAC of each address instead of the address, keyed on
the shared `OPS_AGENT_TOKEN`, and this module hashes each Sent recipient the
same way. The comparison is identical, nothing readable about a customer
crosses, and the gate stays shut without widening `structural` by one field.

This is not privacy theatre. Odysseus can already read every address in the
mailbox. What it must not do is *receive a customer list from the website*,
because that is the transfer the gate is written about.

What this does not do
---------------------
It writes no follow-up field. The hand-set status stays where it is and still
wins, which is what covers the replies this scan cannot see: a customer
answered on WhatsApp, or writing from an address they did not register with
(ws-bd 7.6, 7.8).

It also marks, moves and deletes nothing. The connection and folder detection
come from `services.offers.sent_offers`, which already reads Sent read-only
inside an explicit window, so there is one IMAP path here rather than two.
"""
from __future__ import annotations

import email
import hashlib
import hmac
import logging
import os
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from typing import Iterable, Optional

from routes.email_helpers import _detect_sent_folder, _imap

logger = logging.getLogger(__name__)

# The mailbox registrations are answered from.
#
# Named rather than defaulted: Odysseus holds four accounts, and scanning the
# owner's personal Sent folder for a customer's address would find nothing and
# say the registration went unanswered.
BOOKING_MAILBOX = "book@bilweekend.com"

# How far back a scan looks when the caller names no window.
#
# Long enough to cover the slowest observed reply (17 days) many times over,
# and short enough that a routine scan does not walk 3,000 messages.
DEFAULT_WINDOW_DAYS = 120

_ADDRESS = re.compile(r"[\w.+-]+@[\w.-]+")


def booking_account_id() -> Optional[str]:
    """
    Post: the account id that sends as `BOOKING_MAILBOX`, or None.

    Named rather than left to the default account. The default is that mailbox
    today, and a fifth account added tomorrow would silently move the scan to
    somebody's inbox where no customer address appears at all.
    """
    from core.database import EmailAccount, SessionLocal

    try:
        session = SessionLocal()
        try:
            row = (session.query(EmailAccount)
                   .filter(EmailAccount.from_address == BOOKING_MAILBOX)
                   .first())
            return row.id if row else None
        finally:
            session.close()
    except Exception:
        logger.warning("could not resolve the %s account", BOOKING_MAILBOX,
                       exc_info=True)
        return None


class ReplyScanError(Exception):
    """The mailbox could not be read. The scan reports nothing rather than none.

    An empty result and an unreachable mailbox look identical to a caller that
    cannot tell them apart, and the second one must not clear a panel that was
    showing replies a minute ago.
    """


def _header(message, name: str) -> str:
    """Post: the decoded header, or "". Never raises on a malformed one."""
    try:
        return str(make_header(decode_header(message.get(name, "") or "")))
    except Exception:
        return message.get(name, "") or ""


def _recipients(message) -> set[str]:
    """
    Post: every address in To and Cc, lowercased.

    Cc counts. A registration answered with the customer in copy is answered,
    and reading To alone would call it silent.
    """
    raw = f"{message.get('To') or ''} {message.get('Cc') or ''}"
    return {a.lower() for a in _ADDRESS.findall(raw)}


def _sent_at(message) -> Optional[datetime]:
    """Post: an aware datetime, or None when the header is unusable."""
    try:
        value = parsedate_to_datetime(message.get("Date"))
    except Exception:
        return None
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def read_sent_headers(since: Optional[date] = None,
                      account_id: Optional[str] = None) -> list[tuple[datetime, set, str]]:
    """
    Every message the Sent folder holds since `since`, as headers only.

    Pre:  the account bound to `book@bilweekend.com` is configured.
    Post: (sent_at, recipients, subject) per message, oldest first.
    Inv:  BODY.PEEK, so nothing is marked read. Nothing is moved or deleted.

    Raises ReplyScanError when the mailbox cannot be read, so a caller never
    mistakes an outage for an empty folder.
    """
    window_start = since or (date.today() - timedelta(days=DEFAULT_WINDOW_DAYS))
    criteria = f'(SINCE {window_start.strftime("%d-%b-%Y")})'

    found: list[tuple[datetime, set, str]] = []
    try:
        with _imap(account_id) as conn:
            folder = _detect_sent_folder(conn)
            status, _ = conn.select(f'"{folder}"', readonly=True)
            if status != "OK":
                raise ReplyScanError(f"Could not open '{folder}'.")

            status, data = conn.search(None, criteria)
            if status != "OK":
                raise ReplyScanError(f"Search failed in '{folder}'.")
            numbers = data[0].split()

            # Fetched in blocks. One round trip per message over 185 of them is
            # the difference between a scan that finishes and one that times
            # out on a phone's connection.
            for start in range(0, len(numbers), 200):
                block = b",".join(numbers[start:start + 200])
                status, rows = conn.fetch(
                    block, "(BODY.PEEK[HEADER.FIELDS (DATE TO CC SUBJECT)])")
                if status != "OK":
                    continue
                for row in rows:
                    if not isinstance(row, tuple):
                        continue
                    message = email.message_from_bytes(row[1])
                    when = _sent_at(message)
                    if when is None:
                        continue
                    found.append((when, _recipients(message),
                                  _header(message, "Subject")))
    except ReplyScanError:
        raise
    except Exception as exc:
        raise ReplyScanError(f"Could not read {BOOKING_MAILBOX}: {exc}") from exc

    found.sort(key=lambda item: item[0])
    return found


def hash_address(address: str, key: str) -> str:
    """
    Post: the HMAC the website computes for the same address, or "" for none.

    Pre:  `key` is the shared OPS_AGENT_TOKEN. Both sides must use the same one
          or nothing matches and every registration reads as unanswered.

    Lowercased first. Gmail treats the local part as case-insensitive, and one
    observed registration typed an address the reply came back to in a
    different case.
    """
    cleaned = str(address or "").strip().lower()
    if not cleaned or not key:
        return ""
    return hmac.new(key.encode("utf-8"), cleaned.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def match_replies(bookings: Iterable[dict],
                  sent: list[tuple[datetime, set, str]],
                  key: str = "") -> list[dict]:
    """
    Which registrations the Sent folder answered.

    Pre:  each booking names `bookingId` and `submittedAt`, plus either
          `addressHash` (the website's HMAC) or `email`. `sent` is oldest
          first, as `read_sent_headers` returns it.
    Post: one entry per answered booking, holding the first reply and how many
          followed. A booking with no reply produces no entry at all.
    Inv:  a message must post-date the submission. Without that, a customer who
          wrote in before registering would make every registration look
          answered before it arrived.

    Blame: a booking with an unparseable `submittedAt` is skipped rather than
    matched on the address alone, because the date is the half of the rule that
    stops a stale thread counting.
    """
    rows = list(bookings)
    hashing = bool(key) and any("addressHash" in row for row in rows)

    # Hashed once per message, not once per booking. Twenty-three registrations
    # against 185 messages is 4,255 comparisons, and hashing inside the inner
    # loop would compute the same digest for each of them.
    prepared = [
        (when, _hashed(recipients, key) if hashing else recipients, subject)
        for when, recipients, subject in sent
    ]

    answered: list[dict] = []
    for booking in rows:
        wanted = str(
            booking.get("addressHash") if hashing else booking.get("email") or ""
        ).strip().lower()
        if not wanted:
            continue
        submitted = _as_datetime(booking.get("submittedAt"))
        if submitted is None:
            continue

        hits = [(when, subject) for when, recipients, subject in prepared
                if wanted in recipients and when >= submitted]
        if not hits:
            continue
        first_at, first_subject = hits[0]
        answered.append({
            "bookingId": booking.get("bookingId") or booking.get("id"),
            "repliedAt": first_at.isoformat(),
            "replySubject": first_subject,
            "replyCount": len(hits),
        })
    return answered


def _hashed(addresses: set, key: str) -> set:
    """Post: the same set, each address as its HMAC."""
    return {hash_address(a, key) for a in addresses}


def _as_datetime(value) -> Optional[datetime]:
    """
    Post: an aware datetime at the start of the submission day, or None.

    Truncated to the day on purpose. Three of the 13 matched replies were sent
    the same day the registration arrived, and comparing to the minute would
    drop one answered inside the hour before the timestamp the site recorded.
    """
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.replace(hour=0, minute=0, second=0, microsecond=0)


def scan(bookings: Iterable[dict], since: Optional[date] = None,
         account_id: Optional[str] = None, key: str = "") -> list[dict]:
    """
    Read the Sent folder and say which of these registrations it answered.

    Post: the payload for POST /api/agent/ops/booking-replies.
    Inv:  read-only throughout. Raises ReplyScanError rather than returning an
          empty list when the mailbox is unreachable.
    """
    rows = list(bookings)
    if not rows:
        return []
    sent = read_sent_headers(since=since,
                             account_id=account_id or booking_account_id())
    matched = match_replies(rows, sent, key=key or os.environ.get("OPS_AGENT_TOKEN", ""))
    logger.info("reply scan: %d of %d registrations answered, %d sent messages read",
                len(matched), len(rows), len(sent))
    return matched


def counts_by_day(replies: list[dict]) -> dict:
    """Post: how many replies landed per calendar day. For a run's report."""
    tally: dict = defaultdict(int)
    for reply in replies:
        tally[str(reply.get("repliedAt", ""))[:10]] += 1
    return dict(tally)
