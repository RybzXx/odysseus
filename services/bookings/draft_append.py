"""
services/bookings/draft_append.py

Files an approved reply into the Gmail Drafts folder of book@bilweekend.com.

THE INVARIANT THIS MODULE EXISTS TO HOLD
----------------------------------------
Nothing here calls a model. Not to summarise, not to check tone, not to
translate, not to decide whether to file. This module opens IMAP, APPENDs a
message and stops.

That is what makes it safe to hand this module a customer's name. Every other
path into the bookings desk avoids customer text on purpose: an offer job names
a tour and a party size, and the reply scan compares HMACs, because the runs
that consume them reason, and a run that has read a customer's words may not
act. This one carries a name, an address and a body, and it is safe for the
opposite reason — there is no reasoning step for injected text to reach.

Adding one would break it. A model asked about `body` is a model reading text a
stranger wrote, inside a process that can write to a mailbox. If that is ever
wanted, it belongs in a run that only reports.

WHAT IT DOES NOT DO
-------------------
It does not send. A draft sits in Drafts until a person opens Gmail and presses
send, which is the whole point: operations read what goes out.

It appends and nothing else. It never marks, moves or deletes a message, and it
never touches a folder other than Drafts.
"""
from __future__ import annotations

import imaplib
import logging
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Optional

from routes.email_helpers import _get_email_config, _imap_connect

from services.bookings.reply_scan import BOOKING_MAILBOX, booking_account_id

logger = logging.getLogger(__name__)

# Where Gmail keeps drafts, in the order to try.
#
# `_detect_sent_folder` has a twin for Sent and none for Drafts, and writing one
# for a single mailbox would be the wrong shape. This list covers Gmail's own
# name and the plain one every other server uses.
DRAFT_FOLDERS = ("[Gmail]/Drafts", "Drafts", "INBOX.Drafts")


class DraftAppendError(Exception):
    """The message could not be filed. The caller reports it and closes the row.

    Never retried automatically. An append that landed and then lost its answer
    would file a second draft on a retry, and two drafts in Gmail are one
    message sent twice.
    """


@dataclass
class DraftAppendOutcome:
    """What the appender has to say about one message."""
    folder: str = ""
    appended_uid: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    def as_result_payload(self) -> dict:
        """Post: the body for POST /api/agent/ops/draft-appends/{id}/result."""
        return {
            "folder": self.folder or None,
            "appendedUid": self.appended_uid or None,
            "error": self.error or None,
        }


def build_message(*, recipient: str, subject: str, body: str,
                  from_address: str, display_name: str = "") -> EmailMessage:
    """
    Post: a plain-text message ready to APPEND.

    Pre:  `recipient`, `subject` and `body` are what the operator read on
          screen. This function does not edit them.

    Plain text on purpose. Operations type these into Gmail by hand today and
    Gmail formats them on send; generating HTML here would make the filed draft
    look unlike everything the team has sent before it.
    """
    message = EmailMessage()
    message["To"] = recipient
    message["From"] = f"{display_name} <{from_address}>" if display_name else from_address
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=from_address.split("@")[-1])
    message.set_content(body)
    return message


def _select_draft_folder(conn) -> str:
    """
    Post: the name of a Drafts folder this server has.

    Raises DraftAppendError when none of the candidates opens, rather than
    appending into a folder nobody reads.
    """
    for folder in DRAFT_FOLDERS:
        try:
            status, _ = conn.select(f'"{folder}"', readonly=True)
        except Exception:
            continue
        if status == "OK":
            return folder
    raise DraftAppendError(
        f"No drafts folder found in {BOOKING_MAILBOX}; tried {', '.join(DRAFT_FOLDERS)}")


def _uid_from(response) -> str:
    """
    Post: the UID the server reported, or "".

    Gmail usually answers an APPEND with `[APPENDUID <validity> <uid>]` and is
    not required to. An empty string means the append landed and the server did
    not name it, which is evidence enough for the panel.
    """
    try:
        text = b" ".join(part for part in response if isinstance(part, bytes)).decode(
            "utf-8", "replace")
    except Exception:
        return ""
    marker = "APPENDUID"
    if marker not in text:
        return ""
    tail = text.split(marker, 1)[1].strip(" [])")
    parts = tail.split()
    return parts[1].rstrip("]") if len(parts) >= 2 else ""


def file_draft(append: dict, account_id: Optional[str] = None) -> DraftAppendOutcome:
    """
    Put one approved reply into Gmail Drafts.

    Pre:  `append` is a row from GET /api/agent/ops/draft-appends, naming a
          recipient, a subject and a body.
    Post: an outcome naming the folder the message reached, or the error that
          stopped it.
    Inv:  no model is called, nothing is sent, and no message other than this
          one is written. The connection opens Drafts read-only to check the
          folder exists, and APPEND is the only write.

    Blame: an append with an empty recipient is a caller bug — the server action
    reads the address from the booking and refuses a registration without one.
    """
    recipient = str(append.get("recipient") or "").strip()
    subject = str(append.get("subject") or "").strip()
    body = str(append.get("body") or "")
    if not recipient or not subject or not body.strip():
        return DraftAppendOutcome(
            error="The append names no recipient, subject or body.")

    resolved = account_id or booking_account_id()
    try:
        config = _get_email_config(resolved)
    except Exception as exc:
        return DraftAppendOutcome(error=f"Could not read the mailbox config: {exc}")

    message = build_message(
        recipient=recipient,
        subject=subject,
        body=body,
        from_address=config.get("from_address") or BOOKING_MAILBOX,
        display_name=config.get("display_name") or "",
    )

    conn = None
    try:
        # A fresh connection, not the pooled one. The pool hands out sessions
        # with a folder already selected, and this is the one caller that
        # writes; borrowing a shared session to APPEND is how a write lands
        # somewhere nobody expected.
        conn = _imap_connect(resolved)
        folder = _select_draft_folder(conn)
        status, response = conn.append(
            f'"{folder}"',
            r"(\Draft)",
            imaplib.Time2Internaldate(time.time()),
            message.as_bytes(),
        )
        if status != "OK":
            raise DraftAppendError(f"APPEND to '{folder}' answered {status}.")
        return DraftAppendOutcome(folder=folder, appended_uid=_uid_from(response))
    except DraftAppendError as exc:
        return DraftAppendOutcome(error=str(exc))
    except Exception as exc:
        logger.exception("draft append %s failed", append.get("id"))
        return DraftAppendOutcome(error=f"Could not file the draft: {exc}")
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:
                pass
