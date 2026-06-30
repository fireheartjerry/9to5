"""Parallel batch claims + isolates each subtask when WORKTREE_ISOLATION_ENABLED; the
residual guard only skips remediation on a SHARED tree under parallelism."""
import config
from platform_core.orchestration.review_mixin import OrchestratorReviewMixin
from platform_core.runtime import worktree


class _Guarded(OrchestratorReviewMixin):
    pass


def test_residual_guard_skips_only_shared_tree_under_parallelism(monkeypatch):
    g = _Guarded()
    g._parallelism = 2
    # Isolated worktree path -> remediation ALLOWED (the gate the epic removes).
    monkeypatch.setattr(worktree, "isIsolated", lambda p: True)
    assert g._remediationUnsafe("/state/.sc-worktrees/abc/st-001") is False
    # Shared tree under parallelism -> still unsafe (today's safety net when flag off).
    monkeypatch.setattr(worktree, "isIsolated", lambda p: False)
    assert g._remediationUnsafe("/shared/tree") is True


def test_residual_guard_safe_when_sequential(monkeypatch):
    g = _Guarded()
    g._parallelism = 1
    monkeypatch.setattr(worktree, "isIsolated", lambda p: False)
    assert g._remediationUnsafe("/shared/tree") is False   # no peers -> safe to snapshot/revert
