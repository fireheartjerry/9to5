"""The self_modification_guard PreToolUse hook must FAIL CLOSED: if the guard itself crashes
while a write target is identified, it must BLOCK (exit 2), never silently allow the edit -- a
malformed task meta must not become a way to edit .env / .git / state / core loop files."""
import unittest
from unittest import mock

from agents import hooks


class TestGuardFailClosed(unittest.TestCase):
    def _run(self, data):
        with self.assertRaises(SystemExit) as cm:
            hooks.selfModificationGuard(data)
        return cm.exception.code

    def test_internal_error_with_write_target_blocks(self):
        """An exception after the write target is identified must exit 2 (block), not 0 (allow)."""
        data = {"tool_name": "Edit", "tool_input": {"file_path": r"C:\9to5\.env"}}
        with mock.patch.object(hooks, "_resolveState", side_effect=RuntimeError("malformed meta")):
            code = self._run(data)
        self.assertEqual(code, 2, "guard failed OPEN on internal error (should fail CLOSED)")

    def test_internal_error_bash_write_target_blocks(self):
        data = {"tool_name": "Bash", "tool_input": {"command": "echo x > config.py"}}
        with mock.patch.object(hooks, "_resolveState", side_effect=RuntimeError("boom")):
            code = self._run(data)
        self.assertEqual(code, 2)

    def test_no_write_target_allows(self):
        """A non-write tool has nothing to guard -- it should exit 0 even if something is off."""
        data = {"tool_name": "Read", "tool_input": {}}
        code = self._run(data)
        self.assertEqual(code, 0)

    def _state_with_env_boundary(self):
        st = mock.Mock()
        st.meta = {"universe": {"hard_boundaries": [".env"]}, "is_self_referential": False, "epoch": None}
        return st

    def test_mv_to_boundary_at_command_start_is_blocked(self):
        """A Bash command STARTING with mv/cp onto a hard-boundary file must be inspected + blocked --
        the old ' mv '/' cp ' substring tokens missed a command-initial mv/cp (fail-open)."""
        data = {"tool_name": "Bash", "tool_input": {"command": "mv secrets.txt .env"}}
        with mock.patch.object(hooks, "_resolveState", return_value=(self._state_with_env_boundary(), True)), \
                mock.patch.object(hooks, "_envTaskRequested", return_value=True), \
                mock.patch.object(hooks, "_coreLockFor", return_value=(False, ())):
            code = self._run(data)
        self.assertEqual(code, 2, "command-initial `mv` onto a boundary was not blocked (fail-open)")

    def test_cp_at_command_start_is_inspected(self):
        data = {"tool_name": "Bash", "tool_input": {"command": "cp config.py .env"}}
        with mock.patch.object(hooks, "_resolveState", return_value=(self._state_with_env_boundary(), True)), \
                mock.patch.object(hooks, "_envTaskRequested", return_value=True), \
                mock.patch.object(hooks, "_coreLockFor", return_value=(False, ())):
            code = self._run(data)
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
