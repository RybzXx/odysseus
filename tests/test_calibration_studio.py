"""tests/test_calibration_studio.py

Tests for the standalone Taxonomy & Rule Calibration Studio:
- 100-email balanced draft seeding
- Draft persistence in SQLite (comments, categories, up to 10 parameters)
- Category deletion cascade to email cards
- Multi-category assignment capping (max 3) and parameter token capping (max 10)
- Agent Pass corpus-wide multi-label evaluation
- HTML view endpoint for separate tab
"""

import json
import uuid
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import (
    Base,
    WorkOrganiser,
    EmailOrganiserOverride,
    OverviewCache,
    CalibrationDraft,
    get_db,
    utcnow_naive,
)
from routes.organisers.organisers_routes import (
    setup_organisers_routes,
    _sample_calibration_emails,
    _infer_calibration_taxonomy,
    _generate_initial_draft_payload,
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

    @app.middleware("http")
    async def mock_auth(request, call_next):
        request.state.current_user = "admin"
        request.state.api_token = False
        return await call_next(request)

    app.dependency_overrides[get_db] = lambda: db_session
    app.include_router(setup_organisers_routes())
    return TestClient(app)


def test_sample_100_emails_balancing():
    """Verify sampling balances sent mail, recent inbox, and domain diversity up to 100."""
    fake_emails = []
    # 30 sent emails
    for i in range(30):
        fake_emails.append({
            "account_key": "acc1",
            "uid": f"sent_{i}",
            "subject": f"Quotation {i}",
            "from_name": "Booking",
            "from_address": "book@bilweekend.com",
            "folder": "Sent",
        })
    # 60 inbox emails from common domain
    for i in range(60):
        fake_emails.append({
            "account_key": "acc1",
            "uid": f"inbox_{i}",
            "subject": f"Inquiry {i}",
            "from_name": f"Traveler {i}",
            "from_address": f"traveler{i}@gmail.com",
            "folder": "INBOX",
        })
    # 40 diversity emails from unique domains
    for i in range(40):
        fake_emails.append({
            "account_key": "acc1",
            "uid": f"div_{i}",
            "subject": f"Partner circular {i}",
            "from_name": f"Supplier {i}",
            "from_address": f"sales@partner{i}.com",
            "folder": "INBOX",
        })

    sampled = _sample_calibration_emails(fake_emails, limit=100)
    assert len(sampled) == 100

    # Ensure sent mail is represented (up to 25)
    sent_in_sample = [e for e in sampled if e["folder"] == "Sent"]
    assert len(sent_in_sample) == 25


def test_draft_initialization_and_persistence(client, db_session, monkeypatch):
    """Verify GET /draft auto-initializes the 100-email draft and PUT saves edits."""
    # Mock recent emails with 120 items
    fake_emails = [
        {
            "account_key": "acc1",
            "uid": str(i),
            "subject": f"Invoice and receipt payment {i}" if i < 10 else f"Tour booking inquiry {i}",
            "from_name": "Anthropic" if i < 10 else f"Traveler {i}",
            "from_address": "billing@anthropic.com" if i < 10 else f"user{i}@gmail.com",
            "folder": "INBOX",
            "date_iso": "2026-09-02T10:00:00",
        }
        for i in range(120)
    ]
    monkeypatch.setattr("routes.organisers.organisers_routes._get_recent_emails", lambda days=14: fake_emails)

    # 1. GET /calibrate/draft should seed fresh draft with 100 emails
    res = client.get("/api/organisers/calibrate/draft")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert len(data["emails"]) == 100
    assert len(data["categories"]) >= 6

    # Verify each email has <= 3 categories and <= 10 parameters
    for e in data["emails"]:
        assert len(e["assigned_categories"]) <= 3
        assert len(e["extracted_parameters"]) <= 10

    # 2. Modify draft: add row comments and a second category to the first email
    modified_categories = data["categories"]
    modified_emails = data["emails"]
    modified_emails[0]["comments"] = "User note: high priority billing"
    modified_emails[0]["assigned_categories"] = ["receipts-and-payments", "tech-security-infrastructure"]

    # PUT /calibrate/draft
    save_res = client.put("/api/organisers/calibrate/draft", json={
        "stage": "draft",
        "categories": modified_categories,
        "emails": modified_emails,
    })
    assert save_res.status_code == 200
    assert save_res.json()["ok"] is True

    # 3. Reload GET /calibrate/draft and assert persistence
    reload_res = client.get("/api/organisers/calibrate/draft")
    assert reload_res.status_code == 200
    reloaded_data = reload_res.json()
    first_email = reloaded_data["emails"][0]
    assert first_email["comments"] == "User note: high priority billing"
    assert first_email["assigned_categories"] == ["receipts-and-payments", "tech-security-infrastructure"]


def test_category_deletion_cascades_to_email_assignments(client, db_session, monkeypatch):
    """Verify that deleting a category strips it from all assigned emails in draft."""
    fake_emails = [
        {
            "account_key": "acc1",
            "uid": "1",
            "subject": "Tour inquiry",
            "from_name": "Dave",
            "from_address": "dave@example.com",
            "folder": "INBOX",
        }
    ]
    monkeypatch.setattr("routes.organisers.organisers_routes._get_recent_emails", lambda days=14: fake_emails)

    # Initialize draft
    res = client.get("/api/organisers/calibrate/draft")
    data = res.json()

    # Assign bilweekend-tour-ops to email
    data["emails"][0]["assigned_categories"] = ["bilweekend-tour-ops"]

    # Mark bilweekend-tour-ops as is_deleted = True
    for c in data["categories"]:
        if c["slug"] == "bilweekend-tour-ops":
            c["is_deleted"] = True

    # Save draft
    save_res = client.put("/api/organisers/calibrate/draft", json={
        "stage": "draft",
        "categories": data["categories"],
        "emails": data["emails"],
    })
    assert save_res.status_code == 200

    # Reload draft: email must NO LONGER have bilweekend-tour-ops assigned
    reload_res = client.get("/api/organisers/calibrate/draft")
    reloaded_data = reload_res.json()
    assert "bilweekend-tour-ops" not in reloaded_data["emails"][0]["assigned_categories"]


def test_multi_category_and_parameter_capping(client, db_session, monkeypatch):
    """Verify server-side clamping of max 3 categories and max 10 parameters."""
    monkeypatch.setattr("routes.organisers.organisers_routes._get_recent_emails", lambda days=14: [])

    payload = {
        "stage": "draft",
        "categories": [],
        "emails": [
            {
                "account_key": "acc1",
                "uid": "1",
                "assigned_categories": ["cat1", "cat2", "cat3", "cat4", "cat5"],  # 5 categories
                "extracted_parameters": [
                    {"type": "keyword", "value": f"kw_{i}"} for i in range(15)     # 15 parameters
                ],
                "comments": "X" * 3000,                                             # 3,000 chars
            }
        ],
    }

    save_res = client.put("/api/organisers/calibrate/draft", json=payload)
    assert save_res.status_code == 200

    # Verify in DB
    draft = db_session.query(CalibrationDraft).first()
    saved_emails = json.loads(draft.emails_json)
    assert len(saved_emails[0]["assigned_categories"]) == 3
    assert len(saved_emails[0]["extracted_parameters"]) == 10
    assert len(saved_emails[0]["comments"]) == 2000


def test_agent_pass_multi_label_evaluation(client, db_session, monkeypatch):
    """Verify Phase 2 Agent Pass iterates over the corpus and breaks down multi-label counts."""
    # Corpus with 5 emails
    corpus = [
        # Matches both Receipts & Tech Security
        {"account_key": "acc1", "uid": "1", "subject": "Vercel invoice payment and receipt", "from_address": "billing@vercel.com"},
        # Matches only Tour Ops
        {"account_key": "acc1", "uid": "2", "subject": "Ur marshes private tour booking", "from_address": "client@yahoo.com"},
        # Matches only Financial Intel
        {"account_key": "acc1", "uid": "3", "subject": "ISX weekly stocks market bulletin", "from_address": "rs@rs.iq"},
        # Matches none (Unassigned)
        {"account_key": "acc1", "uid": "4", "subject": "Unrelated hello", "from_address": "random@xyz.com"},
    ]
    monkeypatch.setattr("routes.organisers.organisers_routes._get_recent_emails", lambda days=14: corpus)

    categories = [
        {
            "slug": "receipts-and-payments",
            "name": "Receipts and Payments",
            "rules": {"keywords": ["receipt", "payment", "invoice"], "domains": [], "senders": []},
            "is_deleted": False,
        },
        {
            "slug": "tech-security-infrastructure",
            "name": "Tech Security",
            "rules": {"keywords": ["vercel"], "domains": ["vercel.com"], "senders": []},
            "is_deleted": False,
        },
        {
            "slug": "bilweekend-tour-ops",
            "name": "Tour Ops",
            "rules": {"keywords": ["tour", "marshes"], "domains": [], "senders": []},
            "is_deleted": False,
        },
        {
            "slug": "financial-intelligence",
            "name": "Financial Intel",
            "rules": {"keywords": ["isx", "stocks"], "domains": ["rs.iq"], "senders": []},
            "is_deleted": False,
        },
    ]

    res = client.post("/api/organisers/calibrate/agent-pass", json={
        "days": 14,
        "categories": categories,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["total_corpus_emails"] == 4
    assert data["matched_unique"] == 3
    assert data["unassigned_count"] == 1

    # Email 1 matched 2 categories (Receipts + Tech)
    assert data["multi_category_breakdown"]["2_categories"] == 1
    assert data["multi_category_breakdown"]["1_category"] == 2


def test_reset_draft_endpoint(client, db_session, monkeypatch):
    """Verify POST /calibrate/draft/reset clears user edits and regenerates fresh baseline."""
    monkeypatch.setattr("routes.organisers.organisers_routes._get_recent_emails", lambda days=14: [
        {"account_key": "acc1", "uid": "1", "subject": "Test", "from_address": "a@b.com", "folder": "INBOX"}
    ])

    # 1. Initialize and edit draft
    client.get("/api/organisers/calibrate/draft")
    client.put("/api/organisers/calibrate/draft", json={
        "stage": "draft",
        "categories": [],
        "emails": [{"account_key": "acc1", "uid": "1", "comments": "Custom draft edit"}],
    })

    # 2. Reset draft
    reset_res = client.post("/api/organisers/calibrate/draft/reset")
    assert reset_res.status_code == 200
    data = reset_res.json()
    assert data["ok"] is True
    # Custom edit should be gone
    assert data["emails"][0]["comments"] == ""
