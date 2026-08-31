"""routes/operations/operations_routes.py

Human-viewable panel over the Bil Weekend operations worklist — the same
data mcp_servers/ops_server.py exposes to agents. Reuses that module's
Supabase client and bookings/contacts/curated_requests/queue_requests
merge (_fetch_merged_worklist/_project/_config) so there is exactly one
implementation of the worklist, read by both the agent MCP tools and this
human-facing panel.

Talks to Supabase directly (SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY), not to
a Bil Weekend website API — that API was never built. See ops_server.py's
module docstring for why.

Status-change writes are PAUSED: they targeted the same never-built
propose_change/proposals endpoint. POST /status returns 501 with an
explanation rather than doing an unreviewed direct write no one has signed
off on. Full customer detail (name/email/phone/summary) is requested
directly — the admin viewing this panel already sees that data in Bil
Weekend's own admin panel.
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
    _PROPOSE_CHANGE_PAUSED,
)

logger = logging.getLogger(__name__)


class StatusChange(BaseModel):
    key: str
    status: str
    expectedUpdatedAt: Optional[str] = None
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

    @router.post("/status")
    async def change_status(request: Request, body: StatusChange):
        require_admin(request)
        if body.status not in _STATUS_ENUM:
            raise HTTPException(422, f"status must be one of {_STATUS_ENUM}")
        # Paused, not a Supabase call — see _PROPOSE_CHANGE_PAUSED. Left as a
        # named 501 rather than silently writing operations_followup direct,
        # since nobody has decided yet whether these writes skip review.
        raise HTTPException(501, _PROPOSE_CHANGE_PAUSED)

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
