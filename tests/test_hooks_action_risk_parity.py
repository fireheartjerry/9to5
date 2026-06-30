"""Hook parity: the legacy block decision and the shared classifier never disagree."""
import pytest
from agents.hooks_destructive import blockDestructive, DESTRUCTIVE_PATTERNS
from platform_core.runtime.action_risk import (
    classifyActionRisk, ActionDescriptor, RiskTier, DESTRUCTIVE_PATTERNS as SHARED_PATTERNS,
)


def test_patterns_are_the_shared_source_of_truth():
    assert tuple(DESTRUCTIVE_PATTERNS) == tuple(SHARED_PATTERNS)


@pytest.mark.parametrize("pat", list(DESTRUCTIVE_PATTERNS))
def test_each_destructive_pattern_classifies_destructive(pat):
    tier = classifyActionRisk(ActionDescriptor(tool_name="Bash", command=f"x {pat} y"))
    assert tier is RiskTier.DESTRUCTIVE


@pytest.mark.parametrize("pat", list(DESTRUCTIVE_PATTERNS))
def test_block_destructive_exits_2_on_each_pattern(pat):
    with pytest.raises(SystemExit) as ei:
        blockDestructive({"tool_name": "Bash", "tool_input": {"command": f"do {pat} now"}})
    assert ei.value.code == 2


def test_safe_command_exits_0():
    with pytest.raises(SystemExit) as ei:
        blockDestructive({"tool_name": "Bash", "tool_input": {"command": "pytest -q"}})
    assert ei.value.code == 0
