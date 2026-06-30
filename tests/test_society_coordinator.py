# tests/test_society_coordinator.py
"""Coordinator: facts post, disjoint batch seam, parallel spawn, collect, contest detect."""
import threading

from society.blackboard import Blackboard
from society.coordinator import Coordinator
from state.task import TaskState


def _state_two_ready():
    st = TaskState.create("multi goal", 1.0)
    st.addSubtask("Implement a.py", "edit a.py")
    st.addSubtask("Write tests for a", "pytest a")
    return st


def test_post_facts_writes_facts_entry(tmp_path):
    state = _state_two_ready()
    bb = Blackboard(tmp_path / "c.jsonl")
    coord = Coordinator(state, bb, threading.Lock(), work_dir=str(tmp_path))
    coord.postFacts({"given": ["x"], "plan": ["do x"]})
    rows = bb.readAll()
    assert rows[-1]["kind"] == "facts" and rows[-1]["to"] == "all"


def test_select_disjoint_batch_deps_only_seam(tmp_path):
    state = _state_two_ready()
    bb = Blackboard(tmp_path / "c.jsonl")
    coord = Coordinator(state, bb, threading.Lock(), work_dir=str(tmp_path))
    ready = [s for s in state.subtasks if s["status"] == "pending"]
    batch = coord.selectDisjointBatch(ready, max_workers=3, file_sets_fn=None)
    assert len(batch) == 2  # deps-only fallback returns the whole ready set (capped)


def test_select_disjoint_batch_filters_overlap(tmp_path):
    state = _state_two_ready()
    bb = Blackboard(tmp_path / "c.jsonl")
    coord = Coordinator(state, bb, threading.Lock(), work_dir=str(tmp_path))
    ready = [s for s in state.subtasks if s["status"] == "pending"]
    # both subtasks touch a.py -> only the first is schedulable disjointly
    batch = coord.selectDisjointBatch(ready, max_workers=3,
                                      file_sets_fn=lambda st: {"a.py"})
    assert len(batch) == 1


def test_handle_society_batch_runs_workers_and_collects(tmp_path):
    state = _state_two_ready()
    bb = Blackboard(tmp_path / "c.jsonl")
    coord = Coordinator(state, bb, threading.Lock(), work_dir=str(tmp_path))
    ran = []

    def fake_run(spec, **kw):
        ran.append(kw["subtask"]["subtask_id"])
        return {"ok": True, "returncode": 0, "stdout": "ok"}

    ready = [s for s in state.subtasks if s["status"] == "pending"]
    msgs = coord._handleSocietyBatch(ready, parallelism=2, run_fn=fake_run)
    assert len(ran) == 2 and all(m["ok"] for m in msgs)
    assert {s["status"] for s in state.subtasks} == {"in_progress"}  # claimed; verifier lands later


def test_detect_contested_flags_failed_result(tmp_path):
    state = _state_two_ready()
    bb = Blackboard(tmp_path / "c.jsonl")
    coord = Coordinator(state, bb, threading.Lock(), work_dir=str(tmp_path))
    msgs = [{"role": "coder", "subtask_id": "st-001", "ok": True},
            {"role": "reviewer", "subtask_id": "st-001", "ok": False}]
    assert coord.detectContested(msgs) == ["st-001"]


def test_worker_crash_contained(tmp_path):
    state = _state_two_ready()
    bb = Blackboard(tmp_path / "c.jsonl")
    coord = Coordinator(state, bb, threading.Lock(), work_dir=str(tmp_path))

    def boom(spec, **kw):
        if kw["subtask"]["subtask_id"] == "st-001":
            raise RuntimeError("worker exploded")
        return {"ok": True, "returncode": 0}

    ready = [s for s in state.subtasks if s["status"] == "pending"]
    msgs = coord._handleSocietyBatch(ready, parallelism=2, run_fn=boom)
    statuses = {s["subtask_id"]: s["status"] for s in state.subtasks}
    assert statuses["st-001"] == "failed"          # crashed -> failed, peers unaffected
    assert any(m["ok"] for m in msgs)              # the other worker still completed


from notifications.event_bus import LiveEventBus
from society.blackboard import Blackboard as _BB
from society.coordinator import Coordinator as _Coord


def test_blackboard_appends_mirror_to_event_bus(tmp_path):
    bus = LiveEventBus()
    state = _state_two_ready()
    bb = _BB(tmp_path / "m.jsonl")
    coord = _Coord(state, bb, __import__("threading").Lock(),
                   work_dir=str(tmp_path), bus=bus)
    coord.attachBus()                     # wires bus mirror as blackboard.on_append
    coord.postFacts({"plan": ["x"]})
    events = bus.history(last_n=10)
    assert any(e["kind"] == "society" for e in events)
    assert events[-1]["data"]["kind"] == "facts"
