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

# Where a proposal stands. Only PENDING is not terminal.
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
TERMINAL_STATUSES = (STATUS_APPROVED, STATUS_REJECTED)


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
    target_code: Optional[str] = None             # set for KIND_REVISION
    nearest_code: Optional[str] = None
    nearest_score: float = 0.0
    status: str = STATUS_PENDING
    reviewer_note: str = ""
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
    target_code: Optional[str] = None,
    nearest_code: Optional[str] = None,
    nearest_score: float = 0.0,
) -> TemplateProposal:
    """
    Pre:  `kind` is KIND_NEW or KIND_REVISION; `fields` covers TEMPLATE_FIELDS;
          a KIND_REVISION names `target_code`.
    Post: a pending proposal whose id is determined by its content.

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
        target_code=target_code,
        nearest_code=nearest_code,
        nearest_score=nearest_score,
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


def iter_proposals(status: Optional[str] = None) -> Iterator[TemplateProposal]:
    """
    Yield proposals, most-evidenced first.

    Post: a proposal whose file is unreadable is skipped rather than raised —
          one bad file must not empty the reviewer's queue.
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
        if status is None or proposal.status == status:
            found.append(proposal)
    found.sort(key=lambda p: (-p.occurrences, p.proposal_id))
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
    counts = {STATUS_PENDING: 0, STATUS_APPROVED: 0, STATUS_REJECTED: 0}
    for proposal in iter_proposals():
        counts[proposal.status] = counts.get(proposal.status, 0) + 1
    return counts


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
