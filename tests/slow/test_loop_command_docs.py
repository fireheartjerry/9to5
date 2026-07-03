"""Validates that docs/loop_command.md exists and covers /loop command usage correctly."""
import pathlib
import sys
import unittest

DOC = pathlib.Path(__file__).parent.parent.parent / "docs" / "loop_command.md"

REQUIRED_SECTIONS = [
    "## What `/loop` does",
    "## Syntax",
    "## Examples",
    "## Self-paced mode",
    "## When to use",
    "## When NOT to use",
    "## Anti-patterns",
    "## Stopping a loop",
    "## Error handling inside a loop body",
]

REQUIRED_TERMS = [
    "/loop",
    "CC slash command",
    "ScheduleWakeup",
    "interval",
    "self-paced",
    "/loop 5m",
    "subprocess",
    "Ctrl-C",
]


class TestLoopCommandDocs(unittest.TestCase):

    def setUp(self):
        self.assertTrue(DOC.exists(), f"docs/loop_command.md not found at {DOC}")
        self.text = DOC.read_text(encoding="utf-8")

    def test_required_sections_present(self):
        missing = [s for s in REQUIRED_SECTIONS if s not in self.text]
        self.assertEqual(missing, [], f"Missing sections: {missing}")

    def test_required_terms_documented(self):
        missing = [t for t in REQUIRED_TERMS if t not in self.text]
        self.assertEqual(missing, [], f"Missing terms: {missing}")

    def test_non_empty(self):
        self.assertGreater(len(self.text.strip()), 500, "Documentation is too short")

    def test_no_placeholder_text(self):
        for placeholder in ["TODO", "FIXME", "TBD", "placeholder"]:
            self.assertNotIn(placeholder, self.text,
                             f"Placeholder text {placeholder!r} found in doc")

    def test_loop_is_cc_slash_command(self):
        self.assertIn("CC slash command", self.text,
                      "docs/loop_command.md must clarify that /loop is a CC slash command")

    def test_anti_patterns_documented(self):
        self.assertIn("subprocess", self.text,
                      "Anti-patterns must warn against invoking /loop via subprocess")

    def test_self_paced_mode_documented(self):
        self.assertIn("ScheduleWakeup", self.text,
                      "Self-paced mode must reference ScheduleWakeup")
