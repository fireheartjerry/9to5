"""addSubtask carries the additive planner fork_eligible hint (default-safe)."""
from state.task import TaskState


def test_fork_eligible_defaults_false():
    state = TaskState.create("goal", 1.0)
    st = state.addSubtask("title", "desc")
    assert st["fork_eligible"] is False


def test_fork_eligible_opt_in():
    state = TaskState.create("goal", 1.0)
    st = state.addSubtask("title", "desc", fork_eligible=True)
    assert st["fork_eligible"] is True
