"""Unit tests for executor pure helpers: the block_destructive scanner and the
`claude --output-format json` result-envelope parser. Both are security/contract
critical and were previously untested.

Also covers: a spec with read_only=True must disallow Edit/Write at the hands layer
(enforced read-only verify), and _applyEnvironment -- the executor applies an
environment's wrapLauncher; default None is byte-for-byte identity."""
import json
import unittest
from unittest import mock

import config
from agents import executor
from agents.executor import _applyEnvironment


class TestScanDestructive(unittest.TestCase):
    def test_flags_command_position(self):
        self.assertEqual(executor.scanDestructive("rm -rf /"), ["rm -rf"])
        self.assertTrue(executor.scanDestructive("git push --force origin main"))
        self.assertTrue(executor.scanDestructive("git push -f"))
        self.assertTrue(executor.scanDestructive("drop table users;"))

    def test_flags_after_shell_separators(self):
        self.assertTrue(executor.scanDestructive("echo hi && rm -rf /tmp/x"))
        self.assertTrue(executor.scanDestructive("first line\nrm -rf ~"))
        self.assertTrue(executor.scanDestructive("ls; rmdir /s foo"))

    def test_flags_privilege_prefixed(self):
        # regression: a sudo/doas prefix must not let a destructive command slip past
        self.assertEqual(executor.scanDestructive("sudo rm -rf /"), ["rm -rf"])
        self.assertEqual(executor.scanDestructive("doas rm -rf /home"), ["rm -rf"])

    def test_ignores_benign_prose(self):
        self.assertEqual(executor.scanDestructive("please format the output nicely"), [])
        self.assertEqual(executor.scanDestructive("we could run rm later if needed"), [])
        self.assertEqual(executor.scanDestructive("perform a git push to main"), [])
        self.assertEqual(executor.scanDestructive(""), [])
        self.assertEqual(executor.scanDestructive("python reformatter.py"), [])

    def test_flags_rf_variants_with_extra_letters(self):
        # BUG-010: -[rf]{2} required exactly "-rf"/"-fr" verbatim; real-world variants with an
        # extra flag in the same cluster (verbose, etc.) must still be caught.
        self.assertTrue(executor.scanDestructive("rm -rfv /tmp/x"))
        self.assertTrue(executor.scanDestructive("rm -rvf /tmp/x"))
        self.assertTrue(executor.scanDestructive("rm -vrf /tmp/x"))
        self.assertTrue(executor.scanDestructive("rm -Rf /tmp/x"))
        self.assertTrue(executor.scanDestructive("sudo rm -rfv /"))

    def test_fork_bomb_and_disk_write(self):
        self.assertTrue(executor.scanDestructive(":(){ :|:& };:"))
        # a raw-disk redirect is flagged at command position (after a separator / line start)
        self.assertTrue(executor.scanDestructive("> /dev/sda"))
        self.assertTrue(executor.scanDestructive("echo x; > /dev/sdb"))


class TestParseEnvelope(unittest.TestCase):
    def test_clean_envelope(self):
        blob = json.dumps({"type": "result", "result": "DONE", "is_error": False,
                           "session_id": "s1", "total_cost_usd": 0.01, "num_turns": 3})
        text, fields = executor._parseEnvelope(blob)
        self.assertEqual(text, "DONE")
        self.assertFalse(fields["is_error"])
        self.assertEqual(fields["session_id"], "s1")
        self.assertEqual(fields["cost_usd"], 0.01)
        self.assertEqual(fields["num_turns"], 3)

    def test_tolerates_preamble_line(self):
        blob = "Using fallback model\n" + json.dumps(
            {"type": "result", "result": "OK", "is_error": False, "session_id": "s2"})
        text, fields = executor._parseEnvelope(blob)
        self.assertEqual(text, "OK")
        self.assertEqual(fields["session_id"], "s2")

    def test_no_envelope_returns_raw(self):
        text, fields = executor._parseEnvelope("just plain text")
        self.assertEqual(text, "just plain text")
        self.assertEqual(fields, {})

    def test_empty(self):
        self.assertEqual(executor._parseEnvelope(""), ("", {}))

    def test_error_envelope_nonstring_result_gets_marker(self):
        blob = json.dumps({"type": "result", "is_error": True,
                           "subtype": "error_max_turns", "session_id": "s3"})
        text, fields = executor._parseEnvelope(blob)
        self.assertEqual(text, "[claude error_max_turns]")   # never the raw JSON blob
        self.assertTrue(fields["is_error"])

    def test_cost_usd_fallback_key(self):
        blob = json.dumps({"type": "result", "result": "x", "is_error": False, "cost_usd": 0.5})
        _, fields = executor._parseEnvelope(blob)
        self.assertEqual(fields["cost_usd"], 0.5)


# ---------------------------------------------------------------------------
# "A spec with read_only=True must disallow Edit/Write at the hands layer
# (enforced read-only verify)."
# ---------------------------------------------------------------------------

def _build(spec):
    with mock.patch.object(executor, "_resolveClaudeLauncher", return_value=["claude"]):
        fresh_cmd, _resume, _env, _flags, _model = executor._buildRunConfig(
            spec, task_state=None, subtask=None, resume_session=None,
            work=str(config.PROJECT_ROOT), effort="default", flag=None,
            charter="", claude_md_path=None)
    return fresh_cmd


def test_read_only_disallows_edit_write():
    cmd = _build({"read_only": True})
    assert "--disallowedTools" in cmd
    i = cmd.index("--disallowedTools")
    assert cmd[i + 1] == "Edit" and cmd[i + 2] == "Write"


def test_normal_spec_has_no_global_disallow():
    cmd = _build({})
    # no bare 'Edit'/'Write' disallow tokens for a normal write subtask
    assert "Edit" not in cmd and "Write" not in cmd


# ---------------------------------------------------------------------------
# "The executor applies an environment's wrapLauncher; default None is
# byte-for-byte identity."
# ---------------------------------------------------------------------------

class _FakeDockerEnv:
    def wrapLauncher(self, run_cmd, handle):
        cid = handle["cid"]
        return ["docker", "exec", "-w", "/work", cid, *run_cmd], "/work"


def test_no_environment_is_identity():
    fresh = ["cmd", "/c", "claude.cmd", "--print"]
    resume = ["cmd", "/c", "claude.cmd", "--print", "--resume", "sess-1"]
    out_fresh, out_resume, out_work = _applyEnvironment(fresh, resume, "/repo", None, None)
    assert out_fresh == fresh and out_resume == resume and out_work == "/repo"


def test_none_handle_is_identity():
    fresh = ["claude", "--print"]
    out_fresh, out_resume, out_work = _applyEnvironment(fresh, None, "/repo", _FakeDockerEnv(), None)
    assert out_fresh == fresh and out_resume is None and out_work == "/repo"


def test_environment_wraps_both_commands_and_overrides_work():
    fresh = ["claude", "--print"]
    resume = ["claude", "--print", "--resume", "s1"]
    handle = {"cid": "abc123"}
    out_fresh, out_resume, out_work = _applyEnvironment(fresh, resume, "/repo",
                                                        _FakeDockerEnv(), handle)
    assert out_fresh == ["docker", "exec", "-w", "/work", "abc123", "claude", "--print"]
    assert out_resume == ["docker", "exec", "-w", "/work", "abc123",
                          "claude", "--print", "--resume", "s1"]
    assert out_work == "/work"
