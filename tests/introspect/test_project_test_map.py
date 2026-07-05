"""Tests for introspect.project_test_map: convention-based file->test mapping."""
from __future__ import annotations


def test_exact_stem_match(fixture_project):
    from introspect.project_test_map import mapFileToTests

    hits = mapFileToTests(fixture_project, "pkg/core.py", ["tests/test_core.py"])
    assert hits == ["tests/test_core.py"]


def test_unknown_file_maps_to_nothing(fixture_project):
    from introspect.project_test_map import mapFileToTests

    assert mapFileToTests(fixture_project, "pkg/nowhere.py", ["tests/test_core.py"]) == []


def test_prefix_match_min_four_chars(fixture_project):
    from introspect.project_test_map import mapFileToTests

    # core_extra -> prefix "core" (4 chars) -> tests/test_core.py
    hits = mapFileToTests(fixture_project, "pkg/core_extra.py", ["tests/test_core.py"])
    assert hits == ["tests/test_core.py"]


def test_glob_fallback(fixture_project):
    from introspect.project_test_map import mapFileToTests

    test_files = ["tests/test_project_util.py"]
    hits = mapFileToTests(fixture_project, "pkg/util.py", test_files)
    assert hits == ["tests/test_project_util.py"]


def test_js_conventions(fixture_project):
    from introspect.project_test_map import mapFileToTests

    hits = mapFileToTests(fixture_project, "src/foo.js", ["src/foo.test.js"])
    assert hits == ["src/foo.test.js"]


def test_js_lookup_is_pure_no_filesystem_escape(fixture_project):
    """JS branch must consult ONLY caller-supplied test_files, never the live tree."""
    from introspect.project_test_map import mapFileToTests

    src = fixture_project / "src"
    src.mkdir()
    (src / "foo.js").write_text("export const a = 1;\n", encoding="utf-8")
    (src / "foo.test.js").write_text("test('a', () => {});\n", encoding="utf-8")
    # Sibling test exists on disk but is NOT in test_files -> must not be returned.
    assert mapFileToTests(fixture_project, "src/foo.js", []) == []
    assert mapFileToTests(fixture_project, "src/foo.js", ["other/x.test.js"]) == []


def test_overrides_checked_first(fixture_project):
    from introspect.project_test_map import mapFileToTests

    hits = mapFileToTests(
        fixture_project,
        "pkg/core.py",
        ["tests/test_core.py"],
        overrides={"pkg/core.py": ["tests/test_special.py"]},
    )
    assert hits == ["tests/test_special.py"]
