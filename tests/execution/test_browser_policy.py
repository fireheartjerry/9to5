from agents.execution.browser_executor import BrowserEvidence, BrowserPolicy, _validate_actions, runBrowser
from agents.execution import browser_executor


def test_policy_rejects_non_allowlisted_origin():
    policy = BrowserPolicy(allowed_origins=("https://safe.test",))
    try:
        _validate_actions([{"action": "goto", "url": "https://elsewhere.test"}], policy)
    except ValueError as exc:
        assert "allowlisted" in str(exc)
    else:
        raise AssertionError("origin should be blocked")


def test_irreversible_action_requires_confirmation():
    res = runBrowser({"surface": "browser", "browser_actions": [{"action": "click", "selector": "#delete", "irreversible": True}]})
    assert not res["ok"]
    assert "confirmation" in res["stderr"]
    assert res["surface_receipt"]["actual_mode"] == "live"


def test_policy_allows_production_protocol_actions():
    _validate_actions([
        {"action": "upload", "selector": "#file", "path": "proof.txt"},
        {"action": "download", "selector": "#export", "path": "result.csv"},
        {"action": "assert", "selector": "#status", "contains": "done"},
    ], BrowserPolicy())


def test_browser_retries_a_transient_failure(monkeypatch):
    calls = {"n": 0}
    def flaky(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("stale selector")
        return "ok"
    monkeypatch.setattr(browser_executor, "_run_actions", flaky)
    res = runBrowser({"browser_actions": [{"action": "goto", "url": "http://fixture"}], "browser_policy": {"max_retries": 1}})
    assert res["ok"] and "attempts=2" in res["stdout"]


def test_policy_rejects_artifact_path_escape():
    try:
        _validate_actions([{"action": "download", "selector": "#export", "path": "../escape.csv"}], BrowserPolicy())
    except ValueError as exc:
        assert "basename" in str(exc)
    else:
        raise AssertionError("artifact path traversal should be blocked")


def test_successful_run_exposes_structured_action_evidence(monkeypatch):
    def fake(actions, **kwargs):
        kwargs["evidence"].append(BrowserEvidence(0, "goto", "http://fixture", duration_ms=3))
        return "ok"
    monkeypatch.setattr(browser_executor, "_run_actions", fake)
    result = runBrowser({"browser_actions": [{"action": "goto", "url": "http://fixture"}]})
    assert result["browser_evidence"] == [{"index": 0, "action": "goto", "url": "http://fixture", "selector": "", "duration_ms": 3, "artifact_ref": ""}]


def test_failed_run_preserves_declared_artifact_reference(monkeypatch, tmp_path):
    monkeypatch.setattr(browser_executor, "_run_actions", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("proof failed")))
    result = runBrowser({"browser_actions": [{"action": "screenshot", "path": "proof.png"}, {"action": "assert", "contains": "done"}]}, work_dir=str(tmp_path))
    assert result["ok"] is False
    assert str(tmp_path / "proof.png") in result["surface_receipt"]["artifacts"]
