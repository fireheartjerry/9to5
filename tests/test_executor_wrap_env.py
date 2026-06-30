"""The executor applies an environment's wrapLauncher; default None is byte-for-byte identity."""
from agents.executor import _applyEnvironment


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
