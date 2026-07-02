"""The evidence gate can only DOWNGRADE a deterministic pass, and the downgrade is MODE-DEPENDENT:
self-improvement run => HARD-FAIL; normal product run => VERIFIED_WITH_GAPS, run continues."""
import tempfile
from pathlib import Path
from unittest import mock

import config
from agents import evidence_receipt as er
from agents import independent_verifier as iv
from agents.completion_envelope import EnvelopeParse
from orchestrator import Orchestrator
from state.task import TaskState


def _orch_state(self_ref):
    d = Path(tempfile.mkdtemp())
    p = mock.patch.object(config, "STATE_DIR", d)
    p.start()
    st = TaskState.create("goal", 1.0)
    st.meta["goal_elaborated"] = "build a thing"
    st.meta["is_self_referential"] = self_ref
    st.addSubtask("t", "d")  # st-001
    orch = Orchestrator()
    orch.obs = mock.Mock()
    orch._work_dir = str(config.PROJECT_ROOT)
    orch._parallelism = 1
    return orch, st, p


def _run_gate(orch, st):
    sub = st.getSubtask("st-001")
    vres = {"passed": True, "cmd": "python a.py", "expect": "exit_zero", "returncode": 0,
            "stdout": "", "stderr": ""}
    # force a NOT_VERIFIED outcome: non-empty diff but the independent verifier returns no envelope
    with mock.patch.object(orch, "_gitDiffFacts", return_value={
            "base_sha": "b", "head_sha": "h", "diff_text": "a.py | 1 +", "files_changed": 1}), \
         mock.patch.object(iv, "runIndependentVerification",
                           return_value=EnvelopeParse(None, present=False, malformed=False)), \
         mock.patch.object(er, "_computeHeadline", return_value="NOT_VERIFIED"):
        return orch._runEvidenceGate(st, sub, {"ok": True, "stdout": ""},
                                     str(config.PROJECT_ROOT), dict(vres), "st-001")


def test_self_ref_not_verified_hard_fails():
    orch, st, p = _orch_state(self_ref=True)
    try:
        vres, passed = _run_gate(orch, st)
        assert passed is False
        assert vres["passed"] is False
        assert vres.get("evidence_headline") == "NOT_VERIFIED"
    finally:
        p.stop()


def test_product_run_not_verified_continues_with_gaps():
    orch, st, p = _orch_state(self_ref=False)
    try:
        vres, passed = _run_gate(orch, st)
        assert passed is True  # run continues
        assert vres.get("evidence_headline") == "VERIFIED_WITH_GAPS"
        assert vres.get("evidence_gap")  # loud gap note attached
    finally:
        p.stop()
