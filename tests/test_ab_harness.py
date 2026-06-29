"""Tests for human_nature/ab_harness.py — Phase 5.5 A/B validation harness.

The autouse ``_isolate_ab_harness_db`` fixture (tests/conftest.py) redirects
every write to a per-test tmp DB, so tests never touch the real ab_runs.db.
"""
from __future__ import annotations

import pytest

from human_nature.ab_harness import compare, record_run


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _db(tmp_path):
    return tmp_path / "ab.db"


# ---------------------------------------------------------------------------
# record_run / invalid arm
# ---------------------------------------------------------------------------

class TestRecordRun:
    def test_invalid_arm_raises_valueerror(self, tmp_path):
        with pytest.raises(ValueError, match="invalid arm"):
            record_run("r1", "maybe", {"test_pass": 1.0}, db_path=_db(tmp_path))

    def test_invalid_arm_raises_before_any_write(self, tmp_path):
        db = _db(tmp_path)
        with pytest.raises(ValueError):
            record_run("r1", "both", {}, db_path=db)
        # DB may not even exist — if it does, it should be empty
        if db.exists():
            result = compare(db_path=db)
            assert result["n_on"] == 0 and result["n_off"] == 0

    def test_valid_arm_on_succeeds(self, tmp_path):
        record_run("r1", "on", {"test_pass": 0.9}, db_path=_db(tmp_path))
        assert compare(db_path=_db(tmp_path))["n_on"] == 1

    def test_valid_arm_off_succeeds(self, tmp_path):
        record_run("r1", "off", {"test_pass": 0.8}, db_path=_db(tmp_path))
        assert compare(db_path=_db(tmp_path))["n_off"] == 1

    def test_partial_metrics_allowed(self, tmp_path):
        """Missing metric keys should be stored as NULL (not raise)."""
        db = _db(tmp_path)
        record_run("r1", "on", {}, db_path=db)
        result = compare(db_path=db)
        assert result["n_on"] == 1
        assert result["on"]["test_pass"] is None

    def test_multiple_runs_same_arm(self, tmp_path):
        db = _db(tmp_path)
        for i in range(3):
            record_run(f"r{i}", "on", {"test_pass": float(i) / 2}, db_path=db)
        assert compare(db_path=db)["n_on"] == 3


# ---------------------------------------------------------------------------
# compare — per-arm averages + delta
# ---------------------------------------------------------------------------

class TestCompare:
    def test_empty_db_returns_none_averages(self, tmp_path):
        result = compare(db_path=_db(tmp_path))
        assert result["n_on"] == 0
        assert result["n_off"] == 0
        assert result["on"]["test_pass"] is None
        assert result["off"]["test_pass"] is None
        assert result["delta"]["test_pass"] is None

    def test_per_arm_averages_correct(self, tmp_path):
        db = _db(tmp_path)
        # ON arm: test_pass 0.8 and 1.0 → mean 0.9
        record_run("on-a", "on", {"test_pass": 0.8, "time_to_green": 100.0, "commit_quality": 0.7}, db_path=db)
        record_run("on-b", "on", {"test_pass": 1.0, "time_to_green": 200.0, "commit_quality": 0.9}, db_path=db)
        # OFF arm: test_pass 0.6 and 0.8 → mean 0.7
        record_run("off-a", "off", {"test_pass": 0.6, "time_to_green": 120.0, "commit_quality": 0.5}, db_path=db)
        record_run("off-b", "off", {"test_pass": 0.8, "time_to_green": 180.0, "commit_quality": 0.7}, db_path=db)

        result = compare(db_path=db)

        assert result["n_on"] == 2
        assert result["n_off"] == 2
        assert abs(result["on"]["test_pass"] - 0.9) < 1e-9
        assert abs(result["off"]["test_pass"] - 0.7) < 1e-9
        assert abs(result["on"]["time_to_green"] - 150.0) < 1e-9
        assert abs(result["off"]["time_to_green"] - 150.0) < 1e-9
        assert abs(result["on"]["commit_quality"] - 0.8) < 1e-9
        assert abs(result["off"]["commit_quality"] - 0.6) < 1e-9

    def test_delta_is_on_minus_off(self, tmp_path):
        db = _db(tmp_path)
        record_run("on-1", "on",  {"test_pass": 0.9}, db_path=db)
        record_run("off-1", "off", {"test_pass": 0.7}, db_path=db)

        result = compare(db_path=db)
        assert abs(result["delta"]["test_pass"] - 0.2) < 1e-9

    def test_delta_none_when_one_arm_missing(self, tmp_path):
        db = _db(tmp_path)
        record_run("on-1", "on", {"test_pass": 0.9}, db_path=db)
        # no OFF rows → delta should be None

        result = compare(db_path=db)
        assert result["delta"]["test_pass"] is None

    def test_delta_none_when_metric_all_null(self, tmp_path):
        db = _db(tmp_path)
        # Both arms exist but commit_quality is not recorded
        record_run("on-1",  "on",  {"test_pass": 0.8}, db_path=db)
        record_run("off-1", "off", {"test_pass": 0.7}, db_path=db)

        result = compare(db_path=db)
        assert result["delta"]["commit_quality"] is None

    def test_compare_result_keys(self, tmp_path):
        result = compare(db_path=_db(tmp_path))
        assert set(result.keys()) == {"on", "off", "delta", "n_on", "n_off"}
        for arm_key in ("on", "off", "delta"):
            assert set(result[arm_key].keys()) == {"test_pass", "time_to_green", "commit_quality"}

    def test_isolated_db_not_polluted_by_other_tests(self, tmp_path):
        """Each test gets its own tmp DB so data never leaks between tests."""
        result = compare(db_path=_db(tmp_path))
        assert result["n_on"] == 0
        assert result["n_off"] == 0

    def test_autouse_fixture_also_isolates(self):
        """config.AB_HARNESS_DB_PATH points at tmp so default-path calls are safe."""
        import config
        # The _isolate_ab_harness_db autouse fixture replaces the real path;
        # compare() with no db_path should be able to run without touching real state.
        result = compare()
        assert result["n_on"] == 0
        assert result["n_off"] == 0
