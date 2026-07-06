"""Tests for platform_core/orchestration/human_nature_bridge/planning.py::opinionVote --
the earned-authority VOTE coupling on the plan gate.

INVARIANT under test: opinionVote may only FLAG/down-rank a subtask by appending a
weighted, logged entry to state.meta["hn_votes"] -- it must NEVER remove, skip, or
reorder a planned subtask, and must NEVER raise.
"""
from __future__ import annotations

import config
from state.task import TaskState


def _make_state(domain: str = "tactics") -> TaskState:
    state = TaskState.create("build the auth flow", 1.0)
    state.meta["domain"] = domain
    state.subtasks.append(
        {
            "subtask_id": "st-001",
            "title": "harden the auth token path",
            "type": domain,
            "status": "pending",
        }
    )
    return state


def _high_track_record(judgment_type, domain, **k):
    # Enough volume + rate to clear the "veto" earned ceiling in human_nature.authority.
    return {"hits": 49, "total": 50, "rate": 0.98}


def test_opinion_vote_off_when_hn_disabled(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import planning

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", False)
    monkeypatch.setattr(config, "HN_PLAN_AUTHORITY", True)
    state = _make_state()
    assert planning.opinionVote(state, None) == []
    assert "hn_votes" not in state.meta


def test_opinion_vote_off_when_plan_authority_disabled(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import planning

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_PLAN_AUTHORITY", False)
    state = _make_state()
    assert planning.opinionVote(state, None) == []
    assert "hn_votes" not in state.meta


def test_opinion_vote_casts_vote_for_high_conviction_tactics(monkeypatch):
    import memory.conviction_ledger as ledger
    from human_nature import operator_authority
    from platform_core.orchestration.human_nature_bridge import planning

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_PLAN_AUTHORITY", True)
    monkeypatch.setattr(planning, "_convictionFor", lambda *a, **k: 0.99)
    monkeypatch.setattr(ledger, "track_record", _high_track_record)
    # Unknown-domain-safe default caps every domain at "cosmetic"; a deployment that
    # has cleared "tactics" for safety lifts that cap, exposing the vote/hold path.
    monkeypatch.setattr(operator_authority, "safety_ceiling", lambda domain: "veto")
    events = []

    class _Dash:
        def event(self, msg):
            events.append(msg)

    state = _make_state("tactics")
    votes = planning.opinionVote(state, _Dash())

    assert votes, "expected a cast vote for a high-conviction earned-authority domain"
    assert votes[0]["domain"] == "tactics"
    assert votes[0]["tier"] in ("vote", "hold", "veto")
    assert votes[0]["flag"] is True
    assert votes[0]["weight"] == 0.99
    assert state.meta["hn_votes"] == votes
    assert any("vote" in e for e in events), events


def test_opinion_vote_duplicate_vote_is_idempotent(monkeypatch):
    import memory.conviction_ledger as ledger
    from human_nature import operator_authority
    from platform_core.orchestration.human_nature_bridge import planning

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_PLAN_AUTHORITY", True)
    monkeypatch.setattr(planning, "_convictionFor", lambda *a, **k: 0.99)
    monkeypatch.setattr(ledger, "track_record", _high_track_record)
    monkeypatch.setattr(operator_authority, "safety_ceiling", lambda domain: "veto")
    state = _make_state("tactics")

    first = planning.opinionVote(state, None)
    second = planning.opinionVote(state, None)

    assert second == first
    assert state.meta["hn_votes"] == first


def test_opinion_vote_no_vote_for_low_conviction(monkeypatch):
    import memory.conviction_ledger as ledger
    from platform_core.orchestration.human_nature_bridge import planning

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_PLAN_AUTHORITY", True)
    monkeypatch.setattr(planning, "_convictionFor", lambda *a, **k: 0.0)
    monkeypatch.setattr(
        ledger, "track_record", lambda jt, dom, **k: {"hits": 0, "total": 0, "rate": 0.0}
    )
    state = _make_state("tactics")

    votes = planning.opinionVote(state, None)

    assert votes == []
    assert "hn_votes" not in state.meta


def test_opinion_vote_never_removes_or_reorders_subtasks(monkeypatch):
    """INVARIANT: even a cast vote only flags -- it must never mutate the plan itself."""
    import memory.conviction_ledger as ledger
    from human_nature import operator_authority
    from platform_core.orchestration.human_nature_bridge import planning

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_PLAN_AUTHORITY", True)
    monkeypatch.setattr(planning, "_convictionFor", lambda *a, **k: 0.99)
    monkeypatch.setattr(ledger, "track_record", _high_track_record)
    monkeypatch.setattr(operator_authority, "safety_ceiling", lambda domain: "veto")

    state = _make_state("tactics")
    before_statuses = [s["status"] for s in state.subtasks]
    before_count = len(state.subtasks)

    planning.opinionVote(state, None)

    assert [s["status"] for s in state.subtasks] == before_statuses
    assert len(state.subtasks) == before_count
    for key in ("abort", "reject", "hold", "plan_rejected"):
        assert key not in state.meta


def test_opinion_vote_never_raises(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import planning

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_PLAN_AUTHORITY", True)

    def _boom(*a, **k):
        raise RuntimeError("ledger down")

    monkeypatch.setattr(planning, "_convictionFor", _boom)
    state = _make_state("tactics")

    assert planning.opinionVote(state, None) == []
    assert "hn_votes" not in state.meta
