"""shouldFork is opt-in: fork_eligible flag is the ONLY trigger (fork-as-retry OFF).

forkPlan emits N distinct seeds spanning effort x angle.
"""
from platform_core.orchestration import fork_policy as fp


def _kwargs(**over):
    base = dict(enabled=True, projected_cost=2.0, cost_ceiling=5.0,
                worktree_isolated=True, goal_elaborated="build a feature spanning multiple files",
                is_self_referential=False)
    base.update(over)
    return base


def test_forks_only_when_eligible_flag_set():
    assert fp.shouldFork({"fork_eligible": True}, **_kwargs()) is True
    assert fp.shouldFork({"fork_eligible": False}, **_kwargs()) is False
    assert fp.shouldFork({}, **_kwargs()) is False


def test_high_effort_alone_does_not_fork():   # fork-as-retry / auto triggers OFF
    assert fp.shouldFork({"effort_level": "xhigh"}, **_kwargs()) is False


def test_global_flag_off_never_forks():
    assert fp.shouldFork({"fork_eligible": True}, **_kwargs(enabled=False)) is False


def test_over_cost_ceiling_downgrades():
    assert fp.shouldFork({"fork_eligible": True}, **_kwargs(projected_cost=9.0)) is False


def test_no_isolation_never_forks():
    assert fp.shouldFork({"fork_eligible": True}, **_kwargs(worktree_isolated=False)) is False


def test_single_deliverable_excluded():
    assert fp.shouldFork({"fork_eligible": True},
                         **_kwargs(goal_elaborated="edit config.py")) is False


def test_self_referential_excluded():
    assert fp.shouldFork({"fork_eligible": True}, **_kwargs(is_self_referential=True)) is False


def test_discovery_profile_can_opt_in_design_fork():
    st = {"title": "Explore transformative architecture", "description": "ambiguous design options"}
    assert fp.shouldFork(st, **_kwargs(work_profile="inventor")) is True


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


def test_profile_shapes_fork_angles():
    plan = fp.forkPlan({"subtask_id": "st-001"}, n=3, work_profile="auditor")
    assert any("test-first" in s.angle_hint for s in plan.branch_seeds)
    assert any("conservative" in s.angle_hint for s in plan.branch_seeds)
