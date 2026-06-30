"""The seam degrades fail-open when Epic 1/2 modules are absent."""
from platform_core.orchestration import fork_seams as fs


def test_headline_constants():
    assert fs.VERIFIED == "VERIFIED"
    assert fs.VERIFIED_WITH_GAPS == "VERIFIED_WITH_GAPS"
    assert fs.NOT_VERIFIED == "NOT_VERIFIED"


def test_headline_from_branch_uses_receipt_when_present():
    class R:
        headline = fs.VERIFIED
    assert fs.headlineFromBranch(False, R()) == fs.VERIFIED   # receipt wins over passed flag


def test_headline_from_branch_uses_dict_receipt():
    # Real Epic 2 buildReceipt returns a dict -> headline read by key.
    assert fs.headlineFromBranch(False, {"headline": fs.VERIFIED}) == fs.VERIFIED


def test_headline_from_branch_degrades_to_facts_only():
    assert fs.headlineFromBranch(True, None) == fs.VERIFIED_WITH_GAPS
    assert fs.headlineFromBranch(False, None) == fs.NOT_VERIFIED


def test_null_worktree_is_not_isolated():
    wt = fs.NullWorktree()
    assert wt.isIsolated("/anything") is False
    assert wt.enterWorktree(None, "sid#b0") == ""          # shared/no isolation
    assert wt.exitWorktree("/p", merge=True) == {"merged": False}
    assert wt.removeWorktree("/p") is False
    assert wt.gcOrphans(None) == 0


def test_load_backend_returns_real_or_null_but_isolatable_api():
    # Epic 1 worktree.py now exists -> the real module; still must expose isIsolated, never raise.
    backend = fs.loadWorktreeBackend()
    assert hasattr(backend, "isIsolated")
