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


def test_run_events_agency_is_numeric_not_self_string(monkeypatch):
    """REGRESSION: _runEvents must emit a NUMERIC agency, never the string "self".

    appraisal.appraise() coerces agency via float(); an agency of "self" raised
    `ValueError: could not convert string to float: 'self'` inside the appraisal path,
    which best_effort at teardown silently swallowed -- so affect was never written.
    """
    from human_nature.appraisal import appraise
    from platform_core.orchestration.human_nature_bridge import _runEvents

    state = TaskState.create("test goal", 1.0)
    state.subtasks.append({"subtask_id": "st-1", "title": "a", "status": "done"})
    state.subtasks.append({"subtask_id": "st-2", "title": "b", "status": "failed"})

    events = _runEvents(state)
    assert events, "expected appraisal events for done/failed subtasks"
    for e in events:
        assert isinstance(e["agency"], (int, float)) and not isinstance(e["agency"], bool)
    # Previously raised on float("self"); must now appraise cleanly.
    pad = appraise(events)
    assert {"valence", "arousal", "control"}.issubset(pad)


def test_teardown_writes_real_affect_when_enabled(monkeypatch):
    """REGRESSION: with HN on and a completed subtask, teardown's appraisal must actually
    WRITE affect into self_state. Before the fix the appraisal raised (agency="self") and
    best_effort swallowed it, leaving affect unset -- the crash the live run surfaced."""
    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    state = _make_state()  # one "done" subtask
    runPreambleHooks(state)
    runTeardownHooks(_FakeOrch(), state)
    affect = state.meta["self_state"].get("affect")
    assert affect is not None, "appraisal never wrote affect (silently swallowed crash)"
    assert affect["valence"] > 0.0  # a single successful subtask -> positive valence


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


# --- _convictionFor (ledger-grounded conviction sourcing) ----------------------


def test_conviction_for_zero_when_ledger_empty(monkeypatch, tmp_path):
    """Empty ledger / unseen domain -> 0.0 (cosmetic -> silent no-op)."""
    import memory.conviction_ledger as ledger
    from platform_core.orchestration import human_nature_bridge as hnb

    # track_record on an empty db returns {"hits":0,"total":0,"rate":0.0}.
    monkeypatch.setattr(
        ledger,
        "track_record",
        lambda jt, dom, **k: {"hits": 0, "total": 0, "rate": 0.0},
    )
    assert hnb._convictionFor(_make_opinion_state(), "tactics") == 0.0


def test_conviction_for_zero_when_accessor_raises(monkeypatch):
    """Best-effort: a ledger accessor that raises -> 0.0, never propagates."""
    import memory.conviction_ledger as ledger
    from platform_core.orchestration import human_nature_bridge as hnb

    def _boom(*a, **k):
        raise RuntimeError("conviction db locked")

    monkeypatch.setattr(ledger, "track_record", _boom)
    assert hnb._convictionFor(_make_opinion_state(), "tactics") == 0.0


def test_conviction_for_zero_below_min_samples(monkeypatch):
    """A 1/1 perfect record is NOT full conviction -- cold-start floor gives no teeth."""
    import memory.conviction_ledger as ledger
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(
        ledger,
        "track_record",
        lambda jt, dom, **k: {"hits": 1, "total": 1, "rate": 1.0},
    )
    assert hnb._convictionFor(_make_opinion_state(), "tactics") == 0.0


def test_conviction_for_returns_rate_when_enough_samples(monkeypatch):
    """With a proven track record (>= MIN_SAMPLES), conviction == the hit-rate in [0,1]."""
    import memory.conviction_ledger as ledger
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(
        ledger,
        "track_record",
        lambda jt, dom, **k: {"hits": 9, "total": 10, "rate": 0.9},
    )
    conv = hnb._convictionFor(_make_opinion_state(), "tactics")
    assert 0.0 <= conv <= 1.0
    assert abs(conv - 0.9) < 1e-9


def test_conviction_for_queries_opinion_type_and_domain(monkeypatch):
    """The accessor is called with the opinion judgment_type and the passed domain."""
    import memory.conviction_ledger as ledger
    from platform_core.orchestration import human_nature_bridge as hnb

    seen = {}

    def _capture(judgment_type, domain, **k):
        seen["jt"] = judgment_type
        seen["dom"] = domain
        return {"hits": 8, "total": 10, "rate": 0.8}

    monkeypatch.setattr(ledger, "track_record", _capture)
    hnb._convictionFor(_make_opinion_state(), "scope")
    assert seen["dom"] == "scope"
    assert seen["jt"]  # a non-empty judgment_type was used


def test_opinion_advisory_surfaces_hard_from_real_ledger(monkeypatch):
    """END-TO-END: HN + HN_OPINIONS_BEHAVIOR on, ledger yields a hit-rate >= HN_THETA_HARD
    for the subtask's (hard-ceiling) domain -> a 'hard' advisory is surfaced into
    state.meta['hn_opinions'] + a dashboard event fires -- and the plan is NEVER mutated."""
    import memory.conviction_ledger as ledger
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_OPINIONS_BEHAVIOR", True)
    # Proven, high hit-rate on a hard-ceiling domain -> conviction clears HN_THETA_HARD.
    monkeypatch.setattr(
        ledger,
        "track_record",
        lambda jt, dom, **k: {"hits": 19, "total": 20, "rate": 0.95},
    )
    events = []

    class _Dash:
        def event(self, msg):
            events.append(msg)

    state = _make_opinion_state()  # subtask type "tactics" (a hard-ceiling domain)
    before_statuses = [s["status"] for s in state.subtasks]
    before_count = len(state.subtasks)

    advisories = hnb.opinionAdvisory(state, _Dash())

    assert advisories, "expected a surfaced hard-tier advisory from the real ledger"
    assert advisories[0]["tier"] == "hard"
    assert advisories[0]["domain"] == "tactics"
    assert state.meta["hn_opinions"] == advisories
    assert any("opinion" in e for e in events), events
    # advisory-only invariant still holds: plan/subtasks untouched.
    assert [s["status"] for s in state.subtasks] == before_statuses
    assert len(state.subtasks) == before_count
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


# --- emotionAdvisory (affect -> emotion label -> behavior coupling) --------------


def _make_emotion_state(affect: "dict | None" = None) -> TaskState:
    state = TaskState.create("ship the feature", 1.0)
    ss = {"competence": {}, "affect": affect} if affect is not None else {"competence": {}}
    state.meta["self_state"] = ss
    return state


def test_emotion_advisory_off_is_noop_when_hn_disabled(monkeypatch):
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", False)
    monkeypatch.setattr(config, "HN_EMOTIONS_BEHAVIOR", True)
    state = _make_emotion_state({"valence": -0.9, "arousal": 0.9, "control": 0.0})
    assert hnb.emotionAdvisory(state, None) == {}
    assert "hn_behavior" not in state.meta


def test_emotion_advisory_off_is_noop_when_behavior_disabled(monkeypatch):
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_EMOTIONS_BEHAVIOR", False)
    state = _make_emotion_state({"valence": -0.9, "arousal": 0.9, "control": 0.0})
    assert hnb.emotionAdvisory(state, None) == {}
    assert "hn_behavior" not in state.meta


def test_emotion_advisory_couples_and_records(monkeypatch):
    from human_nature import emotions
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_EMOTIONS_BEHAVIOR", True)
    monkeypatch.setattr(config, "HN_MANIFOLD", False)  # exercise the legacy PAD label path
    seen = {}

    def _spy_couple(label, meta, **kw):
        seen["label"] = label
        seen["meta"] = meta
        return {"behavior": "escalate_effort", "comms": "frustration (functional)"}

    monkeypatch.setattr(emotions, "couple", _spy_couple)
    events = []

    class _Dash:
        def event(self, msg):
            events.append(msg)

    # low valence + high arousal -> frustration
    state = _make_emotion_state({"valence": -0.8, "arousal": 0.8, "control": 0.0})
    coupling = hnb.emotionAdvisory(state, _Dash())

    assert seen["label"] == "frustration"
    assert coupling["behavior"] == "escalate_effort"
    assert state.meta["hn_behavior"][-1] == {"emotion": "frustration", "behavior": "escalate_effort"}
    assert any("emotion" in e for e in events), events


def test_emotion_advisory_neutral_when_no_affect(monkeypatch):
    from human_nature import emotions
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_EMOTIONS_BEHAVIOR", True)
    seen = {}
    monkeypatch.setattr(
        emotions,
        "couple",
        lambda label, meta, **kw: seen.setdefault("label", label) or {"behavior": None, "comms": ""},
    )

    # self_state present but affect absent -> do not invent affect -> neutral
    state = _make_emotion_state(None)
    hnb.emotionAdvisory(state, None)
    assert seen["label"] == "neutral"


def test_emotion_advisory_never_raises(monkeypatch):
    from human_nature import emotions
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_EMOTIONS_BEHAVIOR", True)

    def _boom(*a, **k):
        raise RuntimeError("emotions down")

    monkeypatch.setattr(emotions, "couple", _boom)
    state = _make_emotion_state({"valence": -0.8, "arousal": 0.8, "control": 0.0})
    assert hnb.emotionAdvisory(state, None) == {}
    assert "hn_behavior" not in state.meta


def test_emotion_advisory_never_raises_on_bad_affect(monkeypatch):
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_EMOTIONS_BEHAVIOR", True)
    state = _make_emotion_state()
    # affect is a garbage type -> derive must swallow and default to neutral, never raise
    state.meta["self_state"]["affect"] = "not-a-dict"
    result = hnb.emotionAdvisory(state, None)
    assert isinstance(result, dict)  # did not raise


# --- affect -> label rule + bounded nudge helper (pure) -------------------------


def test_affect_to_label_rule():
    from platform_core.orchestration.human_nature_bridge import _affectToLabel

    assert _affectToLabel(None) == "neutral"
    assert _affectToLabel({}) == "neutral"
    assert _affectToLabel({"valence": 0.0, "arousal": 0.0, "control": 0.0}) == "neutral"
    assert _affectToLabel({"valence": 0.7, "arousal": 0.1, "control": 0.0}) == "satisfaction"
    assert _affectToLabel({"valence": -0.7, "arousal": 0.7, "control": 0.0}) == "frustration"
    assert _affectToLabel({"valence": -0.7, "arousal": 0.0, "control": 0.0}) == "anxiety"
    assert _affectToLabel({"valence": 0.0, "arousal": -0.7, "control": 0.0}) == "boredom"


def test_emotion_nudge_maps_safe_intents_and_clamps():
    from platform_core.orchestration.human_nature_bridge import emotionNudge

    # ONLY clearly-safe bounded intents map to +1; everything else is 0.
    assert emotionNudge("escalate_effort") == 1
    assert emotionNudge("raise_verification") == 1
    # abstract/unbounded intents -> record-only, no run effect
    assert emotionNudge("explore") == 0
    assert emotionNudge("propose_refactor") == 0
    assert emotionNudge(None) == 0
    assert emotionNudge("something_unknown") == 0
    # bounded in {0, +1}
    for intent in ("escalate_effort", "raise_verification", "explore", None, "x"):
        assert emotionNudge(intent) in (0, 1)


# --- attemptSignals (real retrieval/experience confidence signals) --------------


def _make_signal_state(goal: str = "harden the auth token path") -> TaskState:
    state = TaskState.create(goal, 1.0)
    state.meta["domain"] = "tactics"
    return state


def test_attempt_signals_empty_when_hn_disabled(monkeypatch):
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", False)
    state = _make_signal_state()
    assert hnb.attemptSignals(state, {"title": "do the thing"}) == {}


def test_attempt_signals_returns_real_numeric_keys(monkeypatch):
    """With retrieval returning high-similarity successes and no nearby failures,
    attemptSignals must surface real numeric similarity/p_true in [0, 1]."""
    import memory.retrieval as retrieval
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    # Two similar past SUCCESSES, no similar failures -> high confidence.
    monkeypatch.setattr(
        retrieval,
        "retrieve",
        lambda goal, title="", **k: [{"score": 0.93}, {"score": 0.88}],
    )
    monkeypatch.setattr(retrieval, "retrieve_failures", lambda goal, title="", **k: [])

    sig = hnb.attemptSignals(_make_signal_state(), {"title": "harden the auth token path"})

    assert set(sig).issubset({"p_true", "similarity"})
    assert sig  # non-empty: real data was present
    assert 0.0 <= sig["similarity"] <= 1.0
    assert abs(sig["similarity"] - 0.93) < 1e-9  # top score
    assert 0.0 <= sig["p_true"] <= 1.0
    assert sig["p_true"] == 1.0  # 2 successes, 0 failures nearby


def test_attempt_signals_p_true_reflects_failure_mix(monkeypatch):
    """p_true honestly drops when similar FAILURES sit alongside similar successes."""
    import memory.retrieval as retrieval
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(
        retrieval,
        "retrieve",
        lambda goal, title="", **k: [{"score": 0.9}, {"score": 0.8}, {"score": 0.75}],
    )
    monkeypatch.setattr(
        retrieval,
        "retrieve_failures",
        lambda goal, title="", **k: [{"score": 0.7}],
    )

    sig = hnb.attemptSignals(_make_signal_state(), {"title": "harden the auth token path"})

    # 3 successes / (3 successes + 1 failure) = 0.75
    assert abs(sig["p_true"] - 0.75) < 1e-9


def test_attempt_signals_empty_when_no_data(monkeypatch):
    import memory.retrieval as retrieval
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(retrieval, "retrieve", lambda goal, title="", **k: [])
    monkeypatch.setattr(retrieval, "retrieve_failures", lambda goal, title="", **k: [])

    # No retrieval hits, no brain confidence -> honest empty (deliberate default).
    assert hnb.attemptSignals(_make_signal_state(), {"title": "x"}) == {}


def test_attempt_signals_uses_brain_confidence_when_present(monkeypatch):
    """A numeric confidence carried on the subtask is used as p_true even with no retrieval."""
    import memory.retrieval as retrieval
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(retrieval, "retrieve", lambda goal, title="", **k: [])
    monkeypatch.setattr(retrieval, "retrieve_failures", lambda goal, title="", **k: [])

    sig = hnb.attemptSignals(_make_signal_state(), {"title": "x", "confidence": 0.9})
    assert sig.get("p_true") == 0.9


def test_attempt_signals_never_raises(monkeypatch):
    import memory.retrieval as retrieval
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)

    def _boom(*a, **k):
        raise RuntimeError("retrieval down")

    monkeypatch.setattr(retrieval, "retrieve", _boom)
    monkeypatch.setattr(retrieval, "retrieve_failures", _boom)
    assert hnb.attemptSignals(_make_signal_state(), {"title": "x"}) == {}


def test_attempt_signals_clamps_negative_cosine(monkeypatch):
    """Cosine can be negative; similarity must clamp into [0, 1]."""
    import memory.retrieval as retrieval
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(retrieval, "retrieve", lambda goal, title="", **k: [{"score": -0.4}])
    monkeypatch.setattr(retrieval, "retrieve_failures", lambda goal, title="", **k: [])

    sig = hnb.attemptSignals(_make_signal_state(), {"title": "x"})
    assert sig["similarity"] == 0.0


# --- end-to-end: real signals flow through the call site to lower effort --------


def test_call_site_lowers_effort_with_real_high_confidence(monkeypatch):
    """End-to-end: HN on + shortcut on + attemptSignals yielding high confidence
    routes 'fast' through the REAL snap/route fusion and lowers effort one tier."""
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_INTUITION_SHORTCUT", True)
    # Real fusion path: keep the theta reachable by a genuine high-confidence snap.
    monkeypatch.setattr(config, "HN_THETA_HARD", 0.6)
    monkeypatch.setattr(config, "HN_RECAL_TEMPERATURE", 1.0)
    monkeypatch.setattr(hnb, "attemptSignals", lambda state, subtask: {"p_true": 1.0, "similarity": 1.0})
    host = _attempt_host()
    state = _AttemptState()
    spec = {"effort_level": "high"}

    host._hnBiasEffort(state, {"type": "tactics", "title": "t"}, spec)

    assert spec["effort_level"] == "default"  # one tier lower via real routing


def test_call_site_unchanged_with_low_confidence(monkeypatch):
    """Absent/low confidence -> deliberate -> effort untouched (honest default)."""
    from platform_core.orchestration import human_nature_bridge as hnb

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_INTUITION_SHORTCUT", True)
    monkeypatch.setattr(hnb, "attemptSignals", lambda state, subtask: {})
    host = _attempt_host()
    state = _AttemptState()
    spec = {"effort_level": "high"}

    host._hnBiasEffort(state, {"type": "tactics", "title": "t"}, spec)

    assert spec["effort_level"] == "high"  # unchanged
