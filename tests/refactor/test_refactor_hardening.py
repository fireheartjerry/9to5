"""Tests for refactor hardening: rename guard, gate cmd forms, crash journal, aliasing."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def test_rename_onto_existing_target_rejected(fixture_project):
    from refactor import RefactorTransaction, RenameFile

    src_before = (fixture_project / "app.js").read_bytes()
    dst_before = (fixture_project / "lib.js").read_bytes()
    tx = RefactorTransaction(fixture_project)
    tx.add(RenameFile("app.js", "lib.js"))
    res = tx.apply(check_cycles=False)
    assert not res.applied
    assert "rename target exists: lib.js" in res.reason
    assert (fixture_project / "app.js").read_bytes() == src_before
    assert (fixture_project / "lib.js").read_bytes() == dst_before


def test_split_gate_cmd_preserves_windows_paths():
    from refactor.refactor_transaction import _splitGateCmd

    parts = _splitGateCmd(r"python C:\tools\gate.py --strict")
    if os.name == "nt":
        assert parts == ["python", r"C:\tools\gate.py", "--strict"]
    else:
        assert parts[0] == "python" and len(parts) == 3
    argv = ["python", "-c", "import sys; sys.exit(0)"]
    assert _splitGateCmd(argv) == argv


def test_gate_cmd_str_form_still_supported(fixture_project):
    from refactor import RefactorTransaction, WriteFile

    tx = RefactorTransaction(fixture_project)
    tx.add(WriteFile("pkg/extra.py", "VALUE = 1\n"))
    res = tx.apply(gate_cmd="python -V", check_cycles=False)
    assert res.applied, res.reason


def test_gate_timeout_rolls_back(fixture_project):
    from refactor import RefactorTransaction, WriteFile

    tx = RefactorTransaction(fixture_project)
    tx.add(WriteFile("pkg/extra.py", "VALUE = 1\n"))
    res = tx.apply(
        gate_cmd=[sys.executable, "-c", "import time; time.sleep(5)"],
        check_cycles=False,
        timeout_s=1,
    )
    assert not res.applied and "timed out" in res.reason
    assert not (fixture_project / "pkg" / "extra.py").exists()


def test_crash_journal_recovery(fixture_project):
    from refactor import RefactorTransaction, ReplaceInFile, WriteFile, recoverJournal
    from refactor.refactor_edits import editPaths
    from refactor.refactor_journal import writeJournal

    core = fixture_project / "pkg" / "core.py"
    before = core.read_bytes()
    tx = RefactorTransaction(fixture_project)
    tx.add(ReplaceInFile("pkg/core.py", "def coreFunc():", "def coreFunc():  # crashed"))
    tx.add(WriteFile("pkg/new_mod.py", "VALUE = 1\n"))
    assert tx._validateAll() is None
    touched = sorted({tx._norm(p) for e in tx.edits for p in editPaths(e)})
    journal_dir = writeJournal(tx.root, tx._snapshot(touched))
    tx._writeAll([])                       # simulated crash: writes done, no gate/rollback
    assert core.read_bytes() != before
    res = recoverJournal(journal_dir)
    assert not res.applied and "recovered" in res.reason
    assert core.read_bytes() == before                      # byte-identical restore
    assert not (fixture_project / "pkg" / "new_mod.py").exists()
    assert not Path(journal_dir).exists()                   # journal cleaned after recovery


def test_path_aliasing_same_file_in_one_tx(fixture_project):
    from refactor import RefactorTransaction, ReplaceInFile, WriteFile

    tx = RefactorTransaction(fixture_project)
    tx.add(WriteFile("./a.py", "VALUE = 1\n"))
    tx.add(ReplaceInFile("a.py", "VALUE = 1", "VALUE = 2"))
    res = tx.apply(check_cycles=False)
    assert res.applied, res.reason
    assert (fixture_project / "a.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert res.files_touched == ("a.py",)


def test_rollback_removes_created_dirs(fixture_project):
    from refactor import RefactorTransaction, WriteFile

    tx = RefactorTransaction(fixture_project)
    tx.add(WriteFile("newdir/sub/broken.py", "def x(:\n"))  # compile gate must fail
    res = tx.apply(check_cycles=False)
    assert not res.applied
    assert not (fixture_project / "newdir").exists()        # tx-created dirs removed


def test_same_file_double_edit_applies_in_order(fixture_project):
    from refactor import RefactorTransaction, ReplaceInFile

    tx = RefactorTransaction(fixture_project)
    tx.add(ReplaceInFile("pkg/core.py", "def coreFunc():", "def coreFunc():  # one"))
    tx.add(ReplaceInFile("pkg/core.py", "# one", "# one  # two"))
    res = tx.apply(check_cycles=False)
    assert res.applied, res.reason
    text = (fixture_project / "pkg" / "core.py").read_text(encoding="utf-8")
    assert "# one  # two" in text
    assert res.files_touched == ("pkg/core.py",)


def test_replace_in_latin1_file_applies(fixture_project):
    from refactor import RefactorTransaction, ReplaceInFile

    legacy = fixture_project / "pkg" / "legacy.py"
    legacy.write_bytes("# -*- coding: latin-1 -*-\n# caf\xe9\nVALUE = 1\n".encode("latin-1"))
    tx = RefactorTransaction(fixture_project)
    tx.add(ReplaceInFile("pkg/legacy.py", "VALUE = 1", "VALUE = 2"))
    res = tx.apply(check_cycles=False)
    # Pinned behavior: replacement is byte-level and the latin-1 coding
    # declaration keeps py_compile happy, so the apply SUCCEEDS.
    assert res.applied, res.reason
    raw = legacy.read_bytes()
    assert b"VALUE = 2" in raw and b"\xe9" in raw           # non-UTF-8 byte preserved
