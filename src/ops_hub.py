"""Client for Bil Weekend's agent API — the AI Hub at /admin/operations/ai.

The division of labour this module implements: Odysseus is the operator. It
holds the model, it runs the schedule, it decides what to suggest. Bil Weekend
holds the record — every run, report, note and suggestion the agent produces is
written there, because that is where the people who act on the work already are.

Before this existed, the agent's output stayed on the phone. An admin could
watch suggestions appear in the worklist with no way to learn which run produced
them, what that run was asked, what it read, or what it concluded about
everything it did not propose on. Mirroring here is what closes that gap.

Documented in the website repo at `docs/agent-api.md`. Four post the agent's
record to a site that can read it:

    POST /api/agent/ops/runs        a run reporting itself, twice per run
    POST /api/agent/ops/proposals   a suggested change, inert until accepted
    POST /api/agent/ops/notes       an observation that asks for nothing
    POST /api/agent/ops/activity    telemetry, one event per tool call

The bookings desk adds calls that run the other way, because the phone has no
inbound route and work must wait where the phone already looks:

    GET  /api/agent/ops/jobs            pricing work, carrying no customer text
    GET  /api/agent/ops/draft-appends   approved replies, carrying the name
    GET  /api/agent/ops/booking-recipients   HMACs, not addresses
    POST /api/agent/ops/booking-replies      what the sent folder answered
    POST /api/agent/ops/booking-templates    the wording, unfilled

The difference between the first two GETs is the whole safety story. A pricing
job names a tour and a party size, because the run that consumes it reasons. An
append names a person, because the run that consumes it does not.

Environment:
    OPS_API_BASE_URL   e.g. https://dev.bilweekend.iq
    OPS_AGENT_TOKEN    the bearer token, set on both sides

Neither is ever accepted as an argument: a caller asks for a post, it does not
supply the authority for one.

Every function here fails soft. A mirror is a copy, and losing the copy must
never cost the original — a run whose report could not be delivered still ran,
and a note whose mirror failed is still in Odysseus's own store. Callers get a
result dict saying what happened; nothing raises.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 20.0

# The operations tasks that mirror to the hub, by name.
#
# Single source of truth: create_ops_agent_tasks.py creates exactly these, and
# task_scheduler mirrors a run to the hub only when its task is one of them.
# Naming them once is what stops the two files drifting apart and quietly
# ending the mirroring for a renamed task.
OPS_TASK_LANES = {
    "Ops Structural Triage": "ambient-structural",
    "Ops Daily Digest": "ambient-digest",
    # The bookings desk. Neither calls a model, and both are named here so a
    # run of either appears in the Hub beside the ones that do — an operator
    # watching a draft that never arrived should find out where it stopped.
    "Bookings Offer Jobs": "bookings-offers",
    "Bookings Reply Scan": "bookings-replies",
    "Bookings Draft Appends": "bookings-drafts",
}

OPS_TASK_NAMES = tuple(OPS_TASK_LANES)


def lane_for_task(task_name: str | None) -> str | None:
    """The lane a task reports under, or None when it is not an ops task.

    None is the signal not to mirror. Odysseus runs many scheduled tasks —
    email sweeps, project summaries — and none of them belong in Bil Weekend's
    operations hub.
    """
    if not task_name:
        return None
    return OPS_TASK_LANES.get(task_name.strip())


# TaskRun statuses, mapped to what the hub accepts.
#
# 'aborted' and 'skipped' both mean the run stopped without completing, which
# is what 'halted' names — most often the external-context gate refusing a run
# that tried to act after reading customer text. They are mapped rather than
# dropped: a run reported as started and never closed would sit in the hub
# reading 'running' forever.
_STATUS_MAP = {
    "success": "success",
    "error": "error",
    "aborted": "halted",
    "skipped": "skipped",
    "running": "running",
    "queued": "running",
}


def hub_status(task_run_status: str | None) -> str:
    """Translate a TaskRun status. Anything unrecognised is an error, not a
    guess — an unknown terminal state is not evidence the run succeeded."""
    return _STATUS_MAP.get((task_run_status or "").strip(), "error")


def as_instant(value) -> str | None:
    """A datetime as a full ISO instant carrying an explicit UTC offset.

    Odysseus stores naive UTC in its task tables. Sent as-is, a naive ISO string
    is read by JavaScript's Date.parse as LOCAL time, not UTC — so a run would
    land in the hub shifted by the reader's offset, and 'started 3 hours ago'
    would be wrong by that much. Stamping the offset is what stops that.
    """
    if value is None:
        return None
    try:
        if value.tzinfo is None:
            from datetime import timezone as _tz

            value = value.replace(tzinfo=_tz.utc)
        return value.isoformat()
    except Exception:
        return None


def hub_config() -> tuple[str, str] | None:
    """Base URL and bearer token, or None when either is missing.

    Inv: returns None rather than a partial config. A base URL with no token
    would post unauthenticated and collect 401s on a schedule.
    """
    base_url = os.environ.get("OPS_API_BASE_URL", "").strip().rstrip("/")
    token = os.environ.get("OPS_AGENT_TOKEN", "").strip()
    if not base_url or not token:
        return None
    return base_url, token


async def _post(path: str, payload: dict) -> dict:
    """One POST to the agent API.

    Post: {"ok": True, "body": <decoded>} on 2xx, else {"ok": False,
    "error": <reason>}. Never raises — see the module docstring on failing soft.
    """
    config = hub_config()
    if config is None:
        return {
            "ok": False,
            "error": "OPS_API_BASE_URL and OPS_AGENT_TOKEN are not both set.",
            "unconfigured": True,
        }
    base_url, token = config

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{base_url}{path}",
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
            )
    except Exception as exc:
        return {"ok": False, "error": f"Could not reach {base_url}{path}: {exc}"}

    if response.status_code >= 300:
        return {
            "ok": False,
            "error": f"{path} returned {response.status_code}: {response.text[:300]}",
            "status_code": response.status_code,
        }

    try:
        return {"ok": True, "body": response.json() if response.text else {}}
    except ValueError:
        return {"ok": False, "error": f"{path} returned a body that is not JSON."}


async def post_run(**fields: Any) -> dict:
    """Report a run, at its start or at its end.

    Pre: `runRef`, `taskName` and `lane` are set. Post: the hub holds one row
    for this runRef, merging what this call states over what the start call did.
    Inv: fields omitted here are left as they were on the hub — the finish
    report does not resend the prompt.
    """
    return await _post("/api/agent/ops/runs", fields)


async def post_proposals(author: str, proposals: list[dict]) -> dict:
    """Suggest changes. Nothing posted alters a record until an admin accepts."""
    if not proposals:
        return {"ok": True, "body": {"accepted": [], "rejected": [], "skipped": []}}
    return await _post(
        "/api/agent/ops/proposals", {"author": author, "proposals": proposals}
    )


async def post_notes(notes: list[dict]) -> dict:
    """Mirror observations. Accepted on every source, queue included."""
    if not notes:
        return {"ok": True, "body": {"accepted": [], "rejected": []}}
    return await _post("/api/agent/ops/notes", {"notes": notes})


async def post_activity(events: list[dict]) -> dict:
    """Mirror telemetry — one event per tool call, fetch or refusal."""
    if not events:
        return {"ok": True, "body": {"accepted": 0, "rejected": []}}
    return await _post("/api/agent/ops/activity", {"events": events})


# ------------------------------------------------------ the bookings desk ---
#
# Four calls that run the other way, or that carry something no other endpoint
# does. `claim_offer_jobs` is the only GET here, and it is the only place where
# Bil Weekend gives Odysseus work rather than receiving a record from it.


async def _get(path: str, params: dict | None = None) -> dict:
    """One GET to the agent API.

    Post: same shape as `_post`. Never raises, for the same reason: a poll that
    could not reach the site has not lost anything, and the next one will.
    """
    config = hub_config()
    if config is None:
        return {
            "ok": False,
            "error": "OPS_API_BASE_URL and OPS_AGENT_TOKEN are not both set.",
            "unconfigured": True,
        }
    base_url, token = config

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{base_url}{path}",
                headers={"Authorization": f"Bearer {token}"},
                params=params or {},
            )
    except Exception as exc:
        return {"ok": False, "error": f"Could not reach {base_url}{path}: {exc}"}

    if response.status_code >= 300:
        return {
            "ok": False,
            "error": f"{path} returned {response.status_code}: {response.text[:300]}",
            "status_code": response.status_code,
        }

    try:
        return {"ok": True, "body": response.json() if response.text else {}}
    except ValueError:
        return {"ok": False, "error": f"{path} returned a body that is not JSON."}


async def claim_offer_jobs(limit: int = 10) -> dict:
    """Take pricing work waiting for this agent.

    Post: {"ok": True, "body": {"jobs": [...]}} — and the jobs it names are now
    claimed on the site. A second call gets different ones.
    Inv: every job returned carries a tour and a party size and no customer
    text, so a run may read this and still act afterwards. That is what lets one
    run both price a job and report the answer.
    """
    return await _get("/api/agent/ops/jobs", {"limit": limit})


async def post_job_result(job_id: str, **fields: Any) -> dict:
    """Report what a pricing run produced. Closes the job either way.

    Pre: `fields` carries `emailBody` or `error`. A result saying neither is
    refused, because a finished job with an empty draft tells the operator
    nothing about why.
    """
    return await _post(f"/api/agent/ops/jobs/{job_id}/result", fields)


async def claim_draft_appends(limit: int = 10) -> dict:
    """Take approved replies waiting to be filed into Gmail Drafts.

    Post: {"ok": True, "body": {"appends": [...]}} — and the rows it names are
    now claimed on the site.
    Inv: unlike `claim_offer_jobs`, every row this returns carries a customer's
    name and address. That is safe only because its consumer,
    `services.bookings.draft_append`, calls no model. Do not read these rows in
    any run that reasons.
    """
    return await _get("/api/agent/ops/draft-appends", {"limit": limit})


async def post_draft_append_result(append_id: str, **fields: Any) -> dict:
    """Report where a draft was filed. Closes the row either way.

    Pre: `fields` carries `folder` or `error`. An append reporting neither
    leaves the panel claiming a draft exists in a mailbox nobody can name.
    """
    return await _post(f"/api/agent/ops/draft-appends/{append_id}/result", fields)


async def post_booking_templates(templates: list[dict]) -> dict:
    """Push the wording operations sends a registration.

    Unfilled, placeholders and all. The panel shows it before anything has run,
    and fills the deposit one itself — a group departure is priced already.
    """
    if not templates:
        return {"ok": True, "body": {"accepted": 0, "rejected": []}}
    return await _post("/api/agent/ops/booking-templates", {"templates": templates})


async def post_booking_replies(replies: list[dict]) -> dict:
    """Report which registrations the Sent folder already answered.

    Evidence, never a decision. Nothing this posts writes a follow-up field.
    """
    if not replies:
        return {"ok": True, "body": {"accepted": 0, "rejected": []}}
    return await _post("/api/agent/ops/booking-replies", {"replies": replies})


# ------------------------------------------------------- the run marker -----

# Which run is currently executing, shared between two processes.
#
# The scheduler runs in the app; the ops MCP server is a separate stdio
# subprocess. Only the scheduler knows the run id, and only the MCP server knows
# what the run actually read and staged. Neither can see the other's memory.
#
# So the scheduler writes the run id to a file before it executes, and the MCP
# server reads it on each tool call and tallies into it. This is deliberately
# not time-correlation ("which ops calls happened during this run's window"):
# that infers attribution rather than recording it, and it guesses wrong the
# moment two runs overlap or a call is logged late.
#
# A single file is safe here because runs do not overlap — the scheduler holds a
# model slot for the length of a run, and the ops calls inside one are
# sequential.

_MARKER_NAME = "ops_current_run.json"


def _marker_path() -> Path:
    from src.constants import DATA_DIR

    return Path(DATA_DIR) / _MARKER_NAME


def _read_marker() -> dict | None:
    try:
        return json.loads(_marker_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        logger.debug("ops run marker is unreadable", exc_info=True)
        return None


def _write_marker(marker: dict) -> None:
    """Replace the marker atomically.

    Written to a temp file in the same directory and renamed, so a reader can
    never observe a half-written marker. os.replace is atomic on both POSIX and
    Windows when source and destination share a filesystem, which they do here.
    """
    path = _marker_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", dir=path.parent, delete=False, encoding="utf-8"
        ) as handle:
            json.dump(marker, handle)
            temporary = handle.name
        os.replace(temporary, path)
    except Exception:
        logger.debug("Could not write the ops run marker", exc_info=True)


def begin_run(run_ref: str, task_name: str, lane: str) -> None:
    """Mark a run as current, with an empty tally.

    Pre (caller-owed): the previous run has ended. Post: ops tool calls made
    from now on are attributed to `run_ref`.
    """
    _write_marker({
        "run_ref": run_ref,
        "task_name": task_name,
        "lane": lane,
        "read_customer_text": False,
        "proposals_posted": 0,
    })


def current_run() -> dict | None:
    """The run in progress, or None outside one."""
    return _read_marker()


def end_run() -> dict | None:
    """Clear the marker and return the tally it accumulated.

    Post: no run is current. Returning the tally rather than requiring a second
    read is what lets the caller close the run in one step, with no window in
    which the marker is gone but the figures have not been read.
    """
    marker = _read_marker()
    try:
        _marker_path().unlink()
    except FileNotFoundError:
        pass
    except Exception:
        logger.debug("Could not clear the ops run marker", exc_info=True)
    return marker


def note_tool_call(action: str, *, proposals_posted: int = 0) -> str | None:
    """Record what an ops tool call means for the current run's tally.

    Pre: called by the ops MCP server, once per tool call it serves.
    Post: the marker reflects this call, and the current run reference is
    returned so the caller can attribute its activity event — or None when no
    run is in progress, which is the normal case for a call made from the chat
    UI rather than from a schedule.

    `worklist_full` is the one action that sets read_customer_text. That is the
    external-context gate expressed as a fact: reading it arms the gate, and a
    run past that point may not act. Recording it here means the hub reports
    what the run did, not what its task was designed to do — a distinction that
    matters exactly when a run does something unexpected.

    A FAILED worklist_full still sets it, and must. OpsApiError is raised rather
    than returned precisely so the MCP framework marks the result isError, which
    is what makes McpManager mark it untrusted_content and arm the gate. The
    gate does not care that the read failed; the error body is remote text and
    the run is restricted either way. A caller that recorded only successful
    reads would report a restricted run as one that could still act.
    """
    marker = _read_marker()
    if marker is None:
        return None

    if action == "worklist_full":
        marker["read_customer_text"] = True
    if proposals_posted:
        marker["proposals_posted"] = int(marker.get("proposals_posted", 0)) + proposals_posted

    _write_marker(marker)
    return marker.get("run_ref")
