"""routes/operations/operations_routes.py

Human-viewable panel over the Bil Weekend operations worklist — the same
data mcp_servers/ops_server.py already exposes to agents. Reuses that
module's HTTP client (_call_ops_api/_config) so there is exactly one
implementation of the Bil Weekend API contract, read by both the agent MCP
tools and this human-facing panel.

Writes (status changes from a card drag) go through Bil Weekend's existing
propose_change endpoint — nothing here writes the worklist directly. A
human-originated proposal is tagged author="odysseus-ui:<username>" so it's
distinguishable from agent proposals in Bil Weekend's own records; the panel
is expected to show the change as pending until a later read confirms it,
since propose_change never applies anything by itself.

Full customer detail (name/email/phone/summary) is requested directly
(detail=full) rather than the structural-only view ops_server.py's agent
tools default to — the admin viewing this panel is the same person who can
already see that data in Bil Weekend's own admin panel.
"""

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.database import SessionLocal, OperationsNote
from core.middleware import require_admin
from src.auth_helpers import require_user
from mcp_servers.ops_server import _call_ops_api, _config, OpsApiError, _STATUS_ENUM

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
            503, "The operations API is not configured (OPS_API_BASE_URL / OPS_AGENT_TOKEN)."
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
        params: dict[str, str | int] = {"detail": "full"}
        if status:
            params["status"] = status
        if isinstance(limit, int) and limit > 0:
            params["limit"] = limit
        try:
            return await _call_ops_api("GET", "/api/agent/ops/attention", params=params)
        except OpsApiError as e:
            raise HTTPException(502, str(e))

    @router.post("/status")
    async def change_status(request: Request, body: StatusChange):
        require_admin(request)
        _require_ops_configured()
        if body.status not in _STATUS_ENUM:
            raise HTTPException(422, f"status must be one of {_STATUS_ENUM}")
        user = require_user(request) or "unknown"
        try:
            return await _call_ops_api(
                "POST",
                "/api/agent/ops/proposals",
                body={
                    "author": f"odysseus-ui:{user}",
                    "proposals": [
                        {
                            "key": body.key,
                            "patch": {"status": body.status},
                            "expectedUpdatedAt": body.expectedUpdatedAt,
                            "rationale": body.rationale
                            or "Status changed via Odysseus Operations board",
                        }
                    ],
                },
            )
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
