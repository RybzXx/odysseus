"""tests/test_organisers_calibrate.py

Deterministic tests for the AI email taxonomy calibration workflow:
- Extraction & prompt building
- LLM response parsing into candidate categories and parameter rules
- Pure deterministic recalculation across corpus
- Codification to WorkOrganiser and OverviewCache reset
- Human override precedence preservation

Adheres to tests/TESTING_STANDARD.md:
- Deterministic, zero live network
- Behavior-first assertions
- In-memory database isolation
"""

import json
import uuid
import pytest
from unittest.mock import AsyncMock, patch
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
    get_db,
    utcnow_naive,
)
from routes.organisers.organisers_routes import (
    setup_organisers_routes,
    _sample_calibration_emails,
    _build_calibration_prompt,
    _parse_calibration_llm_response,
    _recalculate_taxonomy_coverage,
    OrganiserRules,
    CalibratedCategory,
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


def test_sample_calibration_emails_balances_inbound_and_outbound():
    emails = []
    for i in range(20):
        emails.append({
            "uid": str(i),
            "account_key": "acc1",
            "from_address": f"sender{i}@example.com",
            "folder": "INBOX",
        })
    for i in range(20, 30):
        emails.append({
            "uid": str(i),
            "account_key": "acc1",
            "from_address": "me@mycompany.com",
            "folder": "Sent",
        })

    sampled = _sample_calibration_emails(emails, limit=10)
    assert len(sampled) == 10

    outbound_count = sum(1 for e in sampled if e["folder"].lower() == "sent")
    inbound_count = sum(1 for e in sampled if e["folder"].lower() != "sent")

    assert outbound_count >= 2
    assert inbound_count >= 5


def test_parse_calibration_llm_response_extracts_rules_and_assignments():
    mock_llm_output = """```json
{
  "categories": [
    {
      "slug": "receipts-and-payments",
      "name": "Receipts and Payments",
      "description": "Invoices, payment receipts, and billing notifications.",
      "category_group": "finance"
    },
    {
      "slug": "developer-infrastructure",
      "name": "Developer Infrastructure",
      "description": "Cloud hosting, GitHub, and dev services.",
      "category_group": "tech"
    }
  ],
  "assignments": [
    {
      "uid": "101",
      "account_key": "acc1",
      "category_slug": "receipts-and-payments",
      "extracted_senders": ["Stripe Billing"],
      "extracted_domains": ["stripe.com"],
      "extracted_keywords": ["invoice", "receipt"],
      "reasoning": "Invoice confirmation from Stripe."
    },
    {
      "uid": "102",
      "account_key": "acc1",
      "category_slug": "developer-infrastructure",
      "extracted_senders": ["GitHub Notifications"],
      "extracted_domains": ["github.com"],
      "extracted_keywords": ["security alert"],
      "reasoning": "Repository security advisory."
    }
  ]
}
```"""

    sampled = [
        {"uid": "101", "account_key": "acc1", "subject": "Stripe invoice ready", "from_name": "Stripe", "from_address": "billing@stripe.com", "snippet": "Your receipt for $49"},
        {"uid": "102", "account_key": "acc1", "subject": "Security alert on repo", "from_name": "GitHub", "from_address": "support@github.com", "snippet": "Advisory GHSA-1234"},
        {"uid": "103", "account_key": "acc1", "subject": "Unmatched newsletter", "from_name": "News", "from_address": "news@daily.com", "snippet": "Morning briefing"},
    ]

    existing_org = WorkOrganiser(
        id="org1",
        owner="admin",
        name="Receipts and Payments",
        slug="receipts-and-payments",
        description="",
        rules_json="{}",
    )

    rows, categories = _parse_calibration_llm_response(mock_llm_output, sampled, [existing_org])

    assert len(categories) == 2
    receipts_cat = next(c for c in categories if c.slug == "receipts-and-payments")
    assert "stripe.com" in receipts_cat.rules.domains
    assert "invoice" in receipts_cat.rules.keywords

    dev_cat = next(c for c in categories if c.slug == "developer-infrastructure")
    assert dev_cat.is_new is True
    assert "github.com" in dev_cat.rules.domains

    assert len(rows) == 3
    row101 = next(r for r in rows if r.uid == "101")
    assert row101.proposed_category == "receipts-and-payments"
    assert row101.reasoning == "Invoice confirmation from Stripe."

    # Email 103 was not assigned by LLM, should gracefully degrade to pending calibration
    row103 = next(r for r in rows if r.uid == "103")
    assert row103.proposed_category == ""
    assert "daily.com" in row103.extracted_domains


def test_recalculate_pure_deterministic():
    emails = [
        {"account_key": "acc1", "uid": "1", "from_name": "Stripe", "from_address": "billing@stripe.com", "subject": "Receipt #123", "folder": "INBOX", "snippet": ""},
        {"account_key": "acc1", "uid": "2", "from_name": "GitHub", "from_address": "no-reply@github.com", "subject": "SSH Key Added", "folder": "INBOX", "snippet": ""},
        {"account_key": "acc1", "uid": "3", "from_name": "Friend", "from_address": "friend@gmail.com", "subject": "Weekend trip", "folder": "INBOX", "snippet": "Let's meet"},
    ]

    categories = [
        CalibratedCategory(
            id="c1",
            slug="finance",
            name="Finance",
            rules=OrganiserRules(domains=["stripe.com"], keywords=["receipt"]),
        ),
        CalibratedCategory(
            id="c2",
            slug="tech",
            name="Tech",
            rules=OrganiserRules(domains=["github.com"], keywords=["ssh"]),
        ),
    ]

    res = _recalculate_taxonomy_coverage(categories, emails, overrides={})
    assert res["total_emails"] == 3
    assert res["matched_unique"] == 2
    assert res["unassigned_count"] == 1
    assert res["categories"][0].coverage_count == 1
    assert res["categories"][1].coverage_count == 1
    assert res["match_map"]["acc1:1"] == ["finance"]
    assert res["match_map"]["acc1:2"] == ["tech"]
    assert "acc1:3" not in res["match_map"]


def test_calibrate_recalculate_endpoint(client, monkeypatch):
    mock_emails = [
        {"account_key": "acc1", "uid": "10", "from_name": "Booking", "from_address": "res@hotel.com", "subject": "Quotation for 37 pax", "folder": "INBOX", "snippet": ""},
        {"account_key": "acc1", "uid": "20", "from_name": "Random", "from_address": "hi@random.com", "subject": "Hello", "folder": "INBOX", "snippet": ""},
    ]
    monkeypatch.setattr("routes.organisers.organisers_routes._get_recent_emails", lambda days=14: mock_emails)

    payload = {
        "days": 14,
        "categories": [
            {
                "slug": "operations",
                "name": "Tour Operations",
                "rules": {
                    "senders": [],
                    "keywords": ["quotation", "pax"],
                    "domains": ["hotel.com"],
                },
            }
        ]
    }

    res = client.post("/api/organisers/calibrate/recalculate", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["matched_unique"] == 1
    assert data["unassigned_count"] == 1
    assert data["categories"][0]["coverage_count"] == 1


def test_calibrate_apply_endpoint_updates_db_and_clears_cache(client, db_session, monkeypatch):
    monkeypatch.setattr("routes.organisers.organisers_routes._get_recent_emails", lambda days=14: [])

    # Create an existing organiser to update
    existing_org = WorkOrganiser(
        id=uuid.uuid4().hex,
        owner="admin",
        name="Old Operations",
        slug="operations",
        description="Old description",
        rules_json='{"senders": ["old"]}',
        sort_order=1,
    )
    db_session.add(existing_org)

    # Insert a row into overview cache
    from datetime import timedelta
    db_session.add(OverviewCache(
        id="admin:overview",
        owner="admin",
        payload_json='{"status": "stale"}',
        expires_at=utcnow_naive() + timedelta(hours=1),
    ))
    db_session.commit()

    assert db_session.query(OverviewCache).count() == 1

    payload = {
        "clear_overview_cache": True,
        "categories": [
            {
                "id": existing_org.id,
                "slug": "operations",
                "name": "Bil Weekend Tour Operations",
                "description": "All booking quotes and hotel communications.",
                "category_group": "operations",
                "color": "#61afef",
                "icon": "briefcase",
                "priority": "critical",
                "rules": {
                    "senders": ["Adrian"],
                    "keywords": ["pax", "quotation"],
                    "domains": ["adatours.com"],
                },
                "ai_instructions": "Prioritize direct traveler inquiries.",
                "is_new": False,
            },
            {
                "slug": "receipts-and-payments",
                "name": "Receipts & Invoices",
                "description": "Incoming receipts and payment processing.",
                "category_group": "finance",
                "rules": {
                    "senders": ["Stripe"],
                    "keywords": ["invoice", "receipt"],
                    "domains": ["stripe.com"],
                },
                "is_new": True,
            }
        ]
    }

    res = client.post("/api/organisers/calibrate/apply", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["created"] == 1
    assert data["updated"] == 1

    # Overview cache must be cleared
    assert db_session.query(OverviewCache).count() == 0

    # Existing organiser must have updated rules and description
    updated_org = db_session.query(WorkOrganiser).filter(WorkOrganiser.slug == "operations").first()
    assert updated_org.name == "Bil Weekend Tour Operations"
    assert updated_org.description == "All booking quotes and hotel communications."
    rules = json.loads(updated_org.rules_json)
    assert "adatours.com" in rules["domains"]
    assert "pax" in rules["keywords"]

    # New organiser must be created
    new_org = db_session.query(WorkOrganiser).filter(WorkOrganiser.slug == "receipts-and-payments").first()
    assert new_org is not None
    assert new_org.category_group == "finance"
    new_rules = json.loads(new_org.rules_json)
    assert "stripe.com" in new_rules["domains"]


def test_human_overrides_survive_calibration(client, db_session, monkeypatch):
    """Verify that explicit EmailOrganiserOverride takes precedence over calibrated rules."""
    org_ops = WorkOrganiser(
        id="org_ops",
        owner="admin",
        name="Operations",
        slug="operations",
        rules_json='{"keywords": ["tour"]}',
    )
    org_finance = WorkOrganiser(
        id="org_finance",
        owner="admin",
        name="Finance",
        slug="finance",
        rules_json='{"keywords": ["payment"]}',
    )
    db_session.add_all([org_ops, org_finance])

    # Human explicitly files email under Finance even though subject has "tour"
    override = EmailOrganiserOverride(
        id="ov1",
        owner="admin",
        account_key="acc1",
        uid="100",
        organiser_id="org_finance",
    )
    db_session.add(override)
    db_session.commit()

    email = {
        "account_key": "acc1",
        "uid": "100",
        "subject": "Tour invoice payment",
        "from_address": "client@example.com",
        "folder": "INBOX",
        "snippet": "",
    }
    monkeypatch.setattr("routes.organisers.organisers_routes._get_recent_emails", lambda days=14: [email])

    payload = {
        "days": 14,
        "categories": [
            {"id": "org_ops", "slug": "operations", "name": "Operations", "rules": {"keywords": ["tour"]}},
            {"id": "org_finance", "slug": "finance", "name": "Finance", "rules": {"keywords": ["payment"]}},
        ]
    }

    res = client.post("/api/organisers/calibrate/recalculate", json=payload)
    data = res.json()
    assert data["ok"] is True
    # Human override filed it under finance, so operations does NOT claim it
    assert data["match_map"]["acc1:100"] == ["finance"]
