"""routes/organisers/organisers_routes.py

AI Work Organisers router.
Manages high-level semantic categories that bind multi-account emails,
actionable project tasks, contextual memories, and AI assistant directives.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from core.database import (
    SessionLocal,
    get_db,
    WorkOrganiser,
    Project,
    ProjectTask,
    Memory,
    EmailAccount,
    utcnow_naive,
)
from src.auth_helpers import require_user
from src.constants import DATA_DIR, SCHEDULED_EMAILS_DB

logger = logging.getLogger(__name__)


# ================= SCHEMAS =================

class OrganiserRules(BaseModel):
    senders: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    domains: List[str] = Field(default_factory=list)


class OrganiserCreate(BaseModel):
    name: str
    slug: Optional[str] = None
    description: Optional[str] = None
    category_group: str = "operations"  # operations, strategy, partnerships, finance, tech, personal
    icon: str = "briefcase"
    color: str = "#61afef"
    priority: str = "normal"  # critical, high, normal, low
    target_accounts: List[str] = Field(default_factory=list)
    rules: OrganiserRules = Field(default_factory=OrganiserRules)
    ai_instructions: Optional[str] = None
    linked_project_ids: List[str] = Field(default_factory=list)
    memory_lane: Optional[str] = None
    sort_order: int = 0


class OrganiserUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category_group: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    priority: Optional[str] = None
    target_accounts: Optional[List[str]] = None
    rules: Optional[OrganiserRules] = None
    ai_instructions: Optional[str] = None
    linked_project_ids: Optional[List[str]] = None
    memory_lane: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class PreviewRulesRequest(BaseModel):
    target_accounts: List[str] = Field(default_factory=list)
    rules: OrganiserRules = Field(default_factory=OrganiserRules)
    days: int = 14
    limit: int = 20


# ================= DEFAULT EMPIRICAL CATEGORIES =================

DEFAULT_ORGANISERS = [
    {
        "slug": "bilweekend-tour-ops",
        "name": "Bil Weekend Tour Operations & Bookings",
        "category_group": "operations",
        "icon": "briefcase",
        "color": "#61afef",
        "priority": "critical",
        "target_accounts": ["99fccecdba6c497bb5961e5bf9b780d4"],
        "rules": {
            "senders": ["Adrian Matache", "Nivine Ismail", "Ali Bil Weekend", "adatours.com", "Thikaa"],
            "keywords": ["tour", "quotation", "rates", "pax", "hotel", "resort", "booking"],
            "domains": ["adatours.com", "bilweekend.com"]
        },
        "ai_instructions": "Prioritize custom tour quotations (Federal Iraq & Kurdistan), 37-pax group arrangements, hotel contract rates (Ashur Resort), and direct traveler inquiries. Draft professional, accurate responses and highlight booking deadlines.",
        "memory_lane": "organisers:bilweekend_ops",
        "sort_order": 1,
    },
    {
        "slug": "bilweekend-team-strategy",
        "name": "Internal Team Strategy & Proposals",
        "category_group": "strategy",
        "icon": "users",
        "color": "#98c379",
        "priority": "high",
        "target_accounts": ["d42f8326b1b64bf9a256bab742bef8ee"],
        "rules": {
            "senders": ["Mustafa Nabil", "Mohammed Alawadi", "Noor Ahmed", "Ghada Al Makhzomy", "Mustafa Simani"],
            "keywords": ["proposal", "app", "meeting", "agreement", "strategy", "school"],
            "domains": ["bilweekend.iq"]
        },
        "ai_instructions": "Track internal team proposals (School Proposal, App Notices), weekly meeting agendas, and shared document revisions. Surface pending decisions and track assigned team deliverables.",
        "memory_lane": "organisers:team_strategy",
        "sort_order": 2,
    },
    {
        "slug": "tourism-b2b-partnerships",
        "name": "B2B Tourism Partnerships & Suppliers",
        "category_group": "partnerships",
        "icon": "globe",
        "color": "#e5c07b",
        "priority": "normal",
        "target_accounts": ["99fccecdba6c497bb5961e5bf9b780d4", "d42f8326b1b64bf9a256bab742bef8ee"],
        "rules": {
            "senders": ["Zivotrip Sales", "DMCFinder", "TravelShop Booking", "Seat Unique", "Bilitom Hotel", "Uzakrota"],
            "keywords": ["wholesale", "b2b", "fair", "trade", "cooperation", "dmc", "partnership"],
            "domains": ["dmcfinder.com", "travelshopbooking.com", "seatunique.com"]
        },
        "ai_instructions": "Catalog wholesale supplier rates, trade fair invitations (Antalya Tourism Fair), and supplier agreements. Extract partner pricing and summarize B2B terms.",
        "memory_lane": "organisers:b2b_partnerships",
        "sort_order": 3,
    },
    {
        "slug": "financial-intelligence",
        "name": "Financial Intelligence & Market Research",
        "category_group": "finance",
        "icon": "trending-up",
        "color": "#c678dd",
        "priority": "normal",
        "target_accounts": ["e4c890c531d74898928ba764b1fa2a2c"],
        "rules": {
            "senders": ["research@rs.iq", "zmohanad@rs.iq", "RS Research"],
            "keywords": ["سوق العراق للأوراق المالية", "تداولات", "نشرة", "ISX", "stocks", "market", "economy"],
            "domains": ["rs.iq"]
        },
        "ai_instructions": "Parse daily and weekly Iraq Stock Exchange (ISX) reports from RS Research. Extract trading volumes, index movements, sector performance, and macroeconomic trends.",
        "memory_lane": "organisers:financial_intel",
        "sort_order": 4,
    },
    {
        "slug": "tech-security-infrastructure",
        "name": "Technical Infrastructure & Security",
        "category_group": "tech",
        "icon": "shield",
        "color": "#e06c75",
        "priority": "high",
        "target_accounts": ["7a8233ae54194c2f9590fba1dc38659b"],
        "rules": {
            "senders": ["Google", "GitHub", "Vercel Inc.", "Toters"],
            "keywords": ["security alert", "ssh", "oauth", "receipt", "verification", "claude", "ollama", "vercel", "github"],
            "domains": ["github.com", "vercel.com", "google.com"]
        },
        "ai_instructions": "Monitor SSH key modifications, cloud hosting receipts (Vercel), OAuth third-party permissions, and critical Google Security alerts. Verify infrastructure integrity.",
        "memory_lane": "organisers:tech_security",
        "sort_order": 5,
    },
    {
        "slug": "personal-logistics",
        "name": "Personal Logistics & Lifestyle",
        "category_group": "personal",
        "icon": "coffee",
        "color": "#56b6c2",
        "priority": "low",
        "target_accounts": ["e4c890c531d74898928ba764b1fa2a2c", "7a8233ae54194c2f9590fba1dc38659b"],
        "rules": {
            "senders": ["Secret Escapes", "Pinterest", "Steam", "Reddit", "ElevenLabs", "Toters"],
            "keywords": ["sale", "escapes", "gift", "delivery", "points", "order"],
            "domains": ["secretescapes.com", "pinterest.com", "steampowered.com", "redditmail.com"]
        },
        "ai_instructions": "Group food deliveries, gaming receipts, travel leisure ideas, and non-work notifications cleanly away from executive queues.",
        "memory_lane": "organisers:personal_logistics",
        "sort_order": 6,
    },
]


# ================= HELPER FUNCTIONS =================

def _normalize_slug(name: str, custom_slug: Optional[str] = None) -> str:
    if custom_slug:
        raw = custom_slug.strip().lower()
    else:
        raw = name.strip().lower()
    slug_chars = [c if (c.isalnum() or c in "-_") else "-" for c in raw]
    clean = "".join(slug_chars).strip("-")
    while "--" in clean:
        clean = clean.replace("--", "-")
    return clean or f"org-{uuid.uuid4().hex[:8]}"


def _matches_rule(
    email: Dict[str, Any],
    target_accounts: List[str],
    rules: Dict[str, Any],
) -> bool:
    """Evaluate if an email matches an organiser's target accounts and rules.

    An organiser selects an email when it passes the account filter (if one is
    set) AND matches at least one sender / domain / keyword rule (if any are
    set). An organiser that sets *neither* selects nothing: it is unconfigured,
    not universal.
    """
    senders = [s.strip().lower() for s in rules.get("senders", []) if s.strip()]
    keywords = [k.strip().lower() for k in rules.get("keywords", []) if k.strip()]
    domains = [d.strip().lower().lstrip("@") for d in rules.get("domains", []) if d.strip()]

    # An organiser with no criteria at all matches nothing. Previously the
    # account filter was skipped when target_accounts was empty and the rule
    # check then returned True unconditionally — so a freshly-created or
    # seeded organiser claimed every email in the index (161 of 161 live).
    if not target_accounts and not senders and not keywords and not domains:
        return False

    # 1. Account Filter
    if target_accounts:
        acc_id = email.get("account_key") or email.get("account_id") or ""
        # An email carrying no account key cannot be confirmed as a member of
        # the targeted accounts, so it fails the filter rather than bypassing
        # it (the previous `if acc_id and ...` let those through).
        if acc_id not in target_accounts:
            return False

    # Account match alone is sufficient when the organiser declares no rules.
    if not senders and not keywords and not domains:
        return True

    from_name = (email.get("from_name") or "").lower()
    from_addr = (email.get("from_address") or "").lower()
    subject = (email.get("subject") or "").lower()
    body_snippet = (email.get("snippet") or "").lower()

    # Senders Match
    for s in senders:
        if s in from_name or s in from_addr:
            return True

    # Domains Match
    for d in domains:
        if f"@{d}" in from_addr or from_addr.endswith(f".{d}"):
            return True

    # Keywords Match (in Subject or Snippet)
    for kw in keywords:
        if kw in subject or kw in body_snippet:
            return True

    return False


def _get_recent_emails(days: int = 14) -> List[Dict[str, Any]]:
    """Retrieve raw email rows from SCHEDULED_EMAILS_DB."""
    db_file = Path(SCHEDULED_EMAILS_DB)
    if not db_file.exists():
        return []

    cutoff_ts = time.time() - (days * 86400)
    try:
        conn = sqlite3.connect(str(db_file), timeout=5.0)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        rows = cur.execute("""
            SELECT account_key, folder, uid, message_id, subject, from_name, from_address,
                   to_text, cc_text, date_iso, date_display, date_epoch, size, flags, has_attachments
            FROM email_message_index
            WHERE date_epoch >= ?
            ORDER BY date_epoch DESC
        """, (cutoff_ts,)).fetchall()
        emails = [dict(r) for r in rows]
        conn.close()
        return emails
    except Exception as e:
        logger.debug("Failed querying scheduled_emails.db for organisers: %s", e)
        return []


def _get_memory_manager():
    try:
        from src.memory import MemoryManager
        from src.constants import DATA_DIR
        return MemoryManager(DATA_DIR)
    except Exception:
        return None


def _organiser_memories(org, owner, limit: int = 20) -> List[Dict[str, Any]]:
    """The memories bound to one organiser's lane.

    Pre:  org is a persisted WorkOrganiser; owner is the caller's username, or
          None for an unscoped read.
    Post: at most `limit` entries the caller owns, each either carrying the
          organiser's memory lane or category group as its category, or naming
          the organiser's slug in its text.
    Inv:  reads the JSON store through MemoryManager, which is where memories
          actually live — the SQLAlchemy Memory table is a separate store that
          nothing in this system writes or reads. Never raises: an unreadable
          store yields [].

    Shared with mcp_servers/organisers_server.py so the MCP tool and the HTTP
    route cannot drift into answering the same question differently.
    """
    mem_mgr = _get_memory_manager()
    if not mem_mgr or not org.slug:
        return []
    try:
        # Scope to the caller. load_all() is unfiltered and returned every
        # user's memories on a multi-user deploy.
        own_mems = mem_mgr.load(owner) if owner else mem_mgr.load_all()
        target_slug = org.slug.lower()
        categories = {
            c for c in (org.memory_lane, org.category_group)
            if c and c.strip()
        }
        return [
            {
                "id": m.get("id"),
                "content": m.get("text"),
                "category": m.get("category"),
                "timestamp": m.get("timestamp"),
            }
            for m in own_mems
            if m.get("category") in categories
            or target_slug in (m.get("text") or "").lower()
        ][:limit]
    except Exception:
        return []


def _format_organiser_summary(
    org: WorkOrganiser,
    all_emails: List[Dict[str, Any]],
    db: Session,
) -> Dict[str, Any]:
    """Compile complete metadata and stats for an organiser."""
    try:
        accounts_list = json.loads(org.target_accounts) if org.target_accounts else []
    except Exception:
        accounts_list = []

    try:
        rules_dict = json.loads(org.rules_json) if org.rules_json else {}
    except Exception:
        rules_dict = {}

    try:
        project_ids = json.loads(org.linked_project_ids) if org.linked_project_ids else []
    except Exception:
        project_ids = []

    # Calculate email match count
    matching_emails = [e for e in all_emails if _matches_rule(e, accounts_list, rules_dict)]
    match_count = len(matching_emails)

    # Calculate linked tasks count
    tasks_count = 0
    if project_ids:
        tasks_count = db.query(ProjectTask).filter(
            ProjectTask.project_id.in_(project_ids),
            ProjectTask.completed == False,
        ).count()

    # Calculate linked memories count
    memory_count = 0
    mem_mgr = _get_memory_manager()
    if mem_mgr and org.slug:
        try:
            all_mems = mem_mgr.load_all()
            target_slug = org.slug.lower()
            memory_count = sum(
                1 for m in all_mems
                if target_slug in (m.get("text") or "").lower() or m.get("category") == org.category_group
            )
        except Exception:
            memory_count = 0

    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "description": org.description,
        "category_group": org.category_group,
        "icon": org.icon,
        "color": org.color,
        "priority": org.priority,
        "target_accounts": accounts_list,
        "rules": rules_dict,
        "ai_instructions": org.ai_instructions,
        "linked_project_ids": project_ids,
        "memory_lane": org.memory_lane,
        "is_active": org.is_active,
        "sort_order": org.sort_order,
        "stats": {
            "email_matches_14d": match_count,
            "open_tasks": tasks_count,
            "memories_count": memory_count,
        },
        "created_at": org.created_at.isoformat() if org.created_at else None,
        "updated_at": org.updated_at.isoformat() if org.updated_at else None,
    }


# ================= ROUTER DEFINITION =================

def setup_organisers_routes() -> APIRouter:
    router = APIRouter(prefix="/api/organisers", tags=["organisers"])

    @router.get("")
    def list_organisers(
        request: Request,
        group: Optional[str] = None,
        db: Session = Depends(get_db),
    ):
        """List all work organisers for the user with match statistics."""
        owner = require_user(request)
        all_emails = _get_recent_emails(days=14)

        query = db.query(WorkOrganiser).filter(
            or_(WorkOrganiser.owner == owner, WorkOrganiser.owner == None),
            WorkOrganiser.is_active == True,
        )
        if group:
            query = query.filter(WorkOrganiser.category_group == group)

        organisers = query.order_by(WorkOrganiser.sort_order.asc(), WorkOrganiser.created_at.asc()).all()

        # If zero organisers exist for this user, auto-seed defaults seamlessly
        if not organisers:
            for item in DEFAULT_ORGANISERS:
                new_org = WorkOrganiser(
                    id=uuid.uuid4().hex,
                    owner=owner,
                    name=item["name"],
                    slug=item["slug"],
                    category_group=item["category_group"],
                    icon=item["icon"],
                    color=item["color"],
                    priority=item["priority"],
                    target_accounts=json.dumps(item["target_accounts"]),
                    rules_json=json.dumps(item["rules"]),
                    ai_instructions=item["ai_instructions"],
                    memory_lane=item.get("memory_lane"),
                    sort_order=item["sort_order"],
                    is_active=True,
                )
                db.add(new_org)
            db.commit()
            organisers = query.order_by(WorkOrganiser.sort_order.asc()).all()

        results = [_format_organiser_summary(o, all_emails, db) for o in organisers]
        return {
            "ok": True,
            "total": len(results),
            "organisers": results,
        }

    @router.get("/{id_or_slug}")
    def get_organiser_detail(
        id_or_slug: str,
        request: Request,
        db: Session = Depends(get_db),
    ):
        """Get full details of a specific organiser with matching emails, tasks, and memories."""
        owner = require_user(request)
        org = db.query(WorkOrganiser).filter(
            or_(WorkOrganiser.id == id_or_slug, WorkOrganiser.slug == id_or_slug),
            or_(WorkOrganiser.owner == owner, WorkOrganiser.owner == None),
        ).first()

        if not org:
            raise HTTPException(404, f"Work organiser '{id_or_slug}' not found")

        all_emails = _get_recent_emails(days=14)
        summary = _format_organiser_summary(org, all_emails, db)

        # 1. Matching Emails
        accounts_list = summary["target_accounts"]
        rules_dict = summary["rules"]
        matched_emails = [
            {
                "id": f"{e.get('account_key')}:{e.get('uid')}",
                "uid": str(e.get("uid")),
                "account_id": e.get("account_key"),
                "folder": e.get("folder", "INBOX"),
                "sender_name": e.get("from_name") or e.get("from_address") or "Unknown",
                "sender_email": e.get("from_address") or "",
                "subject": e.get("subject") or "(No subject)",
                "date_iso": e.get("date_iso"),
                "date_display": e.get("date_display"),
                "has_attachments": bool(e.get("has_attachments")),
            }
            for e in all_emails if _matches_rule(e, accounts_list, rules_dict)
        ][:50]

        # 2. Linked Tasks
        tasks_list = []
        if summary["linked_project_ids"]:
            tasks = db.query(ProjectTask).filter(
                ProjectTask.project_id.in_(summary["linked_project_ids"])
            ).order_by(ProjectTask.completed.asc(), ProjectTask.due_date.asc()).all()
            tasks_list = [
                {
                    "id": t.id,
                    "project_id": t.project_id,
                    "title": t.title,
                    "description": t.description,
                    "completed": bool(t.completed),
                    "priority": t.priority,
                    "due_date": t.due_date,
                }
                for t in tasks
            ]

        # 3. Linked Memories
        #
        # Memory entries carry (id, text, category, timestamp, owner) — there
        # is no separate lane field, so `category` is what memory_lane can bind
        # to. The column was written on create/update (seeds use namespaced
        # values like "organisers:bilweekend_ops") and never read.
        #
        # The lane is an *additional* selector, not a replacement for
        # category_group: no existing memory carries a namespaced category, so
        # letting the lane displace category_group would empty this tab for
        # every seeded organiser. Match either, plus the slug-in-text heuristic.
        memories_list = _organiser_memories(org, owner)

        return {
            "ok": True,
            "organiser": summary,
            "matching_emails": matched_emails,
            "tasks": tasks_list,
            "memories": memories_list,
        }

    @router.post("")
    def create_organiser(
        payload: OrganiserCreate,
        request: Request,
        db: Session = Depends(get_db),
    ):
        """Create a new work organiser."""
        owner = require_user(request)
        slug = _normalize_slug(payload.name, payload.slug)

        existing = db.query(WorkOrganiser).filter(
            WorkOrganiser.owner == owner,
            WorkOrganiser.slug == slug,
        ).first()
        if existing:
            raise HTTPException(400, f"An organiser with slug '{slug}' already exists")

        rules_dict = payload.rules.model_dump() if hasattr(payload.rules, "model_dump") else payload.rules.dict()

        new_org = WorkOrganiser(
            id=uuid.uuid4().hex,
            owner=owner,
            name=payload.name,
            slug=slug,
            description=payload.description,
            category_group=payload.category_group,
            icon=payload.icon,
            color=payload.color,
            priority=payload.priority,
            target_accounts=json.dumps(payload.target_accounts),
            rules_json=json.dumps(rules_dict),
            ai_instructions=payload.ai_instructions,
            linked_project_ids=json.dumps(payload.linked_project_ids),
            memory_lane=payload.memory_lane or f"organisers:{slug}",
            sort_order=payload.sort_order,
            is_active=True,
        )
        db.add(new_org)
        db.commit()
        db.refresh(new_org)

        all_emails = _get_recent_emails(days=14)
        return {
            "ok": True,
            "organiser": _format_organiser_summary(new_org, all_emails, db),
        }

    @router.put("/{id_or_slug}")
    def update_organiser(
        id_or_slug: str,
        payload: OrganiserUpdate,
        request: Request,
        db: Session = Depends(get_db),
    ):
        """Update an existing work organiser."""
        owner = require_user(request)
        org = db.query(WorkOrganiser).filter(
            or_(WorkOrganiser.id == id_or_slug, WorkOrganiser.slug == id_or_slug),
            or_(WorkOrganiser.owner == owner, WorkOrganiser.owner == None),
        ).first()

        if not org:
            raise HTTPException(404, f"Work organiser '{id_or_slug}' not found")

        if payload.name is not None:
            org.name = payload.name
        if payload.description is not None:
            org.description = payload.description
        if payload.category_group is not None:
            org.category_group = payload.category_group
        if payload.icon is not None:
            org.icon = payload.icon
        if payload.color is not None:
            org.color = payload.color
        if payload.priority is not None:
            org.priority = payload.priority
        if payload.target_accounts is not None:
            org.target_accounts = json.dumps(payload.target_accounts)
        if payload.rules is not None:
            rules_dict = payload.rules.model_dump() if hasattr(payload.rules, "model_dump") else payload.rules.dict()
            org.rules_json = json.dumps(rules_dict)
        if payload.ai_instructions is not None:
            org.ai_instructions = payload.ai_instructions
        if payload.linked_project_ids is not None:
            org.linked_project_ids = json.dumps(payload.linked_project_ids)
        if payload.memory_lane is not None:
            org.memory_lane = payload.memory_lane
        if payload.is_active is not None:
            org.is_active = payload.is_active
        if payload.sort_order is not None:
            org.sort_order = payload.sort_order

        org.updated_at = utcnow_naive()
        db.commit()
        db.refresh(org)

        all_emails = _get_recent_emails(days=14)
        return {
            "ok": True,
            "organiser": _format_organiser_summary(org, all_emails, db),
        }

    @router.delete("/{id_or_slug}")
    def delete_organiser(
        id_or_slug: str,
        request: Request,
        db: Session = Depends(get_db),
    ):
        """Delete an organiser."""
        owner = require_user(request)
        org = db.query(WorkOrganiser).filter(
            or_(WorkOrganiser.id == id_or_slug, WorkOrganiser.slug == id_or_slug),
            or_(WorkOrganiser.owner == owner, WorkOrganiser.owner == None),
        ).first()

        if not org:
            raise HTTPException(404, f"Work organiser '{id_or_slug}' not found")

        db.delete(org)
        db.commit()
        return {"ok": True, "deleted_id": org.id, "slug": org.slug}

    @router.post("/seed-defaults")
    def seed_default_organisers(
        request: Request,
        force: bool = Query(False),
        db: Session = Depends(get_db),
    ):
        """Seed or reset empirical default categories for the user."""
        owner = require_user(request)
        if force:
            db.query(WorkOrganiser).filter(WorkOrganiser.owner == owner).delete()
            db.commit()

        existing_slugs = {
            o.slug for o in db.query(WorkOrganiser).filter(WorkOrganiser.owner == owner).all()
        }

        seeded = []
        for item in DEFAULT_ORGANISERS:
            if item["slug"] in existing_slugs:
                continue
            new_org = WorkOrganiser(
                id=uuid.uuid4().hex,
                owner=owner,
                name=item["name"],
                slug=item["slug"],
                category_group=item["category_group"],
                icon=item["icon"],
                color=item["color"],
                priority=item["priority"],
                target_accounts=json.dumps(item["target_accounts"]),
                rules_json=json.dumps(item["rules"]),
                ai_instructions=item["ai_instructions"],
                memory_lane=item.get("memory_lane"),
                sort_order=item["sort_order"],
                is_active=True,
            )
            db.add(new_org)
            seeded.append(item["name"])

        db.commit()
        all_emails = _get_recent_emails(days=14)
        organisers = db.query(WorkOrganiser).filter(WorkOrganiser.owner == owner).order_by(WorkOrganiser.sort_order.asc()).all()

        return {
            "ok": True,
            "seeded": seeded,
            "total": len(organisers),
            "organisers": [_format_organiser_summary(o, all_emails, db) for o in organisers],
        }

    @router.post("/preview-matches")
    def preview_matches(
        payload: PreviewRulesRequest,
        request: Request,
    ):
        """Test candidate rules against live indexed emails without saving."""
        require_user(request)
        all_emails = _get_recent_emails(days=payload.days)
        rules_dict = payload.rules.dict()

        matched = [
            {
                "id": f"{e.get('account_key')}:{e.get('uid')}",
                "uid": str(e.get("uid")),
                "account_id": e.get("account_key"),
                "folder": e.get("folder", "INBOX"),
                "sender_name": e.get("from_name") or e.get("from_address") or "Unknown",
                "sender_email": e.get("from_address") or "",
                "subject": e.get("subject") or "(No subject)",
                "date_iso": e.get("date_iso"),
                "date_display": e.get("date_display"),
            }
            for e in all_emails if _matches_rule(e, payload.target_accounts, rules_dict)
        ]

        return {
            "ok": True,
            "total_matches": len(matched),
            "preview_emails": matched[:payload.limit],
        }

    return router
