"""
services/bookings/desk_task.py

What Odysseus does for the bookings desk, on a schedule.

`run_offer_jobs` takes pricing work the website left and answers it.
`run_reply_scan` reads the Sent folder and says which registrations it answered.

Both are unattended, and neither calls a model. That is deliberate rather than
incidental: an unattended run that reasons about a customer is the case
Odysseus's external-context gate exists to stop, and these two are built so the
question never arises. Pricing reads a tour and a party size. Matching reads
HMACs. The greeting is `str.replace`, done by the website afterwards.

`run_draft_appends` files approved replies into Gmail Drafts. It is the one
task here that handles a customer's name, and it is safe for the opposite
reason to the others: `draft_append` calls no model, so there is no reasoning
step for injected text to reach.

`run_templates_push` sends the wording once, so the panel can show an operator
what will be sent before any button is pressed.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field

from services.bookings.draft_append import file_draft
from services.bookings.offer_jobs import price_and_build
from services.bookings.reply_scan import ReplyScanError, scan
from services.bookings.templates import NAME_PLACEHOLDERS, raw_templates
from src import ops_hub

logger = logging.getLogger(__name__)

# How many jobs one poll takes.
#
# A pricing run builds a document, which is the slow part. Ten is more than the
# desk has ever queued at once and small enough that a poll finishes long before
# the twenty-minute claim expiry hands the same work to the next one.
JOBS_PER_POLL = 10


@dataclass
class DeskRunReport:
    """What one run of either task has to say. Read into the run's `response`."""
    priced: int = 0
    failed: int = 0
    filed: int = 0
    answered: int = 0
    templates_pushed: int = 0
    notes: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def status(self) -> str:
        completed = self.priced + self.filed + self.answered + self.templates_pushed
        if self.failed or self.errors:
            return "partial" if completed else "failed"
        return "completed" if completed or self.notes else "empty"

    @property
    def ok(self) -> bool:
        return self.status not in ("failed", "partial")

    def summary(self) -> str:
        parts = []
        if self.priced:
            parts.append(f"priced {self.priced}")
        if self.failed:
            parts.append(f"failed {self.failed}")
        if self.filed:
            parts.append(f"filed {self.filed} drafts")
        if self.answered:
            parts.append(f"{self.answered} registrations already answered")
        if self.templates_pushed:
            parts.append(f"pushed {self.templates_pushed} templates")
        if not parts:
            parts.append("failed" if self.errors else "nothing waiting")
        return "; ".join(parts + self.notes + self.errors)


async def run_offer_jobs() -> DeskRunReport:
    """
    Answer the pricing work the website is holding.

    Post: every job this poll claimed is closed, as `done` or as `error`.
    Inv:  a job never stays claimed because this function returned. A claim
          this run cannot finish is one an operator watches spin, so a failure
          is reported rather than left.
    """
    report = DeskRunReport()

    claimed = await ops_hub.claim_offer_jobs(JOBS_PER_POLL)
    if not claimed.get("ok"):
        report.errors.append(f"could not claim jobs: {claimed.get('error')}")
        return report

    jobs = (claimed.get("body") or {}).get("jobs") or []
    for job in jobs:
        try:
            outcome = await asyncio.to_thread(price_and_build, job)
        except Exception as exc:
            from services.bookings.offer_jobs import OfferJobOutcome
            outcome = OfferJobOutcome(error=f"Pricing failed: {exc}")
        posted = await ops_hub.post_job_result(job["id"], **outcome.as_result_payload())
        if not posted.get("ok"):
            # The work is done and the answer is lost. Say so loudly: the job
            # stays claimed, and the claim expiry is what gets it retried.
            report.notes.append(
                f"job {job['id']} priced but the result did not post: {posted.get('error')}")
            report.failed += 1
            continue
        if outcome.ok:
            report.priced += 1
        else:
            report.failed += 1
            report.notes.append(f"job {job['id']}: {outcome.error}")

    return report


async def run_draft_appends() -> DeskRunReport:
    """
    File the replies an operator approved into Gmail Drafts.

    Post: every append this poll claimed is closed, as `done` or as `error`.
    Inv:  no model is called at any point, and nothing is sent. A filed draft
          waits in Drafts until a person opens Gmail and presses send.
    Inv:  a failed append is not retried here. One that landed and then lost its
          answer would file a second draft on a retry, and two drafts in Gmail
          are one message sent twice.
    """
    report = DeskRunReport()

    claimed = await ops_hub.claim_draft_appends(JOBS_PER_POLL)
    if not claimed.get("ok"):
        report.errors.append(f"could not claim appends: {claimed.get('error')}")
        return report

    for append in (claimed.get("body") or {}).get("appends") or []:
        outcome = await asyncio.to_thread(_file_draft_once, append)
        posted = await ops_hub.post_draft_append_result(
            append["id"], **outcome.as_result_payload())
        if not posted.get("ok"):
            report.notes.append(
                f"append {append['id']} filed but the result did not post: "
                f"{posted.get('error')}")
            report.failed += 1
            continue
        if outcome.ok:
            report.filed += 1
        else:
            report.failed += 1
            report.notes.append(f"append {append['id']}: {outcome.error}")

    return report


def _file_draft_once(append):
    """Persist an attempt before IMAP. A lost reply must never cause another append."""
    import hashlib
    import json
    from pathlib import Path
    from core.atomic_io import atomic_write_json
    from src.constants import DATA_DIR
    from services.bookings.draft_append import DraftAppendOutcome

    identifier = append.get("id")
    if not isinstance(identifier, str) or not identifier:
        return DraftAppendOutcome(error="Draft append has no stable identifier")
    receipt_dir = Path(DATA_DIR) / "bookings_draft_receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    path = receipt_dir / (hashlib.sha256(identifier.encode()).hexdigest() + ".json")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
            if previous.get("state") == "finished":
                return DraftAppendOutcome(**previous["outcome"])
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return DraftAppendOutcome(error="A previous draft attempt has an uncertain outcome. Reconcile Gmail before retrying.")
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump({"state": "started"}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    if os.name == "posix":
        # Persist both directory entries before any remote write can occur.
        for directory in (receipt_dir.parent, receipt_dir):
            descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    outcome = file_draft(append)
    atomic_write_json(str(path), {"state": "finished", "outcome": {
        "folder": outcome.folder, "appended_uid": outcome.appended_uid, "error": outcome.error,
    }})
    return outcome


async def run_reply_scan(window_days: int | None = None) -> DeskRunReport:
    """
    Say which registrations book@bilweekend.com has already answered.

    Post: one posted entry per answered registration.
    Inv:  reads the mailbox read-only, and writes no follow-up field. The
          hand-set status is untouched and still wins.

    Blame: an unreachable mailbox reports nothing rather than none. Posting an
    empty list would look identical to "no registration was ever answered", and
    would blank a panel that was right a minute earlier.
    """
    report = DeskRunReport()

    recipients = await _fetch_recipients()
    if recipients is None:
        report.errors.append("could not fetch the recipient list")
        return report
    if not recipients:
        report.notes.append("no registrations to check")
        return report

    from datetime import date, timedelta
    since = date.today() - timedelta(days=window_days) if window_days else None

    try:
        answered = await asyncio.to_thread(scan, recipients, since=since,
                        key=os.environ.get("OPS_AGENT_TOKEN", ""))
    except ReplyScanError as exc:
        report.errors.append(str(exc))
        return report

    posted = await ops_hub.post_booking_replies(answered)
    if not posted.get("ok"):
        report.errors.append(f"replies did not post: {posted.get('error')}")
        return report

    report.answered = len(answered)
    report.notes.append(f"{len(recipients)} registrations checked")
    return report


async def run_templates_push() -> DeskRunReport:
    """
    Send the two templates, unfilled.

    Post: the panel can show an operator the wording before anything runs, and
          can fill the deposit one itself for a group departure (ws-bd A1, 8.1).
    """
    report = DeskRunReport()
    payload = [
        {
            "name": template.name,
            "subject": template.subject,
            "body": template.body,
            # What the panel must substitute. The deposit template needs the
            # tour and the month too, because no run ever touches it.
            "variables": _variables_in(template.subject, template.body),
        }
        for template in raw_templates()
    ]
    posted = await ops_hub.post_booking_templates(payload)
    if not posted.get("ok"):
        report.errors.append(f"templates did not post: {posted.get('error')}")
        return report
    report.templates_pushed = (posted.get("body") or {}).get("accepted", 0)
    return report


def _variables_in(*texts: str) -> list:
    """
    Post: the placeholders these texts hold, sorted, without their braces.

    Read from the text rather than listed by hand. A list that drifts from the
    body leaves the panel showing a customer `Dear {first_name}`.
    """
    import re

    found = set()
    for text in texts:
        found.update(re.findall(r"\{([a-z_]+)\}", text or ""))
    return sorted(found)


async def _fetch_recipients():
    """
    Post: [{bookingId, addressHash, submittedAt}], or None when the fetch failed.

    None and [] are different answers. An empty list means the desk holds no
    registrations; None means this run does not know, and must not report as if
    it did.
    """
    config = ops_hub.hub_config()
    if config is None:
        return None
    result = await ops_hub._get("/api/agent/ops/booking-recipients")
    if not result.get("ok"):
        logger.warning("recipient fetch failed: %s", result.get("error"))
        return None
    return (result.get("body") or {}).get("recipients") or []


# The placeholders a pricing run leaves for the website. Re-exported so a
# reader of this module can see what does not get filled here, and why.
__all__ = [
    "DeskRunReport",
    "NAME_PLACEHOLDERS",
    "run_draft_appends",
    "run_offer_jobs",
    "run_reply_scan",
    "run_templates_push",
]
