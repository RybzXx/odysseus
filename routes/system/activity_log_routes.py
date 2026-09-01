"""routes/system/activity_log_routes.py

REST API Endpoints for System Activity & Non-Chat Query Audit Logging.
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request, HTTPException

from core import database as cdb
from src.auth_helpers import get_current_user
from src.system_logger import get_system_logs, get_system_log_stats, prune_system_logs

logger = logging.getLogger(__name__)


def setup_activity_log_routes() -> APIRouter:
    router = APIRouter(prefix="/api/system/activity-logs", tags=["system-activity-logs"])

    @router.get("")
    async def list_activity_logs(
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        module: Optional[str] = Query(default=None),
        status: Optional[str] = Query(default=None),
        query_type: Optional[str] = Query(default=None),
        search: Optional[str] = Query(default=None),
    ):
        """List and filter non-chat system query and activity logs."""
        user = get_current_user(request)
        owner = getattr(user, "username", None) if user else "default"
        return get_system_logs(
            limit=limit,
            offset=offset,
            module=module,
            status=status,
            query_type=query_type,
            search=search,
            owner=owner,
        )

    @router.get("/stats")
    async def activity_log_stats(request: Request):
        """Get real-time statistics for all system queries and module operations."""
        user = get_current_user(request)
        owner = getattr(user, "username", None) if user else "default"
        return get_system_log_stats(owner=owner)

    @router.delete("/clear")
    async def clear_activity_logs(
        request: Request,
        older_than_days: Optional[int] = Query(default=None, ge=1, le=365),
    ):
        """Prune or clear older system query logs."""
        user = get_current_user(request)
        deleted = prune_system_logs(older_than_days=older_than_days)
        return {"ok": True, "deleted_count": deleted}

    return router
