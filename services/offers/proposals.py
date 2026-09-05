"""
services/offers/proposals.py

Proposed additions and revisions to the day-template catalogue, and the human
verdict each one is waiting for.

Every change to the catalogue passes through here. A proposal carries the days
that motivated it, so a reviewer judges the evidence rather than the assertion,
and it carries the nearest existing template, so a near-duplicate is visible
before it is created rather than discovered later.

Nothing here writes to the catalogue sheet. Applying an approved proposal is a
separate, deliberate step (ws-03 WP1.5), and rows land inactive when it happens
(invariant 1.3).
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Iterator, Optional

from src.constants import TEMPLATE_PROPOSAL_DIR

from services.offers.catalogue import TEMPLATE_FIELDS

# What a proposal asks for.
KIND_NEW = "new"                 # a day the catalogue cannot express at all
KIND_REVISION = "revision"       # an existing template whose text has drifted

# Where a proposal stands.
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
# A rebuild no longer draws this day out of the corpus. It leaves the reviewer's
# queue and stays on disk. Deliberately not terminal: a proposal id is its
# content, so a later analysis that finds the day again returns it to pending.
# Treating it as terminal would bury a day the corpus still writes.
STATUS_RETIRED = "retired"
TERMINAL_STATUSES = (STATUS_APPROVED, STATUS_REJECTED)

# How often the corpus wrote the day behind a proposal. The reviewer reads the
# two apart: a rare day earns a new row, and a recurring one usually restates a
# row the catalogue already holds.
FREQUENCY_RARE = "rare"
FREQUENCY_RECURRING = "recurring"


class ProposalError(Exception):
    """The proposal is malformed, or the transition asked for is not allowed."""


@dataclass
class TemplateProposal:
    """One proposed catalogue change, with the evidence that motivated it."""
    proposal_id: str
    kind: str
    fields: dict                                  # the 11 catalogue columns
    evidence_day_keys: list = field(default_factory=list)
    occurrences: int = 0
    # Occurrences discounted by age. Orders the queue; `occurrences` reports the
    # plain count. A day written five times last month is stronger evidence than
    # one written five times two years ago, and the reviewer sees which.
    weight: float = 0.0
    target_code: Optional[str] = None             # set for KIND_REVISION
    nearest_code: Optional[str] = None
    nearest_score: float = 0.0
    # Templates this day matches in content but not in order — the same route
    # driven the other way. Without this, a reversed route becomes a second
    # template for a journey the catalogue already describes.
    reordered_codes: list = field(default_factory=list)
    status: str = STATUS_PENDING
    # Set when the proposal is drafted, from the evidence behind it. Stored
    # rather than derived, so the page filters without measuring anything.
    frequency: str = FREQUENCY_RECURRING
    reviewer_note: str = ""
    # The corpus this proposal was derived from, as `corpus_fingerprint()` saw
    # it. None on a proposal written before stamping existed, which reads as
    # unknown provenance rather than as current.
    corpus: Optional[dict] = None
    # What a model proposed for the columns the analysis leaves empty, marked as
    # machine text. Never merged into `fields` by any code. Only the reviewer's
    # accept moves a value across, through record_verdict.
    suggested: Optional[dict] = None
    created_at: str = ""
    decided_at: Optional[str] = None
    # Set once the approved change actually reached the catalogue sheet. Kept
    # separate from status: approving is a decision, applying is an effect, and
    # conflating them would let a failed write look like a completed one.
    applied_at: Optional[str] = None

    @property
    def is_pending(self) -> bool:
        return self.status == STATUS_PENDING

    @property
    def is_applicable(self) -> bool:
        """Approved, named, and not yet written to the catalogue sheet."""
        return (self.status == STATUS_APPROVED
                and not self.applied_at
                and bool((self.fields.get("code") or "").strip()))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def proposal_id_for(kind: str, text: str, target_code: Optional[str] = None) -> str:
    """
    Content-addressed id, so re-running the analysis re-proposes the same thing
    under the same id instead of duplicating a decision the reviewer has made.
    """
    seed = f"{kind}|{target_code or ''}|{text}".encode("utf-8")
    return f"{kind[:3]}-{hashlib.sha1(seed).hexdigest()[:12]}"


def _path(proposal_id: str) -> str:
    return os.path.join(TEMPLATE_PROPOSAL_DIR, f"{proposal_id}.json")


def build_proposal(
    kind: str,
    fields: dict,
    evidence_day_keys: list,
    occurrences: int = 0,
    weight: float = 0.0,
    target_code: Optional[str] = None,
    nearest_code: Optional[str] = None,
    nearest_score: float = 0.0,
    reordered_codes: Optional[list] = None,
    corpus: Optional[dict] = None,
    frequency: str = FREQUENCY_RECURRING,
) -> TemplateProposal:
    """
    Pre:  `kind` is KIND_NEW or KIND_REVISION; `fields` covers TEMPLATE_FIELDS;
          a KIND_REVISION names `target_code`; `corpus` is the stamp of the
          corpus the evidence came from, or None.
    Post: a pending proposal whose id is determined by its content.

    The stamp is not part of the id. Two runs over two corpora that find the
    same day must still produce one proposal, because the reviewer decided
    about the day and not about the run.

    Blame: a missing field or a revision without a target is a caller bug and
    raises — a proposal that cannot be applied must never reach the queue.
    """
    if kind not in (KIND_NEW, KIND_REVISION):
        raise ProposalError(f"unknown proposal kind: {kind!r}")
    if kind == KIND_REVISION and not target_code:
        raise ProposalError("a revision must name the template it revises")
    missing = [name for name in TEMPLATE_FIELDS if name not in fields]
    if missing:
        raise ProposalError(f"proposal is missing catalogue fields: {', '.join(missing)}")

    return TemplateProposal(
        proposal_id=proposal_id_for(kind, fields.get("full_text", ""), target_code),
        kind=kind,
        fields={name: fields[name] for name in TEMPLATE_FIELDS},
        evidence_day_keys=list(evidence_day_keys),
        occurrences=occurrences or len(evidence_day_keys),
        weight=weight or float(occurrences or len(evidence_day_keys)),
        target_code=target_code,
        nearest_code=nearest_code,
        nearest_score=nearest_score,
        reordered_codes=list(reordered_codes or []),
        corpus=corpus,
        frequency=frequency,
        created_at=_now(),
    )


def save(proposal: TemplateProposal) -> str:
    """
    Post: the proposal is on disk, written atomically. An existing proposal with
          a terminal verdict is left untouched — re-running the analysis must
          not silently reopen a decision a human already made.
    """
    os.makedirs(TEMPLATE_PROPOSAL_DIR, exist_ok=True)
    existing = load(proposal.proposal_id)
    if existing is not None and existing.status in TERMINAL_STATUSES:
        return _path(proposal.proposal_id)

    # A rebuild redraws every proposal and would otherwise erase a suggestion
    # with it. The reviewer works through hundreds of cards across sittings, and
    # rebuilds happen in between. A freshly drafted proposal carries none, so
    # the one already on disk is kept.
    if existing is not None and existing.suggested and not proposal.suggested:
        proposal.suggested = existing.suggested

    target = _path(proposal.proposal_id)
    temporary = target + ".tmp"
    with open(temporary, "w", encoding="utf-8") as fh:
        json.dump(asdict(proposal), fh, ensure_ascii=False, indent=2)
    os.replace(temporary, target)
    return target


def load(proposal_id: str) -> Optional[TemplateProposal]:
    path = _path(proposal_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return TemplateProposal(**json.load(fh))
    except (json.JSONDecodeError, OSError, TypeError):
        return None


def iter_proposals(status: Optional[str] = None,
                   frequency: Optional[str] = None) -> Iterator[TemplateProposal]:
    """
    Yield proposals in the order their own list is read.

    Post: a proposal whose file is unreadable is skipped rather than raised —
          one bad file must not empty the reviewer's queue.

    Two lists, two orders. A rare list is ordered by distance from the
    catalogue, farthest first, because the day the catalogue understands least
    is the one that most clearly earns a row. A recurring list is ordered by
    weight, because there the argument is repetition. Ordering the rare list by
    weight would put the least rare day at the top of a list of rare days.
    """
    if not os.path.isdir(TEMPLATE_PROPOSAL_DIR):
        return
    found = []
    for name in sorted(os.listdir(TEMPLATE_PROPOSAL_DIR)):
        if not name.endswith(".json"):
            continue
        proposal = load(name[:-5])
        if proposal is None:
            continue
        if status is not None and proposal.status != status:
            continue
        if frequency is not None and proposal.frequency != frequency:
            continue
        found.append(proposal)
    if frequency == FREQUENCY_RARE:
        found.sort(key=lambda p: (p.nearest_score, -p.occurrences, p.proposal_id))
    else:
        found.sort(key=lambda p: (-p.weight, -p.occurrences, p.proposal_id))
    yield from found


def record_verdict(
    proposal_id: str,
    status: str,
    reviewer_note: str = "",
    edited_fields: Optional[dict] = None,
) -> TemplateProposal:
    """
    Record a human decision, optionally with the reviewer's own edits.

    Pre:  `status` is approved or rejected; the proposal exists and is pending.
    Post: the proposal is terminal and carries `decided_at`. Edited fields
          replace the drafted ones, so what a reviewer approves is exactly what
          can later be applied.

    Blame: deciding an already-decided proposal is a caller bug and raises —
    silently overwriting a verdict would lose the record of who decided what.
    """
    if status not in TERMINAL_STATUSES:
        raise ProposalError(f"not a verdict: {status!r}")
    proposal = load(proposal_id)
    if proposal is None:
        raise ProposalError(f"no such proposal: {proposal_id}")
    if not proposal.is_pending:
        raise ProposalError(f"{proposal_id} is already {proposal.status}")

    if edited_fields:
        unknown = [name for name in edited_fields if name not in TEMPLATE_FIELDS]
        if unknown:
            raise ProposalError(f"not catalogue fields: {', '.join(unknown)}")
        proposal.fields.update(edited_fields)

    proposal.status = status
    proposal.reviewer_note = reviewer_note
    proposal.decided_at = _now()

    target = _path(proposal_id)
    temporary = target + ".tmp"
    with open(temporary, "w", encoding="utf-8") as fh:
        json.dump(asdict(proposal), fh, ensure_ascii=False, indent=2)
    os.replace(temporary, target)
    return proposal


def queue_summary() -> dict:
    """Counts by status, for a panel header or a log line."""
    counts = {STATUS_PENDING: 0, STATUS_APPROVED: 0,
              STATUS_REJECTED: 0, STATUS_RETIRED: 0}
    for proposal in iter_proposals():
        counts[proposal.status] = counts.get(proposal.status, 0) + 1
    return counts


# The columns a row must carry before it is worth writing to the catalogue. A
# row without them builds into an itinerary and prices at zero. `included_sites`
# and `overnight_city` are not here: two catalogue rows legitimately hold
# neither, so demanding them would call a correct row unready.
REQUIRED_TO_PUSH = ("code", "title", "city", "region", "pricing_tags_json")


def is_ready_to_push(proposal: TemplateProposal) -> bool:
    """
    Post: True when every column the catalogue needs carries a value.

    Read rather than stored, because a reviewer fills the boxes one at a time
    and a stored flag would go stale between two edits.
    """
    for name in REQUIRED_TO_PUSH:
        value = proposal.fields.get(name)
        if isinstance(value, str) and not value.strip():
            return False
        if value in (None, "", [], "[]"):
            return False
    return True


def revise_approved(proposal_id: str, fields: dict) -> TemplateProposal:
    """
    Change the catalogue columns of an approved proposal before it is written.

    Pre:  the proposal is approved and not yet applied. `fields` names only
          catalogue columns.
    Post: those columns hold the new values. The verdict, its time and the
          proposal id are untouched.

    Blame: revising an applied proposal is a caller bug and raises. That row is
    already in the sheet, and changing the record here would make the two
    disagree with nothing to say which is right.
    """
    proposal = load(proposal_id)
    if proposal is None:
        raise ProposalError(f"no such proposal: {proposal_id}")
    if proposal.status != STATUS_APPROVED:
        raise ProposalError(f"{proposal_id} is {proposal.status}, not approved")
    if proposal.applied_at:
        raise ProposalError(f"{proposal_id} already reached the catalogue")

    unknown = [name for name in fields if name not in TEMPLATE_FIELDS]
    if unknown:
        raise ProposalError(f"not catalogue fields: {', '.join(unknown)}")
    proposal.fields.update(fields)

    target = _path(proposal_id)
    temporary = target + ".tmp"
    with open(temporary, "w", encoding="utf-8") as fh:
        json.dump(asdict(proposal), fh, ensure_ascii=False, indent=2)
    os.replace(temporary, target)
    return proposal


def record_suggestion(proposal_id: str, suggestion: dict) -> TemplateProposal:
    """
    Store what a model proposed for one pending proposal.

    Pre:  the proposal exists and is pending. `suggestion` came from
          `suggest_catalogue_row` and names its model, endpoint and time.
    Post: the proposal carries the suggestion under `suggested`, and `fields` is
          byte-identical to what it held before. A second suggestion replaces
          the first, so the block holds one answer.

    Blame: suggesting on a decided proposal is a caller bug and raises. A
    verdict is the one thing this queue exists to collect.
    """
    proposal = load(proposal_id)
    if proposal is None:
        raise ProposalError(f"no such proposal: {proposal_id}")
    if not proposal.is_pending:
        raise ProposalError(f"{proposal_id} is already {proposal.status}")

    proposal.suggested = suggestion
    target = _path(proposal_id)
    temporary = target + ".tmp"
    with open(temporary, "w", encoding="utf-8") as fh:
        json.dump(asdict(proposal), fh, ensure_ascii=False, indent=2)
    os.replace(temporary, target)
    return proposal


def retire_undrafted(drafted_ids) -> int:
    """
    Retire every pending proposal that this rebuild did not draft.

    Pre:  `drafted_ids` holds every id from one complete rebuild over the whole
          corpus. A partial set retires proposals the corpus still writes.
    Post: a pending proposal outside that set reads `retired`. Its file stays on
          disk and nothing else about it changes. Returns how many were retired.

    Blame: passing the ids of a narrowed run is a caller bug. The proposals it
    did not reach are not gone from the corpus, only from that run.

    Approved and rejected proposals are never touched. A verdict is the one
    thing this queue exists to collect, and a rebuild must not undo it.
    """
    drafted = set(drafted_ids)
    retired = 0
    for proposal in iter_proposals(status=STATUS_PENDING):
        if proposal.proposal_id in drafted:
            continue
        proposal.status = STATUS_RETIRED
        target = _path(proposal.proposal_id)
        temporary = target + ".tmp"
        with open(temporary, "w", encoding="utf-8") as fh:
            json.dump(asdict(proposal), fh, ensure_ascii=False, indent=2)
        os.replace(temporary, target)
        retired += 1
    return retired


def mark_applied(proposal_id: str) -> TemplateProposal:
    """
    Record that an approved proposal reached the catalogue sheet.

    Pre:  the proposal exists and is approved.
    Post: `applied_at` is set, so a later run cannot write it a second time.

    Blame: marking an unapproved proposal is a caller bug and raises — it would
    claim the catalogue holds something no one approved.
    """
    proposal = load(proposal_id)
    if proposal is None:
        raise ProposalError(f"no such proposal: {proposal_id}")
    if proposal.status != STATUS_APPROVED:
        raise ProposalError(f"{proposal_id} is {proposal.status}, not approved")
    proposal.applied_at = _now()

    target = _path(proposal_id)
    temporary = target + ".tmp"
    with open(temporary, "w", encoding="utf-8") as fh:
        json.dump(asdict(proposal), fh, ensure_ascii=False, indent=2)
    os.replace(temporary, target)
    return proposal
