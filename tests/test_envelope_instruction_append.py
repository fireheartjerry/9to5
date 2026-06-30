"""When INDEPENDENT_VERIFY_ENABLED, the executor prompt carries the CompletionEnvelope instruction."""
import tempfile
from pathlib import Path
from unittest import mock

import config
from agents import completion_envelope as ce
from orchestrator import Orchestrator
from state.task import TaskState


def _spec_with_flag(flag):
    d = Path(tempfile.mkdtemp())
    with mock.patch.object(config, "STATE_DIR", d), \
         mock.patch.object(config, "INDEPENDENT_VERIFY_ENABLED", flag), \
         mock.patch.object(config, "SIE_REFLECTION_ENABLED", False):
        st = TaskState.create("goal", 1.0)
        st.meta["goal_elaborated"] = "build a thing"
        orch = Orchestrator()
        # brain returns a minimal valid spec with a prompt
        orch._ollamaChat = mock.Mock(return_value={"message": {"content":
            '{"prompt": "do the work", "claude_md_inject": "", "effort_level": "high"}'}})
        sub = {"subtask_id": "st-001", "title": "t", "description": "d", "verify": {}}
        return orch.authorInvocationSpec(st, sub, "arch")


def test_instruction_appended_when_enabled():
    spec = _spec_with_flag(True)
    assert ce.COMPLETION_ENVELOPE_INSTRUCTION.strip()[:20] in spec["prompt"]


def test_instruction_absent_when_disabled():
    spec = _spec_with_flag(False)
    assert "CompletionEnvelope" not in spec["prompt"]
