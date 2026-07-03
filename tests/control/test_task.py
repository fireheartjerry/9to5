"""state/task.py -- TaskState: subtask graph, schema defaults, listing, and concurrent save.

Merged (consolidation pass, tests/control sprawl reduction) from:
  - test_dependents_of.py      -- dependentsOf() cascade-reset lookup
  - test_solution_fork_schema.py -- addSubtask fork_eligible planner hint
  - test_task_listrecent.py    -- TaskState.listRecent / loadSafe / iterStored
  - test_task_save_concurrent.py -- TaskState.save() unique-temp-per-writer
  - test_task_schema_hn.py     -- vestigial parked human-nature-layer meta fields
"""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import config
from state.task import TaskState


# =============================================================================
# Merged from test_dependents_of.py
# =============================================================================
"""dependentsOf returns the subtasks that depend on a given id (for cascade reset)."""


def test_dependents_of():
    with mock.patch.object(config, "STATE_DIR", Path(tempfile.mkdtemp())):
        st = TaskState.create("g", 1.0)
        a = st.addSubtask("a", "da")               # st-001
        st.addSubtask("b", "db", depends_on=[a["subtask_id"]])  # st-002 depends on st-001
        st.addSubtask("c", "dc")                   # st-003 independent
        deps = st.dependentsOf(a["subtask_id"])
        assert [d["subtask_id"] for d in deps] == ["st-002"]
        assert st.dependentsOf("st-003") == []


# =============================================================================
# Merged from test_solution_fork_schema.py
# =============================================================================
"""addSubtask carries the additive planner fork_eligible hint (default-safe)."""


def test_fork_eligible_defaults_false():
    state = TaskState.create("goal", 1.0)
    st = state.addSubtask("title", "desc")
    assert st["fork_eligible"] is False


def test_fork_eligible_opt_in():
    state = TaskState.create("goal", 1.0)
    st = state.addSubtask("title", "desc", fork_eligible=True)
    assert st["fork_eligible"] is True


# =============================================================================
# Merged from test_task_listrecent.py
# =============================================================================
"""Unit tests for TaskState.listRecent."""


class TestListRecent(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def _w(self, name, tid, status, started, subs):
        (self.dir / name).write_text(json.dumps({
            "task_id": tid,
            "meta": {"status": status, "goal_raw": "goal " + tid, "started_at": started},
            "plan": {"subtasks": subs}}), encoding="utf-8")

    def test_load_safe_returns_none_on_corrupt_or_missing(self):
        good_id = "33333333-3333-4333-8333-333333333333"
        bad_id = "44444444-4444-4444-8444-444444444444"
        missing_id = "55555555-5555-4555-8555-555555555555"
        (self.dir / f"{good_id}.json").write_text(
            json.dumps({"task_id": good_id, "meta": {}, "plan": {"subtasks": []}}), encoding="utf-8")
        (self.dir / f"{bad_id}.json").write_text("{broken", encoding="utf-8")
        with mock.patch.object(config, "STATE_DIR", self.dir):
            self.assertIsNotNone(TaskState.loadSafe(good_id))
            self.assertIsNone(TaskState.loadSafe(bad_id))
            self.assertIsNone(TaskState.loadSafe(missing_id))

    def test_load_rejects_path_traversal_task_id(self):
        # BUG-003: a non-UUID task_id (e.g. path-traversal payload) must be rejected before any
        # path is constructed under STATE_DIR, not silently resolved outside it.
        with mock.patch.object(config, "STATE_DIR", self.dir):
            with self.assertRaises(ValueError):
                TaskState.load("../../.env")

    def test_iter_stored_skips_corrupt(self):
        self._w("ok.json", "ok1", "done", "2026-06-22T08:00:00+00:00", [])
        (self.dir / "broken.json").write_text("{not json", encoding="utf-8")
        with mock.patch.object(config, "STATE_DIR", self.dir):
            ids = sorted(d.get("task_id") for _f, d in TaskState.iterStored())
        self.assertEqual(ids, ["ok1"])   # the corrupt file is silently skipped

    def test_sorted_desc_with_progress(self):
        self._w("a.json", "aaa", "done", "2026-06-22T08:00:00+00:00", [{"status": "done"}])
        self._w("b.json", "bbb", "executing", "2026-06-22T10:00:00+00:00",
                 [{"status": "done"}, {"status": "pending"}])
        with mock.patch.object(config, "STATE_DIR", self.dir):
            rec = TaskState.listRecent(5)
        self.assertEqual(len(rec), 2)
        self.assertEqual(rec[0]["task_id"], "bbb")          # most recent first
        self.assertEqual((rec[0]["done"], rec[0]["total"]), (1, 2))
        self.assertEqual(rec[0]["status"], "executing")

    def test_limit(self):
        for i in range(5):
            self._w(f"{i}.json", f"t{i}", "done", f"2026-06-22T0{i}:00:00+00:00", [])
        with mock.patch.object(config, "STATE_DIR", self.dir):
            self.assertEqual(len(TaskState.listRecent(3)), 3)


# =============================================================================
# Merged from test_task_save_concurrent.py
# =============================================================================
"""TaskState.save() must use a unique temp per writer so two processes/threads saving the same
task never collide on a shared '<id>.json.tmp' (the second os.replace would hit FileNotFoundError
after the first moved it). The final file must always be complete, valid JSON."""


class TestConcurrentSave(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self._p = mock.patch.object(config, "STATE_DIR", self.dir)
        self._p.start()

    def tearDown(self):
        self._p.stop()

    def test_many_threads_saving_same_task_never_clobber(self):
        from state.task import TaskState
        ts = TaskState.create("concurrent save goal", 1.0)
        errors: list[Exception] = []

        def worker() -> None:
            try:
                for _ in range(60):
                    ts.save()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

        self.assertEqual(errors, [], f"concurrent saves raised: {errors[:2]}")
        # final file is complete + valid, and no stray temp files linger
        self.assertIsInstance(json.loads(ts.path().read_text(encoding="utf-8")), dict)
        self.assertEqual(list(self.dir.glob("*.tmp")), [], "left a temp file behind")


# =============================================================================
# Merged from test_task_schema_hn.py
# =============================================================================
def test_create_has_parked_layer_meta_fields():
    """Vestigial meta keys kept for the parked human-nature layer (code at a7b1b2d)."""
    ts = TaskState.create("ship the thing", 1.0)
    meta = ts.data["meta"]
    for key in ("self_state", "autonomy", "charter_version"):
        assert key in meta
        assert meta[key] is None
