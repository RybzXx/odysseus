"""Unit tests for companion.todos.fetch_email_summary."""

import json

import companion.todos as todos


def test_missing_state_file_returns_zeros(tmp_path, monkeypatch):
    monkeypatch.setattr("src.constants.DATA_DIR", str(tmp_path))
    result = todos.fetch_email_summary("someone")
    assert result == {"total_unread": 0, "total_urgent": 0, "max_score": 0}


def test_reads_the_same_slugged_filename_the_scanner_writes(tmp_path, monkeypatch):
    monkeypatch.setattr("src.constants.DATA_DIR", str(tmp_path))
    # Same slug algorithm as action_check_email_urgency (src/builtin_actions.py)
    # and the /api/email/urgency-state reader (routes/email_routes.py).
    slug = "".join(c if (c.isalnum() or c in "-_.@") else "_" for c in "user@example.com")
    state_file = tmp_path / f"email_urgency_state_{slug}.json"
    state_file.write_text(json.dumps({
        "total_unread": 7,
        "total_urgent": 2,
        "max_score": 3,
        "per_uid": {"123": {"subject": "should not leak into the summary"}},
        "notified_uids": ["123"],
    }))

    result = todos.fetch_email_summary("user@example.com")
    assert result == {"total_unread": 7, "total_urgent": 2, "max_score": 3}
    assert "per_uid" not in result
    assert "notified_uids" not in result


def test_missing_owner_falls_back_to_default_slug(tmp_path, monkeypatch):
    monkeypatch.setattr("src.constants.DATA_DIR", str(tmp_path))
    state_file = tmp_path / "email_urgency_state_default.json"
    state_file.write_text(json.dumps({"total_unread": 1, "total_urgent": 0, "max_score": 0}))
    assert todos.fetch_email_summary(None) == {"total_unread": 1, "total_urgent": 0, "max_score": 0}


def test_corrupt_state_file_fails_closed_to_zeros(tmp_path, monkeypatch):
    monkeypatch.setattr("src.constants.DATA_DIR", str(tmp_path))
    slug = "default"
    state_file = tmp_path / f"email_urgency_state_{slug}.json"
    state_file.write_text("{not valid json")
    assert todos.fetch_email_summary(None) == {"total_unread": 0, "total_urgent": 0, "max_score": 0}
