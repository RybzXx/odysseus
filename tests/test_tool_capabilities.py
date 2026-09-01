"""Unit tests for the ResultIntegrity ordering and combiner."""

import pytest

from src.tool_capabilities import (
    ResultIntegrity,
    ToolRunSecurityContext,
    coerce_result_integrity,
    combine_result_integrity,
)


def test_combine_returns_most_tainted_level():
    assert combine_result_integrity(
        [ResultIntegrity.SYSTEM, ResultIntegrity.WORKSPACE_UNTRUSTED]
    ) == ResultIntegrity.WORKSPACE_UNTRUSTED
    assert combine_result_integrity(
        [
            ResultIntegrity.SYSTEM,
            ResultIntegrity.WORKSPACE_UNTRUSTED,
            ResultIntegrity.EXTERNAL_UNTRUSTED,
        ]
    ) == ResultIntegrity.EXTERNAL_UNTRUSTED


def test_combine_is_order_independent():
    levels = [ResultIntegrity.EXTERNAL_UNTRUSTED, ResultIntegrity.SYSTEM]
    assert combine_result_integrity(levels) == combine_result_integrity(
        list(reversed(levels))
    )


def test_combine_single_untrusted_row_taints_whole_read():
    five_rows = [ResultIntegrity.SYSTEM] * 4 + [ResultIntegrity.EXTERNAL_UNTRUSTED]
    assert combine_result_integrity(five_rows) == ResultIntegrity.EXTERNAL_UNTRUSTED


def test_combine_empty_set_is_system():
    assert combine_result_integrity([]) == ResultIntegrity.SYSTEM


def test_coerce_known_enum_value_passthrough():
    assert coerce_result_integrity(ResultIntegrity.WORKSPACE_UNTRUSTED) is (
        ResultIntegrity.WORKSPACE_UNTRUSTED
    )


def test_coerce_known_string_value():
    assert coerce_result_integrity("system") is ResultIntegrity.SYSTEM


@pytest.mark.parametrize("value", [None, "", "garbage", 42, object()])
def test_coerce_unknown_or_missing_fails_closed(value):
    assert coerce_result_integrity(value) is ResultIntegrity.EXTERNAL_UNTRUSTED


def test_observe_data_integrity_is_shadow_only():
    ctx = ToolRunSecurityContext()
    ctx.observe_data_integrity(
        ResultIntegrity.EXTERNAL_UNTRUSTED, source_ref="notes:42", row_id="42"
    )
    assert ctx.shadow_data_integrity is ResultIntegrity.EXTERNAL_UNTRUSTED
    # Shadow-mode invariant (I7): the real gate is untouched by data-derived taint.
    assert ctx.external_untrusted_context_seen is False
    assert ctx.decision_for("bash").allowed is True


def test_observe_data_integrity_combines_monotonically_across_calls():
    ctx = ToolRunSecurityContext()
    ctx.observe_data_integrity(ResultIntegrity.SYSTEM, source_ref="notes:1")
    ctx.observe_data_integrity(ResultIntegrity.WORKSPACE_UNTRUSTED, source_ref="notes:2")
    ctx.observe_data_integrity(ResultIntegrity.SYSTEM, source_ref="notes:3")
    assert ctx.shadow_data_integrity is ResultIntegrity.WORKSPACE_UNTRUSTED


def test_observe_data_integrity_fails_closed_on_unknown_value():
    ctx = ToolRunSecurityContext()
    returned = ctx.observe_data_integrity(None, source_ref="notes:99")
    assert returned is ResultIntegrity.EXTERNAL_UNTRUSTED
    assert ctx.shadow_data_integrity is ResultIntegrity.EXTERNAL_UNTRUSTED


def test_observe_data_integrity_logs_ids_only_no_content(caplog):
    ctx = ToolRunSecurityContext()
    with caplog.at_level("INFO"):
        ctx.observe_data_integrity(
            ResultIntegrity.EXTERNAL_UNTRUSTED,
            source_ref="notes:42",
            row_id="42",
        )
    [record] = caplog.records
    assert ctx.run_id in record.message
    assert "notes:42" in record.message
    assert "42" in record.message
    assert "external_untrusted" in record.message
