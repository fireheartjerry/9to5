"""Regression guard for the in-run Discord poller call sites.

`Orchestrator._translateDiscord(self, bus, state)` requires BOTH arguments. A
call that omits `state` raises TypeError at runtime; because the per-subtask
body is wrapped in `try/except Exception`, that TypeError is swallowed and the
subtask is force-marked crashed/failed *even when verification passed*. The bug
is invisible to ordinary tests (it lives deep in the live run loop), so we guard
it statically: parse orchestrator.py and assert every `self._translateDiscord`
call passes exactly two positional args.
"""
import ast
import pathlib
import unittest

_SRC = pathlib.Path(__file__).resolve().parent.parent / "orchestrator.py"


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
        self.tree = ast.parse(_SRC.read_text(encoding="utf-8"))

    def test_required_arity(self):
        calls = _translateDiscordCalls(self.tree)
        self.assertGreater(len(calls), 0, "expected at least one _translateDiscord call site")
        for call in calls:
            self.assertEqual(
                len(call.args), 2,
                f"_translateDiscord call at line {call.lineno} passes {len(call.args)} "
                f"positional arg(s); it requires (bus, state)")
            self.assertFalse(call.keywords, f"unexpected kwargs at line {call.lineno}")

    def test_signature_unchanged(self):
        """If the signature ever changes, this guard's arity assumption must be revisited."""
        func = next((n for n in ast.walk(self.tree)
                     if isinstance(n, ast.FunctionDef) and n.name == "_translateDiscord"), None)
        self.assertIsNotNone(func)
        names = [a.arg for a in func.args.args]
        self.assertEqual(names, ["self", "bus", "state"])
        self.assertFalse(func.args.defaults, "no defaults expected; both args are required")


if __name__ == "__main__":
    unittest.main()
