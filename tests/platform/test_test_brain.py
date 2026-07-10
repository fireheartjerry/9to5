"""Tests for the history-aware test selector (tools/test_brain.py)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))
import test_brain  # noqa: E402
import test_brain_selection  # noqa: E402


def _write_history(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def test_changed_test_covers_itself_with_explanation(tmp_path):
    target = "tests/platform/test_test_brain.py"

    sel = test_brain.select_tests([target], REPO_ROOT, budget_seconds=60, history_dir=tmp_path)

    assert sel.ok is True
    assert target in sel.targets
    assert any("direct affected" in line for line in sel.explanations)


def test_sensitive_change_fails_closed(tmp_path):
    sel = test_brain.select_tests(["pytest.ini"], REPO_ROOT, budget_seconds=60, history_dir=tmp_path)

    assert sel.ok is False
    assert "sensitive" in sel.reason


def test_recent_failure_is_added_to_selection(tmp_path):
    history = tmp_path / "run.jsonl"
    _write_history(
        history,
        [
            {
                "nodeid": "tests/platform/test_ci_affected.py::test_recent_failure_probe",
                "outcome": "failed",
                "duration_seconds": 1.25,
                "timestamp": time.time(),
            },
        ],
    )

    sel = test_brain.select_tests(
        ["tests/platform/test_test_brain.py"], REPO_ROOT, budget_seconds=60, history_dir=tmp_path
    )

    assert sel.ok is True
    assert "tests/platform/test_ci_affected.py" in sel.targets
    assert "tests/platform/test_ci_affected.py" in sel.recent_failure_targets


def test_quarantined_recent_failure_is_not_added_unless_direct(tmp_path):
    history = tmp_path / "run.jsonl"
    _write_history(
        history,
        [
            {
                "nodeid": "tests/platform/test_ci_affected.py::test_recent_failure_probe",
                "outcome": "failed",
                "duration_seconds": 1.25,
                "timestamp": time.time(),
            },
        ],
    )
    quarantine = tmp_path / "quarantine.json"
    quarantine.write_text(json.dumps({"targets": ["tests/platform/test_ci_affected.py"]}), encoding="utf-8")

    sel = test_brain.select_tests(
        ["tests/platform/test_test_brain.py"],
        REPO_ROOT,
        budget_seconds=60,
        history_dir=tmp_path,
        quarantine_file=quarantine,
    )

    assert sel.ok is True
    assert "tests/platform/test_ci_affected.py" not in sel.targets
    assert "tests/platform/test_ci_affected.py" in sel.quarantined_targets


def test_domain_sentinel_adds_adjacent_contract_tests(tmp_path):
    sel = test_brain.select_tests(
        ["tests/platform/test_test_brain.py"], REPO_ROOT, budget_seconds=60, history_dir=tmp_path
    )
    assert sel.sentinel_targets == []

    sentinels = test_brain.sentinel_targets_for(["platform_core/runtime/control_store.py"])

    assert "tests/control/test_control_store.py" in sentinels


def test_selector_includes_domain_sentinels_when_direct_map_is_narrow(tmp_path, monkeypatch):
    monkeypatch.setattr(
        test_brain.affected_tests, "targets_for", lambda files: ["tests/platform/test_test_brain.py"]
    )

    sel = test_brain.select_tests(
        ["platform_core/runtime/control_store.py"], REPO_ROOT, budget_seconds=60, history_dir=tmp_path
    )

    assert sel.ok is True
    assert "tests/platform/test_test_brain.py" in sel.direct_targets
    assert "tests/control/test_control_store.py" in sel.sentinel_targets
    assert "tests/control/test_control_store.py" in sel.targets


def test_flake_candidates_need_mixed_results_and_enough_runs(tmp_path):
    history = tmp_path / "run.jsonl"
    _write_history(
        history,
        [
            {"nodeid": "tests/a.py::test_x", "outcome": "passed", "duration_seconds": 1, "timestamp": 1},
            {"nodeid": "tests/a.py::test_y", "outcome": "passed", "duration_seconds": 1, "timestamp": 2},
            {"nodeid": "tests/a.py::test_z", "outcome": "failed", "duration_seconds": 1, "timestamp": 3},
            {"nodeid": "tests/b.py::test_x", "outcome": "failed", "duration_seconds": 1, "timestamp": 4},
            {"nodeid": "tests/b.py::test_y", "outcome": "failed", "duration_seconds": 1, "timestamp": 5},
            {"nodeid": "tests/b.py::test_z", "outcome": "failed", "duration_seconds": 1, "timestamp": 6},
        ],
    )

    flakes = test_brain.flake_candidates(test_brain.load_stats(tmp_path))

    assert [f.target for f in flakes] == ["tests/a.py"]


def test_load_stats_dedupes_same_run_nodeid(tmp_path):
    history = tmp_path / "run.jsonl"
    _write_history(
        history,
        [
            {
                "run_id": "123",
                "nodeid": "tests/a.py::test_x",
                "outcome": "passed",
                "duration_seconds": 1,
                "timestamp": 1,
            },
            {
                "run_id": "123",
                "nodeid": "tests/a.py::test_x",
                "outcome": "passed",
                "duration_seconds": 1,
                "timestamp": 1,
            },
        ],
    )

    stats = test_brain.load_stats(tmp_path)

    assert stats["tests/a.py"].runs == 1
    assert stats["tests/a.py"].passes == 1


def test_budget_overflow_falls_back_but_reports_targets(tmp_path):
    history = tmp_path / "run.jsonl"
    _write_history(
        history,
        [
            {
                "nodeid": "tests/platform/test_test_brain.py::test_changed_test_covers_itself_with_explanation",
                "outcome": "passed",
                "duration_seconds": 100.0,
                "timestamp": time.time(),
            },
        ],
    )

    sel = test_brain.select_tests(
        ["tests/platform/test_test_brain.py"], REPO_ROOT, budget_seconds=1, history_dir=tmp_path
    )

    assert sel.ok is False
    assert "exceeds budget" in sel.reason
    assert "tests/platform/test_test_brain.py" in sel.targets


def test_selection_report_and_markdown_are_written(tmp_path):
    sel = test_brain.select_tests(
        ["tests/platform/test_test_brain.py"], REPO_ROOT, budget_seconds=60, history_dir=tmp_path
    )

    json_path, md_path = test_brain.write_reports(sel, tmp_path / "reports")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    md = md_path.read_text(encoding="utf-8")

    assert data["schema"] == 1
    assert data["ok"] is True
    assert "tests/platform/test_test_brain.py" in data["targets"]
    assert "# Test Brain Selection" in md
    assert "## Selected Targets" in md


def test_plan_shards_balances_by_duration():
    stats = {
        "tests/a.py": test_brain.TestStat("tests/a.py", runs=1, passes=1, total_duration=10),
        "tests/b.py": test_brain.TestStat("tests/b.py", runs=1, passes=1, total_duration=6),
        "tests/c.py": test_brain.TestStat("tests/c.py", runs=1, passes=1, total_duration=4),
        "tests/d.py": test_brain.TestStat("tests/d.py", runs=1, passes=1, total_duration=2),
    }

    shards = test_brain.plan_shards(
        ["tests/a.py", "tests/b.py", "tests/c.py", "tests/d.py"], stats, shard_count=2
    )

    assert len(shards) == 2
    assert shards[0]["targets"] == ["tests/a.py", "tests/d.py"]
    assert shards[1]["targets"] == ["tests/b.py", "tests/c.py"]
    assert test_brain.shard_report(shards)["max_estimated_seconds"] == 12.0


def test_write_reports_can_include_shard_artifacts(tmp_path):
    sel = test_brain.select_tests(
        ["tests/platform/test_test_brain.py"], REPO_ROOT, budget_seconds=60, history_dir=tmp_path
    )
    shards = test_brain.plan_shards(sel.targets, {}, 2)

    test_brain.write_reports(sel, tmp_path / "reports", shards)
    shard_json = json.loads((tmp_path / "reports" / "shards.json").read_text(encoding="utf-8"))
    shard_md = (tmp_path / "reports" / "shards.md").read_text(encoding="utf-8")
    selection_json = json.loads((tmp_path / "reports" / "selection.json").read_text(encoding="utf-8"))

    assert shard_json["shard_count"] == 2
    assert "shard_plan" in selection_json
    assert "## Shard Plan" in shard_md


def test_matrix_report_and_shard_selection_are_stable():
    stats = {
        "tests/a.py": test_brain.TestStat("tests/a.py", runs=1, passes=1, total_duration=10),
        "tests/b.py": test_brain.TestStat("tests/b.py", runs=1, passes=1, total_duration=2),
    }

    shards = test_brain.plan_shards(["tests/a.py", "tests/b.py"], stats, 2)
    matrix = test_brain.matrix_report(shards)

    assert matrix == {
        "include": [
            {
                "shard": 1,
                "estimated_seconds": 10.0,
                "targets": "tests/a.py",
                "has_targets": True,
            },
            {
                "shard": 2,
                "estimated_seconds": 2.0,
                "targets": "tests/b.py",
                "has_targets": True,
            },
        ],
    }
    assert test_brain._select_shard(shards, 2)["targets"] == ["tests/b.py"]


def test_history_report_lists_slowest_and_flakes(tmp_path):
    history = tmp_path / "run.jsonl"
    _write_history(
        history,
        [
            {"nodeid": "tests/a.py::test_x", "outcome": "passed", "duration_seconds": 10, "timestamp": 1},
            {"nodeid": "tests/a.py::test_y", "outcome": "failed", "duration_seconds": 8, "timestamp": 2},
            {"nodeid": "tests/a.py::test_z", "outcome": "passed", "duration_seconds": 6, "timestamp": 3},
            {"nodeid": "tests/b.py::test_x", "outcome": "passed", "duration_seconds": 1, "timestamp": 4},
        ],
    )

    report = test_brain.history_report(test_brain.load_stats(tmp_path), limit=5)
    md = test_brain.history_markdown(report)

    assert report["target_count"] == 2
    assert report["slowest"][0]["target"] == "tests/a.py"
    assert report["flake_candidates"][0]["target"] == "tests/a.py"
    assert "# Test Brain History" in md


def test_mapping_audit_reports_unmapped_sources(monkeypatch):
    monkeypatch.setattr(
        test_brain_selection,
        "_audit_source_files",
        lambda repo_root=test_brain.REPO_ROOT: ["tools/a.py", "notifications/discord_client.py"],
    )
    monkeypatch.setattr(
        test_brain.affected_tests,
        "targets_for",
        lambda files: ["tests/platform/test_a.py"] if files == ["tools/a.py"] else [],
    )

    report = test_brain.audit_mapping(REPO_ROOT)
    md = test_brain.mapping_markdown(report)

    assert report["total_files"] == 2
    assert report["mapped_files"] == 1
    assert report["unmapped_files"] == 1
    assert report["coverage"] == 0.5
    assert report["unmapped"][0]["file"] == "notifications/discord_client.py"
    assert report["unmapped"][0]["priority_label"] == "critical"
    assert "# Test Brain Mapping Audit" in md
    assert "### Critical" in md
    assert "`notifications/discord_client.py`" in md


def test_mapping_audit_fail_under_exits_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(
        test_brain,
        "audit_mapping",
        lambda repo_root: {
            "schema": 1,
            "total_files": 2,
            "mapped_files": 1,
            "unmapped_files": 1,
            "coverage": 0.5,
            "mapped": [],
            "unmapped": [{"file": "agents/b.py", "targets": []}],
        },
    )

    rc = test_brain.main(["--mapping-audit", "--mapping-fail-under", "0.75"])

    assert rc == 1
    assert "below 75.0%" in capsys.readouterr().err


def test_current_mapping_audit_has_no_critical_debt():
    report = test_brain.audit_mapping(REPO_ROOT)

    critical = [row["file"] for row in report["unmapped"] if row["priority_label"] == "critical"]
    assert critical == []


def test_optional_optimizer_keeps_required_and_uses_exact_budget_search():
    stats = {
        "tests/a.py": test_brain.TestStat("tests/a.py", runs=1, total_duration=4),
        "tests/b.py": test_brain.TestStat("tests/b.py", runs=1, total_duration=3, failures=1, last_failed=time.time()),
        "tests/c.py": test_brain.TestStat("tests/c.py", runs=1, total_duration=3),
    }

    picked = test_brain.optimize_optional_targets(["tests/a.py"], ["tests/b.py", "tests/c.py"], stats, 7)

    assert picked == ["tests/b.py"]
