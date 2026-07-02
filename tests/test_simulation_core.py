"""Unit tests for simulation.py — core SimBrain, SimRunClaude, SimObs, SimReplan, SimReview.

Split from test_simulation_units.py (was 673 lines).  Builder / orchestrator
tests live in test_simulation_advanced.py.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import platform_core.simulator.simulation as simulation  # noqa: F401 — ensure module is loaded
from platform_core.simulator.simulation import (
    SimBrain,
    SimObs,
    simReplan,
    simReview,
    simRunClaude,
)


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
# SimBrain.chat -- EXACT act dispatch (R5): prompt wording NEVER routes
# ---------------------------------------------------------------------------

class TestSimBrainChat(unittest.TestCase):
    def _user_msg(self, text):
        return [{"role": "user", "content": text}]

    def test_invocation_spec_act(self):
        brain = SimBrain()
        resp = brain.chat(messages=self._user_msg("anything at all"), act="invocation_spec")
        data = json.loads(resp["message"]["content"])
        self.assertIn("prompt", data)
        self.assertIn("effort_level", data)
        self.assertIn("skills_to_invoke", data)

    def test_critique_act_returns_plan(self):
        brain = SimBrain(n_subtasks=2)
        resp = brain.chat(messages=self._user_msg("totally reworded critique ask"), act="critique")
        data = json.loads(resp["message"]["content"])
        self.assertIn("subtasks", data)
        self.assertEqual(len(data["subtasks"]), 2)

    def test_plan_act_returns_plan(self):
        brain = SimBrain(n_subtasks=1)
        resp = brain.chat(messages=self._user_msg("build something"), act="plan")
        data = json.loads(resp["message"]["content"])
        self.assertIn("subtasks", data)

    def test_wording_never_routes(self):
        """THE R5 regression: the old sim substring-matched 'invocation spec' in the user
        prompt. Now the act tag wins even when the wording says the opposite."""
        brain = SimBrain(n_subtasks=2)
        # wording screams invocation-spec; act says plan -> plan payload
        resp = brain.chat(messages=self._user_msg("INVOCATION SPEC please"), act="plan")
        self.assertIn("subtasks", json.loads(resp["message"]["content"]))
        # wording is a fully reworded directive; act says invocation_spec -> spec payload
        resp = brain.chat(messages=self._user_msg("Compose the execution directive for step 1"),
                          act="invocation_spec")
        self.assertIn("prompt", json.loads(resp["message"]["content"]))

    def test_unknown_act_raises(self):
        brain = SimBrain()
        with self.assertRaises(ValueError):
            brain.chat(messages=self._user_msg("go"), act="mystery_act")

    def test_missing_act_raises(self):
        brain = SimBrain()
        with self.assertRaises(ValueError):
            brain.chat(messages=self._user_msg("go"))

    def test_gatekeeper_act_approves(self):
        brain = SimBrain()
        resp = brain.chat(messages=self._user_msg("gate?"), act="gatekeeper")
        self.assertTrue(json.loads(resp["message"]["content"])["approve"])

    def test_horizon_fill_act_returns_empty_batch(self):
        brain = SimBrain()
        resp = brain.chat(messages=self._user_msg("more work?"), act="horizon_fill")
        self.assertEqual(json.loads(resp["message"]["content"])["subtasks"], [])

    def test_architect_act_returns_text(self):
        brain = SimBrain()
        resp = brain.chat(messages=self._user_msg("design"), act="architect")
        self.assertTrue(resp["message"]["content"].strip())

    def test_calls_counter_increments(self):
        brain = SimBrain()
        self.assertEqual(brain.calls, 0)
        brain.chat(messages=self._user_msg("x"), act="invocation_spec")
        brain.chat(messages=self._user_msg("y"), act="plan")
        self.assertEqual(brain.calls, 2)

    def test_model_kwarg_ignored(self):
        brain = SimBrain()
        resp = brain.chat(model="qwen2.5:7b", messages=self._user_msg("x"), act="invocation_spec")
        self.assertIn("message", resp)

    def test_response_has_message_content_key(self):
        brain = SimBrain()
        resp = brain.chat(messages=self._user_msg("go"), act="plan")
        self.assertIn("message", resp)
        self.assertIn("content", resp["message"])

    def test_messages_irrelevant_to_dispatch(self):
        brain = SimBrain(n_subtasks=1)
        for msgs in (None, [], ["junk", 42], [{"role": "user", "content": None}]):
            data = json.loads(brain.chat(messages=msgs, act="plan")["message"]["content"])
            self.assertIn("subtasks", data)


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
