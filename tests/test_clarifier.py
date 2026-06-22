"""Unit tests for the Clarifier -- detecting executor punts and auto-answering.

These lock in detection behavior: a regression that stops detecting a punt would
silently stall subtasks (the executor asks, nobody answers, retries burn), and a
regression that over-detects would waste brain calls on work that was actually done.
"""
import unittest

from agents import clarifier


class TestDetect(unittest.TestCase):
    def test_detects_uncertainty_and_questions(self):
        for text in [
            "I'm not sure whether to use tabs or spaces.",
            "Which approach do you want me to take?",
            "Should I add a test for this?",
            "Could you please clarify the expected output?",
            "Do you want me to delete the old file?",
            "This is ambiguous; multiple approaches exist.",
        ]:
            self.assertTrue(clarifier.detectClarificationNeeded(text), text)

    def test_ignores_action_reports(self):
        for text in [
            "I implemented the function and added tests. All pass.",
            "Created config.py with the constants.",
            "The build succeeded and I committed the change.",
        ]:
            self.assertEqual(clarifier.detectClarificationNeeded(text), [], text)

    def test_empty_and_none(self):
        self.assertEqual(clarifier.detectClarificationNeeded(""), [])
        self.assertEqual(clarifier.detectClarificationNeeded(None), [])

    def test_caps_at_five_hits(self):
        text = " ".join(["I'm not sure about this."] * 12)
        self.assertLessEqual(len(clarifier.detectClarificationNeeded(text)), 5)


class TestAnswer(unittest.TestCase):
    def test_answers_via_chat(self):
        def chat(system, user):
            return {"message": {"content": "  Use spaces.  "}}
        out = clarifier.answerClarifications(chat, "goal", {"subtask_id": "st-001", "title": "t"},
                                             "executor output", ["tabs or spaces?"])
        self.assertEqual(out, "Use spaces.")

    def test_none_when_no_questions(self):
        def chat(system, user):
            return {"message": {"content": "x"}}
        self.assertIsNone(clarifier.answerClarifications(chat, "g", {}, "o", []))

    def test_none_when_chat_returns_none(self):
        self.assertIsNone(clarifier.answerClarifications(lambda s, u: None, "g", {}, "o", ["q?"]))

    def test_none_when_chat_raises(self):
        def boom(system, user):
            raise RuntimeError("ollama down")
        self.assertIsNone(clarifier.answerClarifications(boom, "g", {}, "o", ["q?"]))

    def test_empty_answer_is_none(self):
        self.assertIsNone(clarifier.answerClarifications(
            lambda s, u: {"message": {"content": "   "}}, "g", {}, "o", ["q?"]))


if __name__ == "__main__":
    unittest.main()
