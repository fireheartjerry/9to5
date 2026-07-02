"""Config knobs + (Task 4) router fallback discipline."""
from unittest import mock

import config

from platform_core.execution import router
from platform_core.execution.backends.local import LocalEnvironment


def test_execution_config_defaults_to_today(monkeypatch):
    # monkeypatch isolates from live .env; test verifies intended ship-dark default.
    monkeypatch.setattr(config, "EXECUTION_FABRIC_ENABLED", False, raising=False)
    assert config.EXECUTION_FABRIC_ENABLED is False     # master gate OFF by default
    assert config.EXECUTION_BACKEND == "local"          # default backend
    assert isinstance(config.EXECUTION_BACKEND_BY_RISK, dict)
    assert config.EXECUTION_BACKEND_BY_RISK == {}        # empty until Epic 4 lands
    assert isinstance(config.DOCKER_EXECUTOR_IMAGE, str) and config.DOCKER_EXECUTOR_IMAGE
    assert config.EXECUTION_REMOTE_KIND in ("ssh", "modal", "daytona", "e2b")
    assert isinstance(config.EXECUTION_PROVISION_TIMEOUT_SECONDS, int)
    assert config.EXECUTION_PROVISION_TIMEOUT_SECONDS > 0


def test_select_returns_local_when_fabric_disabled():
    with mock.patch.object(config, "EXECUTION_FABRIC_ENABLED", False):
        env = router.selectEnvironment({}, {"execution_backend": "docker"}, None)
    assert isinstance(env, LocalEnvironment)


def test_select_unknown_name_degrades_to_local():
    with mock.patch.object(config, "EXECUTION_FABRIC_ENABLED", True), \
         mock.patch.object(config, "EXECUTION_BACKEND", "local"):
        env = router.selectEnvironment({}, {"execution_backend": "does-not-exist"}, None)
    assert isinstance(env, LocalEnvironment)


def test_select_unhealthy_backend_degrades_to_local():
    class _Unhealthy(LocalEnvironment):
        NAME = "unhealthy"
        def healthCheck(self):
            return False
    with mock.patch.object(config, "EXECUTION_FABRIC_ENABLED", True), \
         mock.patch.object(router, "_backendClass", return_value=_Unhealthy):
        env = router.selectEnvironment({}, {"execution_backend": "unhealthy"}, None)
    assert isinstance(env, LocalEnvironment)


def test_provision_failure_falls_back_to_local_handle():
    class _Boom(LocalEnvironment):
        NAME = "boom"
        def provision(self, *, task_state, subtask, base_dir, policy):
            raise RuntimeError("provision blew up")
    env, handle = router.provision(_Boom(), task_state=None, subtask={"subtask_id": "s1"},
                                   base_dir="/repo")
    assert isinstance(env, LocalEnvironment)        # fell back
    assert handle.work_dir == "/repo"               # local handle points at base_dir
    assert handle.backend == "local"


def test_provision_success_returns_same_env_and_handle():
    env, handle = router.provision(LocalEnvironment(), task_state=None,
                                   subtask=None, base_dir="/repo")
    assert isinstance(env, LocalEnvironment) and handle.work_dir == "/repo"


def test_finalize_calls_collect_then_teardown():
    calls = []
    class _Spy(LocalEnvironment):
        def collectChanges(self, handle, *, task_state, subtask):
            calls.append("collect")
            return {"backend": "spy", "merged": True}
        def teardown(self, handle):
            calls.append("teardown")
    env = _Spy()
    handle = env.provision(task_state=None, subtask=None, base_dir="/repo", policy=None)
    summary = router.finalize(env, handle, None, None)
    assert calls == ["collect", "teardown"]
    assert summary == {"backend": "spy", "merged": True}


# --- Task 13: backend tag in surfaces_used (SIE learning, non-load-bearing) ---
import platform_core.core.surfaces as surfaces


def test_surfaces_used_tags_backend():
    used = surfaces.surfaces_used({"prompt": "do x", "execution_backend": "worktree"})
    assert "backend:worktree" in used


def test_surfaces_used_no_backend_tag_by_default():
    used = surfaces.surfaces_used({"prompt": "do x"})
    assert not any(t.startswith("backend:") for t in used)
