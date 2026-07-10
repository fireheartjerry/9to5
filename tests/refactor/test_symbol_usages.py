"""Tests for refactor.symbol_usages: AST Name/Attribute/ImportFrom usage scan."""
from __future__ import annotations


def test_find_usages(fixture_project):
    from developer_tools.refactoring.symbol_usages import findUsages

    hits = findUsages(fixture_project, "coreFunc")
    assert any(u.file == "tests/test_core.py" and u.kind == "import" for u in hits)


def test_find_usages_kinds(fixture_project):
    from developer_tools.refactoring.symbol_usages import Usage, findUsages

    (fixture_project / "pkg" / "caller.py").write_text(
        "import pkg.core\n\n\ndef call():\n    return pkg.core.coreFunc()\n",
        encoding="utf-8",
    )
    hits = findUsages(fixture_project, "coreFunc")
    assert Usage(file="pkg/caller.py", line=5, kind="attr") in hits
    # facade re-export is an ImportFrom usage
    assert any(u.file == "pkg/__init__.py" and u.kind == "import" for u in hits)


def test_find_usages_skips_excluded_dirs_and_sorted(fixture_project):
    from developer_tools.refactoring.symbol_usages import findUsages

    hidden = fixture_project / ".git" / "hook.py"
    hidden.write_text("coreFunc()\n", encoding="utf-8")
    hits = findUsages(fixture_project, "coreFunc")
    assert not any(".git" in u.file for u in hits)
    assert hits == sorted(hits, key=lambda u: (u.file, u.line, u.kind))


def test_find_usages_unknown_symbol_empty(fixture_project):
    from developer_tools.refactoring.symbol_usages import findUsages

    assert findUsages(fixture_project, "definitelyNotAName") == []


def test_find_usages_multi_matches_per_symbol_calls(fixture_project):
    from developer_tools.refactoring.symbol_usages import findUsages, findUsagesMulti

    symbols = {"coreFunc", "helper", "definitelyNotAName"}
    multi = findUsagesMulti(fixture_project, symbols)
    assert set(multi) == symbols
    for symbol in symbols:
        assert multi[symbol] == findUsages(fixture_project, symbol)
    assert multi["definitelyNotAName"] == []
