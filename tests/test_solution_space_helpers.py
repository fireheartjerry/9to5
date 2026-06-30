"""Branch clones isolate writes: a branch's recordVerify never touches canonical state."""
from state.task import TaskState
from platform_core.orchestration import solution_space as ss
from platform_core.orchestration import fork_policy as fp


def test_branch_state_is_isolated_clone():
    state = TaskState.create("goal", 1.0)
    state.addSubtask("title", "desc")
    clone = ss.forkBranchState(state, "b0")
    assert clone.task_id != state.task_id          # different file -> save() can't clobber canonical
    assert "b0" in clone.task_id
    # Mutating the clone leaves the canonical state untouched.
    clone.updateSubtask(clone.subtasks[0]["subtask_id"], status="in_progress")
    assert state.subtasks[0]["status"] == "pending"


def test_branch_subtask_folds_seed():
    seed = fp.forkPlan({"subtask_id": "st-001"}, n=1).branch_seeds[0]
    base = {"subtask_id": "st-001", "title": "t", "description": "do it", "effort_level": "default"}
    branch_st = ss.forkBranchSubtask(base, seed)
    assert branch_st is not base                    # copy, not alias
    assert branch_st["effort_level"] == seed.effort_level
    assert seed.angle_hint in branch_st["description"]
    assert base["description"] == "do it"           # original untouched
