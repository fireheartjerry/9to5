"""Tests for introspect.project_scanner: classification, exclusion, deterministic cap."""
from __future__ import annotations


def test_scanner_classifies_and_excludes(fixture_project):
    from introspect.project_scanner import scanProject

    mods = scanProject(fixture_project, max_files=100)
    paths = {m.path for m in mods}
    assert "pkg/core.py" in paths and "app.js" in paths
    assert not any(".git" in p or "__pycache__" in p for p in paths)
    js = next(m for m in mods if m.path == "app.js")
    assert js.lang == "javascript"


def test_scanner_truncates_deterministically(fixture_project):
    from introspect.project_scanner import scanProject

    a = scanProject(fixture_project, max_files=3)
    b = scanProject(fixture_project, max_files=3)
    assert [m.path for m in a] == [m.path for m in b] and len(a) == 3


def test_scanner_sorted_and_counts_loc(fixture_project):
    from introspect.project_scanner import scanProject

    mods = scanProject(fixture_project, max_files=100)
    paths = [m.path for m in mods]
    assert paths == sorted(paths)
    core = next(m for m in mods if m.path == "pkg/core.py")
    assert core.loc > 0
    assert core.lang == "python"
    # Skeletons only: graph fields are filled by the analyzer modules, not the scanner.
    assert core.exports == () and core.imports == ()
