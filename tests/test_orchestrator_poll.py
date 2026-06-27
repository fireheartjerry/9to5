"""Regression guard for the in-run Discord poller call sites.

`Orchestrator._translateDiscord(self, bus, state)` requires BOTH arguments. A
call that omits `state` raises TypeError at runtime; because the per-subtask
body is wrapped in `try/except Exception`, that TypeError is swallowed and the
subtask is force-marked crashed/failed *even when verification passed*. The bug
is invisible to ordinary tests (it lives deep in the live run loop), so we guard
it statically: parse all orchestrator*.py files and assert every
`self._translateDiscord` call passes exactly two positional args.

NOTE: After the mixin split the definition and call sites live in
orchestrator_control_mixin.py / orchestrator_run_mixin.py / orchestrator_execute_mixin.py;
we scan all orchestrator*.py files to cover the full surface.
"""
import ast
import pathlib
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
# Scan all orchestrator source files (main + all mixin modules).
_SRCS = sorted(_ROOT.glob("orchestrator*.py"))


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


if __name__ == "__main__":
    unittest.main()
