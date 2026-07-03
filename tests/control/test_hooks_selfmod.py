"""agents/hooks_selfmod.py + the self_modification_guard PreToolUse hook (agents/hooks.py).

Merged (consolidation pass, tests/control sprawl reduction) from:
  - test_hooks_resolve_state.py    -- BUG-012: _resolveState() must not guess the wrong task
  - test_hooks_selfmod_writes.py   -- B11: Bash write-detection must cover PowerShell/downloaders
  - test_self_mod_guard_failclosed.py -- the guard hook must FAIL CLOSED on internal error
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

import pytest

from agents import hooks
from agents import hooks_selfmod
from agents.hooks_selfmod import _parseBashGuardInput, _resolveState


# =============================================================================
# Merged from test_hooks_resolve_state.py
# =============================================================================
"""BUG-012: _resolveState() must not guess the wrong task via loadLatest() when no task is
pinned via env vars at all. In a concurrent/resumed session "the latest" task may not be the
one this hook's tool call actually belongs to, enforcing the wrong task's hard_boundaries."""


class _FakeState:
    pass


def test_no_env_vars_returns_none_without_calling_load_latest():
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("NINE_TO_FIVE_TASK_FILE", None)
        os.environ.pop("NINE_TO_FIVE_TASK_ID", None)
        with mock.patch("state.task.TaskState.loadLatest") as m:
            m.return_value = _FakeState()   # would be a WRONG-task guess if ever called
            state, explicit = _resolveState()
    m.assert_not_called()
    assert state is None
    assert explicit is False


def test_task_id_env_var_failure_still_falls_back_to_load_latest():
    # A real degraded case (env var WAS set but resolution failed) is not the same bug --
    # falling back here is a reasonable degrade, not a guess from nothing.
    with mock.patch.dict(os.environ, {"NINE_TO_FIVE_TASK_ID": "does-not-exist"}, clear=False):
        os.environ.pop("NINE_TO_FIVE_TASK_FILE", None)
        with mock.patch("state.task.TaskState.load", side_effect=RuntimeError("missing")), \
             mock.patch("state.task.TaskState.loadLatest") as m:
            fake = _FakeState()
            m.return_value = fake
            state, explicit = _resolveState()
    m.assert_called_once()
    assert state is fake
    assert explicit is False


# =============================================================================
# Merged from test_hooks_selfmod_writes.py
# =============================================================================
"""Bash write-detection must cover PowerShell verbs and downloaders (B11).

If a write command is not recognised as a write, ``_parseBashGuardInput`` returns
``should_exit0=True`` (treated as read-only, safe) and the boundary check is skipped.
"""

_POWERSHELL_WRITES = [
    "Set-Content -Path foo.txt -Value bar",
    "Out-File -FilePath foo.txt",
    "Add-Content foo.txt 'x'",
    "New-Item -ItemType File foo.txt",
    "Remove-Item foo.txt",
    "Clear-Content foo.txt",
]

_DOWNLOADERS = [
    "curl -o out.bin https://example.com/x",
    "curl -O https://example.com/x",
    "iwr https://example.com/x -OutFile out.bin",
    "wget https://example.com/x",
]


@pytest.mark.parametrize("cmd", _POWERSHELL_WRITES + _DOWNLOADERS)
def test_write_command_is_not_flagged_readonly(cmd):
    _bash, is_secret, should_exit0 = _parseBashGuardInput({"command": cmd})
    assert is_secret is False
    # should_exit0 True would mean "read-only, skip boundary check" -- a write must NOT be that.
    assert should_exit0 is False, f"write command treated as read-only: {cmd!r}"


def test_plain_read_still_readonly():
    _bash, is_secret, should_exit0 = _parseBashGuardInput({"command": "cat README.md"})
    assert is_secret is False
    assert should_exit0 is True


def test_bare_curl_get_still_readonly():
    # curl without -o just prints to stdout -- not a write.
    _bash, _is_secret, should_exit0 = _parseBashGuardInput({"command": "curl https://example.com"})
    assert should_exit0 is True


# =============================================================================
# Merged from test_self_mod_guard_failclosed.py
# =============================================================================
"""The self_modification_guard PreToolUse hook must FAIL CLOSED: if the guard itself crashes
while a write target is identified, it must BLOCK (exit 2), never silently allow the edit -- a
malformed task meta must not become a way to edit .env / .git / state / core loop files."""


class TestGuardFailClosed(unittest.TestCase):
    def setUp(self):
        # Runner-agnostic safety: the guard's boundary-hit path posts a Discord embed
        # (agents/hooks.py), and the conftest Discord mute is pytest-only -- under bare `unittest`
        # it would hit the live channel. Patch the sink at its source so this file never posts.
        import notifications.discord_bot as _discord
        self._discord_patch = mock.patch.object(_discord, "sendEmbed", return_value=None)
        self._discord_patch.start()

    def tearDown(self):
        self._discord_patch.stop()

    def _run(self, data):
        with self.assertRaises(SystemExit) as cm:
            hooks.selfModificationGuard(data)
        return cm.exception.code

    def test_internal_error_with_write_target_blocks(self):
        """An exception after the write target is identified must exit 2 (block), not 0 (allow)."""
        data = {"tool_name": "Edit", "tool_input": {"file_path": r"C:\9to5\.env"}}
        with mock.patch.object(hooks_selfmod, "_resolveState", side_effect=RuntimeError("malformed meta")):
            code = self._run(data)
        self.assertEqual(code, 2, "guard failed OPEN on internal error (should fail CLOSED)")

    def test_internal_error_bash_write_target_blocks(self):
        data = {"tool_name": "Bash", "tool_input": {"command": "echo x > config.py"}}
        with mock.patch.object(hooks_selfmod, "_resolveState", side_effect=RuntimeError("boom")):
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
        with mock.patch.object(hooks_selfmod, "_resolveState", return_value=(self._state_with_env_boundary(), True)), \
                mock.patch.object(hooks_selfmod, "_envTaskRequested", return_value=True), \
                mock.patch.object(hooks_selfmod, "_coreLockFor", return_value=(False, ())):
            code = self._run(data)
        self.assertEqual(code, 2, "command-initial `mv` onto a boundary was not blocked (fail-open)")

    def test_cp_at_command_start_is_inspected(self):
        data = {"tool_name": "Bash", "tool_input": {"command": "cp config.py .env"}}
        with mock.patch.object(hooks_selfmod, "_resolveState", return_value=(self._state_with_env_boundary(), True)), \
                mock.patch.object(hooks_selfmod, "_envTaskRequested", return_value=True), \
                mock.patch.object(hooks_selfmod, "_coreLockFor", return_value=(False, ())):
            code = self._run(data)
        self.assertEqual(code, 2)

    def _block_expected(self, command: str):
        data = {"tool_name": "Bash", "tool_input": {"command": command}}
        with mock.patch.object(hooks_selfmod, "_resolveState", return_value=(self._state_with_env_boundary(), True)), \
                mock.patch.object(hooks_selfmod, "_envTaskRequested", return_value=True), \
                mock.patch.object(hooks_selfmod, "_coreLockFor", return_value=(False, ())):
            return self._run(data)

    def test_write_verbs_after_a_wrapper_word_are_blocked(self):
        """Write verbs preceded by a wrapper word (git/sudo/xargs) or grouping were fail-open:
        the old command-position anchor only matched start-of-line / after [\\n;&|]."""
        for cmd in ("git rm .env", "sudo rm .env", "echo .env | xargs rm", "(rm .env)",
                    "find . -name .env -delete"):
            self.assertEqual(self._block_expected(cmd), 2, f"not blocked: {cmd!r}")

    def test_inline_interpreter_write_to_boundary_is_blocked(self):
        for cmd in ("python -c \"open('.env','w').write('x')\"",
                    "dd if=/dev/zero of=.env", "truncate -s0 .env"):
            self.assertEqual(self._block_expected(cmd), 2, f"not blocked: {cmd!r}")

    def test_plain_read_of_nonsecret_file_still_allowed(self):
        """Reads of NON-secret files (even a core file) are not writes -- still allowed.
        (The secret family is carved out separately; everything else reads freely.)"""
        self.assertEqual(self._block_expected("cat config.py"), 0)
        self.assertEqual(self._block_expected("head README.md"), 0)

    def test_secret_read_via_bash_is_blocked(self):
        """HIGH read-exfil: a Bash READ of the .env secret family is refused (exfiltration guard)."""
        for cmd in ("cat .env", "type .env", "head .env.local", "grep SECRET .env",
                    "less ./.env", "tail -n5 .env.production"):
            self.assertEqual(self._block_expected(cmd), 2, f"secret read not blocked: {cmd!r}")

    def test_secret_read_blocked_even_without_run_context(self):
        """The secret-read block is state-independent / fail-closed -- no task context needed."""
        data = {"tool_name": "Bash", "tool_input": {"command": "cat .env"}}
        with self.assertRaises(SystemExit) as cm:
            hooks.selfModificationGuard(data)
        self.assertEqual(cm.exception.code, 2)

    def test_envrc_and_lookalikes_are_not_secret_reads(self):
        """.envrc is NOT the secret family; foo.env / .environment / unrelated reads must not block."""
        for cmd in ("cat .envrc", "cat foo.env", "cat .environment", "grep x app.py"):
            self.assertEqual(self._block_expected(cmd), 0, f"false-blocked: {cmd!r}")

    def test_external_generated_dirs_are_hard_boundaries(self):
        st = mock.Mock()
        st.meta = {"universe": {"hard_boundaries": []}, "is_self_referential": False, "epoch": None}
        with mock.patch.object(hooks_selfmod, "_resolveState", return_value=(st, True)), \
                mock.patch.object(hooks_selfmod, "_envTaskRequested", return_value=True), \
                mock.patch.object(hooks_selfmod, "_coreLockFor", return_value=(False, ())):
            data = {"tool_name": "Edit",
                    "tool_input": {"file_path": r"C:\project\node_modules\pkg\index.js"}}
            self.assertEqual(self._run(data), 2)

    def test_normal_external_source_file_is_not_boundary(self):
        st = mock.Mock()
        st.meta = {"universe": {"hard_boundaries": []}, "is_self_referential": False, "epoch": None}
        with mock.patch.object(hooks_selfmod, "_resolveState", return_value=(st, True)), \
                mock.patch.object(hooks_selfmod, "_envTaskRequested", return_value=True), \
                mock.patch.object(hooks_selfmod, "_coreLockFor", return_value=(False, ())):
            data = {"tool_name": "Edit", "tool_input": {"file_path": r"C:\project\src\app.py"}}
            self.assertEqual(self._run(data), 0)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
