"""End-to-end test of the ws-02 storage-layer shadow hook (Q1 = option B).

Uses an isolated in-memory SQLite engine, never the app's real database file.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.database as db
from src.tool_capabilities import (
    ACTIVE_RUN_SECURITY,
    ResultIntegrity,
    ToolRunSecurityContext,
)


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    db.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_row_with_no_integrity_column_reads_back_untrusted():
    session = _make_session()
    session.add(db.OperationsNote(id="n1", key="ops:1", author="staff", text="hello"))
    session.commit()
    session.expire_all()

    run_security = ToolRunSecurityContext()
    token = ACTIVE_RUN_SECURITY.set(run_security)
    try:
        session.query(db.OperationsNote).filter_by(id="n1").one()
    finally:
        ACTIVE_RUN_SECURITY.reset(token)

    # I1: a store with no integrity column fails closed, not open.
    assert run_security.shadow_data_integrity is ResultIntegrity.EXTERNAL_UNTRUSTED
    # I7: shadow mode only — the real gate is untouched.
    assert run_security.external_untrusted_context_seen is False
    assert run_security.decision_for("bash").allowed is True


def test_no_active_run_security_is_a_silent_noop():
    session = _make_session()
    session.add(db.OperationsNote(id="n2", key="ops:2", author="staff", text="hi"))
    session.commit()
    session.expire_all()

    assert ACTIVE_RUN_SECURITY.get() is None
    # Must not raise outside of any tool-execution context.
    session.query(db.OperationsNote).filter_by(id="n2").one()


def test_hook_propagates_to_every_mapped_model_not_just_operations_notes():
    """propagate=True on Base means a model that never heard of ws-02 is still observed."""
    session = _make_session()
    session.add(db.Note(id="note1", owner="u1", content="x"))
    session.commit()
    session.expire_all()

    run_security = ToolRunSecurityContext()
    token = ACTIVE_RUN_SECURITY.set(run_security)
    try:
        fetched = session.query(db.Note).filter_by(id="note1").one()
    finally:
        ACTIVE_RUN_SECURITY.reset(token)

    assert fetched.id == "note1"
    assert run_security.shadow_data_integrity is ResultIntegrity.EXTERNAL_UNTRUSTED
