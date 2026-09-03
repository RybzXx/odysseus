"""The organisers MCP tools must not raise, and must agree with the HTTP route.

Registering organisers_server in _BUILTIN_SERVERS made three tools reachable
by the model. Two of them could not work at all:

  * get_work_organiser_detail filtered `Memory.lane`, and the Memory model has
    no `lane` column — AttributeError for every organiser carrying a lane,
    which is all seven of the seeded ones.
  * record_work_insight constructed Memory(content=…, lane=…, tags=…), three
    columns that do not exist — TypeError on every call.

Both raised out of call_tool, so the failure reached the model as an MCP error
rather than an answer. These tests are what makes a return to the SQLAlchemy
Memory model loud.

Recording under an organiser lane is now implemented: a note takes the
organiser's lane as its memory *category*, written to the JSON store the detail
view actually reads. The tests below pin that, and pin the two-section split
that keeps an organiser's own notes distinct from general memories its rules
merely select.
"""

import pytest

pytest.importorskip("mcp", reason="mcp is only installed in the guest")

from core.database import Memory  # noqa: E402


class _Org:
    """A stand-in mirroring the live seeds: lanes are namespaced."""

    id = "org-1"
    name = "Bil Weekend Ops"
    slug = "bilweekend_ops"
    memory_lane = "organisers:bilweekend_ops"
    category_group = "operations"
    rules_json = '{"senders": ["Adrian"], "keywords": ["quotation"], "domains": []}'


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

    assert hasattr(organisers_server, "organiser_memory_sections")


def test_memory_sections_tolerate_an_unreadable_store():
    """Inv: never raises — an unreadable store yields empty sections."""
    from routes.organisers.organisers_routes import organiser_memory_sections

    assert organiser_memory_sections(_Org(), "nobody-owns-this") == {
        "lane": [],
        "referenced": [],
    }


def test_lane_memories_and_referenced_memories_are_separated(monkeypatch):
    """An organiser's own notes and the general pool are two different things.

    Before the split, the tab matched on the lane and category_group together;
    since no memory carried either, it was empty for every organiser despite
    the store holding entries.
    """
    from routes.organisers import organisers_routes

    class FakeManager:
        def load(self, owner):
            return [
                {"id": "1", "text": "recorded here", "category": "organisers:bilweekend_ops"},
                {"id": "2", "text": "Adrian handles the north route", "category": "fact"},
                {"id": "3", "text": "a quotation needs two signatures", "category": "preference"},
                {"id": "4", "text": "mentions bilweekend_ops inline", "category": "fact"},
                {"id": "5", "text": "entirely unrelated", "category": "fact"},
                {"id": "6", "text": "also operations", "category": "operations"},
            ]

    monkeypatch.setattr(organisers_routes, "_get_memory_manager", lambda: FakeManager())
    sections = organisers_routes.organiser_memory_sections(_Org(), "admin")

    assert {m["id"] for m in sections["lane"]} == {"1"}
    # 2 by sender rule, 3 by keyword rule, 4 by slug mention.
    assert {m["id"] for m in sections["referenced"]} == {"2", "3", "4"}
    # category_group alone no longer selects: "operations" is a grouping label,
    # not a statement that the memory is about this organiser.
    assert "6" not in {m["id"] for m in sections["referenced"]}


def test_badge_count_and_tab_cannot_disagree(monkeypatch):
    """Both derive from one function, which is the point of having it."""
    from routes.organisers import organisers_routes

    class FakeManager:
        def load(self, owner):
            return [
                {"id": "1", "text": "recorded here", "category": "organisers:bilweekend_ops"},
                {"id": "2", "text": "Adrian handles the north route", "category": "fact"},
            ]

    monkeypatch.setattr(organisers_routes, "_get_memory_manager", lambda: FakeManager())
    org = _Org()
    sections = organisers_routes.organiser_memory_sections(org, "admin")

    assert organisers_routes.count_organiser_memories(org, "admin") == (
        len(sections["lane"]) + len(sections["referenced"])
    )


def test_lane_falls_back_to_the_slug_when_unset():
    """A lane is always well-defined, so a note can always be filed."""
    from routes.organisers.organisers_routes import organiser_lane

    class Unlaned(_Org):
        memory_lane = None

    assert organiser_lane(Unlaned()) == "organisers:bilweekend_ops"
    assert organiser_lane(_Org()) == "organisers:bilweekend_ops"


def test_record_work_insight_writes_into_the_lane(monkeypatch, tmp_path):
    """The note lands in the JSON store, carrying the organiser's lane.

    The old writer targeted the SQLAlchemy `memories` table, which the detail
    view does not read, so a note written there could never appear.
    """
    import asyncio
    import json

    from mcp_servers import organisers_server

    class FakeQuery:
        def filter(self, *a, **k):
            return self

        def first(self):
            return _Org()

    class FakeSession:
        def query(self, *a, **k):
            return FakeQuery()

        def close(self):
            pass

    monkeypatch.setattr(organisers_server, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr("src.constants.DATA_DIR", str(tmp_path))

    result = asyncio.run(
        organisers_server.call_tool(
            "record_work_insight", {"slug": "bilweekend_ops", "note": "a real note"}
        )
    )

    assert "Recorded" in result[0].text
    assert "organisers:bilweekend_ops" in result[0].text

    stored = json.loads((tmp_path / "memory.json").read_text(encoding="utf-8"))
    assert [m["text"] for m in stored] == ["a real note"]
    assert stored[0]["category"] == "organisers:bilweekend_ops"


def test_record_work_insight_is_advertised_as_working():
    """It writes now, so it must no longer describe itself as unavailable."""
    import asyncio

    from mcp_servers import organisers_server

    tools = asyncio.run(organisers_server.list_tools())
    record = next(t for t in tools if t.name == "record_work_insight")
    assert "UNAVAILABLE" not in record.description
    assert "lane" in record.description.lower()
