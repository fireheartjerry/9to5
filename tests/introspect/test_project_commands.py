"""Tests for introspect.project_commands: config-proven command detection."""
from __future__ import annotations

import json


def test_pyproject_pytest_detected(fixture_project):
    from introspect.project_commands import detectCommands

    cmds = detectCommands(fixture_project)
    hit = [c for c in cmds if c.kind == "test" and c.source == "pyproject.toml"]
    assert hit and hit[0].cmd == "python -m pytest"


def test_package_json_scripts(fixture_project):
    from introspect.project_commands import detectCommands

    (fixture_project / "package.json").write_text(
        json.dumps({"scripts": {"test": "jest", "lint": "eslint ."}}), encoding="utf-8"
    )
    cmds = detectCommands(fixture_project)
    kinds = {(c.kind, c.source) for c in cmds}
    assert ("test", "package.json") in kinds
    assert ("lint", "package.json") in kinds


def test_empty_dir_never_guesses(tmp_path):
    from introspect.project_commands import detectCommands

    empty = tmp_path / "empty"
    empty.mkdir()
    assert detectCommands(empty) == []


def test_every_command_has_source(fixture_project):
    from introspect.project_commands import detectCommands

    (fixture_project / "Makefile").write_text(
        "test:\n\tpytest\nbuild:\n\techo build\n", encoding="utf-8"
    )
    cmds = detectCommands(fixture_project)
    assert cmds and all(c.source for c in cmds)
    assert any(c.kind == "test" and c.cmd == "make test" and c.source == "Makefile" for c in cmds)


def test_pytest_ini_detected(tmp_path):
    from introspect.project_commands import detectCommands

    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    cmds = detectCommands(proj)
    assert any(c.kind == "test" and c.source == "pytest.ini" for c in cmds)


def test_cargo_and_go(tmp_path):
    from introspect.project_commands import detectCommands

    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "Cargo.toml").write_text('[package]\nname = "x"\n', encoding="utf-8")
    cmds = detectCommands(proj)
    assert any(c.kind == "test" and c.cmd == "cargo test" for c in cmds)
    assert any(c.kind == "build" and c.cmd == "cargo build" for c in cmds)

    proj2 = tmp_path / "g"
    proj2.mkdir()
    (proj2 / "go.mod").write_text("module example.com/x\n", encoding="utf-8")
    cmds2 = detectCommands(proj2)
    assert any(c.kind == "test" and c.cmd == "go test ./..." for c in cmds2)
