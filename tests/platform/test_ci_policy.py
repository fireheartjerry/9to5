"""Policy tests for the trusted self-hosted GitHub Actions workflow."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_uses_only_lean_trusted_triggers_and_runner():
    text = _workflow_text()

    assert "pull_request:" not in text
    assert "pull_request_target:" not in text
    assert "merge_group:" not in text
    assert "push:\n    branches: [main]" in text
    assert "workflow_dispatch:" in text
    assert "schedule:" in text
    assert "runs-on: [self-hosted, Windows, X64, 9to5-ci]" in text
    assert "contents: read" in text


def test_workflow_keeps_required_validation_and_capacity_schedule():
    text = _workflow_text()

    assert "python tools/repo_map.py --check" in text
    assert "python validate_workflows.py" in text
    assert "python tools/ci_schedule.py" in text
    assert "pytest -m \"not slow\"" in text
    assert "pytest -m slow" in text
    assert "python main.py --dry-run" in text
    assert "python main.py --e2e" in text
    assert "--mapping-fail-under 0.99" in text


def test_workflow_avoids_paid_hosted_cache_and_artifact_steps():
    text = _workflow_text()

    assert "actions/cache/" not in text
    assert "upload-artifact" not in text
    assert "download-artifact" not in text
    assert "enable-cache: false" in text
