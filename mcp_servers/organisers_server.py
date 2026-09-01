"""mcp_servers/organisers_server.py

MCP Server exposing AI Work Organisers taxonomy, rules, linked tasks, and directives.
Enables AI agents to query active workstream contexts and record category insights.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.database import SessionLocal, WorkOrganiser, ProjectTask, Memory
from routes.organisers.organisers_routes import _get_recent_emails, _matches_rule

server = Server("organisers")

_OWNER_ENV_KEYS = ("ODYSSEUS_MCP_MEMORY_OWNER", "ODYSSEUS_MEMORY_OWNER", "CURRENT_USER")


def _configured_owner() -> str | None:
    for key in _OWNER_ENV_KEYS:
        owner = os.environ.get(key, "").strip()
        if owner:
            return owner
    return None


def _text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="list_work_organisers",
            description="List all active high-level AI Work Organisers (workstream categories) with their AI missions, priority, and rules.",
            inputSchema={
                "type": "object",
                "properties": {
                    "group": {
                        "type": "string",
                        "description": "Optional category group filter: operations, strategy, partnerships, finance, tech, personal",
                    },
                },
            },
        ),
        Tool(
            name="get_work_organiser_detail",
            description="Retrieve detailed context for a specific Work Organiser including its AI instructions, matching recent emails, linked tasks, and memory notes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "slug": {
                        "type": "string",
                        "description": "The unique slug or identifier of the work organiser (e.g. 'bilweekend-tour-ops')",
                    },
                },
                "required": ["slug"],
            },
        ),
        Tool(
            name="record_work_insight",
            description="Record a new insight, status update, or learned fact under a work organiser's dedicated memory lane.",
            inputSchema={
                "type": "object",
                "properties": {
                    "slug": {
                        "type": "string",
                        "description": "The organiser slug to associate this memory note with.",
                    },
                    "note": {
                        "type": "string",
                        "description": "The detailed insight or context note to preserve.",
                    },
                    "tag": {
                        "type": "string",
                        "description": "Optional tag (e.g. 'client_preference', 'vendor_rate', 'action_item').",
                    },
                },
                "required": ["slug", "note"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    owner = _configured_owner()
    db = SessionLocal()
    try:
        if name == "list_work_organisers":
            group = arguments.get("group")
            query = db.query(WorkOrganiser).filter(WorkOrganiser.is_active == True)
            if owner:
                query = query.filter((WorkOrganiser.owner == owner) | (WorkOrganiser.owner == None))
            if group:
                query = query.filter(WorkOrganiser.category_group == group)
            organisers = query.order_by(WorkOrganiser.sort_order.asc()).all()

            if not organisers:
                return _text_result("No active work organisers found.")

            lines = ["# Active AI Work Organisers\n"]
            for o in organisers:
                lines.append(f"### {o.name} (`{o.slug}`)")
                lines.append(f"- **Group**: {o.category_group} | **Priority**: {o.priority}")
                if o.ai_instructions:
                    lines.append(f"- **AI Mission**: {o.ai_instructions}")
                lines.append("")
            return _text_result("\n".join(lines))

        elif name == "get_work_organiser_detail":
            slug = arguments.get("slug", "").strip()
            if not slug:
                return _text_result("Error: slug is required")

            query = db.query(WorkOrganiser).filter((WorkOrganiser.slug == slug) | (WorkOrganiser.id == slug))
            if owner:
                query = query.filter((WorkOrganiser.owner == owner) | (WorkOrganiser.owner == None))
            org = query.first()
            if not org:
                return _text_result(f"Error: Work organiser '{slug}' not found.")

            accounts = json.loads(org.target_accounts) if org.target_accounts else []
            rules = json.loads(org.rules_json) if org.rules_json else {}
            project_ids = json.loads(org.linked_project_ids) if org.linked_project_ids else []

            # Recent matching emails
            all_emails = _get_recent_emails(days=14)
            matched_emails = [e for e in all_emails if _matches_rule(e, accounts, rules)][:10]

            # Linked tasks
            tasks = []
            if project_ids:
                tasks = db.query(ProjectTask).filter(ProjectTask.project_id.in_(project_ids)).all()

            # Linked memories
            mems = []
            if org.memory_lane:
                mems = db.query(Memory).filter(Memory.lane == org.memory_lane).all()

            out = {
                "name": org.name,
                "slug": org.slug,
                "group": org.category_group,
                "priority": org.priority,
                "ai_instructions": org.ai_instructions,
                "matching_emails_14d_sample": [
                    {"from": e.get("from_name") or e.get("from_address"), "subject": e.get("subject"), "date": e.get("date_iso")}
                    for e in matched_emails
                ],
                "open_tasks": [
                    {"title": t.title, "completed": bool(t.completed), "due": t.due_date}
                    for t in tasks
                ],
                "memory_notes": [
                    {"content": m.content, "lane": m.lane}
                    for m in mems
                ],
            }
            return _text_result(json.dumps(out, indent=2))

        elif name == "record_work_insight":
            slug = arguments.get("slug", "").strip()
            note = arguments.get("note", "").strip()
            tag = arguments.get("tag", "general").strip()
            if not slug or not note:
                return _text_result("Error: slug and note are required")

            query = db.query(WorkOrganiser).filter((WorkOrganiser.slug == slug) | (WorkOrganiser.id == slug))
            if owner:
                query = query.filter((WorkOrganiser.owner == owner) | (WorkOrganiser.owner == None))
            org = query.first()
            if not org:
                return _text_result(f"Error: Work organiser '{slug}' not found.")

            lane = org.memory_lane or f"organisers:{org.slug}"
            new_mem = Memory(
                content=f"[{org.name}] {note}",
                lane=lane,
                tags=f"organiser,{org.slug},{tag}",
                owner=owner,
            )
            db.add(new_mem)
            db.commit()
            return _text_result(f"Recorded insight under '{org.name}' ({lane})")

        else:
            return _text_result(f"Error: Unknown tool '{name}'")
    finally:
        db.close()


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())
