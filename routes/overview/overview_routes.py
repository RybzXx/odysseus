"""routes/overview/overview_routes.py

Executive Overview Hub aggregator endpoint.
Combines 7-day email digest with AI urgencies/summaries, active project tasks
with bidirectional disk-sync bindings, and operations inbound inquiries into a
high-density, unified morning briefing payload.

Utilizes multi-tier Stale-While-Revalidate (SWR) caching:
1. In-Memory fast cache (0ms)
2. SQLite `overview_cache` persistence (< 2ms cold load)
3. Background asynchronous revalidation when data exceeds 120s freshness TTL.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from core.database import (
    SessionLocal,
    get_db,
    Project,
    ProjectTask,
    EmailAccount,
    OverviewCache,
    utcnow_naive,
)
from src.auth_helpers import require_user
from src.constants import DATA_DIR
from mcp_servers.ops_server import _fetch_merged_worklist, _config as _ops_config

logger = logging.getLogger(__name__)

# In-memory fast cache: owner_key -> { "data": dict, "cached_at": datetime }
_OVERVIEW_MEMORY_CACHE: Dict[str, Dict[str, Any]] = {}
_REVALIDATING_OWNERS: Set[str] = set()
_CACHE_FRESHNESS_TTL_SECONDS = 120  # 2 minutes


def _owner_slug(owner: Optional[str]) -> str:
    """Normalize owner username to safe filename/cache slug."""
    raw = owner or "default"
    return "".join(c if (c.isalnum() or c in "-_.@") else "_" for c in raw)


def _get_owner_key(owner: Optional[str]) -> str:
    return owner if owner else "__global__"


def _is_owner_match(row_owner: Optional[str], owner: Optional[str]) -> bool:
    if owner is None:
        return True
    return row_owner is None or row_owner == owner


def _fetch_email_digest_data(db: Session, owner: Optional[str], days: int = 7) -> Dict[str, Any]:
    """Aggregate email stream, urgency states, and connected accounts scoped to the duration."""
    from src import constants as _constants
    import sqlite3 as _sql3

    # 1. Accounts list
    acc_q = db.query(EmailAccount).filter(EmailAccount.enabled == True)
    if owner:
        acc_q = acc_q.filter(or_(EmailAccount.owner == owner, EmailAccount.owner == None))
    accounts = acc_q.order_by(EmailAccount.is_default.desc(), EmailAccount.name.asc()).all()

    accounts_out = [
        {
            "id": a.id,
            "name": a.name or a.from_address or a.imap_user or "Account",
            "email": a.from_address or a.imap_user or "",
            "is_default": bool(a.is_default),
        }
        for a in accounts
    ]

    now_utc = datetime.now(timezone.utc)
    cutoff_epoch = now_utc.timestamp() - (days * 86400)
    raw_emails: List[Dict[str, Any]] = []
    seen_ids = set()

    # 2. Read AI summaries and urgency alerts from SQLite
    ai_summaries: Dict[str, str] = {}
    urgency_scores: Dict[str, tuple[float, str]] = {}

    try:
        import core.database as _cdb
        from sqlalchemy import text as _text
        with _cdb.engine.connect() as conn:
            # Fetch summaries
            sum_rows = conn.execute(
                _text("SELECT message_id, summary FROM email_summaries WHERE summary IS NOT NULL")
            ).fetchall()
            for mid, summ in sum_rows:
                if mid and summ:
                    ai_summaries[str(mid).strip()] = str(summ).strip()

            # Fetch urgency alerts
            alert_rows = conn.execute(
                _text("""
                    SELECT message_id, urgency_score, reason 
                    FROM email_urgency_alerts 
                    WHERE (owner = :owner OR owner IS NULL OR owner = '')
                """),
                {"owner": owner or ""}
            ).fetchall()
            for mid, score, reason in alert_rows:
                if mid:
                    urgency_scores[str(mid).strip()] = (float(score or 0), str(reason or ""))
    except Exception as e:
        logger.debug("Database email alerts query deferred: %s", e)

    # 3. Read indexed emails from scheduled_tasks.db email_message_index
    sched_db_file = Path(_constants.DATA_DIR) / "scheduled_tasks.db"
    if sched_db_file.exists():
        try:
            s_conn = _sql3.connect(str(sched_db_file), timeout=2.0)
            try:
                cur = s_conn.cursor()
                rows = cur.execute(
                    """
                    SELECT uid, account_key, message_id, subject, from_name, from_address,
                           date_iso, date_epoch, flags
                    FROM email_message_index
                    WHERE (owner = ? OR owner IS NULL OR owner = '')
                      AND date_epoch >= ?
                    ORDER BY date_epoch DESC
                    LIMIT 80
                    """,
                    (owner or "", cutoff_epoch),
                ).fetchall()

                for r in rows:
                    uid, acc_key, mid, subj, from_n, from_a, d_iso, d_epoch, flags = r
                    msg_uid = str(uid)
                    item_id = f"{acc_key or 'default'}:{msg_uid}"
                    if item_id in seen_ids:
                        continue
                    seen_ids.add(item_id)

                    flags_str = str(flags or "")
                    is_read = "\\Seen" in flags_str

                    mid_clean = str(mid or "").strip()
                    score_info = urgency_scores.get(mid_clean) or (0.0, "")
                    score_val = score_info[0]
                    urgency_lvl = "critical" if score_val >= 80 else ("urgent" if score_val >= 50 else "normal")
                    ai_comm = ai_summaries.get(mid_clean) or score_info[1] or None

                    matched_acc = next((a for a in accounts_out if a["id"] == acc_key), None)
                    acc_display = matched_acc["name"] if matched_acc else (acc_key or "Primary Account")

                    raw_emails.append({
                        "id": item_id,
                        "uid": msg_uid,
                        "account_id": acc_key or "default",
                        "account_name": acc_display,
                        "sender_name": from_n or from_a or "Unknown",
                        "sender_email": from_a or "",
                        "subject": subj or "(No Subject)",
                        "snippet": ai_comm or "",
                        "timestamp": d_iso or now_utc.isoformat(),
                        "date_epoch": float(d_epoch or 0),
                        "read": is_read,
                        "urgency": urgency_lvl,
                        "ai_comment": ai_comm,
                        "folder": "INBOX",
                    })
            finally:
                s_conn.close()
        except Exception as e:
            logger.debug("Scheduled email index query deferred: %s", e)

    # 4. Check urgency state snapshot file
    slug = _owner_slug(owner)
    urgency_file = Path(_constants.DATA_DIR) / f"email_urgency_state_{slug}.json"
    if urgency_file.exists():
        try:
            urgency_data = json.loads(urgency_file.read_text(encoding="utf-8"))
            per_account = urgency_data.get("accounts") or {}
            for acc_id, acc_info in per_account.items():
                matched_acc = next((a for a in accounts_out if a["id"] == acc_id), None)
                acc_name = matched_acc["name"] if matched_acc else acc_id

                for msg in acc_info.get("messages") or []:
                    msg_uid = str(msg.get("uid") or msg.get("id") or "")
                    msg_id = msg.get("id") or f"{acc_id}:{msg_uid}"
                    if msg_id in seen_ids:
                        continue

                    msg_ts_str = msg.get("date") or msg.get("timestamp") or now_utc.isoformat()
                    try:
                        msg_dt = datetime.fromisoformat(msg_ts_str.replace("Z", "+00:00"))
                        msg_epoch = msg_dt.timestamp()
                    except Exception:
                        msg_epoch = now_utc.timestamp()

                    if msg_epoch < cutoff_epoch:
                        continue

                    seen_ids.add(msg_id)
                    urgency_lvl = msg.get("urgency") or ("critical" if msg.get("is_urgent") else "normal")

                    raw_emails.append({
                        "id": msg_id,
                        "uid": msg_uid,
                        "account_id": acc_id,
                        "account_name": acc_name,
                        "sender_name": msg.get("sender_name") or msg.get("from_name") or msg.get("sender") or "Unknown",
                        "sender_email": msg.get("sender_email") or msg.get("from_email") or "",
                        "subject": msg.get("subject") or "(No Subject)",
                        "snippet": msg.get("snippet") or msg.get("preview") or "",
                        "timestamp": msg_ts_str,
                        "date_epoch": msg_epoch,
                        "read": bool(msg.get("read", False)),
                        "urgency": urgency_lvl,
                        "ai_comment": msg.get("ai_comment") or msg.get("summary") or None,
                        "folder": "INBOX",
                    })
        except (ValueError, OSError):
            pass

    # 5. Direct SQLite fallback if index and state file are empty
    if not raw_emails:
        try:
            import core.database as _cdb
            from sqlalchemy import text as _text
            with _cdb.engine.connect() as conn:
                rows = conn.execute(
                    _text("""
                        SELECT a.account_key, a.message_id, a.sender, a.subject, a.urgency_score,
                               a.reason, a.created_at, s.summary, p.preview_text
                        FROM email_urgency_alerts a
                        LEFT JOIN email_summaries s ON s.message_id = a.message_id
                        LEFT JOIN email_body_preview_cache p ON p.message_id = a.message_id
                        WHERE (a.owner = :owner OR a.owner IS NULL OR a.owner = '')
                        ORDER BY a.created_at DESC
                        LIMIT 30
                    """),
                    {"owner": owner or ""}
                ).fetchall()

                for r in rows:
                    acc_key, mid, sender, subj, score, reason, created_at, summary, preview = r
                    acc_name = "Primary Account"
                    score_val = float(score or 0)
                    urgency_lvl = "critical" if score_val >= 80 else ("urgent" if score_val >= 50 else "normal")
                    raw_emails.append({
                        "id": mid or f"{acc_key}:alert",
                        "uid": str(mid or ""),
                        "account_id": acc_key or "default",
                        "account_name": acc_name,
                        "sender_name": sender or "Unknown",
                        "sender_email": sender or "",
                        "subject": subj or "(No Subject)",
                        "snippet": preview or reason or "",
                        "timestamp": created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at or ""),
                        "date_epoch": created_at.timestamp() if hasattr(created_at, "timestamp") else now_utc.timestamp(),
                        "read": False,
                        "urgency": urgency_lvl,
                        "ai_comment": summary or reason or None,
                        "folder": "INBOX",
                    })
        except Exception as e:
            logger.debug("Direct SQLite email urgency query deferred: %s", e)

    # Sort emails by date_epoch descending
    raw_emails.sort(key=lambda m: m.get("date_epoch") or 0.0, reverse=True)

    # Dynamically compute unread and urgent counts for the active duration
    total_unread = sum(1 for e in raw_emails if not e.get("read"))
    total_urgent = sum(1 for e in raw_emails if e.get("urgency") in ("critical", "urgent"))

    return {
        "accounts": accounts_out,
        "total_unread": total_unread,
        "total_urgent": total_urgent,
        "days": days,
        "emails": raw_emails[:50],
    }


def _fetch_projects_matrix_data(db: Session, owner: Optional[str]) -> List[Dict[str, Any]]:
    """Query active projects with tasks, completion stats, and agent summaries."""
    proj_q = db.query(Project).filter(Project.status == "active")
    if owner is not None:
        proj_q = proj_q.filter(or_(Project.owner == owner, Project.owner == None))
    projects = proj_q.order_by(Project.priority.desc(), Project.updated_at.desc()).all()

    matrix: List[Dict[str, Any]] = []
    for p in projects:
        if not _is_owner_match(p.owner, owner):
            continue

        tasks_list = [
            {
                "id": t.id,
                "title": t.title,
                "completed": bool(t.completed),
                "sort_order": t.sort_order or 0,
                "due_date": t.due_date,
            }
            for t in p.tasks
        ]
        tasks_list.sort(key=lambda x: (x["completed"], x["sort_order"]))

        matrix.append({
            "id": p.id,
            "slug": p.slug or "",
            "name": p.name or "Untitled Project",
            "priority": p.priority or "normal",
            "agent_summary": p.agent_summary,
            "task_total": p.task_total or len(tasks_list),
            "task_completed": p.task_completed or sum(1 for t in tasks_list if t["completed"]),
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
            "tasks": tasks_list,
        })
    return matrix


async def _fetch_operations_radar_data() -> Dict[str, Any]:
    """Fetch and organize recent inbound requests across all 5 operational pipelines."""
    if _ops_config() is None:
        return {"configured": False, "inquiries": [], "total_open": 0, "total_overdue": 0}

    try:
        worklist = await _fetch_merged_worklist()
    except Exception as e:
        logger.warning("Operations worklist fetch failed for overview: %s", e)
        return {"configured": True, "inquiries": [], "total_open": 0, "total_overdue": 0, "error": str(e)}

    inquiries = []
    now_date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    total_open = 0
    total_overdue = 0

    for item in worklist:
        status = item.get("status") or "New"
        is_terminal = status in ("Confirmed", "Rejected")
        if not is_terminal:
            total_open += 1

        next_act = item.get("next_action_date")
        is_overdue = bool(next_act and next_act < now_date_str and not is_terminal)
        if is_overdue:
            total_overdue += 1

        data = item.get("data") or {}
        email = data.get("email") or item.get("email") or ""
        phone = item.get("phone") or data.get("phone") or ""
        name = item.get("name") or data.get("name") or "Inquiry"

        inquiries.append({
            "key": item.get("key"),
            "source": item.get("source"),
            "source_id": item.get("source_id"),
            "name": name,
            "email": email,
            "phone": phone,
            "summary": " • ".join(str(s) for s in item.get("summary", []) if s),
            "status": status,
            "operator": item.get("operator"),
            "next_action_date": next_act,
            "is_overdue": is_overdue,
            "risk_verdict": item.get("risk_verdict") or "not-scored",
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
        })

    def _inquiry_sort_key(x):
        created_val = x.get("created_at") or ""
        try:
            ts = datetime.fromisoformat(created_val.replace("Z", "+00:00")).timestamp()
        except Exception:
            ts = 0.0
        return (
            not x["is_overdue"],
            x["status"] in ("Confirmed", "Rejected"),
            -ts,
        )

    inquiries.sort(key=_inquiry_sort_key)

    return {
        "configured": True,
        "total_open": total_open,
        "total_overdue": total_overdue,
        "inquiries": inquiries[:25],
    }


async def _build_overview_payload(owner: Optional[str], email_days: int = 7, db: Optional[Session] = None) -> Dict[str, Any]:
    """Consolidate the complete Overview Hub payload across all domains."""
    close_db = False
    if db is None:
        import core.database as _cdb
        db = _cdb.SessionLocal()
        close_db = True

    try:
        # 1. Projects Matrix
        projects_matrix = _fetch_projects_matrix_data(db, owner)

        # 2. Email Digest
        email_digest = _fetch_email_digest_data(db, owner, days=email_days)

        # 3. Operations Radar
        ops_radar = await _fetch_operations_radar_data()

        # Compute KPIs
        open_tasks_count = sum(
            sum(1 for t in p["tasks"] if not t["completed"])
            for p in projects_matrix
        )

        kpis = {
            "urgent_emails": email_digest.get("total_urgent", 0),
            "unread_emails": email_digest.get("total_unread", 0),
            "active_projects": len(projects_matrix),
            "open_tasks": open_tasks_count,
            "pending_inquiries": ops_radar.get("total_open", 0),
            "overdue_inquiries": ops_radar.get("total_overdue", 0),
        }

        now_dt = utcnow_naive()
        return {
            "ok": True,
            "cached_at": now_dt.isoformat() + "Z",
            "kpis": kpis,
            "email_digest": email_digest,
            "projects_matrix": projects_matrix,
            "operations_radar": ops_radar,
        }
    finally:
        if close_db:
            db.close()


async def _revalidate_overview_bg(owner: Optional[str], email_days: int = 7) -> None:
    """Asynchronous background revalidation worker."""
    raw_owner_key = _get_owner_key(owner)
    owner_key = f"{raw_owner_key}:{email_days}"
    if owner_key in _REVALIDATING_OWNERS:
        return

    _REVALIDATING_OWNERS.add(owner_key)
    try:
        logger.debug("Background revalidating Overview cache for owner %s days=%s", raw_owner_key, email_days)
        fresh_payload = await _build_overview_payload(owner, email_days)

        # Update in-memory cache
        now_dt = utcnow_naive()
        _OVERVIEW_MEMORY_CACHE[owner_key] = {
            "data": fresh_payload,
            "cached_at": now_dt,
        }

        # Update SQLite persistence
        import core.database as _cdb
        db = _cdb.SessionLocal()
        try:
            cache_id = f"{raw_owner_key}:overview:{email_days}"
            cache_row = db.query(OverviewCache).filter(OverviewCache.id == cache_id).first()
            if not cache_row:
                cache_row = OverviewCache(
                    id=cache_id,
                    owner=owner,
                    payload_json=json.dumps(fresh_payload),
                    cached_at=now_dt,
                    expires_at=now_dt + timedelta(hours=24),
                )
                db.add(cache_row)
            else:
                cache_row.payload_json = json.dumps(fresh_payload)
                cache_row.cached_at = now_dt
                cache_row.expires_at = now_dt + timedelta(hours=24)
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning("Background Overview revalidation failed for %s: %s", owner_key, e)
    finally:
        _REVALIDATING_OWNERS.discard(owner_key)


def setup_overview_routes() -> APIRouter:
    """Register FastAPI route handlers for the Executive Overview Hub."""
    router = APIRouter(prefix="/api/overview", tags=["overview"])

    @router.get("")
    async def get_overview_briefing(
        request: Request,
        email_days: int = Query(7, ge=1, le=30),
        force_refresh: bool = Query(False),
        db: Session = Depends(get_db),
    ):
        """Retrieve aggregated morning briefing with SWR caching."""
        owner = None
        try:
            owner = require_user(request)
        except Exception:
            owner = None

        raw_owner_key = _get_owner_key(owner)
        owner_key = f"{raw_owner_key}:{email_days}"
        now_dt = utcnow_naive()
        cache_id = f"{raw_owner_key}:overview:{email_days}"

        # 1. Check in-memory fast cache first
        mem_entry = _OVERVIEW_MEMORY_CACHE.get(owner_key)
        if mem_entry and not force_refresh:
            age_sec = (now_dt - mem_entry["cached_at"]).total_seconds()
            if age_sec < _CACHE_FRESHNESS_TTL_SECONDS:
                return {**mem_entry["data"], "is_stale": False}
            else:
                asyncio.create_task(_revalidate_overview_bg(owner, email_days))
                return {**mem_entry["data"], "is_stale": True}

        # 2. Check SQLite persistent cache
        db_cache = db.query(OverviewCache).filter(OverviewCache.id == cache_id).first()
        if db_cache and not force_refresh:
            try:
                cached_data = json.loads(db_cache.payload_json)
                age_sec = (now_dt - db_cache.cached_at).total_seconds()
                _OVERVIEW_MEMORY_CACHE[owner_key] = {
                    "data": cached_data,
                    "cached_at": db_cache.cached_at,
                }

                if age_sec < _CACHE_FRESHNESS_TTL_SECONDS:
                    return {**cached_data, "is_stale": False}
                else:
                    asyncio.create_task(_revalidate_overview_bg(owner, email_days))
                    return {**cached_data, "is_stale": True}
            except (ValueError, TypeError):
                pass

        # 3. Synchronous fetch on cold start or explicit force refresh
        payload = await _build_overview_payload(owner, email_days, db=db)
        _OVERVIEW_MEMORY_CACHE[owner_key] = {
            "data": payload,
            "cached_at": now_dt,
        }

        try:
            if not db_cache:
                db_cache = OverviewCache(
                    id=cache_id,
                    owner=owner,
                    payload_json=json.dumps(payload),
                    cached_at=now_dt,
                    expires_at=now_dt + timedelta(hours=24),
                )
                db.add(db_cache)
            else:
                db_cache.payload_json = json.dumps(payload)
                db_cache.cached_at = now_dt
                db_cache.expires_at = now_dt + timedelta(hours=24)
            db.commit()
        except Exception as e:
            logger.warning("Failed saving overview cache to database: %s", e)
            db.rollback()

        return {**payload, "is_stale": False}

    return router
