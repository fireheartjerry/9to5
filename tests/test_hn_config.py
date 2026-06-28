import importlib

import config
import platform_core.app_config.human_nature as hn_config


def test_behavior_flags_default_off(monkeypatch):
    for var in ("HUMAN_NATURE_ENABLED", "HN_OPINIONS_BEHAVIOR",
                "HN_EMOTIONS_BEHAVIOR", "HN_INTUITION_SHORTCUT"):
        monkeypatch.delenv(var, raising=False)
    try:
        reloaded = importlib.reload(hn_config)
        assert reloaded.HUMAN_NATURE_ENABLED is False
        assert reloaded.HN_OPINIONS_BEHAVIOR is False
        assert reloaded.HN_EMOTIONS_BEHAVIOR is False
        assert reloaded.HN_INTUITION_SHORTCUT is False
    finally:
        importlib.reload(hn_config)  # restore real-env values for other tests


def test_thresholds_and_paths_present():
    assert config.HN_THETA_HARD > config.HN_THETA_SOFT
    assert config.HN_RECAL_TEMPERATURE > 1.0
    assert str(config.CONVICTION_DB_PATH).endswith("conviction.db")
