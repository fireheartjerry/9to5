"""Drift + layering guards for the AI-navigation layer (tools/repo_map.py).

- ``test_no_drift``: the committed `.repo-map.json` / `AGENTS.md` / adopted AI-MAP headers must
  match what the generator produces right now. If a module/export/dep changed without regenerating,
  this FAILS loudly with the exact fix (`python tools/repo_map.py`). This is what keeps the index
  honest -- a stale map is worse than none.
- ``test_no_load_time_import_cycles`` / ``test_leaves_do_not_import_orchestrator``: the layering
  guard. Lazy (in-function) imports are the deliberate cycle-break escape hatch, so these check the
  LOAD-TIME graph only. Keeps the module graph clean (and the Phase-3 splits honest).
- ``TestSpliceSafety`` / ``TestTestsExcluded``: the 2026-07 safety-net regressions -- header
  splicing must never corrupt a non-ASCII multi-line docstring, and must never touch test trees.

Runs under pytest (the pytest-only conftest sandbox). Skips only if the tool can't be imported.
"""
import sys
import unittest
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
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
        self.assertEqual(rc, 0, "repo-map / AGENTS.md / AI-MAP headers are STALE. "
                                "Run:  python tools/repo_map.py")


@unittest.skipIf(repo_map is None, "tools/repo_map.py not importable")
class TestSpliceSafety(unittest.TestCase):
    """Regression for the docstring-splice corruption that broke 5 committed test files:
    AST col_offsets are UTF-8 BYTE offsets, so a non-ASCII (em-dash) docstring made the old
    char-offset math overshoot and eat the first bytes after the closing quotes
    (`\"\"\"mport ...`), producing files that no longer compile."""

    _HEADER = "@AI-MAP v1  (test)\nEXPORTS:\n  foo() -- does a thing\nDEPENDS-ON: (stdlib only)"

    def _assert_round_trips(self, src: str) -> str:
        compile(src, "<synthetic-in>", "exec")  # precondition: input compiles
        out = repo_map.splice_header(src, self._HEADER)
        self.assertIsNotNone(out, "splice returned None for a module that HAS a docstring")
        compile(out, "<synthetic-out>", "exec")  # the whole point: output still compiles
        self.assertIn("@AI-MAP v1", out)
        return out

    def test_multiline_ascii_docstring_compiles(self):
        src = '"""Line one.\n\nLine two of the prose.\n"""\nimport sys\n\n\ndef foo():\n    return sys\n'
        out = self._assert_round_trips(src)
        self.assertIn("import sys", out)

    def test_multiline_non_ascii_docstring_compiles(self):
        # The exact shape that corrupted the suite: an em-dash before the import line.
        src = '"""Task 4.3 — reflection.trust() rejects stub anchors.\n\nSecond — line.\n"""\nimport unittest\n\n\ndef foo():\n    return unittest\n'
        out = self._assert_round_trips(src)
        self.assertIn("\nimport unittest", out)  # the char after the docstring must survive intact

    def test_replaces_prior_header_without_growth(self):
        src = ('"""Prose here.\n\n@AI-MAP v1  (old)\nEXPORTS:\n  (none)\nDEPENDS-ON: (stdlib only)\n"""\n'
               'import os\n')
        out = self._assert_round_trips(src)
        self.assertEqual(out.count("@AI-MAP v1"), 1, "a re-splice must not stack headers")
        self.assertIn("import os", out)

    def test_no_docstring_returns_none(self):
        self.assertIsNone(repo_map.splice_header("import sys\n", self._HEADER))


@unittest.skipIf(repo_map is None, "tools/repo_map.py not importable")
class TestTestsExcluded(unittest.TestCase):
    """The test trees are never mapped and never spliced -- headers there are pure noise and a
    bad splice corrupts the suite. Guards the exclusion + splice-run idempotency."""

    def test_is_test_path_covers_test_trees(self):
        self.assertTrue(repo_map.is_test_path(REPO_ROOT / "tests" / "test_x.py"))
        self.assertTrue(repo_map.is_test_path(REPO_ROOT / "testing" / "e2e.py"))
        self.assertFalse(repo_map.is_test_path(REPO_ROOT / "agents" / "executor.py"))

    def test_map_has_no_test_modules(self):
        m = repo_map.build_map()
        offenders = [k for k, r in m["modules"].items()
                     if r["path"].split("/")[0] in ("tests", "testing")]
        self.assertEqual(offenders, [], f"test modules leaked into the map: {offenders}")

    def test_check_run_never_flags_a_test_file(self):
        # A --check pass must never report a tests/ file as drift (it is out of scope entirely).
        this = Path(__file__)
        before = this.read_bytes()
        repo_map.write_outputs(check=True, only=None, no_headers=False)
        self.assertEqual(this.read_bytes(), before, "check mode mutated a test file")


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


@pytest.mark.skipif(repo_map is None, reason="tools/repo_map.py not importable")
class TestFindTestsRecursive:
    def test_finds_test_in_subdirectory(self, tmp_path, monkeypatch):
        tests_dir = tmp_path / "tests"
        (tests_dir / "somedomain").mkdir(parents=True)
        (tests_dir / "somedomain" / "test_widget.py").write_text("def test_x():\n    pass\n")
        monkeypatch.setattr(repo_map, "TESTS_DIR", tests_dir)
        assert repo_map.find_tests("agents.widget", "widget") == ["tests/somedomain/test_widget.py"]

    def test_glob_fallback_is_recursive(self, tmp_path, monkeypatch):
        tests_dir = tmp_path / "tests"
        (tests_dir / "d").mkdir(parents=True)
        (tests_dir / "d" / "test_widget_extra.py").write_text("def test_x():\n    pass\n")
        monkeypatch.setattr(repo_map, "TESTS_DIR", tests_dir)
        assert repo_map.find_tests("agents.widget", "widget") == ["tests/d/test_widget_extra.py"]
