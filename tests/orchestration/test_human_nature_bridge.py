"""Tests for platform_core/orchestration/human_nature_bridge.py.

THE REGRESSION GUARANTEE: with HUMAN_NATURE_ENABLED=False (the default), runPreambleHooks
is a strict no-op and runTeardownHooks only ever records the "off" arm to the A/B harness
(both arms need rows for ab_harness.compare() to mean anything) -- self_state must stay
untouched. Only with the flag True do the human_nature.integration hooks fire.
"""
from __future__ import annotations

import config
from human_nature.ab_harness import compare
from platform_core.orchestration.human_nature_bridge import runPreambleHooks, runTeardownHooks
from state.task import TaskState


def _make_state() -> TaskState:
    state = TaskState.create("test goal", 1.0)
    state.subtasks.append({
        "subtask_id": "st-001", "title": "do the thing", "status": "done",
        "verify_result": {"passed": True},
    })
    return state


class _FakeOrch:
    def _ollamaChat(self, system: str, user: str, **kw) -> str:  # pragma: no cover -- not reached
        return ""


def test_preamble_is_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", False)
    state = _make_state()
    runPreambleHooks(state)
    assert state.meta["self_state"] is None


def test_preamble_initializes_self_state_when_enabled(monkeypatch):
    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    state = _make_state()
    runPreambleHooks(state)
    assert state.meta["self_state"] is not None
    assert "competence" in state.meta["self_state"]


def test_teardown_records_off_arm_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", False)
    state = _make_state()
    runTeardownHooks(_FakeOrch(), state)
    assert state.meta["self_state"] is None   # no appraisal/consolidation ran
    result = compare()
    assert result["n_off"] == 1
    assert result["n_on"] == 0


def test_teardown_records_on_arm_and_appraises_when_enabled(monkeypatch):
    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    state = _make_state()
    runPreambleHooks(state)   # seed self_state first (mirrors real preamble->teardown order)
    runTeardownHooks(_FakeOrch(), state)
    assert state.meta["self_state"] is not None
    result = compare()
    assert result["n_on"] == 1
    assert result["n_off"] == 0


def test_teardown_never_raises_on_malformed_subtasks(monkeypatch):
    """Best-effort: a subtask missing verify_result/title must never crash teardown."""
    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    state = TaskState.create("test goal", 1.0)
    state.subtasks.append({"subtask_id": "st-001", "status": "failed"})
    runPreambleHooks(state)
    runTeardownHooks(_FakeOrch(), state)   # must not raise
