"""Unit tests for simulation.py — the dry-run doubles.

Covers every public function/class in simulation.py at the unit level.
The integration-level tests (full runFull) live in test_dry_run.py and
test_builder_sim.py; this file focuses on the individual seams.
"""
from __future__ import annotations

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import simulation
from simulation import (
    BuilderBrain,
    SimBrain,
    SimObs,
    buildBuilderOrchestrator,
    buildOrchestrator,
    builderRunClaude,
    simReplan,
    simReview,
    simRunClaude,
)

_OLLAMA_AVAILABLE = importlib.util.find_spec("ollama") is not None


# ---------------------------------------------------------------------------
# SimBrain._plan
# ---------------------------------------------------------------------------

class TestSimBrainPlan(unittest.TestCase):
    def test_default_three_subtasks(self):
        brain = SimBrain()
        plan = brain._plan()
        self.assertEqual(len(plan["subtasks"]), 3)

    def test_n_subtasks_respected(self):
        for n in (1, 5, 10):
            brain = SimBrain(n_subtasks=n)
            self.assertEqual(len(brain._plan()["subtasks"]), n)

    def test_zero_clamped_to_one(self):
        brain = SimBrain(n_subtasks=0)
        self.assertEqual(len(brain._plan()["subtasks"]), 1)

    def test_negative_clamped_to_one(self):
        brain = SimBrain(n_subtasks=-5)
        self.assertEqual(len(brain._plan()["subtasks"]), 1)

    def test_subtask_shape(self):
        brain = SimBrain(n_subtasks=2)
        subs = brain._plan()["subtasks"]
        for st in subs:
            self.assertIn("title", st)
            self.assertIn("description", st)
            self.assertIn("layer", st)
            self.assertIn("effort_level", st)
            self.assertIsNone(st["verify"])

    def test_subtask_titles_are_unique(self):
        brain = SimBrain(n_subtasks=4)
        titles = [s["title"] for s in brain._plan()["subtasks"]]
        self.assertEqual(len(titles), len(set(titles)))


# ---------------------------------------------------------------------------
# SimBrain.chat
# ---------------------------------------------------------------------------

class TestSimBrainChat(unittest.TestCase):
    def _user_msg(self, text):
        return [{"role": "user", "content": text}]

    def test_invocation_spec_path(self):
        brain = SimBrain()
        resp = brain.chat(messages=self._user_msg("Please write an invocation spec for step 1"))
        data = json.loads(resp["message"]["content"])
        self.assertIn("prompt", data)
        self.assertIn("effort_level", data)
        self.assertIn("skills_to_invoke", data)

    def test_corrected_path_returns_plan(self):
        brain = SimBrain(n_subtasks=2)
        resp = brain.chat(messages=self._user_msg("here is the corrected plan to fix things"))
        data = json.loads(resp["message"]["content"])
        self.assertIn("subtasks", data)
        self.assertEqual(len(data["subtasks"]), 2)

    def test_plan_to_fix_path_returns_plan(self):
        brain = SimBrain(n_subtasks=2)
        resp = brain.chat(messages=self._user_msg("plan to fix the failing step"))
        data = json.loads(resp["message"]["content"])
        self.assertIn("subtasks", data)

    def test_default_path_returns_plan(self):
        brain = SimBrain(n_subtasks=1)
        resp = brain.chat(messages=self._user_msg("build something"))
        data = json.loads(resp["message"]["content"])
        self.assertIn("subtasks", data)

    def test_empty_messages_returns_plan(self):
        brain = SimBrain()
        resp = brain.chat(messages=[])
        data = json.loads(resp["message"]["content"])
        self.assertIn("subtasks", data)

    def test_no_messages_kwarg_returns_plan(self):
        brain = SimBrain()
        resp = brain.chat()
        data = json.loads(resp["message"]["content"])
        self.assertIn("subtasks", data)

    def test_calls_counter_increments(self):
        brain = SimBrain()
        self.assertEqual(brain.calls, 0)
        brain.chat(messages=self._user_msg("invocation spec"))
        brain.chat(messages=self._user_msg("some plan"))
        self.assertEqual(brain.calls, 2)

    def test_model_kwarg_ignored(self):
        brain = SimBrain()
        resp = brain.chat(model="qwen2.5:7b", messages=self._user_msg("invocation spec"))
        self.assertIn("message", resp)

    def test_response_has_message_content_key(self):
        brain = SimBrain()
        resp = brain.chat(messages=self._user_msg("go"))
        self.assertIn("message", resp)
        self.assertIn("content", resp["message"])

    def test_non_dict_message_items_ignored(self):
        brain = SimBrain()
        mixed = ["string item", None, {"role": "user", "content": "invocation spec"}, 42]
        resp = brain.chat(messages=mixed)
        data = json.loads(resp["message"]["content"])
        self.assertIn("prompt", data)

    def test_content_none_falls_back_to_plan(self):
        brain = SimBrain(n_subtasks=1)
        resp = brain.chat(messages=[{"role": "user", "content": None}])
        data = json.loads(resp["message"]["content"])
        self.assertIn("subtasks", data)

    def test_messages_none_returns_plan(self):
        brain = SimBrain()
        resp = brain.chat(messages=None)
        data = json.loads(resp["message"]["content"])
        self.assertIn("subtasks", data)

    def test_invocation_spec_case_insensitive(self):
        brain = SimBrain()
        resp = brain.chat(messages=self._user_msg("INVOCATION SPEC please"))
        data = json.loads(resp["message"]["content"])
        self.assertIn("prompt", data)


# ---------------------------------------------------------------------------
# simRunClaude
# ---------------------------------------------------------------------------

class TestSimRunClaude(unittest.TestCase):
    def test_architect_path_returns_design_doc(self):
        result = simRunClaude({"prompt": "arch"}, system_prompt="write architecture")
        self.assertTrue(result["ok"])
        self.assertEqual(result["returncode"], 0)
        self.assertFalse(result["is_error"])
        self.assertIn("Simulated architecture", result["stdout"])

    def test_architect_doc_is_long_enough(self):
        result = simRunClaude({}, system_prompt="write it")
        self.assertGreater(len(result["stdout"]), 100)

    def test_subtask_path_returns_success(self):
        result = simRunClaude({"prompt": "do step"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["returncode"], 0)
        self.assertFalse(result["is_error"])

    def test_subtask_output_contains_subtask_id(self):
        result = simRunClaude({}, subtask={"subtask_id": "st-007"})
        self.assertIn("st-007", result["stdout"])

    def test_subtask_unknown_id_uses_placeholder(self):
        result = simRunClaude({}, subtask=None)
        self.assertIn("?", result["stdout"])

    def test_architect_session_id_is_none(self):
        result = simRunClaude({}, system_prompt="arch")
        self.assertIsNone(result["session_id"])

    def test_subtask_session_id_is_none(self):
        result = simRunClaude({}, subtask={"subtask_id": "st-001"})
        self.assertIsNone(result["session_id"])

    def test_extra_kwargs_ignored(self):
        result = simRunClaude({}, work_dir="/tmp", task_state=None,
                              extra=None, timeout=30, resume_session="x")
        self.assertTrue(result["ok"])

    def test_empty_subtask_dict_uses_placeholder(self):
        result = simRunClaude({}, subtask={})
        self.assertIn("?", result["stdout"])

    def test_returns_complete_envelope(self):
        result = simRunClaude({})
        for key in ("ok", "returncode", "stdout", "is_error", "session_id"):
            self.assertIn(key, result)


# ---------------------------------------------------------------------------
# SimObs
# ---------------------------------------------------------------------------

class TestSimObs(unittest.TestCase):
    def setUp(self):
        self.obs = SimObs()

    def test_write_note_stores_content(self):
        self.obs.writeNote("tasks/a.md", "hello")
        self.assertEqual(self.obs.notes["tasks/a.md"], "hello")

    def test_write_note_returns_ok(self):
        rv = self.obs.writeNote("a.md", "content")
        self.assertTrue(rv["ok"])
        self.assertEqual(rv["via"], "sim")
        self.assertEqual(rv["rel_path"], "a.md")

    def test_write_note_overwrites(self):
        self.obs.writeNote("a.md", "first")
        self.obs.writeNote("a.md", "second")
        self.assertEqual(self.obs.notes["a.md"], "second")

    def test_append_note_creates_new(self):
        self.obs.appendNote("new.md", "first chunk")
        self.assertEqual(self.obs.notes["new.md"], "first chunk")

    def test_append_note_appends_to_existing(self):
        self.obs.writeNote("b.md", "line1")
        self.obs.appendNote("b.md", "\nline2")
        self.assertEqual(self.obs.notes["b.md"], "line1\nline2")

    def test_append_note_multiple_times(self):
        for chunk in ("a", "b", "c"):
            self.obs.appendNote("multi.md", chunk)
        self.assertEqual(self.obs.notes["multi.md"], "abc")

    def test_append_note_returns_ok(self):
        rv = self.obs.appendNote("x.md", "data")
        self.assertTrue(rv["ok"])
        self.assertEqual(rv["via"], "sim")

    def test_read_note_returns_stored_content(self):
        self.obs.writeNote("r.md", "the content")
        self.assertEqual(self.obs.readNote("r.md"), "the content")

    def test_read_note_missing_returns_none(self):
        self.assertIsNone(self.obs.readNote("does_not_exist.md"))

    def test_health_returns_rest_not_ok(self):
        h = self.obs.health()
        self.assertFalse(h["rest_ok"])
        self.assertFalse(h["authed"])

    def test_notes_starts_empty(self):
        obs2 = SimObs()
        self.assertEqual(obs2.notes, {})

    def test_instances_are_independent(self):
        a, b = SimObs(), SimObs()
        a.writeNote("x.md", "a-value")
        self.assertIsNone(b.readNote("x.md"))

    def test_write_then_read_roundtrip(self):
        content = "multiline\ncontent\nhere"
        self.obs.writeNote("round.md", content)
        self.assertEqual(self.obs.readNote("round.md"), content)


# ---------------------------------------------------------------------------
# simReplan / simReview
# ---------------------------------------------------------------------------

class TestSimReplan(unittest.TestCase):
    def test_returns_keep_action(self):
        rv = simReplan()
        self.assertEqual(rv["action"], "keep")

    def test_has_required_keys(self):
        rv = simReplan()
        for k in ("action", "add", "remove", "reason"):
            self.assertIn(k, rv)

    def test_add_and_remove_are_empty_lists(self):
        rv = simReplan()
        self.assertEqual(rv["add"], [])
        self.assertEqual(rv["remove"], [])

    def test_accepts_arbitrary_args(self):
        rv = simReplan("subtask", "reason", "output", something="else")
        self.assertEqual(rv["action"], "keep")

    def test_reason_is_dry_run(self):
        rv = simReplan()
        self.assertEqual(rv["reason"], "dry-run")

    def test_always_returns_same_structure(self):
        for _ in range(5):
            rv = simReplan()
            self.assertEqual(rv["action"], "keep")


class TestSimReview(unittest.TestCase):
    def test_returns_approved(self):
        rv = simReview("title", "heartbeat", "output")
        self.assertEqual(rv["verdict"], "approved")

    def test_is_stub(self):
        rv = simReview("t", "r", "o")
        self.assertTrue(rv["stub"])

    def test_trigger_reason_preserved(self):
        rv = simReview("t", "my-trigger", "o")
        self.assertEqual(rv["trigger_reason"], "my-trigger")

    def test_concerns_is_empty_list(self):
        rv = simReview("t", "r", "o")
        self.assertEqual(rv["concerns"], [])

    def test_has_notes(self):
        rv = simReview("t", "r", "o")
        self.assertIn("notes", rv)

    def test_kwargs_ignored_without_crash(self):
        rv = simReview("t", "r", "o", ollama_chat=None, goal="some goal")
        self.assertEqual(rv["verdict"], "approved")

    def test_various_trigger_reasons(self):
        for trigger in ("heartbeat", "uncertainty", "attempt_limit", "pre_pr"):
            rv = simReview("t", trigger, "o")
            self.assertEqual(rv["trigger_reason"], trigger)


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
