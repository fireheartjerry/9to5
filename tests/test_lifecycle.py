"""The canonical run/subtask status vocabulary (lifecycle.py)."""
import unittest

import platform_core.core.lifecycle as lifecycle
from platform_core.core.lifecycle import RunStatus, SubtaskStatus


class TestEnumValuesAreOnDiskStrings(unittest.TestCase):
    def test_run_status_value_equals_literal(self):
        # The str mixin is the whole point: existing `meta["status"] == "done"` must keep working.
        self.assertEqual(RunStatus.DONE, "done")
        self.assertTrue(RunStatus.EXECUTING == "executing")

    def test_subtask_status_value_equals_literal(self):
        self.assertEqual(SubtaskStatus.IN_PROGRESS, "in_progress")
        self.assertEqual(SubtaskStatus.REMOVED, "removed")

    def test_membership_check_works_with_raw_strings(self):
        # Mirrors orchestrator/state comparisons that test a raw dict value against the set.
        self.assertIn("done", lifecycle.TERMINAL_RUN_STATUSES)
        self.assertIn("complete", lifecycle.TERMINAL_RUN_STATUSES)  # legacy spelling preserved


class TestTerminalSets(unittest.TestCase):
    def test_crashed_is_not_terminal(self):
        # CRASHED is persisted but resumable -- recovery depends on it NOT being terminal.
        self.assertFalse(lifecycle.isTerminalRun("crashed"))

    def test_done_partial_blocked_failed_aborted_are_terminal(self):
        for s in ("done", "partial", "blocked", "failed", "aborted"):
            self.assertTrue(lifecycle.isTerminalRun(s), s)

    def test_executing_is_not_terminal(self):
        self.assertFalse(lifecycle.isTerminalRun("executing"))

    def test_subtask_terminal(self):
        self.assertTrue(lifecycle.isTerminalSubtask("done"))
        self.assertTrue(lifecycle.isTerminalSubtask("removed"))
        self.assertFalse(lifecycle.isTerminalSubtask("pending"))


class TestNormalize(unittest.TestCase):
    def test_synonyms_fold_to_done(self):
        for s in ("complete", "completed", "success", "ok", "passed", "finished"):
            self.assertEqual(lifecycle.normalizeRunStatus(s), "done", s)

    def test_case_and_whitespace_insensitive(self):
        self.assertEqual(lifecycle.normalizeRunStatus("  DONE "), "done")

    def test_unknown_passes_through(self):
        # An uncatalogued status must never be silently lost.
        self.assertEqual(lifecycle.normalizeRunStatus("source_unreachable"), "source_unreachable")

    def test_canonical_terminal_after_normalize(self):
        self.assertTrue(lifecycle.isTerminalRun("Completed"))  # synonym -> done -> terminal


if __name__ == "__main__":
    unittest.main()
