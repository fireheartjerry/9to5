"""Tests for platform_core/orchestration/human_nature_bridge.py.

THE REGRESSION GUARANTEE: with HUMAN_NATURE_ENABLED=False (the default), runPreambleHooks
is a strict no-op and runTeardownHooks only ever records the "off" arm to the A/B harness
(both arms need rows for ab_harness.compare() to mean anything) -- self_state must stay
untouched. Only with the flag True do the human_nature.integration hooks fire.
"""

from __future__ import annotations

import config
from human_nature.ab_harness import compare
from platform_core.orchestration.human_nature_bridge import (
    biasEffort,
    preActRouting,
    runPreambleHooks,
    runTeardownHooks,
)
from state.task import TaskState


def _make_state() -> TaskState:
    state = TaskState.create("test goal", 1.0)
    state.subtasks.append(
        {
            "subtask_id": "st-001",
            "title": "do the thing",
            "status": "done",
            "verify_result": {"passed": True},
        }
    )
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
    assert state.meta["self_state"] is None  # no appraisal/consolidation ran
    result = compare()
    assert result["n_off"] == 1
    assert result["n_on"] == 0


def test_teardown_records_on_arm_and_appraises_when_enabled(monkeypatch):
    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    state = _make_state()
    runPreambleHooks(state)  # seed self_state first (mirrors real preamble->teardown order)
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
    runTeardownHooks(_FakeOrch(), state)  # must not raise


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


# --- opinionAdvisory (advisory-only coupling on the plan gate) -----------------


def _make_opinion_state() -> TaskState:
    state = TaskState.create("build the auth flow", 1.0)
    state.meta["domain"] = "tactics"
    state.subtasks.append(
        {
            "subtask_id": "st-001",
            "title": "harden the auth token path",
            "type": "tactics",
            "status": "pending",
        }
    )
    return state


def test_opinion_advisory_off_is_noop_when_hn_disabled(monkeypatch):
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", False)
    monkeypatch.setattr(config, "HN_OPINIONS_BEHAVIOR", True)
    state = _make_opinion_state()
    assert hnb.opinionAdvisory(state, None) == []
    assert "hn_opinions" not in state.meta


def test_opinion_advisory_off_is_noop_when_behavior_disabled(monkeypatch):
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_OPINIONS_BEHAVIOR", False)
    state = _make_opinion_state()
    assert hnb.opinionAdvisory(state, None) == []
    assert "hn_opinions" not in state.meta


def test_opinion_advisory_surfaces_hard_tier(monkeypatch):
    from human_nature import opinions
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_OPINIONS_BEHAVIOR", True)
    monkeypatch.setattr(hnb, "_convictionFor", lambda *a, **k: 0.99)
    monkeypatch.setattr(opinions, "tier", lambda *a, **k: "hard")
    events = []

    class _Dash:
        def event(self, msg):
            events.append(msg)

    state = _make_opinion_state()
    advisories = hnb.opinionAdvisory(state, _Dash())
    assert advisories, "expected a surfaced hard-tier advisory"
    assert advisories[0]["tier"] == "hard"
    assert state.meta["hn_opinions"] == advisories
    assert any("opinion" in e for e in events), events


def test_opinion_advisory_never_raises(monkeypatch):
    from human_nature import opinions
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_OPINIONS_BEHAVIOR", True)

    def _boom(*a, **k):
        raise RuntimeError("ledger down")

    monkeypatch.setattr(opinions, "tier", _boom)
    state = _make_opinion_state()
    assert hnb.opinionAdvisory(state, None) == []


def test_opinion_advisory_is_advisory_only_never_mutates_plan(monkeypatch):
    """INVARIANT: even a hard opinion only appends to hn_opinions -- it must never
    reject/hold the plan, skip subtasks, or touch subtask statuses/flow."""
    from human_nature import opinions
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_OPINIONS_BEHAVIOR", True)
    monkeypatch.setattr(hnb, "_convictionFor", lambda *a, **k: 0.99)
    monkeypatch.setattr(opinions, "tier", lambda *a, **k: "hard")
    state = _make_opinion_state()
    before_statuses = [s["status"] for s in state.subtasks]
    before_count = len(state.subtasks)

    hnb.opinionAdvisory(state, None)

    assert [s["status"] for s in state.subtasks] == before_statuses
    assert len(state.subtasks) == before_count
    # no abort/reject/hold flag was set anywhere in meta
    for key in ("abort", "reject", "hold", "plan_rejected"):
        assert key not in state.meta


# --- preActRouting + biasEffort (intuition dual-process → advisory effort bias) ---


def test_bias_effort_fast_lowers_one_tier_from_mid():
    assert biasEffort("high", "fast") == "default"
    assert biasEffort("xhigh", "fast") == "high"
    assert biasEffort("ultracode", "fast") == "xhigh"
    assert biasEffort("default", "fast") == "low"


def test_bias_effort_fast_at_lowest_tier_stays_clamped():
    assert biasEffort("low", "fast") == "low"


def test_bias_effort_deliberate_returns_unchanged():
    for eff in ("low", "default", "high", "xhigh", "ultracode"):
        assert biasEffort(eff, "deliberate") == eff


def test_bias_effort_medium_alias_lowers_to_low():
    # "medium" is a display alias of "default"; it must resolve on the ladder, not vanish.
    assert biasEffort("medium", "fast") == "low"


def test_bias_effort_unknown_effort_unchanged():
    # An effort string not on the ladder is never mutated -- safe passthrough.
    assert biasEffort("weird", "fast") == "weird"


def test_pre_act_routing_deliberate_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", False)
    assert preActRouting({"meta": {}}, "tactics", {}) == "deliberate"


def test_pre_act_routing_returns_route_when_enabled(monkeypatch):
    from human_nature import integration
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(integration, "route_pre_act", lambda *a, **k: "fast")
    assert hnb.preActRouting({"meta": {}}, "tactics", {}) == "fast"


def test_pre_act_routing_never_raises(monkeypatch):
    from human_nature import integration
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)

    def _boom(*a, **k):
        raise RuntimeError("intuition down")

    monkeypatch.setattr(integration, "route_pre_act", _boom)
    assert hnb.preActRouting({"meta": {}}, "tactics", {}) == "deliberate"


def test_pre_act_routing_signals_default_none(monkeypatch):
    from human_nature import integration
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    seen = {}

    def _capture(state, domain, signals, **k):
        seen["signals"] = signals
        return "deliberate"

    monkeypatch.setattr(integration, "route_pre_act", _capture)
    hnb.preActRouting({"meta": {}}, "tactics")
    assert seen["signals"] == {}  # None → {} best-effort default


# --- call-site integration: _hnBiasEffort in the executor attempt path ----------


class _AttemptState:
    """Minimal TaskState stand-in for _hnBiasEffort (reads .meta only)."""

    def __init__(self, domain: str = "tactics") -> None:
        self.meta = {"domain": domain}


def _attempt_host():
    from platform_core.orchestration.execute_attempt_mixin import (
        OrchestratorExecuteAttemptMixin,
    )

    return OrchestratorExecuteAttemptMixin()


def test_call_site_lowers_effort_when_routing_fast(monkeypatch):
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(hnb, "preActRouting", lambda *a, **k: "fast")
    host = _attempt_host()
    state = _AttemptState()
    subtask = {"type": "tactics"}
    spec = {"effort_level": "high"}

    host._hnBiasEffort(state, subtask, spec)

    assert spec["effort_level"] == "default"  # one tier lower


def test_call_site_leaves_effort_unchanged_when_deliberate(monkeypatch):
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(hnb, "preActRouting", lambda *a, **k: "deliberate")
    host = _attempt_host()
    state = _AttemptState()
    subtask = {"type": "tactics"}
    spec = {"effort_level": "high", "prompt": "keep me"}

    host._hnBiasEffort(state, subtask, spec)

    assert spec["effort_level"] == "high"  # untouched
    assert spec["prompt"] == "keep me"  # nothing else touched
    assert set(spec) == {"effort_level", "prompt"}  # no keys added/removed


def test_call_site_noop_when_hn_disabled(monkeypatch):
    # Flags off -> preActRouting returns "deliberate" -> effort unchanged.
    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", False)
    host = _attempt_host()
    state = _AttemptState()
    spec = {"effort_level": "xhigh"}

    host._hnBiasEffort(state, {"type": "tactics"}, spec)

    assert spec["effort_level"] == "xhigh"


def test_call_site_never_raises(monkeypatch):
    from platform_core.orchestration import human_nature_bridge as hnb

    def _boom(*a, **k):
        raise RuntimeError("routing down")

    monkeypatch.setattr(hnb, "preActRouting", _boom)
    host = _attempt_host()
    spec = {"effort_level": "high"}

    host._hnBiasEffort(_AttemptState(), {"type": "tactics"}, spec)  # must not raise

    assert spec["effort_level"] == "high"  # unchanged on error
