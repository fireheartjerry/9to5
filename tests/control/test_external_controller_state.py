"""RED contracts for the external, authority-bound controller state root."""

from __future__ import annotations

import importlib
import errno
import inspect
import os
import shutil
import subprocess
import sys
import threading
from dataclasses import replace
from datetime import datetime as RealDateTime
from datetime import timezone
from pathlib import Path

import pytest

_AUTHORITY_LIVE = RealDateTime(2098, 1, 1, tzinfo=timezone.utc)
_AUTHORITY_EXPIRED = RealDateTime(2100, 1, 1, tzinfo=timezone.utc)


def _state():
    return importlib.import_module("platform_core.runtime.controller_state")


def _run_isolated_controller_state_case(
    tmp_path: Path,
    code: str,
) -> subprocess.CompletedProcess[str]:
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_posix_nested_write_read_and_exact_replay_through_real_runtime() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    if os.name == "nt":
        wsl = shutil.which("wsl.exe")
        if wsl is None:
            pytest.skip("WSL is unavailable")
        converted = subprocess.run(
            [wsl, "--exec", "wslpath", "-a", "--", str(repository_root)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if converted.returncode != 0 or not converted.stdout.strip():
            pytest.skip("a WSL POSIX distribution is unavailable")
        command_prefix = [wsl, "--exec", "python3"]
        posix_repository_root = converted.stdout.strip()
    else:
        command_prefix = [sys.executable]
        posix_repository_root = str(repository_root)
    script = r"""
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, sys.argv[1])
dotenv = types.ModuleType("dotenv")
dotenv.load_dotenv = lambda *_args, **_kwargs: False
sys.modules["dotenv"] = dotenv
from platform_core.runtime import controller_state as state

with tempfile.TemporaryDirectory(prefix="galaxy-controller-posix-") as temporary:
    root = Path(temporary) / "controller-state"
    authority = state.issueDiagnosticControllerStateAuthority(
        root=root,
        repository_id="repo_posix_nested",
        controller_generation=1,
        process_capability=object(),
        expires_at="2099-01-01T00:00:00+00:00",
    )
    store = state.ControllerStateStore(root=root, authority=authority)
    value = {"nested": ["exact", {"replay": True}]}
    store.writeJson("one/two/item", value, authority=authority)
    assert (root / "one").stat().st_nlink >= 2
    assert (root / "one" / "two").stat().st_nlink >= 2
    assert store.readJson("one/two/item", authority=authority) == value
    store.writeJson("one/two/item", value, authority=authority)
    assert store.readJson("one/two/item", authority=authority) == value
    store.close()
print("posix-nested-controller-state-green")
"""
    result = subprocess.run(
        [
            *command_prefix,
            "-c",
            script,
            posix_repository_root,
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "posix-nested-controller-state-green"
    )


def _runtime_install_prelude(tmp_path: Path) -> str:
    if os.name != "nt":
        pytest.skip(
            "installed-runtime bootstrap scope requires exact local Windows "
            "absolute roots (bootstrap_scope._require_canonical_windows_root)"
        )
    root = Path(__file__).resolve().parents[2]
    case_root = tmp_path / "runtime-install-case"
    return f"""
import os
import runpy
import sys
from pathlib import Path

repository_root = Path({str(root)!r})
fixture = runpy.run_path(
    str(repository_root / 'tests' / 'control' / 'test_installed_bootstrap_authority.py')
)
case_root = Path({str(case_root)!r})
scope, _spawn_result, outer = fixture['_consume_outer'](
    case_root
)
from platform_core.runtime import bootstrap_authority as bootstrap
from platform_core.runtime import controller_state as state
bundle = bootstrap.deriveInstalledBootstrapAuthorities(outer_capabilities=outer)
consumer_modules = (
    'notifications.surfaces.terminal_ipc',
    'platform_core.runtime.control_store',
    'platform_core.runtime.heartbeat',
    'state.task_io',
)
"""


def _install_fake_controller_clock(mod, monkeypatch: pytest.MonkeyPatch):
    class FakeDateTime(RealDateTime):
        current = _AUTHORITY_LIVE

        @classmethod
        def now(cls, tz=None):
            current = cls.current
            if tz is None:
                return current.replace(tzinfo=None)
            return current.astimezone(tz)

    monkeypatch.setattr(mod, "datetime", FakeDateTime)
    return FakeDateTime


def _expiring_store(tmp_path: Path):
    mod = _state()
    root = tmp_path / "controller-state"
    authority = mod.issueDiagnosticControllerStateAuthority(
        root=root,
        repository_id="repo_expiry_fence",
        controller_generation=1,
        process_capability=object(),
        expires_at="2099-01-01T00:00:00+00:00",
    )
    store = mod.ControllerStateStore(root=root, authority=authority)
    store.writeJson("records/item", {"value": 1}, authority=authority)
    return mod, root, authority, store


def _hide_next_controller_destination_observation(
    store,
    mod,
    monkeypatch: pytest.MonkeyPatch,
    *,
    destination_name: str,
) -> None:
    """Model a name appearing after the controller's pre-publication inventory."""

    original_directory = store._directory
    original_create = mod.NativeDirectoryHandle.createFile
    creating_temporary = False

    def track_temporary_create(self, name: str, payload: bytes):
        nonlocal creating_temporary
        creating_temporary = True
        try:
            return original_create(self, name, payload)
        finally:
            creating_temporary = False

    def stale_directory(parts: tuple[str, ...], *, create: bool):
        directory, opened = original_directory(parts, create=create)
        if parts != ("records",):
            return directory, opened
        original_list_entries = directory.listEntries
        hidden = False

        def hide_once(*, max_entries=65_536, max_name_bytes=1_024):
            nonlocal hidden
            entries = original_list_entries(
                max_entries=max_entries,
                max_name_bytes=max_name_bytes,
            )
            if creating_temporary or hidden:
                return entries
            hidden = True
            return tuple(entry for entry in entries if entry.name != destination_name)

        directory.listEntries = hide_once
        return directory, opened

    monkeypatch.setattr(mod.NativeDirectoryHandle, "createFile", track_temporary_create)
    monkeypatch.setattr(store, "_directory", stale_directory)


def test_installable_store_validation_releases_store_lock_before_authority_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The binding path must not invert store -> watchdog lock ordering."""

    mod, _root, authority, store = _expiring_store(tmp_path)
    original_validate = mod.ControllerStateStore._validateAuthority

    def validate_while_another_thread_takes_store_lock(self, value):
        acquired = threading.Event()

        def take_store_lock() -> None:
            with self._thread_lock:
                acquired.set()

        contender = threading.Thread(target=take_store_lock)
        contender.start()
        try:
            assert acquired.wait(timeout=1), (
                "authority validation ran while the caller retained the store lock"
            )
        finally:
            contender.join(timeout=2)
        assert not contender.is_alive()
        return original_validate(self, value)

    monkeypatch.setattr(
        mod.ControllerStateStore,
        "_validateAuthority",
        validate_while_another_thread_takes_store_lock,
    )

    assert store._validateInstallableAuthority(authority) is authority


def test_missing_authority_refuses_before_external_root_creation(tmp_path: Path) -> None:
    mod = _state()
    root = tmp_path / "controller-state"
    with pytest.raises(mod.ControllerStateRefused):
        mod.ControllerStateStore(root=root, authority=None)
    assert not root.exists()


def test_controller_state_authority_rejects_a_copied_handle(tmp_path: Path) -> None:
    mod = _state()
    authority = mod.issueDiagnosticControllerStateAuthority(
        root=tmp_path / "controller-state",
        repository_id="repo_test",
        controller_generation=4,
        process_capability=object(),
        expires_at="2099-01-01T00:00:00+00:00",
    )
    copied = replace(authority)

    with pytest.raises(mod.ControllerStateRefused, match="issuer differs"):
        mod.validateControllerStateAuthority(copied)


def test_controller_state_authority_copy_cannot_retarget_root(
    tmp_path: Path,
) -> None:
    mod = _state()
    capability = object()
    authority = mod.issueDiagnosticControllerStateAuthority(
        root=tmp_path / "controller-state",
        repository_id="repo_test",
        controller_generation=4,
        process_capability=capability,
        expires_at="2099-01-01T00:00:00+00:00",
    )
    foreign_root = tmp_path / "foreign-controller-state"

    with pytest.raises((mod.ControllerStateRefused, TypeError)):
        forged = replace(authority, root=str(foreign_root))
        mod.ControllerStateStore(root=foreign_root, authority=forged)

    assert not foreign_root.exists()


def test_diagnostic_controller_authority_cannot_be_minted_after_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _state()
    root = tmp_path / "controller-state"
    monkeypatch.setattr(mod, "_controller_paths_active", lambda: True, raising=False)

    with pytest.raises(mod.ControllerStateRefused, match="diagnostic.*activation"):
        mod.issueDiagnosticControllerStateAuthority(
            root=root,
            repository_id="repo_test",
            controller_generation=4,
            process_capability=object(),
            expires_at="2099-01-01T00:00:00+00:00",
        )

    assert not root.exists()


def test_preexisting_diagnostic_authority_cannot_construct_a_store_after_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _state()
    root = tmp_path / "controller-state"
    authority = mod.issueDiagnosticControllerStateAuthority(
        root=root,
        repository_id="repo_test",
        controller_generation=4,
        process_capability=object(),
        expires_at="2099-01-01T00:00:00+00:00",
    )
    monkeypatch.setattr(mod, "_controller_paths_active", lambda: True, raising=False)

    with pytest.raises(mod.ControllerStateRefused, match="diagnostic.*activation"):
        mod.ControllerStateStore(root=root, authority=authority)

    assert not root.exists()


@pytest.mark.parametrize(
    "operation",
    (
        "writeJson",
        "readJson",
        "listJsonIds",
        "replaceJsonWithBackup",
        "updateJson",
        "deleteJson",
    ),
)
def test_preopened_diagnostic_store_data_operations_revoke_after_activation(
    tmp_path: Path,
    operation: str,
) -> None:
    external = tmp_path / "external" / "repo-1"
    source = tmp_path / "target"
    installed = tmp_path / "installed"
    source.mkdir()
    installed.mkdir()
    code = f"""
from pathlib import Path
from platform_core.app_config.paths import installControllerPaths
from platform_core.runtime.controller_state import (
    ControllerStateRefused,
    ControllerStateStore,
    issueDiagnosticControllerStateAuthority,
)

external = Path({str(external)!r})
external.parent.mkdir(parents=True, exist_ok=True)
capability = object()
authority = issueDiagnosticControllerStateAuthority(
    root=external,
    repository_id='repo_revocation_test',
    controller_generation=1,
    process_capability=capability,
    expires_at='2099-01-01T00:00:00+00:00',
)
store = ControllerStateStore(root=external, authority=authority)
store.writeJson('records/item', {{'value': 1}}, authority=authority)

def snapshot():
    return {{
        str(path.relative_to(external)): path.read_bytes()
        for path in sorted(external.rglob('*'))
        if path.is_file()
    }}

operations = {{
    'writeJson': lambda: store.writeJson(
        'records/item', {{'value': 2}}, authority=authority
    ),
    'readJson': lambda: store.readJson('records/item', authority=authority),
    'listJsonIds': lambda: store.listJsonIds('records', authority=authority),
    'replaceJsonWithBackup': lambda: store.replaceJsonWithBackup(
        'records/item',
        'backups/item',
        {{'value': 2}},
        authority=authority,
    ),
    'updateJson': lambda: store.updateJson(
        'records/item',
        default={{'value': 0}},
        mutate=lambda value: {{'value': value['value'] + 1}},
        authority=authority,
    ),
    'deleteJson': lambda: store.deleteJson('records/item', authority=authority),
}}

installControllerPaths(
    authority=authority,
    source_root={str(source)!r},
    installed_root={str(installed)!r},
)
before = snapshot()
try:
    operations[{operation!r}]()
except ControllerStateRefused as exc:
    assert 'diagnostic' in str(exc) and 'activation' in str(exc)
else:
    raise AssertionError({operation!r} + ' remained usable after activation')
if {operation!r} == 'writeJson':
    try:
        store.writeJson(object(), {{'value': float('nan')}}, authority=authority)
    except ControllerStateRefused as exc:
        assert 'diagnostic' in str(exc) and 'activation' in str(exc)
    else:
        raise AssertionError('malformed input bypassed activation revocation')
assert snapshot() == before
store.close()
store.close()
assert store._closed
print('revoked-without-effect')
"""

    result = _run_isolated_controller_state_case(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "revoked-without-effect"


def test_diagnostic_operation_linearizes_before_waiting_activation(
    tmp_path: Path,
) -> None:
    external = tmp_path / "external" / "repo-1"
    source = tmp_path / "target"
    installed = tmp_path / "installed"
    source.mkdir()
    installed.mkdir()
    code = f"""
import threading
from pathlib import Path
import platform_core.runtime.controller_state as state_module
from platform_core.app_config.paths import installControllerPaths
from platform_core.runtime.controller_state import (
    ControllerStateRefused,
    ControllerStateStore,
    issueDiagnosticControllerStateAuthority,
)

external = Path({str(external)!r})
external.parent.mkdir(parents=True, exist_ok=True)
authority = issueDiagnosticControllerStateAuthority(
    root=external,
    repository_id='repo_operation_first',
    controller_generation=1,
    process_capability=object(),
    expires_at='2099-01-01T00:00:00+00:00',
)
store = ControllerStateStore(root=external, authority=authority)
store.writeJson('records/item', {{'value': 1}}, authority=authority)
operation_has_fence = threading.Event()
allow_operation = threading.Event()
activation_at_fence = threading.Event()
operation_finished = threading.Event()
activation_finished = threading.Event()
observed = {{}}

class BoundaryRLock:
    def __init__(self):
        self._lock = threading.RLock()

    def acquire(self, *args, **kwargs):
        name = threading.current_thread().name
        if name == 'activation':
            activation_at_fence.set()
        acquired = self._lock.acquire(*args, **kwargs)
        if acquired and name == 'operation':
            operation_has_fence.set()
            assert allow_operation.wait(timeout=5)
        return acquired

    def release(self):
        self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()

state_module._RUNTIME_BINDING_LOCK = BoundaryRLock()

def operate():
    try:
        observed['operation'] = store.updateJson(
            'records/item',
            default={{'value': 0}},
            mutate=lambda value: {{'value': value['value'] + 1}},
            authority=authority,
        )
    except BaseException as exc:
        observed['operation_error'] = repr(exc)
    finally:
        operation_finished.set()

def activate():
    try:
        installControllerPaths(
            authority=authority,
            source_root={str(source)!r},
            installed_root={str(installed)!r},
        )
    except BaseException as exc:
        observed['activation_error'] = repr(exc)
    finally:
        activation_finished.set()

operation_thread = threading.Thread(target=operate, name='operation')
operation_thread.start()
assert operation_has_fence.wait(timeout=5)
activation_thread = threading.Thread(target=activate, name='activation')
activation_thread.start()
assert activation_at_fence.wait(timeout=5)
assert not activation_finished.is_set()
allow_operation.set()
assert operation_finished.wait(timeout=5)
assert activation_finished.wait(timeout=5)
operation_thread.join(timeout=5)
activation_thread.join(timeout=5)
assert not operation_thread.is_alive() and not activation_thread.is_alive()
assert 'operation_error' not in observed, observed
assert 'activation_error' not in observed, observed
assert observed['operation'] == {{'value': 2}}
assert (external / 'records' / 'item.json').read_bytes() == b'{{"value":2}}'
before = (external / 'records' / 'item.json').read_bytes()
try:
    store.writeJson('records/item', {{'value': 3}}, authority=authority)
except ControllerStateRefused:
    pass
else:
    raise AssertionError('post-activation operation unexpectedly succeeded')
assert (external / 'records' / 'item.json').read_bytes() == before
store.close()
print('operation-linearized-first')
"""

    result = _run_isolated_controller_state_case(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "operation-linearized-first"


def test_diagnostic_constructor_holds_activation_fence_through_root_effects(
    tmp_path: Path,
) -> None:
    external = tmp_path / "external" / "repo-1"
    source = tmp_path / "target"
    installed = tmp_path / "installed"
    external.parent.mkdir(parents=True)
    source.mkdir()
    installed.mkdir()
    code = f"""
import threading
from pathlib import Path
import platform_core.runtime.controller_state as state_module
from platform_core.app_config.paths import installControllerPaths
from platform_core.runtime.controller_state import (
    ControllerStateStore,
    issueDiagnosticControllerStateAuthority,
)

external = Path({str(external)!r})
authority = issueDiagnosticControllerStateAuthority(
    root=external,
    repository_id='repo_constructor_first',
    controller_generation=1,
    process_capability=object(),
    expires_at='2099-01-01T00:00:00+00:00',
)
at_root_effect = threading.Event()
allow_constructor = threading.Event()
activation_at_fence = threading.Event()
constructor_finished = threading.Event()
activation_finished = threading.Event()
observed = {{}}
original_assert_no_reparse = state_module.assertNoReparsePath

class BoundaryRLock:
    def __init__(self):
        self._lock = threading.RLock()

    def acquire(self, *args, **kwargs):
        if threading.current_thread().name == 'activation':
            activation_at_fence.set()
        return self._lock.acquire(*args, **kwargs)

    def release(self):
        self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()

state_module._RUNTIME_BINDING_LOCK = BoundaryRLock()

def blocking_assert_no_reparse(path):
    if threading.current_thread().name == 'constructor' and not at_root_effect.is_set():
        at_root_effect.set()
        assert allow_constructor.wait(timeout=5)
    return original_assert_no_reparse(path)

state_module.assertNoReparsePath = blocking_assert_no_reparse

def construct():
    try:
        observed['store'] = ControllerStateStore(root=external, authority=authority)
    except BaseException as exc:
        observed['constructor_error'] = repr(exc)
    finally:
        constructor_finished.set()

def activate():
    try:
        installControllerPaths(
            authority=authority,
            source_root={str(source)!r},
            installed_root={str(installed)!r},
        )
    except BaseException as exc:
        observed['activation_error'] = repr(exc)
    finally:
        activation_finished.set()

constructor_thread = threading.Thread(target=construct, name='constructor')
constructor_thread.start()
assert at_root_effect.wait(timeout=5)
activation_thread = threading.Thread(target=activate, name='activation')
activation_thread.start()
assert activation_at_fence.wait(timeout=5)
activation_crossed_open_constructor = activation_finished.is_set()
allow_constructor.set()
assert constructor_finished.wait(timeout=5)
assert activation_finished.wait(timeout=5)
constructor_thread.join(timeout=5)
activation_thread.join(timeout=5)
assert not constructor_thread.is_alive() and not activation_thread.is_alive()
assert not activation_crossed_open_constructor
assert 'constructor_error' not in observed, observed
assert 'activation_error' not in observed, observed
observed['store'].close()
print('constructor-linearized-first')
"""

    result = _run_isolated_controller_state_case(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "constructor-linearized-first"


@pytest.mark.parametrize("contender", ("operation", "constructor"))
def test_activation_linearizes_before_diagnostic_contender_without_effect(
    tmp_path: Path,
    contender: str,
) -> None:
    external = tmp_path / "external" / "repo-1"
    candidate_root = tmp_path / "external" / "candidate"
    source = tmp_path / "target"
    installed = tmp_path / "installed"
    source.mkdir()
    installed.mkdir()
    code = f"""
import threading
from pathlib import Path
import platform_core.runtime.controller_state as state_module
from platform_core.app_config.paths import installControllerPaths
from platform_core.runtime.controller_state import (
    ControllerStateRefused,
    ControllerStateStore,
    issueDiagnosticControllerStateAuthority,
)

external = Path({str(external)!r})
candidate_root = Path({str(candidate_root)!r})
candidate_root.parent.mkdir(parents=True, exist_ok=True)

class ExplodingPath:
    def __fspath__(self):
        raise AssertionError('constructor observed root before activation revocation')

activation_authority = issueDiagnosticControllerStateAuthority(
    root=external,
    repository_id='repo_activation_first',
    controller_generation=1,
    process_capability=object(),
    expires_at='2099-01-01T00:00:00+00:00',
)
candidate_authority = issueDiagnosticControllerStateAuthority(
    root=candidate_root,
    repository_id='repo_activation_first_candidate',
    controller_generation=1,
    process_capability=object(),
    expires_at='2099-01-01T00:00:00+00:00',
)
store = None
if {contender!r} == 'operation':
    store = ControllerStateStore(root=candidate_root, authority=candidate_authority)
    store.writeJson('records/item', {{'value': 1}}, authority=candidate_authority)

activation_has_fence = threading.Event()
allow_activation = threading.Event()
contender_at_fence = threading.Event()
activation_finished = threading.Event()
contender_finished = threading.Event()
observed = {{}}

class BoundaryRLock:
    def __init__(self):
        self._lock = threading.RLock()

    def acquire(self, *args, **kwargs):
        name = threading.current_thread().name
        if name == 'contender':
            contender_at_fence.set()
        acquired = self._lock.acquire(*args, **kwargs)
        if acquired and name == 'activation':
            activation_has_fence.set()
            assert allow_activation.wait(timeout=5)
        return acquired

    def release(self):
        self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()

state_module._RUNTIME_BINDING_LOCK = BoundaryRLock()

def activate():
    try:
        installControllerPaths(
            authority=activation_authority,
            source_root={str(source)!r},
            installed_root={str(installed)!r},
        )
    except BaseException as exc:
        observed['activation_error'] = repr(exc)
    finally:
        activation_finished.set()

def contend():
    try:
        if {contender!r} == 'operation':
            assert store is not None
            store.writeJson(
                'records/item', {{'value': 2}}, authority=candidate_authority
            )
        else:
            observed['constructed'] = ControllerStateStore(
                root=ExplodingPath(), authority=candidate_authority
            )
    except BaseException as exc:
        observed['contender_error'] = exc
    finally:
        contender_finished.set()

activation_thread = threading.Thread(target=activate, name='activation')
activation_thread.start()
assert activation_has_fence.wait(timeout=5)
contender_thread = threading.Thread(target=contend, name='contender')
contender_thread.start()
assert contender_at_fence.wait(timeout=5)
assert not contender_finished.is_set()
allow_activation.set()
assert activation_finished.wait(timeout=5)
assert contender_finished.wait(timeout=5)
activation_thread.join(timeout=5)
contender_thread.join(timeout=5)
assert not activation_thread.is_alive() and not contender_thread.is_alive()
assert 'activation_error' not in observed, observed
assert isinstance(observed.get('contender_error'), ControllerStateRefused), observed
if {contender!r} == 'operation':
    assert (candidate_root / 'records' / 'item.json').read_bytes() == b'{{"value":1}}'
    assert store is not None
    store.close()
else:
    assert not candidate_root.exists()
print('activation-linearized-first')
"""

    result = _run_isolated_controller_state_case(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "activation-linearized-first"


def test_same_thread_activation_is_refused_inside_store_and_constructor_fences(
    tmp_path: Path,
) -> None:
    external = tmp_path / "external" / "repo-1"
    constructor_root = tmp_path / "external" / "repo-2"
    source = tmp_path / "target"
    installed = tmp_path / "installed"
    external.parent.mkdir(parents=True)
    source.mkdir()
    installed.mkdir()
    code = f"""
from pathlib import Path
from platform_core.app_config.paths import (
    controllerPathsActivationFence,
    controllerPathsActive,
    installControllerPaths,
    reserveControllerPathsInstallation,
)
from platform_core.runtime.controller_state import (
    ControllerStateStore,
    issueDiagnosticControllerStateAuthority,
)

class ExplodingPath:
    def __fspath__(self):
        raise AssertionError('nested activation processed a caller path')

external = Path({str(external)!r})
authority = issueDiagnosticControllerStateAuthority(
    root=external,
    repository_id='repo_reentrant_operation',
    controller_generation=1,
    process_capability=object(),
    expires_at='2099-01-01T00:00:00+00:00',
)
store = ControllerStateStore(root=external, authority=authority)
store.writeJson('records/item', {{'value': 1}}, authority=authority)

def attempt_activation(active_authority):
    try:
        installControllerPaths(
            authority=active_authority,
            source_root=ExplodingPath(),
            installed_root=ExplodingPath(),
        )
    except RuntimeError as exc:
        assert 'fence' in str(exc)
    else:
        raise AssertionError('same-thread nested activation unexpectedly succeeded')

result = store.updateJson(
    'records/item',
    default={{'value': 0}},
    mutate=lambda value: (attempt_activation(authority), {{'value': 2}})[1],
    authority=authority,
)
assert result == {{'value': 2}}
assert store.readJson('records/item', authority=authority) == {{'value': 2}}
assert not controllerPathsActive()

constructor_authority = issueDiagnosticControllerStateAuthority(
    root={str(constructor_root)!r},
    repository_id='repo_reentrant_constructor',
    controller_generation=1,
    process_capability=object(),
    expires_at='2099-01-01T00:00:00+00:00',
)

class ActivatingRoot:
    def __fspath__(self):
        attempt_activation(constructor_authority)
        return {str(constructor_root)!r}

constructor_store = ControllerStateStore(
    root=ActivatingRoot(), authority=constructor_authority
)
assert not controllerPathsActive()
constructor_store.close()

reservation = reserveControllerPathsInstallation(
    authority=authority,
    source_root={str(source)!r},
    installed_root={str(installed)!r},
)
with controllerPathsActivationFence():
    try:
        with reservation:
            pass
    except RuntimeError as exc:
        assert 'fence' in str(exc)
    else:
        raise AssertionError('reservation entered through an activation fence')

commit_reservation = reserveControllerPathsInstallation(
    authority=authority,
    source_root={str(source)!r},
    installed_root={str(installed)!r},
)
with commit_reservation:
    with controllerPathsActivationFence():
        try:
            commit_reservation.commit()
        except RuntimeError as exc:
            assert 'fence' in str(exc)
        else:
            raise AssertionError('reservation committed inside a nested activation fence')
    committed = commit_reservation.commit()
assert controllerPathsActive()
assert committed.PROJECT_ROOT == Path({str(source)!r}).resolve()
store.close()
print('same-thread-activation-refused')
"""

    result = _run_isolated_controller_state_case(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "same-thread-activation-refused"


def test_invalid_controller_state_boundary_types_are_normalized(
    tmp_path: Path,
) -> None:
    mod = _state()
    root = tmp_path / "controller-state"

    with pytest.raises(mod.ControllerStateRefused):
        mod.issueDiagnosticControllerStateAuthority(
            root=root,
            repository_id=None,
            controller_generation=1,
            process_capability=object(),
            expires_at="2099-01-01T00:00:00+00:00",
        )
    authority = mod.issueDiagnosticControllerStateAuthority(
        root=root,
        repository_id="repo_typed_boundary",
        controller_generation=1,
        process_capability=object(),
        expires_at="2099-01-01T00:00:00+00:00",
    )
    with pytest.raises(mod.ControllerStateRefused):
        mod.ControllerStateStore(root=7, authority=authority)
    assert not root.exists()

    from platform_core.app_config.paths import buildControllerPathsCfg

    with pytest.raises(ValueError):
        buildControllerPathsCfg(
            authority=authority,
            source_root=3,
            installed_root=tmp_path / "installed",
        )


def test_constructor_closes_raw_lock_descriptor_after_post_open_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _state()
    root = tmp_path / "controller-state"
    lock_path = root / mod._LOCK_NAME
    authority = mod.issueDiagnosticControllerStateAuthority(
        root=root,
        repository_id="repo_constructor_descriptor",
        controller_generation=1,
        process_capability=object(),
        expires_at="2099-01-01T00:00:00+00:00",
    )
    real_open = mod.os.open
    real_lstat = mod.os.lstat
    real_open_native_directory = mod.openNativeDirectory
    descriptors: list[int] = []
    handles: list[object] = []

    def track_open(path: object, flags: int, *args, **kwargs) -> int:
        descriptor = real_open(path, flags, *args, **kwargs)
        if Path(path) == lock_path:
            descriptors.append(descriptor)
        return descriptor

    def fail_lock_lstat(path: object, *args, **kwargs):
        if descriptors and Path(path) == lock_path:
            raise OSError(errno.EIO, "injected post-open identity failure")
        return real_lstat(path, *args, **kwargs)

    def track_native_directory(path: Path):
        handle = real_open_native_directory(path)
        handles.append(handle)
        return handle

    with monkeypatch.context() as patch:
        patch.setattr(mod.os, "open", track_open)
        patch.setattr(mod.os, "lstat", fail_lock_lstat)
        patch.setattr(mod, "openNativeDirectory", track_native_directory)
        with pytest.raises(mod.ControllerStateRefused, match="retained safely"):
            mod.ControllerStateStore(root=root, authority=authority)

    assert len(descriptors) == 1
    with pytest.raises(OSError) as closed:
        os.fstat(descriptors[0])
    assert closed.value.errno == errno.EBADF
    assert handles and all(getattr(handle, "_closed", False) for handle in handles)


def test_unlock_failure_poisons_store_and_releases_retained_resources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _state()
    root = tmp_path / "controller-state"
    authority = mod.issueDiagnosticControllerStateAuthority(
        root=root,
        repository_id="repo_unlock_poison",
        controller_generation=1,
        process_capability=object(),
        expires_at="2099-01-01T00:00:00+00:00",
    )
    store = mod.ControllerStateStore(root=root, authority=authority)
    store.writeJson("records/item", {"value": 1}, authority=authority)

    if os.name == "nt":
        import msvcrt

        real_unlocking = msvcrt.locking

        def fail_unlock(descriptor: int, mode: int, count: int) -> None:
            if mode == msvcrt.LK_UNLCK:
                raise OSError(errno.EIO, "injected unlock failure")
            real_unlocking(descriptor, mode, count)

        patch_target = msvcrt
        patch_name = "locking"
        replacement = fail_unlock
    else:
        import fcntl

        real_flock = fcntl.flock

        def fail_flock(descriptor: int, operation: int) -> None:
            if operation == fcntl.LOCK_UN:
                raise OSError(errno.EIO, "injected unlock failure")
            real_flock(descriptor, operation)

        patch_target = fcntl
        patch_name = "flock"
        replacement = fail_flock

    with monkeypatch.context() as patch:
        patch.setattr(patch_target, patch_name, replacement)
        with pytest.raises(mod.ControllerStateRefused, match="release failed.*poisoned"):
            store.readJson("records/item", authority=authority)

    assert store._closed
    assert store._lock_stream.closed
    assert store._handle._closed
    with pytest.raises(mod.ControllerStateRefused, match="closed"):
        store.readJson("records/item", authority=authority)

    replacement_store = mod.ControllerStateStore(root=root, authority=authority)
    assert replacement_store.readJson("records/item", authority=authority) == {
        "value": 1
    }
    replacement_store.close()


def test_authority_expiry_during_process_lock_acquisition_refuses_without_sleep(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod, _root, authority, store = _expiring_store(tmp_path)
    fake_datetime = _install_fake_controller_clock(mod, monkeypatch)
    expired = _AUTHORITY_EXPIRED
    acquisition_attempted = False

    if os.name == "nt":
        import msvcrt

        real_locking = msvcrt.locking

        def expire_while_contended(
            descriptor: int,
            mode: int,
            count: int,
        ) -> None:
            nonlocal acquisition_attempted
            if mode == msvcrt.LK_NBLCK and not acquisition_attempted:
                acquisition_attempted = True
                fake_datetime.current = expired
                raise OSError(errno.EACCES, "injected lock contention")
            real_locking(descriptor, mode, count)

        monkeypatch.setattr(msvcrt, "locking", expire_while_contended)
    else:
        import fcntl

        real_flock = fcntl.flock

        def expire_while_contended(descriptor: int, operation: int) -> None:
            nonlocal acquisition_attempted
            if operation & fcntl.LOCK_NB and not acquisition_attempted:
                acquisition_attempted = True
                fake_datetime.current = expired
                raise OSError(errno.EAGAIN, "injected lock contention")
            real_flock(descriptor, operation)

        monkeypatch.setattr(fcntl, "flock", expire_while_contended)

    monkeypatch.setattr(
        mod.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(
            AssertionError("expired authority entered process-lock backoff")
        ),
    )

    with pytest.raises(mod.ControllerStateRefused, match="expired"):
        store.writeJson("records/item", {"value": 2}, authority=authority)

    assert acquisition_attempted
    fake_datetime.current = _AUTHORITY_LIVE
    assert store.readJson("records/item", authority=authority) == {"value": 1}
    store.close()


def test_authority_expiry_immediately_after_process_lock_refuses_before_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod, _root, authority, store = _expiring_store(tmp_path)
    fake_datetime = _install_fake_controller_clock(mod, monkeypatch)
    expired = _AUTHORITY_EXPIRED
    body_entered = False

    def unexpected_body(_logical_id: str) -> object:
        nonlocal body_entered
        body_entered = True
        raise AssertionError("expired authority entered the store body")

    monkeypatch.setattr(store, "_readJsonUnlocked", unexpected_body)
    if os.name == "nt":
        import msvcrt

        real_locking = msvcrt.locking

        def expire_after_lock(descriptor: int, mode: int, count: int) -> None:
            real_locking(descriptor, mode, count)
            if mode == msvcrt.LK_NBLCK:
                fake_datetime.current = expired

        monkeypatch.setattr(msvcrt, "locking", expire_after_lock)
    else:
        import fcntl

        real_flock = fcntl.flock

        def expire_after_lock(descriptor: int, operation: int) -> None:
            real_flock(descriptor, operation)
            if operation & fcntl.LOCK_NB:
                fake_datetime.current = expired

        monkeypatch.setattr(fcntl, "flock", expire_after_lock)

    with pytest.raises(mod.ControllerStateRefused, match="expired"):
        store.readJson("records/item", authority=authority)

    assert not body_entered
    fake_datetime.current = _AUTHORITY_LIVE
    monkeypatch.undo()
    assert store.readJson("records/item", authority=authority) == {"value": 1}
    store.close()


def test_authority_expiry_after_read_observation_refuses_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod, _root, authority, store = _expiring_store(tmp_path)
    fake_datetime = _install_fake_controller_clock(mod, monkeypatch)
    original_read = store._readJsonUnlocked

    def expire_after_read(logical_id: str) -> object:
        result = original_read(logical_id)
        fake_datetime.current = _AUTHORITY_EXPIRED
        return result

    monkeypatch.setattr(store, "_readJsonUnlocked", expire_after_read)

    with pytest.raises(mod.ControllerStateRefused, match="expired"):
        store.readJson("records/item", authority=authority)

    monkeypatch.undo()
    assert store.readJson("records/item", authority=authority) == {"value": 1}
    store.close()


def test_authority_expiry_after_list_observation_refuses_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod, _root, authority, store = _expiring_store(tmp_path)
    fake_datetime = _install_fake_controller_clock(mod, monkeypatch)
    original_directory = store._directory

    def expiring_directory(parts: tuple[str, ...], *, create: bool):
        directory, opened = original_directory(parts, create=create)
        original_list_entries = directory.listEntries

        def expire_after_list_entries():
            entries = original_list_entries()
            fake_datetime.current = _AUTHORITY_EXPIRED
            return entries

        directory.listEntries = expire_after_list_entries
        return directory, opened

    monkeypatch.setattr(store, "_directory", expiring_directory)

    with pytest.raises(mod.ControllerStateRefused, match="expired"):
        store.listJsonIds("records", authority=authority)

    monkeypatch.undo()
    assert store.listJsonIds("records", authority=authority) == ("records/item",)
    store.close()


def test_authority_expiry_in_update_mutator_refuses_before_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod, _root, authority, store = _expiring_store(tmp_path)
    fake_datetime = _install_fake_controller_clock(mod, monkeypatch)

    def expire_in_mutator(_current: object) -> object:
        fake_datetime.current = _AUTHORITY_EXPIRED
        return {"value": 2}

    with pytest.raises(mod.ControllerStateRefused, match="expired"):
        store.updateJson(
            "records/item",
            default={"value": 0},
            mutate=expire_in_mutator,
            authority=authority,
        )

    monkeypatch.undo()
    assert store.readJson("records/item", authority=authority) == {"value": 1}
    store.close()


def test_authority_expiry_before_delete_effect_preserves_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod, _root, authority, store = _expiring_store(tmp_path)
    fake_datetime = _install_fake_controller_clock(mod, monkeypatch)
    original_directory = store._directory

    def expiring_directory(parts: tuple[str, ...], *, create: bool):
        directory, opened = original_directory(parts, create=create)
        original_list_entries = directory.listEntries

        def expire_after_delete_observation():
            entries = original_list_entries()
            fake_datetime.current = _AUTHORITY_EXPIRED
            return entries

        directory.listEntries = expire_after_delete_observation
        return directory, opened

    monkeypatch.setattr(store, "_directory", expiring_directory)

    with pytest.raises(mod.ControllerStateRefused, match="expired"):
        store.deleteJson("records/item", authority=authority)

    monkeypatch.undo()
    assert store.readJson("records/item", authority=authority) == {"value": 1}
    store.close()


@pytest.mark.parametrize("expiry_point", ("backup", "primary"))
def test_authority_expiry_before_backup_publication_refuses_selected_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    expiry_point: str,
) -> None:
    mod, _root, authority, store = _expiring_store(tmp_path)
    fake_datetime = _install_fake_controller_clock(mod, monkeypatch)
    original_commit = store._commitBytes

    def expire_before_selected_commit(
        logical_id: str,
        payload: bytes,
        *,
        require_live,
        result_commit: bool = True,
    ) -> None:
        selected = "backups/item" if expiry_point == "backup" else "records/item"
        if logical_id == selected:
            fake_datetime.current = _AUTHORITY_EXPIRED
        original_commit(
            logical_id,
            payload,
            require_live=require_live,
            result_commit=result_commit,
        )

    monkeypatch.setattr(store, "_commitBytes", expire_before_selected_commit)

    with pytest.raises(mod.ControllerStateRefused, match="expired"):
        store.replaceJsonWithBackup(
            "records/item",
            "backups/item",
            {"value": 2},
            authority=authority,
        )

    monkeypatch.undo()
    assert store.readJson("records/item", authority=authority) == {"value": 1}
    if expiry_point == "backup":
        with pytest.raises(FileNotFoundError):
            store.readJson("backups/item", authority=authority)
    else:
        assert store.readJson("backups/item", authority=authority) == {"value": 1}
    store.close()


def test_new_document_publication_does_not_depend_on_generic_move(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod, root, authority, store = _expiring_store(tmp_path)

    def unavailable_move(*_args, **_kwargs):
        raise OSError(errno.ENOTSUP, "generic native move is unavailable")

    monkeypatch.setattr(mod.NativeDirectoryHandle, "moveChild", unavailable_move)

    store.writeJson("records/new-item", {"value": 2}, authority=authority)

    assert (root / "records" / "new-item.json").read_bytes() == b'{"value":2}'
    assert store.readJson("records/new-item", authority=authority) == {"value": 2}
    store.close()


def test_create_only_reconcile_accepts_only_an_exact_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod, root, authority, store = _expiring_store(tmp_path)
    reconciled: list[tuple[str, bytes]] = []
    original_reconcile = mod.NativeDirectoryHandle.reconcileCreateOnlyFile

    _hide_next_controller_destination_observation(
        store,
        mod,
        monkeypatch,
        destination_name="item.json",
    )

    def track_reconcile(self, name: str, payload: bytes):
        reconciled.append((name, payload))
        return original_reconcile(self, name, payload)

    def unavailable_move(*_args, **_kwargs):
        raise OSError(errno.ENOTSUP, "generic native move is unavailable")

    monkeypatch.setattr(
        mod.NativeDirectoryHandle,
        "reconcileCreateOnlyFile",
        track_reconcile,
    )
    monkeypatch.setattr(mod.NativeDirectoryHandle, "moveChild", unavailable_move)

    store.writeJson("records/item", {"value": 1}, authority=authority)

    assert reconciled == [("item.json", b'{"value":1}')]
    assert (root / "records" / "item.json").read_bytes() == b'{"value":1}'
    store.close()


def test_create_only_reconcile_refuses_a_changed_unobserved_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod, root, authority, store = _expiring_store(tmp_path)
    _hide_next_controller_destination_observation(
        store,
        mod,
        monkeypatch,
        destination_name="item.json",
    )

    with pytest.raises(mod.ControllerStateRefused, match="ambiguous|poison"):
        store.writeJson("records/item", {"value": 2}, authority=authority)

    assert (root / "records" / "item.json").read_bytes() == b'{"value":1}'
    monkeypatch.undo()
    replacement_store = mod.ControllerStateStore(root=root, authority=authority)
    replacement_store.writeJson("records/item", {"value": 2}, authority=authority)
    assert replacement_store.readJson("records/item", authority=authority) == {
        "value": 2
    }
    replacement_store.close()


def test_authority_is_rechecked_after_destination_observation_before_create_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod, root, authority, store = _expiring_store(tmp_path)
    fake_datetime = _install_fake_controller_clock(mod, monkeypatch)
    original_directory = store._directory
    create_only_called = False

    def expiring_directory(parts: tuple[str, ...], *, create: bool):
        directory, opened = original_directory(parts, create=create)
        if parts != ("records",):
            return directory, opened
        original_list_entries = directory.listEntries

        def expire_after_observation(*args, **kwargs):
            entries = original_list_entries(*args, **kwargs)
            fake_datetime.current = _AUTHORITY_EXPIRED
            return entries

        directory.listEntries = expire_after_observation
        return directory, opened

    def unexpected_create_only(self, name: str, payload: bytes):
        nonlocal create_only_called
        create_only_called = True
        raise AssertionError("expired authority entered create-only publication")

    monkeypatch.setattr(store, "_directory", expiring_directory)
    monkeypatch.setattr(
        mod.NativeDirectoryHandle,
        "reconcileCreateOnlyFile",
        unexpected_create_only,
    )

    with pytest.raises(mod.ControllerStateRefused, match="expired"):
        store.writeJson("records/new-item", {"value": 2}, authority=authority)

    assert not create_only_called
    assert not (root / "records" / "new-item.json").exists()
    store.close()


def test_authority_expiry_after_successful_create_only_returns_committed_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod, root, authority, store = _expiring_store(tmp_path)
    fake_datetime = _install_fake_controller_clock(mod, monkeypatch)
    original_reconcile = mod.NativeDirectoryHandle.reconcileCreateOnlyFile
    create_completed = False

    def expire_after_create(
        self,
        name: str,
        payload: bytes,
    ):
        nonlocal create_completed
        result = original_reconcile(self, name, payload)
        create_completed = True
        fake_datetime.current = _AUTHORITY_EXPIRED
        return result

    monkeypatch.setattr(
        mod.NativeDirectoryHandle,
        "reconcileCreateOnlyFile",
        expire_after_create,
    )

    store.writeJson("records/new-item", {"value": 2}, authority=authority)

    assert create_completed
    assert (root / "records" / "new-item.json").read_bytes() == b'{"value":2}'
    monkeypatch.undo()
    assert store.readJson("records/new-item", authority=authority) == {"value": 2}
    store.close()


def test_authority_expiry_after_successful_replace_returns_committed_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod, root, authority, store = _expiring_store(tmp_path)
    fake_datetime = _install_fake_controller_clock(mod, monkeypatch)
    original_replace = mod.NativeDirectoryHandle.replaceFile
    replace_completed = False

    def expire_after_replace(
        self,
        source_name: str,
        destination_name: str,
        *,
        expected_source=None,
        expected_destination=None,
    ):
        nonlocal replace_completed
        result = original_replace(
            self,
            source_name,
            destination_name,
            expected_source=expected_source,
            expected_destination=expected_destination,
        )
        replace_completed = True
        fake_datetime.current = _AUTHORITY_EXPIRED
        return result

    monkeypatch.setattr(
        mod.NativeDirectoryHandle,
        "replaceFile",
        expire_after_replace,
    )

    store.writeJson("records/item", {"value": 2}, authority=authority)

    assert replace_completed
    assert (root / "records" / "item.json").read_bytes() == b'{"value":2}'
    monkeypatch.undo()
    assert store.readJson("records/item", authority=authority) == {"value": 2}
    store.close()


def test_authority_expiry_after_successful_remove_returns_committed_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod, root, authority, store = _expiring_store(tmp_path)
    fake_datetime = _install_fake_controller_clock(mod, monkeypatch)
    original_remove = mod.NativeDirectoryHandle.removeFile
    remove_completed = False

    def expire_after_remove(self, name: str, *, expected=None) -> None:
        nonlocal remove_completed
        original_remove(self, name, expected=expected)
        remove_completed = True
        fake_datetime.current = _AUTHORITY_EXPIRED

    monkeypatch.setattr(mod.NativeDirectoryHandle, "removeFile", expire_after_remove)

    assert store.deleteJson("records/item", authority=authority)

    assert remove_completed
    assert not (root / "records" / "item.json").exists()
    monkeypatch.undo()
    with pytest.raises(FileNotFoundError):
        store.readJson("records/item", authority=authority)
    store.close()


def test_child_close_failure_after_create_only_preserves_commit_and_poisons_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod, root, authority, store = _expiring_store(tmp_path)
    original_reconcile = mod.NativeDirectoryHandle.reconcileCreateOnlyFile
    original_close = mod.NativeDirectoryHandle.close
    create_completed = False
    close_failure_injected = False

    def track_create(self, name: str, payload: bytes):
        nonlocal create_completed
        result = original_reconcile(self, name, payload)
        create_completed = True
        return result

    def fail_first_child_close_after_create(self) -> None:
        nonlocal close_failure_injected
        if (
            create_completed
            and not close_failure_injected
            and self is not store._handle
        ):
            close_failure_injected = True
            original_close(self)
            raise OSError(errno.EIO, "injected post-create child close failure")
        original_close(self)

    monkeypatch.setattr(
        mod.NativeDirectoryHandle,
        "reconcileCreateOnlyFile",
        track_create,
    )
    monkeypatch.setattr(
        mod.NativeDirectoryHandle,
        "close",
        fail_first_child_close_after_create,
    )

    store.writeJson("records/new-item", {"value": 2}, authority=authority)

    assert create_completed and close_failure_injected
    assert (root / "records" / "new-item.json").read_bytes() == b'{"value":2}'
    assert store._closed
    assert store._lock_stream.closed
    assert store._handle._closed
    with pytest.raises(mod.ControllerStateRefused, match="closed"):
        store.readJson("records/new-item", authority=authority)

    monkeypatch.undo()
    replacement_store = mod.ControllerStateStore(root=root, authority=authority)
    assert replacement_store.readJson("records/new-item", authority=authority) == {
        "value": 2
    }
    replacement_store.close()


def test_child_close_failure_after_replace_preserves_commit_and_poisons_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod, root, authority, store = _expiring_store(tmp_path)
    original_replace = mod.NativeDirectoryHandle.replaceFile
    original_close = mod.NativeDirectoryHandle.close
    replace_completed = False
    close_failure_injected = False

    def track_replace(
        self,
        source_name: str,
        destination_name: str,
        *,
        expected_source=None,
        expected_destination=None,
    ):
        nonlocal replace_completed
        result = original_replace(
            self,
            source_name,
            destination_name,
            expected_source=expected_source,
            expected_destination=expected_destination,
        )
        replace_completed = True
        return result

    def fail_first_child_close_after_replace(self) -> None:
        nonlocal close_failure_injected
        if (
            replace_completed
            and not close_failure_injected
            and self is not store._handle
        ):
            close_failure_injected = True
            original_close(self)
            raise OSError(errno.EIO, "injected post-replace child close failure")
        original_close(self)

    monkeypatch.setattr(mod.NativeDirectoryHandle, "replaceFile", track_replace)
    monkeypatch.setattr(
        mod.NativeDirectoryHandle,
        "close",
        fail_first_child_close_after_replace,
    )

    store.writeJson("records/item", {"value": 2}, authority=authority)

    assert replace_completed and close_failure_injected
    assert (root / "records" / "item.json").read_bytes() == b'{"value":2}'
    assert store._closed
    assert store._lock_stream.closed
    assert store._handle._closed
    with pytest.raises(mod.ControllerStateRefused, match="closed"):
        store.readJson("records/item", authority=authority)

    monkeypatch.undo()
    replacement_store = mod.ControllerStateStore(root=root, authority=authority)
    assert replacement_store.readJson("records/item", authority=authority) == {
        "value": 2
    }
    replacement_store.writeJson("records/lock-proof", True, authority=authority)
    replacement_store.close()


def test_child_close_failure_after_delete_preserves_commit_and_poisons_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod, root, authority, store = _expiring_store(tmp_path)
    original_remove = mod.NativeDirectoryHandle.removeFile
    original_close = mod.NativeDirectoryHandle.close
    remove_completed = False
    close_failure_injected = False

    def track_remove(self, name: str, *, expected=None) -> None:
        nonlocal remove_completed
        original_remove(self, name, expected=expected)
        remove_completed = True

    def fail_first_child_close_after_remove(self) -> None:
        nonlocal close_failure_injected
        if (
            remove_completed
            and not close_failure_injected
            and self is not store._handle
        ):
            close_failure_injected = True
            original_close(self)
            raise OSError(errno.EIO, "injected post-remove child close failure")
        original_close(self)

    monkeypatch.setattr(mod.NativeDirectoryHandle, "removeFile", track_remove)
    monkeypatch.setattr(
        mod.NativeDirectoryHandle,
        "close",
        fail_first_child_close_after_remove,
    )

    assert store.deleteJson("records/item", authority=authority)

    assert remove_completed and close_failure_injected
    assert not (root / "records" / "item.json").exists()
    assert store._closed
    assert store._lock_stream.closed
    assert store._handle._closed
    with pytest.raises(mod.ControllerStateRefused, match="closed"):
        store.listJsonIds("records", authority=authority)

    monkeypatch.undo()
    replacement_store = mod.ControllerStateStore(root=root, authority=authority)
    with pytest.raises(FileNotFoundError):
        replacement_store.readJson("records/item", authority=authority)
    replacement_store.writeJson("records/lock-proof", True, authority=authority)
    replacement_store.close()


def test_backup_close_failure_reports_partial_prefix_and_poisons_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod, root, authority, store = _expiring_store(tmp_path)
    original_reconcile = mod.NativeDirectoryHandle.reconcileCreateOnlyFile
    original_close = mod.NativeDirectoryHandle.close
    backup_completed = False
    close_failure_injected = False

    def track_backup_create(
        self,
        name: str,
        payload: bytes,
    ):
        nonlocal backup_completed
        result = original_reconcile(self, name, payload)
        backup_completed = True
        return result

    def fail_first_child_close_after_backup(self) -> None:
        nonlocal close_failure_injected
        if (
            backup_completed
            and not close_failure_injected
            and self is not store._handle
        ):
            close_failure_injected = True
            original_close(self)
            raise OSError(errno.EIO, "injected post-backup child close failure")
        original_close(self)

    monkeypatch.setattr(
        mod.NativeDirectoryHandle,
        "reconcileCreateOnlyFile",
        track_backup_create,
    )
    monkeypatch.setattr(
        mod.NativeDirectoryHandle,
        "close",
        fail_first_child_close_after_backup,
    )

    with pytest.raises(mod.ControllerStateRefused, match="close|poison"):
        store.replaceJsonWithBackup(
            "records/item",
            "backups/item",
            {"value": 2},
            authority=authority,
        )

    assert backup_completed and close_failure_injected
    assert store._closed
    assert store._lock_stream.closed
    assert store._handle._closed
    monkeypatch.undo()

    replacement_store = mod.ControllerStateStore(root=root, authority=authority)
    assert replacement_store.readJson("records/item", authority=authority) == {
        "value": 1
    }
    assert replacement_store.readJson("backups/item", authority=authority) == {
        "value": 1
    }
    replacement_store.close()


def test_store_close_serializes_with_operations_and_reentrant_close_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _state()
    root = tmp_path / "controller-state"
    authority = mod.issueDiagnosticControllerStateAuthority(
        root=root,
        repository_id="repo_close_serialization",
        controller_generation=1,
        process_capability=object(),
        expires_at="2099-01-01T00:00:00+00:00",
    )
    store = mod.ControllerStateStore(root=root, authority=authority)
    store.writeJson("records/item", {"value": 1}, authority=authority)

    operation_entered = threading.Event()
    release_operation = threading.Event()
    close_started = threading.Event()
    close_finished = threading.Event()
    operation_results: list[object] = []
    operation_errors: list[BaseException] = []
    close_errors: list[BaseException] = []
    original_read = store._readJsonUnlocked

    def blocked_read(logical_id: str) -> object:
        operation_entered.set()
        assert release_operation.wait(timeout=5)
        return original_read(logical_id)

    monkeypatch.setattr(store, "_readJsonUnlocked", blocked_read)

    def run_read() -> None:
        try:
            operation_results.append(
                store.readJson("records/item", authority=authority)
            )
        except BaseException as exc:
            operation_errors.append(exc)

    def run_close() -> None:
        close_started.set()
        try:
            store.close()
        except BaseException as exc:
            close_errors.append(exc)
        finally:
            close_finished.set()

    reader = threading.Thread(target=run_read, name="controller-state-reader")
    closer = threading.Thread(target=run_close, name="controller-state-closer")
    reader.start()
    assert operation_entered.wait(timeout=5)
    closer.start()
    assert close_started.wait(timeout=5)
    assert not close_finished.wait(timeout=0.1), "close returned during an operation"
    release_operation.set()
    reader.join(timeout=5)
    closer.join(timeout=5)

    assert not reader.is_alive()
    assert not closer.is_alive()
    assert operation_results == [{"value": 1}]
    assert not operation_errors
    assert not close_errors
    with pytest.raises(mod.ControllerStateRefused, match="closed"):
        store.readJson("records/item", authority=authority)

    reentrant_store = mod.ControllerStateStore(root=root, authority=authority)

    def close_from_mutate(value: object) -> object:
        reentrant_store.close()
        return value

    with pytest.raises(mod.ControllerStateRefused, match="operation|close"):
        reentrant_store.updateJson(
            "records/item",
            default={"value": 0},
            mutate=close_from_mutate,
            authority=authority,
        )
    assert reentrant_store.readJson("records/item", authority=authority) == {
        "value": 1
    }
    reentrant_store.close()


def test_nested_store_operations_refuse_immediately_and_abort_outer_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _state()
    root = tmp_path / "controller-state"
    authority = mod.issueDiagnosticControllerStateAuthority(
        root=root,
        repository_id="repo_nested_operation",
        controller_generation=1,
        process_capability=object(),
        expires_at="2099-01-01T00:00:00+00:00",
    )
    store = mod.ControllerStateStore(root=root, authority=authority)
    store.writeJson("records/item", {"value": 1}, authority=authority)

    class UnexpectedLockWait(AssertionError):
        pass

    monkeypatch.setattr(
        mod.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(
            UnexpectedLockWait("nested operation waited on its own OS lock")
        ),
    )

    def nested_operations(_current: object) -> object:
        with pytest.raises(mod.ControllerStateRefused, match="nested"):
            store.readJson("records/item", authority=authority)
        with pytest.raises(mod.ControllerStateRefused, match="nested"):
            store.writeJson("records/other", {"value": 9}, authority=authority)
        return {"value": 2}

    with pytest.raises(mod.ControllerStateRefused, match="nested"):
        store.updateJson(
            "records/item",
            default={"value": 0},
            mutate=nested_operations,
            authority=authority,
        )

    assert store.readJson("records/item", authority=authority) == {"value": 1}
    with pytest.raises(FileNotFoundError):
        store.readJson("records/other", authority=authority)
    store.close()


def test_store_accepts_logical_ids_only_and_preserves_previous_value_on_failure(
    tmp_path: Path, monkeypatch
) -> None:
    mod = _state()
    capability = object()
    authority = mod.issueDiagnosticControllerStateAuthority(
        root=tmp_path / "controller-state",
        repository_id="repo_test",
        controller_generation=4,
        process_capability=capability,
        expires_at="2099-01-01T00:00:00+00:00",
    )
    store = mod.ControllerStateStore(root=tmp_path / "controller-state", authority=authority)
    store.writeJson("tasks/task-1", {"status": "pending"}, authority=authority)

    with pytest.raises(mod.ControllerStateRefused):
        store.writeJson("../anchor", {"status": "corrupt"}, authority=authority)

    monkeypatch.setattr(store, "_commitBytes", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        store.writeJson("tasks/task-1", {"status": "done"}, authority=authority)
    assert store.readJson("tasks/task-1", authority=authority) == {"status": "pending"}


def test_store_lists_only_safe_json_children_under_an_exact_logical_prefix(
    tmp_path: Path,
) -> None:
    mod = _state()
    capability = object()
    authority = mod.issueDiagnosticControllerStateAuthority(
        root=tmp_path / "controller-state",
        repository_id="repo_test",
        controller_generation=4,
        process_capability=capability,
        expires_at="2099-01-01T00:00:00+00:00",
    )
    store = mod.ControllerStateStore(
        root=tmp_path / "controller-state", authority=authority
    )
    store.writeJson("tasks/task-2", {"status": "done"}, authority=authority)
    store.writeJson("tasks/task-1", {"status": "pending"}, authority=authority)
    store.writeJson("control/task-3", {"status": "ignored"}, authority=authority)

    assert store.listJsonIds("tasks", authority=authority) == (
        "tasks/task-1",
        "tasks/task-2",
    )
    assert store.listJsonIds("missing", authority=authority) == ()


def test_store_publishes_prior_json_to_backup_in_the_same_exclusive_transaction(
    tmp_path: Path,
) -> None:
    mod = _state()
    capability = object()
    authority = mod.issueDiagnosticControllerStateAuthority(
        root=tmp_path / "controller-state",
        repository_id="repo_test",
        controller_generation=4,
        process_capability=capability,
        expires_at="2099-01-01T00:00:00+00:00",
    )
    store = mod.ControllerStateStore(
        root=tmp_path / "controller-state", authority=authority
    )
    store.writeJson("tasks/task-1", {"status": "created"}, authority=authority)

    store.replaceJsonWithBackup(
        "tasks/task-1",
        "task-backups/task-1",
        {"status": "executing"},
        authority=authority,
    )

    assert store.readJson("tasks/task-1", authority=authority) == {
        "status": "executing"
    }
    assert store.readJson("task-backups/task-1", authority=authority) == {
        "status": "created"
    }


def test_store_backs_up_valid_json_null_before_replacement(tmp_path: Path) -> None:
    mod = _state()
    root = tmp_path / "controller-state"
    authority = mod.issueDiagnosticControllerStateAuthority(
        root=root,
        repository_id="repo_null_backup",
        controller_generation=1,
        process_capability=object(),
        expires_at="2099-01-01T00:00:00+00:00",
    )
    store = mod.ControllerStateStore(root=root, authority=authority)
    store.writeJson("records/item", None, authority=authority)

    store.replaceJsonWithBackup(
        "records/item",
        "backups/item",
        {"value": 2},
        authority=authority,
    )

    assert store.readJson("records/item", authority=authority) == {"value": 2}
    assert store.readJson("backups/item", authority=authority) is None
    store.close()


def test_update_returns_plain_json_value_without_postcommit_deepcopy(
    tmp_path: Path,
) -> None:
    mod = _state()
    root = tmp_path / "controller-state"
    authority = mod.issueDiagnosticControllerStateAuthority(
        root=root,
        repository_id="repo_update_normalization",
        controller_generation=1,
        process_capability=object(),
        expires_at="2099-01-01T00:00:00+00:00",
    )
    store = mod.ControllerStateStore(root=root, authority=authority)

    class FailsDeepcopy(dict):
        def __deepcopy__(self, _memo):
            raise AssertionError("candidate was deep-copied after commit")

    result = store.updateJson(
        "records/item",
        default={},
        mutate=lambda _current: FailsDeepcopy(value=[1, 2, 3]),
        authority=authority,
    )

    assert type(result) is dict
    assert result == {"value": [1, 2, 3]}
    assert store.readJson("records/item", authority=authority) == result
    store.close()


def test_directory_closes_opened_children_when_later_component_is_unsafe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _state()
    root = tmp_path / "controller-state"
    authority = mod.issueDiagnosticControllerStateAuthority(
        root=root,
        repository_id="repo_directory_cleanup",
        controller_generation=1,
        process_capability=object(),
        expires_at="2099-01-01T00:00:00+00:00",
    )
    store = mod.ControllerStateStore(root=root, authority=authority)
    store.writeJson("aa/item", {"value": 1}, authority=authority)
    (root / "aa" / "bb").write_bytes(b"not-a-directory")
    original_open_directory = mod.NativeDirectoryHandle.openDirectory
    opened: list[object] = []

    def track_open_directory(self, name: str, *, expected=None):
        child = original_open_directory(self, name, expected=expected)
        opened.append(child)
        return child

    monkeypatch.setattr(
        mod.NativeDirectoryHandle,
        "openDirectory",
        track_open_directory,
    )

    with pytest.raises(mod.ControllerStateRefused, match="directory identity is unsafe"):
        store.readJson("aa/bb/item", authority=authority)

    assert opened and all(getattr(handle, "_closed", False) for handle in opened)
    store.close()


def test_close_opened_attempts_every_handle_after_one_close_failure() -> None:
    mod = _state()

    class FakeHandle:
        def __init__(self, *, fail: bool = False) -> None:
            self.fail = fail
            self.closed = False

        def close(self) -> None:
            self.closed = True
            if self.fail:
                raise OSError(errno.EIO, "injected child close failure")

    handles = [FakeHandle(), FakeHandle(fail=True), FakeHandle()]

    with pytest.raises(mod.ControllerStateRefused, match="close"):
        mod.ControllerStateStore._closeOpened(handles)

    assert all(handle.closed for handle in handles)


@pytest.mark.parametrize(
    ("operation", "method_name", "setup", "invocation"),
    (
        (
            "create-only",
            "reconcileCreateOnlyFile",
            "",
            "store.writeJson('records/new-item', {'value': 2}, authority=binding.authority)",
        ),
        (
            "replace",
            "replaceFile",
            "store.writeJson('records/item', {'value': 1}, authority=binding.authority)",
            "store.writeJson('records/item', {'value': 2}, authority=binding.authority)",
        ),
        (
            "remove",
            "removeFile",
            "store.writeJson('records/item', {'value': 1}, authority=binding.authority)",
            "store.deleteJson('records/item', authority=binding.authority)",
        ),
    ),
)
def test_installed_native_mutation_then_raise_permanently_poisons_runtime(
    tmp_path: Path,
    operation: str,
    method_name: str,
    setup: str,
    invocation: str,
) -> None:
    code = _runtime_install_prelude(tmp_path) + f"""
binding = state.installControllerRuntimeState(bootstrap_authorities=bundle)
store = binding.store
{setup}
original = getattr(state.NativeDirectoryHandle, {method_name!r})
mutation_completed = False

def mutate_then_raise(self, *args, **kwargs):
    global mutation_completed
    result = original(self, *args, **kwargs)
    mutation_completed = True
    raise OSError('injected {operation} failure after mutation')

setattr(state.NativeDirectoryHandle, {method_name!r}, mutate_then_raise)
try:
    {invocation}
except state.ControllerStateRefused as exc:
    assert 'poison' in str(exc) or 'cleanup' in str(exc)
except OSError as exc:
    raise AssertionError('ambiguous native mutation escaped unclassified') from exc
else:
    raise AssertionError('ambiguous native mutation reported success')
assert mutation_completed
try:
    state.currentControllerRuntimeStateBinding()
except state.ControllerStateRefused as exc:
    assert 'permanently poisoned' in str(exc)
else:
    raise AssertionError('central runtime remained live after ambiguous mutation')
try:
    bootstrap.validateInstalledBootstrapAuthorities(bundle)
except bootstrap.BootstrapAuthorityRefused:
    pass
else:
    raise AssertionError('bootstrap bundle remained live after ambiguous mutation')
print('installed-{operation}-ambiguity-poisoned')
"""

    result = _run_isolated_controller_state_case(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        f"installed-{operation}-ambiguity-poisoned"
    )


@pytest.mark.parametrize("operation", ("read", "list", "traversal"))
def test_installed_child_close_failure_permanently_poisons_runtime(
    tmp_path: Path,
    operation: str,
) -> None:
    setup = {
        "read": "store.writeJson('records/item', {'value': 1}, authority=binding.authority)",
        "list": "store.writeJson('records/item', {'value': 1}, authority=binding.authority)",
        "traversal": "\n".join(
            (
                "store.writeJson('aa/item', {'value': 1}, authority=binding.authority)",
                "(Path(scope.controller_state_root) / 'aa' / 'bb').write_bytes(b'unsafe')",
            )
        ),
    }[operation]
    invocation = {
        "read": "store.readJson('records/item', authority=binding.authority)",
        "list": "store.listJsonIds('records', authority=binding.authority)",
        "traversal": "store.readJson('aa/bb/item', authority=binding.authority)",
    }[operation]
    code = _runtime_install_prelude(tmp_path) + f"""
binding = state.installControllerRuntimeState(bootstrap_authorities=bundle)
store = binding.store
{setup}
original_close = state.NativeDirectoryHandle.close
close_failure_injected = False

def fail_first_child_close(self):
    global close_failure_injected
    if not close_failure_injected and self is not store._handle:
        close_failure_injected = True
        original_close(self)
        raise OSError('injected {operation} child close failure')
    original_close(self)

state.NativeDirectoryHandle.close = fail_first_child_close
try:
    {invocation}
except state.ControllerStateRefused as exc:
    assert 'close' in str(exc) or 'poison' in str(exc)
else:
    raise AssertionError('child cleanup ambiguity reported success')
assert close_failure_injected
try:
    state.currentControllerRuntimeStateBinding()
except state.ControllerStateRefused as exc:
    assert 'permanently poisoned' in str(exc)
else:
    raise AssertionError('central runtime remained live after child cleanup ambiguity')
try:
    bootstrap.validateInstalledBootstrapAuthorities(bundle)
except bootstrap.BootstrapAuthorityRefused:
    pass
else:
    raise AssertionError('bootstrap bundle remained live after child cleanup ambiguity')
print('installed-{operation}-close-poisoned')
"""

    result = _run_isolated_controller_state_case(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        f"installed-{operation}-close-poisoned"
    )


def test_installed_postcommit_close_failure_returns_result_then_poisons_runtime(
    tmp_path: Path,
) -> None:
    code = _runtime_install_prelude(tmp_path) + """
binding = state.installControllerRuntimeState(bootstrap_authorities=bundle)
store = binding.store
store.writeJson('records/item', {'value': 1}, authority=binding.authority)
original_replace = state.NativeDirectoryHandle.replaceFile
original_close = state.NativeDirectoryHandle.close
replace_completed = False
close_failure_injected = False

def track_replace(self, *args, **kwargs):
    global replace_completed
    result = original_replace(self, *args, **kwargs)
    replace_completed = True
    return result

def fail_first_postcommit_child_close(self):
    global close_failure_injected
    if replace_completed and not close_failure_injected and self is not store._handle:
        close_failure_injected = True
        original_close(self)
        raise OSError('injected installed postcommit close failure')
    original_close(self)

state.NativeDirectoryHandle.replaceFile = track_replace
state.NativeDirectoryHandle.close = fail_first_postcommit_child_close
store.writeJson('records/item', {'value': 2}, authority=binding.authority)
assert replace_completed and close_failure_injected
assert (Path(scope.controller_state_root) / 'records' / 'item.json').read_bytes() == b'{"value":2}'
try:
    state.currentControllerRuntimeStateBinding()
except state.ControllerStateRefused as exc:
    assert 'permanently poisoned' in str(exc)
else:
    raise AssertionError('central runtime remained live after postcommit cleanup ambiguity')
try:
    bootstrap.validateInstalledBootstrapAuthorities(bundle)
except bootstrap.BootstrapAuthorityRefused:
    pass
else:
    raise AssertionError('bootstrap bundle remained live after postcommit cleanup ambiguity')
print('installed-postcommit-close-poisoned')
"""

    result = _run_isolated_controller_state_case(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "installed-postcommit-close-poisoned"
    )


def test_runtime_install_api_accepts_only_one_keyword_bundle() -> None:
    parameters = inspect.signature(
        _state().installControllerRuntimeState
    ).parameters

    assert tuple(parameters) == ("bootstrap_authorities",)
    assert parameters["bootstrap_authorities"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["bootstrap_authorities"].default is inspect.Parameter.empty


def test_runtime_install_derives_one_central_binding_without_consumer_imports(
    tmp_path: Path,
) -> None:
    code = _runtime_install_prelude(tmp_path) + """
from platform_core.app_config._env import controllerConfigActive
from platform_core.app_config.paths import controllerPathsActive

assert not any(name in sys.modules for name in consumer_modules)
binding = state.installControllerRuntimeState(bootstrap_authorities=bundle)
assert binding is state.installControllerRuntimeState(bootstrap_authorities=bundle)
assert binding is state.currentControllerRuntimeStateBinding()
assert binding.bootstrap_authorities is bundle
assert binding.authority is bundle.controller_state_authority
assert binding.store._authority is bundle.controller_state_authority
assert binding.source_root == scope.source_root
assert binding.installed_root == scope.installed_controller_root
assert binding.store._root == Path(scope.controller_state_root)
assert controllerConfigActive()
assert controllerPathsActive()
assert not any(name in sys.modules for name in consumer_modules)

from platform_core.runtime import control_store
from platform_core.runtime import heartbeat
from state import task_io
from notifications.surfaces import terminal_ipc
for module in (control_store, heartbeat, task_io, terminal_ipc):
    resolved = module._binding()
    assert resolved.store is binding.store
    assert resolved.authority is binding.authority
print('runtime-bundle-installed')
"""

    result = _run_isolated_controller_state_case(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "runtime-bundle-installed"


def test_runtime_install_clean_precommit_failure_rolls_back_and_retries(
    tmp_path: Path,
) -> None:
    code = _runtime_install_prelude(tmp_path) + """
from platform_core.app_config._env import controllerConfigActive
from platform_core.app_config.paths import controllerPathsActive

closed = []
original_close = state.ControllerStateStore.close
def observing_close(store):
    try:
        return original_close(store)
    finally:
        closed.append(store)
state.ControllerStateStore.close = observing_close

class InjectedPrecommitFailure(RuntimeError):
    pass
def failpoint(stage):
    if stage == 'store_prepared':
        raise InjectedPrecommitFailure(stage)
state._RUNTIME_INSTALL_FAILPOINT = failpoint

try:
    state.installControllerRuntimeState(bootstrap_authorities=bundle)
except InjectedPrecommitFailure:
    pass
else:
    raise AssertionError('precommit failure was not injected')
assert not controllerConfigActive()
assert not controllerPathsActive()
assert not any(name in sys.modules for name in consumer_modules)
assert closed and closed[0]._closed
assert bootstrap.validateInstalledBootstrapAuthorities(bundle) is bundle
try:
    state.currentControllerRuntimeStateBinding()
except state.ControllerStateRefused as exc:
    assert 'unavailable' in str(exc) or 'pending' in str(exc)
else:
    raise AssertionError('precommit failure published a runtime binding')

state._RUNTIME_INSTALL_FAILPOINT = lambda _stage: None
binding = state.installControllerRuntimeState(bootstrap_authorities=bundle)
assert binding.authority is bundle.controller_state_authority
assert controllerConfigActive() and controllerPathsActive()
print('runtime-precommit-rollback-retried')
"""

    result = _run_isolated_controller_state_case(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert (
        result.stdout.strip().splitlines()[-1]
        == "runtime-precommit-rollback-retried"
    )


def test_runtime_install_postcommit_failure_poison_is_permanent(
    tmp_path: Path,
) -> None:
    code = _runtime_install_prelude(tmp_path) + """
from platform_core.app_config._env import controllerConfigActive
from platform_core.app_config.paths import controllerPathsActive

closed = []
original_close = state.ControllerStateStore.close
def observing_close(store):
    try:
        return original_close(store)
    finally:
        closed.append(store)
state.ControllerStateStore.close = observing_close

class InjectedPostcommitFailure(RuntimeError):
    pass
def failpoint(stage):
    if stage == 'paths_committed':
        raise InjectedPostcommitFailure(stage)
state._RUNTIME_INSTALL_FAILPOINT = failpoint

try:
    state.installControllerRuntimeState(bootstrap_authorities=bundle)
except state.ControllerStateRefused as exc:
    assert 'poison' in str(exc) or 'runtime install' in str(exc)
    assert isinstance(exc.__cause__, InjectedPostcommitFailure)
else:
    raise AssertionError('postcommit failure was not injected')
assert controllerConfigActive() and controllerPathsActive()
assert not any(name in sys.modules for name in consumer_modules)
assert closed and closed[0]._closed
for operation in (
    lambda: bootstrap.validateInstalledBootstrapAuthorities(bundle),
    lambda: state.currentControllerRuntimeStateBinding(),
    lambda: state.installControllerRuntimeState(bootstrap_authorities=bundle),
):
    try:
        operation()
    except Exception as exc:
        assert 'poison' in str(exc) or 'live' in str(exc) or 'revoked' in str(exc)
    else:
        raise AssertionError('poisoned runtime operation unexpectedly succeeded')
print('runtime-postcommit-poisoned')
"""

    result = _run_isolated_controller_state_case(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "runtime-postcommit-poisoned"


def test_runtime_install_postcommit_poison_reason_is_closed_and_bounded(
    tmp_path: Path,
) -> None:
    code = _runtime_install_prelude(tmp_path) + """
LongNamedFailure = type('X' * 300, (RuntimeError,), {})
def failpoint(stage):
    if stage == 'paths_committed':
        raise LongNamedFailure(stage)
state._RUNTIME_INSTALL_FAILPOINT = failpoint
authority = bundle.controller_state_authority
authority_root = authority.root
try:
    state.installControllerRuntimeState(bootstrap_authorities=bundle)
except state.ControllerStateRefused as exc:
    assert 'poison' in str(exc)
else:
    raise AssertionError('long exception name bypassed postcommit poison')
for operation in (
    lambda: bootstrap.validateInstalledBootstrapAuthorities(bundle),
    lambda: state.validateControllerStateAuthority(authority),
    lambda: state.ControllerStateStore(root=authority_root, authority=authority),
):
    try:
        operation()
    except Exception as exc:
        assert 'poison' in str(exc) or 'live' in str(exc) or 'issuer' in str(exc)
    else:
        raise AssertionError('malicious poison reason left a descendant live')
print('runtime-postcommit-poison-reason-bounded')
"""

    result = _run_isolated_controller_state_case(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "runtime-postcommit-poison-reason-bounded"
    )


def test_diagnostic_runtime_install_refuses_before_paths_or_root_effects(
    tmp_path: Path,
) -> None:
    external = tmp_path / "external" / "repo-1"
    external.parent.mkdir(parents=True)
    code = f"""
import sys
from platform_core.app_config._env import controllerConfigActive
from platform_core.app_config.paths import controllerPathsActive
from platform_core.runtime.controller_state import (
    ControllerStateRefused,
    installControllerRuntimeState,
    issueDiagnosticControllerStateAuthority,
)

consumer_modules = (
    'notifications.surfaces.terminal_ipc',
    'platform_core.runtime.control_store',
    'platform_core.runtime.heartbeat',
    'state.task_io',
)
assert not any(name in sys.modules for name in consumer_modules)

capability = object()
authority = issueDiagnosticControllerStateAuthority(
    root={str(external)!r}, repository_id='repo_runtime_state_test',
    controller_generation=9, process_capability=capability,
    expires_at='2099-01-01T00:00:00+00:00')
try:
    installControllerRuntimeState(
        bootstrap_authorities=authority,
    )
except ControllerStateRefused as exc:
    assert 'installed bootstrap bundle' in str(exc)
else:
    raise AssertionError('diagnostic runtime installation unexpectedly succeeded')
assert not controllerPathsActive()
assert not controllerConfigActive()
assert not any(name in sys.modules for name in consumer_modules)
print('diagnostic-runtime-refused-without-effects')
"""

    result = _run_isolated_controller_state_case(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert (
        result.stdout.strip().splitlines()[-1]
        == "diagnostic-runtime-refused-without-effects"
    )
    assert not external.exists()


def test_public_paths_cannot_consume_installed_runtime_authority(
    tmp_path: Path,
) -> None:
    code = _runtime_install_prelude(tmp_path) + """
from platform_core.app_config._env import controllerConfigActive
from platform_core.app_config.paths import (
    buildControllerPathsCfg,
    controllerPathsActive,
    installControllerPaths,
    reserveControllerPathsInstallation,
)

class ExplodingPath:
    def __fspath__(self):
        raise AssertionError('public path API observed caller roots')

try:
    installControllerPaths(
        authority=bundle.controller_state_authority,
        source_root=ExplodingPath(),
        installed_root=ExplodingPath(),
    )
except state.ControllerStateRefused as exc:
    assert 'runtime composition permit' in str(exc)
else:
    raise AssertionError('public path API consumed an installed authority')
assert not controllerConfigActive()
assert not controllerPathsActive()
binding = state.installControllerRuntimeState(bootstrap_authorities=bundle)
assert binding.authority is bundle.controller_state_authority
print('public-installed-path-bypass-refused')
"""

    result = _run_isolated_controller_state_case(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "public-installed-path-bypass-refused"
    )


def test_public_store_constructor_cannot_consume_installed_authority(
    tmp_path: Path,
) -> None:
    code = _runtime_install_prelude(tmp_path) + """
authority = bundle.controller_state_authority
root = Path(scope.controller_state_root)
before = {
    str(path.relative_to(root)): path.read_bytes()
    for path in sorted(root.rglob('*'))
    if path.is_file()
}
try:
    state.ControllerStateStore(root=root, authority=authority)
except state.ControllerStateRefused as exc:
    assert 'runtime composition' in str(exc) or 'installed store' in str(exc)
else:
    raise AssertionError('public store constructor consumed installed authority')
after = {
    str(path.relative_to(root)): path.read_bytes()
    for path in sorted(root.rglob('*'))
    if path.is_file()
}
assert after == before
binding = state.installControllerRuntimeState(bootstrap_authorities=bundle)
assert binding.store._authority is authority
print('public-installed-store-bypass-refused')
"""

    result = _run_isolated_controller_state_case(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "public-installed-store-bypass-refused"
    )


@pytest.mark.parametrize("path_variant", ("equal", "different"))
def test_prior_diagnostic_path_publication_blocks_runtime_install(
    tmp_path: Path,
    path_variant: str,
) -> None:
    source = (
        tmp_path / "runtime-install-case" / "source-a"
        if path_variant == "equal"
        else tmp_path / "competing-source"
    )
    installed = (
        tmp_path / "runtime-install-case" / "installed-a"
        if path_variant == "equal"
        else tmp_path / "competing-installed"
    )
    diagnostic_root = tmp_path / "competing-controller-state"
    code = _runtime_install_prelude(tmp_path) + f"""
from platform_core.app_config._env import controllerConfigActive
from platform_core.app_config.paths import controllerPathsActive, installControllerPaths

diagnostic = state.issueDiagnosticControllerStateAuthority(
    root={str(diagnostic_root)!r},
    repository_id='repo_competing_paths',
    controller_generation=1,
    process_capability=object(),
    expires_at='2099-01-01T00:00:00+00:00',
)
installControllerPaths(
    authority=diagnostic,
    source_root={str(source)!r},
    installed_root={str(installed)!r},
)
assert controllerConfigActive() and controllerPathsActive()
def snapshot(root):
    return {{
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob('*'))
        if path.is_file()
    }}
before = snapshot(Path(scope.controller_state_root))
try:
    state.installControllerRuntimeState(bootstrap_authorities=bundle)
except RuntimeError as exc:
    assert 'fresh unpublished process' in str(exc)
else:
    raise AssertionError('runtime installer adopted a competing path publication')
assert snapshot(Path(scope.controller_state_root)) == before
try:
    state.currentControllerRuntimeStateBinding()
except state.ControllerStateRefused as exc:
    assert 'unavailable' in str(exc)
else:
    raise AssertionError('competing path publication created a runtime binding')
print('prior-{path_variant}-paths-refused')
"""

    result = _run_isolated_controller_state_case(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        f"prior-{path_variant}-paths-refused"
    )


def test_runtime_install_precommit_close_failure_poison_is_permanent(
    tmp_path: Path,
) -> None:
    code = _runtime_install_prelude(tmp_path) + """
from platform_core.app_config._env import controllerConfigActive
from platform_core.app_config.paths import controllerPathsActive

original_close = state.ControllerStateStore.close
def ambiguous_close(store):
    original_close(store)
    raise OSError('injected close failure')
state.ControllerStateStore.close = ambiguous_close
state._RUNTIME_INSTALL_FAILPOINT = lambda stage: (
    (_ for _ in ()).throw(RuntimeError(stage))
    if stage == 'store_prepared'
    else None
)
try:
    state.installControllerRuntimeState(bootstrap_authorities=bundle)
except state.ControllerStateRefused as exc:
    assert 'ambiguous' in str(exc) and 'poison' in str(exc)
else:
    raise AssertionError('ambiguous precommit cleanup did not poison')
assert not controllerConfigActive()
assert not controllerPathsActive()
for operation in (
    lambda: bootstrap.validateInstalledBootstrapAuthorities(bundle),
    lambda: state.currentControllerRuntimeStateBinding(),
    lambda: state.installControllerRuntimeState(bootstrap_authorities=bundle),
):
    try:
        operation()
    except Exception as exc:
        assert 'poison' in str(exc) or 'live' in str(exc) or 'revoked' in str(exc)
    else:
        raise AssertionError('ambiguous cleanup left an authority live')
print('runtime-precommit-close-poisoned')
"""

    result = _run_isolated_controller_state_case(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "runtime-precommit-close-poisoned"
    )


def test_runtime_install_constructor_cleanup_ambiguity_poison_is_permanent(
    tmp_path: Path,
) -> None:
    code = _runtime_install_prelude(tmp_path) + """
from platform_core.app_config._env import controllerConfigActive
from platform_core.app_config.paths import controllerPathsActive

real_fdopen = state.os.fdopen
class AmbiguousCloseStream:
    def __init__(self, inner):
        self.inner = inner
    def __getattr__(self, name):
        return getattr(self.inner, name)
    def close(self):
        self.inner.close()
        raise OSError('injected constructor stream close failure')

state.os.fdopen = lambda *args, **kwargs: AmbiguousCloseStream(
    real_fdopen(*args, **kwargs)
)
state.threading.RLock = lambda: (_ for _ in ()).throw(
    RuntimeError('injected post-stream constructor failure')
)

try:
    state.installControllerRuntimeState(bootstrap_authorities=bundle)
except state.ControllerStateRefused as exc:
    assert 'poison' in str(exc) or 'ambiguous' in str(exc)
else:
    raise AssertionError('constructor cleanup ambiguity did not poison')
assert not controllerConfigActive()
assert not controllerPathsActive()
assert isinstance(
    state._RUNTIME_INSTALL_TERMINAL,
    state._PoisonedControllerRuntimeStateInstallation,
)
for operation in (
    lambda: bootstrap.validateInstalledBootstrapAuthorities(bundle),
    lambda: state.currentControllerRuntimeStateBinding(),
    lambda: state.installControllerRuntimeState(bootstrap_authorities=bundle),
):
    try:
        operation()
    except Exception as exc:
        assert 'poison' in str(exc) or 'live' in str(exc) or 'revoked' in str(exc)
    else:
        raise AssertionError('constructor cleanup ambiguity left authority reusable')
print('runtime-constructor-cleanup-poisoned')
"""

    result = _run_isolated_controller_state_case(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "runtime-constructor-cleanup-poisoned"
    )


def test_runtime_install_precommit_reservation_unwind_failure_poison_is_permanent(
    tmp_path: Path,
) -> None:
    code = _runtime_install_prelude(tmp_path) + """
import platform_core.app_config.paths as paths_module

class FailFirstRelease:
    def __init__(self, inner):
        self.inner = inner
        self.failed = False

    def acquire(self, *args, **kwargs):
        return self.inner.acquire(*args, **kwargs)

    def release(self):
        self.inner.release()
        if not self.failed:
            self.failed = True
            raise OSError('injected reservation unwind failure')

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_args):
        self.release()

paths_module._ENV_LOCK = FailFirstRelease(paths_module._ENV_LOCK)
state._RUNTIME_INSTALL_FAILPOINT = lambda stage: (
    (_ for _ in ()).throw(RuntimeError(stage))
    if stage == 'store_prepared'
    else None
)
try:
    state.installControllerRuntimeState(bootstrap_authorities=bundle)
except state.ControllerStateRefused as exc:
    assert 'poison' in str(exc) or 'ambiguous' in str(exc)
else:
    raise AssertionError('reservation unwind failure did not fail closed')
for operation in (
    lambda: bootstrap.validateInstalledBootstrapAuthorities(bundle),
    lambda: state.currentControllerRuntimeStateBinding(),
    lambda: state.installControllerRuntimeState(bootstrap_authorities=bundle),
):
    try:
        operation()
    except Exception as exc:
        assert 'poison' in str(exc) or 'live' in str(exc) or 'revoked' in str(exc)
    else:
        raise AssertionError('reservation unwind failure left authority reusable')
print('runtime-reservation-unwind-poisoned')
"""

    result = _run_isolated_controller_state_case(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "runtime-reservation-unwind-poisoned"
    )


def test_inactive_path_poison_blocks_all_diagnostic_and_legacy_boundaries(
    tmp_path: Path,
) -> None:
    diagnostic_root = tmp_path / "diagnostic-before-poison"
    replacement_root = tmp_path / "diagnostic-after-poison"
    legacy_marker = tmp_path / "legacy-after-poison.txt"
    code = _runtime_install_prelude(tmp_path) + f"""
from platform_core.app_config._env import controllerConfigActive
from platform_core.app_config.paths import (
    buildControllerPathsCfg,
    controllerPathsActive,
    installControllerPaths,
    reserveControllerPathsInstallation,
)
from platform_core.execution.pre_execution import PreExecutionUnavailable, mutateLegacyPath

diagnostic = state.issueDiagnosticControllerStateAuthority(
    root={str(diagnostic_root)!r},
    repository_id='repo_diagnostic_before_poison',
    controller_generation=1,
    process_capability=object(),
    expires_at='2099-01-01T00:00:00+00:00',
)
diagnostic_store = state.ControllerStateStore(
    root={str(diagnostic_root)!r}, authority=diagnostic
)
diagnostic_store.writeJson('records/item', {{'value': 1}}, authority=diagnostic)
before = (Path({str(diagnostic_root)!r}) / 'records' / 'item.json').read_bytes()

original_close = state.ControllerStateStore.close
def ambiguous_installed_close(store):
    original_close(store)
    if store._authority is bundle.controller_state_authority:
        raise OSError('injected installed-store close failure')
state.ControllerStateStore.close = ambiguous_installed_close
state._RUNTIME_INSTALL_FAILPOINT = lambda stage: (
    (_ for _ in ()).throw(RuntimeError(stage))
    if stage == 'store_prepared'
    else None
)
try:
    state.installControllerRuntimeState(bootstrap_authorities=bundle)
except state.ControllerStateRefused as exc:
    assert 'ambiguous' in str(exc) and 'poison' in str(exc)
else:
    raise AssertionError('injected cleanup ambiguity did not poison')
assert not controllerConfigActive() and not controllerPathsActive()

class ExplodingPath:
    def __fspath__(self):
        raise AssertionError('poisoned runtime observed a caller-controlled path')

for build in (buildControllerPathsCfg, reserveControllerPathsInstallation):
    try:
        build(
            authority=diagnostic,
            source_root=ExplodingPath(),
            installed_root=ExplodingPath(),
        )
    except state.ControllerStateRefused as exc:
        assert 'absent' in str(exc) or 'runtime' in str(exc)
    else:
        raise AssertionError('poisoned runtime allowed diagnostic path observation')

operations = (
    lambda: diagnostic_store.writeJson(
        'records/item', {{'value': 2}}, authority=diagnostic
    ),
    lambda: state.ControllerStateStore(
        root={str(replacement_root)!r}, authority=diagnostic
    ),
    lambda: state.issueDiagnosticControllerStateAuthority(
        root={str(replacement_root)!r},
        repository_id='repo_diagnostic_after_poison',
        controller_generation=1,
        process_capability=object(),
        expires_at='2099-01-01T00:00:00+00:00',
    ),
    lambda: installControllerPaths(
        authority=diagnostic,
        source_root={str(tmp_path / 'poisoned-source')!r},
        installed_root={str(tmp_path / 'poisoned-installed')!r},
    ),
    lambda: mutateLegacyPath(
        Path({str(legacy_marker)!r}).write_text,
        'forbidden',
        encoding='utf-8',
    ),
)
for operation in operations:
    try:
        operation()
    except (RuntimeError, PreExecutionUnavailable) as exc:
        assert 'runtime' in str(exc) or 'absent' in str(exc) or 'legacy' in str(exc)
    else:
        raise AssertionError('inactive-path poison allowed a diagnostic effect')
assert (Path({str(diagnostic_root)!r}) / 'records' / 'item.json').read_bytes() == before
assert not Path({str(replacement_root)!r}).exists()
assert not Path({str(legacy_marker)!r}).exists()
assert not controllerConfigActive() and not controllerPathsActive()
print('inactive-path-poison-blocked-diagnostic-boundaries')
"""

    result = _run_isolated_controller_state_case(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "inactive-path-poison-blocked-diagnostic-boundaries"
    )


def test_runtime_install_concurrent_exact_replay_returns_one_binding(
    tmp_path: Path,
) -> None:
    code = _runtime_install_prelude(tmp_path) + """
import threading

barrier = threading.Barrier(3)
results = []
errors = []
def install():
    barrier.wait(timeout=5)
    try:
        results.append(
            state.installControllerRuntimeState(bootstrap_authorities=bundle)
        )
    except BaseException as exc:
        errors.append(exc)

threads = [threading.Thread(target=install) for _ in range(2)]
for thread in threads:
    thread.start()
barrier.wait(timeout=5)
for thread in threads:
    thread.join(timeout=10)
assert not any(thread.is_alive() for thread in threads)
assert errors == []
assert len(results) == 2
assert results[0] is results[1]
assert results[0] is state.currentControllerRuntimeStateBinding()
print('runtime-concurrent-replay-singleton')
"""

    result = _run_isolated_controller_state_case(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "runtime-concurrent-replay-singleton"
    )


def test_runtime_install_replay_revalidates_admission_after_waiting(
    tmp_path: Path,
) -> None:
    code = _runtime_install_prelude(tmp_path) + """
import threading

binding = state.installControllerRuntimeState(bootstrap_authorities=bundle)
initial_validation_finished = threading.Event()
original_validate = bootstrap.validateInstalledBootstrapAuthorities
def observing_validate(value):
    result = original_validate(value)
    if threading.current_thread().name == 'runtime-replay':
        initial_validation_finished.set()
    return result
bootstrap.validateInstalledBootstrapAuthorities = observing_validate

results = []
errors = []
def replay():
    try:
        results.append(
            state.installControllerRuntimeState(bootstrap_authorities=bundle)
        )
    except BaseException as exc:
        errors.append(exc)

with state._RUNTIME_BINDING_LOCK:
    replay_thread = threading.Thread(target=replay, name='runtime-replay')
    replay_thread.start()
    assert initial_validation_finished.wait(timeout=5)
    issuer = bundle.landing_issuer
    admission = bundle.run_admission
    issuer.revokeRunAdmission(admission)
replay_thread.join(timeout=10)
assert not replay_thread.is_alive()
assert results == []
assert len(errors) == 1
assert isinstance(errors[0], state.ControllerStateRefused)
assert 'live' in str(errors[0]) or 'admission' in str(errors[0])
try:
    state.currentControllerRuntimeStateBinding()
except state.ControllerStateRefused:
    pass
else:
    raise AssertionError('revoked admission remained current after replay race')
assert binding.store is not None
print('runtime-replay-revalidated-after-wait')
"""

    result = _run_isolated_controller_state_case(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "runtime-replay-revalidated-after-wait"
    )


def test_installed_store_refuses_stale_use_after_run_admission_revocation(
    tmp_path: Path,
) -> None:
    code = _runtime_install_prelude(tmp_path) + """
binding = state.installControllerRuntimeState(bootstrap_authorities=bundle)
issuer = bundle.landing_issuer
issuer.revokeRunAdmission(bundle.run_admission)
try:
    binding.store.writeJson(
        'stale/record',
        {'value': 'forbidden'},
        authority=binding.authority,
    )
except state.ControllerStateRefused as exc:
    assert 'live' in str(exc) or 'admission' in str(exc) or 'bootstrap' in str(exc)
else:
    raise AssertionError('stale raw installed store survived admission revocation')
assert not (Path(scope.controller_state_root) / 'stale' / 'record.json').exists()
print('installed-store-stale-admission-refused')
"""

    result = _run_isolated_controller_state_case(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "installed-store-stale-admission-refused"
    )


def test_installed_store_transaction_serializes_run_admission_revocation(
    tmp_path: Path,
) -> None:
    code = _runtime_install_prelude(tmp_path) + """
import threading

binding = state.installControllerRuntimeState(bootstrap_authorities=bundle)
entered_commit = threading.Event()
release_commit = threading.Event()
revocation_started = threading.Event()
revocation_finished = threading.Event()
errors = []
original_commit = state.ControllerStateStore._commitBytes

def blocking_commit(store, logical_id, *args, **kwargs):
    if logical_id == 'serialized/record':
        entered_commit.set()
        if not release_commit.wait(timeout=5):
            raise AssertionError('installed-store commit was not released')
    return original_commit(store, logical_id, *args, **kwargs)

state.ControllerStateStore._commitBytes = blocking_commit

def write_record():
    try:
        binding.store.writeJson(
            'serialized/record',
            {'value': 1},
            authority=binding.authority,
        )
    except BaseException as exc:
        errors.append(exc)

def revoke_admission():
    revocation_started.set()
    bundle.landing_issuer.revokeRunAdmission(bundle.run_admission)
    revocation_finished.set()

writer = threading.Thread(target=write_record)
writer.start()
assert entered_commit.wait(timeout=5)
revoker = threading.Thread(target=revoke_admission)
revoker.start()
assert revocation_started.wait(timeout=5)
assert not revocation_finished.wait(timeout=0.25)
release_commit.set()
writer.join(timeout=5)
revoker.join(timeout=5)
assert not writer.is_alive() and not revoker.is_alive()
assert errors == []
assert revocation_finished.is_set()
assert (Path(scope.controller_state_root) / 'serialized' / 'record.json').read_bytes() == b'{"value":1}'
try:
    binding.store.writeJson(
        'serialized/late',
        {'value': 2},
        authority=binding.authority,
    )
except state.ControllerStateRefused:
    pass
else:
    raise AssertionError('post-revocation installed-store write succeeded')
print('installed-store-admission-revocation-serialized')
"""

    result = _run_isolated_controller_state_case(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "installed-store-admission-revocation-serialized"
    )


def test_runtime_install_rejects_foreign_live_bundle_without_rebinding(
    tmp_path: Path,
) -> None:
    code = _runtime_install_prelude(tmp_path) + """
_scope_b, _spawn_b, outer_b = fixture['_consume_outer'](case_root, suffix='b')
bundle_b = bootstrap.deriveInstalledBootstrapAuthorities(
    outer_capabilities=outer_b
)
binding = state.installControllerRuntimeState(bootstrap_authorities=bundle)
try:
    state.installControllerRuntimeState(bootstrap_authorities=bundle_b)
except state.ControllerStateRefused as exc:
    assert 'different facts' in str(exc)
else:
    raise AssertionError('foreign bundle rebound the live runtime')
assert state.currentControllerRuntimeStateBinding() is binding
assert bootstrap.validateInstalledBootstrapAuthorities(bundle_b) is bundle_b
print('runtime-foreign-bundle-refused')
"""

    result = _run_isolated_controller_state_case(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "runtime-foreign-bundle-refused"
    )


def test_runtime_install_revoked_initial_admission_has_zero_effects(
    tmp_path: Path,
) -> None:
    code = _runtime_install_prelude(tmp_path) + """
from platform_core.app_config._env import controllerConfigActive
from platform_core.app_config.paths import controllerPathsActive

issuer = bundle.landing_issuer
admission = bundle.run_admission
def snapshot(root):
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob('*'))
        if path.is_file()
    }
before = snapshot(Path(scope.controller_state_root))
issuer.revokeRunAdmission(admission)
try:
    state.installControllerRuntimeState(bootstrap_authorities=bundle)
except state.ControllerStateRefused as exc:
    assert 'live installed bootstrap bundle' in str(exc)
else:
    raise AssertionError('revoked initial admission installed runtime state')
assert not controllerConfigActive()
assert not controllerPathsActive()
assert snapshot(Path(scope.controller_state_root)) == before
print('runtime-revoked-admission-zero-effects')
"""

    result = _run_isolated_controller_state_case(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "runtime-revoked-admission-zero-effects"
    )


def test_installed_derivation_rejects_legacy_scope_before_path_observation() -> None:
    state = _state()
    operator = importlib.import_module("platform_core.runtime.operator_launch")

    class ExplodingPath:
        def __fspath__(self) -> str:
            raise AssertionError("forged transfer observed controller root")

    forged = operator.AuthorizedOuterCapabilities(
        transfer_id="a" * 64,
        _token=object(),
    )

    with pytest.raises(TypeError, match="unexpected keyword argument 'root'"):
        state.deriveInstalledControllerStateAuthority(
            outer_capabilities=forged,
            root=ExplodingPath(),
            repository_id="repo-forged-transfer",
            controller_generation=1,
            expires_at="2099-01-01T00:00:00+00:00",
        )
