# tests/test_trajectory_parallel.py
"""Trajectory thread-safety under parallel pool workers (Epic 1 FIX 1).

Covers:
  (a) the executor span is a per-thread LOCAL (no shared self._cur_exec_span) so one worker
      never closes/mis-costs another worker's span;
  (b) the lazy Recorder is built exactly once per run even under concurrent first-touch;
  (c) the spawn-link env var is restored after each attempt (no stale leak to later spawns).
"""
import os
import threading
import time

import config
from platform_core.orchestration.execute_mixin import OrchestratorExecuteMixin
from platform_core.runtime import trajectory
from platform_core.runtime.trajectory import Recorder

_ENV_KEY = "NINE_TO_FIVE_PARENT_TRAJECTORY_STEP_ID"


class _Host(OrchestratorExecuteMixin):
    def __init__(self):
        self._state_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Plain Recorder under concurrency (requested 8-way open/close stress).
# ---------------------------------------------------------------------------
def test_concurrent_recorder_spans_all_close_with_parent_linkage(tmp_path):
    rec = Recorder("run-par", root=tmp_path)
    root = rec.openSpan("executor", None, {"sid": "root"})
    child_ids: list[str] = []
    lock = threading.Lock()

    def _cycle(n):
        cid = rec.openSpan("tool", root, {"tool": f"t{n}"})
        time.sleep(0.01)
        rec.closeSpan(cid, usage={"input_tokens": n}, cost_usd=float(n))
        with lock:
            child_ids.append(cid)

    threads = [threading.Thread(target=_cycle, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    rec.closeSpan(root, usage=None, cost_usd=0.0)

    spans = rec._spans
    assert len(child_ids) == 8
    for cid in child_ids:
        assert spans[cid]["closed_at"] is not None       # nobody left another's span open
        assert spans[cid]["parent_id"] == root           # correct parent linkage preserved


# ---------------------------------------------------------------------------
# (b) lazy-init builds exactly ONE Recorder per run under a concurrent stampede.
# ---------------------------------------------------------------------------
def test_trajectory_recorder_lazy_init_single_instance(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "TRAJECTORY_ENABLED", True, raising=False)
    built = []

    class _CountingRecorder(Recorder):
        def __init__(self, run_id, root=None):
            time.sleep(0.02)                              # widen the race window
            built.append(run_id)
            super().__init__(run_id, root=tmp_path)

    monkeypatch.setattr(trajectory, "Recorder", _CountingRecorder)
    host = _Host()

    class _State:
        task_id = "run-z"
        subtasks: list = []

    state = _State()
    got = []
    glock = threading.Lock()

    def _touch():
        r = host._trajectoryRecorder(state)
        with glock:
            got.append(r)

    threads = [threading.Thread(target=_touch) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(built) == 1                                # exactly one Recorder constructed
    assert all(r is got[0] for r in got)                  # every worker got the same instance


# ---------------------------------------------------------------------------
# (a)+(c) two concurrent _runOneAttempt: each closes ITS OWN span with ITS OWN
#         cost, and the spawn-link env var is restored afterward.
# ---------------------------------------------------------------------------
class _FakeState:
    def __init__(self, task_id):
        self.task_id = task_id
        self.subtasks: list = []
        self._subs: dict = {}
        self.meta: dict = {}

    def updateSubtask(self, sid, **kw):
        self._subs.setdefault(sid, {}).update(kw)

    def getSubtask(self, sid):
        return self._subs.get(sid, {"session": {}})

    def setResumeSession(self, sid, s):
        pass

    def addNotification(self, *a, **k):
        pass


class _FakeBus:
    def isAbort(self):
        return False

    def isKillSubprocess(self):
        return False


class _FakeDash:
    def update(self, *a, **k):
        pass


def test_run_one_attempt_spans_are_thread_local(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "TRAJECTORY_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "COST_BUDGET_ENABLED", False, raising=False)
    # Ship-dark: ensure the semantic-safety gate never calls _authorizeAttempt on
    # the bare _Host stub (which doesn't implement it), regardless of live .env.
    monkeypatch.setattr(config, "SEMANTIC_SAFETY_ENABLED", False, raising=False)
    os.environ.pop(_ENV_KEY, None)

    costs = {"st-A": 0.11, "st-B": 0.22}
    seen_parent: dict = {}
    seen_lock = threading.Lock()
    rec = Recorder("run-attempt", root=tmp_path)
    host = _Host()
    host._trajectory = rec   # pre-seed so the lazy-init returns this one recorder

    def _fake_run_claude(spec, **kw):
        sid = kw["subtask"]["subtask_id"]
        with seen_lock:
            seen_parent[sid] = kw.get("parent_trajectory_step_id")
        time.sleep(0.08)   # both threads open their span before either reaches finally
        return {"usage": {"input_tokens": 1}, "cost_usd": costs[sid],
                "stdout": "", "stderr": ""}

    host._run_claude = _fake_run_claude
    host._selectExecutor = lambda spec: host._run_claude
    host.authorInvocationSpec = lambda state, subtask, doc, fb: {
        "effort_level": "default", "prompt": "x"}
    host._narrate = lambda *a, **k: None
    host._deadlinePassed = lambda state: False
    host._runAttemptVerify = lambda *a, **k: ({"passed": True}, True, None, None)

    state = _FakeState("run-attempt")
    bus, dash = _FakeBus(), _FakeDash()

    def _attempt(sid):
        subtask = {"subtask_id": sid, "title": sid, "session": {}}
        host._runOneAttempt(state, subtask, "doc", str(tmp_path), bus, dash,
                            sid, None, None, None, 1)

    threads = [threading.Thread(target=_attempt, args=(s,)) for s in ("st-A", "st-B")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    by_sid = {s["attrs"].get("sid"): s for s in rec._spans.values()
              if s["kind"] == "executor"}
    assert set(by_sid) == {"st-A", "st-B"}
    for sid, cost in costs.items():
        span = by_sid[sid]
        assert span["closed_at"] is not None             # each thread closed its OWN span
        assert span["cost_usd"] == cost                  # no cross-thread cost misattribution
        # (c) each child received ITS OWN parent span id (no cross-thread spawn-link leak)
        assert seen_parent[sid] == span["step_id"]
    assert _ENV_KEY not in os.environ                    # never mutates the process-global env
