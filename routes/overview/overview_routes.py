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

# The single window the briefing is built and cached at. The email panel's
# duration buttons narrow the rows client-side rather than asking for a
# different window, so one bucket per owner is all that is ever needed.
# Mirrored by FETCH_WINDOW_DAYS in static/js/overview.js.
_BRIEFING_WINDOW_DAYS = 30


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


_ACTION_LINE_PREFIXES = ("action items:", "action item:", "action:", "actions:")


def _split_summary_and_action(summary: Optional[str]) -> tuple[str, Optional[str]]:
    """Separate a stored AI summary into its narrative and its action line.

    Summaries are written as bullet lists whose last bullet names what the
    reader has to do ("- Action items: Request an invitation..."). The row shows
    the narrative as body text and the action on its own, so the action must be
    lifted out rather than left duplicated in both places.

    Pre:  summary is a stored ``email_summaries.summary`` value, or None.
    Post: returns (body, action). ``action`` is None when the summary names no
          action. ``body`` never contains the action line, and is "" when the
          summary was nothing but an action line -- the caller then falls back
          to the subject, so a row is never left with empty body text.
    """
    if not summary or not str(summary).strip():
        return "", None

    body_lines: List[str] = []
    action: Optional[str] = None
    for line in str(summary).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        unmarked = stripped.lstrip("-*• \t")
        lowered = unmarked.lower()
        matched = next((p for p in _ACTION_LINE_PREFIXES if lowered.startswith(p)), None)
        if matched and action is None:
            action = unmarked[len(matched):].strip() or unmarked.strip()
        else:
            body_lines.append(unmarked)

    return " ".join(body_lines).strip(), action


def _compose_row_text(
    *,
    stored_summary: Optional[str] = None,
    explicit_snippet: Optional[str] = None,
    explicit_comment: Optional[str] = None,
    triage_reason: Optional[str] = None,
    subject: Optional[str] = None,
) -> tuple[str, Optional[str], Optional[str]]:
    """Resolve one stream row's body, action and triage label.

    Three call sites build stream rows -- the urgency file's ``per_uid`` map,
    its ``accounts`` map, and ``email_message_index`` -- and each used to
    compose this text itself. Two of the three fell back to the triage reason
    for body text while also returning it as the comment, so every row rendered
    the same string twice. Resolving it in one place is what stops those three
    from drifting apart again.

    Pre:  the caller supplies whichever of the five inputs its source carries.
    Post: returns (body, action, reason).
          - body is never the triage reason, and is "" only when the source
            carried no summary, no snippet and no subject.
          - action is None unless the source named one.
          - reason is the triage label, for a chip; it is never body text.
    Inv:  body, action and reason are three distinct roles. A caller that
          renders any two of them from the same value has reintroduced the
          duplicate this function exists to prevent.
    """
    summary_body, summary_action = _split_summary_and_action(stored_summary)

    body = summary_body or (explicit_snippet or "").strip() or (subject or "").strip()
    action = (explicit_comment or "").strip() or summary_action or None
    reason = (triage_reason or "").strip() or None

    # A source may carry the same string as both comment and triage label
    # (email_urgency_alerts stores one `reason` read by both). Showing it twice
    # is the fault; the chip is the better home for it.
    if action and reason and action == reason:
        action = None

    return body, action, reason



def _replied_message_ids(sched_db_path, owner: Optional[str]) -> set:
    """Message-ids the user has answered, drawn from their own sent mail.

    Pre:  sched_db_path points at the email cache; the Sent folder may or may
          not have been indexed yet.
    Post: the set of Message-IDs that a sent message names as the thing it
          replies to. Empty when Sent has never been indexed, which is the
          normal state until the index_sent_mail task has run.
    Inv:  read-only and never raises -- ranking is an enhancement to the
          stream, so a missing column or table must not cost the briefing.
    """
    import sqlite3 as _sql3

    replied = set()
    try:
        conn = _sql3.connect(str(sched_db_path), timeout=2.0)
        try:
            rows = conn.execute(
                """
                SELECT in_reply_to, references_hdr
                FROM email_message_index
                WHERE (owner = ? OR owner IS NULL OR owner = '')
                  AND lower(folder) LIKE '%sent%'
                  AND (in_reply_to != '' OR references_hdr != '')
                """,
                (owner or "",),
            ).fetchall()
        finally:
            conn.close()
        for in_reply_to, references in rows:
            for token in f"{in_reply_to or ''} {references or ''}".split():
                token = token.strip().strip(',')
                if token:
                    replied.add(token)
    except Exception as e:
        logger.debug("Replied-thread lookup skipped: %s", e)
    return replied


def _tag_emails_with_organisers(
    emails: List[Dict[str, Any]], db: Session, owner: Optional[str],
) -> List[Dict[str, Any]]:
    """Attach each stream row's organiser ids, so the panel can filter by them.

    Membership is resolved once per refresh for the whole stream rather than per
    filter interaction, because the filter narrows rows the client already holds.

    Pre:  emails are stream rows from _fetch_email_digest_data; db is open.
    Post: every row carries ``organiser_ids`` (possibly empty), and the return
          value is the organiser descriptors the panel needs for its control.
          On any failure the rows are left untagged rather than the briefing
          failing -- organiser filtering enhances the stream, it is not a
          precondition for showing it.
    Inv:  membership comes from the organisers module's own resolver, so this
          filter and the Organisers panel cannot disagree about where an email
          belongs.
    """
    try:
        from core.database import WorkOrganiser
        from routes.organisers.organisers_routes import (
            email_belongs_to_organiser,
            load_organiser_overrides,
        )
    except Exception as exc:
        logger.debug("Organiser tagging unavailable: %s", exc)
        return []

    try:
        organisers = db.query(WorkOrganiser).filter(
            WorkOrganiser.is_active == True,
            or_(WorkOrganiser.owner == owner, WorkOrganiser.owner == None),
        ).order_by(WorkOrganiser.sort_order.asc()).all()
        if not organisers:
            return []
        overrides = load_organiser_overrides(db, owner)
    except Exception as exc:
        logger.debug("Organiser tagging skipped: %s", exc)
        return []

    parsed = []
    for org in organisers:
        try:
            accounts = json.loads(org.target_accounts) if org.target_accounts else []
        except Exception:
            accounts = []
        try:
            rules = json.loads(org.rules_json) if org.rules_json else {}
        except Exception:
            rules = {}
        parsed.append((org, accounts, rules))

    for email in emails:
        # The stream names its fields for display (sender_name, sender_email);
        # the matcher speaks the index's vocabulary. Translating once here keeps
        # that mismatch at the boundary rather than inside the matcher.
        candidate = {
            "account_key": email.get("account_id") or "",
            "uid": email.get("uid") or "",
            "from_name": email.get("sender_name") or "",
            "from_address": email.get("sender_email") or "",
            "subject": email.get("subject") or "",
            "snippet": email.get("snippet") or "",
        }
        email["organiser_ids"] = [
            org.id for org, accounts, rules in parsed
            if email_belongs_to_organiser(candidate, org, accounts, rules, overrides)
        ]

    return [
        {"id": org.id, "name": org.name, "icon": org.icon, "color": org.color}
        for org, _accounts, _rules in parsed
    ]


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

    sched_db_path = Path(_constants.SCHEDULED_EMAILS_DB if hasattr(_constants, "SCHEDULED_EMAILS_DB") else (Path(_constants.DATA_DIR) / "scheduled_emails.db"))

    if sched_db_path.exists():
        try:
            s_conn = _sql3.connect(str(sched_db_path), timeout=2.0)
            try:
                cur = s_conn.cursor()
                # Summaries
                try:
                    for mid, summ in cur.execute("SELECT message_id, summary FROM email_summaries WHERE summary IS NOT NULL").fetchall():
                        if mid and summ:
                            ai_summaries[str(mid).strip()] = str(summ).strip()
                except Exception:
                    pass

                # Alerts
                try:
                    for mid, score, reason in cur.execute("SELECT message_id, urgency_score, reason FROM email_urgency_alerts WHERE (owner = ? OR owner IS NULL OR owner = '')", (owner or "",)).fetchall():
                        if mid:
                            urgency_scores[str(mid).strip()] = (float(score or 0), str(reason or ""))
                except Exception:
                    pass
            finally:
                s_conn.close()
        except Exception as e:
            logger.debug("Database email alerts query deferred: %s", e)

    # 3. Read urgency state snapshot file (per_uid map and accounts map)
    slug = _owner_slug(owner)
    urgency_file = Path(_constants.DATA_DIR) / f"email_urgency_state_{slug}.json"
    if urgency_file.exists():
        try:
            urgency_data = json.loads(urgency_file.read_text(encoding="utf-8"))
            per_uid = urgency_data.get("per_uid") or {}

            for key, msg in per_uid.items():
                msg_uid = str(msg.get("uid") or "")
                acc_id = "default"
                if ":" in str(key):
                    parts = str(key).split(":", 1)
                    acc_id, msg_uid = parts[0], parts[1]
                elif not msg_uid:
                    msg_uid = str(key)

                item_id = f"{acc_id}:{msg_uid}"
                if item_id in seen_ids:
                    continue

                msg_epoch = float(msg.get("ts") or 0.0)
                if msg_epoch and msg_epoch < cutoff_epoch:
                    continue

                seen_ids.add(item_id)
                score_val = float(msg.get("score") or 0)
                is_urgent = score_val >= 2 or bool(msg.get("is_urgent"))
                urgency_lvl = "critical" if score_val >= 3 else ("urgent" if is_urgent else "normal")
                mid_clean = str(msg.get("message_id") or "").strip()
                body_text, action_text, triage_reason = _compose_row_text(
                    stored_summary=ai_summaries.get(mid_clean) or msg.get("summary"),
                    explicit_snippet=msg.get("snippet") or msg.get("preview"),
                    triage_reason=msg.get("reason"),
                    subject=msg.get("subject"),
                )

                msg_date_str = ""
                if msg_epoch:
                    try:
                        msg_date_str = datetime.fromtimestamp(msg_epoch, tz=timezone.utc).isoformat()
                    except Exception:
                        msg_date_str = now_utc.isoformat()
                else:
                    msg_date_str = msg.get("date") or msg.get("timestamp") or now_utc.isoformat()

                matched_acc = next((a for a in accounts_out if a["id"] == acc_id), None)
                acc_name = matched_acc["name"] if matched_acc else (acc_id if acc_id != "default" else "Primary Inbox")

                raw_emails.append({
                    "id": item_id,
                    "uid": msg_uid,
                    "account_id": acc_id,
                    "account_name": acc_name,
                    "sender_name": msg.get("from") or msg.get("sender_name") or msg.get("sender") or "Unknown",
                    "sender_email": msg.get("from_address") or msg.get("from_email") or "",
                    "subject": msg.get("subject") or "(No Subject)",
                    "message_id": mid_clean,
                    "snippet": body_text,
                    "timestamp": msg_date_str,
                    "date_epoch": msg_epoch or now_utc.timestamp(),
                    "read": not bool(msg.get("unread", True)),
                    "urgency": urgency_lvl,
                    "ai_comment": action_text,
                    "triage_reason": triage_reason,
                    "tags": [t for t in (msg.get("tags") or []) if t],
                    "folder": "INBOX",
                })

            # Also parse accounts format if present
            for acc_id, acc_info in (urgency_data.get("accounts") or {}).items():
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

                    acc_mid = str(msg.get("message_id") or "").strip()
                    body_text, action_text, triage_reason = _compose_row_text(
                        stored_summary=ai_summaries.get(acc_mid) or msg.get("summary"),
                        explicit_snippet=msg.get("snippet") or msg.get("preview"),
                        explicit_comment=msg.get("ai_comment"),
                        triage_reason=msg.get("reason"),
                        subject=msg.get("subject"),
                    )

                    raw_emails.append({
                        "id": msg_id,
                        "uid": msg_uid,
                        "account_id": acc_id,
                        "account_name": acc_name,
                        "sender_name": msg.get("sender_name") or msg.get("from_name") or msg.get("sender") or "Unknown",
                        "sender_email": msg.get("sender_email") or msg.get("from_email") or "",
                        "subject": msg.get("subject") or "(No Subject)",
                        "message_id": acc_mid,
                        "snippet": body_text,
                        "timestamp": msg_ts_str,
                        "date_epoch": msg_epoch,
                        "read": bool(msg.get("read", False)),
                        "urgency": urgency_lvl,
                        "ai_comment": action_text,
                        "triage_reason": triage_reason,
                        "tags": [t for t in (msg.get("tags") or []) if t],
                        "folder": "INBOX",
                    })
        except Exception as e:
            logger.debug("Urgency file reading deferred: %s", e)

    # 4. Read indexed emails from scheduled_emails.db email_message_index
    if sched_db_path.exists():
        try:
            s_conn = _sql3.connect(str(sched_db_path), timeout=2.0)
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
                    LIMIT 400
                    """,
                    (owner or "", cutoff_epoch),
                ).fetchall()

                for r in rows:
                    uid, acc_key, mid, subj, from_n, from_a, d_iso, d_epoch, flags = r
                    msg_uid = str(uid)
                    acc_key_str = str(acc_key or "default")
                    item_id = f"{acc_key_str}:{msg_uid}"
                    if item_id in seen_ids:
                        continue
                    seen_ids.add(item_id)

                    flags_str = str(flags or "")
                    is_read = "\\Seen" in flags_str

                    mid_clean = str(mid or "").strip()
                    score_info = urgency_scores.get(mid_clean) or (0.0, "")
                    score_val = score_info[0]
                    urgency_lvl = "critical" if score_val >= 80 else ("urgent" if score_val >= 50 else "normal")
                    body_text, action_text, triage_reason = _compose_row_text(
                        stored_summary=ai_summaries.get(mid_clean),
                        triage_reason=score_info[1],
                        subject=subj,
                    )

                    matched_acc = next((a for a in accounts_out if a["id"] == acc_key_str), None)
                    acc_display = matched_acc["name"] if matched_acc else (acc_key_str if acc_key_str != "default" else "Primary Inbox")

                    raw_emails.append({
                        "id": item_id,
                        "uid": msg_uid,
                        "account_id": acc_key_str,
                        "account_name": acc_display,
                        "sender_name": from_n or from_a or "Unknown",
                        "sender_email": from_a or "",
                        "subject": subj or "(No Subject)",
                        "message_id": mid_clean,
                        "snippet": body_text,
                        "timestamp": d_iso or now_utc.isoformat(),
                        "date_epoch": float(d_epoch or 0),
                        "read": is_read,
                        "urgency": urgency_lvl,
                        "ai_comment": action_text,
                        "triage_reason": triage_reason,
                        "tags": [],
                        "folder": "INBOX",
                    })
            finally:
                s_conn.close()
        except Exception as e:
            logger.debug("Scheduled email index query deferred: %s", e)

    # 5. Normalize accounts list: ensure all account_ids in raw_emails have descriptors
    existing_acc_ids = {a["id"] for a in accounts_out}
    discovered_acc_ids = {e.get("account_id") for e in raw_emails if e.get("account_id")}

    for acc_k in sorted(discovered_acc_ids):
        if acc_k not in existing_acc_ids:
            existing_acc_ids.add(acc_k)
            accounts_out.append({
                "id": acc_k,
                "name": "Primary Inbox" if acc_k == "default" else f"Account {acc_k[:8]}",
                # A discovered id has no EmailAccount row, so no address is
                # known. Real descriptors above use "" for that; putting the
                # display label here made consumers render "Account a1b2c3d4"
                # as if it were a mailbox address.
                "email": "",
                "is_default": False,
            })

    if not accounts_out:
        accounts_out = [
            {
                "id": "default",
                "name": "Primary Inbox",
                "email": "",
                "is_default": True,
            }
        ]

    # Invariant: exactly one descriptor is the default. The per-append rule was
    # `acc_k == "default" or len(accounts_out) == 0`, which marked both the
    # first discovered account and a later literal "default" — two defaults.
    # The first configured default wins; otherwise the first account does.
    seen_default = False
    for a in accounts_out:
        if a["is_default"] and not seen_default:
            seen_default = True
        else:
            a["is_default"] = False
    if not seen_default:
        accounts_out[0]["is_default"] = True

    # Sort emails by date_epoch descending
    # Threads the user has answered rank above equivalent ones they have not.
    # Having replied is the strongest signal available that a thread matters,
    # and it costs one indexed read. Empty until Sent has been indexed.
    replied_ids = _replied_message_ids(sched_db_path, owner)
    if replied_ids:
        for email in raw_emails:
            mid = str(email.get("message_id") or "").strip()
            email["replied"] = bool(mid and mid in replied_ids)
    else:
        for email in raw_emails:
            email["replied"] = False

    raw_emails.sort(
        key=lambda m: (bool(m.get("replied")), m.get("date_epoch") or 0.0),
        reverse=True,
    )

    # Dynamically compute unread and urgent counts for the active duration
    total_unread = sum(1 for e in raw_emails if not e.get("read"))
    total_urgent = sum(1 for e in raw_emails if e.get("urgency") in ("critical", "urgent"))

    return {
        "accounts": accounts_out,
        "total_unread": total_unread,
        "total_urgent": total_urgent,
        "days": days,
        "emails": raw_emails[:250],
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

        # 2b. Organiser membership, so the email panel can filter by the same
        # taxonomy the Organisers module maintains. Adding an organiser there
        # makes it selectable here on the next refresh, with no code change.
        email_digest["organisers"] = _tag_emails_with_organisers(
            email_digest.get("emails") or [], db, owner,
        )

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
        email_days: int = Query(_BRIEFING_WINDOW_DAYS, ge=1, le=_BRIEFING_WINDOW_DAYS),
        force_refresh: bool = Query(False),
        db: Session = Depends(get_db),
    ):
        """Retrieve aggregated morning briefing with SWR caching.

        The served window is always ``_BRIEFING_WINDOW_DAYS``; ``email_days`` is
        accepted for compatibility and clamped up to it. Narrowing by date is
        the client's job, because the duration control belongs to the email
        panel alone -- when it drove this parameter, every press rebuilt the
        projects and operations panels too and gave each duration its own cache
        bucket, multiplying identical payloads.
        """
        # Let require_user's 401 / 403 propagate. Swallowing it fell through to
        # owner=None, whose cache key is "__global__" — an unauthenticated
        # caller was served the shared briefing bucket, and the 403 that bars
        # API tokens from user-scoped routes was discarded too. Every other
        # route in the codebase calls this bare; match that.
        owner = require_user(request)

        # One window, one bucket per owner. The key still names the window it
        # holds, so it stays truthful if that constant ever changes.
        email_days = _BRIEFING_WINDOW_DAYS
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
