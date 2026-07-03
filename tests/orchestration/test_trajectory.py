# tests/orchestration/test_trajectory.py
"""Tests for the eliza-style append-only JSONL trajectory recorder.

Trajectory thread-safety under parallel pool workers (Epic 1 FIX 1).

Covers:
  (a) the executor span is a per-thread LOCAL (no shared self._cur_exec_span) so one worker
      never closes/mis-costs another worker's span;
  (b) the lazy Recorder is built exactly once per run even under concurrent first-touch;
  (c) the spawn-link env var is restored after each attempt (no stale leak to later spawns).
"""
import json
import os
import threading
import time

import config
from platform_core.orchestration.execute_mixin import OrchestratorExecuteMixin
from platform_core.runtime import trajectory
from platform_core.runtime.trajectory import Recorder, loadSpans


def test_span_tree_parent_child(tmp_path):
    rec = trajectory.Recorder("run-abc", root=tmp_path)
    root_id = rec.openSpan("executor", None, {"sid": "st-001"})
    child_id = rec.openSpan("tool", root_id, {"tool": "Edit"})
    rec.closeSpan(child_id, usage={"input_tokens": 10}, cost_usd=0.0)
    rec.closeSpan(root_id, usage={"input_tokens": 50}, cost_usd=0.42)

    data = trajectory.loadSpans("run-abc", root=tmp_path)
    spans = {s["step_id"]: s for s in data["spans"]}
    assert spans[child_id]["parent_id"] == root_id
    assert spans[child_id]["kind"] == "tool"
    assert spans[root_id]["cost_usd"] == 0.42
    assert spans[child_id]["cost_usd"] == 0.0          # honest-zero for local Ollama
    assert spans[root_id]["usage"]["input_tokens"] == 50


def test_append_only_one_line_per_event(tmp_path):
    """O(1) per event: each open/close appends exactly ONE line -- no whole-file rewrite,
    no temp files, no fixed-temp-name race."""
    rec = trajectory.Recorder("run-x", root=tmp_path)
    sid = rec.openSpan("planner", None, {})
    rec.closeSpan(sid, usage=None, cost_usd=0.0)
    assert not list(tmp_path.glob("*.tmp"))
    lines = (tmp_path / "run-x.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2                             # one open + one close event
    assert json.loads(lines[0])["ev"] == "open"
    assert json.loads(lines[1])["ev"] == "close"


def test_replay_reconstructs_same_tree_old_writer_produced(tmp_path):
    """Property: replaying the JSONL yields the exact span dicts the recorder holds in
    memory (the shape the old whole-tree writer used to persist)."""
    rec = trajectory.Recorder("run-prop", root=tmp_path)
    a = rec.openSpan("executor", None, {"sid": "st-A"})
    b = rec.openSpan("tool", a, {"tool": "Bash"})
    c = rec.openSpan("verify", a, {})
    rec.closeSpan(b, usage={"input_tokens": 7}, cost_usd=0.01)
    rec.closeSpan(c, usage=None, cost_usd=0.0)
    rec.closeSpan(a, usage={"input_tokens": 99}, cost_usd=1.5)

    expected = {"run_id": "run-prop", "spans": [rec._spans[s] for s in rec._order]}
    assert trajectory.loadSpans("run-prop", root=tmp_path) == expected


def test_loader_accepts_legacy_whole_tree_json(tmp_path):
    """One-release compat: a pre-JSONL <run_id>.json span tree still loads."""
    legacy = {"run_id": "run-old", "spans": [
        {"step_id": "s1", "parent_id": None, "kind": "planner", "attrs": {},
         "opened_at": "2026-01-01T09:00:00+00:00", "closed_at": None,
         "usage": None, "cost_usd": None}]}
    (tmp_path / "run-old.json").write_text(json.dumps(legacy), encoding="utf-8")
    assert trajectory.loadSpans("run-old", root=tmp_path) == legacy


def test_torn_tail_line_skips_only_that_event(tmp_path):
    """A crash mid-append leaves a torn last line; the replay must keep every prior event."""
    rec = trajectory.Recorder("run-torn", root=tmp_path)
    sid = rec.openSpan("executor", None, {"sid": "st-1"})
    rec.closeSpan(sid, usage=None, cost_usd=0.0)
    with (tmp_path / "run-torn.jsonl").open("a", encoding="utf-8") as fh:
        fh.write('{"ev": "open", "step_id": "trunc')   # torn tail (no newline, invalid JSON)
    data = trajectory.loadSpans("run-torn", root=tmp_path)
    assert [s["step_id"] for s in data["spans"]] == [sid]
    assert data["spans"][0]["closed_at"] is not None


def test_every_method_is_exception_safe(tmp_path, monkeypatch):
    rec = trajectory.Recorder("run-e", root=tmp_path)
    sid = rec.openSpan("executor", None, {})

    def _boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(trajectory.jsonl_io, "appendRecord", _boom)
    # A write error must be swallowed -- no raise reaches the caller.
    rec.closeSpan(sid, usage=None, cost_usd=1.0)
    rec.openSpan("tool", sid, {})


# ---------------------------------------------------------------------------
# B29's temp+os.replace whole-file flush is gone: the recorder is append-only JSONL
# now (one line per open/close event under self._lock), so there is no per-flush temp
# file to race on -- concurrent-write safety is covered by the append-only test below.
# ---------------------------------------------------------------------------
def test_concurrent_flushes_leave_valid_complete_file(tmp_path):
    rec = Recorder("run-flush", root=tmp_path)

    def _worker(n):
        for i in range(15):
            sid = rec.openSpan("tool", None, {"n": n, "i": i})
            rec.closeSpan(sid, cost_usd=float(n))

    threads = [threading.Thread(target=_worker, args=(k,)) for k in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert (tmp_path / "run-flush.jsonl").exists()
    data = loadSpans("run-flush", root=tmp_path)
    assert data["run_id"] == "run-flush"
    assert len(data["spans"]) == 8 * 15               # no concurrent append silently dropped a span
    assert not list(tmp_path.glob("*.tmp"))           # append-only: no temp files at all

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
        self.meta: dict = {}          # _runOneAttempt reads meta (e.g. work_profile)
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
    # R12: a production install .env may enable the Epic 4 semantic-safety layer; this
    # test's fake host has no _authorizeAttempt and only exercises span thread-locality.
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
