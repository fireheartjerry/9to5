"""Unit tests for the `@9to5 <goal>` chat-style launch shorthand (main._applyMentionShorthand)."""
import unittest

from main import _applyMentionShorthand as sh


class TestMentionShorthand(unittest.TestCase):
    def test_no_mention_passes_through_unchanged(self):
        argv = ["--goal", "x", "--hours", "2"]
        self.assertEqual(sh(argv), argv)

    def test_empty_passes_through(self):
        self.assertEqual(sh([]), [])

    def test_bare_mention_collects_goal_and_implies_auto_approve(self):
        out = sh(["@9to5", "build", "a", "thing"])
        self.assertEqual(out, ["--goal", "build a thing", "--auto-approve"])

    def test_quoted_goal_in_one_token(self):
        out = sh(["@9to5", "build a thing"])
        self.assertEqual(out, ["--goal", "build a thing", "--auto-approve"])

    def test_colon_form_rides_goal_on_mention_token(self):
        out = sh(["@9to5:do the work"])
        self.assertEqual(out, ["--goal", "do the work", "--auto-approve"])

    def test_flags_pass_through_after_goal(self):
        out = sh(["@9to5", "do", "x", "--hours", "2", "--mode", "gated"])
        self.assertEqual(out, ["--goal", "do x", "--auto-approve", "--hours", "2", "--mode", "gated"])

    def test_existing_auto_approve_not_duplicated(self):
        out = sh(["@9to5", "do x", "--auto-approve"])
        self.assertEqual(out.count("--auto-approve"), 1)

    def test_mention_is_case_insensitive(self):
        self.assertEqual(sh(["@9TO5", "do x"]), ["--goal", "do x", "--auto-approve"])


if __name__ == "__main__":
    unittest.main()
