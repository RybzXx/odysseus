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
    EmailOrganiserOverride,
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


class ReassignEmailRequest(BaseModel):
    """One human correction to an email's organiser.

    Exactly one of organiser_id / excluded_from_id is set: the first files the
    message under an organiser, the second removes it from one whose rules keep
    claiming it.
    """
    account_key: str = ""
    uid: str
    organiser_id: Optional[str] = None
    excluded_from_id: Optional[str] = None


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

    # Recipients count too, but only for mail the user sent. On a received
    # message the sender is the correspondent and the recipient is the user, so
    # matching recipients there would make a rule naming someone also claim
    # every message addressed to them. On a sent message the relationship is
    # reversed: the correspondent is in To/Cc, and the sender is the user.
    is_outbound = str(email.get("folder") or "").lower().startswith(("sent", "inbox/sent", "[gmail]/sent"))
    recipients = ""
    if is_outbound:
        recipients = f"{email.get('to_text') or ''} {email.get('cc_text') or ''}".lower()

    # Senders Match
    for s in senders:
        if s in from_name or s in from_addr or (recipients and s in recipients):
            return True

    # Domains Match
    for d in domains:
        if f"@{d}" in from_addr or from_addr.endswith(f".{d}"):
            return True
        if recipients and f"@{d}" in recipients:
            return True

    # Keywords Match (in Subject or Snippet)
    for kw in keywords:
        if kw in subject or kw in body_snippet:
            return True

    return False


# How much cached body text a keyword rule may search. Enough to carry the
# substance of a message without loading whole threads into memory for every
# organiser on every request.
_SNIPPET_CHARS = 2000


def _get_recent_emails(days: int = 14) -> List[Dict[str, Any]]:
    """Retrieve raw email rows from SCHEDULED_EMAILS_DB, with body text where cached.

    Pre:  none.
    Post: each row carries the indexed header fields, plus ``snippet`` holding
          up to _SNIPPET_CHARS of body text when the preview cache has it and
          "" when it does not. Never raises: an unreadable store yields [].
    Inv:  the snippet is read, never fetched. Bodies reach the preview cache
          through the email module's own background warming; matching does not
          open IMAP connections of its own.

    Keyword rules search this. Before the join they searched a ``snippet`` key
    that nothing ever set, so every keyword rule silently matched on the subject
    line alone.
    """
    db_file = Path(SCHEDULED_EMAILS_DB)
    if not db_file.exists():
        return []

    cutoff_ts = time.time() - (days * 86400)
    try:
        conn = sqlite3.connect(str(db_file), timeout=5.0)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        rows = cur.execute("""
            SELECT i.account_key, i.folder, i.uid, i.message_id, i.subject,
                   i.from_name, i.from_address, i.to_text, i.cc_text,
                   i.date_iso, i.date_display, i.date_epoch, i.size, i.flags,
                   i.has_attachments,
                   substr(json_extract(p.payload_json, '$.body'), 1, ?) AS snippet
            FROM email_message_index AS i
            LEFT JOIN email_body_preview_cache AS p
                   ON p.owner = i.owner
                  AND p.account_key = i.account_key
                  AND p.folder = i.folder
                  AND p.uid = i.uid
            WHERE i.date_epoch >= ?
            ORDER BY i.date_epoch DESC
        """, (_SNIPPET_CHARS, cutoff_ts)).fetchall()
        emails = [dict(r) for r in rows]
        for email in emails:
            email["snippet"] = email.get("snippet") or ""
        conn.close()
        return emails
    except sqlite3.OperationalError as e:
        # json_extract needs SQLite's JSON1 extension, and the preview cache
        # postdates some databases. Fall back to headers alone rather than
        # leaving the organisers panel empty — keyword rules then match on the
        # subject, which is what they did before the join existed.
        logger.debug("Body-text join unavailable, using headers only: %s", e)
        try:
            rows = cur.execute("""
                SELECT account_key, folder, uid, message_id, subject, from_name,
                       from_address, to_text, cc_text, date_iso, date_display,
                       date_epoch, size, flags, has_attachments
                FROM email_message_index
                WHERE date_epoch >= ?
                ORDER BY date_epoch DESC
            """, (cutoff_ts,)).fetchall()
            emails = [{**dict(r), "snippet": ""} for r in rows]
            conn.close()
            return emails
        except Exception:
            logger.debug("Failed querying scheduled_emails.db for organisers", exc_info=True)
            return []
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


def email_key(email: Dict[str, Any]) -> tuple[str, str]:
    """The (account, uid) pair that identifies one indexed message.

    Overrides are stored against this pair because it is what
    ``email_message_index`` keys on and what the UI can pass back. Message-ids
    are absent on some indexed rows, so they cannot serve as the identity.
    """
    account = str(email.get("account_key") or email.get("account_id") or "")
    return account, str(email.get("uid") or "")


def load_organiser_overrides(db: Session, owner: Optional[str]) -> Dict[tuple[str, str], Dict[str, Any]]:
    """Every human correction this owner has made, indexed by message.

    Pre:  db is an open session.
    Post: {(account_key, uid): {"assigned": org_id|None, "excluded": {org_id}}}.
          Loaded once per request rather than queried per email -- the caller
          iterates hundreds of messages against a handful of organisers.
    """
    overrides: Dict[tuple[str, str], Dict[str, Any]] = {}
    try:
        rows = db.query(EmailOrganiserOverride).filter(
            or_(EmailOrganiserOverride.owner == owner, EmailOrganiserOverride.owner == None),
        ).all()
    except Exception:
        # The table postdates some databases; absent it, rules alone decide.
        return overrides

    for row in rows:
        entry = overrides.setdefault(
            (row.account_key or "", row.uid or ""), {"assigned": None, "excluded": set()}
        )
        if row.excluded_from_id:
            entry["excluded"].add(row.excluded_from_id)
        elif row.organiser_id:
            entry["assigned"] = row.organiser_id
    return overrides


def email_belongs_to_organiser(
    email: Dict[str, Any],
    org,
    accounts_list: List[str],
    rules: Dict[str, Any],
    overrides: Dict[tuple[str, str], Dict[str, Any]],
) -> bool:
    """Whether one email belongs to one organiser, overrides included.

    Precedence: an explicit assignment wins outright, then an explicit
    exclusion, then the rules. A human correction therefore survives any later
    edit to the rules -- which is the whole point of recording it.

    Pre:  rules and accounts_list come from the same organiser as `org`;
          overrides is the map from load_organiser_overrides.
    Post: True iff this email should appear under this organiser.
    Inv:  the only definition of email membership. The HTTP route, the MCP
          server and the overview payload all call it, so they cannot answer
          the same question differently.
    """
    entry = overrides.get(email_key(email))
    if entry:
        if entry["assigned"]:
            return entry["assigned"] == org.id
        if org.id in entry["excluded"]:
            return False
    return _matches_rule(email, accounts_list, rules)


def organiser_lane(org) -> str:
    """The memory category this organiser owns.

    Every memory written *for* an organiser carries this as its category, which
    is what makes the lane fill up over time. Seeded organisers already store a
    namespaced ``memory_lane``; one created without it falls back to its slug,
    so the lane is always well-defined rather than sometimes absent.

    Pre:  org is a WorkOrganiser with a slug.
    Post: a non-empty category string, stable for the life of the organiser.
    """
    lane = (getattr(org, "memory_lane", None) or "").strip()
    return lane or f"organisers:{(org.slug or '').strip().lower()}"


def _memory_matches_organiser(memory: Dict[str, Any], org, rules: Dict[str, Any]) -> bool:
    """Whether a general memory is worth showing beside this organiser.

    General memories carry categories like ``fact`` and ``preference`` and were
    never written with an organiser in mind, so they are matched on the
    organiser's own sender/keyword/domain vocabulary -- the same words the user
    already maintains for email. That keeps the reason a memory appears visible
    and editable, rather than hidden behind a similarity score.
    """
    text = (memory.get("text") or "").lower()
    if not text:
        return False

    if (org.slug or "").lower() in text:
        return True

    terms = [
        str(t).strip().lower().lstrip("@")
        for group in ("senders", "keywords", "domains")
        for t in (rules.get(group) or [])
    ]
    # A one- or two-character rule term would match almost any text; requiring
    # three keeps a stray rule from dragging every memory into every organiser.
    return any(term in text for term in terms if len(term) > 2)


def organiser_memory_sections(org, owner, limit: int = 20) -> Dict[str, List[Dict[str, Any]]]:
    """The organiser's own memories, and the general ones worth showing with them.

    Two sections, because they are two different things: ``lane`` holds what was
    recorded *for* this organiser, ``referenced`` holds pre-existing general
    memories the organiser's rules select. Keeping them apart is what lets the
    lane fill up without pretending the general pool belongs to any one lane.

    Pre:  org is a persisted WorkOrganiser; owner is the caller's username, or
          None for an unscoped read.
    Post: {"lane": [...], "referenced": [...]}, each at most `limit` entries the
          caller owns, disjoint from one another. Never raises: an unreadable
          store yields empty sections.
    Inv:  this is the only definition of organiser membership for memories.
          The badge count and the tab both derive from it, so they cannot
          disagree -- they previously used different scoping and different
          predicates, and did.

    Shared with mcp_servers/organisers_server.py so the MCP tool and the HTTP
    route cannot drift into answering the same question differently.
    """
    empty: Dict[str, List[Dict[str, Any]]] = {"lane": [], "referenced": []}
    mem_mgr = _get_memory_manager()
    if not mem_mgr or not org.slug:
        return empty

    def _view(memory: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": memory.get("id"),
            "content": memory.get("text"),
            "category": memory.get("category"),
            "timestamp": memory.get("timestamp"),
        }

    try:
        # Scope to the caller. load_all() is unfiltered and returned every
        # user's memories on a multi-user deploy.
        own_mems = mem_mgr.load(owner) if owner else mem_mgr.load_all()
    except Exception:
        return empty

    try:
        rules = json.loads(org.rules_json) if org.rules_json else {}
    except Exception:
        rules = {}

    lane_category = organiser_lane(org)
    lane, referenced = [], []
    for memory in own_mems:
        if memory.get("category") == lane_category:
            lane.append(_view(memory))
        elif _memory_matches_organiser(memory, org, rules):
            referenced.append(_view(memory))

    return {"lane": lane[:limit], "referenced": referenced[:limit]}


def count_organiser_memories(org, owner) -> int:
    """How many memories the organiser's tab will show.

    Derived from organiser_memory_sections so the card badge and the tab are
    the same number by construction.
    """
    sections = organiser_memory_sections(org, owner)
    return len(sections["lane"]) + len(sections["referenced"])


def _format_organiser_summary(
    org: WorkOrganiser,
    all_emails: List[Dict[str, Any]],
    db: Session,
    owner: Optional[str] = None,
) -> Dict[str, Any]:
    """Compile complete metadata and stats for an organiser.

    Pre:  owner is the caller's username. It is optional only so existing
          callers keep working; passing None widens the memory count to
          every user's memories, which is why every route here passes it.
    """
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

    # Email match count, human corrections included. Counting raw rule hits
    # here while the tab listed corrected membership would put a different
    # number on the card than in the list.
    overrides = load_organiser_overrides(db, owner)
    matching_emails = [
        e for e in all_emails
        if email_belongs_to_organiser(e, org, accounts_list, rules_dict, overrides)
    ]
    match_count = len(matching_emails)

    # Calculate linked tasks count
    tasks_count = 0
    if project_ids:
        tasks_count = db.query(ProjectTask).filter(
            ProjectTask.project_id.in_(project_ids),
            ProjectTask.completed == False,
        ).count()

    # Linked memories: the same count the Memories tab will show, from the same
    # predicate. This used to load every user's memories and match on
    # category_group, while the tab loaded the caller's and matched on the lane
    # — so the badge and the tab reported different numbers for one organiser.
    memory_count = count_organiser_memories(org, owner)

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

        results = [_format_organiser_summary(o, all_emails, db, owner) for o in organisers]
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
        summary = _format_organiser_summary(org, all_emails, db, owner)
        detail_overrides = load_organiser_overrides(db, owner)

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
            for e in all_emails
            if email_belongs_to_organiser(e, org, accounts_list, rules_dict, detail_overrides)
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
        # is no separate lane field, so `category` is what the lane binds to.
        #
        # Two sections, not one. The lane holds what was recorded for this
        # organiser; "referenced" holds pre-existing general memories its rules
        # select. Before this split the tab matched on category_group and the
        # lane together, and since no memory carried either, it was empty for
        # every organiser despite the store having entries.
        memory_sections = organiser_memory_sections(org, owner)

        return {
            "ok": True,
            "organiser": summary,
            "matching_emails": matched_emails,
            "tasks": tasks_list,
            "memories": memory_sections["lane"],
            "referenced_memories": memory_sections["referenced"],
            "memory_lane": organiser_lane(org),
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
            "organiser": _format_organiser_summary(new_org, all_emails, db, owner),
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
            "organiser": _format_organiser_summary(org, all_emails, db, owner),
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
            "organisers": [_format_organiser_summary(o, all_emails, db, owner) for o in organisers],
        }

    @router.post("/reassign-email")
    def reassign_email(
        payload: ReassignEmailRequest,
        request: Request,
        db: Session = Depends(get_db),
    ):
        """File one email under an organiser by hand, or remove it from one.

        Pre:  account_key and uid identify a message; exactly one of
              organiser_id (file here) or excluded_from_id (remove from here).
        Post: the correction is stored and outranks the rules from here on. A
              second correction for the same message replaces the first rather
              than stacking, so a message has one filed home at a time.
        """
        owner = require_user(request)

        if bool(payload.organiser_id) == bool(payload.excluded_from_id):
            raise HTTPException(
                400,
                "Pass exactly one of organiser_id (to file) or excluded_from_id (to remove).",
            )

        target_id = payload.organiser_id or payload.excluded_from_id
        target = db.query(WorkOrganiser).filter(
            WorkOrganiser.id == target_id,
            or_(WorkOrganiser.owner == owner, WorkOrganiser.owner == None),
        ).first()
        if not target:
            raise HTTPException(404, f"Work organiser '{target_id}' not found")

        account_key = (payload.account_key or "").strip()
        uid = (payload.uid or "").strip()
        if not uid:
            raise HTTPException(400, "uid is required to identify the message")

        # An assignment supersedes any previous assignment for this message; an
        # exclusion is per-organiser, so it replaces only its own row.
        existing = db.query(EmailOrganiserOverride).filter(
            EmailOrganiserOverride.owner == owner,
            EmailOrganiserOverride.account_key == account_key,
            EmailOrganiserOverride.uid == uid,
            EmailOrganiserOverride.excluded_from_id == payload.excluded_from_id,
        ).first()

        if existing:
            existing.organiser_id = payload.organiser_id
            existing.updated_at = utcnow_naive()
        else:
            db.add(EmailOrganiserOverride(
                id=uuid.uuid4().hex,
                owner=owner,
                account_key=account_key,
                uid=uid,
                organiser_id=payload.organiser_id,
                excluded_from_id=payload.excluded_from_id,
            ))
        db.commit()

        all_emails = _get_recent_emails(days=14)
        return {
            "ok": True,
            "filed_under": payload.organiser_id,
            "removed_from": payload.excluded_from_id,
            "organiser": _format_organiser_summary(target, all_emails, db, owner),
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
