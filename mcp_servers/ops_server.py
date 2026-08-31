"""
ops_server.py

MCP server exposing the Bil Weekend operations worklist and the agent's
proposal channel.

Four tools. The split between the first two is a security boundary, not a
convenience:

  worklist_structural  the worklist with every customer-written field removed.
                       Classified SYSTEM in src/tool_capabilities.py, so reading
                       it leaves the run able to act.
  worklist_full        the same rows with names, emails, phones and summaries.
                       Classified EXTERNAL_UNTRUSTED, so reading it arms the
                       external-context gate and the run may only report
                       afterwards.
  propose_change       suggests a follow-up change. Classified as a write, so it
                       is refused after worklist_full and permitted after
                       worklist_structural.
  add_note             leaves a note against one worklist key, visible to the
                       human operator in Odysseus's Operations panel. Written
                       to Odysseus's own store, not Bil Weekend's — the
                       worklist has no notes field, so this never touches the
                       Bil Weekend API and needs no OPS_API_BASE_URL/
                       OPS_AGENT_TOKEN. Does not change the worklist itself.

The classification is per tool rather than per response because
McpManager._do_call builds the result dict and marks untrusted_content only on
isError — a server cannot mark a successful response untrusted. Two tools with
two static classifications say the same thing without lying about success.

A proposal changes nothing operational: it lands in agent_proposals as pending
and an admin applies or discards it in the worklist. That is what makes posting
one safe to do unattended.

Environment:
  OPS_API_BASE_URL   e.g. https://www.bilweekend.com
  OPS_AGENT_TOKEN    the bearer token the web app compares against

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
    "The operations API is not configured. Set OPS_API_BASE_URL and "
    "OPS_AGENT_TOKEN in the environment this server runs in."
)


def _config() -> tuple[str, str] | None:
    """Base URL and token, or None when either is missing."""
    base_url = os.environ.get("OPS_API_BASE_URL", "").strip().rstrip("/")
    token = os.environ.get("OPS_AGENT_TOKEN", "").strip()
    if not base_url or not token:
        return None
    return base_url, token


class OpsApiError(RuntimeError):
    """A failed call to the operations API.

    Raised rather than returned, and that is load-bearing. worklist_structural
    is classified SYSTEM, so its results do not arm the external-context gate;
    an error body is the remote side talking, not the web app's allowlist
    projection, and must not enter the run as trusted text. Raising makes the
    MCP framework return isError, which is what makes McpManager._do_call mark
    the result untrusted_content and arm the gate.
    """


async def _call_ops_api(
    method: str,
    path: str,
    params: dict | None = None,
    body: dict | None = None,
) -> dict:
    """One request to the operations API.

    Pre: the caller has checked _config(). Post: the decoded JSON body of a 200
    response. Raises OpsApiError on anything else.
    Inv: fails closed — a non-200, a transport failure and an unparseable body
    are all errors, never a partial view. A caller that treated a truncated
    worklist as complete would propose against rows it never saw.
    """
    base_url, token = _config()  # type: ignore[misc]
    url = f"{base_url}{path}"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.request(
                method, url, headers=headers, params=params, json=body
            )
    except Exception as exc:
        raise OpsApiError(f"Could not reach the operations API: {exc}") from exc

    if response.status_code != 200:
        raise OpsApiError(
            f"Operations API returned {response.status_code}: {response.text[:300]}"
        )

    try:
        return response.json()
    except ValueError as exc:
        raise OpsApiError("Operations API returned a body that is not JSON.") from exc


def _attention_params(detail: str, arguments: dict) -> dict:
    """The attention query as a parameter mapping, for httpx to encode.

    Pre: `arguments` is whatever the model sent — the MCP layer does not
    enforce inputSchema, so every field may be any type.
    Post: a mapping containing `detail`, plus `status` and `limit` only when the
    model supplied usable values.

    Handing httpx a mapping rather than a hand-built string is what makes this
    safe. The previous version spliced values in raw: an `&` in a status added a
    parameter, and a `#` started a fragment, silently dropping everything after
    it. httpx percent-encodes both.
    """
    params: dict[str, str | int] = {"detail": detail}

    status = arguments.get("status")
    if isinstance(status, str) and status.strip():
        params["status"] = status.strip()

    limit = arguments.get("limit")
    # bool is a subclass of int in Python, so `isinstance(True, int)` passes and
    # httpx renders True as "true" — which the web app rejects, arming the gate
    # and ending a run that had done nothing wrong.
    if type(limit) is int and limit > 0:
        params["limit"] = limit

    return params


def _write_note(key: str, author: str, text: str) -> dict:
    """Persist a note in Odysseus's own store.

    Local, not a Bil Weekend API call — runs even when OPS_API_BASE_URL/
    OPS_AGENT_TOKEN are unset, unlike the other three tools.
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


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="worklist_structural",
            description=(
                "The operations worklist without any customer-written text: status, "
                "operator, dates, age, overdue flag and the intake scorer's verdict. "
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
            description=(
                "Suggest follow-up changes for an admin to accept or discard. "
                "Nothing changes until an admin accepts. Each proposal names a "
                "worklist key, a patch over status / operator / next_action_date / "
                "moderation, the row's updatedAt as you saw it, and a rationale. "
                "A moderation proposal must cite the intake scorer (risk, riskScore "
                "or flagReasons); queue rows do not accept proposals."
            ),
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
                "worklist itself — use propose_change for that. Works even "
                "without OPS_API_BASE_URL/OPS_AGENT_TOKEN configured."
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

    if _config() is None:
        raise OpsApiError(_CONFIG_ERROR)

    if name in ("worklist_structural", "worklist_full"):
        detail = "structural" if name == "worklist_structural" else "full"
        result = await _call_ops_api(
            "GET",
            "/api/agent/ops/attention",
            params=_attention_params(detail, arguments),
        )
    elif name == "propose_change":
        result = await _call_ops_api(
            "POST",
            "/api/agent/ops/proposals",
            body={
                "author": arguments.get("author", ""),
                "proposals": arguments.get("proposals", []),
            },
        )
    else:
        raise OpsApiError(f"Unknown tool: {name}")

    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())
