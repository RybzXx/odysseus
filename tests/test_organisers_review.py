"""tests/test_organisers_review.py

Deterministic tests for the organiser review pass and the states it feeds:
- Only cloud endpoints may serve the pass, checked at pick and at call
- The batch spends tokens on doubt, never on a strong match
- A verdict that agrees with the rules opens nothing
- A disagreement opens a contest whose direction decides what a verdict does
- The four email states partition the corpus, and the counts follow them
- The seed taxonomy classifies by its own rules, with one catch-all

Adheres to tests/TESTING_STANDARD.md:
- Deterministic, zero live network
- Behavior-first assertions
- In-memory database isolation
"""

import json
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base, CategorisationContest, ModelEndpoint, WorkOrganiser
from services.organisers.contests import (
    ASSERTED,
    CONFIRMED,
    PROPOSED,
    REJECTED,
    resolve_contest,
)
from services.organisers.email_state import (
    ASSIGNED,
    DECLINED,
    PENDING,
    WEAK_MATCH,
    count_states,
    derive_states,
)
from services.organisers.review import (
    ReviewUnavailable,
    build_review_prompt,
    cloud_endpoints,
    extract_json_object,
    is_cloud_endpoint,
    load_reviewed,
    raise_review_contests,
    record_reviews,
    resolve_review_route,
    rules_digest,
    select_review_batch,
)
from services.organisers.seed_taxonomy import (
    catch_all_slug,
    classify,
    load_seed_taxonomy,
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


def _organiser(db, *, slug="ops", rules=None, accounts=None):
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


def _endpoint(db, *, name, base_url, kind="auto", enabled=True):
    ep = ModelEndpoint(
        id=uuid.uuid4().hex,
        name=name,
        base_url=base_url,
        is_enabled=enabled,
        endpoint_kind=kind,
        model_type="llm",
    )
    db.add(ep)
    db.commit()
    return ep


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


# ── The cloud-only gate ─────────────────────────────────────────────────────

@pytest.mark.parametrize("url,kind,expected", [
    ("https://api.openai.com/v1", "auto", True),
    ("https://api.anthropic.com", "api", True),
    ("http://localhost:1234/v1", "auto", False),
    ("http://127.0.0.1:8000/v1", "auto", False),
    ("http://192.168.1.50:8000/v1", "auto", False),
    ("http://my-box.local:8000/v1", "auto", False),
    ("http://host.docker.internal:1234/v1", "auto", False),
    # A globally routable host the admin has marked as self-hosted.
    ("https://models.example.com/v1", "local", False),
])
def test_only_offsite_routes_count_as_cloud(url, kind, expected):
    assert is_cloud_endpoint(url, kind) is expected


def test_local_endpoints_are_absent_from_the_picker(db_session):
    cloud = _endpoint(db_session, name="OpenAI", base_url="https://api.openai.com/v1")
    _endpoint(db_session, name="LM Studio", base_url="http://localhost:1234/v1")

    offered = cloud_endpoints(db_session, None)

    assert [ep.id for ep in offered] == [cloud.id]


def test_a_disabled_cloud_endpoint_is_not_offered(db_session):
    _endpoint(db_session, name="Old", base_url="https://api.openai.com/v1", enabled=False)
    assert cloud_endpoints(db_session, None) == []


def test_the_pass_refuses_when_switched_off(db_session, monkeypatch):
    monkeypatch.setattr(
        "src.settings.load_settings",
        lambda: {"organiser_review_enabled": False},
    )
    monkeypatch.setattr("src.settings.get_user_setting", lambda k, o, d=None: d)

    with pytest.raises(ReviewUnavailable, match="switched off"):
        resolve_review_route(db_session, "admin")


def test_the_pass_refuses_a_local_endpoint_chosen_earlier(db_session, monkeypatch):
    """The picker hides local endpoints, but one can be edited to become local."""
    local = _endpoint(db_session, name="LM Studio", base_url="http://localhost:1234/v1")
    settings = {
        "organiser_review_enabled": True,
        "organiser_review_endpoint_id": local.id,
        "organiser_review_model": "llama-3",
    }
    monkeypatch.setattr("src.settings.load_settings", lambda: settings)
    monkeypatch.setattr("src.settings.get_user_setting", lambda k, o, d=None: settings.get(k, d))

    with pytest.raises(ReviewUnavailable, match="cloud models only"):
        resolve_review_route(db_session, "admin")


def test_the_pass_refuses_when_no_model_is_chosen(db_session, monkeypatch):
    settings = {"organiser_review_enabled": True, "organiser_review_endpoint_id": "", "organiser_review_model": ""}
    monkeypatch.setattr("src.settings.load_settings", lambda: settings)
    monkeypatch.setattr("src.settings.get_user_setting", lambda k, o, d=None: settings.get(k, d))

    with pytest.raises(ReviewUnavailable, match="No endpoint and model"):
        resolve_review_route(db_session, "admin")


# ── What the pass looks at ──────────────────────────────────────────────────

def test_a_strong_match_costs_no_tokens(db_session):
    org = _organiser(db_session, rules={"domains": ["example.com"], "senders": [], "keywords": []})
    assert select_review_batch([_email()], [org], {}) == []


def test_weak_matches_and_residue_reach_the_batch(db_session):
    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})
    weak = _email("1")
    residue = _email("2", subject="Unrelated", snippet="")

    batch = select_review_batch([weak, residue], [org], {})

    assert {e["uid"] for e in batch} == {"1", "2"}


def test_mail_the_human_assigned_is_left_alone(db_session):
    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})
    overrides = {("acc1", "1"): {"assigned": org.id, "excluded": set()}}
    assert select_review_batch([_email()], [org], overrides) == []


def test_the_batch_is_bounded(db_session):
    org = _organiser(db_session, rules={"keywords": ["nothing"], "senders": [], "domains": []})
    many = [_email(str(i), subject="Unrelated", snippet="") for i in range(200)]
    assert len(select_review_batch(many, [org], {}, limit=80)) == 80


def test_the_prompt_offers_no_way_to_invent_a_category(db_session):
    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})
    system, user = build_review_prompt([_email()], [org])

    assert system["role"] == "system"
    assert "belongs" in system["content"]
    assert "is_new" not in system["content"]
    assert org.slug in user["content"]


# ── Turning verdicts into contests ──────────────────────────────────────────

def _reply(**fields):
    return json.dumps({"verdicts": [fields]})


def test_agreeing_with_the_rules_opens_nothing(db_session):
    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})
    reply = _reply(account_key="acc1", uid="1", category_slug=org.slug, belongs=True, reason="It is a tour.")

    assert raise_review_contests(db_session, "admin", reply, [_email()], [org], {}) == 0


def test_disputing_a_rule_opens_an_asserted_contest(db_session):
    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})
    reply = _reply(account_key="acc1", uid="1", category_slug=org.slug, belongs=False, reason="A newsletter.")

    assert raise_review_contests(db_session, "admin", reply, [_email()], [org], {}) == 1

    contest = db_session.query(CategorisationContest).one()
    assert contest.claim == ASSERTED
    assert contest.source == "llm"
    assert contest.reason == "A newsletter."


def test_naming_a_category_for_residue_opens_a_proposed_contest(db_session):
    org = _organiser(db_session, rules={"keywords": ["absent"], "senders": [], "domains": []})
    reply = _reply(account_key="acc1", uid="1", category_slug=org.slug, belongs=True, reason="Clearly ops.")

    assert raise_review_contests(db_session, "admin", reply, [_email()], [org], {}) == 1
    assert db_session.query(CategorisationContest).one().claim == PROPOSED


def test_a_verdict_naming_an_unknown_category_is_ignored(db_session):
    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})
    reply = _reply(account_key="acc1", uid="1", category_slug="ghost", belongs=False)

    assert raise_review_contests(db_session, "admin", reply, [_email()], [org], {}) == 0


def test_a_verdict_naming_an_unknown_message_is_ignored(db_session):
    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})
    reply = _reply(account_key="acc1", uid="999", category_slug=org.slug, belongs=False)

    assert raise_review_contests(db_session, "admin", reply, [_email()], [org], {}) == 0


def test_confirming_a_proposal_files_the_email(db_session):
    """Nothing else would place it, so the confirmation has to write the link."""
    from routes.organisers.organisers_routes import (
        email_belongs_to_organiser,
        load_organiser_overrides,
    )

    org = _organiser(db_session, rules={"keywords": ["absent"], "senders": [], "domains": []})
    reply = _reply(account_key="acc1", uid="1", category_slug=org.slug, belongs=True)
    raise_review_contests(db_session, "admin", reply, [_email()], [org], {})
    contest = db_session.query(CategorisationContest).one()

    resolve_contest(db_session, "admin", contest.id, CONFIRMED)

    overrides = load_organiser_overrides(db_session, "admin")
    assert email_belongs_to_organiser(_email(), org, [], json.loads(org.rules_json), overrides)


def test_rejecting_a_proposal_changes_nothing(db_session):
    from core.database import EmailOrganiserOverride

    org = _organiser(db_session, rules={"keywords": ["absent"], "senders": [], "domains": []})
    reply = _reply(account_key="acc1", uid="1", category_slug=org.slug, belongs=True)
    raise_review_contests(db_session, "admin", reply, [_email()], [org], {})
    contest = db_session.query(CategorisationContest).one()

    resolve_contest(db_session, "admin", contest.id, REJECTED)

    assert db_session.query(EmailOrganiserOverride).count() == 0


def test_extract_json_object_survives_fences_and_prose():
    assert extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json_object('Sure! {"a": 1} Hope that helps.') == {"a": 1}
    assert extract_json_object("not json") == {}
    assert extract_json_object("[1, 2]") == {}


# ── The review record ───────────────────────────────────────────────────────

def test_a_message_read_and_accepted_is_still_recorded(db_session):
    """Contests record disagreement only, so agreement needs its own record."""
    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})
    digest = rules_digest([org])

    record_reviews(db_session, "admin", [("acc1", "1")], digest)

    assert load_reviewed(db_session, "admin", digest) == {("acc1", "1")}


def test_a_reviewed_message_is_not_read_again(db_session):
    org = _organiser(db_session, rules={"keywords": ["absent"], "senders": [], "domains": []})
    digest = rules_digest([org])
    record_reviews(db_session, "admin", [("acc1", "1")], digest)

    batch = select_review_batch(
        [_email()], [org], {}, already_reviewed=load_reviewed(db_session, "admin", digest),
    )

    assert batch == []


def test_changing_the_rules_makes_a_message_worth_reading_again(db_session):
    org = _organiser(db_session, rules={"keywords": ["absent"], "senders": [], "domains": []})
    record_reviews(db_session, "admin", [("acc1", "1")], rules_digest([org]))

    org.rules_json = json.dumps({"keywords": ["different"], "senders": [], "domains": []})
    db_session.commit()

    assert load_reviewed(db_session, "admin", rules_digest([org])) == set()


def test_the_digest_ignores_edits_a_reviewer_never_saw(db_session):
    """A colour change costs no tokens; a rule change does."""
    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})
    before = rules_digest([org])

    org.color = "#ffffff"
    org.priority = "high"
    db_session.commit()

    assert rules_digest([org]) == before


def test_the_digest_ignores_organiser_order(db_session):
    a = _organiser(db_session, slug="a", rules={"keywords": ["x"], "senders": [], "domains": []})
    b = _organiser(db_session, slug="b", rules={"keywords": ["y"], "senders": [], "domains": []})

    assert rules_digest([a, b]) == rules_digest([b, a])


def test_recording_a_review_twice_keeps_one_row(db_session):
    from core.database import MessageReview

    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})
    digest = rules_digest([org])

    record_reviews(db_session, "admin", [("acc1", "1")], digest)
    record_reviews(db_session, "admin", [("acc1", "1")], digest)

    assert db_session.query(MessageReview).count() == 1


# ── The four states ─────────────────────────────────────────────────────────

def test_states_partition_the_corpus(db_session):
    org = _organiser(db_session, rules={"domains": ["example.com"], "keywords": ["tour"], "senders": []})
    strong = _email("1")
    weak = _email("2", from_address="a@other.com", subject="A tour idea")
    residue = _email("3", from_address="a@other.com", subject="Nothing", snippet="")
    declined = _email("4", from_address="a@other.com", subject="Nothing", snippet="")

    states = derive_states(
        [strong, weak, residue, declined], [org], {}, reviewed_keys=[("acc1", "4")],
    )

    assert states[("acc1", "1")].state == ASSIGNED
    assert states[("acc1", "2")].state == WEAK_MATCH
    assert states[("acc1", "3")].state == PENDING
    assert states[("acc1", "4")].state == DECLINED


def test_counts_add_up(db_session):
    org = _organiser(db_session, rules={"domains": ["example.com"], "keywords": ["tour"], "senders": []})
    emails = [
        _email("1"),
        _email("2", from_address="a@other.com", subject="A tour idea"),
        _email("3", from_address="a@other.com", subject="Nothing", snippet=""),
    ]

    counts = count_states(derive_states(emails, [org], {}))

    assert counts["categorised"] + counts["uncategorised"] == counts["total"] == 3
    assert counts[ASSIGNED] == 1 and counts[WEAK_MATCH] == 1 and counts[PENDING] == 1


def test_a_human_assignment_settles_the_state(db_session):
    org = _organiser(db_session, rules={"senders": [], "domains": [], "keywords": []})
    overrides = {("acc1", "1"): {"assigned": org.id, "excluded": set()}}

    states = derive_states([_email()], [org], overrides)

    assert states[("acc1", "1")].state == ASSIGNED
    assert states[("acc1", "1")].evidence["source"] == "human"


def test_an_exclusion_removes_the_holder(db_session):
    org = _organiser(db_session, rules={"domains": ["example.com"], "senders": [], "keywords": []})
    overrides = {("acc1", "1"): {"assigned": None, "excluded": {org.id}}}

    assert derive_states([_email()], [org], overrides)[("acc1", "1")].state == PENDING


# ── The pass end to end ─────────────────────────────────────────────────────

def _configure_pass(db, monkeypatch, endpoint):
    settings = {
        "organiser_review_enabled": True,
        "organiser_review_endpoint_id": endpoint.id,
        "organiser_review_model": "gpt-test",
    }
    monkeypatch.setattr("src.settings.load_settings", lambda: settings)
    monkeypatch.setattr("src.settings.get_user_setting", lambda k, o, d=None: settings.get(k, d))
    monkeypatch.setattr("src.endpoint_resolver.resolve_endpoint_runtime",
                        lambda ep, owner=None: (ep.base_url, "key"))


@pytest.mark.asyncio
async def test_a_pass_opens_contests_and_records_what_it_read(db_session, monkeypatch):
    from core.database import MessageReview
    from services.organisers.review import run_review_pass

    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})
    ep = _endpoint(db_session, name="OpenAI", base_url="https://api.openai.com/v1")
    _configure_pass(db_session, monkeypatch, ep)

    reply = _reply(account_key="acc1", uid="1", category_slug=org.slug,
                   belongs=False, reason="A newsletter, not a booking.")

    async def _fake_call(*args, **kwargs):
        return reply

    monkeypatch.setattr("src.llm_core.llm_call_async", _fake_call)

    summary = await run_review_pass(db_session, "admin", [_email()], [org], {})

    assert summary["examined"] == 1
    assert summary["opened"] == 1
    assert db_session.query(CategorisationContest).one().claim == ASSERTED
    assert db_session.query(MessageReview).count() == 1


@pytest.mark.asyncio
async def test_a_failed_call_marks_nothing_reviewed(db_session, monkeypatch):
    """Otherwise a transport blip would silently retire the message for good."""
    from core.database import MessageReview
    from services.organisers.review import run_review_pass

    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})
    ep = _endpoint(db_session, name="OpenAI", base_url="https://api.openai.com/v1")
    _configure_pass(db_session, monkeypatch, ep)

    async def _boom(*args, **kwargs):
        raise RuntimeError("upstream is down")

    monkeypatch.setattr("src.llm_core.llm_call_async", _boom)

    with pytest.raises(RuntimeError):
        await run_review_pass(db_session, "admin", [_email()], [org], {})

    assert db_session.query(MessageReview).count() == 0
    assert db_session.query(CategorisationContest).count() == 0


@pytest.mark.asyncio
async def test_a_second_pass_over_unchanged_mail_sends_nothing(db_session, monkeypatch):
    from services.organisers.review import run_review_pass

    org = _organiser(db_session, rules={"keywords": ["tour"], "senders": [], "domains": []})
    ep = _endpoint(db_session, name="OpenAI", base_url="https://api.openai.com/v1")
    _configure_pass(db_session, monkeypatch, ep)

    calls = []

    async def _counting_call(*args, **kwargs):
        calls.append(1)
        return json.dumps({"verdicts": []})

    monkeypatch.setattr("src.llm_core.llm_call_async", _counting_call)

    await run_review_pass(db_session, "admin", [_email()], [org], {})
    second = await run_review_pass(db_session, "admin", [_email()], [org], {})

    assert len(calls) == 1
    assert second["examined"] == 0


# ── The seed taxonomy ───────────────────────────────────────────────────────

def test_the_seed_has_exactly_one_catch_all():
    entries = load_seed_taxonomy()
    catch_alls = [e for e in entries if e.get("catch_all")]

    assert len(catch_alls) == 1
    assert catch_all_slug() == catch_alls[0]["slug"]


def test_the_seed_is_ordered_by_precedence():
    orders = [e.get("order", 0) for e in load_seed_taxonomy()]
    assert orders == sorted(orders)


def test_every_email_lands_somewhere():
    slug, reason, _ = classify({"subject": "Nothing recognisable", "from_address": "a@b.invalid"})
    assert slug == catch_all_slug()
    assert reason


def test_a_receipt_beats_the_catch_all():
    slug, _, match = classify({
        "subject": "Your receipt from Stripe",
        "from_address": "billing@stripe.com",
        "snippet": "",
    })
    assert slug == "receipts-and-payments"
    assert match.matched


def test_the_classifier_reads_the_category_it_places_into():
    """The rules consulted are the ones the seed declares, not a second copy."""
    from services.organisers.seed_taxonomy import seed_rules
    from services.organisers.match_detail import evaluate_rules

    email = {"subject": "Invoice attached", "from_address": "a@b.invalid", "snippet": ""}
    slug, _, _ = classify(email)

    assert evaluate_rules(email, [], seed_rules(slug)).matched
