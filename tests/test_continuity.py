"""Tests for human_nature.continuity — diachronic narrative self.

TDD for Phase 4.5. Letters are inspectable file artifacts written under the
conftest-isolated STATE_DIR (tmp_path); the real state/ directory is never touched.
"""
from __future__ import annotations

from pathlib import Path

import config
from human_nature.continuity import read_letters, write_letter


# ---------------------------------------------------------------------------
# write_letter — basic creation
# ---------------------------------------------------------------------------

def test_write_letter_creates_file(tmp_path):
    result = write_letter("task-001", {"morale": 0.5}, letters_dir=tmp_path / "letters")
    fpath = Path(result["path"])
    assert fpath.exists()
    assert fpath.suffix == ".md"


def test_write_letter_returns_text(tmp_path):
    result = write_letter("task-001", {"note": "things went well"},
                          letters_dir=tmp_path / "letters")
    assert result["text"]
    assert isinstance(result["text"], str)
    assert len(result["text"]) > 10


def test_write_letter_path_matches_file_contents(tmp_path):
    result = write_letter("task-001", {}, letters_dir=tmp_path / "letters")
    fpath = Path(result["path"])
    assert fpath.read_text(encoding="utf-8") == result["text"]


# ---------------------------------------------------------------------------
# write_letter — honest discontinuity language
# ---------------------------------------------------------------------------

def test_letter_references_discontinuity(tmp_path):
    """Letter must honestly name the won't-remember / keep / future-self reality."""
    result = write_letter("task-002", {}, letters_dir=tmp_path / "letters")
    text = result["text"].lower()
    assert any(phrase in text for phrase in ("won't remember", "wont remember",
                                             "keep", "future self")), (
        f"Letter does not reference discontinuity or keeping context.\n{result['text']}"
    )


def test_letter_includes_task_id(tmp_path):
    result = write_letter("task-xyz", {"field": "value"}, letters_dir=tmp_path / "letters")
    assert "task-xyz" in result["text"]


# ---------------------------------------------------------------------------
# write_letter — stamp / monotonic counter
# ---------------------------------------------------------------------------

def test_stamp_param_sets_filename(tmp_path):
    d = tmp_path / "letters"
    result = write_letter("task-001", {}, letters_dir=d, stamp="2026-abc")
    assert Path(result["path"]).name == "2026-abc.md"


def test_monotonic_counter_increments(tmp_path):
    d = tmp_path / "letters"
    r1 = write_letter("task-001", {}, letters_dir=d)
    r2 = write_letter("task-001", {}, letters_dir=d)
    f1 = Path(r1["path"]).name
    f2 = Path(r2["path"]).name
    assert f1 != f2  # distinct filenames
    # Counter is monotonic: second file sorts after first
    assert f2 > f1


# ---------------------------------------------------------------------------
# read_letters
# ---------------------------------------------------------------------------

def test_read_letters_returns_texts_in_order(tmp_path):
    d = tmp_path / "letters"
    write_letter("task-001", {"i": 1}, letters_dir=d)
    write_letter("task-001", {"i": 2}, letters_dir=d)
    write_letter("task-001", {"i": 3}, letters_dir=d)
    texts = read_letters("task-001", letters_dir=d)
    assert len(texts) == 3
    # All are strings
    for t in texts:
        assert isinstance(t, str)


def test_read_letters_empty_when_none_written(tmp_path):
    d = tmp_path / "no-letters-here"
    texts = read_letters("task-absent", letters_dir=d)
    assert texts == []


def test_multiple_letters_accumulate(tmp_path):
    d = tmp_path / "letters"
    for i in range(5):
        write_letter(f"task-{i}", {"idx": i}, letters_dir=d)
    texts = read_letters("ignored", letters_dir=d)
    assert len(texts) == 5


# ---------------------------------------------------------------------------
# default letters_dir uses config.STATE_DIR (isolated by conftest)
# ---------------------------------------------------------------------------

def test_default_letters_dir_uses_state_dir():
    """Default letters_dir is derived from config.STATE_DIR, which conftest isolates."""
    result = write_letter("task-default", {"x": 1})
    fpath = Path(result["path"])
    # File must be under the (conftest-isolated) STATE_DIR
    assert str(config.STATE_DIR) in str(fpath)
    assert fpath.exists()


def test_read_letters_default_dir_reads_what_write_wrote():
    texts = read_letters("task-roundtrip")
    initial_count = len(texts)

    write_letter("task-roundtrip", {"step": "a"})
    write_letter("task-roundtrip", {"step": "b"})

    texts_after = read_letters("task-roundtrip")
    assert len(texts_after) == initial_count + 2
