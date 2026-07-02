"""Regression: with worktree isolation, remediation runs under parallelism (no shared-tree skip)."""
import config
from platform_core.orchestration.review_mixin import OrchestratorReviewMixin
from platform_core.runtime import worktree


class _G(OrchestratorReviewMixin):
    pass


def test_isolated_worktree_enables_remediation_under_parallelism(monkeypatch):
    g = _G()
    g._parallelism = 3
    monkeypatch.setattr(worktree, "isIsolated", lambda p: True)
    # The OLD code skipped here (parallelism>1); the residual guard now permits it.
    assert g._remediationUnsafe("/state/.sc-worktrees/x/st-002") is False
