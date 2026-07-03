# tests/test_society_coordinator.py
"""Coordinator: disjoint batch seam, parallel spawn, collect, budget gate, bus mirror."""
import threading

from society.blackboard import Blackboard, makeEntry
from society.coordinator import Coordinator, busMirror
from state.task import TaskState


def _state_two_ready():
    st = TaskState.create("multi goal", 1.0)
    st.addSubtask("Implement a.py", "edit a.py")
    st.addSubtask("Write tests for a", "pytest a")
    return st


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
    # WorkerAgent._landStatus lands a terminal status itself (claim -> execute -> single-shot
    # verify -> land) so the run loop never livelocks on a subtask stuck 'in_progress' -- there
    # is no separate deferred-verifier stage (see test_society_worker.py's own "done" assertion).
    assert {s["status"] for s in state.subtasks} == {"done"}


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


def test_blackboard_appends_mirror_to_event_bus(tmp_path):
    """on_append travels through the Blackboard constructor (forTask seam), not attachBus."""
    bus = LiveEventBus()
    bb = Blackboard.forTask("task-mirror", base_dir=tmp_path,
                            on_append=busMirror("task-mirror", bus=bus))
    bb.append(makeEntry(kind="facts", author="coordinator", to="all",
                        value={"plan": ["x"]}))
    events = bus.history(last_n=10)
    assert any(e["kind"] == "society" for e in events)
    assert events[-1]["data"]["kind"] == "facts"
    assert events[-1]["sid"] == "task-mirror"


def test_budget_governor_accumulates_spend(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "SOCIETY_TOKEN_BUDGET_USD", 0.05)
    state = _state_two_ready()
    bb = Blackboard(tmp_path / "g.jsonl")
    coord = Coordinator(state, bb, threading.Lock(), work_dir=str(tmp_path))

    def fake_run(spec, **kw):
        return {"ok": True, "returncode": 0, "cost_usd": 0.04}

    ready = [s for s in state.subtasks if s["status"] == "pending"]
    coord._handleSocietyBatch(ready, parallelism=2, run_fn=fake_run)
    # two workers each cost 0.04 -> 0.08 > 0.05 budget
    assert coord.spent_usd >= 0.05
    assert coord.budgetExceeded() is True


def test_budget_gate_refuses_spawn_and_posts_budget_entry(tmp_path, monkeypatch):
    """HARD pre-spawn gate: at/over budget -> no worker spawns, one `budget` entry."""
    import config
    monkeypatch.setattr(config, "SOCIETY_TOKEN_BUDGET_USD", 0.05)
    state = _state_two_ready()
    bb = Blackboard(tmp_path / "g.jsonl")
    coord = Coordinator(state, bb, threading.Lock(), work_dir=str(tmp_path))
    coord.spent_usd = 0.05          # already at the budget line
    ran = []

    def fake_run(spec, **kw):
        ran.append(kw["subtask"]["subtask_id"])
        return {"ok": True, "returncode": 0}

    ready = [s for s in state.subtasks if s["status"] == "pending"]
    msgs = coord._handleSocietyBatch(ready, parallelism=2, run_fn=fake_run)
    assert ran == [] and msgs == []                       # nothing spawned
    assert {s["status"] for s in state.subtasks} == {"pending"}   # nothing claimed
    rows = bb.readAll()
    assert len(rows) == 1 and rows[0]["kind"] == "budget"
    assert sorted(rows[0]["value"]["skipped"]) == sorted(s["subtask_id"] for s in ready)
    assert rows[0]["value"]["budget_usd"] == 0.05


def test_handle_society_batch_seeds_prior_spend_run_wide(tmp_path, monkeypatch):
    """society_batch seeds spent_usd from earlier result entries -> gate trips run-wide."""
    import config
    from society import society_batch
    monkeypatch.setattr(config, "SOCIETY_TOKEN_BUDGET_USD", 0.05)
    monkeypatch.setattr("platform_core.app_config.paths.BLACKBOARD_DIR", tmp_path)
    state = _state_two_ready()
    # A previous batch already posted a result costing 0.06 (> 0.05 budget).
    bb = Blackboard.forTask(state.task_id, base_dir=tmp_path)
    bb.append(makeEntry(kind="result", author="coder", to="coordinator",
                        subtask_id="st-000",
                        value={"kind": "result", "ok": True,
                               "value": {"cost_usd": 0.06}}))
    ran = []

    def fake_run(spec, **kw):
        ran.append(kw["subtask"]["subtask_id"])
        return {"ok": True, "returncode": 0}

    ready = [s for s in state.subtasks if s["status"] == "pending"]
    started, abort = society_batch.handleSocietyBatch(
        state, ready, str(tmp_path), 2, threading.Lock(), run_fn=fake_run)
    assert ran == [] and started == 0 and abort is None
    assert any(r["kind"] == "budget" for r in bb.readAll())


def test_lost_claim_not_counted_as_loop_progress(tmp_path, monkeypatch):
    """kind='claim' (lost claim) messages never ran -> excluded from count_started."""
    from society import society_batch
    monkeypatch.setattr("platform_core.app_config.paths.BLACKBOARD_DIR", tmp_path)
    state = _state_two_ready()
    # st-001 is already claimed elsewhere -> its worker loses the CAS claim.
    state.updateSubtask("st-001", status="in_progress", claimed_by="other")
    ran = []

    def fake_run(spec, **kw):
        ran.append(kw["subtask"]["subtask_id"])
        return {"ok": True, "returncode": 0}

    ready = list(state.subtasks)   # pass both: one claimable, one lost
    started, _ = society_batch.handleSocietyBatch(
        state, ready, str(tmp_path), 2, threading.Lock(), run_fn=fake_run)
    assert ran == ["st-002"]
    assert started == 1            # the lost claim is NOT progress
