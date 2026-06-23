"""Unit tests for executor playbook routing (classifyProfile) + builders.

The SAFETY INVARIANT is the important one: a subtask with implement intent must
NEVER route to a read-only profile (architect/reviewer), whose charters forbid
edits and would make the executor refuse to write and burn every retry.
"""
import unittest

from agents import playbook


def _c(title="", desc="", spec=None):
    return playbook.classifyProfile(spec or {}, {"title": title, "description": desc})


class TestClassifyProfile(unittest.TestCase):
    def test_explicit_signals_win(self):
        self.assertEqual(_c("implement X", spec={"subagent": "architect"}), "architect")
        self.assertEqual(_c("x", spec={"skills_to_invoke": ["/architect-review"]}), "architect")
        self.assertEqual(_c("x", spec={"subagent": "security-reviewer"}), "reviewer")
        self.assertEqual(_c("x", spec={"skills_to_invoke": ["/create-pr"]}), "pr")

    def test_implement_intent(self):
        self.assertEqual(_c("Implement the parser"), "implementer")
        self.assertEqual(_c("Refactor the module"), "implementer")

    def test_test_and_docs_are_writing_specializations(self):
        self.assertEqual(_c("Write tests for the parser"), "tester")
        self.assertEqual(_c("Add tests for X"), "tester")          # test wins over the 'add' verb
        self.assertEqual(_c("Update the README"), "docs")

    def test_read_only_only_without_implement_intent(self):
        self.assertEqual(_c("Review the auth module"), "reviewer")
        self.assertEqual(_c("Audit for vulnerabilities"), "reviewer")
        self.assertEqual(_c("Design doc for the system"), "architect")

    def test_safety_invariant_implement_never_read_only(self):
        # an implement verb alongside review/audit language must NOT route read-only
        self.assertEqual(_c("Refactor and review the auth module"), "implementer")
        self.assertEqual(_c("Fix the audit findings"), "implementer")

    def test_no_substring_false_positives(self):
        # 'latest' contains 'test', 'preview' contains 'review' -- must not trigger
        self.assertEqual(_c("Ship the latest preview build by editing main"), "implementer")

    def test_defaults_and_complexity_escalation(self):
        self.assertEqual(_c(""), "generalist")
        self.assertEqual(_c("do stuff", spec={"use_workflow": True}), "implementer")
        self.assertEqual(_c("do stuff", spec={"effort_level": "xhigh"}), "implementer")


class TestBuilders(unittest.TestCase):
    def test_charter_includes_role_and_common(self):
        charter = playbook.buildCharter("implementer")
        self.assertIn("Code implementer", charter)
        self.assertIn("9TO5 EXECUTOR", charter)

    def test_unknown_profile_falls_back_to_generalist(self):
        self.assertIn("General executor", playbook.buildCharter("does-not-exist"))
        self.assertIn("General executor", playbook.buildPlaybook("does-not-exist"))

    def test_playbook_renders_common_nonnegotiables(self):
        pb = playbook.buildPlaybook("tester")
        self.assertIn("Non-negotiables", pb)
        self.assertIn("Test author", pb)


if __name__ == "__main__":
    unittest.main()
