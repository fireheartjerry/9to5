"""Parallel batch claims + isolates each subtask when WORKTREE_ISOLATION_ENABLED; the
residual guard only skips remediation on a SHARED tree under parallelism."""
import threading
import time
from pathlib import Path

import config
from platform_core.orchestration import parallel_safety
from platform_core.orchestration.review_mixin import OrchestratorReviewMixin
from platform_core.orchestration.run_loop_mixin import OrchestratorRunLoopMixin
from platform_core.runtime import worktree
from platform_core.runtime.control import AbortRun


class _Guarded(OrchestratorReviewMixin):
    pass


class _LoopHost(OrchestratorRunLoopMixin):
    def __init__(self):
        self._state_lock = threading.Lock()


class _FakeState:
    def __init__(self):
        self.meta = {}
        self.task_id = "test-task"
        self.subtasks: list = []

    def getSubtask(self, sid):
        return {}

    def updateSubtask(self, *a, **k):
        pass

    def addNotification(self, *a, **k):
        pass

    def nextActionable(self):
        return None


def test_abort_cleans_every_entered_worktree(monkeypatch):
    """On AbortRun the batch loop breaks; every ENTERED worktree must still be exited
    (no leaked worktrees + claims), not just the future that raised."""
    monkeypatch.setattr(config, "WORKTREE_ISOLATION_ENABLED", True, raising=False)
    monkeypatch.setattr(parallel_safety, "claim", lambda state, sid: True)
    entered, exited = [], []

    def _enter(state, sid):
        path = f"/wt/{sid}"
        entered.append(path)
        return worktree.WorktreeLease(sid, Path(path), f"wt/test/{sid}", "base")

    def _exit(lease, *, merge):
        exited.append(str(lease.path))
        return worktree.WorktreeResult(True, merge, True)

    monkeypatch.setattr(worktree, "enterWorktreeLease", _enter)
    monkeypatch.setattr(worktree, "exitWorktreeLease", _exit)

    host = _LoopHost()

    def _fake_exec(state, st, doc, work_dir, bus, dash, position, ctx, defer_completion=False):
        if st["subtask_id"] == "st-A":
            raise AbortRun("operator abort")   # completes first -> triggers the break
        time.sleep(0.2)                         # still running when the break cancels it
        return "done"

    host._executeSubtask = _fake_exec
    batch = [{"subtask_id": "st-A"}, {"subtask_id": "st-B"}]
    _, abort = host._handleParallelBatch(_FakeState(), batch, "doc", "/wd",
                                         object(), object(), 0, 2)
    assert isinstance(abort, AbortRun)
    assert len(entered) == 2
    assert {p.replace("\\", "/") for p in exited} == set(entered)  # BOTH leases cleaned despite the abort


def test_gc_orphans_runs_at_loop_start(monkeypatch):
    """gcOrphans must be wired into run teardown/startup (not dead code): reclaim a prior
    crash's stale worktrees before scheduling any work."""
    monkeypatch.setattr(config, "WORKTREE_ISOLATION_ENABLED", True, raising=False)
    called = []
    monkeypatch.setattr(worktree, "gcOrphans", lambda state: called.append(state))

    host = _LoopHost()
    host._deadlinePassed = lambda state: False
    host._livelockGuard = lambda *a, **k: None
    host._checkControl = lambda *a, **k: None
    host._maybeInstinct = lambda *a, **k: None

    class _Bus:
        def isForceReplan(self):
            return False

    state = _FakeState()   # nextActionable None + not self-referential -> loop drains, breaks
    host.runExecutionLoop(state, "doc", "/wd", _Bus(), object(), parallelism=1)
    assert called and called[0] is state


def test_residual_guard_skips_only_shared_tree_under_parallelism(monkeypatch):
    g = _Guarded()
    g._parallelism = 2
    # Isolated worktree path -> remediation ALLOWED (the gate the epic removes).
    monkeypatch.setattr(worktree, "isIsolated", lambda p: True)
    assert g._remediationUnsafe("/state/.sc-worktrees/abc/st-001") is False
    # Shared tree under parallelism -> still unsafe (today's safety net when flag off).
    monkeypatch.setattr(worktree, "isIsolated", lambda p: False)
    assert g._remediationUnsafe("/shared/tree") is True


def test_residual_guard_safe_when_sequential(monkeypatch):
    g = _Guarded()
    g._parallelism = 1
    monkeypatch.setattr(worktree, "isIsolated", lambda p: False)
    assert g._remediationUnsafe("/shared/tree") is False   # no peers -> safe to snapshot/revert
