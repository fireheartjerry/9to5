"""
Smoke-tests for documentation completeness.
Checks that docs/workflow.md exists and covers all required steps,
decision points, and verification types.

Also folds in the former tests/test_documentation.py (same subject: doc
completeness smoke tests) -- docs/notification_system.md and docs/pr_feedback.md
coverage, plus a standalone verifier path-normalization check.
"""
import pathlib
import sys
import unittest

DOCS_ROOT = pathlib.Path(__file__).parent.parent.parent / "docs"
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


# ---------------------------------------------------------------------------
# docs/notification_system.md completeness (formerly tests/test_documentation.py)
# ---------------------------------------------------------------------------
"""Validates that docs/notification_system.md exists and covers required sections."""

NOTIFICATION_DOC = pathlib.Path(__file__).parent.parent.parent / "docs" / "notification_system.md"

NOTIFICATION_REQUIRED_SECTIONS = [
    "## Architecture overview",
    "## NotificationEntry schema",
    "## Discord live dashboard",
    "## Discord milestone embeds",
    "## Discord branding",
    "## Slash commands",
    "## Web dashboard",
    "## Gateway command bot",
    "## Audit log",
    "## Metrics",
    "## Embed size limits",
    "## Conventions",
]

NOTIFICATION_REQUIRED_TERMS = [
    "NotificationEntry",
    "makeEntry",
    "validate",
    "VALID_KINDS",
    "DiscordDashboard",
    "controlPanelRow",
    "editMessageResult",
    "_clampEmbed",
    "audit.record",
    "compute()",
    "NIGHT_MODE",
    "/api/state",
    "/api/control",
]


class TestNotificationSystemDoc(unittest.TestCase):

    def setUp(self):
        self.assertTrue(NOTIFICATION_DOC.exists(), f"docs/notification_system.md not found at {NOTIFICATION_DOC}")
        self.text = NOTIFICATION_DOC.read_text(encoding="utf-8")

    def test_required_sections_present(self):
        missing = [s for s in NOTIFICATION_REQUIRED_SECTIONS if s not in self.text]
        self.assertEqual(missing, [], f"Missing sections: {missing}")

    def test_required_terms_documented(self):
        missing = [t for t in NOTIFICATION_REQUIRED_TERMS if t not in self.text]
        self.assertEqual(missing, [], f"Missing terms: {missing}")

    def test_non_empty(self):
        self.assertGreater(len(self.text.strip()), 500, "Documentation is too short")

    def test_no_placeholder_text(self):
        for placeholder in ["TODO", "FIXME", "TBD", "placeholder"]:
            self.assertNotIn(placeholder, self.text,
                             f"Placeholder text {placeholder!r} found in doc")

    def test_loop_is_cc_slash_command_documented(self):
        self.assertIn("/loop is a CC slash command", self.text,
                      "docs/notification_system.md must document that /loop is a CC slash command")
        print("/loop is a CC slash command")

class TestPRFeedbackDoc(unittest.TestCase):
    """Validates that docs/pr_feedback.md exists and covers required sections."""

    DOC = pathlib.Path(__file__).parent.parent.parent / "docs" / "pr_feedback.md"

    _REQUIRED_SECTIONS = [
        "## Deployment Instructions",
        "## Architecture overview",
        "## Public API",
        "## Promotion Gate",
        "## Learning Loop Integration",
        "## Tests",
    ]

    _REQUIRED_TERMS = [
        "capturePRFeedback",
        "record_pr_outcome",
        "fetch_pr_outcomes",
        "promote_safe",
        "EXPERIENCE_LEDGER_ENABLED",
        "pr_outcomes",
        "record_reflection",
        "record_feedback",
    ]

    def setUp(self):
        self.assertTrue(self.DOC.exists(), f"docs/pr_feedback.md not found at {self.DOC}")
        self.text = self.DOC.read_text(encoding="utf-8")

    def test_required_sections_present(self):
        missing = [s for s in self._REQUIRED_SECTIONS if s not in self.text]
        self.assertEqual(missing, [], f"Missing sections: {missing}")

    def test_required_terms_documented(self):
        missing = [t for t in self._REQUIRED_TERMS if t not in self.text]
        self.assertEqual(missing, [], f"Missing terms: {missing}")

    def test_non_empty(self):
        self.assertGreater(len(self.text.strip()), 500, "pr_feedback.md is too short")

    def test_deployment_instructions_present(self):
        self.assertIn("## Deployment Instructions", self.text)
        self.assertIn("Step 1", self.text)
        self.assertIn("Step 2", self.text)
        self.assertIn("Step 3", self.text)
        print("Deployment Instructions")

    def test_learning_loop_integration_documented(self):
        self.assertIn("## Learning Loop Integration", self.text)
        self.assertIn("record_reflection", self.text)
        self.assertIn("promote_safe", self.text)
        print("PR feedback integration documented")


def _runPathNormalizationCheck() -> bool:
    """Verify that the verifier normalizes work_dir to the repo root for repo-script commands."""
    repo_root = pathlib.Path(__file__).parent.parent.parent
    sys.path.insert(0, str(repo_root))
    try:
        from agents.verifier import _normalizeWorkDir  # noqa: PLC0415
    except ImportError as exc:
        print(f"FAIL: could not import _normalizeWorkDir: {exc}")
        return False

    subtask_dir = str(repo_root / ".sc-ctx" / "st-033")
    repo_root_str = str(repo_root)

    cases = [
        # Absolute path under INSTALL_ROOT -> must normalise to repo root
        (f"python {repo_root / 'tests' / 'test_documentation.py'}", subtask_dir, repo_root_str),
        # Absolute path under INSTALL_ROOT with extra flags -> must normalise
        (f"python {repo_root / 'tests' / 'test_documentation.py'} --verbose", subtask_dir, repo_root_str),
        # python -c (not a .py file path match) -> unchanged
        ("python -c \"print('hi')\"", subtask_dir, subtask_dir),
        # Already at repo root -> unchanged
        (f"python {repo_root / 'tests' / 'test_documentation.py'}", repo_root_str, repo_root_str),
    ]

    for cmd, work_dir_in, expected in cases:
        result = _normalizeWorkDir(cmd, work_dir_in)
        if result != expected:
            print(f"FAIL: _normalizeWorkDir({cmd!r}, {work_dir_in!r}) -> {result!r}, expected {expected!r}")
            return False

    print("PASS: verifier path normalization works correctly")
    return True
