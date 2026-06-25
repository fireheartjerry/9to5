"""Tests for the Ask Nightclaw pure core: context builder, conservative NL-control intent
detection, and graceful answer() (chat fn injected -> no live Ollama)."""
import unittest

from notifications import ask


class _StubState:
    meta = {"goal_raw": "Build a Discord lab", "status": "executing", "control_mode": "gated"}
    subtasks = [
        {"subtask_id": "st-001", "title": "scaffold", "status": "done",
         "verify_result": {"passed": True}},
        {"subtask_id": "st-002", "title": "cockpit", "status": "in_progress"},
        {"subtask_id": "st-003", "title": "polish", "status": "pending"},
        {"subtask_id": "st-004", "title": "old", "status": "removed"},
    ]
    data = {"notifications": [{"kind": "subtask_done", "detail": "st-001"}],
            "adversary_reviews": [{"trigger_reason": "heartbeat", "verdict": "approved"}]}


class BuildContext(unittest.TestCase):
    def test_includes_core_fields(self):
        ctx = ask.buildContext(_StubState(), "how is it going?")
        self.assertIn("Build a Discord lab", ctx)
        self.assertIn("st-002", ctx)
        self.assertIn("QUESTION: how is it going?", ctx)
        self.assertIn("PROGRESS: 1/3", ctx)        # removed subtask not counted

    def test_excludes_removed_subtask(self):
        self.assertNotIn("st-004", ask.buildContext(_StubState(), "q"))


class Intent(unittest.TestCase):
    def test_pause(self):
        self.assertEqual(ask.detectControlIntent("pause it"), "pause")

    def test_stop_maps_abort(self):
        self.assertEqual(ask.detectControlIntent("stop"), "abort")

    def test_resume(self):
        self.assertEqual(ask.detectControlIntent("resume the run"), "resume")

    def test_question_is_not_command(self):
        self.assertIsNone(ask.detectControlIntent("why did it pause?"))

    def test_long_message_is_not_command(self):
        self.assertIsNone(ask.detectControlIntent("please can you pause the run for me now thanks a lot"))

    def test_unrelated_none(self):
        self.assertIsNone(ask.detectControlIntent("show me the plan"))


class Answer(unittest.TestCase):
    def test_uses_injected_chat(self):
        out = ask.answer("status?", _StubState(), chat=lambda s, u: "All good, st-002 in progress.")
        self.assertEqual(out, "All good, st-002 in progress.")

    def test_empty_completion_message(self):
        out = ask.answer("q", _StubState(), chat=lambda s, u: "   ")
        self.assertIn("empty answer", out)

    def test_offline_on_exception(self):
        def boom(s, u):
            raise RuntimeError("ollama down")
        out = ask.answer("q", _StubState(), chat=boom)
        self.assertIn("Brain offline", out)

    def test_context_passed_to_chat(self):
        seen = {}

        def cap(system, user):
            seen["user"] = user
            return "ok"
        ask.answer("did st-001 pass?", _StubState(), chat=cap)
        self.assertIn("st-001", seen["user"])
        self.assertIn("did st-001 pass?", seen["user"])


if __name__ == "__main__":
    unittest.main()
