from tools import browser_canary


def test_browser_canary_is_explicitly_gated(monkeypatch):
    monkeypatch.delenv("NINE_TO_FIVE_ALLOW_BROWSER_CANARY", raising=False)
    result = browser_canary.run()
    assert result["status"] == "skipped"
