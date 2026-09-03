"""Regression tests for the Overview email row, driven by the live-shape fixture.

Every fault these pin was invisible locally because a fresh checkout has no
email data at all, and invisible in the existing suite because
``test_overview_routes.py`` exercises the urgency file's ``accounts`` shape --
which composes its snippet correctly -- while the live instance writes the
``per_uid`` shape, which does not.

The fixture at ``tests/fixtures/briefing_shape.json`` is captured from the live
instance and pseudonymised (see ``scripts/capture_briefing_fixture.py``). Its
value is the field *distribution*: 157 messages carrying ``reason`` and no
``snippet``, 85 of 154 with a stored summary. A hand-written fixture would give
every message a snippet and none of these tests could fail.

These are offline and deterministic: the fixture is a committed file, no test
here reaches the network or the phone.
"""

import json
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.database as db
from routes.overview.overview_routes import (
    _build_overview_payload,
    _compose_row_text,
    _split_summary_and_action,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "briefing_shape.json"
URGENCY_FILE = "email_urgency_state_admin.json"
OWNER = "admin"


def _load_fixture():
    if not FIXTURE_PATH.exists():
        pytest.skip(
            f"{FIXTURE_PATH} is absent. Regenerate with "
            f"scripts/capture_briefing_fixture.py."
        )
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def briefing_env(tmp_path, monkeypatch):
    """Point the overview at a temp data dir holding the fixture's stores.

    Pre:  none. Post: src.constants paths, and the SQLAlchemy session, all
    resolve inside tmp_path, so nothing here touches a developer's ./data.
    """
    fixture = _load_fixture()

    state = (fixture.get("urgency_states") or {}).get(URGENCY_FILE)
    if not state:
        pytest.skip(f"fixture carries no {URGENCY_FILE}")
    (tmp_path / URGENCY_FILE).write_text(json.dumps(state), encoding="utf-8")

    sched_db = tmp_path / "scheduled_emails.db"
    summaries = fixture.get("email_summaries") or {}
    conn = sqlite3.connect(str(sched_db))
    try:
        conn.execute(
            "CREATE TABLE email_summaries ("
            "message_id TEXT, owner TEXT, uid TEXT, folder TEXT, subject TEXT, "
            "sender TEXT, summary TEXT, model_used TEXT, created_at TEXT)"
        )
        cols = summaries.get("columns") or []
        if cols:
            conn.executemany(
                f"INSERT INTO email_summaries ({', '.join(cols)}) "
                f"VALUES ({', '.join('?' for _ in cols)})",
                [list(r) for r in summaries.get("rows", [])],
            )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr("src.constants.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("src.constants.SCHEDULED_EMAILS_DB", str(sched_db))

    engine = create_engine(f"sqlite:///{(tmp_path / 'app.db').as_posix()}")
    db.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr("core.database.SessionLocal", Session)
    monkeypatch.setattr("core.database.engine", engine)

    try:
        yield fixture, state
    finally:
        engine.dispose()


async def _rows(days=30):
    payload = await _build_overview_payload(owner=OWNER, email_days=days)
    return payload["email_digest"]["emails"]


# ── the fixture's own guarantee ──────────────────────────────────────────

def test_fixture_preserves_the_live_field_distribution(briefing_env):
    """The fixture must keep the shape that makes the other tests meaningful.

    If someone regenerates or hand-edits the fixture such that messages gain a
    ``snippet``, the duplicate-summary regression below silently stops being
    able to fail. This test guards the guard.
    """
    _fixture, state = briefing_env
    messages = list((state.get("per_uid") or {}).values())

    assert messages, "fixture carries no per_uid messages"
    assert all(m.get("reason") for m in messages), (
        "every live message carries a triage reason; the fixture must too"
    )
    assert not any(m.get("snippet") or m.get("preview") for m in messages), (
        "no live message carries a snippet or preview. A fixture that adds one "
        "hides the snippet/ai_comment composition fault entirely."
    )


# ── 1.1 the duplicate ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_snippet_is_never_the_same_text_as_the_ai_comment(briefing_env):
    """A row must not print one string twice.

    overview_routes.py composed ``snippet`` as
    ``snippet or preview or ai_comm or ""``. With no live message carrying a
    snippet or preview, that fell through to ``ai_comm`` on every row, and the
    frontend renders both fields -- so every row showed its triage reason
    twice, once as body text and once in the blue pill.
    """
    duplicated = [
        row for row in await _rows()
        if row.get("ai_comment") and row.get("snippet") == row.get("ai_comment")
    ]
    assert not duplicated, (
        f"{len(duplicated)} row(s) render identical snippet and ai_comment, "
        f"e.g. {duplicated[0]['snippet']!r}"
    )


# ── 1.2 the unreachable summaries ────────────────────────────────────────

@pytest.mark.asyncio
async def test_stored_summaries_reach_the_row(briefing_env):
    """Summaries already in email_summaries must be displayed.

    The lookup was guarded by ``if not ai_comm and ...``, and ``ai_comm``
    resolves from ``reason``, which is present on every row -- so the branch was
    unreachable and every stored summary was read out of SQLite and discarded.

    The row shows the summary's narrative with the action line lifted out into
    its own field, so this checks that the narrative reached the row rather
    than asserting the stored text verbatim -- comparing verbatim would just
    re-implement the splitter it is meant to check.
    """
    fixture, state = briefing_env
    cols = (fixture.get("email_summaries") or {}).get("columns") or []
    mid_i, summary_i = cols.index("message_id"), cols.index("summary")
    stored = {
        r[mid_i]: r[summary_i]
        for r in fixture["email_summaries"]["rows"] if r[summary_i]
    }
    expected = {
        m.get("message_id") for m in (state.get("per_uid") or {}).values()
    } & set(stored)
    assert expected, "fixture has no message with a stored summary"

    shown = "  ".join(row.get("snippet") or "" for row in await _rows())

    def _first_narrative_line(summary):
        for line in summary.splitlines():
            text = line.strip().lstrip("-*• \t")
            if text and not text.lower().startswith("action"):
                return text
        return ""

    surfaced = [
        mid for mid in expected
        if (line := _first_narrative_line(stored[mid])) and line in shown
    ]

    assert len(surfaced) >= len(expected) * 0.9, (
        f"only {len(surfaced)} of {len(expected)} stored summaries reached the "
        f"row; the rest were fetched and discarded"
    )


# ── 1.3 the fallback ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rows_without_a_summary_fall_back_to_the_subject(briefing_env):
    """A message with no stored summary shows its subject, not its triage label.

    ``reason`` has four distinct values across the whole corpus, so rendering it
    as body text tells the reader nothing about the specific message.
    """
    _fixture, state = briefing_env
    reasons = {
        m["reason"] for m in (state.get("per_uid") or {}).values() if m.get("reason")
    }

    rows = await _rows()
    assert rows, "no rows rendered from the fixture"

    leaked = [r for r in rows if r.get("snippet") in reasons]
    assert not leaked, (
        f"{len(leaked)} row(s) show a triage label as body text, "
        f"e.g. {leaked[0]['snippet']!r}"
    )
    assert all(r.get("snippet") for r in rows), (
        "every row must render body text: a stored summary, else its subject"
    )


# ── 1.4 / 1.5 the row-text contract, independent of the fixture ──────────

@pytest.mark.parametrize("summary,expected_action", [
    ("- The venue is confirmed.\n- Action items: Request an invitation.",
     "Request an invitation."),
    ("- 2SV was enabled.\n- Action: Review the settings.",
     "Review the settings."),
    ("- Nothing is required here.", None),
    ("", None),
    (None, None),
])
def test_action_line_is_lifted_out_of_the_summary(summary, expected_action):
    body, action = _split_summary_and_action(summary)
    assert action == expected_action
    if expected_action:
        assert expected_action not in body, (
            "the action must not remain in the body as well as the pill"
        )


def test_body_falls_back_to_subject_never_to_the_triage_label():
    body, action, reason = _compose_row_text(
        triage_reason="bulk marketing/newsletter",
        subject="Your monthly statement",
    )
    assert body == "Your monthly statement"
    assert reason == "bulk marketing/newsletter"
    assert action is None


def test_a_summary_only_of_an_action_still_leaves_body_text():
    """Stripping the action must never leave a row with nothing to show."""
    body, action, _reason = _compose_row_text(
        stored_summary="- Action: Reply to the supplier.",
        subject="Supplier follow-up",
    )
    assert action == "Reply to the supplier."
    assert body == "Supplier follow-up"


def test_the_three_roles_are_never_the_same_string():
    """The invariant the composer exists to hold."""
    body, action, reason = _compose_row_text(
        explicit_comment="action likely needed",
        triage_reason="action likely needed",
        subject="Contract renewal",
    )
    assert body == "Contract renewal"
    assert reason == "action likely needed"
    assert action is None, "a duplicated comment and triage label must collapse to the chip"


# ── 4.2: the stream carries organiser membership ─────────────────────────

@pytest.mark.asyncio
async def test_stream_rows_carry_organiser_membership(briefing_env, monkeypatch):
    """The panel filters by organiser, so each row must say which it belongs to.

    Overview and Organisers shared no server-side code at all; the only link
    between them was a button. Membership is resolved once per refresh here,
    using the organisers module's own resolver so the two cannot disagree.
    """
    import uuid

    import core.database as cdb

    session = cdb.SessionLocal()
    try:
        # A rule matching the fixture's most common sender alias.
        rows = await _rows()
        assert rows, "fixture produced no rows"
        sender = rows[0]["sender_name"]

        session.add(cdb.WorkOrganiser(
            id="org-under-test",
            owner=OWNER,
            name="Under Test",
            slug="under-test",
            category_group="operations",
            rules_json=json.dumps({"senders": [sender], "keywords": [], "domains": []}),
            target_accounts=json.dumps([]),
            is_active=True,
        ))
        session.commit()
    finally:
        session.close()

    payload = await _build_overview_payload(owner=OWNER, email_days=30)
    digest = payload["email_digest"]

    assert {o["id"] for o in digest["organisers"]} == {"org-under-test"}
    assert all("organiser_ids" in row for row in digest["emails"]), (
        "every row must carry organiser_ids, even when it matches none"
    )
    tagged = [r for r in digest["emails"] if "org-under-test" in r["organiser_ids"]]
    assert tagged, "the organiser's sender rule matched no row"
    assert all(r["sender_name"] == tagged[0]["sender_name"] for r in tagged)


@pytest.mark.asyncio
async def test_stream_still_renders_when_no_organisers_exist(briefing_env):
    """Organiser filtering enhances the stream; it must not gate showing it."""
    payload = await _build_overview_payload(owner=OWNER, email_days=30)
    digest = payload["email_digest"]

    assert digest["organisers"] == []
    assert digest["emails"], "the stream must still render with no organisers configured"


# ── 7.4: a thread you answered outranks one you did not ──────────────────

@pytest.mark.asyncio
async def test_replied_threads_rank_above_unreplied_ones(briefing_env, tmp_path):
    """Having replied is the strongest available signal that a thread matters.

    The signal comes from the user's own sent mail, which only exists in the
    index once index_sent_mail has run — so until then every row is simply
    marked not-replied and ordering is unchanged.
    """
    import sqlite3

    rows_before = await _rows()
    assert rows_before, "fixture produced no rows"
    assert all(r["replied"] is False for r in rows_before), (
        "with no Sent mail indexed, nothing can be marked replied"
    )

    # Pick an old row — one that date-ordering would otherwise bury.
    target = rows_before[-1]
    assert target["message_id"], "the row needs a message-id to be matched"

    conn = sqlite3.connect(str(tmp_path / "scheduled_emails.db"))
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS email_message_index ("
            "owner TEXT, account_key TEXT, folder TEXT, uid TEXT, message_id TEXT, "
            "subject TEXT, from_name TEXT, from_address TEXT, to_text TEXT, "
            "cc_text TEXT, date_iso TEXT, date_display TEXT, date_epoch REAL, "
            "size INTEGER, flags TEXT, has_attachments INTEGER, "
            "in_reply_to TEXT DEFAULT '', references_hdr TEXT DEFAULT '')"
        )
        conn.execute(
            "INSERT INTO email_message_index "
            "(owner, account_key, folder, uid, message_id, in_reply_to, references_hdr, date_epoch) "
            "VALUES ('admin','acc-1','Sent','1','<my-reply@x>',?,'',0)",
            (target["message_id"],),
        )
        conn.commit()
    finally:
        conn.close()

    rows_after = await _rows()
    replied = [r for r in rows_after if r["replied"]]

    assert len(replied) == 1
    assert replied[0]["message_id"] == target["message_id"]
    assert rows_after[0]["message_id"] == target["message_id"], (
        "the answered thread must sort to the top, ahead of newer unanswered mail"
    )
