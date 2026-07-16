"""R6 operator-kill: in-flight cancel watcher + stderr drain deadlock regression.

Covers agents/executor_stream.runSubprocess:
  * fake-Popen cancel test: a subprocess that never exits is tree-killed within 3s of the
    cancel signal flipping True, and the result carries subtype='operator_killed'.
  * real-subprocess streaming cancel: the watcher kills a sleeping child on the feed path.
  * stderr 1MB deadlock regression: a stderr-chatty child completes in <5s (the sequential
    read-after-stdout drain deadlocked here and burned the whole timeout).
  * no-cancel path: a normal run with a never-firing cancel_check completes unchanged.

Also covers (B9): streaming drain must read stderr concurrently, not after stdout EOF --
a child that fills the ~64KB stderr pipe buffer before stdout EOF deadlocks the old
"read stderr after the stdout loop" code. The concurrent stderr drain thread fixes it.
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
    monkeypatch.setattr(
        "platform_core.execution.launch_guard.requireTransactionalKernelActive",
        lambda: None,
    )
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
    monkeypatch.setattr(
        "platform_core.execution.launch_guard.requireTransactionalKernelActive",
        lambda: None,
    )
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
    monkeypatch.setattr(
        "platform_core.execution.launch_guard.requireTransactionalKernelActive",
        lambda: None,
    )
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
    monkeypatch.setattr(
        "platform_core.execution.launch_guard.requireTransactionalKernelActive",
        lambda: None,
    )
    monkeypatch.setattr(config, "EXECUTOR_OUTPUT_JSON", False, raising=False)
    result = executor_stream.runSubprocess(
        [sys.executable, "-c", "print('hello')"], "unused prompt",
        cancel_check=lambda: False, **_runKw(timeout=20))
    assert result["ok"] is True
    assert "hello" in result["stdout"]
    assert result.get("subtype") != "operator_killed"


class _Feed:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def consume(self, line: str) -> None:
        self.lines.append(line)


def test_streaming_drains_large_stderr_without_deadlock():
    # Child writes 200KB to stderr FIRST (blocks on a full pipe), THEN streams stdout.
    script = (
        "import sys\n"
        "sys.stderr.write('E' * 200000)\n"
        "sys.stderr.flush()\n"
        "for i in range(5):\n"
        "    sys.stdout.write('line%d\\n' % i)\n"
        "    sys.stdout.flush()\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )
    feed = _Feed()
    box: dict = {}

    def _run():
        box["out"], box["err"] = executor_stream._drainStreaming(proc, "", feed, 60)

    worker = threading.Thread(target=_run, daemon=True)
    try:
        worker.start()
        worker.join(timeout=30)
        assert not worker.is_alive(), "streaming drain deadlocked on a full stderr pipe"
        stdout_lines = [ln for ln in box["out"].splitlines() if ln.startswith("line")]
        assert len(stdout_lines) == 5
        assert len(box["err"]) >= 200000
        assert len(feed.lines) == 5
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()
def test_low_level_launch_seam_checks_embargo_before_popen(monkeypatch):
    import importlib
    import pytest
    from agents.execution import executor_stream

    guard = importlib.import_module("platform_core.execution.launch_guard")
    popen = __import__("unittest").mock.Mock(side_effect=AssertionError("Popen reached"))
    monkeypatch.setattr(executor_stream.subprocess, "Popen", popen)
    with pytest.raises(guard.TransactionalKernelInactive):
        executor_stream._launchClaude(["claude", "--print"], ".", {}, 0)
    popen.assert_not_called()


def test_runclaude_and_provision_wiring_guard_before_any_input_or_backend_work():
    import importlib
    import pytest
    from agents.execution import executor
    from platform_core.execution import wiring
    guard = importlib.import_module("platform_core.execution.launch_guard")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(executor, "normalizeSpec", lambda value: (_ for _ in ()).throw(
            AssertionError("normalization reached")))
        with pytest.raises(guard.TransactionalKernelInactive):
            executor.runClaude({"prompt": "poison"})
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(wiring._env_router, "selectEnvironment", lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("selection reached")))
        with pytest.raises(guard.TransactionalKernelInactive):
            wiring.provisionForSubtask(None, {}, "poison")
