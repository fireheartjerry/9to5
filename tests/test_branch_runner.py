"""runBranches: N results, a crashing branch is excluded-not-fatal, concurrency is capped."""
import threading

from platform_core.orchestration import branch_runner as br
from platform_core.orchestration import fork_policy as fp
from platform_core.orchestration import fork_seams as fs


def _plan(n):
    return fp.forkPlan({"subtask_id": "st-001"}, n=n)


def test_runs_one_result_per_seed():
    plan = _plan(2)

    def run_one(seed):
        return br.BranchResult(branch_id=seed.branch_id, seed=seed, worktree_path=f"/wt/{seed.branch_id}",
                               spec={}, result={}, vresult={"passed": True}, combined="", passed=True,
                               headline=fs.VERIFIED, diff_lines=10, cost_usd=1.0, crashed=False)

    results = br.runBranches(plan, run_one_branch=run_one, max_concurrency=2)
    assert len(results) == 2
    assert {r.branch_id for r in results} == {"b0", "b1"}


def test_crashing_branch_marked_not_fatal():
    plan = _plan(2)

    def run_one(seed):
        if seed.branch_id == "b1":
            raise RuntimeError("branch blew up")
        return br.BranchResult(branch_id=seed.branch_id, seed=seed, worktree_path="/wt/b0",
                               spec={}, result={}, vresult={"passed": True}, combined="", passed=True,
                               headline=fs.VERIFIED, diff_lines=10, cost_usd=1.0, crashed=False)

    results = br.runBranches(plan, run_one_branch=run_one, max_concurrency=2)
    assert len(results) == 2
    crashed = [r for r in results if r.crashed]
    assert len(crashed) == 1 and crashed[0].branch_id == "b1"
    assert crashed[0].headline == fs.NOT_VERIFIED   # a crash can never be eligible


def test_concurrency_respects_cap():
    plan = _plan(3)
    active = {"now": 0, "max": 0}
    lock = threading.Lock()
    barrier_evt = threading.Event()

    def run_one(seed):
        with lock:
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
        barrier_evt.wait(0.05)
        with lock:
            active["now"] -= 1
        return br.BranchResult(branch_id=seed.branch_id, seed=seed, worktree_path="/wt",
                               spec={}, result={}, vresult={}, combined="", passed=True,
                               headline=fs.VERIFIED, diff_lines=1, cost_usd=0.0, crashed=False)

    br.runBranches(plan, run_one_branch=run_one, max_concurrency=1)
    assert active["max"] == 1   # cap honored even though plan has 3 seeds
