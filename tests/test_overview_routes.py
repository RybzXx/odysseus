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
from routes.overview.overview_routes import setup_overview_routes, _build_overview_payload, _OVERVIEW_MEMORY_CACHE


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


def test_overview_api_endpoint(test_db, monkeypatch):
    engine, Session = test_db
    monkeypatch.setattr("core.database.SessionLocal", Session)
    monkeypatch.setattr("core.database.engine", engine)
    _OVERVIEW_MEMORY_CACHE.clear()

    app = FastAPI()
    app.include_router(setup_overview_routes())

    def override_get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[db.get_db] = override_get_db

    client = TestClient(app)

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
    session.add(db.OverviewCache(
        id="__global__:overview",
        owner=None,
        payload_json=json.dumps(stale_payload),
        cached_at=stale_time,
        expires_at=stale_time + timedelta(hours=24),
    ))
    session.commit()
    session.close()

    app = FastAPI()
    app.include_router(setup_overview_routes())

    def override_get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[db.get_db] = override_get_db
    client = TestClient(app)

    # Stale read should return cached data immediately with is_stale: True
    res = client.get("/api/overview")
    assert res.status_code == 200
    data = res.json()
    assert data["kpis"]["active_projects"] == 99
    assert data["is_stale"] is True


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
                        "date": "2026-09-01T12:00:00Z",
                    }
                ]
            }
        }
    }))

    payload = await _build_overview_payload(owner=None, email_days=7)
    digest = payload["email_digest"]
    assert digest["total_unread"] == 8
    assert digest["total_urgent"] == 3
    assert len(digest["emails"]) >= 1
    first_email = digest["emails"][0]
    assert first_email["sender_name"] == "VIP Client"
    assert first_email["urgency"] == "critical"
    assert first_email["ai_comment"] == "Requires CEO signature today."
