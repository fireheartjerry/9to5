"""Tests for SubprocessFeed -- the real-time Claude stdout tap."""

import json
import time

from notifications.event_bus import LiveEventBus
from notifications.subprocess_feed import SubprocessFeed


def _feed(bus):
    return SubprocessFeed(bus, "st-001", time.monotonic(), heartbeat=False)


def _last(bus):
    h = bus.history(last_n=9999)
    return h[-1] if h else None


def test_edit_tool_event():
    bus = LiveEventBus()
    f = _feed(bus)
    f.consume(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "a/b.py"}}]
                },
            }
        )
    )
    e = _last(bus)
    assert e["kind"] == "tool_use"
    assert "b.py" in e["text"] and "editing" in e["text"]


def test_write_and_read_and_grep_glob():
    bus = LiveEventBus()
    f = _feed(bus)
    f.consume(json.dumps({"type": "tool_use", "name": "Write", "input": {"file_path": "m.py"}}))
    assert "writing" in _last(bus)["text"]
    f.consume(json.dumps({"type": "tool_use", "name": "Read", "input": {"file_path": "c.py"}}))
    assert "reading" in _last(bus)["text"]
    f.consume(json.dumps({"type": "tool_use", "name": "Grep", "input": {"pattern": "foo"}}))
    assert "grep" in _last(bus)["text"] and "foo" in _last(bus)["text"]
    f.consume(json.dumps({"type": "tool_use", "name": "Glob", "input": {"pattern": "**/*.py"}}))
    assert "glob" in _last(bus)["text"]


def test_bash_truncated():
    bus = LiveEventBus()
    f = _feed(bus)
    f.consume(json.dumps({"type": "tool_use", "name": "Bash", "input": {"command": "x" * 200}}))
    e = _last(bus)
    assert e["text"].startswith("⚡ bash:")
    assert len(e["text"]) < 100  # command truncated to 70


def test_agent_spawn():
    bus = LiveEventBus()
    f = _feed(bus)
    f.consume(
        json.dumps(
            {"type": "tool_use", "name": "Task", "input": {"description": "research the thing deeply"}}
        )
    )
    assert "agent" in _last(bus)["text"]


def test_non_json_raw_only():
    bus = LiveEventBus()
    f = _feed(bus)
    before = len(bus.history(last_n=9999))
    f.consume("not json at all")
    assert len(bus.history(last_n=9999)) == before  # no structured event emitted
    assert bus.raw_history("st-001")[-1]["line"] == "not json at all"  # raw stored


def test_unknown_tool_generic():
    bus = LiveEventBus()
    f = _feed(bus)
    f.consume(json.dumps({"type": "tool_use", "name": "Frobnicate", "input": {}}))
    assert "Frobnicate" in _last(bus)["text"]


def test_every_line_stored_raw():
    bus = LiveEventBus()
    f = _feed(bus)
    f.consume(json.dumps({"type": "tool_use", "name": "Edit", "input": {"file_path": "z.py"}}))
    assert any("z.py" in r["line"] for r in bus.raw_history("st-001"))


def test_heartbeat_emits():
    bus = LiveEventBus()
    f = SubprocessFeed(bus, "st-001", time.monotonic() - 31, heartbeat=True)
    f.consume(json.dumps({"type": "tool_use", "name": "Edit", "input": {"file_path": "z.py"}}))
    f._beat_once()
    kinds = [e["kind"] for e in bus.history(last_n=9999)]
    assert "heartbeat" in kinds
    hb = next(e for e in bus.history(last_n=9999) if e["kind"] == "heartbeat")
    assert "still running" in hb["text"] and "tool calls" in hb["text"]
    f.stop()


def test_stop_is_idempotent():
    bus = LiveEventBus()
    f = SubprocessFeed(bus, "st-001", time.monotonic(), heartbeat=True)
    f.stop()
    f.stop()  # must not raise


def test_drain_streaming_taps_every_line():
    """The streaming drain path feeds each stdout line to the feed and joins them as `out`."""
    import io
    from agents import executor_stream

    lines = [
        json.dumps({"type": "tool_use", "name": "Edit", "input": {"file_path": "a.py"}}) + "\n",
        json.dumps({"type": "tool_use", "name": "Bash", "input": {"command": "pytest"}}) + "\n",
        "plain log line\n",
    ]

    class _FakeProc:
        args = ["claude"]

        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout = iter(lines)
            self.stderr = io.StringIO("")
            self.pid = 4321

        def wait(self, timeout=None):
            return 0

    bus = LiveEventBus()
    feed = SubprocessFeed(bus, "st-009", time.monotonic(), heartbeat=False)
    out, err = executor_stream._drainStreaming(_FakeProc(), "the prompt", feed, timeout=30)
    assert out == "".join(lines)
    assert err == ""
    texts = [e["text"] for e in bus.history(last_n=99) if e["kind"] == "tool_use"]
    assert any("a.py" in t for t in texts) and any("bash" in t for t in texts)
    # the non-JSON line is stored raw but not emitted as a structured event
    assert any("plain log line" in r["line"] for r in bus.raw_history("st-009"))


def test_on_step_callback_fires_with_parsed_event():
    bus = LiveEventBus()
    seen = []
    f = SubprocessFeed(
        bus,
        "st-002",
        time.monotonic(),
        heartbeat=False,
        on_step=lambda idx, tool, summary, inp: seen.append((idx, tool, inp)),
    )
    f.consume(json.dumps({"type": "tool_use", "name": "Edit", "input": {"file_path": "z.py"}}))
    f.consume(json.dumps({"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}))
    assert [s[0] for s in seen] == [0, 1]  # zero-based step_idx
    assert seen[0][1] == "Edit" and seen[0][2] == {"file_path": "z.py"}
    assert seen[1][1] == "Bash"


def test_on_step_none_is_unchanged_behavior():
    bus = LiveEventBus()
    f = SubprocessFeed(bus, "st-003", time.monotonic(), heartbeat=False)  # on_step defaults None
    f.consume(json.dumps({"type": "tool_use", "name": "Read", "input": {"file_path": "c.py"}}))
    assert "reading" in _last(bus)["text"]  # feed still works, no callback required


def test_on_step_sink_error_never_breaks_consume():
    bus = LiveEventBus()

    def _boom(*a, **k):
        raise RuntimeError("sink down")

    f = SubprocessFeed(bus, "st-004", time.monotonic(), heartbeat=False, on_step=_boom)
    f.consume(json.dumps({"type": "tool_use", "name": "Edit", "input": {"file_path": "z.py"}}))
    assert "editing" in _last(bus)["text"]  # raw/structured emit still happened
