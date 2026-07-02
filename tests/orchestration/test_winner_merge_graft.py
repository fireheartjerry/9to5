"""Graft is advisory: routes the runner-up idea through _remediate, gated, skipped without a runner-up."""
from platform_core.orchestration import winner_merge as wm
from platform_core.orchestration import branch_runner as br
from platform_core.orchestration import fork_seams as fs


class SpyOrch:
    def __init__(self): self.remediate_calls = []
    def _remediate(self, state, subtask, architect_doc, exec_cwd, concerns, cancel_check=None):
        self.remediate_calls.append(concerns); return {"passed": True}


def _runner_up():
    return br.BranchResult(branch_id="b0", seed=None, worktree_path="/wt/b0", spec={},
                           result={}, vresult={"diff_summary": "did X", "residual_risks": "watch Y"},
                           combined="", passed=True, headline=fs.VERIFIED, diff_lines=10, cost_usd=1.0)


def test_graft_off_is_noop():
    orch = SpyOrch()
    wm.graftRunnerUp(orch, {}, {}, "ARCH", "/cwd", _runner_up(), enabled=False)
    assert orch.remediate_calls == []


def test_graft_on_routes_runner_up_idea_through_remediate():
    orch = SpyOrch()
    wm.graftRunnerUp(orch, {}, {"subtask_id": "st-001"}, "ARCH", "/cwd", _runner_up(), enabled=True)
    assert len(orch.remediate_calls) == 1
    assert "did X" in orch.remediate_calls[0][0]


def test_graft_skipped_when_no_runner_up():
    orch = SpyOrch()
    wm.graftRunnerUp(orch, {}, {}, "ARCH", "/cwd", None, enabled=True)
    assert orch.remediate_calls == []
