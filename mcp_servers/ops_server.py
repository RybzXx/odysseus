"""
ops_server.py

MCP server exposing the Bil Weekend operations worklist and the agent's
staging channel.

Reads and writes go different ways round, and the split is deliberate.

READS talk to Supabase directly (bookings, contacts, curated_requests,
queue_requests, operations_followup, tours) rather than to Bil Weekend's
website API, doing the source-table + operations_followup merge in Python.
The merge logic (summary composition, phone formatting, sort order, risk
verdict) was read directly out of Bil Weekend's actual admin source
(OperationsWorklist.tsx / operationsWorklist.ts / antiAbuse.ts) during a
research pass, not guessed.

WRITES go to Bil Weekend's agent API (src/ops_hub.py), not to Supabase, and
they must. A suggestion accepted through that API takes the same path an
admin's own edit takes — the roster check, the version check, and the push
back to the Google Sheet. Writing the table directly from here skips all
three, and for a queue row it leaves Supabase and the sheet disagreeing with
nobody told. Reads have no such requirement, which is why they stay direct.

Everything the agent produces is mirrored to that API so it appears in Bil
Weekend's AI Hub (/admin/operations/ai): the run, its report, its notes, its
suggestions and its tool calls. The local tables below are the fallback for
when the API cannot be reached, never the destination.

Five tools. The split between the first two is a security boundary, not a
convenience:

  worklist_structural  the worklist with every customer-written field removed.
                       Classified SYSTEM in src/tool_capabilities.py, so reading
                       it leaves the run able to act.
  worklist_full        the same rows with names, emails, phones and summaries.
                       Classified EXTERNAL_UNTRUSTED, so reading it arms the
                       external-context gate and the run may only report
                       afterwards.
  stage_change         suggests a patch (status/operator/next_action_date/
                       moderation). Posted to Bil Weekend as a proposal, which
                       an admin accepts or discards in the AI Hub. Falls back
                       to Odysseus's local staging table only when the API
                       refuses it or cannot be reached — one suggestion is
                       never in both queues at once, because two review queues
                       for one suggestion is a way to apply it twice.
  add_note             leaves a note against one worklist key. Written to
                       Odysseus's own store AND mirrored to Bil Weekend, so it
                       shows in both panels. The local write is the one that
                       must succeed; it works even without SUPABASE_URL/
                       SUPABASE_SERVICE_ROLE_KEY set.

The classification is per tool rather than per response because
McpManager._do_call builds the result dict and marks untrusted_content only on
isError — a server cannot mark a successful response untrusted. Two tools with
two static classifications say the same thing without lying about success.

Environment:
  SUPABASE_URL                e.g. https://hjjkmknqunwlhrfulrdl.supabase.co
  SUPABASE_SERVICE_ROLE_KEY   full read/write access — same names Bil
                               Weekend's own web app uses, so its .env can be
                               copied directly rather than inventing a
                               separate credential. Reads only, now that
                               writes go through the agent API.
  OPS_API_BASE_URL            e.g. https://dev.bilweekend.iq
  OPS_AGENT_TOKEN             bearer token for the agent API. Without both,
                               every mirror is skipped and stage_change falls
                               back to local staging — the tools still work,
                               nothing reaches the AI Hub.

Neither is ever accepted as a tool argument: the model asks for an action, it
does not supply the authority for it.
"""

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.database import SessionLocal, OperationsNote, OperationsStagedChange
from src import ops_hub

server = Server("ops")

_TIMEOUT_SECONDS = 30.0

_CONFIG_ERROR = (
    "Supabase is not configured. Set SUPABASE_URL and "
    "SUPABASE_SERVICE_ROLE_KEY in the environment this server runs in."
)


def _config() -> tuple[str, str] | None:
    """Base URL and service-role key, or None when either is missing."""
    base_url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not base_url or not key:
        return None
    return base_url, key


class OpsApiError(RuntimeError):
    """A failed call to Supabase, or a rejected local operation.

    Raised rather than returned, and that is load-bearing. worklist_structural
    is classified SYSTEM, so its results do not arm the external-context gate;
    an error body is the remote side talking, not an allowlist projection,
    and must not enter the run as trusted text. Raising makes the MCP
    framework return isError, which is what makes McpManager._do_call mark
    the result untrusted_content and arm the gate.
    """


async def _sb_request(
    method: str,
    table: str,
    params: dict | None = None,
    json_body=None,
    prefer: str | None = None,
) -> list | dict:
    """One request to Supabase's PostgREST API (/rest/v1/<table>).

    Pre: _config() has already been checked by the caller.
    Post: the decoded JSON body of a 2xx response (a list of rows for GET,
    whatever PostgREST returns for a write). Raises OpsApiError on anything
    else.
    Inv: fails closed — a non-2xx, a transport failure and an unparseable
    body are all errors, never a partial view. A caller that treated a
    truncated worklist as complete would report or act on rows it never saw.
    """
    base_url, key = _config()  # type: ignore[misc]
    url = f"{base_url}/rest/v1/{table}"
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    if prefer:
        headers["Prefer"] = prefer

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.request(
                method, url, headers=headers, params=params, json=json_body
            )
    except Exception as exc:
        raise OpsApiError(f"Could not reach Supabase: {exc}") from exc

    if response.status_code >= 300:
        raise OpsApiError(
            f"Supabase returned {response.status_code}: {response.text[:300]}"
        )

    if not response.text:
        return []
    try:
        return response.json()
    except ValueError as exc:
        raise OpsApiError("Supabase returned a body that is not JSON.") from exc


_STATUS_ENUM = ["New", "In Progress", "Replied", "On Hold", "Confirmed", "Rejected"]
_OPEN_STATUSES = ["New", "In Progress", "Replied", "On Hold"]
_CLOSED_STATUSES = ["Confirmed", "Rejected"]
_MODERATION_ENUM = ["flagged", "spam"]

# source label -> (table, data.name key, data.email key, data.phone key)
# Confirmed against the live schema: bookings/contacts/curated_requests store
# the submitted form as a jsonb `data` blob; only queue_requests is flat
# (handled separately below).
_JSONB_SOURCES = {
    "booking": ("bookings", "name", "email", "phone"),
    "contact": ("contacts", "name", "email", None),
    "curated": ("curated_requests", "name", "email", "phone"),
}

_STRUCTURAL_FIELDS = (
    "key", "source", "source_id", "status", "operator", "next_action_date",
    "moderation", "updated_at", "created_at", "risk_score", "flagged", "risk",
)


# Bil Weekend's data-entry team types "Not known" into a queue column for a
# field the submitter left blank, rather than leaving it NULL, and the intake
# form concatenates a country-code sign onto it ("+Not known"). Both carry the
# same absence of information as NULL, so the worklist must treat them the
# same way. Mirrors _isEmptyDetailValue in static/js/operations.js, which does
# this for the raw-record detail view — that view keeps its own copy because it
# renders the raw record, empties included, behind a "show empty fields"
# toggle, and so cannot share a helper that suppresses them.
_PLACEHOLDER_VALUES = {"not known"}


def _is_empty_value(value) -> bool:
    """True when a column carries no information.

    Pre:  value is whatever the source column holds — any type.
    Post: True for None, for blank text, and for the placeholders the intake
          sources write in place of NULL; False for every real value.
    Inv:  a real value is never suppressed. The placeholder set is matched
          whole and case-insensitively, after trimming surrounding space and a
          leading country-code sign, never as a substring — "Not known Road"
          is a real address and survives.
    """
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    stripped = value.strip().lstrip("+-").strip()
    return not stripped or stripped.casefold() in _PLACEHOLDER_VALUES


def _day_count_summary(value) -> str | None:
    """A trip length carrying exactly one unit.

    Pre:  value is the source column — an int, a bare number as text, or text
          that already carries the unit ("10 days", which is what the queue's
          free-text trip_days column actually holds).
    Post: None when the value is empty; otherwise the value with exactly one
          trailing unit. Never "10 days days".
    """
    if _is_empty_value(value):
        return None
    text = str(value).strip()
    if text.casefold().endswith(("day", "days")):
        return text
    return f"{text} days"


def _contact_field(value) -> str | None:
    """A name or email address, or None when the source only had a placeholder.

    Pre:  value is the source column.
    Post: None for a placeholder, the value unchanged otherwise.
    Inv:  the row stays identifiable. operations.js titles a row
          `row.name || row.email || row.key`, so suppressing both contact
          fields falls back to the key rather than leaving the row nameless —
          a visible key beats a confident "Not known".
    """
    return None if _is_empty_value(value) else value


def _phone_display(country_code, phone) -> str | None:
    """Country code + number, as Bil Weekend's phoneDisplay() renders it.

    Read from app/lib/phone.ts's call sites rather than the file itself
    (not opened this session) — country_code and phone are stored as
    separate fields on every source that has a phone, and every call site
    passes them together. Falls back to the bare number when there's no
    country code to prefix, rather than dropping the phone entirely.
    """
    if _is_empty_value(phone):
        return None
    return f"{country_code} {phone}".strip() if country_code else str(phone)


def _risk_verdict(
    risk_score,
    flagged,
    moderation: str | None,
    intake_status,
    scored: bool,
) -> str:
    """'confirmed-spam' | 'suspected' | 'clean' | 'not-scored'.

    Read verbatim from app/lib/antiAbuse.ts:riskVerdict() during this
    session's research pass — an admin's own moderation="spam" or an
    intake-time honeypot hit outrank the scorer and both read as
    confirmed-spam; an unscored source (queue, app_booking) is never
    "clean", since that would claim a verdict nothing ever computed.
    """
    if moderation == "spam":
        return "confirmed-spam"
    if intake_status == "spam":
        return "confirmed-spam"
    if not scored:
        return "not-scored"
    if flagged is True:
        return "suspected"
    # shouldFlag()'s threshold was not read this session — 50 is a stated
    # assumption, not sourced. Flag via `flagged` (which IS sourced) in the
    # meantime; the exact cutoff is a follow-up.
    if isinstance(risk_score, (int, float)) and risk_score >= 50:
        return "suspected"
    return "clean"


def _curated_travel_window(data: dict) -> str | None:
    """Read from operationsWorklist.ts:curatedTravelWindow()."""
    if data.get("travelDateMode") == "exact":
        return data.get("exactDate") or None
    parts = [p for p in (data.get("travelMonth"), data.get("travelYear")) if p]
    return " ".join(str(p) for p in parts) if parts else None


async def _fetch_merged_worklist() -> list[dict]:
    """The unified worklist: bookings + contacts + curated_requests (each a
    Supabase jsonb blob, keyed by id) left-joined against operations_followup
    on (source, source_id), plus queue_requests, which is flat and
    self-contained already.

    Summary composition, phone formatting and risk verdict match Bil
    Weekend's own admin source exactly (operationsWorklist.ts, antiAbuse.ts),
    read during this session's research pass rather than guessed.

    Note: Bil Weekend's fifth source, "App Bookings", lives in a *separate*
    Supabase project — out of reach of this service-role key, so it's absent
    from this worklist entirely.
    """
    # All six reads are independent — fire them together rather than one
    # round-trip after another. This was the actual cause of "always takes a
    # while to load": six sequential Supabase requests, not the absence of a
    # cache. loadWorklistInputs() in Bil Weekend's own source does the same
    # six reads with Promise.all — this mirrors that, which the first version
    # of this function didn't.
    source_tables = list(_JSONB_SOURCES.items())
    followup_rows, tour_rows, queue_rows, *source_results = await asyncio.gather(
        _sb_request("GET", "operations_followup", params={"select": "*"}),
        _sb_request("GET", "tours", params={"select": "id,data"}),
        _sb_request("GET", "queue_requests", params={"select": "*"}),
        *(
            _sb_request("GET", table, params={"select": "id,data"})
            for _, (table, *_rest) in source_tables
        ),
    )

    followup_by_key = {(r["source"], r["source_id"]): r for r in followup_rows}

    tour_names = {}
    for t in tour_rows:
        tdata = t.get("data") or {}
        if isinstance(tdata, str):
            try:
                tdata = json.loads(tdata)
            except (json.JSONDecodeError, TypeError):
                tdata = {}
        tour_names[t["id"]] = tdata.get("name")

    rows: list[dict] = []

    for (source, (table, name_f, email_f, phone_f)), source_rows in zip(source_tables, source_results):
        for r in source_rows:
            source_id = r["id"]
            data = r.get("data") or {}
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    data = {}
            followup = followup_by_key.get((source, source_id)) or {}

            if source == "booking":
                summary = [
                    tour_names.get(data.get("tourId")),
                    f"{data['partySize']} guests" if data.get("partySize") else None,
                ]
            elif source == "contact":
                summary = [(data.get("message") or "")[:70] or None]
            elif source == "curated":
                summary = [
                    ", ".join(data["regions"]) if data.get("regions") else None,
                    _day_count_summary(data.get("tripDays")),
                    f"{data['numberOfPeople']} people" if data.get("numberOfPeople") else None,
                    _curated_travel_window(data),
                ]
            else:
                summary = []

            risk_score = data.get("riskScore")
            flagged = data.get("flagged")
            moderation = followup.get("moderation")
            intake_status = data.get("status")

            rows.append({
                "key": f"{source}:{source_id}",
                "source": source,
                "source_id": source_id,
                "status": followup.get("status") or "New",
                "operator": followup.get("operator"),
                "next_action_date": followup.get("next_action_date"),
                "moderation": moderation,
                "updated_at": followup.get("updated_at"),
                "created_at": data.get("submittedAt"),
                "risk_score": risk_score,
                "flagged": flagged,
                "risk": _risk_verdict(risk_score, flagged, moderation, intake_status, scored=True),
                "name": _contact_field(data.get(name_f)),
                "email": _contact_field(data.get(email_f)) if email_f else None,
                "phone": _phone_display(data.get("countryCode"), data.get(phone_f)) if phone_f else None,
                "summary": [s for s in summary if not _is_empty_value(s)],
            })

    for r in queue_rows:
        moderation = r.get("moderation")
        summary = [
            r.get("service_type"), r.get("request_type"), r.get("regions"),
            _day_count_summary(r.get("trip_days")),
            r.get("travel_date"),
        ]
        rows.append({
            "key": f"queue:{r.get('row_id')}",
            "source": "queue",
            "source_id": r.get("row_id"),
            "status": r.get("status") or "New",
            "operator": r.get("operator"),
            "next_action_date": r.get("next_action_date"),
            "moderation": moderation,
            "updated_at": r.get("updated_at"),
            "created_at": r.get("created_at") or r.get("submitted_at"),
            "risk_score": None,
            "flagged": None,
            # The queue is typed in by the data-entry team and never scored —
            # the only verdict it can carry is an admin's own moderation call.
            "risk": _risk_verdict(None, None, moderation, None, scored=False),
            "name": _contact_field(r.get("full_name")),
            "email": _contact_field(r.get("customer_email") or r.get("respondent_email")),
            # The queue has no separate country-code column, so its phone is
            # passed through rather than composed — but it carries the same
            # "+Not known" placeholder the composed sources do.
            "phone": None if _is_empty_value(r.get("phone")) else r.get("phone"),
            "summary": [s for s in summary if not _is_empty_value(s)],
        })

    return rows


async def _fetch_full_record(source: str, source_id: str) -> dict | None:
    """Every field Supabase holds for one request — not the worklist's
    composed summary, the raw submitted record. For the three jsonb sources
    that's the whole `data` blob (curated_requests carries the full
    questionnaire: accommodation, dietary needs, walking comfort, etc. — none
    of it is in the worklist row); for queue_requests, which is already flat,
    it's every column. Returns None if the key doesn't resolve to a row.
    """
    if source == "queue":
        rows = await _sb_request("GET", "queue_requests", params={"select": "*", "row_id": f"eq.{source_id}"})
        return rows[0] if rows else None

    table = _JSONB_SOURCES.get(source, (None,))[0]
    if not table:
        return None
    rows = await _sb_request("GET", table, params={"select": "id,data", "id": f"eq.{source_id}"})
    if not rows:
        return None
    data = rows[0].get("data") or {}
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            data = {}
    return data


def _sort_worklist(rows: list[dict]) -> list[dict]:
    """nextActionDate ascending (undated rows last), then created_at
    (submittedAt) descending — read from operationsWorklist.ts:
    buildWorklist()'s own .sort(). Replaces this module's earlier
    (unsourced) updated_at-only sort."""
    has_date = [r for r in rows if r.get("next_action_date")]
    no_date = [r for r in rows if not r.get("next_action_date")]
    has_date.sort(key=lambda r: r["next_action_date"])
    no_date.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return has_date + no_date


def _project(rows: list[dict], detail: str, status: str | None, limit: int | None) -> list[dict]:
    """Filter/sort/trim, then strip customer-written fields for 'structural'."""
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = _sort_worklist(rows)
    if limit:
        rows = rows[:limit]
    if detail == "structural":
        rows = [{k: r.get(k) for k in _STRUCTURAL_FIELDS} for r in rows]
    return rows


def _parse_worklist_args(arguments: dict) -> tuple[str | None, int | None]:
    """status/limit as the model sent them, defensively typed.

    Pre: `arguments` is whatever the model sent — the MCP layer does not
    enforce inputSchema, so every field may be any type.
    """
    status = arguments.get("status")
    status = status.strip() if isinstance(status, str) and status.strip() else None

    limit = arguments.get("limit")
    # bool is a subclass of int in Python, so isinstance(True, int) passes —
    # exclude it explicitly rather than silently treating True as 1.
    limit = limit if type(limit) is int and limit > 0 else None

    return status, limit


def _write_note(key: str, author: str, text: str) -> dict:
    """Persist a note in Odysseus's own store.

    Local, not a Supabase call — runs even when SUPABASE_URL/
    SUPABASE_SERVICE_ROLE_KEY are unset, unlike the worklist tools.
    """
    db = SessionLocal()
    try:
        note = OperationsNote(
            id=str(uuid.uuid4()),
            key=key,
            owner=None,
            author=author,
            source="agent",
            text=text,
        )
        db.add(note)
        db.commit()
        db.refresh(note)
        return {
            "id": note.id,
            "key": note.key,
            "author": note.author,
            "text": note.text,
            "created_at": note.created_at.isoformat() if note.created_at else None,
        }
    finally:
        db.close()


async def _mirror_note(key: str, author: str, text: str) -> dict:
    """Copy one note to Bil Weekend's AI Hub.

    Post: a result dict describing what happened, never an exception. The local
    note is already written by the time this runs, and losing the copy must not
    lose the original.
    """
    result = await ops_hub.post_notes([{
        "key": key,
        "author": author,
        "body": text,
        "runRef": (ops_hub.current_run() or {}).get("run_ref"),
    }])
    if result.get("ok"):
        return {"mirrored": True}
    return {"mirrored": False, "reason": result.get("error")}


_PATCH_FIELDS = {"status", "operator", "next_action_date", "moderation"}


def _validate_patch(patch: dict) -> str | None:
    """None if valid, else a human-readable reason it isn't."""
    if not isinstance(patch, dict) or not patch:
        return "patch must be a non-empty object"
    unknown = set(patch.keys()) - _PATCH_FIELDS
    if unknown:
        return f"unknown patch field(s): {', '.join(sorted(unknown))}"
    if "status" in patch and patch["status"] not in _STATUS_ENUM:
        return f"status must be one of {_STATUS_ENUM}"
    if "moderation" in patch and patch["moderation"] not in (*_MODERATION_ENUM, None):
        return f"moderation must be one of {_MODERATION_ENUM} or null"
    return None


def _stage_change(
    key: str,
    patch: dict,
    expected_updated_at: str | None,
    author: str,
    rationale: str | None,
) -> dict:
    """Write one staged patch to Odysseus's own store. Never touches Supabase
    — see routes/operations/operations_routes.py's push endpoint for that."""
    reason = _validate_patch(patch)
    if reason:
        raise OpsApiError(f"Invalid patch: {reason}")

    db = SessionLocal()
    try:
        row = OperationsStagedChange(
            id=str(uuid.uuid4()),
            key=key,
            patch=json.dumps(patch),
            expected_updated_at=expected_updated_at,
            author=author,
            rationale=rationale,
            conflict=False,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _staged_to_dict(row)
    finally:
        db.close()


async def _propose_or_stage(
    key: str,
    patch: dict,
    expected_updated_at: str | None,
    author: str,
    rationale: str | None,
) -> dict:
    """Send one suggestion to Bil Weekend, or stage it locally if that fails.

    Pre: `patch` has passed _validate_patch.
    Post: exactly one of — the suggestion is a pending proposal in Bil Weekend's
    AI Hub, or it is a row in Odysseus's local staging table. Never both.
    Inv: "never both" is the whole contract. A suggestion sitting in two review
    queues can be accepted in one and pushed from the other, applying the same
    change twice and defeating the version check that exists to stop exactly
    that.

    The fallback is not a failure mode to be tidied away. It is what keeps a
    run's work when the phone has no signal, when the token is unset, and when
    the suggestion names a queue row — which Bil Weekend refuses on purpose,
    because the Google Sheet moves those rows without its admin panel acting.
    """
    remote = await ops_hub.post_proposals(author, [{
        "key": key,
        "patch": patch,
        "expectedUpdatedAt": expected_updated_at,
        "rationale": rationale,
    }])

    if remote.get("ok"):
        body = remote.get("body") or {}
        accepted = body.get("accepted") or []
        if accepted:
            ops_hub.note_tool_call("stage_change", proposals_posted=1)
            return {
                "destination": "bilweekend",
                "state": "pending",
                "id": accepted[0].get("id"),
                "key": key,
                "patch": patch,
                "rationale": rationale,
                "note": "An admin accepts or discards this in /admin/operations/ai.",
            }

        # A 200 that accepted nothing is a refusal with a reason attached, and
        # the reason is worth carrying into the fallback: "already has a pending
        # proposal" and "queue rows are not proposable" call for different
        # responses from whoever reads the staged row later.
        refusals = [entry.get("reason") for entry in (body.get("rejected") or [])]
        refusals += [entry.get("reason") for entry in (body.get("skipped") or [])]
        reason = "; ".join(filter(None, refusals)) or "the API accepted nothing"
    else:
        reason = remote.get("error") or "unknown error"

    staged = _stage_change(key, patch, expected_updated_at, f"agent:{author}", rationale)
    staged["destination"] = "odysseus-local"
    staged["fallback_reason"] = reason
    staged["note"] = (
        "Bil Weekend did not take this suggestion, so it was staged in Odysseus "
        "instead. A human pushes or discards it in the Operations panel's Push view."
    )
    return staged


async def _current_updated_at(source: str, source_id: str) -> str | None:
    """The live updated_at for one worklist key, right now — None if no row
    exists yet (a followup row that's never been touched)."""
    if source == "queue":
        rows = await _sb_request(
            "GET", "queue_requests",
            params={"select": "updated_at", "row_id": f"eq.{source_id}"},
        )
    else:
        rows = await _sb_request(
            "GET", "operations_followup",
            params={"select": "updated_at", "source": f"eq.{source}", "source_id": f"eq.{source_id}"},
        )
    return rows[0]["updated_at"] if rows else None


async def _apply_patch(source: str, source_id: str, patch: dict) -> None:
    """Write a merged patch to its owning Supabase table.

    Pre: the conflict check (_current_updated_at vs. the group's expected
    value) has already passed.
    Post: the row is written. Raises OpsApiError on failure — a caller that
    swallowed this would report a push as successful when nothing landed.
    Inv: queue_requests rows always pre-exist (PATCH); operations_followup
    rows may not (upsert via merge-duplicates) — an untouched request has no
    follow-up row until its first edit.
    """
    if source == "queue":
        await _sb_request(
            "PATCH", "queue_requests",
            params={"row_id": f"eq.{source_id}"},
            json_body=patch,
        )
    else:
        await _sb_request(
            "POST", "operations_followup",
            params={"on_conflict": "source,source_id"},
            json_body={"source": source, "source_id": source_id, **patch},
            prefer="resolution=merge-duplicates",
        )


async def _push_staged_changes() -> dict:
    """Batch-apply every non-conflict staged change to Supabase.

    Pre: none — safe to call with an empty staging table.
    Post: every key with staged changes is either fully applied (its staged
    rows deleted) or marked conflict=True (kept, for review) — never a
    silent partial write for one key.
    Inv: staged changes for the same key are merged into one write and
    checked against the earliest one's expected_updated_at — pushing two
    edits to the same key can never conflict with itself just because the
    first write in the batch moved the row's own updated_at.
    """
    if _config() is None:
        raise OpsApiError(_CONFIG_ERROR)

    db = SessionLocal()
    try:
        staged = db.query(OperationsStagedChange).filter(
            OperationsStagedChange.conflict.is_(False)
        ).order_by(OperationsStagedChange.created_at.asc()).all()

        by_key: dict[str, list[OperationsStagedChange]] = {}
        for row in staged:
            by_key.setdefault(row.key, []).append(row)

        pushed, conflicted, failed = [], [], []

        for key, group in by_key.items():
            source, source_id = key.split(":", 1)
            merged: dict = {}
            for row in group:
                merged.update(json.loads(row.patch))
            expected = group[0].expected_updated_at

            try:
                current = await _current_updated_at(source, source_id)
            except OpsApiError as exc:
                failed.append({"key": key, "error": str(exc)})
                continue

            if current != expected:
                for row in group:
                    row.conflict = True
                conflicted.append({"key": key, "expected": expected, "current": current})
                continue

            try:
                await _apply_patch(source, source_id, merged)
            except OpsApiError as exc:
                failed.append({"key": key, "error": str(exc)})
                continue

            for row in group:
                db.delete(row)
            pushed.append({"key": key, "patch": merged})

        db.commit()
        return {"pushed": pushed, "conflicted": conflicted, "failed": failed}
    finally:
        db.close()


def _staged_to_dict(row: OperationsStagedChange) -> dict:
    return {
        "id": row.id,
        "key": row.key,
        "patch": json.loads(row.patch),
        "expected_updated_at": row.expected_updated_at,
        "author": row.author,
        "rationale": row.rationale,
        "conflict": row.conflict,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _list_staged() -> list[dict]:
    db = SessionLocal()
    try:
        rows = db.query(OperationsStagedChange).order_by(OperationsStagedChange.created_at.asc()).all()
        return [_staged_to_dict(r) for r in rows]
    finally:
        db.close()


def _discard_staged(staged_id: str) -> bool:
    """True if a row was removed, False if staged_id didn't exist — the
    caller decides whether that's a 404 or a no-op."""
    db = SessionLocal()
    try:
        row = db.query(OperationsStagedChange).filter(OperationsStagedChange.id == staged_id).first()
        if not row:
            return False
        db.delete(row)
        db.commit()
        return True
    finally:
        db.close()


_WORKLIST_FILTER_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": _STATUS_ENUM,
            "description": "Only rows with this follow-up status.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "description": "At most this many rows, in worklist order.",
        },
    },
}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="worklist_structural",
            description=(
                "The operations worklist without any customer-written text: status, "
                "operator, dates, and the intake scorer's verdict (risk score / "
                "flagged / a computed risk label). Use this when you intend to "
                "stage a change — it is the only worklist read that leaves you "
                "able to call stage_change afterwards."
            ),
            inputSchema=_WORKLIST_FILTER_SCHEMA,
        ),
        Tool(
            name="worklist_full",
            description=(
                "The operations worklist as the admin sees it, including names, "
                "emails, phones and request summaries. Use this only to read and "
                "report — it contains untrusted customer text, so after calling it "
                "you cannot stage changes or take any other action in this run."
            ),
            inputSchema=_WORKLIST_FILTER_SCHEMA,
        ),
        Tool(
            name="stage_change",
            description=(
                "Suggest a follow-up change for one worklist key. Posts it to "
                "Bil Weekend as a proposal, where an admin accepts or discards "
                "it in the AI Hub; nothing you suggest changes a record until "
                "they do. Queue rows are not accepted — read them, skip them. "
                "If Bil Weekend cannot be reached the suggestion is staged "
                "locally in Odysseus instead, and the reply says which happened."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Worklist key, source:id."},
                    "patch": {
                        "type": "object",
                        "properties": {
                            "status": {"type": "string", "enum": _STATUS_ENUM},
                            "operator": {"type": ["string", "null"]},
                            "next_action_date": {"type": ["string", "null"]},
                            "moderation": {
                                "type": ["string", "null"],
                                "enum": [*_MODERATION_ENUM, None],
                            },
                        },
                    },
                    "expected_updated_at": {
                        "type": ["string", "null"],
                        "description": "The row's updated_at as you read it, from worklist_structural.",
                    },
                    "author": {
                        "type": "string",
                        "description": "Which lane produced this, e.g. 'ambient-structural'.",
                    },
                    "rationale": {"type": "string", "description": "Why this change, citing what you read."},
                },
                "required": ["key", "patch", "author", "rationale"],
            },
        ),
        Tool(
            name="add_note",
            description=(
                "Leave a note against one worklist key — an observation that "
                "asks for nothing and changes nothing. Visible to the human "
                "operator in Odysseus's Operations panel and, when Bil Weekend "
                "is reachable, in its AI Hub. Use it for what you concluded "
                "about a request you decided to leave alone; that reasoning is "
                "otherwise lost when the run ends. Accepted on every source, "
                "queue rows included."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Worklist key, source:id."},
                    "author": {
                        "type": "string",
                        "description": "Which lane wrote this, e.g. 'ambient-structural'.",
                    },
                    "text": {"type": "string", "description": "The note's content."},
                },
                "required": ["key", "author", "text"],
            },
        ),
        Tool(
            name="itinerary_preview",
            description=(
                "Dry-run matching, day-code binding, and quote estimation for a worklist request "
                "without creating a Google Doc. Returns matched route, confidence, bound codes, "
                "gaps, and estimated pricing."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Worklist key, e.g. curated:uuid or queue:id."},
                },
                "required": ["key"],
            },
        ),
        Tool(
            name="itinerary_generate",
            description=(
                "Generates a live customized tour proposal Google Doc and calculates final quote pricing "
                "for a worklist request. Also drafts personalized email and WhatsApp customer replies."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Worklist key, e.g. curated:uuid or queue:id."},
                },
                "required": ["key"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Serve one tool call, and tell Bil Weekend it happened.

    The dispatch itself is _dispatch; this wrapper exists only to time it and
    mirror the outcome as an activity event. It is a wrapper rather than a line
    in each branch because the events that matter most are the ones a branch
    never reaches — a call that raised is exactly the call an admin is looking
    for when a run produced nothing.

    Inv: mirroring never changes what the tool returns. A failed mirror is
    logged into the void and the tool's own result stands; the alternative is a
    working suggestion lost because a telemetry POST timed out.
    """
    started = time.monotonic()
    try:
        payload = await _dispatch(name, arguments)
    except Exception as exc:
        await _mirror_activity(
            name, arguments, "error", started, error=str(exc)[:1000]
        )
        raise
    await _mirror_activity(name, arguments, "completed", started)
    return payload


async def _mirror_activity(
    name: str,
    arguments: dict,
    status: str,
    started: float,
    error: str | None = None,
) -> None:
    """Post one activity event. Swallows every failure — see call_tool."""
    try:
        # note_tool_call both updates the current run's tally and hands back the
        # run reference, so the event is attributed rather than orphaned.
        run_ref = ops_hub.note_tool_call(name)
        key = arguments.get("key") if isinstance(arguments, dict) else None
        target_source, target_id = (None, None)
        if isinstance(key, str) and ":" in key:
            target_source, target_id = key.split(":", 1)

        await ops_hub.post_activity([{
            "runRef": run_ref,
            "module": "ops",
            "action": name,
            "status": status,
            "durationMs": int((time.monotonic() - started) * 1000),
            "targetSource": target_source,
            "targetId": target_id,
            "error": error,
        }])
    except Exception:
        pass


async def _dispatch(name: str, arguments: dict) -> list[TextContent]:
    if name == "add_note":
        key = arguments.get("key", "")
        author = arguments.get("author", "") or "agent"
        text = arguments.get("text", "")
        if not key or not text:
            raise OpsApiError("add_note requires both 'key' and 'text'.")
        result = _write_note(key, author, text)
        # Written locally first, then copied. That order is what makes the note
        # survive an unreachable API: the store that must succeed is the one
        # this process owns.
        result.update(await _mirror_note(key, author, text))
        return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

    if name == "stage_change":
        key = arguments.get("key", "")
        patch = arguments.get("patch") or {}
        author = arguments.get("author", "") or "agent"
        rationale = arguments.get("rationale") or None
        expected_updated_at = arguments.get("expected_updated_at")
        if not key:
            raise OpsApiError("stage_change requires 'key'.")
        reason = _validate_patch(patch)
        if reason:
            raise OpsApiError(f"Invalid patch: {reason}")
        result = await _propose_or_stage(key, patch, expected_updated_at, author, rationale)
        return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

    if name == "itinerary_preview":
        key = arguments.get("key", "")
        if not key:
            raise OpsApiError("itinerary_preview requires 'key'.")
        if ":" not in key:
            raise OpsApiError("key must be in 'source:id' format.")
        source, source_id = key.split(":", 1)
        record = await _fetch_full_record(source, source_id)
        if not record:
            raise OpsApiError(f"No record found for key '{key}'.")
        from services.itinerary import normalize_from_dict, preview_itinerary, compose_email_reply, compose_whatsapp_reply
        norm_req = normalize_from_dict(key, record, source=source)
        preview = preview_itinerary(norm_req)
        email_draft = compose_email_reply(norm_req, preview, quote=preview.estimated_quote)
        whatsapp_draft = compose_whatsapp_reply(norm_req, preview, quote=preview.estimated_quote)
        out = {
            "preview": preview.to_dict(),
            "draft_email": email_draft,
            "draft_whatsapp": whatsapp_draft,
        }
        return [TextContent(type="text", text=json.dumps(out, indent=2, ensure_ascii=False))]

    if name == "itinerary_generate":
        key = arguments.get("key", "")
        if not key:
            raise OpsApiError("itinerary_generate requires 'key'.")
        if ":" not in key:
            raise OpsApiError("key must be in 'source:id' format.")
        source, source_id = key.split(":", 1)
        record = await _fetch_full_record(source, source_id)
        if not record:
            raise OpsApiError(f"No record found for key '{key}'.")
        from services.itinerary import normalize_from_dict, execute_generation, compose_email_reply, compose_whatsapp_reply
        norm_req = normalize_from_dict(key, record, source=source)
        gen_res = execute_generation(norm_req)
        if gen_res.status != "success":
            raise OpsApiError(f"Itinerary generation failed: {gen_res.error_message}")
        email_draft = compose_email_reply(norm_req, gen_res.preview, doc_url=gen_res.doc_url, quote=gen_res.quote)
        whatsapp_draft = compose_whatsapp_reply(norm_req, gen_res.preview, doc_url=gen_res.doc_url, quote=gen_res.quote)
        gen_res.draft_email = email_draft
        gen_res.draft_whatsapp = whatsapp_draft
        return [TextContent(type="text", text=json.dumps(gen_res.to_dict(), indent=2, ensure_ascii=False))]

    if _config() is None:
        raise OpsApiError(_CONFIG_ERROR)

    if name in ("worklist_structural", "worklist_full"):
        detail = "structural" if name == "worklist_structural" else "full"
        status, limit = _parse_worklist_args(arguments)
        rows = await _fetch_merged_worklist()
        result = {"items": _project(rows, detail, status, limit)}
    else:
        raise OpsApiError(f"Unknown tool: {name}")

    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())
