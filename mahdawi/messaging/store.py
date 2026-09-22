"""
messaging.store — the message ledger, the reply log, the audit, the outbox.

claim() is the atomic entry point: a second sighting of the same (channel,
external_id) cannot produce a second processing pass.

Tables
  messages        the ledger. terminal_state NULL = ingested, not yet resolved.
  replies         every reply actually sent. Feeds the rolling cap and the
                  one-private-reply-per-comment check.
  classifications the audit trail — one row per decision, FAQ included.
  staged          the owner's approval queue. payload is JSON.
  runs            one row per pass, holding its report.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from mahdawi.messaging import settings
from mahdawi.messaging.models import InboundItem, utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    channel       TEXT NOT NULL,
    external_id   TEXT NOT NULL,
    thread_ref    TEXT NOT NULL,
    kind          TEXT NOT NULL,
    text          TEXT NOT NULL,
    author_ref    TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    ingested_at   TEXT NOT NULL,
    terminal_state TEXT,
    reason        TEXT,
    PRIMARY KEY (channel, external_id)
);
CREATE TABLE IF NOT EXISTS replies (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    channel       TEXT NOT NULL,
    thread_ref    TEXT NOT NULL,
    external_id   TEXT NOT NULL,
    kind          TEXT NOT NULL,
    sent_at       TEXT NOT NULL,
    resolved      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_replies_thread ON replies (channel, thread_ref, sent_at);
CREATE TABLE IF NOT EXISTS classifications (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    channel       TEXT NOT NULL,
    external_id   TEXT NOT NULL,
    tier          TEXT,
    agent_signal  TEXT,
    agent_confidence REAL,
    agent_reasoning  TEXT,
    gate_facts    TEXT,
    outcome       TEXT NOT NULL,
    reason        TEXT,
    decided_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS staged (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    channel       TEXT NOT NULL,
    external_id   TEXT NOT NULL,
    payload       TEXT NOT NULL,
    reason        TEXT NOT NULL,
    staged_at     TEXT NOT NULL,
    approved      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    report        TEXT NOT NULL
);
"""


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def connect(path: Optional[str] = None) -> sqlite3.Connection:
    """
    Pre : path is writable, or ":memory:".
    Post: WAL is on and every table exists. Idempotent.
    """
    path = path or settings.DB_PATH
    if path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


# -- ledger --------------------------------------------------------------------
def claim(conn: sqlite3.Connection, item: InboundItem) -> bool:
    """
    Pre : item.created_at is tz-aware.
    Post: True on first sighting, False on every later one. On True the row
          exists with terminal_state NULL, so a crash leaves it resumable.
    """
    try:
        conn.execute(
            "INSERT INTO messages (channel, external_id, thread_ref, kind, text,"
            " author_ref, created_at, ingested_at) VALUES (?,?,?,?,?,?,?,?)",
            (item.channel, item.external_id, item.thread_ref, item.kind, item.text,
             item.author_ref, _iso(item.created_at), _iso(utcnow())),
        )
        return True
    except sqlite3.IntegrityError:
        return False


def resolve(conn, channel: str, external_id: str, state: str,
            reason: Optional[str] = None) -> None:
    """Post: the item holds a terminal state and no longer resumes."""
    conn.execute(
        "UPDATE messages SET terminal_state=?, reason=? WHERE channel=? AND external_id=?",
        (state, reason, channel, external_id),
    )


def unresolved(conn, channel: Optional[str] = None) -> list:
    """Items claimed but never resolved — what a restart picks back up."""
    if channel:
        rows = conn.execute("SELECT * FROM messages WHERE terminal_state IS NULL"
                            " AND channel=? ORDER BY ingested_at", (channel,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM messages WHERE terminal_state IS NULL"
                            " ORDER BY ingested_at").fetchall()
    return [dict(r) for r in rows]


# -- facts the gate reads ------------------------------------------------------
def replies_in_window(conn, channel: str, thread_ref: str, hours: int = 24) -> int:
    """Rolling count, not calendar-day: no midnight step."""
    since = _iso(utcnow() - timedelta(hours=hours))
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM replies WHERE channel=? AND thread_ref=? AND sent_at > ?",
        (channel, thread_ref, since),
    ).fetchone()
    return int(row["n"])


def has_unresolved_prior(conn, channel: str, thread_ref: str) -> bool:
    """True when the shop already answered this thread and nobody marked it resolved."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM replies WHERE channel=? AND thread_ref=? AND resolved=0",
        (channel, thread_ref),
    ).fetchone()
    return int(row["n"]) > 0


def comment_reply_used(conn, channel: str, comment_ref: str) -> bool:
    """Meta allows exactly one private reply per comment, ever."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM replies WHERE channel=? AND kind='comment'"
        " AND external_id=?",
        (channel, comment_ref),
    ).fetchone()
    return int(row["n"]) > 0


def record_reply(conn, channel: str, thread_ref: str, external_id: str, kind: str) -> None:
    """Post: the cap counter and the comment-reply check both see this send."""
    conn.execute(
        "INSERT INTO replies (channel, thread_ref, external_id, kind, sent_at)"
        " VALUES (?,?,?,?,?)",
        (channel, thread_ref, external_id, kind, _iso(utcnow())),
    )


def mark_thread_resolved(conn, channel: str, thread_ref: str) -> None:
    conn.execute("UPDATE replies SET resolved=1 WHERE channel=? AND thread_ref=?",
                 (channel, thread_ref))


# -- audit ---------------------------------------------------------------------
def write_classification(conn, *, channel, external_id, tier, verdict,
                         gate_facts, outcome, reason=None) -> None:
    """Invariant: one row per decision, FAQ auto-replies included."""
    conn.execute(
        "INSERT INTO classifications (channel, external_id, tier, agent_signal,"
        " agent_confidence, agent_reasoning, gate_facts, outcome, reason, decided_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (channel, external_id, tier,
         verdict.tier_signal if verdict else None,
         verdict.confidence if verdict else None,
         verdict.reasoning if verdict else None,
         json.dumps(gate_facts.to_dict() if gate_facts else {}),
         outcome, reason, _iso(utcnow())),
    )


def audit_count(conn, outcome: str) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM classifications WHERE outcome=?",
                       (outcome,)).fetchone()
    return int(row["n"])


# -- the owner's approval queue -----------------------------------------------
class AlreadyApproved(RuntimeError):
    """A second approval of the same row. A caught bug, never a silent re-send."""


def insert_staged(conn, channel: str, external_id: str, payload: dict, reason: str) -> int:
    """Post: one row exists with approved=0; returns its id."""
    cur = conn.execute(
        "INSERT INTO staged (channel, external_id, payload, reason, staged_at)"
        " VALUES (?,?,?,?,?)",
        (channel, external_id, json.dumps(payload, ensure_ascii=False), reason, _iso(utcnow())),
    )
    return int(cur.lastrowid)


def staged_rows(conn, approved: Optional[bool] = None) -> list:
    """Post: staged rows oldest first, payload parsed; filtered when asked."""
    if approved is None:
        rows = conn.execute("SELECT * FROM staged ORDER BY id").fetchall()
    else:
        rows = conn.execute("SELECT * FROM staged WHERE approved=? ORDER BY id",
                            (1 if approved else 0,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["payload"] = json.loads(d["payload"])
        out.append(d)
    return out


def approve(conn, staged_id: int) -> dict:
    """
    Pre : the row exists and is not yet approved.
    Post: approved=1; returns the parsed payload for the sender to act on.
    Raises: AlreadyApproved on a second approval.
    Invariant: no send. This flips state only.
    """
    row = conn.execute("SELECT payload, approved FROM staged WHERE id=?",
                       (staged_id,)).fetchone()
    if row is None:
        raise KeyError("no staged row %d" % staged_id)
    if int(row["approved"]) == 1:
        raise AlreadyApproved("staged row %d already approved" % staged_id)
    conn.execute("UPDATE staged SET approved=1 WHERE id=?", (staged_id,))
    return json.loads(row["payload"])


def write_run(conn, report: dict) -> None:
    """Post: one runs row holds this report as JSON."""
    conn.execute("INSERT INTO runs (started_at, report) VALUES (?,?)",
                 (_iso(utcnow()), json.dumps(report, ensure_ascii=False)))
