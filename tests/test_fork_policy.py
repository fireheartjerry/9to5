"""shouldFork is opt-in: fork_eligible flag is the ONLY trigger (fork-as-retry OFF)."""
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
