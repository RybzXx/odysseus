"""tests/test_organisers_calibrate_adversarial.py

Adversarial test suite designed to break assumptions in the taxonomy calibration engine:
- Malformed, corrupted, and adversarial LLM outputs
- Primary Key collisions and cross-tenant ID reuse attacks
- Pathological email dictionaries (None values, missing keys, unicode bombs, SQL injection)
- Destructive/Broad keywords (spaces, empty strings, regex metacharacters)
- Massive batches and stress scenarios
"""

import json
import uuid
import pytest
from datetime import timedelta
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import (
    Base,
    CategorisationContest,
    WorkOrganiser,
    EmailOrganiserOverride,
    OverviewCache,
    get_db,
    utcnow_naive,
)
from routes.organisers.organisers_routes import (
    setup_organisers_routes,
    _sample_calibration_emails,
    _recalculate_taxonomy_coverage,
    _matches_rule,
    OrganiserRules,
    CalibratedCategory,
)
from services.organisers.review import (
    build_review_prompt,
    extract_json_object,
    raise_review_contests,
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
        # Default user is admin
        request.state.current_user = getattr(request.state, "current_user", "admin")
        request.state.api_token = False
        return await call_next(request)

    app.dependency_overrides[get_db] = lambda: db_session
    app.include_router(setup_organisers_routes())
    return TestClient(app)


# ================= ADVERSARIAL ATTACK 1: MALFORMED LLM RESPONSES =================

def test_adversarial_llm_syntax_errors_and_junk(db_session):
    """A hostile or broken reply must open no contest and raise nothing.

    The review pass is now the only place a model reply reaches this module.
    Its contract is that a failure adds no questions rather than bad ones, so
    the queue is measured after every payload.
    """
    emails = [{"uid": "1", "account_key": "acc1", "subject": "Test", "from_address": "a@b.com"}]
    org = WorkOrganiser(
        id="1", owner="admin", name="Ops", slug="ops",
        rules_json='{"keywords": ["test"], "senders": [], "domains": []}',
        target_accounts="[]",
    )

    hostile_payloads = [
        "",  # Empty
        "   ",  # Whitespace only
        "NOT JSON AT ALL",
        "```json\n{ truncated json ...",  # Incomplete JSON
        "```json\n[]\n```",  # List instead of dict
        '{"verdicts": "should be a list"}',  # Wrong type
        '{"verdicts": [{"category_slug": null, "uid": null}]}',  # Null fields
        '{"verdicts": [{"category_slug": "ghost-cat", "uid": "1", "belongs": true}]}',  # Unknown category
        '{"verdicts": [{"category_slug": "<script>alert(1)</script>", "uid": "1"}]}',  # XSS in slug
        '{"verdicts": [{"category_slug": "DROP TABLE work_organisers;--", "uid": "1"}]}',  # SQLi string
        "{'single_quotes': 'not_valid_json'}",  # Invalid python dict string
    ]

    for payload in hostile_payloads:
        assert isinstance(extract_json_object(payload), dict), f"Failed on: {payload}"
        opened = raise_review_contests(db_session, "admin", payload, emails, [org], {})
        assert opened == 0, f"Opened a contest on: {payload}"

    assert db_session.query(CategorisationContest).count() == 0


# ================= ADVERSARIAL ATTACK 2: PATHOLOGICAL EMAIL DATA =================

def test_adversarial_pathological_email_dictionaries():
    """Ensure sampling and recalculation survive completely bare or None-filled email dicts."""
    bare_emails = [
        {},  # Completely empty
        {"uid": None, "account_key": None, "subject": None, "from_name": None, "from_address": None, "folder": None, "snippet": None},
        {"uid": 12345, "account_key": 999, "subject": 0, "from_address": "bad_address"},  # Non-string fields
        {"uid": "safe", "account_key": "acc1", "subject": "Normal", "from_address": "ok@test.com", "folder": "INBOX"},
    ]

    # Sampling must not crash
    sampled = _sample_calibration_emails(bare_emails, limit=5)
    assert len(sampled) == 4

    # Prompt building must not crash
    prompt = build_review_prompt(sampled, [])
    assert len(prompt) == 2
    assert isinstance(prompt[1]["content"], str)

    # Recalculation must not crash
    cat = CalibratedCategory(slug="test", name="Test", rules=OrganiserRules(keywords=["normal"], domains=["test.com"]))
    stats = _recalculate_taxonomy_coverage([cat], bare_emails, overrides={})
    assert stats["total_emails"] == 4
    assert stats["matched_unique"] == 1


# ================= ADVERSARIAL ATTACK 3: DANGEROUS / BROAD KEYWORDS =================

def test_adversarial_broad_keywords_rule_matching():
    """Verify that empty strings, pure whitespace, or dangerous tokens do not trigger universal matches."""
    email = {
        "account_key": "acc1",
        "uid": "1",
        "subject": "Executive briefing",
        "from_name": "Boss",
        "from_address": "boss@corp.com",
        "folder": "INBOX",
        "snippet": "Here is the summary.",
    }

    # Empty keyword
    assert _matches_rule(email, [], {"keywords": [""]}) is False

    # Regex metacharacters should NOT be treated as regexes (literal substring match only)
    assert _matches_rule(email, [], {"keywords": [".*"]}) is False
    assert _matches_rule(email, [], {"keywords": ["[a-z]+"]}) is False
    assert _matches_rule(email, [], {"domains": [".*corp.com"]}) is False


# ================= ADVERSARIAL ATTACK 4: CROSS-TENANT PRIMARY KEY COLLISION IN APPLY =================

def test_adversarial_apply_cross_tenant_primary_key_collision(client, db_session, monkeypatch):
    """
    ATTACK: User A attempts to overwrite User B's organiser by submitting User B's UUID in /apply.
    The system must NOT corrupt User B's organiser, nor crash with an unhandled IntegrityError.
    """
    monkeypatch.setattr("routes.organisers.organisers_routes._get_recent_emails", lambda days=14: [])

    # Victim user: "alice"
    alice_org = WorkOrganiser(
        id="alice-org-uuid-1234",
        owner="alice",
        name="Alice Secrets",
        slug="alice-secrets",
        description="Private Alice Work",
        rules_json='{"keywords": ["secret"]}',
    )
    db_session.add(alice_org)
    db_session.commit()

    # Attacker: "admin" tries to apply a category with alice's ID
    payload = {
        "clear_overview_cache": False,
        "categories": [
            {
                "id": "alice-org-uuid-1234",  # Attacker attempts to target Alice's ID
                "slug": "attacker-category",
                "name": "Attacker Hijack",
                "rules": {"keywords": ["hijack"]},
                "is_new": True,
            }
        ]
    }

    # Let's see how the endpoint behaves:
    res = client.post("/api/organisers/calibrate/apply", json=payload)
    
    # Alice's organiser must remain completely untouched
    victim = db_session.query(WorkOrganiser).filter(WorkOrganiser.id == "alice-org-uuid-1234").first()
    assert victim.owner == "alice"
    assert victim.name == "Alice Secrets"
    assert "secret" in victim.rules_json
