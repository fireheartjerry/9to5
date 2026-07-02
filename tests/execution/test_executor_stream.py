"""R6 operator-kill: in-flight cancel watcher + stderr drain deadlock regression.

Covers agents/executor_stream.runSubprocess:
  * fake-Popen cancel test: a subprocess that never exits is tree-killed within 3s of the
    cancel signal flipping True, and the result carries subtype='operator_killed'.
  * real-subprocess streaming cancel: the watcher kills a sleeping child on the feed path.
  * stderr 1MB deadlock regression: a stderr-chatty child completes in <5s (the sequential
    read-after-stdout drain deadlocked here and burned the whole timeout).
  * no-cancel path: a normal run with a never-firing cancel_check completes unchanged.
"""
import subprocess
import sys
import threading
import time

import config
from agents import executor_stream


class _FeedDouble:
    """Minimal SubprocessFeed stand-in: just records consumed lines."""

    def __init__(self):
        self.lines = []

    def consume(self, line):
        self.lines.append(line)


def _runKw(**over):
    kw = dict(work=".", timeout=30, env=None, creationflags=0, spec={},
              effort="default", flag=None, profile=None, playbook_md="",
              claude_md_path=None, model="test-model", feed=None)
    kw.update(over)
    return kw


class _FakePopen:
    """A subprocess double that NEVER exits until the (faked) tree-kill releases it."""

    last = None

    def __init__(self, *args, **kwargs):
        _FakePopen.last = self
        self.args = args[0] if args else []
        self.pid = 99999
        self.returncode = None
        self._killed = threading.Event()

    def poll(self):
        return self.returncode

    def communicate(self, input=None, timeout=None):
        if not self._killed.wait(timeout=min(timeout or 30, 30)):
            raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout or 0)
        self.returncode = 1
        return "partial output", ""


def test_cancel_watcher_kills_fake_proc_within_3s(monkeypatch):
    """Cancel flips True after 0.1s -> tree-killed and returned in <3s (not the 30s timeout),
    with subtype='operator_killed' distinct from the timeout path."""
    monkeypatch.setattr(executor_stream, "_recordIterationMetric", lambda entry: None)
    monkeypatch.setattr(config, "CANCEL_POLL_SECONDS", 2.0, raising=False)
    monkeypatch.setattr(subprocess, "Popen", _FakePopen)

    def _fake_kill(pid):
        p = _FakePopen.last
        p.returncode = -9
        p._killed.set()

    monkeypatch.setattr(executor_stream, "_killProcessTree", _fake_kill)
    t0 = time.monotonic()
    result = executor_stream.runSubprocess(
        ["claude"], "prompt", cancel_check=lambda: time.monotonic() - t0 > 0.1, **_runKw())
    elapsed = time.monotonic() - t0
    assert elapsed < 3.0, f"kill took {elapsed:.2f}s (must be <3s)"
    assert result["subtype"] == "operator_killed"
    assert result["ok"] is False
    assert "OPERATOR KILLED" in result["stderr"]
    assert result["stdout"] == "partial output"   # partial output is preserved


def test_cancel_watcher_kills_real_streaming_subprocess(monkeypatch):
    """Streaming (feed) path: the watcher tree-kills a real sleeping child within seconds."""
    monkeypatch.setattr(executor_stream, "_recordIterationMetric", lambda entry: None)
    monkeypatch.setattr(config, "CANCEL_POLL_SECONDS", 0.2, raising=False)
    monkeypatch.setattr(config, "EXECUTOR_OUTPUT_JSON", False, raising=False)
    feed = _FeedDouble()
    t0 = time.monotonic()
    result = executor_stream.runSubprocess(
        [sys.executable, "-c", "import time; time.sleep(60)"], "unused prompt",
        cancel_check=lambda: time.monotonic() - t0 > 0.1,
        **_runKw(timeout=20, feed=feed))
    elapsed = time.monotonic() - t0
    assert elapsed < 8.0, f"streaming kill took {elapsed:.2f}s"
    assert result["subtype"] == "operator_killed"
    assert result["ok"] is False


def test_stderr_1mb_no_deadlock(monkeypatch):
    """Regression: a child writing 1MB to stderr BEFORE stdout used to fill the OS pipe
    buffer and deadlock the sequential drain until the full timeout. The concurrent stderr
    reader must let it complete in <5s with all output captured."""
    monkeypatch.setattr(executor_stream, "_recordIterationMetric", lambda entry: None)
    monkeypatch.setattr(config, "EXECUTOR_OUTPUT_JSON", False, raising=False)
    script = ("import sys\n"
              "sys.stderr.write('x' * 1048576)\n"
              "sys.stderr.flush()\n"
              "print('done-marker')\n")
    feed = _FeedDouble()
    t0 = time.monotonic()
    result = executor_stream.runSubprocess(
        [sys.executable, "-c", script], "unused prompt",
        **_runKw(timeout=10, feed=feed))
    elapsed = time.monotonic() - t0
    assert elapsed < 5.0, f"stderr-chatty child took {elapsed:.2f}s (deadlock regression)"
    assert result["ok"] is True
    assert "done-marker" in result["stdout"]
    assert len(result["stderr"]) >= 1048576      # the full stderr stream was drained
    assert result.get("subtype") != "operator_killed"


def test_never_firing_cancel_check_leaves_run_unchanged(monkeypatch):
    """A cancel_check that never fires must not disturb a normal communicate()-path run."""
    monkeypatch.setattr(executor_stream, "_recordIterationMetric", lambda entry: None)
    monkeypatch.setattr(config, "EXECUTOR_OUTPUT_JSON", False, raising=False)
    result = executor_stream.runSubprocess(
        [sys.executable, "-c", "print('hello')"], "unused prompt",
        cancel_check=lambda: False, **_runKw(timeout=20))
    assert result["ok"] is True
    assert "hello" in result["stdout"]
    assert result.get("subtype") != "operator_killed"
