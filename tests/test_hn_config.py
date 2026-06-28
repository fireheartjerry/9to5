import config

def test_behavior_flags_default_off():
    assert config.HUMAN_NATURE_ENABLED is False
    assert config.HN_OPINIONS_BEHAVIOR is False
    assert config.HN_EMOTIONS_BEHAVIOR is False
    assert config.HN_INTUITION_SHORTCUT is False

def test_thresholds_and_paths_present():
    assert config.HN_THETA_HARD > config.HN_THETA_SOFT
    assert config.HN_RECAL_TEMPERATURE > 1.0
    assert str(config.CONVICTION_DB_PATH).endswith("conviction.db")
