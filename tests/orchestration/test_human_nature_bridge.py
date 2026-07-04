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


def test_mid_run_instinct_off_is_noop(monkeypatch):
    import config
    from platform_core.orchestration import human_nature_bridge as hnb
    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", False)
    assert hnb.midRunInstinct({"meta": {}}, None) is None


def test_mid_run_instinct_surfaces_flag(monkeypatch):
    import config
    from human_nature import integration
    import memory.experience_adapters as _adp
    import memory.experience_solutions as _sol
    from platform_core.orchestration import human_nature_bridge as hnb
    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(_sol, "fetch_reflections", lambda *a, **k: [])
    monkeypatch.setattr(_adp, "fetch_failure_modes", lambda *a, **k: [])
    monkeypatch.setattr(integration, "maybe_run_instinct", lambda *a, **k: "watch the auth edge case")
    events = []

    class _Dash:
        def event(self, msg):
            events.append(msg)

    flag = hnb.midRunInstinct({"meta": {}}, _Dash())
    assert flag == "watch the auth edge case"
    assert any("instinct" in e and "auth" in e for e in events), events


def test_mid_run_instinct_never_raises(monkeypatch):
    import config
    from human_nature import integration
    import memory.experience_adapters as _adp
    import memory.experience_solutions as _sol
    from platform_core.orchestration import human_nature_bridge as hnb
    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(_sol, "fetch_reflections", lambda *a, **k: [])
    monkeypatch.setattr(_adp, "fetch_failure_modes", lambda *a, **k: [])

    def _boom(*a, **k):
        raise RuntimeError("ledger down")

    monkeypatch.setattr(integration, "maybe_run_instinct", _boom)
    assert hnb.midRunInstinct({"meta": {}}, None) is None
