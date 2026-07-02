"""When DUAL_LEDGER_PLANNER_ENABLED, authorSubtaskPlan delegates to the dual-ledger planner and yields
real depends_on; when OFF, the legacy one-shot path is unchanged. critiqueSubtaskPlan applies the
deterministic shape-check with one corrective re-prompt."""
import tempfile
from pathlib import Path
from unittest import mock

import config
from orchestrator import Orchestrator
from platform_core.orchestration import dual_ledger_planner as dlp
from platform_core.orchestration import task_ledger as tl


def test_dual_ledger_on_produces_depends_on():
    with mock.patch.object(config, "STATE_DIR", Path(tempfile.mkdtemp())), \
         mock.patch.object(config, "DUAL_LEDGER_PLANNER_ENABLED", True):
        orch = Orchestrator()
        led = tl.TaskLedger(plan=["build module", "wire it up"])
        with mock.patch.object(dlp, "authorTaskLedger", return_value=led):
            subs = orch.authorSubtaskPlan("build X (1) a (2) b", "arch")
        # second bullet depends on the first (index form survives until materialize)
        assert len(subs) == 2 and subs[1]["depends_on"] == [0]


def test_dual_ledger_off_uses_legacy_path():
    with mock.patch.object(config, "STATE_DIR", Path(tempfile.mkdtemp())), \
         mock.patch.object(config, "DUAL_LEDGER_PLANNER_ENABLED", False):
        orch = Orchestrator()
        orch._ollamaChat = mock.Mock(return_value={"message": {"content":
            '{"subtasks": [{"title": "a", "description": "d", "verify": {"cmd": "python a.py", "expect": "exit_zero"}}]}'}})
        subs = orch.authorSubtaskPlan("trivial goal", "arch")
        assert subs and subs[0]["title"] == "a"
