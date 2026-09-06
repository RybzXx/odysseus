"""
services/itinerary/drafts.py

One request, the day-code sequences proposed for it, and the conversation that
produced them.

The review queue stores one verdict per proposal and no history. This is a
different shape: a request keeps every answer it was given and the comment that
caused each one, so a reviewer reads the thread rather than only its last line.

Two sequences sit against every request. The AI proposes one and the vendored
rules propose the other, and neither is authoritative. A comment moves the AI's
answer. The rules answer is deterministic and never moves, which is exactly what
makes it useful as a fixed second opinion across a whole thread.

Nothing here writes to a sheet or generates a document.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Iterator, Optional

from src.constants import DATA_DIR

ITINERARY_DRAFT_DIR = os.path.join(DATA_DIR, "itinerary_drafts")

# Who proposed a sequence. The two are kept apart everywhere, because a reader
# who cannot tell them apart cannot judge a disagreement.
SOURCE_MODEL = "model"
SOURCE_RULES = "rules"

# Where a request came from. Both arrive as the same column dict, and the origin
# is recorded rather than inferred later from the shape.
ORIGIN_SHEET = "sheet"
ORIGIN_TYPED = "typed"

# What became of a comment, as the judged rule book reads it (ws-03 D26).
# A comment starts as raw feedback and leaves this queue exactly once, whether
# it produced a rule or was turned down.
RULE_STATE_NEW = "new"          # waiting to be read for a rule
RULE_STATE_DRAFTED = "drafted"  # a rule was drafted from it
RULE_STATE_DECLINED = "declined"  # read, and it states no rule
RULE_STATES = (RULE_STATE_NEW, RULE_STATE_DRAFTED, RULE_STATE_DECLINED)


class DraftError(Exception):
    """The draft is malformed, or the change asked for is not allowed."""


@dataclass
class ProposedSequence:
    """One answer: an ordered list of day codes, and who produced it."""
    source: str                       # SOURCE_MODEL or SOURCE_RULES
    day_codes: list = field(default_factory=list)
    # Codes the proposer named that the active catalogue does not hold. Kept
    # rather than dropped in silence, because an invented code is evidence about
    # the proposer.
    rejected_codes: list = field(default_factory=list)
    note: str = ""                    # match score, gap notes, or a model's reason
    # The comment that asked for this answer. Empty on the first.
    in_reply_to: str = ""
    model: str = ""
    endpoint: str = ""
    proposed_at: str = ""


@dataclass
class ItineraryDraft:
    """A request under discussion, with every sequence it has been given."""
    draft_id: str
    request_row: dict                 # the column dict, exactly as normalize_row reads it
    origin: str = ORIGIN_TYPED
    request_id: str = ""              # the cr-... id from the sheet, when there is one
    parse_warnings: list = field(default_factory=list)
    sequences: list = field(default_factory=list)   # list[ProposedSequence], oldest first
    comments: list = field(default_factory=list)    # list[{"text", "at"}]
    # Set once a document is generated, with the sequence that produced it.
    generated_from: Optional[str] = None
    doc_url: str = ""
    created_at: str = ""

    @property
    def latest(self) -> dict:
        """Post: {source: the newest sequence from that source}."""
        newest = {}
        for sequence in self.sequences:
            newest[sequence.source] = sequence
        return newest


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def draft_id_for(request_row: dict, request_id: str = "") -> str:
    """
    Post: `dr-` and twelve hex characters, stable for one request.

    Pre:  `request_id` names the request where the caller holds an id the
          request keeps for its whole life, such as a worklist key.

    Keyed on the request rather than the moment, so re-opening the same row
    returns to the same thread instead of starting a second one beside it.

    A typed request has no identity but its own contents, so its id is a hash of
    them. A worklist request has one, and using it means an edit to the
    submitted record returns to the same thread rather than opening a second
    beside the first, with the comments left behind on the old one.
    """
    seed = (request_id.strip() or
            json.dumps(request_row, sort_keys=True, ensure_ascii=False))
    return f"dr-{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:12]}"


def _path(draft_id: str) -> str:
    return os.path.join(ITINERARY_DRAFT_DIR, f"{draft_id}.json")


def save(draft: ItineraryDraft) -> str:
    """Post: the draft is on disk, written atomically."""
    os.makedirs(ITINERARY_DRAFT_DIR, exist_ok=True)
    target = _path(draft.draft_id)
    temporary = target + ".tmp"
    with open(temporary, "w", encoding="utf-8") as fh:
        json.dump(asdict(draft), fh, ensure_ascii=False, indent=2)
    os.replace(temporary, target)
    return target


def load(draft_id: str) -> Optional[ItineraryDraft]:
    """Post: the draft, or None when there is no such thread."""
    path = _path(draft_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None
    raw["sequences"] = [ProposedSequence(**s) for s in raw.get("sequences", [])]
    try:
        return ItineraryDraft(**raw)
    except TypeError:
        return None


def iter_drafts() -> Iterator[ItineraryDraft]:
    """
    Yield every draft, newest first.

    Post: a draft whose file is unreadable is skipped rather than raised — one
          bad file must not empty the desk.
    """
    if not os.path.isdir(ITINERARY_DRAFT_DIR):
        return
    found = []
    for name in sorted(os.listdir(ITINERARY_DRAFT_DIR)):
        if not name.endswith(".json"):
            continue
        draft = load(name[:-5])
        if draft is not None:
            found.append(draft)
    found.sort(key=lambda d: d.created_at, reverse=True)
    yield from found


def open_draft(request_row: dict, origin: str = ORIGIN_TYPED,
               parse_warnings: Optional[list] = None,
               request_id: str = "") -> ItineraryDraft:
    """
    Start a thread for a request, or return the one it already has.

    Pre:  `request_row` is the column dict `normalize_row` reads.
          `request_id` names the request where the caller holds a stable id,
          such as a worklist key; otherwise the row's own `Customize` column
          answers, and failing that the request has no name of its own.
    Post: a saved draft whose id is determined by the request. Re-opening the
          same request returns the existing thread with its history intact.
    """
    named = (request_id or request_row.get("Customize") or "").strip()
    draft_id = draft_id_for(request_row, request_id)
    existing = load(draft_id)
    if existing is not None:
        return existing
    draft = ItineraryDraft(
        draft_id=draft_id,
        request_row=dict(request_row),
        origin=origin,
        request_id=named,
        parse_warnings=list(parse_warnings or []),
        created_at=_now(),
    )
    save(draft)
    return draft


def add_sequence(draft_id: str, sequence: ProposedSequence) -> ItineraryDraft:
    """
    Append one answer to a thread.

    Pre:  the draft exists. `sequence.source` is SOURCE_MODEL or SOURCE_RULES.
    Post: the sequence is the newest from that source, stamped with the moment
          it arrived. Earlier answers are kept.

    Blame: an unknown source is a caller bug. A reader who cannot tell the model
    from the rules cannot judge a disagreement between them.
    """
    if sequence.source not in (SOURCE_MODEL, SOURCE_RULES):
        raise DraftError(f"unknown source: {sequence.source!r}")
    draft = load(draft_id)
    if draft is None:
        raise DraftError(f"no such draft: {draft_id}")
    sequence.proposed_at = sequence.proposed_at or _now()
    draft.sequences.append(sequence)
    save(draft)
    return draft


def comment_id_for(draft_id: str, text: str, at: str) -> str:
    """Post: `cm-` and twelve hex characters, stable for one comment."""
    seed = f"{draft_id}\x1f{text}\x1f{at}".encode("utf-8")
    return f"cm-{hashlib.sha1(seed).hexdigest()[:12]}"


def add_comment(draft_id: str, text: str) -> ItineraryDraft:
    """
    Record a comment. It asks for a new answer; it does not produce one.

    Pre:  the draft exists and `text` is not empty.
    Post: the comment is on the thread, with an id and `rule_state` set to
          RULE_STATE_NEW. The caller asks the model for the next sequence and
          records it with `in_reply_to` set to this text.

    The id and the state exist because a comment is also the raw material of a
    judged rule (ws-03 D18, D26). Without them the rule drafter re-reads every
    comment each time and drafts the same rule twice.
    """
    if not (text or "").strip():
        raise DraftError("a comment cannot be empty")
    draft = load(draft_id)
    if draft is None:
        raise DraftError(f"no such draft: {draft_id}")
    at = _now()
    draft.comments.append({
        "comment_id": comment_id_for(draft_id, text.strip(), at),
        "text": text.strip(),
        "at": at,
        "rule_state": RULE_STATE_NEW,
    })
    save(draft)
    return draft


def set_comment_rule_state(draft_id: str, comment_id: str, state: str) -> ItineraryDraft:
    """
    Record what became of one comment.

    Pre:  the draft holds a comment with this id, and `state` is one of
          RULE_STATES.
    Post: that comment carries the new state and nothing else changes.

    Blame: an unknown state is a caller bug and raises. A drafter that writes a
    state nobody reads would leave the comment queue growing in silence.
    """
    if state not in RULE_STATES:
        raise DraftError(f"unknown rule state: {state!r}")
    draft = load(draft_id)
    if draft is None:
        raise DraftError(f"no such draft: {draft_id}")
    for comment in draft.comments:
        if comment.get("comment_id") == comment_id:
            comment["rule_state"] = state
            save(draft)
            return draft
    raise DraftError(f"no comment {comment_id} on {draft_id}")


def iter_comments(rule_state: Optional[str] = None):
    """
    Every comment on every draft, oldest draft first.

    Pre:  `rule_state` is one of RULE_STATES, or None for all of them.
    Post: dicts carrying the comment and the draft it sits on. A comment
          written before this field existed reads as RULE_STATE_NEW, because it
          has not been drafted into a rule either.
    """
    for draft in iter_drafts():
        for comment in draft.comments:
            state = comment.get("rule_state") or RULE_STATE_NEW
            if rule_state is not None and state != rule_state:
                continue
            yield {
                "comment_id": comment.get("comment_id")
                or comment_id_for(draft.draft_id, comment.get("text") or "",
                                  comment.get("at") or ""),
                "draft_id": draft.draft_id,
                "request_id": draft.request_id,
                "text": comment.get("text") or "",
                "at": comment.get("at") or "",
                "rule_state": state,
            }


def sequences_agree(draft: ItineraryDraft) -> dict:
    """
    Where the newest two answers say the same thing.

    Post: {"same": bool, "model": [...], "rules": [...], "positions": [...]}.
          `positions` marks each day: "same" where both name one code, "differ"
          where they name two, and "only-model" or "only-rules" past the end of
          the shorter answer.

    A difference is a note and never a block. Neither proposer is authoritative,
    and the reviewer decides.
    """
    newest = draft.latest
    model = list(getattr(newest.get(SOURCE_MODEL), "day_codes", []) or [])
    rules = list(getattr(newest.get(SOURCE_RULES), "day_codes", []) or [])
    positions = []
    for index in range(max(len(model), len(rules))):
        left = model[index] if index < len(model) else None
        right = rules[index] if index < len(rules) else None
        if left is None:
            positions.append("only-rules")
        elif right is None:
            positions.append("only-model")
        else:
            positions.append("same" if left == right else "differ")
    return {"same": model == rules and bool(model),
            "model": model, "rules": rules, "positions": positions}
