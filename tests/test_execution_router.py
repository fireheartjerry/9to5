"""Config knobs + (Task 4) router fallback discipline."""
import config


def test_execution_config_defaults_to_today():
    assert config.EXECUTION_FABRIC_ENABLED is False     # master gate OFF by default
    assert config.EXECUTION_BACKEND == "local"          # default backend
    assert isinstance(config.EXECUTION_BACKEND_BY_RISK, dict)
    assert config.EXECUTION_BACKEND_BY_RISK == {}        # empty until Epic 4 lands
    assert isinstance(config.DOCKER_EXECUTOR_IMAGE, str) and config.DOCKER_EXECUTOR_IMAGE
    assert config.EXECUTION_REMOTE_KIND in ("ssh", "modal", "daytona", "e2b")
    assert isinstance(config.EXECUTION_PROVISION_TIMEOUT_SECONDS, int)
    assert config.EXECUTION_PROVISION_TIMEOUT_SECONDS > 0
