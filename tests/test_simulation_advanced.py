"""Unit tests for simulation.py — BuilderBrain, builderRunClaude, orchestrator factories.

Split from test_simulation_units.py (was 673 lines).  Core SimBrain / SimObs /
simReplan / simReview tests live in test_simulation_core.py.
"""
from __future__ import annotations

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import simulation  # noqa: F401 — ensure module is loaded
from simulation import (
    BuilderBrain,
    SimBrain,
    SimObs,
    buildBuilderOrchestrator,
    buildOrchestrator,
    builderRunClaude,
)

_OLLAMA_AVAILABLE = importlib.util.find_spec("ollama") is not None


# ---------------------------------------------------------------------------
# BuilderBrain
# ---------------------------------------------------------------------------

class TestBuilderBrainPlan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.work = str(Path(self.tmp))
        self.brain = BuilderBrain(self.work, n_subtasks=3)

    def test_plan_has_n_subtasks(self):
        plan = self.brain._plan()
        self.assertEqual(len(plan["subtasks"]), 3)

    def test_subtask_has_verify_cmd(self):
        plan = self.brain._plan()
        for st in plan["subtasks"]:
            self.assertIsNotNone(st["verify"])
            self.assertIn("cmd", st["verify"])
            self.assertIn("expect", st["verify"])
            self.assertEqual(st["verify"]["expect"], "exit_zero")

    def test_verify_cmd_references_work_dir(self):
        plan = self.brain._plan()
        for st in plan["subtasks"]:
            self.assertIn(str(Path(self.work)), st["verify"]["cmd"])

    def test_verify_cmd_references_feature_file(self):
        plan = self.brain._plan()
        cmds = [st["verify"]["cmd"] for st in plan["subtasks"]]
        self.assertTrue(any("feature_1.py" in c for c in cmds))
        self.assertTrue(any("feature_3.py" in c for c in cmds))

    def test_zero_clamped_to_one(self):
        brain = BuilderBrain("/tmp/x", n_subtasks=0)
        self.assertEqual(len(brain._plan()["subtasks"]), 1)

    def test_negative_clamped_to_one(self):
        brain = BuilderBrain("/tmp/x", n_subtasks=-3)
        self.assertEqual(len(brain._plan()["subtasks"]), 1)

    def test_work_dir_stored_as_str(self):
        brain = BuilderBrain(Path("/tmp/x"), n_subtasks=1)
        self.assertIsInstance(brain.work, str)


class TestBuilderBrainChat(unittest.TestCase):
    def setUp(self):
        self.brain = BuilderBrain("/tmp/work", n_subtasks=2)

    def _user_msg(self, text):
        return [{"role": "user", "content": text}]

    def test_invocation_spec_path(self):
        resp = self.brain.chat(messages=self._user_msg("invocation spec needed"))
        data = json.loads(resp["message"]["content"])
        self.assertIn("prompt", data)
        self.assertIn("effort_level", data)

    def test_non_spec_path_returns_plan(self):
        resp = self.brain.chat(messages=self._user_msg("plan the work"))
        data = json.loads(resp["message"]["content"])
        self.assertIn("subtasks", data)
        self.assertEqual(len(data["subtasks"]), 2)

    def test_empty_messages_returns_plan(self):
        resp = self.brain.chat(messages=[])
        data = json.loads(resp["message"]["content"])
        self.assertIn("subtasks", data)

    def test_non_dict_items_in_messages_ignored(self):
        msgs = ["not a dict", None, {"role": "user", "content": "invocation spec"}]
        resp = self.brain.chat(messages=msgs)
        data = json.loads(resp["message"]["content"])
        self.assertIn("prompt", data)

    def test_content_none_falls_back_to_plan(self):
        resp = self.brain.chat(messages=[{"role": "user", "content": None}])
        data = json.loads(resp["message"]["content"])
        self.assertIn("subtasks", data)

    def test_no_messages_returns_plan(self):
        resp = self.brain.chat()
        data = json.loads(resp["message"]["content"])
        self.assertIn("subtasks", data)


# ---------------------------------------------------------------------------
# builderRunClaude
# ---------------------------------------------------------------------------

class TestBuilderRunClaude(unittest.TestCase):
    def test_architect_path_returns_design_doc(self):
        result = builderRunClaude({}, system_prompt="architect phase")
        self.assertTrue(result["ok"])
        self.assertFalse(result["is_error"])
        self.assertIn("design", result["stdout"])

    def test_subtask_writes_file(self):
        with tempfile.TemporaryDirectory() as d:
            target = str(Path(d) / "feature_1.py")
            subtask = {
                "subtask_id": "st-001",
                "verify": {"cmd": f'python "{target}"', "expect": "exit_zero"},
            }
            result = builderRunClaude({}, subtask=subtask, work_dir=d)
            self.assertTrue(result["ok"])
            self.assertFalse(result["is_error"])
            self.assertTrue(Path(target).exists())

    def test_written_file_is_valid_python(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "feature_2.py"
            subtask = {
                "subtask_id": "st-002",
                "verify": {"cmd": f'python "{target}"', "expect": "exit_zero"},
            }
            builderRunClaude({}, subtask=subtask, work_dir=d)
            import py_compile
            py_compile.compile(str(target), doraise=True)

    def test_written_file_contains_subtask_id(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "feature_3.py"
            subtask = {
                "subtask_id": "st-003",
                "verify": {"cmd": f'python "{target}"', "expect": "exit_zero"},
            }
            builderRunClaude({}, subtask=subtask, work_dir=d)
            content = target.read_text(encoding="utf-8")
            self.assertIn("st-003", content)

    def test_no_verify_cmd_returns_ok(self):
        result = builderRunClaude({}, subtask={"subtask_id": "st-x", "verify": None})
        self.assertTrue(result["ok"])

    def test_no_subtask_returns_ok(self):
        result = builderRunClaude({}, subtask=None)
        self.assertTrue(result["ok"])

    def test_nested_dir_created_automatically(self):
        with tempfile.TemporaryDirectory() as d:
            target = str(Path(d) / "sub" / "deep" / "feature_1.py")
            subtask = {
                "subtask_id": "st-001",
                "verify": {"cmd": f'python "{target}"', "expect": "exit_zero"},
            }
            result = builderRunClaude({}, subtask=subtask, work_dir=d)
            self.assertTrue(result["ok"])
            self.assertTrue(Path(target).exists())

    def test_write_failure_returns_error_result(self):
        subtask = {
            "subtask_id": "st-fail",
            "verify": {
                "cmd": 'python "/no_such_dir_ever/\x00/feature.py"',
                "expect": "exit_zero",
            },
        }
        result = builderRunClaude({}, subtask=subtask)
        self.assertIsInstance(result, dict)
        self.assertIn("ok", result)
        self.assertIn("is_error", result)

    def test_cmd_without_quoted_python_path_returns_ok(self):
        subtask = {
            "subtask_id": "st-noop",
            "verify": {"cmd": "echo hello", "expect": "exit_zero"},
        }
        result = builderRunClaude({}, subtask=subtask)
        self.assertTrue(result["ok"])

    def test_returns_complete_envelope(self):
        result = builderRunClaude({})
        for key in ("ok", "returncode", "stdout", "is_error", "session_id"):
            self.assertIn(key, result)


# ---------------------------------------------------------------------------
# buildOrchestrator / buildBuilderOrchestrator
# ---------------------------------------------------------------------------

@unittest.skipUnless(_OLLAMA_AVAILABLE, "ollama not installed — skipping orchestrator factory tests")
class TestBuildOrchestrator(unittest.TestCase):
    def test_returns_orchestrator(self):
        from orchestrator import Orchestrator
        orch = buildOrchestrator(n_subtasks=2)
        self.assertIsInstance(orch, Orchestrator)

    def test_brain_is_sim_brain(self):
        orch = buildOrchestrator(n_subtasks=1)
        self.assertIsInstance(orch.ollama, SimBrain)

    def test_obs_is_sim_obs(self):
        orch = buildOrchestrator()
        self.assertIsInstance(orch.obs, SimObs)

    def test_brain_n_subtasks_propagated(self):
        orch = buildOrchestrator(n_subtasks=4)
        self.assertEqual(orch.ollama.n, 4)


@unittest.skipUnless(_OLLAMA_AVAILABLE, "ollama not installed — skipping orchestrator factory tests")
class TestBuildBuilderOrchestrator(unittest.TestCase):
    def test_returns_orchestrator(self):
        from orchestrator import Orchestrator
        with tempfile.TemporaryDirectory() as d:
            orch = buildBuilderOrchestrator(d, n_subtasks=2)
        self.assertIsInstance(orch, Orchestrator)

    def test_brain_is_builder_brain(self):
        with tempfile.TemporaryDirectory() as d:
            orch = buildBuilderOrchestrator(d, n_subtasks=1)
            self.assertIsInstance(orch.ollama, BuilderBrain)

    def test_obs_is_sim_obs(self):
        with tempfile.TemporaryDirectory() as d:
            orch = buildBuilderOrchestrator(d)
            self.assertIsInstance(orch.obs, SimObs)


class TestBuildOrchestratorImportError(unittest.TestCase):
    """Verifies that buildOrchestrator / buildBuilderOrchestrator raise a clear ImportError
    when the orchestrator package cannot be imported (e.g. ollama missing)."""

    def _patch_orchestrator_absent(self):
        """Context manager that hides 'orchestrator' and 'ollama' from sys.modules."""
        import contextlib

        @contextlib.contextmanager
        def _ctx():
            saved_orch = sys.modules.pop("orchestrator", None)
            saved_ollama = sys.modules.pop("ollama", None)
            sys.modules["orchestrator"] = None  # type: ignore[assignment]
            try:
                yield
            finally:
                if saved_orch is not None:
                    sys.modules["orchestrator"] = saved_orch
                else:
                    sys.modules.pop("orchestrator", None)
                if saved_ollama is not None:
                    sys.modules["ollama"] = saved_ollama
                else:
                    sys.modules.pop("ollama", None)
        return _ctx()

    def test_build_orchestrator_raises_import_error_with_message(self):
        with self._patch_orchestrator_absent():
            with self.assertRaises(ImportError) as ctx:
                buildOrchestrator()
        self.assertIn("ollama", str(ctx.exception).lower())

    def test_build_builder_orchestrator_raises_import_error_with_message(self):
        with self._patch_orchestrator_absent():
            with self.assertRaises(ImportError) as ctx:
                buildBuilderOrchestrator("/tmp/x")
        self.assertIn("ollama", str(ctx.exception).lower())


# ---------------------------------------------------------------------------
# sim_error_handling helpers (standalone module)
# ---------------------------------------------------------------------------

class TestSimErrorHandling(unittest.TestCase):
    def setUp(self):
        try:
            from sim_error_handling import safeChatExtract, safeParseJson, safeWritePath
            self.safeChatExtract = safeChatExtract
            self.safeParseJson = safeParseJson
            self.safeWritePath = safeWritePath
        except ImportError:
            self.skipTest("sim_error_handling module not present")

    def test_safeParseJson_valid(self):
        self.assertEqual(self.safeParseJson('{"a": 1}'), {"a": 1})

    def test_safeParseJson_invalid_returns_fallback(self):
        self.assertIsNone(self.safeParseJson("not json"))

    def test_safeParseJson_custom_fallback(self):
        self.assertEqual(self.safeParseJson("bad", fallback={}), {})

    def test_safeWritePath_creates_and_writes(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sub" / "out.txt"
            rv = self.safeWritePath(str(p), "hello")
            self.assertTrue(rv["ok"])
            self.assertIsNone(rv["error"])
            self.assertEqual(p.read_text(), "hello")

    def test_safeWritePath_bad_path_returns_error(self):
        rv = self.safeWritePath("/no_such_dir/\x00bad.txt", "data")
        self.assertFalse(rv["ok"])
        self.assertIsNotNone(rv["error"])

    def test_safeChatExtract_normal(self):
        msgs = [{"role": "user", "content": "hello"}]
        self.assertEqual(self.safeChatExtract(msgs), "hello")

    def test_safeChatExtract_last_wins(self):
        msgs = [
            {"role": "user", "content": "first"},
            {"role": "user", "content": "second"},
        ]
        self.assertEqual(self.safeChatExtract(msgs), "second")

    def test_safeChatExtract_empty_list_returns_empty(self):
        self.assertEqual(self.safeChatExtract([]), "")

    def test_safeChatExtract_none_returns_empty(self):
        self.assertEqual(self.safeChatExtract(None), "")

    def test_safeChatExtract_non_dict_items_skipped(self):
        msgs = ["string", None, {"role": "user", "content": "hi"}]
        self.assertEqual(self.safeChatExtract(msgs), "hi")

    def test_safeChatExtract_content_none_returns_empty(self):
        msgs = [{"role": "user", "content": None}]
        self.assertEqual(self.safeChatExtract(msgs), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
