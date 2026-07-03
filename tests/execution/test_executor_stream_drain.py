"""Streaming drain must read stderr concurrently, not after stdout EOF (B9).

A child that fills the ~64KB stderr pipe buffer before stdout EOF deadlocks the old
"read stderr after the stdout loop" code. The concurrent stderr drain thread fixes it.
"""
from __future__ import annotations

import subprocess
import sys
import threading

import pytest

from agents import executor_stream


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
    worker.start()
    worker.join(timeout=30)

    assert not worker.is_alive(), "streaming drain deadlocked on a full stderr pipe"
    stdout_lines = [ln for ln in box["out"].splitlines() if ln.startswith("line")]
    assert len(stdout_lines) == 5
    assert len(box["err"]) >= 200000
    assert len(feed.lines) == 5


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
