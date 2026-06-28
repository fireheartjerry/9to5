"""Unit tests for memory.experience_pr — record_pr_outcome and fetch_pr_outcomes."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path when run directly: python tests/test_experience_pr.py
sys.path.insert(0, str(Path(__file__).parent.parent))

import sqlite3
import tempfile
from contextlib import contextmanager
from unittest import mock

import pytest

import config
from memory.experience_pr import fetch_pr_outcomes, record_pr_outcome
from memory.experience_schema import _reset_schema_cache, init


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Isolated, schema-initialised DB; ledger enabled."""
    p = tmp_path / "pr_test.db"
    monkeypatch.setattr(config, "EXPERIENCE_DB_PATH", p, raising=False)
    monkeypatch.setattr(config, "EXPERIENCE_LEDGER_ENABLED", True, raising=False)
    init(p)
    yield p
    _reset_schema_cache()


# ---------------------------------------------------------------------------
# record_pr_outcome — happy path
# ---------------------------------------------------------------------------

def test_record_returns_true_on_success(db):
    ok = record_pr_outcome("run1", "https://github.com/org/repo/pull/1",
                           {"ci_status": "pass", "promote_safe": True}, db_path=db)
    assert ok is True


def test_record_row_stored(db):
    record_pr_outcome("run1", "https://github.com/org/repo/pull/1",
                      {"ci_status": "pass", "ci_summary": "all green",
                       "review_state": "approved", "promote_safe": True},
                      db_path=db)
    rows = fetch_pr_outcomes("run1", db_path=db)
    assert len(rows) == 1
    r = rows[0]
    assert r["run_id"] == "run1"
    assert r["pr_url"] == "https://github.com/org/repo/pull/1"
    assert r["ci_status"] == "pass"
    assert r["ci_summary"] == "all green"
    assert r["review_state"] == "approved"
    assert r["promote_safe"] == 1


def test_record_upserts_on_conflict(db):
    url = "https://github.com/org/repo/pull/2"
    record_pr_outcome("run1", url, {"ci_status": "fail", "promote_safe": False}, db_path=db)
    record_pr_outcome("run1", url, {"ci_status": "pass", "promote_safe": True}, db_path=db)
    rows = fetch_pr_outcomes("run1", db_path=db)
    assert len(rows) == 1
    assert rows[0]["ci_status"] == "pass"
    assert rows[0]["promote_safe"] == 1


def test_record_subtask_id_stored(db):
    record_pr_outcome("run1", "https://github.com/org/repo/pull/3",
                      {}, subtask_id="st-001", db_path=db)
    rows = fetch_pr_outcomes("run1", db_path=db)
    assert rows[0]["subtask_id"] == "st-001"


def test_record_subtask_id_merged_into_provenance(db):
    import json
    record_pr_outcome("run1", "https://github.com/org/repo/pull/4",
                      {"provenance": {"commit": "abc123"}},
                      subtask_id="st-007", db_path=db)
    rows = fetch_pr_outcomes("run1", db_path=db)
    prov = json.loads(rows[0]["provenance_json"])
    assert prov["subtask_id"] == "st-007"
    assert prov["commit"] == "abc123"


def test_record_existing_subtask_id_in_provenance_not_overwritten(db):
    import json
    record_pr_outcome("run1", "https://github.com/org/repo/pull/5",
                      {"provenance": {"subtask_id": "original"}},
                      subtask_id="different", db_path=db)
    rows = fetch_pr_outcomes("run1", db_path=db)
    prov = json.loads(rows[0]["provenance_json"])
    assert prov["subtask_id"] == "original"


def test_record_promote_safe_false_stored_as_zero(db):
    record_pr_outcome("run1", "https://github.com/org/repo/pull/6",
                      {"promote_safe": False}, db_path=db)
    rows = fetch_pr_outcomes("run1", db_path=db)
    assert rows[0]["promote_safe"] == 0


def test_record_promote_safe_none_stored_as_null(db):
    record_pr_outcome("run1", "https://github.com/org/repo/pull/7",
                      {}, db_path=db)
    rows = fetch_pr_outcomes("run1", db_path=db)
    assert rows[0]["promote_safe"] is None


def test_record_partial_result_missing_keys_are_null(db):
    record_pr_outcome("run1", "https://github.com/org/repo/pull/8",
                      {}, db_path=db)
    rows = fetch_pr_outcomes("run1", db_path=db)
    r = rows[0]
    assert r["ci_status"] is None
    assert r["ci_summary"] is None
    assert r["review_state"] is None
    assert r["review_feedback_json"] is None


# ---------------------------------------------------------------------------
# record_pr_outcome — guard / early-exit cases
# ---------------------------------------------------------------------------

def test_record_returns_false_when_ledger_disabled(db, monkeypatch):
    monkeypatch.setattr(config, "EXPERIENCE_LEDGER_ENABLED", False)
    ok = record_pr_outcome("run1", "https://github.com/org/repo/pull/9",
                           {}, db_path=db)
    assert ok is False
    assert fetch_pr_outcomes("run1", db_path=db) == []


def test_record_returns_false_for_blank_run_id(db):
    assert record_pr_outcome("", "https://github.com/org/repo/pull/10",
                             {}, db_path=db) is False


def test_record_returns_false_for_whitespace_run_id(db):
    assert record_pr_outcome("   ", "https://github.com/org/repo/pull/10",
                             {}, db_path=db) is False


def test_record_returns_false_for_none_run_id(db):
    assert record_pr_outcome(None, "https://github.com/org/repo/pull/10",
                             {}, db_path=db) is False


def test_record_returns_false_for_blank_pr_url(db):
    assert record_pr_outcome("run1", "", {}, db_path=db) is False


def test_record_returns_false_for_whitespace_pr_url(db):
    assert record_pr_outcome("run1", "   ", {}, db_path=db) is False


def test_record_returns_false_for_none_pr_url(db):
    assert record_pr_outcome("run1", None, {}, db_path=db) is False


# ---------------------------------------------------------------------------
# record_pr_outcome — DB error
# ---------------------------------------------------------------------------

def test_record_returns_false_on_db_error(monkeypatch):
    monkeypatch.setattr(config, "EXPERIENCE_LEDGER_ENABLED", True, raising=False)

    @contextmanager
    def _broken(_db_path=None):
        raise sqlite3.OperationalError("injected failure")
        yield  # noqa: unreachable

    monkeypatch.setattr("memory.experience_pr._connect", _broken)
    ok = record_pr_outcome("run1", "https://github.com/org/repo/pull/99",
                           {"ci_status": "pass"})
    assert ok is False


# ---------------------------------------------------------------------------
# fetch_pr_outcomes — queries
# ---------------------------------------------------------------------------

def test_fetch_empty_table(db):
    assert fetch_pr_outcomes(db_path=db) == []


def test_fetch_all_rows(db):
    for i in range(3):
        record_pr_outcome(f"run{i}", f"https://github.com/org/repo/pull/{i}",
                          {"promote_safe": True}, db_path=db)
    rows = fetch_pr_outcomes(db_path=db)
    assert len(rows) == 3


def test_fetch_filter_by_run_id(db):
    record_pr_outcome("run_a", "https://github.com/org/repo/pull/100",
                      {}, db_path=db)
    record_pr_outcome("run_b", "https://github.com/org/repo/pull/101",
                      {}, db_path=db)
    rows = fetch_pr_outcomes("run_a", db_path=db)
    assert len(rows) == 1
    assert rows[0]["run_id"] == "run_a"


def test_fetch_filter_promote_safe_true(db):
    record_pr_outcome("run1", "https://github.com/org/repo/pull/200",
                      {"promote_safe": True}, db_path=db)
    record_pr_outcome("run1", "https://github.com/org/repo/pull/201",
                      {"promote_safe": False}, db_path=db)
    record_pr_outcome("run1", "https://github.com/org/repo/pull/202",
                      {}, db_path=db)
    safe = fetch_pr_outcomes(promote_safe=True, db_path=db)
    assert all(r["promote_safe"] == 1 for r in safe)
    assert len(safe) == 1


def test_fetch_filter_promote_safe_false(db):
    record_pr_outcome("run1", "https://github.com/org/repo/pull/300",
                      {"promote_safe": True}, db_path=db)
    record_pr_outcome("run1", "https://github.com/org/repo/pull/301",
                      {"promote_safe": False}, db_path=db)
    unsafe = fetch_pr_outcomes(promote_safe=False, db_path=db)
    assert all(r["promote_safe"] == 0 for r in unsafe)
    assert len(unsafe) == 1


def test_fetch_filter_run_id_and_promote_safe(db):
    record_pr_outcome("run_x", "https://github.com/org/repo/pull/400",
                      {"promote_safe": True}, db_path=db)
    record_pr_outcome("run_x", "https://github.com/org/repo/pull/401",
                      {"promote_safe": False}, db_path=db)
    record_pr_outcome("run_y", "https://github.com/org/repo/pull/402",
                      {"promote_safe": True}, db_path=db)
    rows = fetch_pr_outcomes("run_x", promote_safe=True, db_path=db)
    assert len(rows) == 1
    assert rows[0]["pr_url"] == "https://github.com/org/repo/pull/400"


def test_fetch_limit(db):
    for i in range(5):
        record_pr_outcome(f"run{i}", f"https://github.com/org/repo/pull/{500 + i}",
                          {}, db_path=db)
    rows = fetch_pr_outcomes(limit=2, db_path=db)
    assert len(rows) == 2


def test_fetch_order_is_newest_first(db):
    record_pr_outcome("run1", "https://github.com/org/repo/pull/600",
                      {"ci_status": "first"}, db_path=db)
    record_pr_outcome("run1", "https://github.com/org/repo/pull/601",
                      {"ci_status": "second"}, db_path=db)
    rows = fetch_pr_outcomes("run1", db_path=db)
    assert rows[0]["ci_status"] == "second"


# ---------------------------------------------------------------------------
# fetch_pr_outcomes — DB error
# ---------------------------------------------------------------------------

def test_fetch_returns_empty_list_on_db_error(monkeypatch):
    @contextmanager
    def _broken(_db_path=None):
        raise sqlite3.OperationalError("injected failure")
        yield  # noqa: unreachable

    monkeypatch.setattr("memory.experience_pr._connect", _broken)
    result = fetch_pr_outcomes()
    assert result == []
