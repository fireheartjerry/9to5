"""Acceptance test: verify notification_bus_error_handling.md covers the
required error-handling terms for the NotificationBus surface-isolation contract."""
import pathlib
import sys
import unittest

_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

DOC = _ROOT / "docs" / "notification_bus_error_handling.md"

REQUIRED_TERMS = [
    # Core suppression mechanism
    "BaseException",
    "suppressed",
    # Specific exception types that must be documented
    "KeyboardInterrupt",
    "SystemExit",
    # Isolation contract language
    "surface",
    "emit",
    # Logging
    "WARNING",
    "notifications.bus",
    # surface_count helper
    "surface_count",
    # Anti-patterns
    "Anti-pattern",
    # ControlBus guidance
    "ControlBus",
]


class TestNotificationBusDocs(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        assert DOC.exists(), f"doc not found: {DOC}"
        cls.text = DOC.read_text(encoding="utf-8")

    def _check_all(self, label: str, terms: list) -> None:
        missing = [t for t in terms if t not in self.text]
        self.assertFalse(missing, f"[{label}] missing from {DOC.name}: {missing}")

    def test_doc_exists(self):
        self.assertTrue(DOC.exists(), f"documentation file not found: {DOC}")

    def test_required_terms_present(self):
        self._check_all("required error-handling terms", REQUIRED_TERMS)

    def test_keyboard_interrupt_documented(self):
        self.assertIn(
            "KeyboardInterrupt",
            self.text,
            "doc must explain KeyboardInterrupt suppression inside surfaces",
        )

    def test_system_exit_documented(self):
        self.assertIn(
            "SystemExit",
            self.text,
            "doc must explain SystemExit suppression inside surfaces",
        )

    def test_base_exception_documented(self):
        self.assertIn(
            "BaseException",
            self.text,
            "doc must document that BaseException (not Exception) is caught",
        )

    def test_what_is_not_suppressed(self):
        self.assertIn(
            "NOT suppressed",
            self.text,
            "doc must explain what errors are NOT suppressed by emit()",
        )

    def test_logging_table_present(self):
        self._check_all("logging behaviour", ["WARNING", "notifications.bus", "exception()"])

    def test_surface_count_documented(self):
        self.assertIn("surface_count", self.text, "doc must document the surface_count helper")

    def test_anti_patterns_present(self):
        self._check_all("anti-patterns section", [
            "Anti-pattern",
            "recursive",
            "singleton",
        ])

    def test_controlbus_guidance_present(self):
        self.assertIn(
            "ControlBus",
            self.text,
            "doc must direct surface authors to use ControlBus for shutdown signals",
        )

    def test_quick_reference_present(self):
        self._check_all("quick reference", ["NotificationBus", "register", "emit"])

    def test_h2_headers_present(self):
        """Doc must use H2 section headers for key topics."""
        required_headers = [
            "## The isolation contract",
            "## KeyboardInterrupt and SystemExit inside a surface",
            "## What is NOT suppressed",
            "## Logging behaviour",
            "## Guidance for surface authors",
            "## Anti-patterns",
            "## ControlBus for shutdown signals",
            "## Quick reference",
        ]
        missing = [h for h in required_headers if h not in self.text]
        self.assertFalse(missing, f"missing H2 headers in {DOC.name}: {missing}")

    def test_code_blocks_present(self):
        """Doc must contain fenced code blocks for examples."""
        import re
        blocks = re.findall(r"^```", self.text, re.MULTILINE)
        self.assertGreaterEqual(
            len(blocks), 4,
            "doc must have at least 4 fenced code block delimiters (opening+closing pairs = 2+ examples)",
        )

    def test_deadlock_mechanism_documented(self):
        """Doc must explicitly name the deadlock risk of recursive emit() calls."""
        self.assertIn(
            "deadlock",
            self.text.lower(),
            "doc must document the deadlock mechanism caused by recursive bus.emit() inside handle()",
        )


if __name__ == "__main__":
    result = unittest.main(verbosity=2, exit=False)
    sys.exit(0 if result.result.wasSuccessful() else 1)
