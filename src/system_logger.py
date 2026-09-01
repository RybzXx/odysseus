"""src/system_logger.py

Unified Non-Chat System Query & Activity Logging Subsystem for Odysseus.
Captures, indexes, and serves all background, scheduled, and module-driven AI/system operations.
Explicitly isolates and excludes interactive user chat messages.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import or_, desc, func
from core import database as cdb
from core.database import SystemQueryLog

logger = logging.getLogger(__name__)

# Max retention bounds
MAX_RECORDS = 10000
DEFAULT_RETENTION_DAYS = 30


def utcnow_naive() -> datetime:
    """Return naive UTC for database DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def log_system_query(
    module: str,
    action: str,
    target_id: Optional[str] = None,
    target_name: Optional[str] = None,
    query_type: str = "llm",
    model: Optional[str] = None,
    endpoint_url: Optional[str] = None,
    prompt_preview: Optional[str] = None,
    result_preview: Optional[str] = None,
    status: str = "completed",
    duration_ms: Optional[int] = None,
    tokens_used: Optional[int] = None,
    error: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    owner: Optional[str] = "default",
    db_session=None,
) -> Optional[str]:
    """Record a non-chat query or background operation into the central system log.
    
    Safe and non-blocking: never raises exceptions to the caller.
    """
    try:
        log_id = f"sqlog_{uuid.uuid4().hex[:8]}"
        now = utcnow_naive()

        # Sanitize and truncate previews
        clean_prompt = None
        if prompt_preview:
            clean_prompt = str(prompt_preview).strip()
            if len(clean_prompt) > 2000:
                clean_prompt = clean_prompt[:1997] + "..."

        clean_result = None
        if result_preview:
            clean_result = str(result_preview).strip()
            if len(clean_result) > 4000:
                clean_result = clean_result[:3997] + "..."

        clean_error = None
        if error:
            clean_error = str(error).strip()
            if len(clean_error) > 2000:
                clean_error = clean_error[:1997] + "..."

        close_db = False
        db = db_session
        if db is None:
            db = cdb.SessionLocal()
            close_db = True

        try:
            # Check for stacking de-duplication on repetitive background checks (within 10 minutes)
            ten_mins_ago = now - timedelta(minutes=10)
            existing = (
                db.query(SystemQueryLog)
                .filter(
                    SystemQueryLog.module == module.lower(),
                    SystemQueryLog.action == action,
                    SystemQueryLog.target_name == target_name,
                    SystemQueryLog.status == status,
                    SystemQueryLog.timestamp >= ten_mins_ago,
                )
                .order_by(SystemQueryLog.timestamp.desc())
                .first()
            )

            # If result preview matches and this is a recurring check, stack it
            if existing and existing.result_preview == clean_result and status != "running":
                existing.repeat_count = (existing.repeat_count or 1) + 1
                existing.timestamp = now
                existing.duration_ms = duration_ms or existing.duration_ms
                db.commit()
                return existing.id

            entry = SystemQueryLog(
                id=log_id,
                timestamp=now,
                module=module.lower(),
                action=action,
                target_id=str(target_id) if target_id else None,
                target_name=target_name,
                query_type=query_type,
                model=model,
                endpoint_url=endpoint_url,
                prompt_preview=clean_prompt,
                result_preview=clean_result,
                status=status,
                duration_ms=duration_ms,
                tokens_used=tokens_used,
                error=clean_error,
                repeat_count=1,
                metadata_json=metadata or {},
                owner=owner or "default",
            )
            db.add(entry)
            db.commit()
            return log_id
        finally:
            if close_db:
                db.close()
    except Exception as ex:
        logger.debug(f"Failed to log system query: {ex}")
        return None


def get_system_logs(
    limit: int = 50,
    offset: int = 0,
    module: Optional[str] = None,
    status: Optional[str] = None,
    query_type: Optional[str] = None,
    search: Optional[str] = None,
    owner: Optional[str] = None,
    db=None,
) -> Dict[str, Any]:
    """Retrieve filtered, paginated system query logs."""
    close_db = False
    if db is None:
        db = cdb.SessionLocal()
        close_db = True
    try:
        q = db.query(SystemQueryLog)

        if owner:
            q = q.filter(or_(SystemQueryLog.owner == owner, SystemQueryLog.owner == "default", SystemQueryLog.owner == None))

        if module and module.lower() != "all":
            q = q.filter(SystemQueryLog.module == module.lower())

        if status and status.lower() != "all":
            q = q.filter(SystemQueryLog.status == status.lower())

        if query_type and query_type.lower() != "all":
            q = q.filter(SystemQueryLog.query_type == query_type.lower())

        if search and search.strip():
            term = f"%{search.strip()}%"
            q = q.filter(
                or_(
                    SystemQueryLog.action.ilike(term),
                    SystemQueryLog.target_name.ilike(term),
                    SystemQueryLog.target_id.ilike(term),
                    SystemQueryLog.model.ilike(term),
                    SystemQueryLog.prompt_preview.ilike(term),
                    SystemQueryLog.result_preview.ilike(term),
                    SystemQueryLog.error.ilike(term),
                )
            )

        total = q.count()
        rows = q.order_by(SystemQueryLog.timestamp.desc()).offset(offset).limit(limit).all()

        logs = []
        for r in rows:
            logs.append({
                "id": r.id,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "module": r.module,
                "action": r.action,
                "target_id": r.target_id,
                "target_name": r.target_name or (r.target_id or "System Operation"),
                "query_type": r.query_type or "llm",
                "model": r.model,
                "endpoint_url": r.endpoint_url,
                "prompt_preview": r.prompt_preview,
                "result_preview": r.result_preview,
                "status": r.status or "completed",
                "duration_ms": r.duration_ms,
                "tokens_used": r.tokens_used,
                "error": r.error,
                "repeat_count": r.repeat_count or 1,
                "metadata": r.metadata_json or {},
                "owner": r.owner,
            })

        return {
            "ok": True,
            "total": total,
            "has_more": (offset + len(logs)) < total,
            "logs": logs,
        }
    finally:
        if close_db:
            db.close()


def get_system_log_stats(owner: Optional[str] = None, db=None) -> Dict[str, Any]:
    """Aggregate real-time statistics across all system query logs."""
    close_db = False
    if db is None:
        db = cdb.SessionLocal()
        close_db = True
    try:
        q = db.query(SystemQueryLog)
        if owner:
            q = q.filter(or_(SystemQueryLog.owner == owner, SystemQueryLog.owner == "default", SystemQueryLog.owner == None))

        total_queries = q.count()
        running_count = q.filter(SystemQueryLog.status == "running").count()
        error_count = q.filter(SystemQueryLog.status == "error").count()

        # Count by module
        module_counts = {}
        grouped = (
            db.query(SystemQueryLog.module, func.count(SystemQueryLog.id))
            .group_by(SystemQueryLog.module)
            .all()
        )
        for mod, cnt in grouped:
            if mod:
                module_counts[mod] = cnt

        return {
            "ok": True,
            "total_queries": total_queries,
            "running_count": running_count,
            "error_count": error_count,
            "counts_by_module": module_counts,
        }
    finally:
        if close_db:
            db.close()


def prune_system_logs(older_than_days: Optional[int] = None, db=None) -> int:
    """Prune expired system logs to maintain storage boundaries."""
    close_db = False
    if db is None:
        db = cdb.SessionLocal()
        close_db = True
    try:
        days = older_than_days or DEFAULT_RETENTION_DAYS
        cutoff = utcnow_naive() - timedelta(days=days)
        deleted = db.query(SystemQueryLog).filter(SystemQueryLog.timestamp < cutoff).delete()

        # If count exceeds MAX_RECORDS, trim oldest
        total = db.query(SystemQueryLog).count()
        if total > MAX_RECORDS:
            excess = total - MAX_RECORDS
            oldest_ids = [
                row[0]
                for row in db.query(SystemQueryLog.id)
                .order_by(SystemQueryLog.timestamp.asc())
                .limit(excess)
                .all()
            ]
            if oldest_ids:
                deleted += db.query(SystemQueryLog).filter(SystemQueryLog.id.in_(oldest_ids)).delete(synchronize_session=False)

        db.commit()
        return deleted
    finally:
        if close_db:
            db.close()
