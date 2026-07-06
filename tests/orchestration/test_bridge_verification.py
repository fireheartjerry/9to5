"""Tests for platform_core/orchestration/human_nature_bridge/verification.py.

requestDeepen is ADDITIVE-ONLY: when the psyche's earned authority for the additive
'deepen_verification' action reaches the 'hold' (or 'veto') tier, it appends an advisory
deepen REQUEST to state.meta["hn_verify_deepen"] (capped at config.HN_MAX_VERIFY_DEEPEN).
It must never read or mutate any verifier verdict/status -- that belongs to the verifier.
"""
from __future__ import annotations

import config
from human_nature import authority, operator_authority


def _state(domain: str = "unknown") -> dict:
    return {"meta": {"domain": domain}}


def _unlock_hold(monkeypatch) -> None:
    """Clear every ceiling that would otherwise floor the 5-cap gate below "hold" so a
    high-conviction call can actually reach it. `requestDeepen` passes an empty track
    dict (no ledger history yet for this brand-new coupling -- mirrors the same
    track={} convention already used by instinct.py's resolveTier call), which means
    `authority.earned_ceiling` floors at "cosmetic" for total < MIN_SAMPLES; an
    operator-cleared deployment would have real history, so the test simulates that
    by patching earned_ceiling directly (same technique the authority_gate tests use
    for safety_ceiling)."""
    monkeypatch.setattr(config, "HN_AUTHORITY_MAX", "hold")
    monkeypatch.setattr(operator_authority, "safety_ceiling", lambda domain: "hold")
    monkeypatch.setattr(authority, "earned_ceiling", lambda track: "hold")


def test_request_deepen_off_when_hn_disabled(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import verification as v

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", False)
    monkeypatch.setattr(config, "HN_VERIFY_DEEPEN", True)
    state = _state("tactics")

    assert v.requestDeepen(state, reason="looks risky", conviction=0.99) == 0
    assert "hn_verify_deepen" not in state["meta"]


def test_request_deepen_off_when_flag_disabled(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import verification as v

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_VERIFY_DEEPEN", False)
    state = _state("tactics")

    assert v.requestDeepen(state, reason="looks risky", conviction=0.99) == 0
    assert "hn_verify_deepen" not in state["meta"]


def test_request_deepen_records_at_hold_tier(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import verification as v

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_VERIFY_DEEPEN", True)
    _unlock_hold(monkeypatch)
    state = _state("tactics")  # a known (veto-ceiling) domain -- doesn't block hold

    result = v.requestDeepen(state, reason="two similar regressions", conviction=0.99)

    assert result == 1
    assert state["meta"]["hn_verify_deepen"] == [
        {"reason": "two similar regressions", "conviction": 0.99}
    ]


def test_request_deepen_low_conviction_records_nothing(monkeypatch):
    """Even with every ceiling unlocked, a low conviction bands to "cosmetic" and
    nothing is recorded -- authority must be genuinely earned, not just unblocked."""
    from platform_core.orchestration.human_nature_bridge import verification as v

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_VERIFY_DEEPEN", True)
    _unlock_hold(monkeypatch)
    state = _state("tactics")

    result = v.requestDeepen(state, reason="meh", conviction=0.05)

    assert result == 0
    assert "hn_verify_deepen" not in state["meta"]


def test_request_deepen_capped_at_max(monkeypatch):
    """Calling it repeatedly at hold-tier conviction never exceeds HN_MAX_VERIFY_DEEPEN."""
    from platform_core.orchestration.human_nature_bridge import verification as v

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_VERIFY_DEEPEN", True)
    monkeypatch.setattr(config, "HN_MAX_VERIFY_DEEPEN", 2)
    _unlock_hold(monkeypatch)
    state = _state("tactics")

    results = [v.requestDeepen(state, reason=f"r{i}", conviction=0.99) for i in range(5)]

    assert results == [1, 2, 2, 2, 2]
    assert len(state["meta"]["hn_verify_deepen"]) == 2


def test_request_deepen_duplicate_request_is_idempotent(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import verification as v

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_VERIFY_DEEPEN", True)
    _unlock_hold(monkeypatch)
    state = _state("tactics")

    first = v.requestDeepen(state, reason="same risk", conviction=0.99)
    second = v.requestDeepen(state, reason="same risk", conviction=0.99)

    assert (first, second) == (1, 1)
    assert state["meta"]["hn_verify_deepen"] == [{"reason": "same risk", "conviction": 0.99}]


def test_request_deepen_never_touches_verifier_verdict(monkeypatch):
    """INVARIANT: requestDeepen only ever reads/writes meta["hn_verify_deepen"] -- it
    must never read or mutate anything resembling a verifier verdict/status."""
    from platform_core.orchestration.human_nature_bridge import verification as v

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_VERIFY_DEEPEN", True)
    _unlock_hold(monkeypatch)
    state = _state("tactics")
    state["verify_result"] = {"passed": True, "verdict": "clean"}
    before = dict(state["verify_result"])

    v.requestDeepen(state, reason="watch this", conviction=0.99)

    assert state["verify_result"] == before
    assert set(state["meta"]) == {"domain", "hn_verify_deepen"}


def test_request_deepen_never_raises(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import verification as v

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_VERIFY_DEEPEN", True)

    def _boom(*a, **k):
        raise RuntimeError("authority down")

    monkeypatch.setattr(v, "resolveTier", _boom)
    state = _state("tactics")

    assert v.requestDeepen(state, reason="x", conviction=0.99) == 0
    assert "hn_verify_deepen" not in state["meta"]


def test_request_deepen_dashboard_receipt(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import verification as v

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_VERIFY_DEEPEN", True)
    _unlock_hold(monkeypatch)
    state = _state("tactics")
    events = []

    class _Dash:
        def event(self, msg):
            events.append(msg)

    v.requestDeepen(state, reason="watch this", conviction=0.99, dashboard=_Dash())

    assert any("verify" in e.lower() for e in events), events


def test_request_deepen_dashboard_never_raises(monkeypatch):
    """A broken dashboard.event must not prevent the deepen request from being recorded."""
    from platform_core.orchestration.human_nature_bridge import verification as v

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_VERIFY_DEEPEN", True)
    _unlock_hold(monkeypatch)
    state = _state("tactics")

    class _BadDash:
        def event(self, msg):
            raise RuntimeError("dashboard down")

    result = v.requestDeepen(state, reason="x", conviction=0.99, dashboard=_BadDash())

    assert result == 1
    assert state["meta"]["hn_verify_deepen"] == [{"reason": "x", "conviction": 0.99}]
