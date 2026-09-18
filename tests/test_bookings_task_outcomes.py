"""A failed remote read must never become an empty or successful task."""
from unittest.mock import AsyncMock

import pytest

from services.bookings import desk_task
from src import builtin_actions


@pytest.mark.asyncio
@pytest.mark.parametrize("action,claim", [
    ("action_bookings_offer_jobs", "claim_offer_jobs"),
    ("action_bookings_draft_appends", "claim_draft_appends"),
])
async def test_failed_claim_reports_failure(monkeypatch, action, claim):
    monkeypatch.setattr(desk_task.ops_hub, claim, AsyncMock(return_value={"ok": False, "error": "offline"}))
    text, ok = await getattr(builtin_actions, action)("owner")
    assert not ok
    assert "offline" in text
    assert "nothing waiting" not in text


@pytest.mark.asyncio
async def test_failed_recipient_fetch_reports_failure(monkeypatch):
    monkeypatch.setattr(desk_task, "_fetch_recipients", AsyncMock(return_value=None))
    text, ok = await builtin_actions.action_bookings_reply_scan("owner")
    assert not ok
    assert "could not fetch" in text


@pytest.mark.asyncio
async def test_successful_empty_claim_remains_noop(monkeypatch):
    monkeypatch.setattr(desk_task.ops_hub, "claim_offer_jobs", AsyncMock(return_value={"ok": True, "body": {"jobs": []}}))
    with pytest.raises(builtin_actions.TaskNoop):
        await builtin_actions.action_bookings_offer_jobs("owner")


@pytest.mark.asyncio
async def test_uncertain_append_result_is_not_repeated(monkeypatch, tmp_path):
    monkeypatch.setattr("src.constants.DATA_DIR", str(tmp_path))
    from services.bookings.draft_append import DraftAppendOutcome
    calls = []
    monkeypatch.setattr(desk_task.ops_hub, "claim_draft_appends", AsyncMock(return_value={"ok": True, "body": {"appends": [{"id": "one"}]}}))
    monkeypatch.setattr(desk_task, "file_draft", lambda item: calls.append(item["id"]) or DraftAppendOutcome(folder="Drafts"))
    monkeypatch.setattr(desk_task.ops_hub, "post_draft_append_result", AsyncMock(return_value={"ok": False, "error": "offline"}))
    report = await desk_task.run_draft_appends()
    await desk_task.run_draft_appends()
    assert calls == ["one"]
    assert not report.ok


def test_partial_completion_stays_unsuccessful():
    report = desk_task.DeskRunReport(priced=1, failed=1)
    assert report.status == "partial"
    assert not report.ok
