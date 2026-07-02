"""dependentsOf returns the subtasks that depend on a given id (for cascade reset)."""
import tempfile
from pathlib import Path
from unittest import mock

import config
from state.task import TaskState


def test_dependents_of():
    with mock.patch.object(config, "STATE_DIR", Path(tempfile.mkdtemp())):
        st = TaskState.create("g", 1.0)
        a = st.addSubtask("a", "da")               # st-001
        st.addSubtask("b", "db", depends_on=[a["subtask_id"]])  # st-002 depends on st-001
        st.addSubtask("c", "dc")                   # st-003 independent
        deps = st.dependentsOf(a["subtask_id"])
        assert [d["subtask_id"] for d in deps] == ["st-002"]
        assert st.dependentsOf("st-003") == []
