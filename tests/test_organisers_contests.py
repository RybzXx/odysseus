"""tests/test_organisers_contests.py

Deterministic tests for contested categorisations:
- Match strength: a claim on a sender or domain is strong, on a keyword weak
- The boolean matcher and the detailed one never disagree
- Weak claims raise one contest each, and human-judged mail raises none
- Confirming leaves the rules deciding; rejecting writes an exclusion
- Editing an organiser's rules discards the confirmations they earned

Adheres to tests/TESTING_STANDARD.md:
- Deterministic, zero live network
- Behavior-first assertions
- In-memory database isolation
"""

import json
import uuid
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import (
    Base,
    CategorisationContest,
    EmailOrganiserOverride,
    WorkOrganiser,
    get_db,
)
from routes.organisers.organisers_routes import (
    _matches_rule,
    email_belongs_to_organiser,
    load_organiser_overrides,
    setup_organisers_routes,
)
from services.organisers.contests import (
    CONFIRMED,
    OPEN,
    REJECTED,
    reopen_contests_for_organiser,
    resolve_contest,
    scan_weak_matches,
)
from services.organisers.match_detail import STRONG, WEAK, evaluate_rules


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


def _organiser(db, *, slug="tour-ops", rules=None, accounts=None):
    org = WorkOrganiser(
        id=uuid.uuid4().hex,
        owner="admin",
        name=slug.replace("-", " ").title(),
        slug=slug,
        category_group="operations",
        icon="compass",
        color="#98c379",
        priority="normal",
        target_accounts=json.dumps(accounts or []),
        rules_json=json.dumps(rules or {"senders": [], "domains": [], "keywords": []}),
        ai_instructions="",
        sort_order=0,
        is_active=True,
    )
    db.add(org)
    db.commit()
    return org


def _email(uid="1", **over):
    email = {
        "uid": uid,
        "account_key": "acc1",
        "from_name": "Dave Mani",
        "from_address": "dave@example.com",
        "subject": "Our tour next month",
        "snippet": "Looking forward to it.",
        "folder": "INBOX",
    }
    email.update(over)
    return email


# ── Match strength ──────────────────────────────────────────────────────────

def test_domain_rule_is_a_strong_claim():
    match = evaluate_rules(_email(), [], {"domains": ["example.com"], "keywords": [], "senders": []})
    assert match.matched
    assert match.strength == STRONG
    assert match.domain_hits == ["example.com"]


def test_sender_rule_is_a_strong_claim():
    match = evaluate_rules(_email(), [], {"senders": ["dave mani"], "domains": [], "keywords": []})
    assert match.strength == STRONG
    assert match.sender_hits == ["dave mani"]


def test_keyword_alone_is_a_weak_claim():
    match = evaluate_rules(_email(), [], {"keywords": ["tour"], "senders": [], "domains": []})
    assert match.matched
    assert match.strength == WEAK
    assert match.is_weak
    assert match.keyword_hits == ["tour"]


def test_a_keyword_beside_a_domain_is_strong():
    """A weak signal does not weaken a claim that a strong one already carries."""
    match = evaluate_rules(
        _email(), [], {"keywords": ["tour"], "domains": ["example.com"], "senders": []},
    )
    assert match.strength == STRONG
    assert match.keyword_hits == ["tour"]


def test_an_organiser_with_no_criteria_claims_nothing():
    match = evaluate_rules(_email(), [], {"senders": [], "domains": [], "keywords": []})
    assert not match.matched
    assert not match.is_weak


def test_account_targeting_alone_is_a_strong_claim():
    match = evaluate_rules(_email(), ["acc1"], {"senders": [], "domains": [], "keywords": []})
    assert match.strength == STRONG
    assert match.account_only


def test_account_filter_still_rejects_other_accounts():
    match = evaluate_rules(_email(), ["other"], {"keywords": ["tour"], "senders": [], "domains": []})
    assert not match.matched


def test_recipients_count_only_on_sent_mail():
    sent = _email(folder="Sent", to_text="partner@adatours.com")
    received = _email(folder="INBOX", to_text="partner@adatours.com")
    rules = {"domains": ["adatours.com"], "senders": [], "keywords": []}
    assert evaluate_rules(sent, [], rules).matched
    assert not evaluate_rules(received, [], rules).matched


@pytest.mark.parametrize("rules", [
    {"senders": [], "domains": [], "keywords": []},
    {"senders": ["dave mani"], "domains": [], "keywords": []},
    {"senders": [], "domains": ["example.com"], "keywords": []},
    {"senders": [], "domains": [], "keywords": ["tour"]},
    {"senders": [], "domains": [], "keywords": ["absent"]},
])
def test_boolean_matcher_agrees_with_the_detailed_one(rules):
    """The membership decision and a contest over it cannot disagree."""
    email = _email()
    assert _matches_rule(email, [], rules) == evaluate_rules(email, [], rules).matched


# ── Raising contests ────────────────────────────────────────────────────────

def test_a_weak_match_raises_one_contest(db_session):
    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})
    opened = scan_weak_matches(db_session, "admin", [_email()], [org], {})
    assert opened == 1

    contest = db_session.query(CategorisationContest).one()
    assert contest.organiser_id == org.id
    assert contest.state == OPEN
    assert contest.source == "rule_weak"
    assert json.loads(contest.evidence_json)["keywords"] == ["tour"]
    assert "tour" in contest.reason


def test_a_strong_match_raises_nothing(db_session):
    org = _organiser(db_session, rules={"domains": ["example.com"], "senders": [], "keywords": []})
    assert scan_weak_matches(db_session, "admin", [_email()], [org], {}) == 0
    assert db_session.query(CategorisationContest).count() == 0


def test_scanning_twice_does_not_duplicate_a_contest(db_session):
    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})
    emails = [_email()]
    assert scan_weak_matches(db_session, "admin", emails, [org], {}) == 1
    assert scan_weak_matches(db_session, "admin", emails, [org], {}) == 0
    assert db_session.query(CategorisationContest).count() == 1


def test_mail_the_human_already_judged_is_not_contested(db_session):
    """A contest asks an open question; an override has already closed it."""
    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})
    overrides = {("acc1", "1"): {"assigned": org.id, "excluded": set()}}
    assert scan_weak_matches(db_session, "admin", [_email()], [org], overrides) == 0


def test_mail_excluded_from_this_organiser_is_not_contested(db_session):
    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})
    overrides = {("acc1", "1"): {"assigned": None, "excluded": {org.id}}}
    assert scan_weak_matches(db_session, "admin", [_email()], [org], overrides) == 0


def test_a_resolved_contest_is_not_raised_again(db_session):
    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})
    scan_weak_matches(db_session, "admin", [_email()], [org], {})
    contest = db_session.query(CategorisationContest).one()
    resolve_contest(db_session, "admin", contest.id, CONFIRMED)

    assert scan_weak_matches(db_session, "admin", [_email()], [org], {}) == 0
    assert db_session.query(CategorisationContest).count() == 1


# ── Resolving contests ──────────────────────────────────────────────────────

def test_confirming_writes_no_override(db_session):
    """The rules already produce this match; a second record would outlive them."""
    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})
    scan_weak_matches(db_session, "admin", [_email()], [org], {})
    contest = db_session.query(CategorisationContest).one()

    resolve_contest(db_session, "admin", contest.id, CONFIRMED)

    assert contest.state == CONFIRMED
    assert contest.resolved_at is not None
    assert db_session.query(EmailOrganiserOverride).count() == 0


def test_rejecting_removes_the_email_from_the_organiser(db_session):
    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})
    email = _email()
    rules = json.loads(org.rules_json)

    assert email_belongs_to_organiser(email, org, [], rules, load_organiser_overrides(db_session, "admin"))

    scan_weak_matches(db_session, "admin", [email], [org], {})
    contest = db_session.query(CategorisationContest).one()
    resolve_contest(db_session, "admin", contest.id, REJECTED)

    overrides = load_organiser_overrides(db_session, "admin")
    assert not email_belongs_to_organiser(email, org, [], rules, overrides)


def test_rejecting_twice_writes_one_exclusion(db_session):
    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})
    scan_weak_matches(db_session, "admin", [_email()], [org], {})
    contest = db_session.query(CategorisationContest).one()

    resolve_contest(db_session, "admin", contest.id, REJECTED)
    resolve_contest(db_session, "admin", contest.id, REJECTED)

    assert db_session.query(EmailOrganiserOverride).count() == 1


def test_an_unknown_verdict_is_a_caller_bug(db_session):
    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})
    scan_weak_matches(db_session, "admin", [_email()], [org], {})
    contest = db_session.query(CategorisationContest).one()

    with pytest.raises(ValueError):
        resolve_contest(db_session, "admin", contest.id, "maybe")


def test_resolving_an_absent_contest_is_a_caller_bug(db_session):
    with pytest.raises(LookupError):
        resolve_contest(db_session, "admin", "no-such-id", CONFIRMED)


def test_editing_rules_discards_the_confirmations_they_earned(db_session):
    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})
    scan_weak_matches(db_session, "admin", [_email()], [org], {})
    contest = db_session.query(CategorisationContest).one()
    resolve_contest(db_session, "admin", contest.id, CONFIRMED)

    discarded = reopen_contests_for_organiser(db_session, "admin", org.id)

    assert discarded == 1
    assert db_session.query(CategorisationContest).count() == 0


def test_editing_rules_keeps_rejections(db_session):
    """The exclusion a rejection wrote still stands, so the question stays shut."""
    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})
    scan_weak_matches(db_session, "admin", [_email()], [org], {})
    contest = db_session.query(CategorisationContest).one()
    resolve_contest(db_session, "admin", contest.id, REJECTED)

    assert reopen_contests_for_organiser(db_session, "admin", org.id) == 0
    assert db_session.query(CategorisationContest).count() == 1


# ── HTTP surface ────────────────────────────────────────────────────────────

def test_contests_route_reports_weak_claims(client, db_session):
    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})

    with patch(
        "routes.organisers.organisers_routes._get_recent_emails",
        return_value=[_email()],
    ):
        res = client.get("/api/organisers/contests")

    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    item = body["contests"][0]
    assert item["organiser_name"] == org.name
    assert item["subject"] == "Our tour next month"
    assert item["evidence"]["keywords"] == ["tour"]
    assert item["email_available"] is True


def test_contests_route_is_not_shadowed_by_the_organiser_lookup(client, db_session):
    """"/contests" is one path segment, like "/{id_or_slug}" — order decides."""
    with patch(
        "routes.organisers.organisers_routes._get_recent_emails",
        return_value=[],
    ):
        res = client.get("/api/organisers/contests")

    assert res.status_code == 200
    assert res.json()["contests"] == []


def test_resolve_route_records_the_verdict(client, db_session):
    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})
    scan_weak_matches(db_session, "admin", [_email()], [org], {})
    contest = db_session.query(CategorisationContest).one()

    res = client.post(
        f"/api/organisers/contests/{contest.id}/resolve",
        json={"verdict": "rejected"},
    )

    assert res.status_code == 200
    assert res.json()["state"] == REJECTED
    assert db_session.query(EmailOrganiserOverride).count() == 1


def test_resolve_route_rejects_an_unknown_verdict(client, db_session):
    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})
    scan_weak_matches(db_session, "admin", [_email()], [org], {})
    contest = db_session.query(CategorisationContest).one()

    res = client.post(
        f"/api/organisers/contests/{contest.id}/resolve",
        json={"verdict": "maybe"},
    )

    assert res.status_code == 400


def test_resolve_route_404s_on_an_absent_contest(client):
    res = client.post(
        "/api/organisers/contests/no-such-id/resolve",
        json={"verdict": "confirmed"},
    )
    assert res.status_code == 404


def test_bulk_resolve_settles_many_and_names_what_it_could_not(client, db_session):
    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})
    scan_weak_matches(
        db_session, "admin",
        [_email("1"), _email("2", subject="Another tour")],
        [org], {},
    )
    ids = [c.id for c in db_session.query(CategorisationContest).all()]
    assert len(ids) == 2

    res = client.post(
        "/api/organisers/contests/resolve",
        json={"ids": ids + ["no-such-id"], "verdict": "confirmed"},
    )

    assert res.status_code == 200
    body = res.json()
    assert sorted(body["resolved"]) == sorted(ids)
    assert body["missing"] == ["no-such-id"]


def test_bulk_resolve_rejects_an_unknown_verdict(client, db_session):
    res = client.post("/api/organisers/contests/resolve", json={"ids": [], "verdict": "maybe"})
    assert res.status_code == 400


def test_review_route_reports_a_configuration_fault_as_such(client, db_session, monkeypatch):
    """A pass that is switched off is the user's to fix, not a server error."""
    monkeypatch.setattr("src.settings.load_settings", lambda: {"organiser_review_enabled": False})
    monkeypatch.setattr("src.settings.get_user_setting", lambda k, o, d=None: d)
    _organiser(db_session, rules={"keywords": ["absent"], "senders": [], "domains": []})

    with patch(
        "routes.organisers.organisers_routes._get_recent_emails",
        return_value=[_email()],
    ):
        res = client.post("/api/organisers/contests/review")

    assert res.status_code == 409
    assert "switched off" in res.json()["detail"]


def test_review_endpoints_route_explains_an_empty_list(client, db_session):
    res = client.get("/api/organisers/contests/endpoints")

    assert res.status_code == 200
    body = res.json()
    assert body["endpoints"] == []
    assert "cloud models only" in body["note"]


def test_contest_payload_carries_the_claim_direction(client, db_session):
    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})

    with patch(
        "routes.organisers.organisers_routes._get_recent_emails",
        return_value=[_email()],
    ):
        res = client.get("/api/organisers/contests")

    assert res.json()["contests"][0]["claim"] == "asserted"
