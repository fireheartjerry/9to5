"""
Smoke-tests for workflow documentation completeness.
Checks that docs/workflow.md exists and covers all required steps,
decision points, and verification types.
"""
import pathlib
import unittest

DOCS_ROOT = pathlib.Path(__file__).parent.parent / "docs"
WORKFLOW_DOC = DOCS_ROOT / "workflow.md"

REQUIRED_HEADINGS = [
    "Step 0",
    "Step 1",
    "Step 2",
    "Step 3",
    "Step 4",
    "Step 5",
    "Step 6",
    "Step 7",
]

REQUIRED_SECTIONS = [
    "Decision-point summary",
    "Verification",
    "Error handling",
    "File layout",
    "Conventions",
]

REQUIRED_KEYWORDS = [
    # core agents
    "Elaborator",
    "Architect",
    "Planner",
    "Adversary",
    "Replanner",
    "Verifier",
    # verify expect types
    "exit_zero",
    "stdout_contains",
    "stdout_regex",
    "stdout_contains_all",
    "stdout_regex_all",
    # control signals
    "abort",
    "pause",
    "skip",
    # control modes
    "watch",
    "gated",
    # retry
    "MAX_SUBTASK_ATTEMPTS",
    # obsidian fallback
    "disk fallback",
    # adversary triggers
    "heartbeat",
    "challenged",
    "approved",
]


class TestWorkflowDoc(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.content = WORKFLOW_DOC.read_text(encoding="utf-8")

    def test_file_exists(self):
        self.assertTrue(WORKFLOW_DOC.exists(), f"Missing: {WORKFLOW_DOC}")

    def test_not_empty(self):
        self.assertGreater(len(self.content.strip()), 500, "workflow.md is too short")

    def test_required_step_headings(self):
        for heading in REQUIRED_HEADINGS:
            self.assertIn(heading, self.content, f"Missing step heading: {heading!r}")

    def test_required_sections(self):
        for section in REQUIRED_SECTIONS:
            self.assertIn(section, self.content, f"Missing section: {section!r}")

    def test_required_keywords(self):
        for kw in REQUIRED_KEYWORDS:
            self.assertIn(kw, self.content, f"Missing keyword: {kw!r}")

    def test_decision_points_table(self):
        self.assertIn("Decision-point summary", self.content)
        # table must cover at least 4 decision rows
        table_rows = [
            ln for ln in self.content.splitlines()
            if ln.strip().startswith("|") and "---" not in ln and "Decision" not in ln
        ]
        self.assertGreaterEqual(
            len(table_rows), 4,
            "Decision-point summary table has fewer rows than expected",
        )

    def test_error_handling_table(self):
        self.assertIn("Error handling", self.content)
        self.assertIn("Ollama unavailable", self.content)
        self.assertIn("disk write", self.content)


if __name__ == "__main__":
    unittest.main()
