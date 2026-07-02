"""Tests for the composite Health Aura score + color thresholds."""
from notifications.health_aura import aura_color, compute_health


class _S:
    def __init__(self, meta, subtasks, data):
        self.meta, self.subtasks, self.data = meta, subtasks, data


def _state(subs=None, notifs=None, advs=None, started=None, deadline=None):
    meta = {"started_at": started, "deadline_at": deadline}
    return _S(meta, subs or [], {"notifications": notifs or [], "adversary_reviews": advs or []})


def test_perfect_run_is_100():
    s = _state(subs=[{"subtask_id": "st-001", "status": "done", "attempts": 1,
                      "verify_result": {"passed": True}}])
    assert compute_health(s) == 100


def test_empty_state_is_100():
    assert compute_health(_state()) == 100


def test_replans_penalize():
    s = _state(notifs=[{"kind": "replan"}] * 4)  # min(30, 4*10) = 30
    assert compute_health(s) == 70


def test_replan_penalty_capped_at_30():
    s = _state(notifs=[{"kind": "replan"}] * 9)  # min(30, 90) = 30
    assert compute_health(s) == 70


def test_adversary_and_failed_verifies():
    s = _state(advs=[{}] * 5,
               subs=[{"subtask_id": "st-001", "status": "failed", "attempts": 1,
                      "verify_result": {"passed": False}}])
    # adversary: -min(20, 5*5)= -20 ; failed verify: -min(20, 1*5)= -5
    assert compute_health(s) == 75


def test_retry_overhead():
    s = _state(subs=[{"subtask_id": "st-001", "status": "done", "attempts": 3,
                      "verify_result": {"passed": True}}])
    # retry_count = attempts-1 = 2 ; -min(20, 2*3) = -6
    assert compute_health(s) == 94


def test_max_non_pace_penalties_floor_at_10():
    # 100 - 30(replan) - 20(adv) - 20(verify) - 20(retry) = 10; pace can't fire (done==0).
    s = _state(notifs=[{"kind": "replan"}] * 10, advs=[{}] * 10,
               subs=[{"subtask_id": f"st-{i}", "status": "failed", "attempts": 4,
                      "verify_result": {"passed": False}} for i in range(10)])
    assert compute_health(s) == 10


def test_score_clamped_to_zero_with_pace():
    # one done subtask far behind schedule pulls the -10 pace penalty; total hits the 0 floor.
    from datetime import datetime, timedelta
    started = (datetime.now().astimezone() - timedelta(hours=9)).isoformat()
    deadline = (datetime.now().astimezone() + timedelta(hours=1)).isoformat()
    subs = [{"subtask_id": "st-0", "status": "done", "attempts": 4,
             "verify_result": {"passed": True}}]
    subs += [{"subtask_id": f"st-{i}", "status": "failed", "attempts": 4,
              "verify_result": {"passed": False}} for i in range(1, 6)]
    s = _state(notifs=[{"kind": "replan"}] * 10, advs=[{}] * 10, subs=subs,
               started=started, deadline=deadline)
    s.meta["planned_subtasks"] = 50
    assert compute_health(s) == 0


def test_colors():
    assert aura_color(91) == "#00d4aa"
    assert aura_color(80) == "#00d4aa"
    assert aura_color(79) == "#ff9f00"
    assert aura_color(50) == "#ff9f00"
    assert aura_color(49) == "#ff4444"
    assert aura_color(10) == "#ff4444"


def test_never_raises_on_garbage():
    bad = _S(meta=None, subtasks="not a list", data=None)
    assert isinstance(compute_health(bad), int)
