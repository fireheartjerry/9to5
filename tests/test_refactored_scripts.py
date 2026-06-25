"""Tests for the refactored orchestration pipeline.

Verifies that the orchestration scripts expose finer-grained, named, testable
steps via ``agents.orchestration_pipeline``.  Pure-stdlib -- no Ollama, Discord,
or live subprocess required; runs cleanly with ``python tests/test_refactored_scripts.py``.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# Ensure the repo root is importable when the test is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.orchestration_pipeline import (
    PIPELINE_STEPS,
    STEP_NAMES,
    PipelineStep,
    StepResult,
    executionOrder,
    fmtElapsed,
    runSteps,
    sanitizeSpec,
    singleDeliverable,
    stepFor,
    validateSpec,
    verifyStep,
)


# ---------------------------------------------------------------------------
# StepResult contract
# ---------------------------------------------------------------------------

class TestStepResult(unittest.TestCase):
    def test_ok_unwrap_returns_payload(self):
        sr = StepResult(step="x", ok=True, payload={"k": 1})
        self.assertEqual(sr.unwrap(), {"k": 1})

    def test_failed_unwrap_raises(self):
        sr = StepResult(step="x", ok=False, error="boom")
        with self.assertRaises(RuntimeError) as ctx:
            sr.unwrap()
        self.assertIn("boom", str(ctx.exception))

    def test_ok_no_error(self):
        sr = StepResult(step="y", ok=True)
        self.assertIsNone(sr.error)


# ---------------------------------------------------------------------------
# Pipeline registry
# ---------------------------------------------------------------------------

class TestPipelineRegistry(unittest.TestCase):
    def test_all_expected_steps_present(self):
        expected = {
            "elaborate", "architect", "plan", "critique",
            "gate_plan", "spec", "execute", "verify",
            "review", "replan", "gate_pr", "complete",
        }
        self.assertTrue(expected.issubset(STEP_NAMES),
                        f"missing steps: {expected - STEP_NAMES}")

    def test_step_names_frozenset_matches_pipeline_steps(self):
        self.assertEqual(STEP_NAMES, frozenset(s.name for s in PIPELINE_STEPS))

    def test_step_for_returns_correct_step(self):
        s = stepFor("verify")
        self.assertIsInstance(s, PipelineStep)
        self.assertEqual(s.name, "verify")

    def test_step_for_raises_on_unknown(self):
        with self.assertRaises(KeyError):
            stepFor("nonexistent_step_xyz")

    def test_plan_depends_on_elaborate_and_architect(self):
        s = stepFor("plan")
        self.assertIn("elaborate", s.depends_on)
        self.assertIn("architect", s.depends_on)

    def test_complete_is_last_step(self):
        self.assertEqual(PIPELINE_STEPS[-1].name, "complete")


# ---------------------------------------------------------------------------
# executionOrder -- topological sort
# ---------------------------------------------------------------------------

class TestExecutionOrder(unittest.TestCase):
    def test_order_has_all_steps(self):
        order = executionOrder()
        self.assertEqual(sorted(order), sorted(STEP_NAMES))

    def test_elaborate_before_plan(self):
        order = executionOrder()
        self.assertLess(order.index("elaborate"), order.index("plan"))

    def test_plan_before_verify(self):
        order = executionOrder()
        self.assertLess(order.index("plan"), order.index("verify"))

    def test_verify_before_review(self):
        order = executionOrder()
        self.assertLess(order.index("verify"), order.index("review"))

    def test_cycle_raises(self):
        # Manually construct a two-step cycle.
        cycled = [
            PipelineStep("alpha", "alpha", depends_on=("beta",)),
            PipelineStep("beta",  "beta",  depends_on=("alpha",)),
        ]
        with self.assertRaises(RuntimeError):
            executionOrder(cycled)

    def test_subset_order_respects_deps(self):
        subset = [stepFor("elaborate"), stepFor("plan")]
        order = executionOrder(subset)
        self.assertLess(order.index("elaborate"), order.index("plan"))


# ---------------------------------------------------------------------------
# sanitizeSpec -- pure coercion step
# ---------------------------------------------------------------------------

_SKILLS = frozenset({"skill_a", "skill_b"})
_AGENTS = frozenset({"architect"})
_PRE = frozenset({"block_destructive"})
_POST = frozenset({"write_obsidian"})


class TestSanitizeSpec(unittest.TestCase):
    def _run(self, spec, subtask=None):
        return sanitizeSpec(
            spec, subtask or {},
            available_skills=_SKILLS,
            available_subagents=_AGENTS,
            available_pre_hooks=_PRE,
            available_post_hooks=_POST,
        )

    def test_returns_step_result_ok(self):
        res = self._run({"prompt": "do stuff", "effort_level": "high"})
        self.assertTrue(res.ok)
        self.assertEqual(res.step, "sanitize_spec")

    def test_coerces_invalid_effort_to_default(self):
        res = self._run({"prompt": "x", "effort_level": "turbo_max_9000"})
        self.assertEqual(res.payload["effort_level"], "default")

    def test_preserves_valid_effort(self):
        for eff in ("low", "default", "medium", "high", "xhigh", "ultracode"):
            res = self._run({"prompt": "x", "effort_level": eff})
            self.assertEqual(res.payload["effort_level"], eff)

    def test_filters_unknown_skills(self):
        res = self._run({"prompt": "x", "skills_to_invoke": ["skill_a", "unknown_one"]})
        self.assertEqual(res.payload["skills_to_invoke"], ["skill_a"])

    def test_filters_unknown_subagent(self):
        res = self._run({"prompt": "x", "subagent": "hacker"})
        self.assertIsNone(res.payload["subagent"])

    def test_allows_known_subagent(self):
        res = self._run({"prompt": "x", "subagent": "architect"})
        self.assertEqual(res.payload["subagent"], "architect")

    def test_filters_unknown_hooks(self):
        res = self._run({"prompt": "x",
                         "pre_tool_hooks": ["block_destructive", "rm_rf"],
                         "post_tool_hooks": ["write_obsidian", "exfiltrate"]})
        self.assertEqual(res.payload["pre_tool_hooks"], ["block_destructive"])
        self.assertEqual(res.payload["post_tool_hooks"], ["write_obsidian"])

    def test_fallback_prompt_from_subtask(self):
        res = self._run({}, subtask={"description": "build it"})
        self.assertEqual(res.payload["prompt"], "build it")

    def test_fallback_prompt_from_title(self):
        res = self._run({}, subtask={"title": "the title"})
        self.assertEqual(res.payload["prompt"], "the title")

    def test_non_dict_spec_produces_defaults(self):
        res = self._run(None, subtask={"description": "do something"})
        self.assertTrue(res.ok)
        self.assertEqual(res.payload["effort_level"], "default")
        self.assertEqual(res.payload["prompt"], "do something")

    def test_workflow_disabled_when_no_phases(self):
        res = self._run({"prompt": "x", "use_workflow": True,
                         "workflow_definition": {"name": "wf"}})  # no phases key
        self.assertFalse(res.payload["use_workflow"])

    def test_workflow_enabled_with_valid_definition(self):
        wf = {"name": "wf", "phases": [{"title": "phase1", "agents": []}]}
        res = self._run({"prompt": "x", "use_workflow": True, "workflow_definition": wf})
        self.assertTrue(res.payload["use_workflow"])
        self.assertEqual(res.payload["workflow_definition"], wf)


# ---------------------------------------------------------------------------
# validateSpec
# ---------------------------------------------------------------------------

class TestValidateSpec(unittest.TestCase):
    def test_valid_spec_passes(self):
        res = validateSpec({"prompt": "do it", "effort_level": "high"})
        self.assertTrue(res.ok)

    def test_missing_prompt_fails(self):
        res = validateSpec({"effort_level": "high"})
        self.assertFalse(res.ok)
        self.assertIn("prompt", res.error)

    def test_bad_effort_fails(self):
        res = validateSpec({"prompt": "x", "effort_level": "turbo"})
        self.assertFalse(res.ok)
        self.assertIn("effort_level", res.error)


# ---------------------------------------------------------------------------
# fmtElapsed
# ---------------------------------------------------------------------------

class TestFmtElapsed(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(fmtElapsed(0), "0h00m00s")

    def test_one_hour(self):
        self.assertEqual(fmtElapsed(3600), "1h00m00s")

    def test_mixed(self):
        self.assertEqual(fmtElapsed(3661), "1h01m01s")

    def test_sub_minute(self):
        self.assertEqual(fmtElapsed(45), "0h00m45s")

    def test_float_truncated(self):
        self.assertEqual(fmtElapsed(59.9), "0h00m59s")


# ---------------------------------------------------------------------------
# singleDeliverable
# ---------------------------------------------------------------------------

class TestSingleDeliverable(unittest.TestCase):
    def test_plain_single_file_is_single(self):
        self.assertTrue(singleDeliverable("improve webdash.py readability"))

    def test_enumerated_multi_req_is_not_single(self):
        goal = ("improve webdash.py with (1) auto-refresh meta tag, "
                "(2) elapsed-time line, (3) per-subtask green/red coding.")
        self.assertFalse(singleDeliverable(goal))

    def test_empty_goal_is_single(self):
        self.assertTrue(singleDeliverable(""))

    def test_multi_file_phrase_is_not_single(self):
        self.assertFalse(singleDeliverable("update multiple files to improve performance"))

    def test_no_file_extension_is_single(self):
        self.assertTrue(singleDeliverable("write a fibonacci function"))


# ---------------------------------------------------------------------------
# verifyStep -- thin wrapper around verifier.runVerification
# ---------------------------------------------------------------------------

class TestVerifyStep(unittest.TestCase):
    def test_exit_zero_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "pass_me.py"
            script.write_text("print('ok')", encoding="utf-8")
            v = {"cmd": f'python "{script}"', "expect": "exit_zero"}
            res = verifyStep(v, tmp, {"ok": True, "returncode": 0})
            self.assertTrue(res.ok)
            self.assertEqual(res.step, "verify")

    def test_bad_script_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "fail_me.py"
            script.write_text("raise SystemExit(1)", encoding="utf-8")
            v = {"cmd": f'python "{script}"', "expect": "exit_zero"}
            res = verifyStep(v, tmp, {"ok": False, "returncode": 1})
            self.assertFalse(res.ok)
            self.assertIsNotNone(res.error)

    def test_no_verify_trusts_executor_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = verifyStep(None, tmp, {"ok": True, "returncode": 0})
            self.assertTrue(res.ok)

    def test_no_verify_fails_when_executor_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = verifyStep(None, tmp, {"ok": False, "returncode": 1})
            self.assertFalse(res.ok)


# ---------------------------------------------------------------------------
# runSteps -- step sequencer
# ---------------------------------------------------------------------------

class TestRunSteps(unittest.TestCase):
    def test_all_steps_run_on_success(self):
        log = []
        handlers = {
            "plan": lambda ctx: (log.append("plan"), StepResult("plan", True))[1],
            "exec": lambda ctx: (log.append("exec"), StepResult("exec", True))[1],
        }
        results = runSteps(["plan", "exec"], {}, handlers)
        self.assertEqual(log, ["plan", "exec"])
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.ok for r in results))

    def test_stops_on_first_failure(self):
        log = []
        handlers = {
            "plan": lambda ctx: (log.append("plan"), StepResult("plan", False, error="boom"))[1],
            "exec": lambda ctx: (log.append("exec"), StepResult("exec", True))[1],
        }
        results = runSteps(["plan", "exec"], {}, handlers)
        self.assertEqual(log, ["plan"])
        self.assertFalse(results[0].ok)
        self.assertEqual(len(results), 1)

    def test_missing_handler_is_skipped(self):
        results = runSteps(["elaborate", "plan"], {}, {"plan": lambda ctx: StepResult("plan", True)})
        self.assertEqual(len(results), 2)
        self.assertTrue(results[0].payload.get("skipped"))
        self.assertTrue(results[1].ok)

    def test_context_is_shared_across_steps(self):
        ctx: dict = {}
        handlers = {
            "step_a": lambda c: (c.update({"from_a": 1}), StepResult("step_a", True))[1],
            "step_b": lambda c: StepResult("step_b", True, payload={"saw": c.get("from_a")}),
        }
        results = runSteps(["step_a", "step_b"], ctx, handlers)
        self.assertEqual(results[1].payload["saw"], 1)

    def test_empty_steps_returns_empty_list(self):
        self.assertEqual(runSteps([], {}, {}), [])


if __name__ == "__main__":
    unittest.main()
