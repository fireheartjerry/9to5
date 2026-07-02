"""Regression guard for the in-run Discord poller call sites.

`Orchestrator._translateDiscord(self, bus, state)` requires BOTH arguments. A
call that omits `state` raises TypeError at runtime; because the per-subtask
body is wrapped in `try/except Exception`, that TypeError is swallowed and the
subtask is force-marked crashed/failed *even when verification passed*. The bug
is invisible to ordinary tests (it lives deep in the live run loop), so we guard
it statically: parse orchestrator source files and assert every
`self._translateDiscord` call passes exactly two positional args.

NOTE: After the package split the definition and call sites live under
platform_core/orchestration/; we scan the facade plus package modules.
"""
import ast
import pathlib
import threading
import types
import unittest
from unittest import mock

_ROOT = pathlib.Path(__file__).resolve().parent.parent
# Scan all orchestrator source files (main + all mixin modules).
_SRCS = sorted([
    *_ROOT.glob("orchestrator*.py"),
    *(_ROOT / "platform_core" / "orchestration").glob("*.py"),
])


def _trees():
    """Yield (path, ast.Module) for every orchestrator source file."""
    for src in _SRCS:
        yield src, ast.parse(src.read_text(encoding="utf-8"))


def _translateDiscordCalls(tree: ast.AST) -> list[ast.Call]:
    calls = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_translateDiscord"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"):
            calls.append(node)
    return calls


class TestTranslateDiscordArity(unittest.TestCase):
    def setUp(self):
        self.all_trees = list(_trees())

    def test_required_arity(self):
        all_calls = []
        for src, tree in self.all_trees:
            for call in _translateDiscordCalls(tree):
                all_calls.append((src.name, call))
        self.assertGreater(len(all_calls), 0, "expected at least one _translateDiscord call site")
        for fname, call in all_calls:
            self.assertEqual(
                len(call.args), 2,
                f"_translateDiscord call in {fname}:{call.lineno} passes {len(call.args)} "
                f"positional arg(s); it requires (bus, state)")
            self.assertFalse(call.keywords, f"unexpected kwargs in {fname}:{call.lineno}")

    def test_signature_unchanged(self):
        """If the signature ever changes, this guard's arity assumption must be revisited."""
        func = None
        for _src, tree in self.all_trees:
            func = next((n for n in ast.walk(tree)
                         if isinstance(n, ast.FunctionDef) and n.name == "_translateDiscord"), None)
            if func:
                break
        self.assertIsNotNone(func)
        names = [a.arg for a in func.args.args]
        self.assertEqual(names, ["self", "bus", "state"])
        self.assertFalse(func.args.defaults, "no defaults expected; both args are required")


# ---------------------------------------------------------------------------
# R8 ingestion authority: the gateway bot OWNS Discord ingestion; the in-run
# REST poller engages ONLY while the bot is provably dead (heartbeat gating).
# ---------------------------------------------------------------------------
from platform_core.orchestration import control_mixin as cm  # noqa: E402
from platform_core.runtime.control import ControlBus  # noqa: E402


class _Host(cm.OrchestratorControlMixin):
    def __init__(self):
        self._poll_lock = threading.Lock()


def _state(tid="t-poll"):
    return types.SimpleNamespace(task_id=tid)


class TestPollerGating(unittest.TestCase):
    def test_bot_alive_means_zero_rest_calls(self):
        host = _Host()
        bus = ControlBus("t-poll")
        with mock.patch.object(cm.heartbeat, "isBotAlive", return_value=True), \
                mock.patch.object(cm.discord, "fetchMessagesAfter") as fetch:
            for _ in range(3):
                host._translateDiscord(bus, _state())
        fetch.assert_not_called()

    def test_bot_dead_engages_rest_poller(self):
        host = _Host()
        bus = ControlBus("t-poll2")
        with mock.patch.object(cm.heartbeat, "isBotAlive", return_value=False), \
                mock.patch.object(cm.discord, "fetchMessagesAfter",
                                  return_value=([], None)) as fetch:
            host._translateDiscord(bus, _state("t-poll2"))
        fetch.assert_called_once()

    def test_degraded_transition_logs_once_each_way(self):
        host = _Host()
        bus = ControlBus("t-poll3")
        alive = {"v": False}
        with mock.patch.object(cm.heartbeat, "isBotAlive", side_effect=lambda: alive["v"]), \
                mock.patch.object(cm.discord, "fetchMessagesAfter", return_value=([], None)), \
                mock.patch.object(cm, "LOG") as log:
            host._translateDiscord(bus, _state("t-poll3"))   # dead -> engage (warn once)
            host._translateDiscord(bus, _state("t-poll3"))   # still dead -> silent
            alive["v"] = True
            host._translateDiscord(bus, _state("t-poll3"))   # back -> disengage (info once)
            host._translateDiscord(bus, _state("t-poll3"))   # still alive -> silent
        self.assertEqual(log.warning.call_count, 1, "degraded-mode entry must log exactly once")
        self.assertEqual(log.info.call_count, 1, "recovery must log exactly once")

    def test_polled_message_carries_source_msg_id(self):
        """A '!' message ingested by the degraded poller must dedup against the SAME
        message id (e.g. the bot pushed it just before dying)."""
        host = _Host()
        bus = ControlBus("t-poll4")
        msg = {"id": "424242", "content": "!retry", "author_is_bot": False, "author_id": "7"}
        with mock.patch.object(cm.heartbeat, "isBotAlive", return_value=False), \
                mock.patch.object(cm.discord, "fetchMessagesAfter",
                                  return_value=([msg], "424242")), \
                mock.patch.object(cm.config, "DISCORD_HUMAN_USER_ID", "7"), \
                mock.patch.object(cm.audit, "record"):
            host._translateDiscord(bus, _state("t-poll4"))
            bus.setSeen(None)   # simulate a cursor rewind re-delivering the same message
            host._translateDiscord(bus, _state("t-poll4"))
        ops = bus.drainOps()
        self.assertEqual(len(ops), 1, "the same Discord message must queue exactly one op")
        self.assertEqual(ops[0]["op"], "retry")
