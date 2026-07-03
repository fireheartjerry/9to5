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


def test_unverified_subtask_skips_evidence_gate(monkeypatch):
    """unverified=True (no verify cmd) must skip the evidence gate entirely — exit-zero fallback
    is not a code-change subtask and gitDiffFacts sees pre-existing dirty files on branches with
    in-progress work, producing a false has_code_change=True that triggers a spurious HARD-FAIL.
    INDEPENDENT_VERIFY_ENABLED is forced True so the test exercises the actual unverified guard
    rather than passing vacuously because the gate is off by default (ship-dark)."""
    from platform_core.orchestration import evidence_gate
    # Force the gate ON so we actually test `not vresult.get("unverified")` — without this,
    # INDEPENDENT_VERIFY_ENABLED=False (ship-dark default) makes the condition short-circuit
    # before reaching the unverified guard, and riv/gdf assertions pass vacuously.
    monkeypatch.setattr(config, "INDEPENDENT_VERIFY_ENABLED", True, raising=False)
    orch, st, p = _orch_state(self_ref=True)
    try:
        sub = st.getSubtask("st-001")
        with mock.patch.object(iv, "runIndependentVerification") as riv, \
             mock.patch.object(orch, "_gitDiffFacts",
                               return_value={"base_sha": "b", "head_sha": "h",
                                             "diff_text": "M foo.py", "files_changed": 5}) as gdf, \
             mock.patch.object(orch, "_selfRefQualityGate", return_value=(True, "")), \
             mock.patch.object(orch, "_repairVerify", return_value=None), \
             mock.patch.object(orch, "_resolveClarifications", return_value=None):
            # verify_spec=None → runVerification produces exit-zero result → unverified=True set
            # internally; runAttemptVerify must then skip runEvidenceGate entirely.
            vres, passed, *_ = evidence_gate.runAttemptVerify(
                orch, st, sub, {"ok": True, "stdout": ""}, str(config.PROJECT_ROOT),
                None, 0.0, "st-001", "", mock.Mock(), None)
        assert passed is True, "unverified subtask must not be hard-failed by evidence gate"
        riv.assert_not_called()  # independent verifier must not spawn for exit-zero fallbacks
        gdf.assert_not_called()  # git inspection must not run for exit-zero fallbacks
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


def test_repaired_verify_is_sanitized_before_use():
    """BUG-009: _repairVerify()'s output must be routed through sanitizeVerify() same as every
    planner-authored verify -- a repaired verify carrying shell-chaining metacharacters must be
    dropped, not executed."""
    from platform_core.orchestration import evidence_gate
    orch, st, p = _orch_state(self_ref=False)
    try:
        sub = st.getSubtask("st-001")
        unsafe = {"cmd": "python a.py; rm -rf /tmp/x", "expect": "exit_zero"}
        with mock.patch.object(orch, "_repairVerify", return_value=unsafe):
            vres, passed, *_ = evidence_gate.runAttemptVerify(
                orch, st, sub, {"ok": True, "stdout": ""}, str(config.PROJECT_ROOT),
                None, 0.0, "st-001", "", mock.Mock(), None)
        # sanitizeVerify drops the unsafe cmd entirely -> falls back to the exit-zero envelope
        # check (unverified=True), NEVER the raw shell-chained command.
        assert vres.get("cmd") != unsafe["cmd"]
    finally:
        p.stop()
