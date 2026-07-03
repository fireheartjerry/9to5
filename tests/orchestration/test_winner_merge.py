"""mergeWinner lands exactly the winner; reclaimLosers removes exactly the non-winners.

Graft is advisory: routes the runner-up idea through _remediate, gated, skipped without a runner-up.
"""
from platform_core.orchestration import winner_merge as wm
from platform_core.orchestration import branch_runner as br
from platform_core.orchestration import fork_seams as fs


class RecordingWorktree:
    def __init__(self):
        self.exited = []
        self.removed = []

    def enterWorktree(self, state, tag): return f"/wt/{tag}"
    def exitWorktree(self, path, merge=False):
        self.exited.append((path, merge))
        return {"merged": merge}
    def removeWorktree(self, path):
        self.removed.append(path)
        return True
    def gcOrphans(self, state): return 0
    def isIsolated(self, path): return True


def _branch(bid, headline=fs.VERIFIED):
    return br.BranchResult(branch_id=bid, seed=None, worktree_path=f"/wt/{bid}", spec={},
                           result={}, vresult={"passed": True, "branch": bid}, combined="",
                           passed=True, headline=headline, diff_lines=10, cost_usd=1.0)


def test_merge_winner_exits_only_winner_with_merge_true():
    wt = RecordingWorktree()
    winner = _branch("b1")
    vres = wm.mergeWinner(winner, worktree=wt)
    assert wt.exited == [("/wt/b1", True)]
    assert vres == {"passed": True, "branch": "b1"}   # returns winner vresult for canonical commit


def test_reclaim_removes_exactly_non_winners():
    wt = RecordingWorktree()
    branches = [_branch("b0"), _branch("b1"), _branch("b2")]
    winner = branches[1]
    wm.reclaimLosers(branches, winner, worktree=wt)
    assert set(wt.removed) == {"/wt/b0", "/wt/b2"}    # winner's tree is kept (it was merged)


def test_reclaim_is_best_effort_on_failure():
    class Flaky(RecordingWorktree):
        def removeWorktree(self, path):
            raise OSError("locked")
    branches = [_branch("b0"), _branch("b1")]
    # Must not raise -- a removal failure logs and is swept later by gcOrphans (Epic 1).
    wm.reclaimLosers(branches, branches[1], worktree=Flaky())


class SpyOrch:
    def __init__(self): self.remediate_calls = []
    def _remediate(self, state, subtask, architect_doc, exec_cwd, concerns, cancel_check=None):
        self.remediate_calls.append(concerns)
        return {"passed": True}


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
