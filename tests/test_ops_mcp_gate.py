"""The ops MCP tools' security posture, asserted as one contract.

The two ambient lanes only work because of how these three tools are
classified: a structural read leaves the run able to propose, a full read ends
it. Nothing enforces that at runtime beyond the classification itself, so a
rebase that drops the mapping in src/tool_capabilities.py would silently turn
the proposing lane into a lane that reads and is then blocked — visible only as
proposals quietly never arriving.

These tests are what makes that failure loud.
"""

from src.tool_capabilities import (
    ResultIntegrity,
    ToolEffect,
    ToolRunSecurityContext,
    capabilities_for_tool,
)

STRUCTURAL = "mcp__ops__worklist_structural"
FULL = "mcp__ops__worklist_full"
PROPOSE = "mcp__ops__propose_change"

SUCCESS = {"stdout": '{"rows": []}', "exit_code": 0}


def test_all_three_tools_are_classified():
    """An unmapped ops tool falls through to _UNKNOWN_CAPABILITIES, which is
    blocked after any untrusted read — the lane would fail closed, not open."""
    for tool in (STRUCTURAL, FULL, PROPOSE):
        assert capabilities_for_tool(tool).known is True, tool


def test_structural_read_is_system_integrity():
    capabilities = capabilities_for_tool(STRUCTURAL)
    assert capabilities.result_integrity is ResultIntegrity.SYSTEM
    assert capabilities.effects == frozenset({ToolEffect.BROKERED_NETWORK_READ})


def test_full_read_is_external_untrusted():
    capabilities = capabilities_for_tool(FULL)
    assert capabilities.result_integrity is ResultIntegrity.EXTERNAL_UNTRUSTED


def test_propose_is_classified_as_a_write():
    """Posting a proposal changes nothing until an admin accepts it, but it is
    still a remote write. Classifying it as a read would let a run that had
    already read customer text act on what it read."""
    capabilities = capabilities_for_tool(PROPOSE)
    assert ToolEffect.EXTERNAL_SIDE_EFFECT in capabilities.effects


def test_structural_read_leaves_the_run_able_to_propose():
    """Lane A's whole premise."""
    context = ToolRunSecurityContext()
    context.observe_tool_result(STRUCTURAL, SUCCESS)

    assert context.external_untrusted_context_seen is False
    assert context.decision_for(PROPOSE).allowed is True


def test_full_read_blocks_proposing():
    """Lane B's whole premise: it may report and nothing else."""
    context = ToolRunSecurityContext()
    context.observe_tool_result(FULL, SUCCESS)

    assert context.external_untrusted_context_seen is True
    assert context.decision_for(PROPOSE).allowed is False


def test_full_read_after_structural_still_blocks_proposing():
    """Order does not launder the taint. A run that reads structural, proposes,
    then reads full must not be able to propose again on what it just read."""
    context = ToolRunSecurityContext()
    context.observe_tool_result(STRUCTURAL, SUCCESS)
    context.observe_tool_result(FULL, SUCCESS)

    assert context.decision_for(PROPOSE).allowed is False


def test_a_failed_structural_read_arms_the_gate():
    """A structural call is trusted only while it is the web app's allowlist
    projection. An error body is the remote side talking, not that projection.

    This is the shape McpManager._do_call produces when a tool raises, which is
    why ops_server raises OpsApiError instead of returning the message as text.
    """
    context = ToolRunSecurityContext()
    context.observe_tool_result(
        STRUCTURAL,
        {"stdout": "", "stderr": "Operations API returned 500: ...",
         "exit_code": 1, "untrusted_content": True},
    )

    assert context.external_untrusted_context_seen is True
    assert context.decision_for(PROPOSE).allowed is False


def test_a_silent_structural_failure_would_not_arm():
    """Why ops_server must raise rather than return an error string.

    A SYSTEM-classified tool that reports failure without untrusted_content does
    not arm the gate — the remote error text would enter the run as trusted. The
    server closes this by raising, so _do_call sets isError and the marker.
    """
    context = ToolRunSecurityContext()
    context.observe_tool_result(STRUCTURAL, {"stdout": "", "stderr": "boom", "exit_code": 1})

    assert context.external_untrusted_context_seen is False
