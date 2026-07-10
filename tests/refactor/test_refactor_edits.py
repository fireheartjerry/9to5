"""Tests for refactor.refactor_edits: edit primitives + path validation."""
from __future__ import annotations

from pathlib import Path


def test_validate_accepts_normal_relpaths(tmp_path):
    from developer_tools.refactoring.refactor_edits import (
        DeleteFile,
        RenameFile,
        ReplaceInFile,
        WriteFile,
        validateEdit,
    )

    assert validateEdit(tmp_path, WriteFile("pkg/new.py", "x = 1\n")) is None
    assert validateEdit(tmp_path, ReplaceInFile("pkg/core.py", "a", "b")) is None
    assert validateEdit(tmp_path, DeleteFile("pkg/old.py")) is None
    assert validateEdit(tmp_path, RenameFile("pkg/a.py", "pkg/b.py")) is None


def test_validate_rejects_escapes_and_absolute_outside(tmp_path):
    from developer_tools.refactoring.refactor_edits import DeleteFile, WriteFile, validateEdit

    assert validateEdit(tmp_path, WriteFile("../outside.py", "x")) is not None
    assert validateEdit(tmp_path, WriteFile("pkg/../../outside.py", "x")) is not None
    outside = Path(tmp_path).parent / "elsewhere" / "f.py"
    assert validateEdit(tmp_path, DeleteFile(str(outside))) is not None
    # absolute path INSIDE root is fine
    assert validateEdit(tmp_path, WriteFile(str(Path(tmp_path) / "in.py"), "x")) is None


def test_validate_rejects_forbidden_segments(tmp_path):
    from developer_tools.refactoring.refactor_edits import (
        FORBIDDEN_SEGMENTS,
        RenameFile,
        WriteFile,
        validateEdit,
    )

    assert ".git" in FORBIDDEN_SEGMENTS and ".env" in FORBIDDEN_SEGMENTS
    assert validateEdit(tmp_path, WriteFile(".git/hook", "x")) is not None
    assert validateEdit(tmp_path, WriteFile("venv/x.py", "x")) is not None
    assert validateEdit(tmp_path, WriteFile(".env", "SECRET=1")) is not None
    assert validateEdit(tmp_path, WriteFile("a/node_modules/b.js", "x")) is not None
    # rename TARGET is validated too
    assert validateEdit(tmp_path, RenameFile("ok.py", "__pycache__/bad.py")) is not None


def test_edit_dataclasses_frozen():
    import dataclasses

    import pytest

    from developer_tools.refactoring.refactor_edits import WriteFile

    edit = WriteFile("a.py", "x")
    assert dataclasses.is_dataclass(edit)
    with pytest.raises(dataclasses.FrozenInstanceError):
        edit.path = "b.py"
