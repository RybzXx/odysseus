"""
ops_server.py

MCP server exposing the Bil Weekend operations worklist and the agent's
proposal channel.

Talks to Supabase directly (the actual data store — bookings, contacts,
curated_requests, queue_requests, operations_followup) rather than to a
Bil Weekend website API. That website API (/api/agent/ops/attention,
/api/agent/ops/proposals) was never built — no agent_proposals table exists
in Supabase either — so this reads the same tables Bil Weekend's own admin
panel reads, using the service-role key, and does the source-table +
operations_followup merge in Python instead of in Bil Weekend's backend.

Four tools. The split between the first two is a security boundary, not a
convenience:

  worklist_structural  the worklist with every customer-written field removed.
                       Classified SYSTEM in src/tool_capabilities.py, so reading
                       it leaves the run able to act.
  worklist_full        the same rows with names, emails, phones and summaries.
                       Classified EXTERNAL_UNTRUSTED, so reading it arms the
                       external-context gate and the run may only report
                       afterwards.
  propose_change       PAUSED. It targeted the never-built proposals endpoint;
                       see the error it raises for why, and what has to be
                       decided before it does anything again.
  add_note             leaves a note against one worklist key, visible to the
                       human operator in Odysseus's Operations panel. Written
                       to Odysseus's own store, not Supabase's — works even
                       without SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY set.

The classification is per tool rather than per response because
McpManager._do_call builds the result dict and marks untrusted_content only on
isError — a server cannot mark a successful response untrusted. Two tools with
two static classifications say the same thing without lying about success.

Environment:
  SUPABASE_URL                e.g. https://hjjkmknqunwlhrfulrdl.supabase.co
  SUPABASE_SERVICE_ROLE_KEY   full read/write access — same names Bil
                               Weekend's own web app uses, so its .env can be
                               copied directly rather than inventing a
                               separate credential.

Neither is ever accepted as a tool argument: the model asks for an action, it
does not supply the authority for it.
"""

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

import httpx

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.database import SessionLocal, OperationsNote

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
    """A failed call to Supabase, or a deliberately paused write path.

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


# source label -> (table, data.name key, data.email key, data.phone key, data.summary key)
# Confirmed against the live schema (2026-08-31): bookings/contacts/
# curated_requests store the submitted form as a jsonb `data` blob; only
# queue_requests is flat (handled separately below). `phone`/`summary` are
# None where that source has no such field.
_JSONB_SOURCES = {
    "booking": ("bookings", "name", "email", "phone", None),
    "contact": ("contacts", "name", "email", None, "message"),
    "curated": ("curated_requests", "name", "email", "phone", None),
}

_STRUCTURAL_FIELDS = (
    "key", "source", "source_id", "status", "operator", "next_action_date",
    "moderation", "updated_at", "created_at", "risk_score", "flagged",
)


async def _fetch_merged_worklist() -> list[dict]:
    """The unified worklist: bookings + contacts + curated_requests (each a
    Supabase jsonb blob, keyed by id) left-joined against operations_followup
    on (source, source_id) — the same key shape propose_change already used
    — plus queue_requests, which is flat and self-contained already.

    This merge used to be Bil Weekend's Next.js API's job. That API was
    never built, so it lives here now instead.

    Note: Bil Weekend's fourth source, "App Bookings", lives in a *separate*
    Supabase project per my work/OPERATIONSBilWeekend.md — out of reach of
    this service-role key, so it's absent from this worklist entirely.
    """
    followup_rows = await _sb_request("GET", "operations_followup", params={"select": "*"})
    followup_by_key = {(r["source"], r["source_id"]): r for r in followup_rows}

    rows: list[dict] = []

    for source, (table, name_f, email_f, phone_f, summary_f) in _JSONB_SOURCES.items():
        source_rows = await _sb_request("GET", table, params={"select": "id,data"})
        for r in source_rows:
            source_id = r["id"]
            data = r.get("data") or {}
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    data = {}
            followup = followup_by_key.get((source, source_id)) or {}
            rows.append({
                "key": f"{source}:{source_id}",
                "source": source,
                "source_id": source_id,
                "status": followup.get("status") or "New",
                "operator": followup.get("operator"),
                "next_action_date": followup.get("next_action_date"),
                "moderation": followup.get("moderation"),
                "updated_at": followup.get("updated_at") or data.get("submittedAt"),
                "created_at": data.get("submittedAt"),
                "risk_score": data.get("riskScore"),
                "flagged": data.get("flagged"),
                "name": data.get(name_f),
                "email": data.get(email_f) if email_f else None,
                "phone": data.get(phone_f) if phone_f else None,
                "summary": data.get(summary_f) if summary_f else None,
            })

    queue_rows = await _sb_request("GET", "queue_requests", params={"select": "*"})
    for r in queue_rows:
        rows.append({
            "key": f"queue:{r.get('row_id')}",
            "source": "queue",
            "source_id": r.get("row_id"),
            "status": r.get("status") or "New",
            "operator": r.get("operator"),
            "next_action_date": r.get("next_action_date"),
            "moderation": r.get("moderation"),
            "updated_at": r.get("updated_at"),
            "created_at": r.get("created_at") or r.get("submitted_at"),
            "risk_score": None,
            "flagged": None,
            "name": r.get("full_name"),
            "email": r.get("customer_email") or r.get("respondent_email"),
            "phone": r.get("phone"),
            "summary": r.get("entry_notes") or r.get("trip_focus"),
        })

    return rows


def _project(rows: list[dict], detail: str, status: str | None, limit: int | None) -> list[dict]:
    """Filter/sort/trim, then strip customer-written fields for 'structural'."""
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted(rows, key=lambda r: r.get("updated_at") or "", reverse=True)
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
    SUPABASE_SERVICE_ROLE_KEY are unset, unlike the other three tools.
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


_STATUS_ENUM = ["New", "In Progress", "Replied", "On Hold", "Confirmed", "Rejected"]

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

_PROPOSE_CHANGE_PAUSED = (
    "propose_change is paused. It targeted Bil Weekend's "
    "/api/agent/ops/proposals endpoint, which was never built — no "
    "agent_proposals table exists in Supabase. Now that reads go straight "
    "to Supabase, a write path needs a decision first: direct writes to "
    "operations_followup/queue_requests (immediate, no review step), or a "
    "real proposals table so a human still approves each change. Ask the "
    "person running Odysseus before this tool does anything."
)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="worklist_structural",
            description=(
                "The operations worklist without any customer-written text: status, "
                "operator, dates, the intake scorer's verdict (risk score / flagged). "
                "Use this when you intend to propose changes — it is the only "
                "worklist read that leaves you able to call propose_change afterwards."
            ),
            inputSchema=_WORKLIST_FILTER_SCHEMA,
        ),
        Tool(
            name="worklist_full",
            description=(
                "The operations worklist as the admin sees it, including names, "
                "emails, phones and request summaries. Use this only to read and "
                "report — it contains untrusted customer text, so after calling it "
                "you cannot propose changes or take any other action in this run."
            ),
            inputSchema=_WORKLIST_FILTER_SCHEMA,
        ),
        Tool(
            name="propose_change",
            description="PAUSED — calling this raises an error explaining why. See tool docs.",
            inputSchema={
                "type": "object",
                "properties": {
                    "author": {
                        "type": "string",
                        "description": "Which lane produced these, e.g. 'ambient-structural'.",
                    },
                    "proposals": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
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
                                            "enum": ["flagged", "spam", None],
                                        },
                                    },
                                },
                                "expectedUpdatedAt": {
                                    "type": ["string", "null"],
                                    "description": "The row's updatedAt as you read it.",
                                },
                                "rationale": {"type": "string"},
                            },
                            "required": ["key", "patch", "rationale"],
                        },
                    },
                },
                "required": ["author", "proposals"],
            },
        ),
        Tool(
            name="add_note",
            description=(
                "Leave a note against one worklist key, visible to the human "
                "operator in Odysseus's Operations panel. Does not change the "
                "worklist itself. Works even without SUPABASE_URL/"
                "SUPABASE_SERVICE_ROLE_KEY configured."
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
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "add_note":
        key = arguments.get("key", "")
        author = arguments.get("author", "") or "agent"
        text = arguments.get("text", "")
        if not key or not text:
            raise OpsApiError("add_note requires both 'key' and 'text'.")
        result = _write_note(key, author, text)
        return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

    if name == "propose_change":
        raise OpsApiError(_PROPOSE_CHANGE_PAUSED)

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
