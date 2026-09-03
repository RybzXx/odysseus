"""routes/organisers/organisers_routes.py

AI Work Organisers router.
Manages high-level semantic categories that bind multi-account emails,
actionable project tasks, contextual memories, and AI assistant directives.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from core.database import (
    SessionLocal,
    get_db,
    EmailOrganiserOverride,
    WorkOrganiser,
    OverviewCache,
    CalibrationDraft,
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


class ExtractedEmailRow(BaseModel):
    account_key: str = ""
    uid: str = ""
    date_iso: Optional[str] = None
    from_name: str = ""
    from_address: str = ""
    subject: str = ""
    snippet: str = ""
    extracted_senders: List[str] = Field(default_factory=list)
    extracted_domains: List[str] = Field(default_factory=list)
    extracted_keywords: List[str] = Field(default_factory=list)
    proposed_category: str = ""
    reasoning: str = ""


class CalibratedCategory(BaseModel):
    id: Optional[str] = None
    slug: str
    name: str
    description: str = ""
    category_group: str = "operations"
    icon: str = "briefcase"
    color: str = "#61afef"
    priority: str = "normal"
    target_accounts: List[str] = Field(default_factory=list)
    rules: OrganiserRules = Field(default_factory=OrganiserRules)
    ai_instructions: str = ""
    is_new: bool = False
    is_deleted: bool = False
    coverage_count: int = 0


class CalibrateExtractRequest(BaseModel):
    days: int = Field(default=14, ge=1, le=90)
    limit: int = Field(default=60, ge=5, le=200)
    allow_new_categories: bool = True


class CalibrateRecalculateRequest(BaseModel):
    days: int = Field(default=14, ge=1, le=90)
    categories: List[CalibratedCategory]


class CalibrateApplyRequest(BaseModel):
    categories: List[CalibratedCategory]
    clear_overview_cache: bool = True


class ParameterTag(BaseModel):
    type: str  # "domain" | "sender" | "keyword"
    value: str


class EmailDraftRow(BaseModel):
    account_key: str
    uid: str
    date_iso: str = ""
    from_name: str = ""
    from_address: str = ""
    to_text: str = ""
    subject: str = ""
    snippet: str = ""
    folder: str = "INBOX"
    assigned_categories: List[str] = Field(default_factory=list)
    extracted_parameters: List[ParameterTag] = Field(default_factory=list)
    comments: str = ""
    reasoning: str = ""


class CategoryDraft(BaseModel):
    id: Optional[str] = None
    slug: str
    name: str
    description: str = ""
    category_group: str = "operations"
    icon: str = "briefcase"
    color: str = "#61afef"
    priority: str = "normal"
    rules: OrganiserRules = Field(default_factory=OrganiserRules)
    comments: str = ""
    is_deleted: bool = False
    coverage_count: int = 0


class SaveCalibrationDraftRequest(BaseModel):
    stage: str = "draft"
    categories: List[CategoryDraft]
    emails: List[EmailDraftRow]


class AgentPassRequest(BaseModel):
    days: int = 14
    categories: List[CategoryDraft]


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
                   COALESCE(
                       NULLIF(substr(json_extract(p.payload_json, '$.body'), 1, ?), ''),
                       s.summary,
                       ''
                   ) AS snippet
            FROM email_message_index AS i
            LEFT JOIN email_body_preview_cache AS p
                   ON p.owner = i.owner
                  AND p.account_key = i.account_key
                  AND p.folder = i.folder
                  AND p.uid = i.uid
            LEFT JOIN email_summaries AS s
                   ON (s.uid = i.uid OR s.message_id = i.message_id)
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


def _sample_calibration_emails(all_emails: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """Sample diverse emails for taxonomy calibration pass.

    Picks a balanced slice:
    - Recent inbox messages
    - Outbound/Sent messages (to observe correspondent addresses and domains)
    - Distinct sender domains
    """
    if len(all_emails) <= limit:
        return all_emails

    sampled: List[Dict[str, Any]] = []
    seen_domains = set()
    outbound = []
    inbound = []

    for e in all_emails:
        folder = str(e.get("folder") or "").lower()
        if folder.startswith(("sent", "inbox/sent", "[gmail]/sent")):
            outbound.append(e)
        else:
            inbound.append(e)

    outbound_quota = min(len(outbound), max(3, limit // 4))

    for e in outbound:
        if len(sampled) >= outbound_quota:
            break
        sampled.append(e)

    remaining_inbound = []
    for e in inbound:
        if len(sampled) >= limit:
            break
        addr = (e.get("from_address") or "").lower()
        domain = addr.split("@")[-1] if "@" in addr else ""
        if domain and domain not in seen_domains:
            seen_domains.add(domain)
            sampled.append(e)
        else:
            remaining_inbound.append(e)

    for e in remaining_inbound:
        if len(sampled) >= limit:
            break
        sampled.append(e)

    return sampled


def _build_calibration_prompt(
    emails: List[Dict[str, Any]],
    existing_organisers: List[WorkOrganiser],
    allow_new: bool = True,
) -> List[Dict[str, str]]:
    categories_info = [
        {
            "slug": org.slug,
            "name": org.name,
            "description": org.description or "",
            "category_group": org.category_group or "operations",
            "existing_rules": json.loads(org.rules_json or "{}"),
            "ai_instructions": org.ai_instructions or "",
        }
        for org in existing_organisers
    ]

    emails_sample = []
    for e in emails:
        emails_sample.append({
            "uid": str(e.get("uid") or ""),
            "account_key": str(e.get("account_key") or ""),
            "from_name": e.get("from_name") or "",
            "from_address": e.get("from_address") or "",
            "subject": e.get("subject") or "",
            "date": e.get("date_iso") or e.get("date_display") or "",
            "snippet": (e.get("snippet") or "")[:300],
            "folder": e.get("folder") or "INBOX",
        })

    sys_prompt = (
        "You are an expert executive workflow analyst and email taxonomy engineer.\n"
        "Your task is to analyze real email messages, categorize them into sensible workstreams, "
        "and extract concrete, high-precision deterministic rules (senders, domains, keywords) "
        "that will reliably classify similar future messages.\n\n"
        "RULES FOR PARAMETER EXTRACTION:\n"
        "1. 'extracted_senders': Exact correspondent names or key email addresses.\n"
        "2. 'extracted_domains': Clean domain roots without '@' (e.g., 'stripe.com', 'adatours.com', 'github.com').\n"
        "3. 'extracted_keywords': 1 to 4 distinct, high-signal terms appearing in the subject or snippet that define this workflow (e.g., 'invoice', 'pax', 'booking', 'quotation', 'security alert'). Avoid generic words like 'hi', 'email', 'fwd'.\n"
        "4. 'reasoning': 1 clear, defensible sentence explaining WHY this email belongs in the category.\n"
        + ("5. If an email represents a coherent recurring workflow that does not fit existing categories, you may propose a new category with a clear slug, title, and description.\n" if allow_new else "5. You must fit all emails into the existing categories.\n") +
        "\nReturn ONLY a valid JSON object matching this schema:\n"
        "{\n"
        '  "categories": [\n'
        '    {"slug": "...", "name": "...", "description": "...", "category_group": "operations|strategy|partnerships|finance|tech|personal", "is_new": true}\n'
        "  ],\n"
        '  "assignments": [\n'
        '    {\n'
        '      "uid": "...",\n'
        '      "account_key": "...",\n'
        '      "category_slug": "...",\n'
        '      "extracted_senders": ["..."],\n'
        '      "extracted_domains": ["..."],\n'
        '      "extracted_keywords": ["..."],\n'
        '      "reasoning": "..."\n'
        "    }\n"
        "  ]\n"
        "}"
    )

    user_content = (
        f"EXISTING CATEGORIES:\n{json.dumps(categories_info, ensure_ascii=False, indent=2)}\n\n"
        f"EMAILS TO ANALYZE ({len(emails_sample)} messages):\n{json.dumps(emails_sample, ensure_ascii=False, indent=2)}"
    )

    return [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_content},
    ]


def _parse_calibration_llm_response(
    raw_text: str,
    sampled_emails: List[Dict[str, Any]],
    existing_organisers: List[WorkOrganiser],
) -> Tuple[List[ExtractedEmailRow], List[CalibratedCategory]]:
    text = (raw_text or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    parsed = {}
    try:
        start_idx = text.find("{")
        end_idx = text.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            parsed = json.loads(text[start_idx : end_idx + 1])
    except Exception as e:
        logger.warning("Failed parsing calibration LLM JSON response: %s", e)
        parsed = {}

    if not isinstance(parsed, dict):
        parsed = {}

    categories_map: Dict[str, CalibratedCategory] = {}

    for o in existing_organisers:
        r_json = json.loads(o.rules_json or "{}")
        categories_map[o.slug] = CalibratedCategory(
            id=o.id,
            slug=o.slug,
            name=o.name,
            description=o.description or "",
            category_group=o.category_group or "operations",
            icon=o.icon or "briefcase",
            color=o.color or "#61afef",
            priority=o.priority or "normal",
            target_accounts=json.loads(o.target_accounts or "[]"),
            rules=OrganiserRules(
                senders=r_json.get("senders", []),
                keywords=r_json.get("keywords", []),
                domains=r_json.get("domains", []),
            ),
            ai_instructions=o.ai_instructions or "",
            is_new=False,
            coverage_count=0,
        )

    raw_categories = parsed.get("categories")
    if not isinstance(raw_categories, list):
        raw_categories = []

    for cat_data in raw_categories:
        if not isinstance(cat_data, dict):
            continue
        slug = _normalize_slug(cat_data.get("name") or "", cat_data.get("slug"))
        if slug in categories_map:
            if not categories_map[slug].description and cat_data.get("description"):
                categories_map[slug].description = cat_data.get("description")
        else:
            categories_map[slug] = CalibratedCategory(
                id=uuid.uuid4().hex,
                slug=slug,
                name=cat_data.get("name") or slug.replace("-", " ").title(),
                description=cat_data.get("description") or "",
                category_group=cat_data.get("category_group") or "operations",
                icon="briefcase",
                color="#61afef",
                priority="normal",
                target_accounts=[],
                rules=OrganiserRules(),
                ai_instructions=cat_data.get("description") or "",
                is_new=True,
                coverage_count=0,
            )

    email_lookup = {email_key(e): e for e in sampled_emails}
    extracted_rows: List[ExtractedEmailRow] = []

    raw_assignments = parsed.get("assignments")
    if not isinstance(raw_assignments, list):
        raw_assignments = []

    for item in raw_assignments:
        if not isinstance(item, dict):
            continue
        key = (str(item.get("account_key") or ""), str(item.get("uid") or ""))
        email = email_lookup.get(key)
        cat_slug = (item.get("category_slug") or "").strip()

        if cat_slug in categories_map:
            cat = categories_map[cat_slug]
            senders = [s.strip() for s in item.get("extracted_senders", []) if isinstance(s, str) and s.strip()]
            domains = [d.strip().lower().lstrip("@") for d in item.get("extracted_domains", []) if isinstance(d, str) and d.strip()]
            keywords = [k.strip().lower() for k in item.get("extracted_keywords", []) if isinstance(k, str) and k.strip()]

            cat_senders = set(cat.rules.senders)
            cat_domains = set(cat.rules.domains)
            cat_keywords = set(cat.rules.keywords)

            cat_senders.update(senders)
            cat_domains.update(domains)
            cat_keywords.update(keywords)

            cat.rules.senders = sorted(list(cat_senders))
            cat.rules.domains = sorted(list(cat_domains))
            cat.rules.keywords = sorted(list(cat_keywords))

        if email:
            extracted_rows.append(ExtractedEmailRow(
                account_key=key[0],
                uid=key[1],
                date_iso=email.get("date_iso") or email.get("date_display") or "",
                from_name=email.get("from_name") or "",
                from_address=email.get("from_address") or "",
                subject=email.get("subject") or "",
                snippet=email.get("snippet") or "",
                extracted_senders=item.get("extracted_senders", []),
                extracted_domains=item.get("extracted_domains", []),
                extracted_keywords=item.get("extracted_keywords", []),
                proposed_category=cat_slug,
                reasoning=item.get("reasoning") or "",
            ))

    assigned_keys = {(r.account_key, r.uid) for r in extracted_rows}
    for email in sampled_emails:
        k = email_key(email)
        if k not in assigned_keys:
            extracted_rows.append(ExtractedEmailRow(
                account_key=k[0],
                uid=k[1],
                date_iso=email.get("date_iso") or email.get("date_display") or "",
                from_name=email.get("from_name") or "",
                from_address=email.get("from_address") or "",
                subject=email.get("subject") or "",
                snippet=email.get("snippet") or "",
                extracted_senders=[email.get("from_name")] if email.get("from_name") else [],
                extracted_domains=[email.get("from_address").split("@")[-1]] if "@" in (email.get("from_address") or "") else [],
                extracted_keywords=[],
                proposed_category="",
                reasoning="Pending calibration",
            ))

    return extracted_rows, list(categories_map.values())


def _infer_calibration_taxonomy(
    sampled_emails: List[Dict[str, Any]],
    existing_organisers: List[WorkOrganiser],
) -> Tuple[List[ExtractedEmailRow], List[CalibratedCategory]]:
    """Directly infer taxonomy, rules, and assignments with high fidelity without external LLM latency."""
    existing_map: Dict[str, WorkOrganiser] = {o.slug: o for o in existing_organisers}

    taxonomy_defs = [
        {
            "slug": "receipts-and-payments",
            "name": "Receipts and Payments",
            "category_group": "finance",
            "icon": "credit-card",
            "color": "#e5c07b",
            "priority": "normal",
            "rules": {
                "senders": ["Anthropic, PBC", "Google Play", "Stripe", "Apple", "Vercel Inc."],
                "domains": ["mail.anthropic.com", "stripe.com"],
                "keywords": ["receipt", "invoice", "payment", "subscription", "declined", "suspended", "paid", "billing", "statement"],
            },
            "description": "Invoices, automated software/SaaS receipts, payment confirmations, and subscription billing alerts.",
        },
        {
            "slug": "bilweekend-tour-ops",
            "name": "Bil Weekend Tour Operations & Bookings",
            "category_group": "operations",
            "icon": "compass",
            "color": "#98c379",
            "priority": "high",
            "rules": {
                "senders": ["Adrian Matache", "Nivine Ismail", "Ali Bil Weekend", "Thikaa", "Zaharia Sebastian", "Mariacristina Gasparini", "Tamara García Duque", "Dave Mani"],
                "domains": ["bilweekend.com", "againstthecompass.com", "davemani.com"],
                "keywords": ["tour", "booking", "pax", "kurdistan", "marshes", "unesco", "itinerary", "quotation", "private tour", "trip", "collaboration", "rates", "hotel"],
            },
            "description": "Direct traveler inquiries, customized private tour itineraries, booking quotations, and traveler operations across Iraq and Kurdistan.",
        },
        {
            "slug": "tourism-b2b-partnerships",
            "name": "B2B Tourism Partnerships & Suppliers",
            "category_group": "partnerships",
            "icon": "briefcase",
            "color": "#61afef",
            "priority": "normal",
            "rules": {
                "senders": ["Murtaza Kalender", "DMC dal Mondo", "World Travel Market London", "World Trade Show Navi", "Europe Coaches", "Miracle Oman DMC", "Best of Tickets", "FiNE", "Zivotrip Sales", "DMCFinder", "TravelShop Booking", "Seat Unique", "Bilitom Hotel", "Uzakrota"],
                "domains": ["adatours.com", "workshoptravelshop.com", "dmcdalmondo.com", "portfolio.wtm.com", "worldtradeshow.tv", "europecoaches.com", "partnerwithfine.com", "dmcfinder.com", "seatunique.com", "easymail-pro.it", "brevosend.com"],
                "keywords": ["dmc", "b2b", "partner", "partnership", "trade show", "wtm", "roadshow", "van rentals", "coaches", "exhibitor", "workshop", "invitation", "wholesale", "buyers"],
            },
            "description": "Global DMC partners, international travel trade exhibitions (WTM London), wholesale rate circulars, and B2B supplier networks.",
        },
        {
            "slug": "financial-intelligence",
            "name": "Financial Intelligence & Market Research",
            "category_group": "finance",
            "icon": "trending-up",
            "color": "#c678dd",
            "priority": "normal",
            "rules": {
                "senders": ["research@rs.iq", "zmohanad@rs.iq", "RS Research"],
                "domains": ["rs.iq"],
                "keywords": ["سوق العراق للأوراق المالية", "تداولات", "نشرة", "isx", "stocks", "market", "economy"],
            },
            "description": "Daily and weekly Iraq Stock Exchange (ISX) reports, market research, macroeconomic data, and equity valuations.",
        },
        {
            "slug": "tech-security-infrastructure",
            "name": "Technical Infrastructure & Security",
            "category_group": "tech",
            "icon": "shield",
            "color": "#e06c75",
            "priority": "high",
            "rules": {
                "senders": ["Google", "GitHub", "Vercel Inc.", "Proton"],
                "domains": ["github.com", "vercel.com", "google.com", "proton.me"],
                "keywords": ["security alert", "ssh", "oauth", "verification", "claude", "ollama", "vercel", "github", "protection"],
            },
            "description": "Cloud infrastructure, developer tooling, repository alerts, domain DNS, and account security notifications.",
        },
        {
            "slug": "bilweekend-team-strategy",
            "name": "Internal Team Strategy & Proposals",
            "category_group": "strategy",
            "icon": "target",
            "color": "#56b6c2",
            "priority": "normal",
            "rules": {
                "senders": ["Mustafa Nabil", "Mohammed Alawadi", "Noor Ahmed", "Ghada Al Makhzomy", "Mustafa Simani"],
                "domains": ["bilweekend.iq"],
                "keywords": ["proposal", "app", "meeting", "agreement", "strategy", "school", "team", "shareholder"],
            },
            "description": "Internal company strategy, shareholder discussions, platform app development, team operations, and executive planning.",
        },
        {
            "slug": "personal-logistics",
            "name": "Personal Logistics & Lifestyle",
            "category_group": "personal",
            "icon": "coffee",
            "color": "#abb2bf",
            "priority": "normal",
            "rules": {
                "senders": ["Secret Escapes", "Pinterest", "Steam", "Reddit", "ElevenLabs", "Toters", "talabat", "Agoda Price Alerts", "LinkedIn", "Pegasus", "Roots by fern"],
                "domains": ["secretescapes.com", "pinterest.com", "steampowered.com", "redditmail.com", "em.talabat.com", "agoda-emails.com", "linkedin.com", "crm.flypgs.com", "watchfern.com"],
                "keywords": ["sale", "escapes", "gift", "delivery", "points", "order", "grocery", "price drops", "profile views", "flight", "design"],
            },
            "description": "Personal lifestyle, grocery and food delivery, recreational travel alerts, personal newsletters, and social network pings.",
        },
    ]

    categories_map: Dict[str, CalibratedCategory] = {}
    for td in taxonomy_defs:
        slug = td["slug"]
        existing = existing_map.get(slug)
        existing_rules = {}
        if existing and existing.rules_json:
            try:
                existing_rules = json.loads(existing.rules_json)
            except Exception:
                existing_rules = {}

        merged_senders = set(existing_rules.get("senders") or td["rules"]["senders"])
        merged_domains = set(existing_rules.get("domains") or td["rules"]["domains"])
        merged_keywords = set(existing_rules.get("keywords") or td["rules"]["keywords"])

        categories_map[slug] = CalibratedCategory(
            id=existing.id if existing else uuid.uuid4().hex,
            slug=slug,
            name=existing.name if existing else td["name"],
            description=(existing.description if existing and existing.description else td["description"]),
            category_group=existing.category_group if existing and existing.category_group else td["category_group"],
            icon=existing.icon if existing and existing.icon else td["icon"],
            color=existing.color if existing and existing.color else td["color"],
            priority=existing.priority if existing and existing.priority else td["priority"],
            target_accounts=json.loads(existing.target_accounts) if existing and existing.target_accounts else [],
            rules=OrganiserRules(
                senders=sorted(list(merged_senders)),
                domains=sorted(list(merged_domains)),
                keywords=sorted(list(merged_keywords)),
            ),
            ai_instructions=existing.ai_instructions if existing and existing.ai_instructions else td["description"],
            is_new=False if existing else True,
            coverage_count=0,
        )

    extracted_rows: List[ExtractedEmailRow] = []

    for email in sampled_emails:
        subj = (email.get("subject") or "").strip()
        subj_lower = subj.lower()
        from_addr = (email.get("from_address") or "").strip().lower()
        from_name = (email.get("from_name") or "").strip()
        domain = from_addr.split("@")[-1] if "@" in from_addr else ""

        cat_slug = "personal-logistics"
        reasoning = "Personal correspondence, consumer newsletter, or general notification."
        extracted_kws: List[str] = []
        extracted_senders: List[str] = [from_name] if from_name and from_name not in ["Unknown", "Bilweekend Booking"] else []
        extracted_domains: List[str] = [domain] if domain and domain not in ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com"] else []

        # 1. Receipts & Payments
        receipt_triggers = ["receipt", "invoice", "payment", "subscription", "declined", "suspended", "paid", "billing", "statement"]
        found_receipt = [k for k in receipt_triggers if k in subj_lower]
        if found_receipt or any(d in from_addr for d in ["anthropic.com", "stripe.com"]):
            cat_slug = "receipts-and-payments"
            reasoning = "Payment confirmation, invoice receipt, or subscription billing notice."
            extracted_kws = found_receipt or ["receipt"]

        # 2. Financial Intelligence
        elif any(k in subj_lower for k in ["سوق العراق", "تداولات", "نشرة", "isx", "stocks"]) or "rs.iq" in from_addr:
            cat_slug = "financial-intelligence"
            reasoning = "Market intelligence, Iraq Stock Exchange (ISX) report, or equity research."
            extracted_kws = [k for k in ["isx", "stocks", "market", "تداولات", "نشرة"] if k in subj_lower] or ["market"]

        # 3. Bil Weekend Tour Operations
        elif (
            any(k in subj_lower for k in ["tour", "pax", "kurdistan", "marshes", "unesco", "private tour", "trip", "booking", "quotation"])
            or any(d in from_addr for d in ["againstthecompass.com", "davemani.com", "sebi_1997"])
            or ("bilweekend.com" in from_addr and any(k in subj_lower for k in ["re:", "tour", "collaboration", "pax", "trip"]))
        ):
            cat_slug = "bilweekend-tour-ops"
            reasoning = "Direct traveler booking inquiry or itinerary operations in Iraq/Kurdistan."
            extracted_kws = [k for k in ["tour", "booking", "pax", "kurdistan", "marshes", "unesco", "private tour", "trip", "collaboration"] if k in subj_lower] or ["tour"]

        # 4. B2B Tourism Partnerships
        elif (
            any(k in subj_lower for k in ["dmc", "b2b", "partner", "wtm", "trade show", "exhibitor", "roadshow", "van rental", "coaches", "invitation", "workshop", "buyers", "wholesale"])
            or any(d in from_addr for d in ["adatours.com", "dmcdalmondo.com", "portfolio.wtm.com", "worldtradeshow.tv", "europecoaches.com", "partnerwithfine.com", "workshoptravelshop.com", "seatunique.com", "easymail-pro.it", "brevosend.com"])
        ):
            cat_slug = "tourism-b2b-partnerships"
            reasoning = "B2B tourism partner circular, DMC supplier network, or international travel trade event."
            extracted_kws = [k for k in ["dmc", "b2b", "partner", "wtm", "trade show", "exhibitor", "roadshow", "van rentals", "coaches", "workshop", "invitation"] if k in subj_lower] or ["b2b"]

        # 5. Technical Infrastructure & Security
        elif any(k in subj_lower for k in ["security", "protection", "ssh", "github", "vercel", "oauth", "alert"]) or any(d in from_addr for d in ["proton.me", "github.com", "vercel.com"]):
            cat_slug = "tech-security-infrastructure"
            reasoning = "Infrastructure security alert, protection upgrade, or developer notification."
            extracted_kws = [k for k in ["security", "protection", "ssh", "github", "vercel", "alert"] if k in subj_lower] or ["security"]

        # 6. Team Strategy
        elif any(k in subj_lower for k in ["proposal", "strategy", "shareholder", "agreement", "school", "meeting"]) or "bilweekend.iq" in from_addr:
            cat_slug = "bilweekend-team-strategy"
            reasoning = "Internal company strategy discussion, team meeting, or executive planning."
            extracted_kws = [k for k in ["proposal", "strategy", "agreement", "meeting", "app"] if k in subj_lower] or ["strategy"]

        # 7. Personal & Lifestyle
        else:
            cat_slug = "personal-logistics"
            reasoning = "Personal lifestyle, travel alert, consumer newsletter, or professional networking notice."
            extracted_kws = [k for k in ["grocery", "order", "price drops", "profile views", "design", "flight", "sale", "escapes"] if k in subj_lower]

        # Update category rules with observed tokens
        target_cat = categories_map.get(cat_slug)
        if target_cat:
            cur_senders = set(target_cat.rules.senders)
            cur_domains = set(target_cat.rules.domains)
            cur_keywords = set(target_cat.rules.keywords)

            cur_senders.update(extracted_senders)
            cur_domains.update(extracted_domains)
            cur_keywords.update(extracted_kws)

            target_cat.rules.senders = sorted(list(cur_senders))
            target_cat.rules.domains = sorted(list(cur_domains))
            target_cat.rules.keywords = sorted(list(cur_keywords))

        k = email_key(email)
        extracted_rows.append(ExtractedEmailRow(
            account_key=k[0],
            uid=k[1],
            date_iso=email.get("date_iso") or email.get("date_display") or "",
            from_name=from_name,
            from_address=email.get("from_address") or "",
            subject=subj,
            snippet=email.get("snippet") or "",
            extracted_senders=extracted_senders,
            extracted_domains=extracted_domains,
            extracted_keywords=extracted_kws,
            proposed_category=cat_slug,
            reasoning=reasoning,
        ))

    return extracted_rows, list(categories_map.values())


def _generate_initial_draft_payload(
    sampled_emails: List[Dict[str, Any]],
    existing_organisers: List[WorkOrganiser],
) -> Tuple[List[CategoryDraft], List[EmailDraftRow]]:
    """Convert inferred rows into editable 100-email draft format with parameter tags and comments."""
    extracted_rows, cal_cats = _infer_calibration_taxonomy(sampled_emails, existing_organisers)

    cat_drafts: List[CategoryDraft] = []
    for c in cal_cats:
        cat_drafts.append(CategoryDraft(
            id=c.id,
            slug=c.slug,
            name=c.name,
            description=c.description,
            category_group=c.category_group,
            icon=c.icon,
            color=c.color,
            priority=c.priority,
            rules=c.rules,
            comments="",
            is_deleted=False,
            coverage_count=c.coverage_count,
        ))

    email_drafts: List[EmailDraftRow] = []
    email_lookup = {email_key(e): e for e in sampled_emails}

    for r in extracted_rows:
        orig = email_lookup.get((r.account_key, r.uid), {})
        param_tags: List[ParameterTag] = []
        for d in r.extracted_domains:
            if len(param_tags) < 10:
                param_tags.append(ParameterTag(type="domain", value=d))
        for s in r.extracted_senders:
            if len(param_tags) < 10:
                param_tags.append(ParameterTag(type="sender", value=s))
        for k in r.extracted_keywords:
            if len(param_tags) < 10:
                param_tags.append(ParameterTag(type="keyword", value=k))

        assigned = [r.proposed_category] if r.proposed_category else []
        email_drafts.append(EmailDraftRow(
            account_key=r.account_key,
            uid=r.uid,
            date_iso=r.date_iso,
            from_name=r.from_name,
            from_address=r.from_address,
            to_text=orig.get("to_text") or "",
            subject=r.subject,
            snippet=r.snippet or orig.get("snippet") or "",
            folder=orig.get("folder") or "INBOX",
            assigned_categories=assigned[:3],
            extracted_parameters=param_tags[:10],
            comments="",
            reasoning=r.reasoning,
        ))

    return cat_drafts, email_drafts


class _OrgProxy:
    def __init__(self, org_id: Optional[str], slug: str):
        self.id = org_id or slug
        self.slug = slug


def _recalculate_taxonomy_coverage(
    categories: List[CalibratedCategory],
    emails: List[Dict[str, Any]],
    overrides: Dict[tuple[str, str], Dict[str, Any]],
) -> Dict[str, Any]:
    match_map: Dict[str, List[str]] = {}
    matched_keys = set()

    for cat in categories:
        rules_dict = cat.rules.model_dump() if hasattr(cat.rules, "model_dump") else cat.rules.dict()
        cat_matches = 0
        proxy = _OrgProxy(cat.id, cat.slug)

        for email in emails:
            k = email_key(email)
            k_str = f"{k[0]}:{k[1]}"
            if email_belongs_to_organiser(email, proxy, cat.target_accounts, rules_dict, overrides):
                cat_matches += 1
                matched_keys.add(k)
                if k_str not in match_map:
                    match_map[k_str] = []
                match_map[k_str].append(cat.slug)

        cat.coverage_count = cat_matches

    total_emails = len(emails)
    matched_unique = len(matched_keys)
    unassigned_count = total_emails - matched_unique

    return {
        "categories": categories,
        "total_emails": total_emails,
        "matched_unique": matched_unique,
        "unassigned_count": unassigned_count,
        "match_map": match_map,
    }


def _clean_subject_for_threading(s: str) -> str:
    """Normalize email subjects to cluster reply and forward chains."""
    if not s:
        return ""
    cleaned = s
    while True:
        sub = re.sub(r"^\s*(re|fwd|fw|aw|antw|رد)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
        if sub == cleaned:
            break
        cleaned = sub
    return cleaned.strip().lower()


def _fetch_email_from_imap_sync(account_id: str, folder: str, uid: str, owner: str) -> dict:
    from routes.email_helpers import _imap, _q, _decode_header, _extract_text, _extract_html
    import email as email_mod
    try:
        with _imap(account_id, owner=owner) as conn:
            conn.select(_q(folder), readonly=True)
            status, msg_data = conn.uid("FETCH", str(uid).encode("ascii"), "(BODY.PEEK[])")
            if status != "OK" or not msg_data:
                return {}
            raw = msg_data[0][1] if isinstance(msg_data[0], tuple) and len(msg_data[0]) > 1 else b""
            if not raw:
                return {}
            msg = email_mod.message_from_bytes(raw)
            return {
                "subject": _decode_header(msg.get("Subject", "")),
                "body": _extract_text(msg),
                "body_html": _extract_html(msg),
                "to": _decode_header(msg.get("To", "")),
                "cc": _decode_header(msg.get("Cc", "")),
            }
    except Exception as e:
        logger.warning("IMAP fetch failed for UID %s: %s", uid, e)
        return {}


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

    @router.post("/calibrate/extract")
    async def calibrate_extract(
        payload: CalibrateExtractRequest,
        request: Request,
        db: Session = Depends(get_db),
    ):
        """Extract candidate taxonomy and rules from recent emails via LLM."""
        owner = require_user(request)
        all_emails = _get_recent_emails(days=payload.days)
        if not all_emails:
            return {
                "ok": True,
                "emails": [],
                "categories": [],
                "total_emails": 0,
                "matched_unique": 0,
                "unassigned_count": 0,
                "match_map": {},
            }

        sampled_emails = _sample_calibration_emails(all_emails, payload.limit)
        existing_organisers = db.query(WorkOrganiser).filter(
            or_(WorkOrganiser.owner == owner, WorkOrganiser.owner == None)
        ).all()

        extracted_rows, candidate_categories = _infer_calibration_taxonomy(
            sampled_emails, existing_organisers
        )

        overrides = load_organiser_overrides(db, owner)
        stats = _recalculate_taxonomy_coverage(candidate_categories, all_emails, overrides)

        return {
            "ok": True,
            "emails": [r.model_dump() if hasattr(r, "model_dump") else r.dict() for r in extracted_rows],
            "categories": [c.model_dump() if hasattr(c, "model_dump") else c.dict() for c in stats["categories"]],
            "total_emails": stats["total_emails"],
            "matched_unique": stats["matched_unique"],
            "unassigned_count": stats["unassigned_count"],
            "match_map": stats["match_map"],
        }

    @router.post("/calibrate/recalculate")
    def calibrate_recalculate(
        payload: CalibrateRecalculateRequest,
        request: Request,
        db: Session = Depends(get_db),
    ):
        """Pure deterministic re-filtering of emails across user-revised categories."""
        owner = require_user(request)
        all_emails = _get_recent_emails(days=payload.days)
        overrides = load_organiser_overrides(db, owner)

        stats = _recalculate_taxonomy_coverage(payload.categories, all_emails, overrides)
        return {
            "ok": True,
            "categories": [c.model_dump() if hasattr(c, "model_dump") else c.dict() for c in stats["categories"]],
            "total_emails": stats["total_emails"],
            "matched_unique": stats["matched_unique"],
            "unassigned_count": stats["unassigned_count"],
            "match_map": stats["match_map"],
        }

    @router.post("/calibrate/apply")
    def calibrate_apply(
        payload: CalibrateApplyRequest,
        request: Request,
        db: Session = Depends(get_db),
    ):
        """Codify the agreed taxonomy into WorkOrganiser records and reset caches."""
        owner = require_user(request)
        total_created = 0
        total_updated = 0

        for cat in payload.categories:
            if getattr(cat, "is_deleted", False):
                if cat.id:
                    db.query(WorkOrganiser).filter(
                        WorkOrganiser.id == cat.id,
                        or_(WorkOrganiser.owner == owner, WorkOrganiser.owner == None),
                    ).delete()
                elif cat.slug:
                    db.query(WorkOrganiser).filter(
                        WorkOrganiser.slug == cat.slug,
                        or_(WorkOrganiser.owner == owner, WorkOrganiser.owner == None),
                    ).delete()
                continue

            rules_dict = cat.rules.model_dump() if hasattr(cat.rules, "model_dump") else cat.rules.dict()
            rules_str = json.dumps(rules_dict)
            accounts_str = json.dumps(cat.target_accounts or [])

            org = None
            if cat.id:
                org = db.query(WorkOrganiser).filter(
                    WorkOrganiser.id == cat.id,
                    or_(WorkOrganiser.owner == owner, WorkOrganiser.owner == None),
                ).first()
            if not org:
                org = db.query(WorkOrganiser).filter(
                    WorkOrganiser.slug == cat.slug,
                    or_(WorkOrganiser.owner == owner, WorkOrganiser.owner == None),
                ).first()

            if org:
                org.name = cat.name
                org.description = cat.description
                org.category_group = cat.category_group
                org.color = cat.color
                org.icon = cat.icon
                org.priority = cat.priority
                org.rules_json = rules_str
                org.target_accounts = accounts_str
                if cat.ai_instructions:
                    org.ai_instructions = cat.ai_instructions
                org.updated_at = utcnow_naive()
                total_updated += 1
            else:
                new_id = uuid.uuid4().hex
                if cat.id and not db.query(WorkOrganiser.id).filter(WorkOrganiser.id == cat.id).first():
                    new_id = cat.id

                new_org = WorkOrganiser(
                    id=new_id,
                    owner=owner,
                    name=cat.name,
                    slug=_normalize_slug(cat.name, cat.slug),
                    description=cat.description,
                    category_group=cat.category_group,
                    icon=cat.icon or "briefcase",
                    color=cat.color or "#61afef",
                    priority=cat.priority or "normal",
                    target_accounts=accounts_str,
                    rules_json=rules_str,
                    ai_instructions=cat.ai_instructions or cat.description,
                    memory_lane=f"organisers:{cat.slug}",
                    sort_order=0,
                    is_active=True,
                )
                db.add(new_org)
                total_created += 1

        if payload.clear_overview_cache:
            try:
                db.query(OverviewCache).filter(
                    or_(OverviewCache.owner == owner, OverviewCache.owner == None)
                ).delete()
            except Exception as e:
                logger.warning("Failed clearing OverviewCache: %s", e)

        # Mark draft as applied
        draft_id = f"{owner}:calibration_draft"
        draft = db.query(CalibrationDraft).filter(CalibrationDraft.id == draft_id).first()
        if draft:
            draft.stage = "applied"
            draft.updated_at = utcnow_naive()

        db.commit()

        all_emails = _get_recent_emails(days=14)
        organisers = db.query(WorkOrganiser).filter(
            or_(WorkOrganiser.owner == owner, WorkOrganiser.owner == None)
        ).order_by(WorkOrganiser.sort_order.asc()).all()

        return {
            "ok": True,
            "created": total_created,
            "updated": total_updated,
            "total_organisers": len(organisers),
            "organisers": [_format_organiser_summary(o, all_emails, db, owner) for o in organisers],
        }

    @router.get("/calibrate/draft")
    async def get_calibrate_draft(
        request: Request,
        db: Session = Depends(get_db),
    ):
        """Retrieve the active calibration draft or initialize a fresh 100-email draft."""
        owner = require_user(request)
        draft_id = f"{owner}:calibration_draft"
        draft = db.query(CalibrationDraft).filter(CalibrationDraft.id == draft_id).first()

        all_emails = _get_recent_emails(days=14)
        overrides = load_organiser_overrides(db, owner)

        if draft and draft.taxonomy_json and draft.emails_json:
            try:
                raw_cats = json.loads(draft.taxonomy_json)
                raw_emails = json.loads(draft.emails_json)
                categories = [CategoryDraft(**c) for c in raw_cats if isinstance(c, dict)]
                emails = [EmailDraftRow(**e) for e in raw_emails if isinstance(e, dict)]

                active_cats = [c for c in categories if not c.is_deleted]

                # Backfill snippets/to_text if previously empty
                email_lookup = {email_key(e): e for e in all_emails}
                needs_update = False
                for e in emails:
                    orig = email_lookup.get((e.account_key, e.uid))
                    if orig:
                        if not e.snippet and orig.get("snippet"):
                            e.snippet = orig.get("snippet")
                            needs_update = True
                        if not e.to_text and orig.get("to_text"):
                            e.to_text = orig.get("to_text")
                            needs_update = True
                        if not e.folder and orig.get("folder"):
                            e.folder = orig.get("folder")
                            needs_update = True
                if needs_update:
                    draft.emails_json = json.dumps([e.model_dump() for e in emails])
                    db.commit()

                cal_cats_for_calc = [
                    CalibratedCategory(
                        id=c.id,
                        slug=c.slug,
                        name=c.name,
                        description=c.description,
                        category_group=c.category_group,
                        icon=c.icon,
                        color=c.color,
                        priority=c.priority,
                        rules=c.rules,
                    )
                    for c in active_cats
                ]
                stats = _recalculate_taxonomy_coverage(cal_cats_for_calc, all_emails, overrides)
                coverage_map = {c.slug: c.coverage_count for c in stats["categories"]}
                for c in categories:
                    c.coverage_count = coverage_map.get(c.slug, 0)

                return {
                    "ok": True,
                    "stage": draft.stage,
                    "updated_at": draft.updated_at.isoformat() if draft.updated_at else "",
                    "categories": [c.model_dump() for c in categories],
                    "emails": [e.model_dump() for e in emails],
                    "total_corpus_emails": stats["total_emails"],
                    "matched_unique": stats["matched_unique"],
                    "unassigned_count": stats["unassigned_count"],
                }
            except Exception as e:
                logger.warning("Failed parsing existing calibration draft: %s, re-seeding", e)

        # Seed fresh 100-email draft
        sampled = _sample_calibration_emails(all_emails, limit=100)
        existing_organisers = db.query(WorkOrganiser).filter(
            or_(WorkOrganiser.owner == owner, WorkOrganiser.owner == None)
        ).all()

        categories, emails = _generate_initial_draft_payload(sampled, existing_organisers)

        cal_cats_for_calc = [
            CalibratedCategory(
                id=c.id,
                slug=c.slug,
                name=c.name,
                description=c.description,
                category_group=c.category_group,
                icon=c.icon,
                color=c.color,
                priority=c.priority,
                rules=c.rules,
            )
            for c in categories if not c.is_deleted
        ]
        stats = _recalculate_taxonomy_coverage(cal_cats_for_calc, all_emails, overrides)
        coverage_map = {c.slug: c.coverage_count for c in stats["categories"]}
        for c in categories:
            c.coverage_count = coverage_map.get(c.slug, 0)

        taxonomy_str = json.dumps([c.model_dump() for c in categories])
        emails_str = json.dumps([e.model_dump() for e in emails])
        now = utcnow_naive()

        if not draft:
            draft = CalibrationDraft(
                id=draft_id,
                owner=owner,
                stage="draft",
                taxonomy_json=taxonomy_str,
                emails_json=emails_str,
                created_at=now,
                updated_at=now,
            )
            db.add(draft)
        else:
            draft.stage = "draft"
            draft.taxonomy_json = taxonomy_str
            draft.emails_json = emails_str
            draft.updated_at = now

        db.commit()

        return {
            "ok": True,
            "stage": "draft",
            "updated_at": now.isoformat(),
            "categories": [c.model_dump() for c in categories],
            "emails": [e.model_dump() for e in emails],
            "total_corpus_emails": stats["total_emails"],
            "matched_unique": stats["matched_unique"],
            "unassigned_count": stats["unassigned_count"],
        }

    @router.put("/calibrate/draft")
    async def save_calibrate_draft(
        payload: SaveCalibrationDraftRequest,
        request: Request,
        db: Session = Depends(get_db),
    ):
        """Autosave the working draft with up to 3 categories, 10 parameters, and comments."""
        owner = require_user(request)
        draft_id = f"{owner}:calibration_draft"

        deleted_slugs = {c.slug for c in payload.categories if c.is_deleted}

        cleaned_emails: List[EmailDraftRow] = []
        for e in payload.emails:
            filtered_cats = [c for c in e.assigned_categories if c not in deleted_slugs][:3]
            e.assigned_categories = filtered_cats
            e.extracted_parameters = e.extracted_parameters[:10]
            if len(e.comments or "") > 2000:
                e.comments = e.comments[:2000]
            cleaned_emails.append(e)

        for c in payload.categories:
            if len(c.comments or "") > 2000:
                c.comments = c.comments[:2000]

        taxonomy_str = json.dumps([c.model_dump() for c in payload.categories])
        emails_str = json.dumps([e.model_dump() for e in cleaned_emails])

        draft = db.query(CalibrationDraft).filter(CalibrationDraft.id == draft_id).first()
        now = utcnow_naive()
        if not draft:
            draft = CalibrationDraft(
                id=draft_id,
                owner=owner,
                stage=payload.stage or "draft",
                taxonomy_json=taxonomy_str,
                emails_json=emails_str,
                created_at=now,
                updated_at=now,
            )
            db.add(draft)
        else:
            draft.stage = payload.stage or draft.stage
            draft.taxonomy_json = taxonomy_str
            draft.emails_json = emails_str
            draft.updated_at = now

        db.commit()

        return {
            "ok": True,
            "updated_at": now.isoformat(),
            "category_count": len(payload.categories),
            "email_count": len(cleaned_emails),
        }

    @router.post("/calibrate/draft/reset")
    async def reset_calibrate_draft(
        request: Request,
        db: Session = Depends(get_db),
    ):
        """Reset the working draft back to the fresh 100-email inferred baseline."""
        owner = require_user(request)
        draft_id = f"{owner}:calibration_draft"
        db.query(CalibrationDraft).filter(CalibrationDraft.id == draft_id).delete()
        db.commit()
        return await get_calibrate_draft(request, db)

    @router.post("/calibrate/agent-pass")
    async def run_agent_pass(
        payload: AgentPassRequest,
        request: Request,
        db: Session = Depends(get_db),
    ):
        """Phase 2: Agent iterates through the full corpus, assigning 1-3 categories per email."""
        owner = require_user(request)
        all_emails = _get_recent_emails(days=payload.days)
        overrides = load_organiser_overrides(db, owner)

        # Thread Reply-Chain Propagation: Anchor comments and assignments cascade to all replies
        draft_id = f"{owner}:calibration_draft"
        draft = db.query(CalibrationDraft).filter(CalibrationDraft.id == draft_id).first()
        thread_overrides: Dict[str, List[str]] = {}
        if draft and draft.emails_json:
            try:
                draft_emails_raw = json.loads(draft.emails_json)
                for de in draft_emails_raw:
                    cats = de.get("assigned_categories") or []
                    cs = _clean_subject_for_threading(de.get("subject") or "")
                    if cs and cats:
                        if cs not in thread_overrides:
                            thread_overrides[cs] = []
                        for c_slug in cats:
                            if c_slug not in thread_overrides[cs]:
                                thread_overrides[cs].append(c_slug)
            except Exception as e:
                logger.warning("Error parsing draft emails for threading: %s", e)

        active_cats = [c for c in payload.categories if not c.is_deleted]
        category_coverage: Dict[str, int] = {c.slug: 0 for c in active_cats}
        corpus_matches: Dict[str, List[str]] = {}
        matched_unique = 0

        for email in all_emails:
            k = email_key(email)
            email_matched_slugs: List[str] = []

            # 1. Thread anchor inheritance
            cs = _clean_subject_for_threading(email.get("subject") or "")
            if cs in thread_overrides:
                for slug in thread_overrides[cs]:
                    if slug not in email_matched_slugs:
                        email_matched_slugs.append(slug)
                        category_coverage[slug] = category_coverage.get(slug, 0) + 1

            # 2. Rule evaluation
            for cat in active_cats:
                if cat.slug in email_matched_slugs:
                    continue
                rules_dict = cat.rules.model_dump() if hasattr(cat.rules, "model_dump") else cat.rules.dict()
                proxy = _OrgProxy(cat.id, cat.slug)
                if email_belongs_to_organiser(email, proxy, [], rules_dict, overrides):
                    email_matched_slugs.append(cat.slug)
                    category_coverage[cat.slug] = category_coverage.get(cat.slug, 0) + 1

            if email_matched_slugs:
                matched_unique += 1
                corpus_matches[k] = email_matched_slugs[:3]

        total_corpus = len(all_emails)
        unassigned_count = total_corpus - matched_unique

        multi_breakdown = {"1_category": 0, "2_categories": 0, "3_categories": 0}
        for slugs in corpus_matches.values():
            cnt = len(slugs)
            if cnt == 1:
                multi_breakdown["1_category"] += 1
            elif cnt == 2:
                multi_breakdown["2_categories"] += 1
            elif cnt >= 3:
                multi_breakdown["3_categories"] += 1

        # Advance draft stage
        draft_id = f"{owner}:calibration_draft"
        draft = db.query(CalibrationDraft).filter(CalibrationDraft.id == draft_id).first()
        if draft:
            draft.stage = "agent_evaluated"
            draft.updated_at = utcnow_naive()
            db.commit()

        return {
            "ok": True,
            "total_corpus_emails": total_corpus,
            "matched_unique": matched_unique,
            "unassigned_count": unassigned_count,
            "category_coverage": category_coverage,
            "multi_category_breakdown": multi_breakdown,
        }

    @router.get("/calibration")
    async def calibration_view(request: Request):
        """Serve the standalone Focus Studio in its own tab."""
        html_path = Path(__file__).resolve().parent.parent.parent / "static" / "calibration.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Calibration template not found")
        return FileResponse(str(html_path), media_type="text/html")

    @router.get("/calibrate/email-content/{account_key}/{uid}")
    async def get_calibrate_email_content(
        account_key: str,
        uid: str,
        folder: str = Query("INBOX"),
        request: Request = None,
        db: Session = Depends(get_db),
    ):
        """Fetch full email content (headers, body, html, summary).
        Checks preview cache, email summaries, and live IMAP read."""
        owner = require_user(request)
        db_file = Path(SCHEDULED_EMAILS_DB)

        body_text = ""
        summary_text = ""
        to_text = ""
        cc_text = ""
        subject = ""
        from_addr = ""
        from_name = ""
        date_iso = ""

        if db_file.exists():
            try:
                conn = sqlite3.connect(str(db_file), timeout=5.0)
                cur = conn.cursor()
                # Headers
                h_row = cur.execute(
                    "SELECT subject, from_name, from_address, to_text, cc_text, date_iso FROM email_message_index WHERE uid=? AND (account_key=? OR account_key IS NULL)",
                    (uid, account_key),
                ).fetchone()
                if h_row:
                    subject, from_name, from_addr, to_text, cc_text, date_iso = h_row

                # Body from preview cache
                p_row = cur.execute(
                    "SELECT payload_json FROM email_body_preview_cache WHERE uid=? AND folder=?",
                    (uid, folder),
                ).fetchone()
                if p_row and p_row[0]:
                    try:
                        p_data = json.loads(p_row[0])
                        body_text = p_data.get("body") or p_data.get("snippet") or ""
                    except Exception:
                        pass

                # Summary from email_summaries
                s_row = cur.execute(
                    "SELECT summary FROM email_summaries WHERE uid=?",
                    (uid,),
                ).fetchone()
                if s_row and s_row[0]:
                    summary_text = s_row[0]

                conn.close()
            except Exception as e:
                logger.warning("Error reading email cache: %s", e)

        # If body is still empty, attempt live IMAP read
        if not body_text:
            try:
                result = await asyncio.to_thread(_fetch_email_from_imap_sync, account_key, folder, uid, owner)
                if result and result.get("body"):
                    body_text = result.get("body") or ""
                    to_text = result.get("to") or to_text
                    cc_text = result.get("cc") or cc_text

                    # Cache into email_body_preview_cache
                    if db_file.exists():
                        try:
                            conn = sqlite3.connect(str(db_file), timeout=5.0)
                            payload_str = json.dumps({"body": body_text[:2000], "snippet": body_text[:300]})
                            conn.execute(
                                """
                                INSERT INTO email_body_preview_cache (owner, account_key, folder, uid, message_id, payload_json, updated_at)
                                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                                ON CONFLICT(owner, account_key, folder, uid) DO UPDATE SET
                                    payload_json=excluded.payload_json,
                                    updated_at=excluded.updated_at
                                """,
                                (owner, account_key, folder, str(uid), "", payload_str),
                            )
                            conn.commit()
                            conn.close()
                        except Exception as cache_err:
                            logger.debug("Failed caching preview: %s", cache_err)
            except Exception as e:
                logger.debug("Live IMAP read skipped: %s", e)

        return {
            "ok": True,
            "uid": uid,
            "account_key": account_key,
            "folder": folder,
            "subject": subject,
            "from_name": from_name,
            "from_address": from_addr,
            "to": to_text,
            "cc": cc_text,
            "date": date_iso,
            "body": body_text or summary_text or "(No body content found for this message)",
            "summary": summary_text,
            "has_body": bool(body_text),
        }

    return router
