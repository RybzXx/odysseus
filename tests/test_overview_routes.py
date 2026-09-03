"""Unit tests for routes/overview/overview_routes.py.

Tests:
1. Overview briefing payload aggregation and schema invariants.
2. Multi-tier SWR (Stale-While-Revalidate) cache hit and revalidation behavior.
3. Projects and open task counter calculations.
"""

import json
import os
import tempfile
import pytest
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI
from starlette.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.database as db
from routes.overview.overview_routes import (
    setup_overview_routes,
    _build_overview_payload,
    _BRIEFING_WINDOW_DAYS,
    _OVERVIEW_MEMORY_CACHE,
)


@pytest.fixture
def test_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}")
    db.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    # Seed test project and tasks
    session = Session()
    proj = db.Project(
        id="proj_test1",
        slug="test-hub",
        name="Test Hub Project",
        status="active",
        priority="high",
        folder_path="workspaces/test-hub",
        manifest_path="workspaces/test-hub/PROJECT.md",
        task_total=2,
        task_completed=1,
        agent_summary="Test agent summary for hub.",
    )
    task1 = db.ProjectTask(
        id="ptask_1",
        project_id="proj_test1",
        title="Active Task 1",
        completed=False,
        sort_order=1,
    )
    task2 = db.ProjectTask(
        id="ptask_2",
        project_id="proj_test1",
        title="Completed Task 2",
        completed=True,
        sort_order=2,
    )
    session.add(proj)
    session.add(task1)
    session.add(task2)
    session.commit()
    session.close()

    try:
        yield engine, Session
    finally:
        engine.dispose()
        if os.path.exists(path):
            os.remove(path)


@pytest.mark.asyncio
async def test_build_overview_payload_schema(test_db, monkeypatch):
    engine, Session = test_db
    monkeypatch.setattr("core.database.SessionLocal", Session)
    monkeypatch.setattr("core.database.engine", engine)

    payload = await _build_overview_payload(owner=None, email_days=7)

    assert payload["ok"] is True
    assert "kpis" in payload
    assert "email_digest" in payload
    assert "projects_matrix" in payload
    assert "operations_radar" in payload

    # Verify KPIs
    kpis = payload["kpis"]
    assert kpis["active_projects"] == 1
    assert kpis["open_tasks"] == 1

    # Verify Projects Matrix
    matrix = payload["projects_matrix"]
    assert len(matrix) == 1
    assert matrix[0]["id"] == "proj_test1"
    assert matrix[0]["name"] == "Test Hub Project"
    assert len(matrix[0]["tasks"]) == 2
    assert matrix[0]["agent_summary"] == "Test agent summary for hub."


def _build_app(Session, authenticated=True):
    """Assemble the overview router with a DB override.

    `authenticated` installs the same mock auth middleware the organisers
    tests use. /api/overview calls require_user, so an unauthenticated client
    gets a 401 — which is the point of the without-auth regression below.
    """
    app = FastAPI()

    if authenticated:
        @app.middleware("http")
        async def mock_auth_middleware(request, call_next):
            request.state.current_user = "admin"
            request.state.api_token = False
            return await call_next(request)

    app.include_router(setup_overview_routes())

    def override_get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[db.get_db] = override_get_db
    return app


def test_overview_api_requires_authentication(test_db, monkeypatch):
    """An unauthenticated caller must be rejected, not served the shared
    "__global__" cache bucket. require_user's 401 used to be swallowed by a
    bare `except Exception` that fell through to owner=None."""
    engine, Session = test_db
    monkeypatch.setattr("core.database.SessionLocal", Session)
    monkeypatch.setattr("core.database.engine", engine)
    _OVERVIEW_MEMORY_CACHE.clear()

    client = TestClient(_build_app(Session, authenticated=False))
    assert client.get("/api/overview").status_code == 401


def test_overview_api_endpoint(test_db, monkeypatch):
    engine, Session = test_db
    monkeypatch.setattr("core.database.SessionLocal", Session)
    monkeypatch.setattr("core.database.engine", engine)
    _OVERVIEW_MEMORY_CACHE.clear()

    client = TestClient(_build_app(Session))

    # 1. Cold request -> computes fresh overview
    res1 = client.get("/api/overview")
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["ok"] is True
    assert data1["is_stale"] is False
    assert data1["kpis"]["active_projects"] == 1

    # 2. Immediate second request -> hits fast cache (SWR fresh)
    res2 = client.get("/api/overview")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["is_stale"] is False
    assert data2["cached_at"] == data1["cached_at"]

    # 3. Force refresh request -> recomputes
    res3 = client.get("/api/overview?force_refresh=true")
    assert res3.status_code == 200
    data3 = res3.json()
    assert data3["ok"] is True


def test_overview_swr_stale_revalidation(test_db, monkeypatch):
    engine, Session = test_db
    monkeypatch.setattr("core.database.SessionLocal", Session)
    monkeypatch.setattr("core.database.engine", engine)
    _OVERVIEW_MEMORY_CACHE.clear()

    # Pre-populate OverviewCache with a stale row (> 120s old)
    session = Session()
    stale_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)
    stale_payload = {
        "ok": True,
        "cached_at": stale_time.isoformat() + "Z",
        "kpis": {"active_projects": 99, "open_tasks": 42},
        "email_digest": {"accounts": [], "emails": []},
        "projects_matrix": [],
        "operations_radar": {"inquiries": []},
    }
    # Keyed to the authenticated owner. Before /api/overview required auth,
    # the caller resolved to owner=None and this row was seeded under the
    # shared "__global__" bucket.
    #
    # The window suffix is now the fixed _BRIEFING_WINDOW_DAYS rather than the
    # requested email_days: the endpoint serves and caches one window per owner,
    # and the email panel narrows by date client-side. This id changed with that
    # policy — it is not a stale expectation being papered over.
    session.add(db.OverviewCache(
        id=f"admin:overview:{_BRIEFING_WINDOW_DAYS}",
        owner="admin",
        payload_json=json.dumps(stale_payload),
        cached_at=stale_time,
        expires_at=stale_time + timedelta(hours=24),
    ))
    session.commit()
    session.close()

    client = TestClient(_build_app(Session))

    # Stale read should return cached data immediately with is_stale: True
    res = client.get("/api/overview?email_days=7")
    assert res.status_code == 200
    data = res.json()
    assert data["kpis"]["active_projects"] == 99
    assert data["is_stale"] is True


def test_requested_window_does_not_fork_the_cache(test_db, monkeypatch):
    """Every duration shares one bucket per owner.

    The email panel's duration buttons used to drive ``email_days``, so each
    press produced a separate full-payload cache row carrying its own copy of
    the projects and operations panels.
    """
    engine, Session = test_db
    monkeypatch.setattr("core.database.SessionLocal", Session)
    monkeypatch.setattr("core.database.engine", engine)
    _OVERVIEW_MEMORY_CACHE.clear()

    client = TestClient(_build_app(Session))
    for days in (1, 3, 7, 30):
        assert client.get(f"/api/overview?email_days={days}").status_code == 200

    session = Session()
    try:
        ids = [row.id for row in session.query(db.OverviewCache).all()]
    finally:
        session.close()

    assert ids == [f"admin:overview:{_BRIEFING_WINDOW_DAYS}"], (
        f"four durations produced {len(ids)} cache rows: {ids}"
    )


@pytest.mark.asyncio
async def test_email_digest_urgency_file_parsing(test_db, tmp_path, monkeypatch):
    engine, Session = test_db
    monkeypatch.setattr("core.database.SessionLocal", Session)
    monkeypatch.setattr("core.database.engine", engine)
    monkeypatch.setattr("src.constants.DATA_DIR", str(tmp_path))

    # Write urgency state file
    state_file = tmp_path / "email_urgency_state_default.json"
    state_file.write_text(json.dumps({
        "total_unread": 8,
        "total_urgent": 3,
        "accounts": {
            "acc_1": {
                "messages": [
                    {
                        "id": "acc_1:101",
                        "sender_name": "VIP Client",
                        "sender_email": "vip@client.com",
                        "subject": "Contract Renewal Required",
                        "snippet": "Please review the updated agreement.",
                        "is_urgent": True,
                        "urgency": "critical",
                        "ai_comment": "Requires CEO signature today.",
                        "read": False,
                        "date": datetime.now(timezone.utc).isoformat(),
                    }
                ]
            }
        }
    }))

    payload = await _build_overview_payload(owner=None, email_days=7)
    digest = payload["email_digest"]
    assert digest["total_unread"] == 1
    assert digest["total_urgent"] == 1
    assert len(digest["emails"]) >= 1
    first_email = digest["emails"][0]
    assert first_email["sender_name"] == "VIP Client"
    assert first_email["urgency"] == "critical"
    assert first_email["ai_comment"] == "Requires CEO signature today."


@pytest.mark.asyncio
async def test_discovered_accounts_yield_exactly_one_default(test_db, tmp_path, monkeypatch):
    """Accounts discovered from the email stream have no EmailAccount row.

    Two invariants held here. (1) Exactly one descriptor is the default: the
    old per-append rule `acc_k == "default" or len(accounts_out) == 0` marked
    both the first discovered account and a later literal "default". (2) The
    `email` field carries an address or "" — it was being filled with the
    display label, so consumers rendered "Account acc_1" as a mailbox address.
    """
    engine, Session = test_db
    monkeypatch.setattr("core.database.SessionLocal", Session)
    monkeypatch.setattr("core.database.engine", engine)
    monkeypatch.setattr("src.constants.DATA_DIR", str(tmp_path))

    now_iso = datetime.now(timezone.utc).isoformat()

    def _msg(mid, acc):
        return {
            "id": f"{acc}:{mid}",
            "sender_name": f"Sender {mid}",
            "sender_email": f"s{mid}@example.com",
            "subject": f"Subject {mid}",
            "snippet": "",
            "is_urgent": False,
            "read": True,
            "date": now_iso,
        }

    # "acc_1" sorts before "default", so the old rule marked acc_1 default
    # (list was empty) and then default too (literal id match).
    state_file = tmp_path / "email_urgency_state_default.json"
    state_file.write_text(json.dumps({
        "total_unread": 0,
        "total_urgent": 0,
        "accounts": {
            "acc_1": {"messages": [_msg("101", "acc_1")]},
            "default": {"messages": [_msg("202", "default")]},
        },
    }))

    payload = await _build_overview_payload(owner=None, email_days=7)
    accounts = payload["email_digest"]["accounts"]

    assert {a["id"] for a in accounts} >= {"acc_1", "default"}
    assert sum(1 for a in accounts if a["is_default"]) == 1
    for a in accounts:
        assert "@" in a["email"] or a["email"] == "", (
            f"account {a['id']} has a display label in its email field: {a['email']!r}"
        )
