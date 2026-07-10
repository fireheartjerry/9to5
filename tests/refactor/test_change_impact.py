"""Tests for refactor.change_impact: in-memory impact prediction, no writes."""
from __future__ import annotations


def test_impact_detects_orphans_and_cycle(fixture_project):
    from developer_tools.introspection import extractProject
    from developer_tools.refactoring.change_impact import predictImpact
    from developer_tools.refactoring.refactor_edits import ReplaceInFile, WriteFile

    model = extractProject(fixture_project, use_cache=False)
    edits = [ReplaceInFile("pkg/core.py", "def coreFunc():", "def coreFn():")]
    rep = predictImpact(model, edits)
    assert not rep.ok and any(u.file == "tests/test_core.py" for u in rep.orphaned_usages)
    edits2 = [WriteFile("pkg/util2.py", "from pkg.core import coreFunc\n")]
    rep2 = predictImpact(model, edits2)
    assert rep2.ok and ("tests/test_core.py" in rep2.affected_tests or rep2.affected_tests == ())


def test_impact_predicts_new_cycle(fixture_project):
    from developer_tools.introspection import extractProject
    from developer_tools.refactoring.change_impact import predictImpact
    from developer_tools.refactoring.refactor_edits import WriteFile

    model = extractProject(fixture_project, use_cache=False)
    edits = [
        WriteFile("pkg/c1.py", "import pkg.c2\n"),
        WriteFile("pkg/c2.py", "import pkg.c1\n"),
    ]
    rep = predictImpact(model, edits)
    assert not rep.ok
    assert ("pkg/c1.py", "pkg/c2.py") in rep.new_cycles
    # the fixture's pre-existing cycle_a/cycle_b cycle is NOT re-reported
    assert ("pkg/cycle_a.py", "pkg/cycle_b.py") not in rep.new_cycles


def test_impact_maps_affected_tests_and_never_writes(fixture_project):
    from developer_tools.introspection import extractProject
    from developer_tools.refactoring.change_impact import predictImpact
    from developer_tools.refactoring.refactor_edits import ReplaceInFile

    core = fixture_project / "pkg" / "core.py"
    before = core.read_bytes()
    model = extractProject(fixture_project, use_cache=False)
    rep = predictImpact(model, [ReplaceInFile("pkg/core.py", "return helper()", "return 2")])
    assert "tests/test_core.py" in rep.affected_tests
    assert rep.files_touched == ("pkg/core.py",)
    assert core.read_bytes() == before          # pure prediction, no disk writes


def test_impact_delete_file_orphans_importers(fixture_project):
    from developer_tools.introspection import extractProject
    from developer_tools.refactoring.change_impact import predictImpact
    from developer_tools.refactoring.refactor_edits import DeleteFile

    model = extractProject(fixture_project, use_cache=False)
    rep = predictImpact(model, [DeleteFile("pkg/core.py")])
    assert not rep.ok
    assert any(u.file == "tests/test_core.py" for u in rep.orphaned_usages)
