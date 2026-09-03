"""Human corrections to an email's organiser outrank the matching rules.

Membership used to be recomputed from rules on every request and stored
nowhere, so a misfiled email could not be corrected — there was no record to
edit. These pin the record and its precedence: an explicit filing wins, then an
explicit removal, then the rules.
"""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.database as db
from routes.organisers.organisers_routes import (
    email_belongs_to_organiser,
    email_key,
    load_organiser_overrides,
)

ACCOUNTS = ["acc-1"]
RULES = {"senders": ["Adrian"], "keywords": ["quotation"], "domains": []}


class _Org:
    def __init__(self, org_id="org-1"):
        self.id = org_id
        self.slug = "bilweekend_ops"


def _email(uid="101", sender="Adrian Matache", subject="Tour quotation"):
    return {
        "account_key": "acc-1",
        "uid": uid,
        "from_name": sender,
        "from_address": f"{sender.split()[0].lower()}@example.invalid",
        "subject": subject,
        "snippet": "",
    }


@pytest.fixture
def session(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'app.db').as_posix()}")
    db.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _add_override(session, *, uid, organiser_id=None, excluded_from_id=None):
    session.add(db.EmailOrganiserOverride(
        id=uuid.uuid4().hex,
        owner="admin",
        account_key="acc-1",
        uid=uid,
        organiser_id=organiser_id,
        excluded_from_id=excluded_from_id,
    ))
    session.commit()


def test_email_key_identifies_a_message_by_account_and_uid():
    assert email_key(_email()) == ("acc-1", "101")
    # The overview payload names the account differently; both must resolve.
    assert email_key({"account_id": "acc-1", "uid": "101"}) == ("acc-1", "101")


def test_rules_decide_when_nobody_has_corrected_anything(session):
    overrides = load_organiser_overrides(session, "admin")
    assert overrides == {}
    assert email_belongs_to_organiser(_email(), _Org(), ACCOUNTS, RULES, overrides) is True


def test_an_explicit_filing_wins_over_the_rules(session):
    """A message the rules do not match still appears where it was filed."""
    unmatched = _email(sender="Nobody Relevant", subject="unrelated")
    _add_override(session, uid="101", organiser_id="org-1")
    overrides = load_organiser_overrides(session, "admin")

    assert email_belongs_to_organiser(unmatched, _Org("org-1"), ACCOUNTS, RULES, overrides) is True


def test_filing_elsewhere_removes_it_from_the_organiser_the_rules_chose(session):
    """One filed home at a time — otherwise a moved email appears in both."""
    _add_override(session, uid="101", organiser_id="org-2")
    overrides = load_organiser_overrides(session, "admin")

    assert email_belongs_to_organiser(_email(), _Org("org-1"), ACCOUNTS, RULES, overrides) is False
    assert email_belongs_to_organiser(_email(), _Org("org-2"), ACCOUNTS, RULES, overrides) is True


def test_an_exclusion_survives_a_rule_that_keeps_matching(session):
    """Without this, a rule re-asserts a match the human already rejected."""
    _add_override(session, uid="101", excluded_from_id="org-1")
    overrides = load_organiser_overrides(session, "admin")

    assert email_belongs_to_organiser(_email(), _Org("org-1"), ACCOUNTS, RULES, overrides) is False
    # The exclusion is per-organiser, not a blanket hide.
    assert email_belongs_to_organiser(_email(), _Org("org-2"), ACCOUNTS, RULES, overrides) is True


def test_corrections_do_not_leak_between_messages(session):
    _add_override(session, uid="101", organiser_id="org-2")
    overrides = load_organiser_overrides(session, "admin")

    other = _email(uid="202")
    assert email_belongs_to_organiser(other, _Org("org-1"), ACCOUNTS, RULES, overrides) is True


def test_a_missing_table_leaves_the_rules_in_charge(tmp_path):
    """Databases predating the table must still serve the organisers panel."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'bare.db').as_posix()}")
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        overrides = load_organiser_overrides(s, "admin")
        assert overrides == {}
        assert email_belongs_to_organiser(_email(), _Org(), ACCOUNTS, RULES, overrides) is True
    finally:
        s.close()
        engine.dispose()


# ── 4.1: keyword rules must see body text, not just the subject ──────────

def test_keyword_rules_match_body_text_not_only_the_subject(tmp_path, monkeypatch):
    """A keyword rule searched a `snippet` key nothing ever set.

    `_matches_rule` read `email["snippet"]` while `_get_recent_emails` selected
    no body column, so every keyword rule silently degraded to a subject-line
    match. The body now comes from the preview cache the email module already
    warms.
    """
    import sqlite3
    import json as _json

    from routes.organisers import organisers_routes as org

    db_path = tmp_path / "scheduled_emails.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE email_message_index ("
        "owner TEXT, account_key TEXT, folder TEXT, uid TEXT, message_id TEXT, "
        "subject TEXT, from_name TEXT, from_address TEXT, to_text TEXT, cc_text TEXT, "
        "date_iso TEXT, date_display TEXT, date_epoch REAL, size INTEGER, "
        "flags TEXT, has_attachments INTEGER)"
    )
    conn.execute(
        "CREATE TABLE email_body_preview_cache ("
        "owner TEXT, account_key TEXT, folder TEXT, uid TEXT, message_id TEXT, "
        "payload_json TEXT, updated_at TEXT)"
    )
    import time as _time

    now = _time.time()
    conn.execute(
        "INSERT INTO email_message_index VALUES "
        "('admin','acc-1','INBOX','9','mid-9','Weekly note','A Sender',"
        "'s@example.invalid','','','','',?,10,'',0)",
        (now,),
    )
    conn.execute(
        "INSERT INTO email_body_preview_cache VALUES "
        "('admin','acc-1','INBOX','9','mid-9',?,'now')",
        (_json.dumps({"body": "Please confirm the wholesale rates before Friday."}),),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(org, "SCHEDULED_EMAILS_DB", str(db_path))
    emails = org._get_recent_emails(days=30)

    assert len(emails) == 1
    assert "wholesale" in emails[0]["snippet"].lower()
    # The subject says nothing about wholesale; only the body does.
    assert "wholesale" not in emails[0]["subject"].lower()
    assert org._matches_rule(emails[0], [], {"keywords": ["wholesale"]}) is True


def test_a_message_without_a_cached_body_still_matches_on_its_subject(tmp_path, monkeypatch):
    """Most messages have no cached body; they must not vanish from matching."""
    import sqlite3
    import time as _time

    from routes.organisers import organisers_routes as org

    db_path = tmp_path / "scheduled_emails.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE email_message_index ("
        "owner TEXT, account_key TEXT, folder TEXT, uid TEXT, message_id TEXT, "
        "subject TEXT, from_name TEXT, from_address TEXT, to_text TEXT, cc_text TEXT, "
        "date_iso TEXT, date_display TEXT, date_epoch REAL, size INTEGER, "
        "flags TEXT, has_attachments INTEGER)"
    )
    conn.execute(
        "CREATE TABLE email_body_preview_cache ("
        "owner TEXT, account_key TEXT, folder TEXT, uid TEXT, message_id TEXT, "
        "payload_json TEXT, updated_at TEXT)"
    )
    conn.execute(
        "INSERT INTO email_message_index VALUES "
        "('admin','acc-1','INBOX','10','mid-10','Wholesale rates enquiry','A Sender',"
        "'s@example.invalid','','','','',?,10,'',0)",
        (_time.time(),),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(org, "SCHEDULED_EMAILS_DB", str(db_path))
    emails = org._get_recent_emails(days=30)

    assert emails[0]["snippet"] == ""
    assert org._matches_rule(emails[0], [], {"keywords": ["wholesale"]}) is True


# ── 7.3: recipients count, but only on mail the user sent ────────────────

RECIPIENT_RULES = {"senders": ["Adrian"], "keywords": [], "domains": ["partner.example"]}


def test_a_sent_message_matches_on_who_it_was_addressed_to():
    """On outbound mail the correspondent is in To/Cc, not From.

    Without this a sender rule could never match anything the user wrote,
    because the sender of every sent message is the user.
    """
    from routes.organisers.organisers_routes import _matches_rule

    sent = {
        "folder": "Sent",
        "from_name": "Me",
        "from_address": "me@mine.invalid",
        "subject": "Re: rates",
        "to_text": "Adrian Matache <adrian@partner.example>",
        "cc_text": "",
        "snippet": "",
    }
    assert _matches_rule(sent, [], RECIPIENT_RULES) is True


def test_a_received_message_does_not_match_on_its_recipients():
    """Received mail is addressed to the user, so matching recipients there
    would make a rule naming someone claim every message sent *to* them."""
    from routes.organisers.organisers_routes import _matches_rule

    received = {
        "folder": "INBOX",
        "from_name": "Someone Else",
        "from_address": "other@elsewhere.invalid",
        "subject": "Unrelated",
        "to_text": "Adrian Matache <adrian@partner.example>",
        "cc_text": "",
        "snippet": "",
    }
    assert _matches_rule(received, [], RECIPIENT_RULES) is False


def test_a_sent_message_still_matches_on_its_sender_rules_normally():
    """The outbound path must add recipients, not replace the other checks."""
    from routes.organisers.organisers_routes import _matches_rule

    sent = {
        "folder": "Sent",
        "from_name": "Me",
        "from_address": "me@mine.invalid",
        "subject": "Adrian asked about rates",
        "to_text": "someone@nowhere.invalid",
        "cc_text": "",
        "snippet": "",
    }
    assert _matches_rule(sent, [], {"senders": [], "keywords": ["adrian"], "domains": []}) is True
