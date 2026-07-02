"""Cascade reset removes only PENDING dependents of a replaced/removed subtask (freeze done prefix)."""
import tempfile
from pathlib import Path
from unittest import mock

import config
from orchestrator import Orchestrator
from state.task import TaskState


def _setup():
    d = Path(tempfile.mkdtemp())
    p = mock.patch.object(config, "STATE_DIR", d)
    p.start()
    st = TaskState.create("g", 1.0)
    a = st.addSubtask("a", "da")                              # st-001
    b = st.addSubtask("b", "db", depends_on=[a["subtask_id"]])  # st-002 pending dependent
    c = st.addSubtask("c", "dc", depends_on=[b["subtask_id"]])  # st-003 transitive dependent
    orch = Orchestrator()
    orch.obs = mock.Mock()
    return orch, st, p


def test_cascade_resets_pending_dependents_transitively():
    orch, st, p = _setup()
    try:
        orch._cascadeResetDependents(st, ["st-001"])
        assert st.getSubtask("st-002")["status"] == "removed"
        assert st.getSubtask("st-003")["status"] == "removed"
    finally:
        p.stop()


def test_cascade_freezes_done_dependents():
    orch, st, p = _setup()
    try:
        st.updateSubtask("st-002", status="done")   # executed prefix -> frozen
        orch._cascadeResetDependents(st, ["st-001"])
        assert st.getSubtask("st-002")["status"] == "done"     # not reset
        assert st.getSubtask("st-003")["status"] == "removed"  # still-pending dependent reset
    finally:
        p.stop()
