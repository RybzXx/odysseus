"""tests/test_organisers_routes.py

Unit and regression tests for AI Work Organisers REST API, rule engine, and default seeding.
"""

import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sqlalchemy.pool import StaticPool

from core.database import Base, WorkOrganiser, Project, ProjectTask, Memory, get_db
from routes.organisers.organisers_routes import (
    setup_organisers_routes,
    DEFAULT_ORGANISERS,
    _matches_rule,
    _normalize_slug,
)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client(db_session):
    app = FastAPI()

    # Mock auth middleware attaching current_user = 'admin'
    @app.middleware("http")
    async def mock_auth_middleware(request, call_next):
        request.state.current_user = "admin"
        request.state.api_token = False
        return await call_next(request)

    app.dependency_overrides[get_db] = lambda: db_session
    app.include_router(setup_organisers_routes())
    return TestClient(app)


def test_rule_matching_engine():
    """Verify rule matcher across accounts, senders, keywords, and domains."""
    email_sample = {
        "account_key": "99fccecdba6c497bb5961e5bf9b780d4",
        "from_name": "Adrian Matache",
        "from_address": "adrian@travelagency.ro",
        "subject": "Quotation Request: Federal Iraq Tour March 2027",
        "snippet": "We have 37 pax interested in hotel booking.",
    }

    # Match by sender
    assert _matches_rule(
        email_sample,
        target_accounts=["99fccecdba6c497bb5961e5bf9b780d4"],
        rules={"senders": ["Adrian Matache"]},
    ) is True

    # Mismatched account
    assert _matches_rule(
        email_sample,
        target_accounts=["other-acc-id"],
        rules={"senders": ["Adrian Matache"]},
    ) is False

    # Match by keyword in subject
    assert _matches_rule(
        email_sample,
        target_accounts=[],
        rules={"keywords": ["quotation", "rates"]},
    ) is True

    # Match by domain
    assert _matches_rule(
        email_sample,
        target_accounts=[],
        rules={"domains": ["travelagency.ro"]},
    ) is True

    # Unmatched rules
    assert _matches_rule(
        email_sample,
        target_accounts=[],
        rules={"senders": ["Zaid Mohanad"], "keywords": ["سوق العراق"]},
    ) is False


def test_organiser_with_no_criteria_matches_nothing():
    """An organiser that declares neither accounts nor rules is unconfigured,
    not universal. The account filter used to be skipped when target_accounts
    was empty, after which the "no rules specified" branch returned True
    unconditionally — every organiser claimed every email in the index."""
    email_sample = {
        "account_key": "99fccecdba6c497bb5961e5bf9b780d4",
        "from_name": "Adrian Matache",
        "from_address": "adrian@travelagency.ro",
        "subject": "Quotation Request",
        "snippet": "We have 37 pax interested in hotel booking.",
    }

    assert _matches_rule(email_sample, target_accounts=[], rules={}) is False
    # Whitespace-only rule entries are stripped, so they count as absent.
    assert _matches_rule(
        email_sample,
        target_accounts=[],
        rules={"senders": ["  "], "keywords": [""], "domains": []},
    ) is False

    # An account filter alone still selects, per the documented contract.
    assert _matches_rule(
        email_sample,
        target_accounts=["99fccecdba6c497bb5961e5bf9b780d4"],
        rules={},
    ) is True


def test_account_filter_rejects_email_with_no_account_key():
    """An email carrying no account key cannot be confirmed as a member of the
    targeted accounts, so it fails the filter rather than bypassing it."""
    orphan = {
        "from_name": "Adrian Matache",
        "from_address": "adrian@travelagency.ro",
        "subject": "Quotation Request",
        "snippet": "",
    }
    assert _matches_rule(
        orphan,
        target_accounts=["99fccecdba6c497bb5961e5bf9b780d4"],
        rules={"senders": ["Adrian Matache"]},
    ) is False


def test_seed_defaults_and_list(client, db_session):
    """Ensure GET /api/organisers auto-seeds default categories when empty."""
    res = client.get("/api/organisers")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["total"] == len(DEFAULT_ORGANISERS)

    # Check that Tour Operations and Financial Intelligence were seeded
    slugs = [o["slug"] for o in data["organisers"]]
    assert "bilweekend-tour-ops" in slugs
    assert "financial-intelligence" in slugs
    assert "tech-security-infrastructure" in slugs


def test_organiser_crud_lifecycle(client, db_session):
    """Test creating, reading, updating, and deleting a custom work organiser."""
    # 1. Create
    create_payload = {
        "name": "Custom Corporate Events",
        "slug": "corp-events",
        "description": "High-budget corporate retreats and summits",
        "category_group": "operations",
        "icon": "briefcase",
        "color": "#e06c75",
        "priority": "high",
        "target_accounts": ["99fccecdba6c497bb5961e5bf9b780d4"],
        "rules": {
            "senders": ["Events Coordinator"],
            "keywords": ["summit", "retreat", "conference"],
            "domains": ["corp.com"],
        },
        "ai_instructions": "Flag all retreat venues and track headcount.",
    }
    create_res = client.post("/api/organisers", json=create_payload)
    assert create_res.status_code == 200
    org = create_res.json()["organiser"]
    assert org["slug"] == "corp-events"
    assert org["priority"] == "high"

    # 2. Get Detail
    detail_res = client.get(f"/api/organisers/{org['id']}")
    assert detail_res.status_code == 200
    detail_data = detail_res.json()
    assert detail_data["ok"] is True
    assert detail_data["organiser"]["name"] == "Custom Corporate Events"

    # 3. Update
    update_res = client.put(f"/api/organisers/{org['id']}", json={
        "name": "Corporate Events & Summits",
        "priority": "critical",
    })
    assert update_res.status_code == 200
    updated_org = update_res.json()["organiser"]
    assert updated_org["name"] == "Corporate Events & Summits"
    assert updated_org["priority"] == "critical"

    # 4. Delete
    del_res = client.delete(f"/api/organisers/{org['id']}")
    assert del_res.status_code == 200
    assert del_res.json()["ok"] is True

    # Verify 404
    get_404 = client.get(f"/api/organisers/{org['id']}")
    assert get_404.status_code == 404
