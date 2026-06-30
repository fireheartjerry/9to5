"""runForked returns a _runAttemptLoop-shaped tuple; all-crash falls back to a single attempt."""
from state.task import TaskState
from platform_core.orchestration import solution_space as ss
from platform_core.orchestration import branch_runner as br
from platform_core.orchestration import fork_seams as fs


class FakeWorktree:
    def __init__(self): self.entered = []; self.exited = []; self.removed = []
    def enterWorktree(self, state, tag): self.entered.append(tag); return f"/wt/{tag}"
    def exitWorktree(self, path, merge=False): self.exited.append((path, merge)); return {"merged": merge}
    def removeWorktree(self, path): self.removed.append(path); return True
    def gcOrphans(self, state): return 0
    def isIsolated(self, path): return True


class FakeOrch:
    """Minimal stand-in for the execute mixin: exposes the seams runForked needs."""
    def __init__(self):
        import threading
        self._state_lock = threading.RLock()
        self.attempt_calls = []

    def _runAttemptLoop(self, state, subtask, architect_doc, exec_cwd, bus, dashboard, sid, verify_spec):
        self.attempt_calls.append(exec_cwd)
        vres = {"passed": True, "cmd": "x"}
        return ({"effort_level": "high"}, {"ok": True}, vres, "out", True, 1)


def _state():
    st = TaskState.create("build a multi-file feature", 1.0)
    st.addSubtask("title", "desc", fork_eligible=True)
    return st


def test_runforked_winner_path_returns_attempt_shaped_tuple(monkeypatch):
    state = _state()
    sub = state.subtasks[0]
    orch = FakeOrch()
    wt = FakeWorktree()
    monkeypatch.setattr(ss.fs, "loadWorktreeBackend", lambda: wt)

    # Two healthy branches, b1 VERIFIED beats b0 GAPS.
    def fake_run_branches(plan, *, run_one_branch, max_concurrency):
        out = []
        for i, seed in enumerate(plan.branch_seeds):
            run_one_branch(seed)   # exercise the real per-branch closure (enter worktree + attempt loop)
            out.append(br.BranchResult(branch_id=seed.branch_id, seed=seed,
                                       worktree_path=f"/wt/st-001#{seed.branch_id}", spec={"e": i},
                                       result={}, vresult={"passed": True, "b": seed.branch_id},
                                       combined="c", passed=True,
                                       headline=fs.VERIFIED if seed.branch_id == "b1" else fs.VERIFIED_WITH_GAPS,
                                       diff_lines=10, cost_usd=1.0, attempt=1))
        return out
    monkeypatch.setattr(ss.branch_runner, "runBranches", fake_run_branches)

    tup = ss.runForked(orch, state, sub, "ARCH", "/canonical", bus=None, dashboard=None,
                       sid="st-001", verify_spec={"cmd": "x"})
    assert isinstance(tup, tuple) and len(tup) == 6        # _runAttemptLoop shape
    spec, result, vresult, combined, passed, attempt = tup
    assert passed is True
    assert vresult["b"] == "b1"                            # the VERIFIED branch won
    assert ("/wt/st-001#b1", True) in wt.exited            # winner merged
    assert state.subtasks[0]["verify_result"]["b"] == "b1"  # canonical recordVerify = winner's vresult


def test_runforked_all_crash_falls_back_to_single_attempt(monkeypatch):
    state = _state()
    sub = state.subtasks[0]
    orch = FakeOrch()
    wt = FakeWorktree()
    monkeypatch.setattr(ss.fs, "loadWorktreeBackend", lambda: wt)

    def all_crashed(plan, *, run_one_branch, max_concurrency):
        return [br.BranchResult(branch_id=s.branch_id, seed=s, worktree_path="", spec=None,
                                result=None, vresult=None, combined="", passed=False,
                                headline=fs.NOT_VERIFIED, diff_lines=0, cost_usd=0.0, crashed=True)
                for s in plan.branch_seeds]
    monkeypatch.setattr(ss.branch_runner, "runBranches", all_crashed)

    tup = ss.runForked(orch, state, sub, "ARCH", "/canonical", bus=None, dashboard=None,
                       sid="st-001", verify_spec={"cmd": "x"})
    assert len(tup) == 6 and tup[4] is True
    assert orch.attempt_calls[-1] == "/canonical"          # fallback ran on the canonical tree
