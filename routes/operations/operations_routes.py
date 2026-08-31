"""routes/operations/operations_routes.py

Human-viewable panel over the Bil Weekend operations worklist — the same
data mcp_servers/ops_server.py exposes to agents. Reuses that module's
Supabase client, merge, and staging logic so there is exactly one
implementation of the worklist and exactly one place writes get queued,
read by both the agent MCP tools and this human-facing panel.

Talks to Supabase directly (SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY), not to
a Bil Weekend website API — that API was never built. See ops_server.py's
module docstring for why.

Writes are staged locally, not applied immediately: a human or an agent
stages a patch (POST /stage), it's reviewable and discardable (GET/DELETE
/staged), and only a deliberate POST /push actually writes Supabase — in one
batch, with a per-item optimistic-concurrency check against each item's
expected_updated_at. Full customer detail (name/email/phone/summary) is
requested directly for the merged worklist — the admin viewing this panel
already sees that data in Bil Weekend's own admin panel.
"""

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.database import SessionLocal, OperationsNote
from core.middleware import require_admin
from src.auth_helpers import require_user
from mcp_servers.ops_server import (
    _fetch_merged_worklist,
    _project,
    _config,
    OpsApiError,
    _STATUS_ENUM,
    _MODERATION_ENUM,
    _stage_change,
    _list_staged,
    _discard_staged,
    _push_staged_changes,
)

logger = logging.getLogger(__name__)


class StagePatch(BaseModel):
    key: str
    status: Optional[str] = None
    operator: Optional[str] = None
    next_action_date: Optional[str] = None
    moderation: Optional[str] = None
    expected_updated_at: Optional[str] = None
    rationale: Optional[str] = None


class NoteCreate(BaseModel):
    key: str
    text: str


def _note_to_dict(note: OperationsNote) -> dict:
    return {
        "id": note.id,
        "key": note.key,
        "author": note.author,
        "source": note.source,
        "text": note.text,
        "created_at": note.created_at.isoformat() if note.created_at else None,
    }


def _require_ops_configured() -> None:
    if _config() is None:
        raise HTTPException(
            503, "Supabase is not configured (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY)."
        )


def setup_operations_routes() -> APIRouter:
    router = APIRouter(prefix="/api/operations")

    @router.get("")
    async def list_worklist(
        request: Request,
        status: Optional[str] = None,
        limit: Optional[int] = None,
    ):
        require_admin(request)
        _require_ops_configured()
        try:
            rows = await _fetch_merged_worklist()
        except OpsApiError as e:
            raise HTTPException(502, str(e))
        return {"items": _project(rows, "full", status, limit)}

    @router.post("/stage")
    def stage_change(request: Request, body: StagePatch):
        require_admin(request)
        user = require_user(request) or "unknown"
        patch = {}
        if body.status is not None:
            if body.status not in _STATUS_ENUM:
                raise HTTPException(422, f"status must be one of {_STATUS_ENUM}")
            patch["status"] = body.status
        if body.operator is not None:
            patch["operator"] = body.operator or None
        if body.next_action_date is not None:
            patch["next_action_date"] = body.next_action_date or None
        if body.moderation is not None:
            if body.moderation not in (*_MODERATION_ENUM, ""):
                raise HTTPException(422, f"moderation must be one of {_MODERATION_ENUM} or empty")
            patch["moderation"] = body.moderation or None
        if not patch:
            raise HTTPException(422, "at least one of status/operator/next_action_date/moderation is required")

        try:
            return _stage_change(
                body.key, patch, body.expected_updated_at, f"user:{user}", body.rationale,
            )
        except OpsApiError as e:
            raise HTTPException(422, str(e))

    @router.get("/staged")
    def list_staged(request: Request):
        require_admin(request)
        return {"staged": _list_staged()}

    @router.delete("/staged/{staged_id}")
    def discard_staged(request: Request, staged_id: str):
        require_admin(request)
        if not _discard_staged(staged_id):
            raise HTTPException(404, "No staged change with that id.")
        return {"discarded": staged_id}

    @router.post("/push")
    async def push_staged(request: Request):
        require_admin(request)
        _require_ops_configured()
        try:
            return await _push_staged_changes()
        except OpsApiError as e:
            raise HTTPException(502, str(e))

    @router.get("/notes")
    def list_notes(request: Request, key: Optional[str] = None):
        require_admin(request)
        db = SessionLocal()
        try:
            q = db.query(OperationsNote)
            if key:
                q = q.filter(OperationsNote.key == key)
            notes = q.order_by(OperationsNote.created_at.desc()).all()
            return {"notes": [_note_to_dict(n) for n in notes]}
        finally:
            db.close()

    @router.post("/notes")
    def create_note(request: Request, body: NoteCreate):
        require_admin(request)
        user = require_user(request) or "unknown"
        db = SessionLocal()
        try:
            note = OperationsNote(
                id=str(uuid.uuid4()),
                key=body.key,
                owner=user,
                author=user,
                source="user",
                text=body.text,
            )
            db.add(note)
            db.commit()
            db.refresh(note)
            return _note_to_dict(note)
        finally:
            db.close()

    return router
