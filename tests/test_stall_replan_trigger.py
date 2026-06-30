"""A stalling progress-ledger sequence triggers EXACTLY one root-cause replan at STALL_THRESHOLD."""
import tempfile
from pathlib import Path
from unittest import mock

import config
from orchestrator import Orchestrator
from platform_core.orchestration import dual_ledger_planner as dlp
from state.task import TaskState


def test_stall_threshold_triggers_one_root_cause_replan():
    with mock.patch.object(config, "STATE_DIR", Path(tempfile.mkdtemp())), \
         mock.patch.object(config, "DUAL_LEDGER_PLANNER_ENABLED", True), \
         mock.patch.object(config, "STALL_THRESHOLD", 2):
        st = TaskState.create("g", 1.0)
        st.meta["goal_elaborated"] = "build (1) a (2) b"
        st.meta["stall_count"] = 0
        sub = st.addSubtask("a", "da")
        orch = Orchestrator()
        orch.obs = mock.Mock()
        stalling = {"is_in_loop": {"answer": True}, "is_progress_being_made": {"answer": False},
                    "is_request_satisfied": {"answer": False}, "instruction": {"answer": "retry"}}
        with mock.patch.object(dlp, "progressLedgerStep", return_value=stalling), \
             mock.patch.object(orch, "_stallReplan", return_value=True) as m_replan, \
             mock.patch.object(orch, "_singleDeliverable", return_value=False):
            # first stall: count 0 -> 1, no replan
            orch._runSieAndReplan(st, sub, {"prompt": "p"}, "out", True, "done", "arch",
                                  mock.Mock(), None, False)
            assert m_replan.call_count == 0
            # second stall: count 1 -> 2 == threshold -> exactly one replan, counter reset by _stallReplan
            orch._runSieAndReplan(st, sub, {"prompt": "p"}, "out", True, "done", "arch",
                                  mock.Mock(), None, False)
            assert m_replan.call_count == 1
