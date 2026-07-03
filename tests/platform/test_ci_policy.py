"""Policy tests for the GitHub Actions test workflow."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_test_workflow_keeps_merge_queue_and_fail_closed_test_brain_contract():
    text = _workflow_text()

    assert "merge_group:" in text
    assert "git rev-parse HEAD^" in text
    assert "affected_ok=false" in text
    assert "not-a-PR-or-unknown-change-set" in text


def test_test_workflow_publishes_test_brain_reports_and_matrix_output():
    text = _workflow_text()

    assert "testbrain_matrix:" in text
    assert 'testbrain_matrix={"include":[]}' in text
    assert "testbrain-reports" in text
    assert ".testbrain/reports/selection.md" in text
    assert ".testbrain/reports/history.md" in text
    assert ".testbrain/reports/mapping.md" in text
    assert "--mapping-fail-under 0.99" in text


def test_fast_gate_waits_for_smart_shards_without_skipping_full_fallback():
    text = _workflow_text()

    assert "smart-shards:" in text
    assert "strategy:" in text
    assert "matrix: ${{ fromJson(needs.classify.outputs.testbrain_matrix) }}" in text
    assert "needs: [classify, smart-shards]" in text
    assert "if: always() && needs.classify.outputs.core == 'true'" in text
    assert "smart lane delegated to smart-shards" in text
    assert "smart-shards result was" in text
    assert "full fast lane" in text
