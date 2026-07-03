"""CompletionEnvelope parser: absent => fall-back, malformed => correction, valid => parsed.

Also covers: when INDEPENDENT_VERIFY_ENABLED, the executor prompt carries the
CompletionEnvelope instruction (agents.completion_envelope end-to-end wiring)."""
import tempfile
from pathlib import Path
from unittest import mock

import config
from agents import completion_envelope as ce
from orchestrator import Orchestrator
from state.task import TaskState


_VALID = '''Done. Summary follows.
```json
{"diff_summary": "added foo", "files_changed": ["foo.py"],
 "test_results": [{"command": "pytest", "exit_code": 0, "summary": "1 passed"}],
 "acceptance_criteria_status": [{"criterion": "foo works", "met": true, "evidence": "pytest green"}],
 "residual_risks": []}
```'''


def test_absent_envelope_falls_back():
    parse = ce.parseCompletionEnvelope("just some narration, no fenced json")
    assert parse.present is False
    assert parse.envelope is None


def test_valid_envelope_parsed():
    parse = ce.parseCompletionEnvelope(_VALID)
    assert parse.present and not parse.malformed
    env = parse.envelope
    assert env.files_changed == ["foo.py"]
    assert env.test_results[0]["exit_code"] == 0
    assert env.acceptance_criteria_status[0]["met"] is True


def test_malformed_envelope_flagged():
    bad = "```json\n{\"diff_summary\": \"x\"\n```"  # missing required keys + broken
    parse = ce.parseCompletionEnvelope(bad)
    assert parse.present and parse.malformed
    assert parse.error


def test_last_fenced_block_wins():
    text = "```json\n{\"old\": 1}\n```\nthen\n" + _VALID
    parse = ce.parseCompletionEnvelope(text)
    assert parse.envelope is not None and parse.envelope.files_changed == ["foo.py"]


def test_envelope_correction_mentions_error():
    msg = ce.envelopeCorrection("missing key: files_changed")
    assert "files_changed" in msg and "json" in msg.lower()


# ---------------------------------------------------------------------------
# Instruction wiring: "When INDEPENDENT_VERIFY_ENABLED, the executor prompt
# carries the CompletionEnvelope instruction."
# ---------------------------------------------------------------------------

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
