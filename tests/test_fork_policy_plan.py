"""forkPlan emits N distinct seeds spanning effort x angle."""
from platform_core.orchestration import fork_policy as fp


def test_plan_emits_n_distinct_seeds():
    plan = fp.forkPlan({"subtask_id": "st-001"}, n=2)
    assert plan.n == 2
    assert len(plan.branch_seeds) == 2
    ids = [s.branch_id for s in plan.branch_seeds]
    assert ids == ["b0", "b1"]
    # No two seeds identical on (effort, angle).
    fingerprints = {(s.effort_level, s.angle_hint) for s in plan.branch_seeds}
    assert len(fingerprints) == 2


def test_plan_seeds_carry_routed_model():
    import config
    plan = fp.forkPlan({"subtask_id": "st-001"}, n=2)
    for s in plan.branch_seeds:
        assert s.model == config.MODEL_BY_EFFORT[s.effort_level]


def test_plan_caps_at_angle_bank_but_stays_distinct():
    plan = fp.forkPlan({"subtask_id": "st-001"}, n=3)
    assert len(plan.branch_seeds) == 3
    fingerprints = {(s.effort_level, s.angle_hint) for s in plan.branch_seeds}
    assert len(fingerprints) == 3
