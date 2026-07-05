"""Tests for refactor.refactor_transaction: all-or-nothing apply with rollback."""
from __future__ import annotations

import pytest


def test_apply_all_or_nothing_rollback(fixture_project):
    from refactor import RefactorTransaction, ReplaceInFile, WriteFile

    unrelated = fixture_project / "scratch.txt"
    unrelated.write_text("dirty", encoding="utf-8")
    before = (fixture_project / "pkg/core.py").read_bytes()
    tx = RefactorTransaction(fixture_project)
    tx.add(ReplaceInFile("pkg/core.py", "def coreFunc():", "def coreFunc():  # touched"))
    tx.add(WriteFile("pkg/broken.py", "def x(:\n"))               # syntax error -> gate must fail
    res = tx.apply()
    assert not res.applied and "broken.py" in res.reason + res.gate_output
    assert (fixture_project / "pkg/core.py").read_bytes() == before      # byte-identical restore
    assert not (fixture_project / "pkg/broken.py").exists()              # created file removed
    assert unrelated.read_text(encoding="utf-8") == "dirty"              # unrelated file untouched


def test_apply_success_and_gate_cmd(fixture_project):
    from refactor import RefactorTransaction, WriteFile

    tx = RefactorTransaction(fixture_project)
    tx.add(WriteFile("pkg/extra.py", "VALUE = 1\n"))
    res = tx.apply(gate_cmd='python -c "import sys; sys.exit(0)"')   # shlex-split, no shell
    assert res.applied and "pkg/extra.py" in res.files_touched
    assert (fixture_project / "pkg/extra.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_gate_cmd_failure_rolls_back(fixture_project):
    from refactor import RefactorTransaction, WriteFile

    tx = RefactorTransaction(fixture_project)
    tx.add(WriteFile("pkg/extra.py", "VALUE = 1\n"))
    res = tx.apply(gate_cmd='python -c "import sys; sys.exit(3)"')
    assert not res.applied
    assert not (fixture_project / "pkg/extra.py").exists()


def test_replace_must_match_once(fixture_project):
    from refactor import RefactorTransaction, ReplaceInFile

    tx = RefactorTransaction(fixture_project)
    tx.add(ReplaceInFile("pkg/core.py", "NO_SUCH_TEXT", "x"))
    res = tx.apply()
    assert not res.applied and "match" in res.reason.lower()


def test_replace_rejects_multiple_matches(fixture_project):
    from refactor import RefactorTransaction, ReplaceInFile

    (fixture_project / "pkg" / "dup.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    tx = RefactorTransaction(fixture_project)
    tx.add(ReplaceInFile("pkg/dup.py", "x = 1\n", "x = 2\n"))
    res = tx.apply()
    assert not res.applied and "match" in res.reason.lower()


def test_new_cycle_blocked(fixture_project):
    from refactor import RefactorTransaction, WriteFile

    tx = RefactorTransaction(fixture_project)
    tx.add(WriteFile("pkg/c1.py", "import pkg.c2\n"))
    tx.add(WriteFile("pkg/c2.py", "import pkg.c1\n"))
    res = tx.apply()
    assert not res.applied and "cycle" in res.reason.lower()
    assert not (fixture_project / "pkg/c1.py").exists()
    # NOTE: fixture already contains cycle_a/cycle_b -- pre-existing cycles alone
    # must NOT block an unrelated edit:
    tx2 = RefactorTransaction(fixture_project)
    tx2.add(WriteFile("pkg/safe.py", "VALUE = 2\n"))
    assert tx2.apply().applied


def test_add_rejects_invalid_edit(fixture_project):
    from refactor import RefactorTransaction, WriteFile

    tx = RefactorTransaction(fixture_project)
    with pytest.raises(ValueError):
        tx.add(WriteFile(".git/hook", "x"))
    with pytest.raises(ValueError):
        tx.add(WriteFile("../escape.py", "x"))


def test_rename_and_delete_roundtrip(fixture_project):
    from refactor import DeleteFile, RefactorTransaction, RenameFile

    tx = RefactorTransaction(fixture_project)
    tx.add(RenameFile("lib.js", "lib2.js"))
    tx.add(DeleteFile("app.js"))
    res = tx.apply(check_cycles=False)
    assert res.applied
    assert not (fixture_project / "lib.js").exists()
    assert (fixture_project / "lib2.js").read_text(encoding="utf-8") == "export const x = 1;\n"
    assert not (fixture_project / "app.js").exists()


def test_preview_uses_impact_report(fixture_project):
    from refactor import RefactorTransaction, ReplaceInFile

    tx = RefactorTransaction(fixture_project)
    tx.add(ReplaceInFile("pkg/core.py", "def coreFunc():", "def coreFn():"))
    rep = tx.preview()
    assert not rep.ok
    assert rep.files_touched == ("pkg/core.py",)
    # preview never writes
    assert "coreFunc" in (fixture_project / "pkg/core.py").read_text(encoding="utf-8")


def test_cli_check_reports_cycles(fixture_project, capsys):
    from refactor.__main__ import main

    rc = main(["check", str(fixture_project)])
    out = capsys.readouterr().out
    assert rc == 1                                  # fixture has a deliberate cycle
    assert "cycle" in out.lower() and "modules" in out.lower()
