"""Adversary remediation snapshots + whole-tree git-reverts the working tree. That is SAFE only
when the tree is private to one subtask. _remediationTreeShared must flag the one unsafe case --
a non-self-ref PARALLEL run where subtasks share work_dir -- so remediation is skipped there
instead of clobbering concurrent peer workers' edits (#1)."""
import os
import unittest

from orchestrator import Orchestrator


class _Fake:
    """Minimal stand-in: the method only reads self._parallelism and self._work_dir."""


class TestRemediationTreeShared(unittest.TestCase):
    def _shared(self, parallelism, work_dir, exec_cwd):
        f = _Fake()
        f._parallelism = parallelism
        f._work_dir = work_dir
        return Orchestrator._remediationTreeShared(f, exec_cwd)

    def test_sequential_never_shared(self):
        # parallelism 1 -> no peers -> safe regardless of cwd
        self.assertFalse(self._shared(1, r"C:\repo", r"C:\repo"))

    def test_parallel_shared_workdir_is_shared(self):
        # non-self-ref parallel: all subtasks run in work_dir -> a revert would clobber peers
        self.assertTrue(self._shared(2, r"C:\repo", r"C:\repo"))

    def test_parallel_isolated_cwd_is_safe(self):
        # self-ref: each subtask gets its own .sc-ctx cwd (exec_cwd != work_dir) -> private tree
        self.assertFalse(self._shared(2, r"C:\repo", os.path.join(r"C:\repo", ".sc-ctx", "st-001")))


if __name__ == "__main__":
    unittest.main()
