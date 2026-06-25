"""Drift + layering guards for the AI-navigation layer (tools/repo_map.py).

- ``test_no_drift``: the committed `.repo-map.json` / `AGENTS.md` / adopted `@AI-MAP` headers must
  match what the generator produces right now. If a module/export/dep changed without regenerating,
  this FAILS loudly with the exact fix (`python tools/repo_map.py`). This is what keeps the index
  honest -- a stale map is worse than none.
- ``test_no_load_time_import_cycles`` / ``test_leaves_do_not_import_orchestrator``: the layering
  guard. Lazy (in-function) imports are the deliberate cycle-break escape hatch, so these check the
  LOAD-TIME graph only. Keeps the module graph clean (and the Phase-3 splits honest).

Runs under both `unittest discover` and pytest. Skips only if the tool can't be imported.
"""
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

try:
    import repo_map  # noqa: E402  (path injected above)
except Exception:  # noqa: BLE001 -- old/partial checkout: skip rather than error
    repo_map = None


@unittest.skipIf(repo_map is None, "tools/repo_map.py not importable")
class TestRepoMapDrift(unittest.TestCase):
    def test_no_drift(self):
        """Committed artifacts + adopted headers are current. Fix: python tools/repo_map.py"""
        rc = repo_map.write_outputs(check=True, only=None, no_headers=False)
        self.assertEqual(rc, 0, "repo-map / AGENTS.md / @AI-MAP headers are STALE. "
                                "Run:  python tools/repo_map.py")


@unittest.skipIf(repo_map is None, "tools/repo_map.py not importable")
class TestLayering(unittest.TestCase):
    def _graph(self):
        # dotted -> set of first-party modules imported at load time
        g = repo_map.toplevel_import_graph()
        # Normalize 'agents.executor' edges to the module key space (keys are dotted modules).
        keys = set(g)
        return {m: {d for d in deps if d in keys} for m, deps in g.items()}

    def test_no_load_time_import_cycles(self):
        graph = self._graph()
        WHITE, GREY, BLACK = 0, 1, 2
        color = {m: WHITE for m in graph}
        cycle: list[str] = []

        def visit(m, stack):
            color[m] = GREY
            for d in sorted(graph.get(m, ())):
                if color.get(d, BLACK) == GREY:
                    i = stack.index(d)
                    cycle.extend(stack[i:] + [d])
                    return True
                if color.get(d, BLACK) == WHITE and visit(d, stack + [d]):
                    return True
            color[m] = BLACK
            return False

        for m in sorted(graph):
            if color[m] == WHITE and visit(m, [m]):
                break
        self.assertFalse(cycle, f"Load-time import cycle: {' -> '.join(cycle)}")

    def test_orchestrator_deps_have_no_backedge(self):
        """Modules orchestrator depends on must NOT import orchestrator at load time (the back-edge
        that would create a cycle). Higher-layer importers (main, simulation, tests) are allowed."""
        graph = self._graph()
        deps = graph.get("orchestrator", set())
        offenders = sorted(d for d in deps if "orchestrator" in graph.get(d, set()))
        self.assertFalse(offenders, f"orchestrator dependencies that back-import orchestrator: {offenders}")


if __name__ == "__main__":
    unittest.main()
