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


def test_scanner_prunes_gitignored_dirs(fixture_project):
    """Simple .gitignore dir patterns (bare name + nested relpath) prune like EXCLUDE_DIRS;
    wildcard/negation lines are ignored (honest subset)."""
    from introspect.project_scanner import scanProject

    (fixture_project / ".gitignore").write_text(
        "# comment\nbigvendor/\nlogs\nnested/runtime/\n*.tmp\n!keep.py\n", encoding="utf-8")
    for rel in ("bigvendor/mod.py", "logs/log.py", "nested/runtime/x.py", "nested/kept.py"):
        p = fixture_project / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("X = 1\n", encoding="utf-8")
    paths = {m.path for m in scanProject(fixture_project, max_files=200)}
    assert "nested/kept.py" in paths                      # sibling of pruned relpath survives
    assert not any(p.startswith(("bigvendor/", "logs/", "nested/runtime/")) for p in paths)


def test_scanner_no_gitignore_is_fine(tmp_path):
    from introspect.project_scanner import scanProject

    (tmp_path / "a.py").write_text("A = 1\n", encoding="utf-8")
    assert [m.path for m in scanProject(tmp_path)] == ["a.py"]
