"""Epic 5 config knobs exist with safe OFF defaults and re-export through config."""
import config


def test_society_disabled_by_default():
    assert config.SOCIETY_ENABLED is False


def test_society_numeric_defaults():
    assert config.SOCIETY_MAX_WORKERS >= 1
    assert config.SOCIETY_DEBATE_MAX_ROUNDS >= 1
    assert config.SOCIETY_TOKEN_BUDGET_USD > 0


def test_society_role_models_map_to_effort_keys():
    # Each role routes to an effort key the executor already understands.
    for role, effort in config.SOCIETY_ROLE_MODELS.items():
        assert effort in config.MODEL_BY_EFFORT


def test_blackboard_dir_under_state():
    assert config.BLACKBOARD_DIR.name == "blackboard"
    assert config.BLACKBOARD_DIR.parent.name == "state"
