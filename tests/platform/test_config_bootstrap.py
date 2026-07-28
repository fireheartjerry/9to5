"""R12 config-v2 regression suite: env bootstrap, typed registry, PEP 562 facade.

Guards the three landmines this rewrite removed:
1. PROJECT_ROOT collapsing to platform_core/app_config/ when no env is present
   (STATE_DIR/LOG_PATH/EXPERIENCE_DB_PATH silently resolved INSIDE the package).
2. set_override mutating config's globals() only, so config.KNOB and the registry
   silently diverged after a live-tune.
3. Model/effort routing defaults drifting during the reorganization (they must be
   byte-identical to the pre-R12 literals).

Also folds in the former tests/test_config_robust_env.py (same subject module,
config.py's env-parsing helpers): config.py parses ~40 numeric constants from
.env. A bare int()/float() meant one malformed value (e.g. OLLAMA_TIMEOUT_SECONDS=
with nothing after it) raised at IMPORT time, taking down every entry point.
_envInt/_envFloat fall back to the default instead.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import config
import platform_core.app_config.settings as app_settings

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# 1) Bootstrap: PROJECT_ROOT landmine
# ---------------------------------------------------------------------------

def test_project_root_is_repo_root_not_package_dir():
    assert Path(config.PROJECT_ROOT).resolve() == REPO_ROOT
    assert "app_config" not in str(config.PROJECT_ROOT)


def test_derived_paths_live_under_repo_root():
    for name in ("STATE_DIR", "CONTROL_DIR", "EXPERIENCE_DB_PATH", "EVAL_SUITE_DIR",
                 "SIE_OVERRIDES_PATH", "HEARTBEAT_DIR", "LAUNCH_DIR", "IPC_DIR"):
        p = str(getattr(app_settings.settings().paths, name))
        assert str(REPO_ROOT) in p, f"{name} escaped the repo root: {p}"
        assert "app_config" not in p, f"{name} still inside the package dir: {p}"


def test_poisoned_runtime_refuses_legacy_config_io_before_callback() -> None:
    code = """
from platform_core.app_config import _env
from platform_core.runtime import controller_state

controller_state._RUNTIME_INSTALL_TERMINAL = (
    controller_state._PoisonedControllerRuntimeStateInstallation(
        bootstrap_id='a' * 64,
        reason='test-poison',
    )
)
called = []
def effect():
    called.append(True)
    raise AssertionError('legacy config callback crossed poisoned runtime')

for boundary in (_env._legacyConfigPathObservation, _env._legacyConfigPathMutation):
    try:
        boundary(effect)
    except controller_state.ControllerStateRefused as exc:
        assert 'absent' in str(exc) or 'runtime' in str(exc)
    else:
        raise AssertionError('poisoned runtime allowed legacy config I/O')
assert called == []
print('poisoned-config-io-refused-before-callback')
"""
    env = dict(os.environ)
    env.pop("NINE_TO_FIVE_LOG_DIR", None)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "poisoned-config-io-refused-before-callback"


def test_legacy_config_io_materializes_the_runtime_absence_boundary_first() -> None:
    code = """
import sys
from platform_core.app_config import _env

module_name = 'platform_core.runtime.controller_state'
assert module_name not in sys.modules
observed = []
def operation():
    observed.append(module_name in sys.modules)
    return 'ok'
assert _env._legacyConfigPathObservation(operation) == 'ok'
assert observed == [True]
print('runtime-absence-boundary-materialized')
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "runtime-absence-boundary-materialized"


def test_poisoned_runtime_refuses_all_legacy_root_lookups() -> None:
    code = """
from pathlib import Path
from platform_core.app_config import _env
from platform_core.runtime import controller_state

_env._ENV_LOADED = True
_env._PROCESS_PROJECT_ROOT = r'C:\\ambient-target'
controller_state._RUNTIME_INSTALL_TERMINAL = (
    controller_state._PoisonedControllerRuntimeStateInstallation(
        bootstrap_id='a' * 64,
        reason='test-poison',
    )
)
for lookup in (_env.locateRepoRoot, _env.installRoot, _env.projectRoot):
    try:
        lookup()
    except controller_state.ControllerStateRefused as exc:
        assert 'absent' in str(exc) or 'runtime' in str(exc)
    else:
        raise AssertionError(f'poisoned runtime allowed {{lookup.__name__}}')
print('poisoned-root-lookups-refused')
"""
    env = dict(os.environ)
    env["INSTALL_ROOT"] = str(REPO_ROOT / "ambient-install")
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "poisoned-root-lookups-refused"


def test_pending_runtime_uses_an_installed_config_projection_without_ambient_io() -> None:
    code = """
import os
from pathlib import Path
from platform_core.app_config import _env
from platform_core.runtime import controller_state

source = Path(r'C:\\controller-source')
installed = Path(r'C:\\controller-install')
_env._installControllerConfig(source_root=source, installed_root=installed)
controller_state._RUNTIME_INSTALL_TERMINAL = (
    controller_state._PendingControllerRuntimeStateInstallation(
        bootstrap_authorities=object(),
        owner_thread_id=1,
    )
)
_env.load_dotenv = lambda *args, **kwargs: (_ for _ in ()).throw(
    AssertionError('installed projection attempted ambient dotenv I/O')
)
os.environ['GALAXY_CONFIG_POISON'] = 'ambient-value'
_env.loadEnvOnce()
assert _env.projectRoot() == source
assert _env.installRoot() == installed
assert _env._envString('GALAXY_CONFIG_POISON', 'safe-default') == 'safe-default'
assert _env._envBool('FULL_STACK', True) is False
print('pending-runtime-used-installed-config')
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "pending-runtime-used-installed-config"


def test_pending_runtime_without_installed_config_refuses_ambient_env_reads() -> None:
    code = """
import os
from platform_core.app_config import _env
from platform_core.runtime import controller_state

controller_state._RUNTIME_INSTALL_TERMINAL = (
    controller_state._PendingControllerRuntimeStateInstallation(
        bootstrap_authorities=object(),
        owner_thread_id=1,
    )
)
os.environ['GALAXY_CONFIG_POISON'] = 'ambient-value'
for lookup in (
    lambda: _env._envString('GALAXY_CONFIG_POISON', 'safe-default'),
    lambda: _env._envBool('GALAXY_CONFIG_POISON', False),
    _env.installRoot,
    _env.projectRoot,
):
    try:
        lookup()
    except controller_state.ControllerStateRefused:
        pass
    else:
        raise AssertionError('pending runtime exposed ambient configuration')
print('pending-runtime-refused-ambient-config')
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "pending-runtime-refused-ambient-config"


def test_pending_runtime_refuses_cached_ambient_settings_and_overrides() -> None:
    code = """
import platform_core.app_config.settings as settings_module
from platform_core.runtime import controller_state

cached = settings_module.settings()
cached_flags = settings_module.runFlags()
original = cached.sie.RETRIEVAL_K
controller_state._RUNTIME_INSTALL_TERMINAL = (
    controller_state._PendingControllerRuntimeStateInstallation(
        bootstrap_authorities=object(),
        owner_thread_id=1,
    )
)
for operation in (
    settings_module.settings,
    settings_module.runFlags,
    lambda: settings_module.setOverride('RETRIEVAL_K', original + 1),
):
    try:
        operation()
    except controller_state.ControllerStateRefused:
        pass
    else:
        raise AssertionError('pending runtime exposed cached ambient configuration')
assert settings_module._SETTINGS is cached
assert settings_module._RUN_FLAGS is cached_flags
assert settings_module._SETTINGS.sie.RETRIEVAL_K == original
print('pending-runtime-refused-cached-settings')
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "pending-runtime-refused-cached-settings"


def test_runtime_fallback_fence_refuses_reentrant_path_install(tmp_path) -> None:
    external = tmp_path / "external" / "repo-1"
    source = tmp_path / "target"
    installed = tmp_path / "installed"
    source.mkdir()
    installed.mkdir()
    code = f"""
from platform_core.app_config.paths import (
    controllerPathsActive,
    installControllerPaths,
)
from platform_core.runtime.controller_state import (
    ControllerStateRefused,
    controllerRuntimeStateAbsentPermit,
    installControllerRuntimeState,
    issueDiagnosticControllerStateAuthority,
)

authority = issueDiagnosticControllerStateAuthority(
    root={str(external)!r},
    repository_id='repo_reentrant_fallback',
    controller_generation=1,
    process_capability=object(),
    expires_at='2099-01-01T00:00:00+00:00',
)
with controllerRuntimeStateAbsentPermit():
    try:
        installControllerPaths(
            authority=authority,
            source_root={str(source)!r},
            installed_root={str(installed)!r},
        )
    except ControllerStateRefused as exc:
        assert 'fallback' in str(exc) or 'reentrant' in str(exc)
    else:
        raise AssertionError('fallback callback reentrantly installed controller paths')
    try:
        installControllerRuntimeState(bootstrap_authorities=object())
    except ControllerStateRefused as exc:
        assert 'reentrant' in str(exc)
    else:
        raise AssertionError('fallback callback began central runtime composition')
assert not controllerPathsActive()
print('reentrant-path-install-refused')
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "reentrant-path-install-refused"


def test_poisoned_runtime_refuses_ensure_dirs_before_settings_observation() -> None:
    code = """
from platform_core.app_config import paths
import platform_core.app_config.settings as settings_module
from platform_core.runtime import controller_state

controller_state._RUNTIME_INSTALL_TERMINAL = (
    controller_state._PoisonedControllerRuntimeStateInstallation(
        bootstrap_id='a' * 64,
        reason='test-poison',
    )
)
called = []
def observe_settings():
    called.append(True)
    raise AssertionError('ensureDirs observed legacy settings after poison')
settings_module.settings = observe_settings
try:
    paths.ensureDirs()
except controller_state.ControllerStateRefused as exc:
    assert 'absent' in str(exc) or 'runtime' in str(exc)
else:
    raise AssertionError('poisoned runtime allowed legacy directory creation')
assert called == []
print('poisoned-ensure-dirs-refused-before-settings')
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "poisoned-ensure-dirs-refused-before-settings"


def test_poisoned_runtime_refuses_logging_before_settings_observation() -> None:
    code = """
import platform_core.app_config.settings as settings_module
from platform_core.runtime import controller_state

controller_state._RUNTIME_INSTALL_TERMINAL = (
    controller_state._PoisonedControllerRuntimeStateInstallation(
        bootstrap_id='a' * 64,
        reason='test-poison',
    )
)
called = []
def observe_settings():
    called.append(True)
    raise AssertionError('logging observed legacy settings after poison')
settings_module.settings = observe_settings
try:
    settings_module._configureLogging()
except controller_state.ControllerStateRefused as exc:
    assert 'absent' in str(exc) or 'runtime' in str(exc)
else:
    raise AssertionError('poisoned runtime allowed legacy logging setup')
assert called == []
print('poisoned-logging-refused-before-settings')
"""
    env = dict(os.environ)
    env.pop("NINE_TO_FIVE_LOG_DIR", None)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "poisoned-logging-refused-before-settings"


def test_subprocess_import_from_non_repo_cwd_resolves_repo_root():
    """THE landmine regression: import the paths domain with PROJECT_ROOT env unset,
    from a cwd OUTSIDE the repo -> PROJECT_ROOT must equal the repo root (marker walk
    from __file__), never the package dir and never a .env-file PROJECT_ROOT."""
    env = {k: v for k, v in os.environ.items() if k != "PROJECT_ROOT"}
    env["PYTHONPATH"] = str(REPO_ROOT)
    code = ("import platform_core.app_config.paths as p; "
            "print(p.PROJECT_ROOT); print(p.STATE_DIR)")
    with tempfile.TemporaryDirectory(prefix="9to5-config-bootstrap-") as outside:
        r = subprocess.run(
            [sys.executable, "-c", code],
            cwd=outside,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
    assert r.returncode == 0, f"paths import failed from non-repo cwd:\n{r.stderr}"
    got_root, got_state = r.stdout.strip().splitlines()[-2:]
    assert Path(got_root).resolve() == REPO_ROOT
    assert Path(got_state).resolve() == REPO_ROOT / "state" / "tasks"


def test_dotenv_project_root_never_leaks_to_children():
    """loadEnvOnce scrubs a .env-provided PROJECT_ROOT from os.environ so child
    processes cannot inherit it as a fake process-level override."""
    from platform_core.app_config import _env
    _env.loadEnvOnce()
    if _env._PROCESS_PROJECT_ROOT is None:   # normal case: no real process override
        assert "PROJECT_ROOT" not in os.environ


def test_load_env_once_is_idempotent():
    from platform_core.app_config import _env
    _env.loadEnvOnce()
    snapshot = dict(os.environ)
    _env.loadEnvOnce()
    assert dict(os.environ) == snapshot


def test_controller_paths_ignore_target_environment_and_place_runtime_state_externally(
    tmp_path,
    monkeypatch,
):
    from platform_core.app_config.paths import buildControllerPathsCfg
    from platform_core.runtime.controller_state import issueDiagnosticControllerStateAuthority

    external_root = tmp_path / "external" / "repo-1"
    source_root = tmp_path / "poisoned-target"
    source_root.mkdir()
    monkeypatch.setenv("LOG_PATH", str(source_root / "redirected-logs"))
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(source_root / "redirected-vault"))
    capability = object()
    authority = issueDiagnosticControllerStateAuthority(
        root=external_root,
        repository_id="repo_config_test",
        controller_generation=1,
        process_capability=capability,
        expires_at="2099-01-01T00:00:00+00:00",
    )

    paths = buildControllerPathsCfg(
        authority=authority,
        source_root=source_root,
        installed_root=tmp_path / "installed-controller",
    )

    assert paths.PROJECT_ROOT == source_root.resolve()
    for name in (
        "LOG_PATH",
        "KNOWLEDGE_DIR",
        "STATE_DIR",
        "CONTROL_DIR",
        "HEARTBEAT_DIR",
        "LAUNCH_DIR",
        "IPC_DIR",
        "BLACKBOARD_DIR",
        "EXPERIENCE_DB_PATH",
        "CONVICTION_DB_PATH",
        "AB_HARNESS_DB_PATH",
        "SIE_OVERRIDES_PATH",
        "AUDIT_LOG_PATH",
        "PERF_TELEMETRY_PATH",
        "CLAUDE_DIR",
        "EVOLUTION_CANDIDATE_DIR",
    ):
        value = Path(getattr(paths, name)).resolve()
        assert value == external_root.resolve() or external_root.resolve() in value.parents
        assert source_root.resolve() not in value.parents


def test_controller_paths_reservation_exit_without_commit_publishes_nothing(tmp_path):
    external = tmp_path / "external" / "repo-1"
    source = tmp_path / "target"
    installed = tmp_path / "installed"
    source.mkdir()
    installed.mkdir()
    code = f"""
from platform_core.app_config._env import controllerConfigActive
from platform_core.app_config.paths import (
    controllerPathsActive,
    reserveControllerPathsInstallation,
)
from platform_core.runtime.controller_state import issueDiagnosticControllerStateAuthority
capability = object()
authority = issueDiagnosticControllerStateAuthority(
    root={str(external)!r}, repository_id='repo_reservation_release',
    controller_generation=1, process_capability=capability,
    expires_at='2099-01-01T00:00:00+00:00')
reservation = reserveControllerPathsInstallation(
    authority=authority, source_root={str(source)!r}, installed_root={str(installed)!r})
assert not controllerPathsActive()
assert not controllerConfigActive()
with reservation as active:
    assert active is reservation
    assert not controllerPathsActive()
    assert not controllerConfigActive()
assert not controllerPathsActive()
assert not controllerConfigActive()
try:
    reservation.commit()
except RuntimeError:
    pass
else:
    raise AssertionError('post-exit reservation commit unexpectedly succeeded')
print('inactive')
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "inactive"


def test_controller_paths_reservation_serializes_ambient_builder_until_exit(tmp_path):
    external = tmp_path / "external" / "repo-1"
    source = tmp_path / "target"
    installed = tmp_path / "installed"
    source.mkdir()
    installed.mkdir()
    code = f"""
import json
import threading
import platform_core.app_config.paths as paths_module
from platform_core.app_config.paths import (
    buildPathsCfg,
    controllerPathsActive,
    reserveControllerPathsInstallation,
)
from platform_core.runtime.controller_state import issueDiagnosticControllerStateAuthority
capability = object()
authority = issueDiagnosticControllerStateAuthority(
    root={str(external)!r}, repository_id='repo_reservation_race',
    controller_generation=1, process_capability=capability,
    expires_at='2099-01-01T00:00:00+00:00')
at_lock_boundary = threading.Event()
finished = threading.Event()
observed = {{}}

class BoundaryRLock:
    def __init__(self):
        self._lock = threading.RLock()

    def acquire(self, *args, **kwargs):
        if threading.current_thread().name == 'ambient-path-builder':
            at_lock_boundary.set()
        return self._lock.acquire(*args, **kwargs)

    def release(self):
        self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()

paths_module._CONTROLLER_PATHS_LOCK = BoundaryRLock()

def build_ambient_paths():
    try:
        observed['paths'] = buildPathsCfg()
    except BaseException as exc:
        observed['error'] = repr(exc)
    finally:
        finished.set()

with reserveControllerPathsInstallation(
    authority=authority,
    source_root={str(source)!r},
    installed_root={str(installed)!r},
) as reservation:
    worker = threading.Thread(target=build_ambient_paths, name='ambient-path-builder')
    worker.start()
    assert at_lock_boundary.wait(timeout=5)
    assert not finished.wait(timeout=0.25), 'ambient builder crossed an open reservation'
    committed = reservation.commit()
    assert str(committed.PROJECT_ROOT) == {str(source.resolve())!r}
    assert str(committed.INSTALL_ROOT) == {str(installed.resolve())!r}
    assert str(committed.LOG_PATH) == {str(external.resolve() / 'logs')!r}
    assert controllerPathsActive()
    assert not finished.wait(timeout=0.25), 'commit released the reservation lock early'

assert finished.wait(timeout=5)
worker.join(timeout=5)
assert not worker.is_alive()
assert 'error' not in observed, observed.get('error')
assert observed['paths'] is committed
print(json.dumps({{
    'project': str(observed['paths'].PROJECT_ROOT),
    'installed': str(observed['paths'].INSTALL_ROOT),
    'log': str(observed['paths'].LOG_PATH),
}}))
"""
    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": str(REPO_ROOT),
            "PROJECT_ROOT": str(tmp_path / "ambient-project"),
            "INSTALL_ROOT": str(tmp_path / "ambient-install"),
            "LOG_PATH": str(tmp_path / "ambient-logs"),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout.strip().splitlines()[-1])
    assert observed == {
        "project": str(source.resolve()),
        "installed": str(installed.resolve()),
        "log": str(external.resolve() / "logs"),
    }


def test_ambient_path_build_never_holds_path_lock_while_waiting_for_runtime(
    tmp_path,
):
    code = """
import threading
import platform_core.app_config.paths as paths_module
import platform_core.runtime.controller_state as state_module

runtime_wait = threading.Event()
finished = threading.Event()
observed = {}

class BoundaryRuntimeRLock:
    def __init__(self):
        self._lock = threading.RLock()

    def acquire(self, *args, **kwargs):
        if threading.current_thread().name == 'ambient-builder':
            runtime_wait.set()
        return self._lock.acquire(*args, **kwargs)

    def release(self):
        self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()

runtime_lock = BoundaryRuntimeRLock()
state_module._RUNTIME_BINDING_LOCK = runtime_lock
runtime_lock.acquire()

def build_paths():
    try:
        observed['paths'] = paths_module.buildPathsCfg()
    except BaseException as exc:
        observed['error'] = repr(exc)
    finally:
        finished.set()

worker = threading.Thread(target=build_paths, name='ambient-builder')
worker.start()
assert runtime_wait.wait(timeout=5)
path_acquired = paths_module._CONTROLLER_PATHS_LOCK.acquire(timeout=0.5)
if path_acquired:
    paths_module._CONTROLLER_PATHS_LOCK.release()
runtime_lock.release()
assert finished.wait(timeout=5)
worker.join(timeout=5)
assert not worker.is_alive()
assert 'error' not in observed, observed.get('error')
assert path_acquired, 'ambient builder inverted path -> runtime lock order'
print('runtime-path-order-preserved')
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "runtime-path-order-preserved"


def test_settings_build_never_holds_registry_lock_while_waiting_for_runtime(
    tmp_path,
):
    code = """
import threading
import platform_core.app_config.settings as settings_module
import platform_core.runtime.controller_state as state_module

def prove_runtime_first(operation, label):
    runtime_wait = threading.Event()
    finished = threading.Event()
    observed = {}

    class BoundaryRuntimeRLock:
        def __init__(self):
            self._lock = threading.RLock()

        def acquire(self, *args, **kwargs):
            if threading.current_thread().name == label:
                runtime_wait.set()
            return self._lock.acquire(*args, **kwargs)

        def release(self):
            self._lock.release()

        def __enter__(self):
            self.acquire()
            return self

        def __exit__(self, *args):
            self.release()

    runtime_lock = BoundaryRuntimeRLock()
    state_module._RUNTIME_BINDING_LOCK = runtime_lock
    settings_module._LOCK = threading.Lock()
    settings_module._SETTINGS = None
    settings_module._RUN_FLAGS = None
    runtime_lock.acquire()

    def invoke():
        try:
            observed['result'] = operation()
        except BaseException as exc:
            observed['error'] = repr(exc)
        finally:
            finished.set()

    worker = threading.Thread(target=invoke, name=label)
    worker.start()
    assert runtime_wait.wait(timeout=5)
    registry_acquired = settings_module._LOCK.acquire(timeout=0.5)
    if registry_acquired:
        settings_module._LOCK.release()
    runtime_lock.release()
    assert finished.wait(timeout=5)
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert 'error' not in observed, observed.get('error')
    assert registry_acquired, f'{{label}} inverted registry -> runtime lock order'

prove_runtime_first(settings_module.settings, 'settings-build')
prove_runtime_first(settings_module.reload, 'settings-reload')
print('runtime-registry-order-preserved')
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "runtime-registry-order-preserved"


def test_controller_paths_reservation_wins_atomic_race_with_settings_initialization(
    tmp_path,
):
    external = tmp_path / "external" / "repo-1"
    source = tmp_path / "target"
    installed = tmp_path / "installed"
    source.mkdir()
    installed.mkdir()
    code = f"""
import threading
import platform_core.app_config._env as bootstrap_env
import platform_core.app_config.paths as paths_module
import platform_core.app_config.settings as settings_module
import platform_core.runtime.controller_state as state_module
from platform_core.app_config.paths import reserveControllerPathsInstallation
from platform_core.runtime.controller_state import issueDiagnosticControllerStateAuthority

at_env_boundary = threading.Event()
allow_settings = threading.Event()
settings_released_env = threading.Event()
settings_finished = threading.Event()
observed = {{}}

class BoundaryEnvRLock:
    def __init__(self):
        self._lock = threading.RLock()
        self._state_lock = threading.Lock()
        self._owner = None
        self._depth = 0

    def acquire(self, *args, **kwargs):
        acquired = self._lock.acquire(*args, **kwargs)
        if acquired:
            ident = threading.get_ident()
            with self._state_lock:
                assert self._owner in (None, ident)
                self._owner = ident
                self._depth += 1
        return acquired

    def release(self):
        ident = threading.get_ident()
        with self._state_lock:
            assert self._owner == ident and self._depth > 0
            self._depth -= 1
            outermost = self._depth == 0
            if outermost:
                self._owner = None
        self._lock.release()
        if outermost and threading.current_thread().name == 'settings-builder':
            settings_released_env.set()

    def owned_by_current_thread(self):
        with self._state_lock:
            return self._owner == threading.get_ident()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()

class BoundaryRuntimeRLock:
    def __init__(self):
        self._lock = threading.RLock()

    def acquire(self, *args, **kwargs):
        if threading.current_thread().name == 'settings-builder':
            at_env_boundary.set()
            assert allow_settings.wait(timeout=5)
        return self._lock.acquire(*args, **kwargs)

    def release(self):
        self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()

env_lock = BoundaryEnvRLock()
bootstrap_env._ENV_LOCK = env_lock
paths_module._ENV_LOCK = env_lock
state_module._RUNTIME_BINDING_LOCK = BoundaryRuntimeRLock()
capability = object()
authority = issueDiagnosticControllerStateAuthority(
    root={str(external)!r}, repository_id='repo_settings_race',
    controller_generation=1, process_capability=capability,
    expires_at='2099-01-01T00:00:00+00:00')

def initialize_settings():
    try:
        observed['settings'] = settings_module.settings()
    except BaseException as exc:
        observed['error'] = repr(exc)
    finally:
        settings_finished.set()

with reserveControllerPathsInstallation(
    authority=authority,
    source_root={str(source)!r},
    installed_root={str(installed)!r},
) as reservation:
    worker = threading.Thread(target=initialize_settings, name='settings-builder')
    worker.start()
    assert at_env_boundary.wait(timeout=5)
    reservation_holds_env = env_lock.owned_by_current_thread()
    allow_settings.set()
    if not reservation_holds_env:
        assert settings_released_env.wait(timeout=5)
    committed = reservation.commit()
    assert reservation_holds_env
    assert not settings_finished.is_set()

assert settings_finished.wait(timeout=5)
worker.join(timeout=5)
assert not worker.is_alive()
assert 'error' not in observed, observed.get('error')
assert observed['settings'].paths is committed
print('settings-race-serialized')
"""
    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": str(REPO_ROOT),
            "PROJECT_ROOT": str(tmp_path / "ambient-project"),
            "INSTALL_ROOT": str(tmp_path / "ambient-install"),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "settings-race-serialized"


def test_controller_paths_reservation_refuses_ambient_settings_build_before_publish(
    tmp_path,
):
    external = tmp_path / "external" / "repo-1"
    source = tmp_path / "target"
    installed = tmp_path / "installed"
    source.mkdir()
    installed.mkdir()
    code = f"""
import threading
import platform_core.app_config.settings as settings_module
from platform_core.app_config._env import controllerConfigActive
from platform_core.app_config.paths import (
    controllerPathsActive,
    reserveControllerPathsInstallation,
)
from platform_core.runtime.controller_state import issueDiagnosticControllerStateAuthority

settings_built = threading.Event()
allow_settings_publish = threading.Event()
settings_finished = threading.Event()
reservation_finished = threading.Event()
observed = {{}}
original_build_settings = settings_module.buildSettings

def build_then_pause():
    built = original_build_settings()
    settings_built.set()
    assert allow_settings_publish.wait(timeout=5)
    return built

def initialize_settings():
    try:
        observed['settings'] = settings_module.settings()
    except BaseException as exc:
        observed['error'] = repr(exc)
    finally:
        settings_finished.set()

settings_module.buildSettings = build_then_pause
capability = object()
authority = issueDiagnosticControllerStateAuthority(
    root={str(external)!r}, repository_id='repo_settings_pre_publish',
    controller_generation=1, process_capability=capability,
    expires_at='2099-01-01T00:00:00+00:00')
worker = threading.Thread(target=initialize_settings, name='paused-settings-builder')
worker.start()
assert settings_built.wait(timeout=5)

def reserve_paths():
    try:
        observed['reservation'] = reserveControllerPathsInstallation(
            authority=authority,
            source_root={str(source)!r},
            installed_root={str(installed)!r},
        )
    except BaseException as exc:
        observed['reservation_error'] = repr(exc)
    finally:
        reservation_finished.set()

installer = threading.Thread(target=reserve_paths, name='blocked-path-reserver')
installer.start()
assert not reservation_finished.wait(timeout=0.25), (
    'path reservation crossed an unpublished settings build'
)
allow_settings_publish.set()
assert settings_finished.wait(timeout=5)
assert reservation_finished.wait(timeout=5)
worker.join(timeout=5)
installer.join(timeout=5)
assert not worker.is_alive()
assert not installer.is_alive()
assert 'error' not in observed, observed.get('error')
assert 'reservation_error' not in observed, observed.get('reservation_error')
reservation = observed['reservation']
body_entered = False
try:
    with reservation:
        body_entered = True
except RuntimeError as exc:
    assert 'config initialization' in str(exc)
else:
    raise AssertionError('reservation entered after ambient settings paths were built')
assert not body_entered
try:
    reservation.commit()
except RuntimeError:
    pass
else:
    raise AssertionError('refused reservation remained active')
assert settings_module._SETTINGS is observed['settings']
assert not controllerPathsActive()
assert not controllerConfigActive()
print('pre-publish-settings-refused')
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "pre-publish-settings-refused"


def test_controller_paths_reservation_direct_construction_cannot_bypass_validation(
    tmp_path,
):
    external = tmp_path / "external" / "repo-1"
    source = tmp_path / "target"
    installed = tmp_path / "installed"
    source.mkdir()
    installed.mkdir()
    code = f"""
from dataclasses import replace
from platform_core.app_config._env import controllerConfigActive
from platform_core.app_config.paths import (
    ControllerPathsInstallReservation,
    buildControllerPathsCfg,
    controllerPathsActive,
)
from platform_core.runtime.controller_state import issueDiagnosticControllerStateAuthority
capability = object()
authority = issueDiagnosticControllerStateAuthority(
    root={str(external)!r}, repository_id='repo_direct_reservation',
    controller_generation=1, process_capability=capability,
    expires_at='2099-01-01T00:00:00+00:00')
candidate = buildControllerPathsCfg(
    authority=authority, source_root={str(source)!r}, installed_root={str(installed)!r})
poisoned = replace(candidate, PROJECT_ROOT=candidate.LOG_PATH)
try:
    direct = ControllerPathsInstallReservation(poisoned)
except RuntimeError as exc:
    assert 'factory' in str(exc)
else:
    with direct as reservation:
        reservation.commit()
    raise AssertionError('direct reservation construction published unvalidated paths')
assert not controllerPathsActive()
assert not controllerConfigActive()
print('direct-construction-refused')
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "direct-construction-refused"


def test_controller_paths_reservation_foreign_commit_refuses_before_publication(
    tmp_path,
):
    external = tmp_path / "external" / "repo-1"
    source = tmp_path / "target"
    installed = tmp_path / "installed"
    source.mkdir()
    installed.mkdir()
    code = f"""
import threading
import platform_core.app_config.paths as paths_module
from platform_core.app_config._env import controllerConfigActive
from platform_core.app_config.paths import (
    controllerPathsActive,
    reserveControllerPathsInstallation,
)
from platform_core.runtime.controller_state import issueDiagnosticControllerStateAuthority

commit_attempted = threading.Event()
commit_finished = threading.Event()
publication_boundary = threading.Event()
observed = {{}}

def forbidden_publication(**kwargs):
    publication_boundary.set()
    raise AssertionError(f'foreign commit reached publication: {{kwargs!r}}')

paths_module._installControllerConfig = forbidden_publication
capability = object()
authority = issueDiagnosticControllerStateAuthority(
    root={str(external)!r}, repository_id='repo_foreign_commit',
    controller_generation=1, process_capability=capability,
    expires_at='2099-01-01T00:00:00+00:00')
reservation = reserveControllerPathsInstallation(
    authority=authority, source_root={str(source)!r}, installed_root={str(installed)!r})

def commit_from_foreign_thread():
    commit_attempted.set()
    try:
        reservation.commit()
    except BaseException as exc:
        observed['error'] = exc
    finally:
        commit_finished.set()

with reservation:
    worker = threading.Thread(
        target=commit_from_foreign_thread,
        name='foreign-reservation-committer',
    )
    worker.start()
    assert commit_attempted.wait(timeout=5)
    assert commit_finished.wait(timeout=5), 'foreign commit blocked on an owner-held lock'
    assert type(observed.get('error')) is RuntimeError, repr(observed.get('error'))
    assert 'owner' in str(observed['error'])
    assert not publication_boundary.is_set()
    assert not controllerPathsActive()
    assert not controllerConfigActive()

worker.join(timeout=5)
assert not worker.is_alive()
assert not controllerPathsActive()
assert not controllerConfigActive()
print('foreign-commit-refused')
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "foreign-commit-refused"


def test_controller_paths_reservation_same_object_racing_enter_has_one_winner(
    tmp_path,
):
    external = tmp_path / "external" / "repo-1"
    source = tmp_path / "target"
    installed = tmp_path / "installed"
    source.mkdir()
    installed.mkdir()
    code = f"""
import threading
import platform_core.runtime.controller_state as state_module
from platform_core.app_config.paths import (
    controllerPathsActive,
    reserveControllerPathsInstallation,
)
from platform_core.runtime.controller_state import issueDiagnosticControllerStateAuthority

capability = object()
authority = issueDiagnosticControllerStateAuthority(
    root={str(external)!r}, repository_id='repo_same_reservation_enter',
    controller_generation=1, process_capability=capability,
    expires_at='2099-01-01T00:00:00+00:00')
reservation = reserveControllerPathsInstallation(
    authority=authority, source_root={str(source)!r}, installed_root={str(installed)!r})
enter_barrier = threading.Barrier(2)
first_entered = threading.Event()
release_first = threading.Event()
results_lock = threading.Lock()
seen_lock = threading.Lock()
seen_threads = set()
entered_names = []
errors = []
exit_errors = []

class RacingBoundaryRLock:
    def __init__(self):
        self._lock = threading.RLock()

    def acquire(self, *args, **kwargs):
        name = threading.current_thread().name
        if name.startswith('reservation-enter-'):
            with seen_lock:
                first_acquire = name not in seen_threads
                seen_threads.add(name)
            if first_acquire:
                enter_barrier.wait(timeout=5)
        return self._lock.acquire(*args, **kwargs)

    def release(self):
        self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()

state_module._RUNTIME_BINDING_LOCK = RacingBoundaryRLock()

def race_enter():
    entered = False
    name = threading.current_thread().name
    try:
        reservation.__enter__()
        entered = True
        with results_lock:
            entered_names.append(name)
            first = len(entered_names) == 1
        if first:
            first_entered.set()
            assert release_first.wait(timeout=5)
    except BaseException as exc:
        with results_lock:
            errors.append(exc)
    finally:
        if entered:
            try:
                reservation.__exit__(None, None, None)
            except BaseException as exc:
                with results_lock:
                    exit_errors.append(exc)

workers = [
    threading.Thread(target=race_enter, name=f'reservation-enter-{{index}}')
    for index in range(2)
]
for worker in workers:
    worker.start()
assert first_entered.wait(timeout=5)
release_first.set()
for worker in workers:
    worker.join(timeout=5)
    assert not worker.is_alive()
assert len(entered_names) == 1, entered_names
assert len(errors) == 1 and type(errors[0]) is RuntimeError, errors
assert not exit_errors, exit_errors
assert not controllerPathsActive()
print('same-reservation-one-winner')
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "same-reservation-one-winner"


def test_controller_paths_reservation_foreign_exit_preserves_owner_and_locks(tmp_path):
    external = tmp_path / "external" / "repo-1"
    source = tmp_path / "target"
    installed = tmp_path / "installed"
    source.mkdir()
    installed.mkdir()
    code = f"""
import threading
from platform_core.app_config._env import controllerConfigActive
from platform_core.app_config.paths import (
    controllerPathsActive,
    reserveControllerPathsInstallation,
)
from platform_core.runtime.controller_state import issueDiagnosticControllerStateAuthority

capability = object()
authority = issueDiagnosticControllerStateAuthority(
    root={str(external)!r}, repository_id='repo_foreign_exit',
    controller_generation=1, process_capability=capability,
    expires_at='2099-01-01T00:00:00+00:00')
reservation = reserveControllerPathsInstallation(
    authority=authority, source_root={str(source)!r}, installed_root={str(installed)!r})
foreign_finished = threading.Event()
observed = {{}}

def exit_from_foreign_thread():
    try:
        reservation.__exit__(None, None, None)
    except BaseException as exc:
        observed['foreign_error'] = exc
    finally:
        foreign_finished.set()

reservation.__enter__()
worker = threading.Thread(target=exit_from_foreign_thread, name='foreign-reservation-exit')
worker.start()
assert foreign_finished.wait(timeout=5)
worker.join(timeout=5)
assert not worker.is_alive()
assert type(observed.get('foreign_error')) is RuntimeError, observed.get('foreign_error')
try:
    reservation.__exit__(None, None, None)
except BaseException as exc:
    raise AssertionError(f'owner could not close after foreign exit: {{exc!r}}') from exc
assert 'owner' in str(observed['foreign_error'])
assert not controllerPathsActive()
assert not controllerConfigActive()

next_reservation = reserveControllerPathsInstallation(
    authority=authority, source_root={str(source)!r}, installed_root={str(installed)!r})
next_acquired = threading.Event()
next_finished = threading.Event()
next_errors = []

def acquire_after_owner_close():
    try:
        with next_reservation:
            next_acquired.set()
    except BaseException as exc:
        next_errors.append(exc)
    finally:
        next_finished.set()

next_worker = threading.Thread(
    target=acquire_after_owner_close,
    name='reservation-after-foreign-exit',
)
next_worker.start()
assert next_acquired.wait(timeout=5)
assert next_finished.wait(timeout=5)
next_worker.join(timeout=5)
assert not next_worker.is_alive()
assert not next_errors, next_errors
assert not controllerPathsActive()
assert not controllerConfigActive()
print('foreign-exit-preserved-owner')
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "foreign-exit-preserved-owner"


def test_controller_paths_reservation_commit_publishes_exact_projection(tmp_path):
    external = tmp_path / "external" / "repo-1"
    source = tmp_path / "target"
    installed = tmp_path / "installed"
    source.mkdir()
    installed.mkdir()
    code = f"""
import json
from platform_core.app_config._env import installRoot, projectRoot
from platform_core.app_config.paths import (
    buildPathsCfg,
    controllerPathsActive,
    reserveControllerPathsInstallation,
)
from platform_core.runtime.controller_state import issueDiagnosticControllerStateAuthority
capability = object()
authority = issueDiagnosticControllerStateAuthority(
    root={str(external)!r}, repository_id='repo_reservation_commit',
    controller_generation=1, process_capability=capability,
    expires_at='2099-01-01T00:00:00+00:00')
with reserveControllerPathsInstallation(
    authority=authority,
    source_root={str(source)!r},
    installed_root={str(installed)!r},
) as reservation:
    committed = reservation.commit()
assert controllerPathsActive()
assert buildPathsCfg() is committed
print(json.dumps({{
    'project': str(committed.PROJECT_ROOT),
    'installed': str(committed.INSTALL_ROOT),
    'state': str(committed.STATE_DIR),
    'env_project': str(projectRoot()),
    'env_installed': str(installRoot()),
}}))
"""
    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": str(REPO_ROOT),
            "PROJECT_ROOT": str(tmp_path / "ambient-project"),
            "INSTALL_ROOT": str(tmp_path / "ambient-install"),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout.strip().splitlines()[-1])
    assert observed == {
        "project": str(source.resolve()),
        "installed": str(installed.resolve()),
        "state": str(external.resolve() / "state" / "tasks"),
        "env_project": str(source.resolve()),
        "env_installed": str(installed.resolve()),
    }


def test_boot_capsule_can_install_controller_paths_before_normal_config_import(tmp_path):
    external = tmp_path / "external" / "repo-1"
    source = tmp_path / "target"
    installed = tmp_path / "installed"
    source.mkdir()
    installed.mkdir()
    code = f"""
from platform_core.runtime.controller_state import issueDiagnosticControllerStateAuthority
from platform_core.app_config.paths import installControllerPaths
capability = object()
authority = issueDiagnosticControllerStateAuthority(
    root={str(external)!r}, repository_id='repo_capsule_test', controller_generation=1,
    process_capability=capability, expires_at='2099-01-01T00:00:00+00:00')
installControllerPaths(
    authority=authority, source_root={str(source)!r}, installed_root={str(installed)!r})
import config
print(config.STATE_DIR)
print(config.LOG_PATH)
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PROJECT_ROOT"] = str(tmp_path / "poison-project")
    env["LOG_PATH"] = str(tmp_path / "poison-logs")
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    state_path, log_path = (Path(line) for line in result.stdout.strip().splitlines()[-2:])
    assert state_path.resolve() == external.resolve() / "state" / "tasks"
    assert log_path.resolve() == external.resolve() / "logs"


def test_boot_capsule_settings_ignore_ambient_env_and_raw_override_files(tmp_path):
    external = tmp_path / "external" / "repo-1"
    source = tmp_path / "target"
    installed = tmp_path / "installed"
    source.mkdir()
    installed.mkdir()
    override = external / "state" / "sie_overrides.json"
    override.parent.mkdir(parents=True)
    override.write_text(json.dumps({"RETRIEVAL_K": 19}), encoding="utf-8")
    (source / ".env").write_text(
        "FULL_STACK=1\nGEMINI_API_KEY=target-secret\nDISCORD_BOT_TOKEN=target-token\n",
        encoding="utf-8",
    )
    code = f"""
import json
import platform_core.app_config._env as bootstrap_env
from platform_core.runtime.controller_state import issueDiagnosticControllerStateAuthority
from platform_core.app_config.paths import installControllerPaths
bootstrap_env.load_dotenv = lambda *args, **kwargs: (_ for _ in ()).throw(
    AssertionError('capsule attempted to load a legacy .env'))
capability = object()
authority = issueDiagnosticControllerStateAuthority(
    root={str(external)!r}, repository_id='repo_capsule_test', controller_generation=1,
    process_capability=capability, expires_at='2099-01-01T00:00:00+00:00')
installControllerPaths(
    authority=authority, source_root={str(source)!r}, installed_root={str(installed)!r})
import config
print(json.dumps({{
    'external_spend_allowed': config.EXTERNAL_SPEND_ALLOWED,
    'gemini_api_key': config.GEMINI_API_KEY,
    'gemini_enabled': config.GEMINI_ENABLED,
    'discord_token': config.DISCORD_BOT_TOKEN,
    'discord_channel': config.DISCORD_CHANNEL_ID,
    'discord_dashboard': config.DISCORD_DASHBOARD,
    'web_dashboard': config.WEB_DASHBOARD,
    'obsidian_api_key': config.OBSIDIAN_API_KEY,
    'ollama_host': config.OLLAMA_HOST,
    'sie_auto_maintenance': config.SIE_AUTO_MAINTENANCE,
    'evolution_enabled': config.EVOLUTION_ENABLED,
    'society_enabled': config.SOCIETY_ENABLED,
    'browser_enabled': config.BROWSER_LAYER_ENABLED,
    'native_enabled': config.NATIVE_LAYER_ENABLED,
    'retention_enabled': config.RETENTION_ENABLED,
    'execution_backend': config.EXECUTION_BACKEND,
    'retrieval_k': config.RETRIEVAL_K,
}}))
"""
    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": str(REPO_ROOT),
            "PROJECT_ROOT": str(tmp_path / "poison-project"),
            "INSTALL_ROOT": str(tmp_path / "poison-install"),
            "FULL_STACK": "1",
            "GALAXY_R3_POLICY_ENFORCEMENT_ENABLED": "1",
            "GEMINI_API_KEY": "ambient-secret",
            "GEMINI_ENABLED": "1",
            "DISCORD_BOT_TOKEN": "ambient-token",
            "DISCORD_CHANNEL_ID": "123456",
            "OBSIDIAN_API_KEY": "ambient-obsidian",
            "OLLAMA_HOST": "https://remote.invalid",
            "SIE_AUTO_MAINTENANCE": "1",
            "EVOLUTION_ENABLED": "1",
            "SOCIETY_ENABLED": "1",
            "BROWSER_LAYER_ENABLED": "1",
            "NATIVE_LAYER_ENABLED": "1",
            "EXECUTION_BACKEND": "remote",
            "RETRIEVAL_K": "17",
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout.strip().splitlines()[-1])
    assert observed == {
        "external_spend_allowed": False,
        "gemini_api_key": "",
        "gemini_enabled": False,
        "discord_token": "",
        "discord_channel": 0,
        "discord_dashboard": False,
        "web_dashboard": False,
        "obsidian_api_key": "",
        "ollama_host": "http://127.0.0.1:11434",
        "sie_auto_maintenance": False,
        "evolution_enabled": False,
        "society_enabled": False,
        "browser_enabled": False,
        "native_enabled": False,
        "retention_enabled": False,
        "execution_backend": "local",
        "retrieval_k": 5,
    }


# ---------------------------------------------------------------------------
# 2) Facade mechanics
# ---------------------------------------------------------------------------

def test_import_time_from_import_still_works():
    from config import OLLAMA_NUM_CTX, STATE_DIR  # noqa: PLC0415 -- the compat contract
    assert OLLAMA_NUM_CTX == app_settings.settings().ollama.OLLAMA_NUM_CTX
    # from-import snapshots whatever config.X currently resolves to -- including a
    # monkeypatched shadow (conftest isolates STATE_DIR); both views must agree.
    assert STATE_DIR == config.STATE_DIR


def test_monkeypatched_shadow_wins_over_registry(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path, raising=False)
    assert config.STATE_DIR == tmp_path                       # shadow wins (conftest relies on this)
    assert app_settings.settings().paths.STATE_DIR != tmp_path  # registry untouched


def test_unknown_attribute_raises_attribute_error():
    try:
        config.DEFINITELY_NOT_A_KNOB
    except AttributeError as e:
        assert "DEFINITELY_NOT_A_KNOB" in str(e)
    else:
        raise AssertionError("facade must raise AttributeError for unknown names")


def test_namespace_pollution_gone():
    """The old star-import facade leaked config.os / config.Path / config.load_dotenv."""
    for junk in ("os", "load_dotenv"):
        assert not hasattr(config, junk), f"config.{junk} leaked again"


def test_run_flags_route_through_facade():
    flags = app_settings.runFlags()
    saved = flags.WEB_DASHBOARD
    try:
        flags.WEB_DASHBOARD = not saved
        assert config.WEB_DASHBOARD == (not saved)   # facade reads the live flag object
    finally:
        flags.WEB_DASHBOARD = saved


def test_main_cli_overrides_mutate_run_flags_not_config_globals(monkeypatch):
    """main.py no longer pokes config module globals: CLI overrides land on runFlags()."""
    import types

    import main as main_mod
    flags = app_settings.runFlags()
    saved = (flags.NIGHT_MODE, flags.WEB_DASHBOARD, flags.WEB_DASHBOARD_PORT)
    names = ("NIGHT_MODE", "WEB_DASHBOARD", "WEB_DASHBOARD_PORT", "CLAUDE_DOC_FETCH")
    shadows_before = {n: (n in vars(config)) for n in names}
    monkeypatch.setattr(config, "ensureDirs", lambda: None, raising=False)
    args = types.SimpleNamespace(web_port=9999, no_web=True, night_mode=True,
                                 mode="gated", auto_approve=False)
    try:
        main_mod._applyConfigOverrides(args)
        assert flags.WEB_DASHBOARD_PORT == 9999
        assert flags.WEB_DASHBOARD is False
        assert flags.NIGHT_MODE is True
        assert args.mode == "watch" and args.auto_approve is True   # night mode side effects
        assert {n: (n in vars(config)) for n in names} == shadows_before, \
            "main.py wrote a config module global again"
    finally:
        flags.NIGHT_MODE, flags.WEB_DASHBOARD, flags.WEB_DASHBOARD_PORT = saved


def test_legacy_name_surface_is_complete():
    """Spot-check one name per legacy module/group so a lost re-export fails loudly."""
    names = [
        # paths
        "PROJECT_ROOT", "LOG_PATH", "INSTALL_ROOT", "KNOWLEDGE_DIR", "CLAUDE_KNOWLEDGE_PATH",
        "CLAUDE_RECOMMENDATIONS_PATH", "CLAUDE_SCAN_ROOTS", "OBSIDIAN_VAULT_PATH",
        "VAULT_DISK_ROOT", "TASKS_DIR_REL", "SESSIONS_DIR_REL", "STATE_DIR", "CONTROL_DIR",
        "HEARTBEAT_DIR", "LAUNCH_DIR", "IPC_DIR", "BLACKBOARD_DIR", "EXPERIENCE_DB_PATH",
        "EVAL_SUITE_DIR", "EVOLUTION_SUITE_DIR", "EVOLUTION_SKILL_DIR", "EVOLUTION_CANDIDATE_DIR",
        "LORA_OUTPUT_DIR", "ADVERSARY_TRUST_LOG", "SIE_OVERRIDES_PATH", "AUDIT_LOG_PATH",
        "AUDIT_MAX_BYTES", "CLAUDE_DIR", "CLAUDE_SETTINGS_PATH", "VENV_PYTHON",
        # discord
        "DISCORD_BOT_TOKEN", "DISCORD_CHANNEL_ID", "DISCORD_HUMAN_USER_ID", "DISCORD_GUILD_ID",
        "DISCORD_MAX_CONTENT", "DISCORD_MAX_EMBED_DESC", "DISCORD_MAX_FIELD_NAME",
        "DISCORD_MAX_FIELD_VALUE", "DISCORD_EMBED_TOTAL_MAX", "DISCORD_REST_TIMEOUT",
        "DISCORD_RETRY_MAX", "VERSION", "BRAND_COLOR", "BRAND_ICON_URL", "COOLDOWN_RATE",
        "COOLDOWN_PER", "PRESENCE_INTERVAL", "DISCORD_POLL_SECONDS", "DISCORD_DASHBOARD",
        "WEB_DASHBOARD", "WEB_DASHBOARD_PORT", "DISCORD_LAB_MODE", "DASHBOARD_CV2", "CAST_MODE",
        "ASK_ENABLED", "ASK_NL_CONTROL", "POLL_GATES", "RUN_THREADS", "SCHEDULED_EVENTS",
        "AUTOMOD_GUARD", "REACTION_APPROVE", "WATCHDOG_ENABLED", "VISUALS_ENABLED",
        "COCKPIT_THEME", "COCKPIT_IMAGE_MIN_INTERVAL", "DISCORD_MSGFLAG_COMPONENTS_V2",
        "DISCORD_CV2_MAX_COMPONENTS", "DISCORD_CV2_MAX_CHARS", "NIGHT_MODE",
        "NIGHT_MODE_PAUSE_TIMEOUT", "STATUS_COLORS",
        # llm: ollama/gemini
        "OLLAMA_MODEL", "OLLAMA_HOST", "OLLAMA_TIMEOUT_SECONDS", "OLLAMA_NUM_CTX",
        "OLLAMA_GEN_HEADROOM", "OLLAMA_KEEP_ALIVE", "EMBED_MODEL", "BRAIN_MODEL_TAG",
        "BRIEF_MODEL", "GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_ENABLED", "GEMINI_TIMEOUT_MS",
        "GEMINI_MAX_TURNS", "GEMINI_MIN_OUTPUT_CHARS", "GEMINI_JSON_REPAIR_RETRIES",
        "GEMINI_HEALTH_PROBE_RETRIES", "GEMINI_SYSTEM_PREAMBLE",
        # llm: claude cli / effort / knowledge fetch
        "CLAUDE_CLI_TIMEOUT_SECONDS", "CANCEL_POLL_SECONDS", "PRIMARY_MODEL", "FALLBACK_MODEL",
        "MODEL_BY_EFFORT", "SESSION_LIMIT_PAUSE_SECONDS", "SESSION_LIMIT_MAX_RETRIES",
        "GIT_TIMEOUT_SECONDS", "EXECUTOR_PLAYBOOK_ENABLED", "EXECUTOR_APPEND_SYSTEM_PROMPT",
        "EXECUTOR_OUTPUT_JSON", "EXECUTOR_RESUME_RETRIES", "EFFORT_LEVELS", "EFFORT_FLAG_MAP",
        "EFFORT_BARS", "EFFORT_LABELS", "CLAUDE_DOC_FETCH", "CLAUDE_DOC_TIMEOUT_SECONDS",
        "CLAUDE_DOC_FETCH_WORKERS", "CLAUDE_DOC_FETCH_BUDGET_SECONDS",
        "CLAUDE_KNOWLEDGE_MAX_AGE_HOURS", "CLAUDE_CAPABILITIES_MAX_CHARS", "MCP_SERVERS",
        "AVAILABLE_SKILLS", "AVAILABLE_SUBAGENTS", "AVAILABLE_PRE_HOOKS", "AVAILABLE_POST_HOOKS",
        # llm: sie / adversary / orchestration / run control
        "OBSIDIAN_API_KEY", "OBSIDIAN_PORT", "OBSIDIAN_HTTPS", "OBSIDIAN_BASE_URL",
        "OBSIDIAN_ASYNC", "EXPERIENCE_POOL", "EXPERIENCE_LEDGER_ENABLED", "RETRIEVAL_K",
        "RETRIEVAL_MAX_TOKENS", "RETRIEVAL_MIN_SCORE", "RETRIEVAL_CONTENT_MAX_TOKENS",
        "ANN_INDEX_ENABLED", "ANN_INDEX_BACKEND", "ANN_INDEX_DIR", "ANN_EMBED_DIM",
        "RETRIEVAL_W_RECENCY", "RETRIEVAL_W_IMPORTANCE", "RETRIEVAL_W_RELEVANCE",
        "RETRIEVAL_RECENCY_HALFLIFE_DAYS", "COMPACTION_ENABLED", "COMPACTION_TRIGGER_RATIO",
        "COMPACTION_RESERVE_RATIO", "COMPACTION_RESERVE_FLOOR", "COMPACTION_MAX_PASSES",
        "COMPACTION_OFFLOAD_DIR", "REFLECTION_CONSOLIDATE_ENABLED", "EVAL_FITNESS_WEIGHTS",
        "LESSONS_MIN_SUPPORT", "LESSONS_WIN_GAP", "POLICY_REWARD_WEIGHTS",
        "PROMPT_PROMOTE_MIN_USES", "PROMPT_PROMOTE_Z", "SIE_AUTO_MAINTENANCE",
        "SIE_MAINTENANCE_JOIN_SECONDS", "SIE_KILL_SWITCH", "LORA_MIN_EXAMPLES", "DPO_KL_BETA",
        "DPO_MIN_PAIRS", "CONFIDENCE_DEFER_THRESHOLD", "SIE_REFLECTION_ENABLED",
        "SIE_AUTHORING_CONTEXT", "INSIGHT_TRIGGER_BUDGET", "EVOLUTION_ENABLED",
        "EVOLUTION_CONSOLIDATE", "EVOLUTION_ESCALATE", "EVOLUTION_CANARY_FRACTION",
        "EVOLUTION_ESCALATE_MIN_FAILS", "EVOLUTION_PINNED_SKILLS", "EVOLUTION_STALE_DAYS",
        "EVOLUTION_ARCHIVE_DAYS", "SELFMOD_ALLOW_CORE", "SEMANTIC_SAFETY_ENABLED",
        "AUTONOMY_ALLOWANCE_USD", "AUTONOMOUS_DESTRUCTIVE_POLICY",
        "AUTONOMOUS_DESTRUCTIVE_ALLOWANCE_USD", "CLAUDE_ATTEMPT_COST_HINT_USD", "SIE_COMPUTE",
        "LORA_HF_BASE_REPO", "LORA_RANK", "LORA_EPOCHS", "SELFPLAY_ENABLED", "SELFPLAY_MAX_PER_DAY", "SELFPLAY_HOURS",
        "SELFPLAY_START_HOUR", "SELFPLAY_END_HOUR", "SIE_BOOTSTRAP", "RUN_MAX_RESTARTS",
        "RUN_RESTART_MAX_BACKOFF", "RUN_STALL_SECONDS", "BROWSER_LAYER_ENABLED",
        "NATIVE_LAYER_ENABLED", "ADVERSARY_REVIEW_PLAN", "ADVERSARY_REVIEW_ARCH",
        "ADVERSARY_REVIEW_PREPR_DIFF", "ADVERSARY_LOWCONF_CONSULT",
        "ADVERSARY_PREPR_DIFF_MAX_CHARS", "ADVERSARY_BLOCKING_SEVERITY",
        "ADVERSARY_REMEDIATION_MAX_ATTEMPTS", "ADVERSARY_TRIGGER_PHRASES",
        "ADVERSARY_HEARTBEAT_EVERY", "ADVERSARY_REMEDIATION_ENABLED", "ADVERSARY_PR_HOLD_ENABLED",
        "MAX_SUBTASK_ATTEMPTS", "MAX_SUBTASKS", "VERIFY_DEFAULT_EXPECT", "VERIFY_TIMEOUT_SECONDS",
        "CONTROL_MODE_DEFAULT", "PLAN_GATE_AUTO_APPROVE_SECONDS", "DEFAULT_PARALLELISM",
        "PREDICTIVE_FLAGS_ENABLED", "PREDICTIVE_FLAG_OLLAMA",
        "PREDICTIVE_FLAG_MIN_INTERVAL_SECONDS", "INSTINCT_ENABLED", "INSTINCT_INTERVAL_SECONDS",
        "SIE_META_AUTOAPPLY", "SIE_TUNABLE_KNOBS",
        # prompts + self-ref safety
        "SELF_IMPROVEMENT_PHILOSOPHY", "ARCHITECTURE_BRIEF", "BRAIN_DIALOGUE_SYSTEM_PROMPT",
        "INSTINCT_SYSTEM_PROMPT", "CORE_PROTECTED_FILES", "SELF_REF_BRANCH_PREFIX",
        "UNIVERSE_DEFAULT_HARD_BOUNDARIES",
        # epic flags (formerly llm_epic_flags.py)
        "TRAJECTORY_ENABLED", "COST_BUDGET_ENABLED", "COST_BUDGET_CEILING_USD",
        "STEP_JOURNAL_ENABLED", "STEP_RESUME_ENABLED", "WORKTREE_ISOLATION_ENABLED",
        "DUAL_LEDGER_PLANNER_ENABLED", "INDEPENDENT_VERIFY_ENABLED", "EVIDENCE_RECEIPT_ENABLED",
        "BRAIN_JSON_RETRY_MAX", "STALL_THRESHOLD", "SOCIETY_ENABLED", "SOCIETY_MAX_WORKERS",
        "SOCIETY_DEBATE_MAX_ROUNDS", "SOCIETY_TOKEN_BUDGET_USD", "SOCIETY_ROLE_MODELS",
        "SOLUTION_FORK_ENABLED", "SOLUTION_FORK_N", "SOLUTION_FORK_MAX_CONCURRENCY",
        "SOLUTION_FORK_COST_CEILING_USD", "SOLUTION_FORK_BRANCH_COST_ESTIMATE_USD",
        "SOLUTION_FORK_GRAFT_ENABLED", "W_FACT", "W_RUBRIC", "W_RISK", "W_COST",
        "EXECUTION_FABRIC_ENABLED", "EXECUTION_BACKEND", "EXECUTION_BACKEND_BY_RISK",
        "DOCKER_EXECUTOR_IMAGE", "EXECUTION_REMOTE_KIND", "EXECUTION_REMOTE_HOST",
        "EXECUTION_PROVISION_TIMEOUT_SECONDS",
        # facade helpers + private compat
        "set_override", "validateEnv", "getLogger", "ensureDirs", "_SIE_BOUNDS",
        "_envInt", "_envFloat", "_envBool",
    ]
    missing = [n for n in names if not hasattr(config, n)]
    assert missing == [], f"legacy config names lost by the facade: {missing}"


def test_controller_paths_reserve_refuses_inside_activation_fence_before_paths(
    tmp_path,
):
    external = tmp_path / "external" / "repo-1"
    source = tmp_path / "target"
    installed = tmp_path / "installed"
    source.mkdir()
    installed.mkdir()
    code = f"""
from platform_core.app_config.paths import (
    controllerPathsActivationFence,
    controllerPathsActive,
    reserveControllerPathsInstallation,
)
from platform_core.runtime.controller_state import issueDiagnosticControllerStateAuthority

class ExplodingPath:
    def __fspath__(self):
        raise AssertionError('nested reservation observed a caller path')

authority = issueDiagnosticControllerStateAuthority(
    root={str(external)!r}, repository_id='repo_fenced_reserve',
    controller_generation=1, process_capability=object(),
    expires_at='2099-01-01T00:00:00+00:00')
with controllerPathsActivationFence():
    try:
        reserveControllerPathsInstallation(
            authority=authority,
            source_root=ExplodingPath(),
            installed_root=ExplodingPath(),
        )
    except RuntimeError as exc:
        assert 'fence' in str(exc)
    else:
        raise AssertionError('reservation crossed an activation fence')
assert not controllerPathsActive()
print('fenced-reserve-refused-before-paths')
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "fenced-reserve-refused-before-paths"


def test_controller_paths_build_fence_blocks_reentrant_path_activation(tmp_path):
    external = tmp_path / "external" / "repo-1"
    source = tmp_path / "target"
    installed = tmp_path / "installed"
    source.mkdir()
    installed.mkdir()
    code = f"""
from platform_core.app_config.paths import (
    controllerPathsActive,
    installControllerPaths,
    reserveControllerPathsInstallation,
)
from platform_core.runtime.controller_state import issueDiagnosticControllerStateAuthority

class ExplodingPath:
    def __fspath__(self):
        raise AssertionError('reentrant activation observed nested path arguments')

authority = issueDiagnosticControllerStateAuthority(
    root={str(external)!r}, repository_id='repo_reentrant_build',
    controller_generation=1, process_capability=object(),
    expires_at='2099-01-01T00:00:00+00:00')

class ReentrantSource:
    def __fspath__(self):
        try:
            installControllerPaths(
                authority=authority,
                source_root=ExplodingPath(),
                installed_root=ExplodingPath(),
            )
        except RuntimeError as exc:
            assert 'fence' in str(exc)
        else:
            raise AssertionError('reentrant path conversion activated controller paths')
        return {str(source)!r}

reservation = reserveControllerPathsInstallation(
    authority=authority,
    source_root=ReentrantSource(),
    installed_root={str(installed)!r},
)
with reservation:
    pass
assert not controllerPathsActive()
print('build-fence-blocked-reentrant-activation')
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "build-fence-blocked-reentrant-activation"
    )


def test_direct_controller_paths_build_blocks_reentrant_path_activation(tmp_path):
    external = tmp_path / "external" / "repo-1"
    source = tmp_path / "target"
    installed = tmp_path / "installed"
    source.mkdir()
    installed.mkdir()
    code = f"""
from platform_core.app_config.paths import (
    buildControllerPathsCfg,
    controllerPathsActive,
    installControllerPaths,
)
from platform_core.runtime.controller_state import issueDiagnosticControllerStateAuthority

class ExplodingPath:
    def __fspath__(self):
        raise AssertionError('direct build exposed nested path arguments')

authority = issueDiagnosticControllerStateAuthority(
    root={str(external)!r}, repository_id='repo_direct_reentrant_build',
    controller_generation=1, process_capability=object(),
    expires_at='2099-01-01T00:00:00+00:00')

class ReentrantSource:
    def __fspath__(self):
        try:
            installControllerPaths(
                authority=authority,
                source_root=ExplodingPath(),
                installed_root=ExplodingPath(),
            )
        except RuntimeError as exc:
            assert 'fence' in str(exc)
        else:
            raise AssertionError('direct build reentrancy activated controller paths')
        return {str(source)!r}

candidate = buildControllerPathsCfg(
    authority=authority,
    source_root=ReentrantSource(),
    installed_root={str(installed)!r},
)
assert str(candidate.PROJECT_ROOT) == {str(source.resolve())!r}
assert not controllerPathsActive()
print('direct-build-fence-blocked-reentrant-activation')
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "direct-build-fence-blocked-reentrant-activation"
    )


def test_controller_paths_reservation_enter_refuses_inside_activation_fence(
    tmp_path,
):
    external = tmp_path / "external" / "repo-1"
    source = tmp_path / "target"
    installed = tmp_path / "installed"
    source.mkdir()
    installed.mkdir()
    code = f"""
from platform_core.app_config.paths import (
    controllerPathsActivationFence,
    controllerPathsActive,
    reserveControllerPathsInstallation,
)
from platform_core.runtime.controller_state import issueDiagnosticControllerStateAuthority
authority = issueDiagnosticControllerStateAuthority(
    root={str(external)!r}, repository_id='repo_fenced_enter',
    controller_generation=1, process_capability=object(),
    expires_at='2099-01-01T00:00:00+00:00')
reservation = reserveControllerPathsInstallation(
    authority=authority,
    source_root={str(source)!r},
    installed_root={str(installed)!r},
)
with controllerPathsActivationFence():
    try:
        reservation.__enter__()
    except RuntimeError as exc:
        assert 'fence' in str(exc)
    else:
        reservation.__exit__(None, None, None)
        raise AssertionError('reservation entered through an activation fence')
assert not controllerPathsActive()
print('fenced-enter-refused')
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "fenced-enter-refused"


def test_controller_paths_reservation_commit_refuses_inside_nested_fence(tmp_path):
    external = tmp_path / "external" / "repo-1"
    source = tmp_path / "target"
    installed = tmp_path / "installed"
    source.mkdir()
    installed.mkdir()
    code = f"""
from platform_core.app_config._env import controllerConfigActive
from platform_core.app_config.paths import (
    controllerPathsActivationFence,
    controllerPathsActive,
    reserveControllerPathsInstallation,
)
from platform_core.runtime.controller_state import issueDiagnosticControllerStateAuthority
authority = issueDiagnosticControllerStateAuthority(
    root={str(external)!r}, repository_id='repo_fenced_commit',
    controller_generation=1, process_capability=object(),
    expires_at='2099-01-01T00:00:00+00:00')
reservation = reserveControllerPathsInstallation(
    authority=authority,
    source_root={str(source)!r},
    installed_root={str(installed)!r},
)
with reservation:
    with controllerPathsActivationFence():
        try:
            reservation.commit()
        except RuntimeError as exc:
            assert 'fence' in str(exc)
        else:
            raise AssertionError('reservation committed inside a nested fence')
    committed = reservation.commit()
assert controllerPathsActive()
assert controllerConfigActive()
assert str(committed.PROJECT_ROOT) == {str(source.resolve())!r}
print('nested-fence-commit-refused')
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "nested-fence-commit-refused"


def test_controller_path_type_errors_are_normalized_before_effects(tmp_path):
    external = tmp_path / "external" / "repo-1"
    source = tmp_path / "target"
    installed = tmp_path / "installed"
    source.mkdir()
    installed.mkdir()
    code = f"""
from platform_core.app_config.paths import buildControllerPathsCfg, controllerPathsActive
from platform_core.runtime.controller_state import issueDiagnosticControllerStateAuthority
authority = issueDiagnosticControllerStateAuthority(
    root={str(external)!r}, repository_id='repo_typed_paths',
    controller_generation=1, process_capability=object(),
    expires_at='2099-01-01T00:00:00+00:00')
for source_root, installed_root in (
    (3, {str(installed)!r}),
    ({str(source)!r}, object()),
    (None, {str(installed)!r}),
):
    try:
        buildControllerPathsCfg(
            authority=authority,
            source_root=source_root,
            installed_root=installed_root,
        )
    except ValueError:
        pass
    else:
        raise AssertionError('invalid controller path type was not normalized')
assert not controllerPathsActive()
print('invalid-path-types-normalized')
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "invalid-path-types-normalized"


def test_controller_paths_reservation_revalidates_authority_at_commit(tmp_path):
    external = tmp_path / "external" / "repo-1"
    source = tmp_path / "target"
    installed = tmp_path / "installed"
    source.mkdir()
    installed.mkdir()
    code = f"""
from datetime import datetime as RealDateTime, timezone
import platform_core.runtime.controller_state as state_module
from platform_core.app_config._env import controllerConfigActive
from platform_core.app_config.paths import (
    controllerPathsActive,
    reserveControllerPathsInstallation,
)
from platform_core.runtime.controller_state import (
    ControllerStateRefused,
    issueDiagnosticControllerStateAuthority,
    validateControllerStateAuthority,
)

class FakeDateTime(RealDateTime):
    current = RealDateTime(2029, 1, 1, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        value = cls.current
        return value if tz is not None else value.replace(tzinfo=None)

state_module.datetime = FakeDateTime
authority = issueDiagnosticControllerStateAuthority(
    root={str(external)!r}, repository_id='repo_expiring_reservation',
    controller_generation=1, process_capability=object(),
    expires_at='2030-01-01T00:00:00+00:00')
reservation = reserveControllerPathsInstallation(
    authority=authority,
    source_root={str(source)!r},
    installed_root={str(installed)!r},
)
FakeDateTime.current = RealDateTime(2031, 1, 1, tzinfo=timezone.utc)
try:
    validateControllerStateAuthority(authority)
except ControllerStateRefused:
    pass
else:
    raise AssertionError('expired authority still validates')
with reservation:
    try:
        reservation.commit()
    except ControllerStateRefused:
        pass
    else:
        raise AssertionError('expired reservation authority activated paths')
assert not controllerPathsActive()
assert not controllerConfigActive()
print('expired-reservation-refused')
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "expired-reservation-refused"


# ---------------------------------------------------------------------------
# 3) set_override divergence regression
# ---------------------------------------------------------------------------

def test_set_override_updates_facade_and_registry_and_persists(tmp_path):
    ov = tmp_path / "sie_overrides.json"
    saved = app_settings._SETTINGS
    old_val = config.MAX_SUBTASK_ATTEMPTS
    new_val = 4 if old_val != 4 else 5
    # Re-point persistence at a temp file via a registry swap (frozen -> replace).
    cur = app_settings.settings()
    app_settings._SETTINGS = replace(cur, paths=replace(cur.paths, SIE_OVERRIDES_PATH=ov))
    try:
        assert config.set_override("MAX_SUBTASK_ATTEMPTS", new_val) is True
        # THE divergence regression: facade AND registry move together.
        assert config.MAX_SUBTASK_ATTEMPTS == new_val
        assert app_settings.settings().sie.MAX_SUBTASK_ATTEMPTS == new_val
        assert json.loads(ov.read_text(encoding="utf-8"))["MAX_SUBTASK_ATTEMPTS"] == new_val
    finally:
        app_settings._SETTINGS = saved


def test_set_override_refreshes_an_existing_module_shadow(tmp_path):
    """A prior setattr(config, knob, v) (test/e2e shadow) must not mask a live-tune."""
    ov = tmp_path / "sie_overrides.json"
    saved = app_settings._SETTINGS
    cur = app_settings.settings()
    app_settings._SETTINGS = replace(cur, paths=replace(cur.paths, SIE_OVERRIDES_PATH=ov))
    had_shadow = "RETRIEVAL_K" in vars(config)
    old_shadow = vars(config).get("RETRIEVAL_K")
    setattr(config, "RETRIEVAL_K", 7)
    try:
        assert config.set_override("RETRIEVAL_K", 9) is True
        assert config.RETRIEVAL_K == 9
        assert app_settings.settings().sie.RETRIEVAL_K == 9
    finally:
        app_settings._SETTINGS = saved
        if had_shadow:
            setattr(config, "RETRIEVAL_K", old_shadow)
        else:
            delattr(config, "RETRIEVAL_K")


def test_set_override_still_refuses_unknown_and_out_of_bounds():
    assert config.set_override("PROJECT_ROOT", "C:/evil") is False
    assert config.set_override("MAX_SUBTASK_ATTEMPTS", 9999) is False
    assert config.set_override("MAX_SUBTASK_ATTEMPTS", "garbage") is False


# ---------------------------------------------------------------------------
# 4) Model/effort routing defaults byte-identical (NO routing value changes)
# ---------------------------------------------------------------------------

def test_model_routing_defaults_byte_identical(monkeypatch):
    for k in ("MODEL_LOW", "MODEL_DEFAULT", "MODEL_MEDIUM", "MODEL_HIGH", "MODEL_XHIGH",
              "MODEL_ULTRACODE", "OLLAMA_MODEL"):
        monkeypatch.delenv(k, raising=False)
    from platform_core.app_config.llm import ClaudeCliCfg, OllamaCfg
    cli = ClaudeCliCfg()
    assert cli.PRIMARY_MODEL == "claude-opus-4-8"
    assert cli.FALLBACK_MODEL == "claude-sonnet-4-6"
    assert cli.MODEL_BY_EFFORT == {
        "low":       "claude-haiku-4-5-20251001",
        "default":   "claude-sonnet-4-6",
        "medium":    "claude-sonnet-4-6",
        "high":      "claude-sonnet-4-6",
        "xhigh":     "claude-opus-4-8",
        "ultracode": "claude-opus-4-8",
    }
    assert OllamaCfg().OLLAMA_MODEL == "qwen2.5-coder:7b"


# ---------------------------------------------------------------------------
# 5) reload() rebuilds from env (tests-only seam)
# ---------------------------------------------------------------------------

def test_reload_picks_up_env_changes(monkeypatch):
    saved = app_settings._SETTINGS
    monkeypatch.setenv("RETRIEVAL_MAX_TOKENS", "351")
    try:
        app_settings.reload()
        assert config.RETRIEVAL_MAX_TOKENS == 351
    finally:
        monkeypatch.delenv("RETRIEVAL_MAX_TOKENS", raising=False)
        app_settings._SETTINGS = saved
        app_settings._RUN_FLAGS = None


# ---------------------------------------------------------------------------
# 6) env-parsing helpers survive malformed .env values (formerly
#    tests/test_config_robust_env.py -- same subject module: config.py)
# ---------------------------------------------------------------------------

class TestEnvHelpers(unittest.TestCase):
    def test_envint(self):
        with self._set("X9", "not-a-number"):
            self.assertEqual(config._envInt("X9", 42), 42)
        with self._set("X9", ""):
            self.assertEqual(config._envInt("X9", 42), 42)
        with self._set("X9", "  99 "):
            self.assertEqual(config._envInt("X9", 42), 99)

    def test_envfloat(self):
        with self._set("Y9", "nope"):
            self.assertEqual(config._envFloat("Y9", 1.5), 1.5)
        with self._set("Y9", "3.25"):
            self.assertEqual(config._envFloat("Y9", 1.5), 3.25)

    def _set(self, k, v):
        return _EnvCtx(k, v)


class _EnvCtx:
    def __init__(self, k, v): self.k, self.v = k, v
    def __enter__(self):
        self._old = os.environ.get(self.k)
        os.environ[self.k] = self.v
    def __exit__(self, *a):
        if self._old is None:
            os.environ.pop(self.k, None)
        else:
            os.environ[self.k] = self._old


class TestImportSurvivesMalformedEnv(unittest.TestCase):
    def test_config_import_does_not_crash_on_garbage(self):
        env = {**os.environ, "OLLAMA_TIMEOUT_SECONDS": "garbage", "OBSIDIAN_PORT": "",
               "CLAUDE_DOC_FETCH_BUDGET_SECONDS": "xx"}
        # Import config from THIS test file's repo root (where config.py lives) -- config
        # has no PROJECT_ROOT attribute (that's platform_core.app_config._env.projectRoot()),
        # and cwd can mis-resolve to a sub-dir with no config.py when run from a worktree.
        # This file lives at tests/platform/, so repo root is two levels up.
        repo_root = Path(__file__).resolve().parents[2]
        r = subprocess.run(
            [sys.executable, "-c", "import config; print(config.OLLAMA_TIMEOUT_SECONDS, config.OBSIDIAN_PORT)"],
            cwd=str(repo_root), env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, f"config import crashed on malformed .env:\n{r.stderr}")
        self.assertEqual(r.stdout.strip(), "180 27124")   # both fell back to their defaults
