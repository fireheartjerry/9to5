# tests/test_society_off_invariance.py
"""SOCIETY_ENABLED=False: the gate is closed and routing is unchanged (star/parallel path)."""
import config
from platform_core.orchestration.run_loop_mixin import OrchestratorRunLoopMixin


class _Stub(OrchestratorRunLoopMixin):
    pass


def test_gate_closed_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "SOCIETY_ENABLED", False)
    s = _Stub()
    # even with 2 disjoint ready subtasks, the gate stays closed when the flag is off
    assert s._societyGate([{"subtask_id": "st-1"}, {"subtask_id": "st-2"}]) is False


def test_gate_needs_two_ready(monkeypatch):
    monkeypatch.setattr(config, "SOCIETY_ENABLED", True)
    s = _Stub()
    assert s._societyGate([{"subtask_id": "st-1"}]) is False        # <2 ready -> star path
    assert s._societyGate([{"subtask_id": "st-1"},
                           {"subtask_id": "st-2"}]) is True


def test_handle_society_batch_delegates_to_coordinator(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SOCIETY_ENABLED", True)
    from state.task import TaskState
    state = TaskState.create("multi", 1.0)
    state.addSubtask("Implement a", "edit a.py")
    state.addSubtask("Test a", "pytest a")
    s = _Stub()
    s._state_lock = __import__("threading").Lock()
    s._parallelism = 2
    s._work_dir = str(tmp_path)
    ran = []

    monkeypatch.setattr("society.worker._defaultRunFn",
                        lambda spec, **kw: ran.append(kw["subtask"]["subtask_id"]) or
                        {"ok": True, "returncode": 0})
    ready = [s2 for s2 in state.subtasks if s2["status"] == "pending"]
    s._handleSocietyBatch(state, ready, str(tmp_path), parallelism=2)
    assert len(ran) == 2


from platform_core.orchestration.review_mixin import OrchestratorReviewMixin


class _RStub(OrchestratorReviewMixin):
    pass


def test_remediation_unsafe_sequential_is_safe():
    s = _RStub()
    s._parallelism = 1
    # Co-design with Epic 1: a sequential run has no peers, so a remediation
    # snapshot/whole-tree-revert is always safe. UNCHANGED by Epic 5.
    assert s._remediationUnsafe("") is False


def test_remediation_unsafe_shared_tree_under_parallelism():
    s = _RStub()
    s._parallelism = 3
    # Until per-worker worktrees isolate each society worker, a parallel run shares the
    # tree, so a whole-tree remediation revert would clobber peers -> unsafe. UNCHANGED.
    assert s._remediationUnsafe("") is True
