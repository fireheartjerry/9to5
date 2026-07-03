"""Hook parity: the hook block decision and the shared classifier never disagree.

R7: the taxonomy is COMMAND-POSITION anchored -- each hard pattern blocks when it appears as
a command (start of segment / after ; & | ` newline / behind sudo-doas), while prose that
merely MENTIONS a pattern is not destructive (the substring false-positive class is gone)."""
import json

import pytest

from agents.hooks_destructive import blockDestructive, DESTRUCTIVE_PATTERNS
from platform_core.runtime.action_risk import (
    classifyActionRisk, ActionDescriptor, RiskTier, DESTRUCTIVE_PATTERNS as SHARED_PATTERNS,
)


@pytest.fixture(autouse=True)
def _guard_alerts_to_tmp(tmp_path, monkeypatch):
    """Keep the fire-and-forget guard-alert JSONL out of the real logs dir."""
    monkeypatch.setenv("NINE_TO_FIVE_HOOK_CTX", json.dumps(
        {"guard_alerts": str(tmp_path / "guard_alerts.jsonl")}))


# One canonical destructive exemplar per hard pattern, at a legitimate command position.
EXEMPLARS = {
    "rm -rf": "rm -rf /tmp/x",
    "rm -fr": "echo done && rm -fr build",
    "rmdir /s": "ls; rmdir /s target",
    "del /f": "del /f important.txt",
    "del /s": "true | del /s q",
    "format ": "format c:",
    "DROP TABLE": "DROP TABLE users;",
    "git push --force": "git push --force origin main",
    "git push -f": "git push -f origin main",
    "mkfs": "sudo mkfs.ext4 /dev/sdb",
    ":(){": ":(){ :|:& };:",
    ">/dev/sda": "echo x >/dev/sda",
}


def test_patterns_are_the_shared_source_of_truth():
    assert tuple(DESTRUCTIVE_PATTERNS) == tuple(SHARED_PATTERNS)


def test_every_pattern_has_an_exemplar():
    assert set(EXEMPLARS) == set(DESTRUCTIVE_PATTERNS)


@pytest.mark.parametrize("pat", list(DESTRUCTIVE_PATTERNS))
def test_each_destructive_pattern_classifies_destructive(pat):
    tier = classifyActionRisk(ActionDescriptor(tool_name="Bash", command=EXEMPLARS[pat]))
    assert tier is RiskTier.DESTRUCTIVE


@pytest.mark.parametrize("pat", list(DESTRUCTIVE_PATTERNS))
def test_block_destructive_exits_2_on_each_pattern(pat):
    with pytest.raises(SystemExit) as ei:
        blockDestructive({"tool_name": "Bash", "tool_input": {"command": EXEMPLARS[pat]}})
    assert ei.value.code == 2


def test_safe_command_exits_0():
    with pytest.raises(SystemExit) as ei:
        blockDestructive({"tool_name": "Bash", "tool_input": {"command": "pytest -q"}})
    assert ei.value.code == 0


@pytest.mark.parametrize("cmd", [
    "please format the output nicely",
    "explain what the del /s flag does",
    "the docs mention rm -rf as an example",
])
def test_prose_mentioning_a_pattern_is_not_blocked(cmd):
    """The substring false-positive class: prose containing pattern words must NOT block."""
    assert classifyActionRisk(
        ActionDescriptor(tool_name="Bash", command=cmd)) is not RiskTier.DESTRUCTIVE
    with pytest.raises(SystemExit) as ei:
        blockDestructive({"tool_name": "Bash", "tool_input": {"command": cmd}})
    assert ei.value.code == 0
