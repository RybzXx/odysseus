"""
services/itinerary/run_record.py

What each layer did on one request, kept where a human can read it.

A draft holds answers. This holds the work that produced them: the input each
step received, the answer it gave, the endpoint it reached, and how long it
took. A draft that carried all of that would grow with every re-run, and a
reviewer looking for one sequence would read four prompts first.

So a run lives in its own file and the draft names it (ws-03 D42).

A finished run is sealed. Its steps are evidence about a model, and evidence
that a later run may rewrite is not evidence (invariant 3.7).

Nothing here calls a model. The caller runs the step and reports what happened.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Iterator, Optional

from src.constants import DATA_DIR

ITINERARY_RUN_DIR = os.path.join(DATA_DIR, "itinerary_runs")

# The seven steps of one run, in the order they happen. A record holds one entry
# per step, whether the step ran or not.
STEP_READ_LINK = "read_link"      # find the screenshots the request points to
STEP_EXTRACT = "extract"          # a screenshot becomes text
STEP_BRIEF = "brief"              # layer 1
STEP_CANDIDATES = "candidates"    # the tied routes become sequences
STEP_CHECK = "check"              # every candidate is examined
STEP_RANK = "rank"                # layer 2
STEP_REVIEW = "review"            # layer 3
STEPS = (STEP_READ_LINK, STEP_EXTRACT, STEP_BRIEF, STEP_CANDIDATES,
         STEP_CHECK, STEP_RANK, STEP_REVIEW)

# What a step did.
OUTCOME_DONE = "done"
OUTCOME_UNTESTED = "untested"    # it could not run, and said why (D43)
OUTCOME_FAILED = "failed"        # it ran and raised
OUTCOMES = (OUTCOME_DONE, OUTCOME_UNTESTED, OUTCOME_FAILED)


class RunError(Exception):
    """The run is malformed, or the change asked for is not allowed."""


@dataclass
class RunStep:
    """One step of one run, and everything a reader needs to judge it."""
    name: str
    outcome: str
    statement: str = ""            # what happened, in one sentence
    where: str = ""                # host and model, or "" when no model ran
    prompt: str = ""               # what the model received
    answer: str = ""               # what the model said, before parsing
    result: Optional[dict] = None  # what the step produced, parsed
    ms: int = 0
    at: str = ""

    @property
    def reached_a_model(self) -> bool:
        """Post: whether this step sent anything to an endpoint."""
        return bool(self.where)


@dataclass
class ItineraryRun:
    """One press of the create button, and every step it ran."""
    run_id: str
    draft_id: str
    request_key: str = ""
    steps: list = field(default_factory=list)     # list[RunStep], in STEPS order
    started_at: str = ""
    finished_at: str = ""                          # set once, and it seals

    @property
    def is_sealed(self) -> bool:
        """Post: whether the record refuses further writes (invariant 3.7)."""
        return bool(self.finished_at)

    @property
    def untested(self) -> list:
        """Post: one statement per step that could not run (spec item 16.5)."""
        return [f"{s.name}: {s.statement}" for s in self.steps
                if s.outcome == OUTCOME_UNTESTED]

    @property
    def failures(self) -> list:
        return [f"{s.name}: {s.statement}" for s in self.steps
                if s.outcome == OUTCOME_FAILED]

    @property
    def is_complete(self) -> bool:
        """
        Post: whether every step ran and none of them failed.

        A run that read no screenshot is not complete, whatever else it did
        (invariant 3.5). A caller that gated on failures alone would treat a
        request whose conversation was never read as a fully reasoned one.
        """
        return (self.is_sealed and not self.untested and not self.failures
                and len(self.steps) == len(STEPS))

    def step(self, name: str) -> Optional[RunStep]:
        return next((s for s in self.steps if s.name == name), None)

    @property
    def endpoints_reached(self) -> list:
        """Post: every host and model this run sent customer text to."""
        seen = []
        for s in self.steps:
            if s.where and s.where not in seen:
                seen.append(s.where)
        return seen

    @property
    def statement(self) -> str:
        done = sum(1 for s in self.steps if s.outcome == OUTCOME_DONE)
        return (f"{done} of {len(STEPS)} step(s) done, "
                f"{len(self.untested)} untested, {len(self.failures)} failed")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _path(run_id: str) -> str:
    """Post: the file this run names. Raises RecordIdError on anything else."""
    from services.itinerary.record_paths import record_path

    return record_path(ITINERARY_RUN_DIR, run_id)


def run_id_for(draft_id: str, started_at: str) -> str:
    """
    Post: `run-` and twelve hex characters, different on every call.

    Not keyed on the request, because a second press is a second run and both
    records are kept (spec item 16.4). Not keyed on the moment alone either:
    `_now()` has second resolution, and two presses inside one second would
    give one id, so the second run would overwrite the first record and break
    invariant 3.7. Random bytes carry the difference.
    """
    seed = f"{draft_id}\x1f{started_at}".encode("utf-8") + os.urandom(8)
    return f"run-{hashlib.sha1(seed).hexdigest()[:12]}"


def save(run: ItineraryRun) -> str:
    """Post: the run is on disk, written atomically."""
    os.makedirs(ITINERARY_RUN_DIR, exist_ok=True)
    target = _path(run.run_id)
    temporary = target + ".tmp"
    with open(temporary, "w", encoding="utf-8") as fh:
        json.dump(asdict(run), fh, ensure_ascii=False, indent=2)
    os.replace(temporary, target)
    return target


def load(run_id: str) -> Optional[ItineraryRun]:
    """
    Post: the run, or None when there is no such record.

    An id that names no record and an id that could name no record both answer
    None. A route that raised on the second would tell a caller which ids the
    store rejects, and the caller has no use for that.
    """
    from services.itinerary.record_paths import RecordIdError

    try:
        path = _path(run_id)
    except RecordIdError:
        return None
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None
    raw["steps"] = [RunStep(**s) for s in raw.get("steps", [])]
    try:
        return ItineraryRun(**raw)
    except TypeError:
        return None


def iter_runs(draft_id: str = "") -> Iterator[ItineraryRun]:
    """
    Yield runs, newest first.

    Pre:  `draft_id` names one draft, or is empty for every run.
    Post: a record whose file is unreadable is skipped rather than raised. One
          bad file must not hide every other run.
    """
    if not os.path.isdir(ITINERARY_RUN_DIR):
        return
    found = []
    for name in sorted(os.listdir(ITINERARY_RUN_DIR)):
        if not name.endswith(".json"):
            continue
        run = load(name[:-5])
        if run is None:
            continue
        if not draft_id or run.draft_id == draft_id:
            found.append(run)
    found.sort(key=lambda r: r.started_at, reverse=True)
    yield from found


def start_run(draft_id: str, request_key: str = "") -> ItineraryRun:
    """
    Open a record for one press of the create button.

    Pre:  `draft_id` names a draft that exists.
    Post: a saved record with no steps, and an id no earlier run holds.
    """
    started = _now()
    run = ItineraryRun(run_id=run_id_for(draft_id, started), draft_id=draft_id,
                       request_key=request_key, started_at=started)
    save(run)
    return run


def record_step(run: ItineraryRun, name: str, outcome: str, statement: str = "",
                where: str = "", prompt: str = "", answer: str = "",
                result: Optional[dict] = None, ms: int = 0) -> RunStep:
    """
    Add one step to an open run and write it to disk.

    Pre:  `name` is in STEPS, `outcome` is in OUTCOMES, and the run is not
          sealed.
    Post: the step is the last one on the record, stamped with the moment it
          finished. The record is on disk before this returns, so a crash in
          the next step keeps everything this one produced.

    Blame: a step added to a sealed run is a caller bug and raises. Evidence a
    later run may rewrite is not evidence (invariant 3.7). An unknown step name
    is a caller bug: a reader who cannot name the step cannot judge it.
    """
    if name not in STEPS:
        raise RunError(f"not a run step: {name!r}")
    if outcome not in OUTCOMES:
        raise RunError(f"not an outcome: {outcome!r}")
    if run.is_sealed:
        raise RunError(f"{run.run_id} is sealed and takes no more steps")

    step = RunStep(name=name, outcome=outcome, statement=statement, where=where,
                   prompt=prompt, answer=answer, result=result, ms=ms,
                   at=_now())
    run.steps.append(step)
    save(run)
    return step


def untested_step(run: ItineraryRun, name: str, reason: str) -> RunStep:
    """
    Record a step that could not run, and say why (ws-03 D43).

    Post: the step is on the record with OUTCOME_UNTESTED, and `run.untested`
          names it. The run continues.

    A step that is off and leaves no entry reads as a step that ran and found
    nothing, and a reviewer would take an unread conversation for an empty one.
    """
    return record_step(run, name, OUTCOME_UNTESTED, statement=reason)


def seal(run: ItineraryRun) -> ItineraryRun:
    """
    Close a run. Post: `finished_at` is set and no further step is accepted.

    Blame: sealing a sealed run is a caller bug and raises, because the second
    call would move the finish time of work that already ended.
    """
    if run.is_sealed:
        raise RunError(f"{run.run_id} is already sealed")
    run.finished_at = _now()
    save(run)
    return run


def run_to_dict(run: ItineraryRun) -> dict:
    """
    One run as a reader over HTTP receives it.

    Post: every step in order, the endpoints the run reached, and the two
          halves of "complete" kept apart, in the shape `check_to_dict` uses.

    The shape lives here rather than in the route, because this module decides
    what a step is and a route that built its own shape would drift from it.
    """
    return {
        "run_id": run.run_id,
        "draft_id": run.draft_id,
        "request_key": run.request_key,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "statement": run.statement,
        "steps": [
            {"name": s.name, "outcome": s.outcome, "statement": s.statement,
             "where": s.where, "prompt": s.prompt, "answer": s.answer,
             "result": s.result, "ms": s.ms, "at": s.at}
            for s in run.steps
        ],
        "untested": run.untested,
        "failures": run.failures,
        "endpoints_reached": run.endpoints_reached,
        "is_sealed": run.is_sealed,
        "is_complete": run.is_complete,
    }
