from platform_core.orchestration import evolution_hook


def test_hook_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(evolution_hook.config, "EVOLUTION_ENABLED", False, raising=False)
    assert evolution_hook.fireEvolver(reason="post-run") == {"skipped": "disabled"}
