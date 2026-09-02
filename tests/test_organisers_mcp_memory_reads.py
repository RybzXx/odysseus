"""The organisers MCP tools must not raise on a lane-bearing organiser.

Registering organisers_server in _BUILTIN_SERVERS made three tools reachable
by the model. Two of them could not work at all:

  * get_work_organiser_detail filtered `Memory.lane`, and the Memory model has
    no `lane` column — AttributeError for every organiser carrying a lane,
    which is all seven of the seeded ones.
  * record_work_insight constructed Memory(content=…, lane=…, tags=…), three
    columns that do not exist — TypeError on every call.

Both raised out of call_tool, so the failure reached the model as an MCP
error rather than an answer. These tests are what makes a return to the
SQLAlchemy Memory model loud.

Recording under an organiser lane stays deliberately unimplemented: the write
also targeted the `memories` table, which is not the store the detail view
reads. That is a design question, not a bug to patch here.
"""

import pytest

pytest.importorskip("mcp", reason="mcp is only installed in the guest")

from core.database import Memory  # noqa: E402


def test_memory_model_still_lacks_the_columns_the_old_writer_used():
    """The premise of both defects. If this ever fails, the schema changed and
    the tools' read path should be revisited deliberately, not by accident."""
    columns = {c.name for c in Memory.__table__.columns}
    assert "lane" not in columns
    assert "content" not in columns
    assert "tags" not in columns
    assert {"id", "text", "category", "owner"} <= columns


def test_organisers_server_does_not_touch_the_memory_model():
    """The module imported Memory solely for the two broken paths."""
    from mcp_servers import organisers_server

    assert not hasattr(organisers_server, "Memory")


def test_detail_reads_memories_through_the_shared_helper():
    """One matching rule, shared with the HTTP route, so the MCP tool and the
    route cannot answer the same question differently."""
    from mcp_servers import organisers_server

    assert hasattr(organisers_server, "_organiser_memories")


def test_organiser_memories_tolerates_an_unreadable_store():
    """Inv: never raises — an unreadable store yields []."""
    from routes.organisers.organisers_routes import _organiser_memories

    class Org:
        slug = "bilweekend_ops"
        memory_lane = "organisers:bilweekend_ops"
        category_group = "operations"

    assert _organiser_memories(Org(), "nobody-owns-this") == []


def test_organiser_memories_matches_lane_category_and_slug(monkeypatch):
    """Mirrors the live seeds: lanes are namespaced ("organisers:<slug>")."""
    from routes.organisers import organisers_routes

    class Org:
        slug = "bilweekend_ops"
        memory_lane = "organisers:bilweekend_ops"
        category_group = "operations"

    class FakeManager:
        def load(self, owner):
            return [
                {"id": "1", "text": "by lane", "category": "organisers:bilweekend_ops"},
                {"id": "2", "text": "by group", "category": "operations"},
                {"id": "3", "text": "mentions bilweekend_ops inline", "category": "fact"},
                {"id": "4", "text": "unrelated", "category": "fact"},
            ]

    monkeypatch.setattr(organisers_routes, "_get_memory_manager", lambda: FakeManager())
    got = {m["id"] for m in organisers_routes._organiser_memories(Org(), "admin")}
    assert got == {"1", "2", "3"}


def test_record_work_insight_refuses_instead_of_raising(monkeypatch):
    """Reaches the write path with a real organiser in hand.

    Empty arguments short-circuit on validation and never reach the
    constructor, so they would have passed against the broken code too.
    """
    import asyncio

    from mcp_servers import organisers_server

    class Org:
        id = "org-1"
        name = "Bil Weekend Ops"
        slug = "bilweekend_ops"
        memory_lane = "organisers:bilweekend_ops"

    class FakeQuery:
        def filter(self, *a, **k):
            return self

        def first(self):
            return Org()

    class FakeSession:
        def query(self, *a, **k):
            return FakeQuery()

        def close(self):
            pass

    monkeypatch.setattr(organisers_server, "SessionLocal", lambda: FakeSession())
    result = asyncio.run(
        organisers_server.call_tool(
            "record_work_insight", {"slug": "bilweekend_ops", "note": "a real note"}
        )
    )
    assert "Unavailable" in result[0].text


def test_record_work_insight_is_advertised_as_unavailable():
    """A tool that refuses every call must not describe itself as working."""
    import asyncio

    from mcp_servers import organisers_server

    tools = asyncio.run(organisers_server.list_tools())
    record = next(t for t in tools if t.name == "record_work_insight")
    assert "UNAVAILABLE" in record.description
