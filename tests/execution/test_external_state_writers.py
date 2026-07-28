"""RED contracts for authority-bound external state writers."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import threading
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest


class _ObservedPath:
    def __init__(self, value: Path, observations: list[str]) -> None:
        self._value = value
        self._observations = observations

    def __fspath__(self) -> str:
        self._observations.append("fspath")
        return str(self._value)


def _set_runtime_terminal(
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    controller = _controller_state()
    paths = importlib.import_module("platform_core.app_config.paths")
    worker = importlib.import_module("platform_core.runtime.state_store_worker")
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(worker, "_INSTALLED_BINDING", None)
    if state == "pending":
        terminal = controller._PendingControllerRuntimeStateInstallation(
            bootstrap_authorities=object(),
            owner_thread_id=threading.get_ident(),
        )
        binding = None
    elif state == "poisoned":
        terminal = controller._PoisonedControllerRuntimeStateInstallation(
            bootstrap_id="f" * 64,
            reason="test poison",
        )
        binding = None
    elif state == "live":
        terminal = object()
        binding = object()
    elif state == "inconsistent":
        terminal = None
        binding = object()
    else:  # pragma: no cover - closed test vocabulary
        raise AssertionError(state)
    monkeypatch.setattr(controller, "_RUNTIME_INSTALL_TERMINAL", terminal)
    monkeypatch.setattr(controller, "_RUNTIME_BINDING", binding)


def _controller_state():
    return importlib.import_module("platform_core.runtime.controller_state")


def _run_installed_state_worker_case(
    tmp_path: Path,
    body: str,
) -> subprocess.CompletedProcess[str]:
    root = Path(__file__).resolve().parents[2]
    case_root = tmp_path / "installed-state-worker-case"
    code = f"""
import runpy
import sys
from pathlib import Path

repository_root = Path({str(root)!r})
fixture = runpy.run_path(
    str(repository_root / 'tests' / 'control' / 'test_installed_bootstrap_authority.py')
)
scope, _spawn_result, outer = fixture['_consume_outer'](Path({str(case_root)!r}))
from platform_core.runtime import bootstrap_authority as bootstrap
from platform_core.runtime import controller_state as state
from platform_core.runtime import state_store_worker as worker
bundle = bootstrap.deriveInstalledBootstrapAuthorities(outer_capabilities=outer)
""" + body
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


def test_writer_inventory_detects_target_state_and_path_only_writers(tmp_path: Path) -> None:
    mod = _controller_state()
    module = tmp_path / "unsafe_writer.py"
    module.write_text(
        """
import config
import sqlite3

def unsafe():
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(config.STATE_DIR / 'runtime.db')
""".lstrip(),
        encoding="utf-8",
    )
    findings = mod.auditExternalStateWriters((module,), allowed_boundaries={})
    assert {finding.category for finding in findings} >= {
        "target_state_path",
        "path_only_native_engine",
    }


def test_reviewed_isolated_state_worker_is_the_only_path_engine_exception() -> None:
    mod = _controller_state()
    root = Path.cwd()
    workers = (
        root / "platform_core/runtime/state_store_worker.py",
        root / "containers/galaxy/state_store_entrypoint.py",
    )

    assert mod.auditExternalStateWriters(
        workers,
        allowed_boundaries=mod.reviewedTask3StateWriterAllowlist(root),
    ) == ()


def test_state_worker_client_cannot_bypass_installed_binding_before_rpc() -> None:
    worker = importlib.import_module("platform_core.runtime.state_store_worker")
    calls: list[dict[str, object]] = []
    capability = object()
    client = worker.StateStoreWorkerClient(
        resource_id="state_worker_1",
        database_ids=frozenset({"memory"}),
        rpc=lambda request: calls.append(dict(request)) or {"stored": True},
        process_capability=capability,
    )
    authority = client.issueAuthority(
        process_capability=capability,
        deadline="2099-01-01T00:00:00+00:00",
    )
    request = worker.StateStoreRequest(
        request_id="request_1",
        operation="kv_put",
        database_id="memory",
        namespace="facts",
        key="fact_1",
        value={"truth": True},
    )

    with pytest.raises(worker.StateStoreWorkerUnavailable, match="unavailable"):
        client.execute(request, authority=authority)
    assert calls == []

    wrong_database = worker.StateStoreRequest(
        request_id="request_2",
        operation="kv_get",
        database_id="other",
        namespace="facts",
        key="fact_1",
    )
    with pytest.raises(worker.StateStoreWorkerRefused):
        client.execute(wrong_database, authority=authority)
    assert calls == []


def test_state_worker_client_requires_exact_immutable_database_scope() -> None:
    worker = importlib.import_module("platform_core.runtime.state_store_worker")
    mutable_scope = {"memory"}

    with pytest.raises((TypeError, worker.StateStoreWorkerRefused), match="frozenset|scope"):
        worker.StateStoreWorkerClient(
            resource_id="state_worker_mutable_scope",
            database_ids=mutable_scope,
            rpc=lambda _request: {},
            process_capability=object(),
        )

    assert mutable_scope == {"memory"}


def test_state_worker_authority_copy_cannot_widen_scope_or_deadline() -> None:
    worker = importlib.import_module("platform_core.runtime.state_store_worker")
    calls: list[dict[str, object]] = []
    capability = object()
    client = worker.StateStoreWorkerClient(
        resource_id="state_worker_authority_copy",
        database_ids=frozenset({"memory"}),
        rpc=lambda request: calls.append(dict(request)) or {"stored": True},
        process_capability=capability,
    )
    authority = client.issueAuthority(
        process_capability=capability,
        deadline="2099-01-01T00:00:00+00:00",
    )
    widened = replace(
        authority,
        database_ids=frozenset({"memory", "forbidden"}),
    )
    extended = replace(
        authority,
        deadline="2099-01-02T00:00:00+00:00",
    )

    # Direct execution is now correctly sealed behind the exact installed
    # runtime binding, so exercise the issuer-owned identity check itself here.
    # Installed-path tests below prove the same check happens before RPC.
    with pytest.raises(worker.StateStoreWorkerRefused, match="authority"):
        client._validateAuthority(widened)
    with pytest.raises(worker.StateStoreWorkerRefused, match="authority"):
        client._validateAuthority(extended)
    assert calls == []


@pytest.mark.xfail(
    strict=True,
    reason="requires sealed boot-resource journal, launcher, and worker handshake",
)
def test_state_worker_install_requires_exact_live_runtime_bundle_and_binds_generations(
    tmp_path: Path,
) -> None:
    body = """
calls = []
capability = state._controllerAuthorityScope(
    bundle.controller_state_authority
).process_capability
client = worker.StateStoreWorkerClient(
    resource_id='state_worker_installed',
    database_ids=frozenset({'memory'}),
    rpc=lambda request: calls.append(dict(request)) or {'stored': True},
    process_capability=capability,
)
authority = client.issueAuthority(
    process_capability=capability,
    deadline=bundle.run_admission.deadline.isoformat(),
)
try:
    worker.installStateStoreWorker(
        bootstrap_authorities=bundle,
        client=client,
        authority=authority,
    )
except worker.StateStoreWorkerRefused as exc:
    assert 'runtime' in str(exc) or 'binding' in str(exc)
else:
    raise AssertionError('worker installed before the central runtime')
assert calls == []
runtime = state.installControllerRuntimeState(bootstrap_authorities=bundle)
binding = worker.installStateStoreWorker(
    bootstrap_authorities=bundle,
    client=client,
    authority=authority,
)
admission = bundle.run_admission
assert binding.bootstrap_authorities is bundle
assert binding.controller_runtime_binding is runtime
assert binding.controller_generation == admission.controller_generation
assert binding.watchdog_generation == admission.watchdog_generation
assert binding.revocation_generation == admission.revocation_generation
assert binding.activation_generation == admission.activation_generation
assert binding.boot_generation == admission.boot_generation
assert binding.child_pid == admission.child_pid
assert worker.installStateStoreWorker(
    bootstrap_authorities=bundle,
    client=client,
    authority=authority,
) is binding
assert worker.executeStateOperation(
    database_id='memory',
    namespace='facts',
    operation='kv_put',
    key='fact_1',
    value={'truth': True},
    authority=authority,
) == {'stored': True}
assert len(calls) == 1
print('state-worker-exact-runtime-bound')
"""

    result = _run_installed_state_worker_case(tmp_path, body)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "state-worker-exact-runtime-bound"


def test_state_worker_install_is_typed_unavailable_without_registered_boot_resource(
    tmp_path: Path,
) -> None:
    """An in-process callback can never masquerade as a production worker."""

    body = """
runtime = state.installControllerRuntimeState(bootstrap_authorities=bundle)
capability = state._controllerAuthorityScope(runtime.authority).process_capability
calls = []
client = worker.StateStoreWorkerClient(
    resource_id='state_worker_unregistered',
    database_ids=frozenset({'memory'}),
    rpc=lambda request: calls.append(dict(request)) or {'stored': True},
    process_capability=capability,
)
authority = client.issueAuthority(
    process_capability=capability,
    deadline=bundle.run_admission.deadline.isoformat(),
)
try:
    worker.installStateStoreWorker(
        bootstrap_authorities=bundle,
        client=client,
        authority=authority,
    )
except worker.StateStoreWorkerUnavailable as exc:
    assert exc.reason is worker.StateStoreWorkerUnavailableReason.BOOT_RESOURCE_LIFECYCLE_UNAVAILABLE
else:
    raise AssertionError('unregistered callback acquired installed worker authority')
assert worker._INSTALLED_BINDING is None
assert calls == []
print('state-worker-unregistered-typed-unavailable')
"""

    result = _run_installed_state_worker_case(tmp_path, body)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "state-worker-unregistered-typed-unavailable"
    )


def test_unavailable_state_operation_observes_no_request_value_or_legacy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = importlib.import_module("platform_core.runtime.state_store_worker")
    monkeypatch.setattr(worker, "_INSTALLED_BINDING", None)
    observations: list[str] = []

    class ObservedValue(dict):
        def items(self):
            observations.append("value.items")
            return super().items()

    with pytest.raises(worker.StateStoreWorkerUnavailable) as refused:
        worker.executeStateOperation(
            database_id="memory",
            namespace="facts",
            operation="kv_put",
            key="fact_1",
            value=ObservedValue(truth=True),
        )

    assert refused.value.reason is (
        worker.StateStoreWorkerUnavailableReason.BOOT_RESOURCE_LIFECYCLE_UNAVAILABLE
    )
    assert observations == []


@pytest.mark.parametrize("runtime_state", ("absent", "pending", "poisoned"))
def test_state_worker_install_refuses_nonlive_runtime_terminals(
    tmp_path: Path,
    runtime_state: str,
) -> None:
    terminal_setup = {
        "absent": "",
        "pending": "state._RUNTIME_INSTALL_TERMINAL = state._PendingControllerRuntimeStateInstallation(bootstrap_authorities=bundle, owner_thread_id=0)",
        "poisoned": "state._RUNTIME_INSTALL_TERMINAL = state._PoisonedControllerRuntimeStateInstallation(bootstrap_id=bundle.bootstrap_id, reason='test poison')",
    }[runtime_state]
    body = f"""
capability = state._controllerAuthorityScope(
    bundle.controller_state_authority
).process_capability
client = worker.StateStoreWorkerClient(
    resource_id='state_worker_terminal',
    database_ids=frozenset({{'memory'}}),
    rpc=lambda _request: (_ for _ in ()).throw(AssertionError('rpc must stay dark')),
    process_capability=capability,
)
authority = client.issueAuthority(
    process_capability=capability,
    deadline=bundle.run_admission.deadline.isoformat(),
)
{terminal_setup}
try:
    worker.installStateStoreWorker(
        bootstrap_authorities=bundle,
        client=client,
        authority=authority,
    )
except worker.StateStoreWorkerRefused:
    pass
else:
    raise AssertionError('worker installed in {runtime_state} runtime state')
assert worker._INSTALLED_BINDING is None
print('state-worker-{runtime_state}-refused')
"""

    result = _run_installed_state_worker_case(tmp_path, body)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        f"state-worker-{runtime_state}-refused"
    )


def test_state_worker_install_rejects_foreign_bundle_process_and_deadline(
    tmp_path: Path,
) -> None:
    body = """
scope_b, _spawn_b, outer_b = fixture['_consume_outer'](
    Path(scope.controller_state_root).parent / 'foreign-worker-bundle',
    suffix='worker-b',
)
bundle_b = bootstrap.deriveInstalledBootstrapAuthorities(
    outer_capabilities=outer_b,
)
runtime = state.installControllerRuntimeState(bootstrap_authorities=bundle)
correct_capability = state._controllerAuthorityScope(
    runtime.authority
).process_capability
calls = []

def build_client(label, capability, deadline):
    client = worker.StateStoreWorkerClient(
        resource_id='state_worker_' + label,
        database_ids=frozenset({'memory'}),
        rpc=lambda request: calls.append(dict(request)) or {},
        process_capability=capability,
    )
    authority = client.issueAuthority(
        process_capability=capability,
        deadline=deadline,
    )
    return client, authority

foreign_client, foreign_authority = build_client(
    'foreign_bundle',
    correct_capability,
    bundle.run_admission.deadline.isoformat(),
)
wrong_process_client, wrong_process_authority = build_client(
    'wrong_process',
    object(),
    bundle.run_admission.deadline.isoformat(),
)
wrong_deadline_client, wrong_deadline_authority = build_client(
    'wrong_deadline',
    correct_capability,
    '2098-12-31T23:59:59+00:00',
)
cases = (
    (bundle_b, foreign_client, foreign_authority),
    (bundle, wrong_process_client, wrong_process_authority),
    (bundle, wrong_deadline_client, wrong_deadline_authority),
)
for candidate_bundle, client, authority in cases:
    try:
        worker.installStateStoreWorker(
            bootstrap_authorities=candidate_bundle,
            client=client,
            authority=authority,
        )
    except worker.StateStoreWorkerRefused:
        pass
    else:
        raise AssertionError('foreign worker install scope was accepted')
assert worker._INSTALLED_BINDING is None
assert calls == []
print('state-worker-foreign-scopes-refused')
"""

    result = _run_installed_state_worker_case(tmp_path, body)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "state-worker-foreign-scopes-refused"
    )


@pytest.mark.xfail(
    strict=True,
    reason="requires an issuer-owned prepared worker transfer",
)
def test_state_worker_tampered_generation_refuses_before_rpc(
    tmp_path: Path,
) -> None:
    body = """
from dataclasses import replace

runtime = state.installControllerRuntimeState(bootstrap_authorities=bundle)
capability = state._controllerAuthorityScope(runtime.authority).process_capability
calls = []
client = worker.StateStoreWorkerClient(
    resource_id='state_worker_generation',
    database_ids=frozenset({'memory'}),
    rpc=lambda request: calls.append(dict(request)) or {},
    process_capability=capability,
)
authority = client.issueAuthority(
    process_capability=capability,
    deadline=bundle.run_admission.deadline.isoformat(),
)
binding = worker.installStateStoreWorker(
    bootstrap_authorities=bundle,
    client=client,
    authority=authority,
)
worker._INSTALLED_BINDING = replace(
    binding,
    watchdog_generation=binding.watchdog_generation + 1,
)
try:
    worker.executeStateOperation(
        database_id='memory',
        namespace='facts',
        operation='kv_list',
        authority=authority,
    )
except worker.StateStoreWorkerRefused as exc:
    assert 'generation' in str(exc)
else:
    raise AssertionError('tampered worker generation reached RPC')
assert calls == []
print('state-worker-generation-tamper-refused')
"""

    result = _run_installed_state_worker_case(tmp_path, body)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "state-worker-generation-tamper-refused"
    )


@pytest.mark.xfail(
    strict=True,
    reason="requires an issuer-owned prepared worker transfer",
)
def test_state_worker_revoked_admission_never_falls_back_to_legacy_path(
    tmp_path: Path,
) -> None:
    body = """
runtime = state.installControllerRuntimeState(bootstrap_authorities=bundle)
capability = state._controllerAuthorityScope(runtime.authority).process_capability
calls = []
path_observed = []

class ForbiddenPath:
    def __fspath__(self):
        path_observed.append(True)
        raise AssertionError('legacy path was observed')

client = worker.StateStoreWorkerClient(
    resource_id='state_worker_admission',
    database_ids=frozenset({'memory'}),
    rpc=lambda request: calls.append(dict(request)) or {},
    process_capability=capability,
)
authority = client.issueAuthority(
    process_capability=capability,
    deadline=bundle.run_admission.deadline.isoformat(),
)
worker.installStateStoreWorker(
    bootstrap_authorities=bundle,
    client=client,
    authority=authority,
)
bundle.landing_issuer.revokeRunAdmission(bundle.run_admission)
try:
    worker.executeStateOperation(
        database_id='memory',
        namespace='facts',
        operation='kv_list',
        authority=authority,
        legacy_path=ForbiddenPath(),
    )
except worker.StateStoreWorkerRefused:
    pass
else:
    raise AssertionError('revoked admission remained executable')
assert calls == []
assert path_observed == []
print('state-worker-admission-revoked')
"""

    result = _run_installed_state_worker_case(tmp_path, body)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "state-worker-admission-revoked"
    )


@pytest.mark.xfail(
    strict=True,
    reason="requires a bounded registered worker channel",
)
def test_state_worker_operation_holds_bundle_epoch_and_rejects_after_revocation(
    tmp_path: Path,
) -> None:
    body = """
import threading
import time

state.installControllerRuntimeState(bootstrap_authorities=bundle)
rpc_started = threading.Event()
release_rpc = threading.Event()
revocation_started = threading.Event()
revocation_finished = threading.Event()
calls = []
results = []
errors = []
capability = state._controllerAuthorityScope(
    bundle.controller_state_authority
).process_capability

def rpc(request):
    calls.append(dict(request))
    rpc_started.set()
    assert release_rpc.wait(5)
    return {'items': []}

client = worker.StateStoreWorkerClient(
    resource_id='state_worker_revoke',
    database_ids=frozenset({'memory'}),
    rpc=rpc,
    process_capability=capability,
)
authority = client.issueAuthority(
    process_capability=capability,
    deadline=bundle.run_admission.deadline.isoformat(),
)
worker.installStateStoreWorker(
    bootstrap_authorities=bundle,
    client=client,
    authority=authority,
)

def operate():
    try:
        results.append(worker.executeStateOperation(
            database_id='memory',
            namespace='facts',
            operation='kv_list',
            authority=authority,
        ))
    except BaseException as exc:
        errors.append(exc)

def revoke():
    revocation_started.set()
    bootstrap._revokeInstalledBootstrapAuthorities(bundle, generation=1)
    revocation_finished.set()

operation_thread = threading.Thread(target=operate)
operation_thread.start()
assert rpc_started.wait(5)
revoker_thread = threading.Thread(target=revoke)
revoker_thread.start()
assert revocation_started.wait(5)
assert not revocation_finished.wait(0.2)
release_rpc.set()
operation_thread.join(5)
revoker_thread.join(5)
assert not operation_thread.is_alive() and not revoker_thread.is_alive()
assert errors == []
assert results == [{'items': []}]
assert revocation_finished.is_set()
try:
    worker.executeStateOperation(
        database_id='memory',
        namespace='facts',
        operation='kv_list',
        authority=authority,
    )
except worker.StateStoreWorkerRefused as exc:
    assert 'runtime' in str(exc) or 'bundle' in str(exc) or 'live' in str(exc)
else:
    raise AssertionError('revoked state-worker binding remained executable')
direct_request = worker.StateStoreRequest(
    request_id='request_after_revoke',
    operation='kv_list',
    database_id='memory',
    namespace='facts',
)
try:
    client.execute(direct_request, authority=authority)
except worker.StateStoreWorkerRefused:
    pass
else:
    raise AssertionError('direct client bypassed bundle revocation')
assert len(calls) == 1
print('state-worker-revocation-linearized')
"""

    result = _run_installed_state_worker_case(tmp_path, body)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "state-worker-revocation-linearized"
    )


@pytest.mark.xfail(
    strict=True,
    reason="requires a bounded registered worker channel",
)
def test_state_worker_operation_linearizes_before_runtime_poison(
    tmp_path: Path,
) -> None:
    body = """
import threading

runtime = state.installControllerRuntimeState(bootstrap_authorities=bundle)
capability = state._controllerAuthorityScope(runtime.authority).process_capability
rpc_started = threading.Event()
release_rpc = threading.Event()
poison_started = threading.Event()
poison_finished = threading.Event()
results = []
errors = []
calls = []

def rpc(request):
    calls.append(dict(request))
    rpc_started.set()
    assert release_rpc.wait(5)
    return {'items': ['accepted-before-poison']}

client = worker.StateStoreWorkerClient(
    resource_id='state_worker_runtime_poison',
    database_ids=frozenset({'memory'}),
    rpc=rpc,
    process_capability=capability,
)
authority = client.issueAuthority(
    process_capability=capability,
    deadline=bundle.run_admission.deadline.isoformat(),
)
worker.installStateStoreWorker(
    bootstrap_authorities=bundle,
    client=client,
    authority=authority,
)

def operate():
    try:
        results.append(worker.executeStateOperation(
            database_id='memory',
            namespace='facts',
            operation='kv_list',
            authority=authority,
        ))
    except BaseException as exc:
        errors.append(exc)

def poison():
    poison_started.set()
    state._poisonLiveRuntimeStore(
        bootstrap_authorities=bundle,
        store=runtime.store,
        primary=RuntimeError('injected runtime poison'),
    )
    poison_finished.set()

operation_thread = threading.Thread(target=operate)
operation_thread.start()
assert rpc_started.wait(5)
poison_thread = threading.Thread(target=poison)
poison_thread.start()
assert poison_started.wait(5)
assert not poison_finished.wait(0.2)
release_rpc.set()
operation_thread.join(5)
poison_thread.join(5)
assert not operation_thread.is_alive() and not poison_thread.is_alive()
assert errors == []
assert results == [{'items': ['accepted-before-poison']}]
assert poison_finished.is_set()
try:
    worker.executeStateOperation(
        database_id='memory',
        namespace='facts',
        operation='kv_list',
        authority=authority,
    )
except worker.StateStoreWorkerRefused:
    pass
else:
    raise AssertionError('poisoned runtime reached worker RPC')
direct_request = worker.StateStoreRequest(
    request_id='request_after_poison',
    operation='kv_list',
    database_id='memory',
    namespace='facts',
)
try:
    client.execute(direct_request, authority=authority)
except worker.StateStoreWorkerRefused:
    pass
else:
    raise AssertionError('direct client bypassed runtime poison')
assert len(calls) == 1
print('state-worker-runtime-poison-linearized')
"""

    result = _run_installed_state_worker_case(tmp_path, body)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "state-worker-runtime-poison-linearized"
    )


@pytest.mark.parametrize("transition", ("bundle", "admission", "runtime"))
@pytest.mark.xfail(
    strict=True,
    reason="requires a bounded registered worker channel",
)
def test_state_worker_reentrant_revocation_cannot_return_success(
    tmp_path: Path,
    transition: str,
) -> None:
    transition_code = {
        "bundle": "bootstrap._revokeInstalledBootstrapAuthorities(bundle, generation=1)",
        "admission": "bundle.landing_issuer.revokeRunAdmission(bundle.run_admission)",
        "runtime": "state._poisonLiveRuntimeStore(bootstrap_authorities=bundle, store=runtime.store, primary=RuntimeError('rpc poison'))",
    }[transition]
    body = f"""
runtime = state.installControllerRuntimeState(bootstrap_authorities=bundle)
capability = state._controllerAuthorityScope(runtime.authority).process_capability
calls = []

def rpc(request):
    calls.append(dict(request))
    {transition_code}
    return {{'stored': True}}

client = worker.StateStoreWorkerClient(
    resource_id='state_worker_reentrant_{transition}',
    database_ids=frozenset({{'memory'}}),
    rpc=rpc,
    process_capability=capability,
)
authority = client.issueAuthority(
    process_capability=capability,
    deadline=bundle.run_admission.deadline.isoformat(),
)
worker.installStateStoreWorker(
    bootstrap_authorities=bundle,
    client=client,
    authority=authority,
)
try:
    worker.executeStateOperation(
        database_id='memory',
        namespace='facts',
        operation='kv_put',
        key='fact_1',
        value=True,
        authority=authority,
    )
except worker.StateStoreWorkerRefused:
    pass
else:
    raise AssertionError('reentrant {transition} transition returned success')
assert len(calls) == 1
print('state-worker-reentrant-{transition}-refused')
"""

    result = _run_installed_state_worker_case(tmp_path, body)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        f"state-worker-reentrant-{transition}-refused"
    )


@pytest.mark.xfail(
    strict=True,
    reason="migrated to authenticated protocol; awaits registered-channel integration",
)
def test_state_worker_rpc_uses_one_immutable_canonical_request_snapshot(
    tmp_path: Path,
) -> None:
    body = """
import hashlib

runtime = state.installControllerRuntimeState(bootstrap_authorities=bundle)
capability = state._controllerAuthorityScope(runtime.authority).process_capability
observed = []
client = worker.StateStoreWorkerClient(
    resource_id='state_worker_snapshot',
    database_ids=frozenset({'memory'}),
    rpc=lambda request: observed.append(request) or {'stored': True},
    process_capability=capability,
)
authority = client.issueAuthority(
    process_capability=capability,
    deadline=bundle.run_admission.deadline.isoformat(),
)
worker.installStateStoreWorker(
    bootstrap_authorities=bundle,
    client=client,
    authority=authority,
)
mutable_value = {'truth': True}
request = worker.StateStoreRequest(
    request_id='request_snapshot',
    operation='kv_put',
    database_id='memory',
    namespace='facts',
    key='fact_1',
    value=mutable_value,
)
original_canonical = worker._canonical
snapshot_taken = False

def mutate_after_first_snapshot(value):
    global snapshot_taken
    raw = original_canonical(value)
    if (
        not snapshot_taken
        and isinstance(value, dict)
        and value.get('request_id') == 'request_snapshot'
    ):
        snapshot_taken = True
        mutable_value['truth'] = False
    return raw

worker._canonical = mutate_after_first_snapshot
response = client.execute(request, authority=authority)
assert snapshot_taken
assert mutable_value == {'truth': False}
assert observed == [{
    'database_id': 'memory',
    'key': 'fact_1',
    'namespace': 'facts',
    'operation': 'kv_put',
    'request_id': 'request_snapshot',
    'value': {'truth': True},
}]
expected_raw = original_canonical(observed[0])
assert response.request_digest == hashlib.sha256(expected_raw).hexdigest()
print('state-worker-request-snapshot-stable')
"""

    result = _run_installed_state_worker_case(tmp_path, body)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "state-worker-request-snapshot-stable"
    )


def test_state_worker_entrypoint_supports_only_closed_logical_kv_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entrypoint = importlib.import_module("containers.galaxy.state_store_entrypoint")
    monkeypatch.setattr(entrypoint, "_DATA_ROOT", tmp_path)

    assert entrypoint._handle(
        {
            "operation": "kv_put",
            "database_id": "memory",
            "namespace": "facts",
            "key": "fact_1",
            "value": {"truth": True},
        }
    ) == {"stored": True}
    assert entrypoint._handle(
        {
            "operation": "kv_get",
            "database_id": "memory",
            "namespace": "facts",
            "key": "fact_1",
        }
    ) == {"truth": True}
    with pytest.raises(ValueError):
        entrypoint._handle(
            {
                "operation": "sql",
                "database_id": "memory",
                "namespace": "facts",
                "key": "fact_1",
                "value": "DROP TABLE kv",
            }
        )


def test_state_worker_process_entrypoint_stays_dark_without_boot_storage_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entrypoint = importlib.import_module("containers.galaxy.state_store_entrypoint")
    observations: list[str] = []
    monkeypatch.setattr(
        entrypoint,
        "serve",
        lambda _reader, _writer: observations.append("serve") or 0,
    )

    assert entrypoint.main() == entrypoint.BOOT_RESOURCE_UNAVAILABLE_EXIT_CODE
    assert observations == []


def test_capsule_paths_disable_all_host_path_compatibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = importlib.import_module("platform_core.app_config.paths")
    worker = importlib.import_module("platform_core.runtime.state_store_worker")
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", object())
    monkeypatch.setattr(worker, "_INSTALLED_BINDING", None)

    with pytest.raises(worker.StateStoreWorkerRefused, match="binding is unavailable"):
        worker.executeStateOperation(
            database_id="memory",
            namespace="facts",
            operation="kv_put",
            key="fact_1",
            value={"truth": True},
            legacy_path=tmp_path / "legacy.db",
        )
    with pytest.raises(worker.StateStoreWorkerRefused, match="raw SQL compatibility"):
        worker.legacyDiagnosticSqliteConnection(tmp_path / "legacy.db")
    assert not (tmp_path / "legacy.db").exists()
    assert not (tmp_path / ".legacy.db.state-worker").exists()


def test_task3_writer_manifest_has_no_target_or_ambient_state_destination() -> None:
    mod = _controller_state()
    root = Path.cwd()
    findings = mod.auditExternalStateWriters(
        mod.task3StateWriterInventory(root),
        allowed_boundaries=mod.reviewedTask3StateWriterAllowlist(root),
    )
    assert findings == ()


@pytest.mark.parametrize("runtime_state", ["pending", "live", "poisoned", "inconsistent"])
@pytest.mark.parametrize(
    "caller",
    [
        "worker_operation",
        "worker_raw_sql",
        "ab_harness",
        "psyche_store",
        "conviction_ledger",
        "novelty_store",
        "ann_index",
        "validation_cache",
        "experience_schema",
        "epoch_cache",
    ],
)
def test_legacy_state_callers_reject_runtime_terminal_before_path_observation(
    caller: str,
    runtime_state: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every compatibility caller fences runtime truth before Path/config work."""

    preloaded = {
        "ab_harness": importlib.import_module("human_nature.faculties.runtime.ab_harness"),
        "psyche_store": importlib.import_module(
            "human_nature.faculties.runtime.psyche_store"
        ),
        "conviction_ledger": importlib.import_module("memory.conviction_ledger"),
        "novelty_store": importlib.import_module("memory.novelty.store"),
        "ann_index": importlib.import_module("memory.ledger.index"),
        "validation_cache": importlib.import_module(
            "platform_core.orchestration.validation_cache"
        ),
        "experience_schema": importlib.import_module("memory.ledger.schema"),
        "epoch_cache": importlib.import_module("platform_core.core.epoch"),
    }
    _set_runtime_terminal(monkeypatch, runtime_state)
    worker = importlib.import_module("platform_core.runtime.state_store_worker")
    observations: list[str] = []
    path = _ObservedPath(tmp_path / f"{caller}.db", observations)

    def invoke() -> object:
        if caller == "worker_operation":
            return worker.executeStateOperation(
                database_id="memory",
                namespace="facts",
                operation="kv_list",
                legacy_path=path,
            )
        if caller == "worker_raw_sql":
            return worker.legacyDiagnosticSqliteConnection(path)
        if caller == "ab_harness":
            module = preloaded[caller]
            return module.compare(db_path=path)
        if caller == "psyche_store":
            module = preloaded[caller]
            return module.open_store(db_path=path)
        if caller == "conviction_ledger":
            module = preloaded[caller]
            return module.track_record("opinion", "runtime", db_path=path)
        if caller == "novelty_store":
            module = preloaded[caller]
            return module.ChromaNoveltyStore(path)
        if caller == "ann_index":
            module = preloaded[caller]
            return module.ChromaIndex(path)
        if caller == "validation_cache":
            module = preloaded[caller]
            monkeypatch.setattr(
                module,
                "_cache_path",
                lambda: observations.append("cache_path") or path,
            )
            return module._cacheOperation("kv_get", ("runtime", "fence"))
        if caller == "experience_schema":
            module = preloaded[caller]
            monkeypatch.setattr(
                module,
                "_db_path",
                lambda _value=None: observations.append("db_path") or path,
            )
            with module._connect():
                return None
        if caller == "epoch_cache":
            module = preloaded[caller]
            monkeypatch.setattr(
                module,
                "_cachePath",
                lambda: observations.append("cache_path") or path,
            )
            return module._cacheConn()
        raise AssertionError(caller)  # pragma: no cover

    with pytest.raises(worker.StateStoreWorkerRefused, match="runtime"):
        invoke()
    assert observations == []
    assert not (tmp_path / f"{caller}.db").exists()
    assert not (tmp_path / f".{caller}.db.state-worker").exists()


def test_legacy_state_operation_holds_runtime_fence_through_worker_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = _controller_state()
    paths = importlib.import_module("platform_core.app_config.paths")
    worker = importlib.import_module("platform_core.runtime.state_store_worker")
    entrypoint = importlib.import_module("containers.galaxy.state_store_entrypoint")
    monkeypatch.setattr(controller, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(controller, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(worker, "_INSTALLED_BINDING", None)
    effect_started = threading.Event()
    release_effect = threading.Event()
    runtime_lock_acquired = threading.Event()
    original = entrypoint._handleAtDiagnosticRoot

    def blocking_effect(root: Path, request: dict[str, object]) -> object:
        effect_started.set()
        assert release_effect.wait(5)
        return original(root, request)

    monkeypatch.setattr(entrypoint, "_handleAtDiagnosticRoot", blocking_effect)
    operation = threading.Thread(
        target=lambda: worker.executeStateOperation(
            database_id="memory",
            namespace="facts",
            operation="kv_list",
            legacy_path=tmp_path / "legacy.db",
        ),
        daemon=True,
    )
    operation.start()
    assert effect_started.wait(5)

    def acquire_runtime_lock() -> None:
        with controller._RUNTIME_BINDING_LOCK:
            runtime_lock_acquired.set()

    contender = threading.Thread(target=acquire_runtime_lock, daemon=True)
    contender.start()
    assert not runtime_lock_acquired.wait(0.2)
    release_effect.set()
    operation.join(5)
    contender.join(5)
    assert not operation.is_alive()
    assert not contender.is_alive()
    assert runtime_lock_acquired.is_set()


def test_raw_sql_connection_retains_runtime_fence_until_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = _controller_state()
    paths = importlib.import_module("platform_core.app_config.paths")
    worker = importlib.import_module("platform_core.runtime.state_store_worker")
    monkeypatch.setattr(controller, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(controller, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(worker, "_INSTALLED_BINDING", None)
    connection = worker.legacyDiagnosticSqliteConnection(tmp_path / "legacy.db")
    runtime_lock_acquired = threading.Event()

    def acquire_runtime_lock() -> None:
        with controller._RUNTIME_BINDING_LOCK:
            runtime_lock_acquired.set()

    contender = threading.Thread(target=acquire_runtime_lock, daemon=True)
    contender.start()
    assert not runtime_lock_acquired.wait(0.2)
    connection.close()
    contender.join(5)
    assert not contender.is_alive()
    assert runtime_lock_acquired.is_set()


def test_retained_raw_sql_handle_rejects_poison_before_next_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = _controller_state()
    paths = importlib.import_module("platform_core.app_config.paths")
    worker = importlib.import_module("platform_core.runtime.state_store_worker")
    monkeypatch.setattr(controller, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(controller, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(worker, "_INSTALLED_BINDING", None)
    connection = worker.legacyDiagnosticSqliteConnection(tmp_path / "legacy.db")
    poison = controller._PoisonedControllerRuntimeStateInstallation(
        bootstrap_id="f" * 64,
        reason="test poison",
    )
    monkeypatch.setattr(controller, "_RUNTIME_INSTALL_TERMINAL", poison)
    try:
        with pytest.raises(worker.StateStoreWorkerRefused, match="runtime"):
            connection.execute("CREATE TABLE forbidden(value INTEGER)")
    finally:
        connection.close()

    import sqlite3

    with sqlite3.connect(tmp_path / "legacy.db") as check:
        names = check.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    assert ("forbidden",) not in names


def test_raw_sql_permit_can_only_be_released_by_its_owner_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sqlite3

    controller = _controller_state()
    paths = importlib.import_module("platform_core.app_config.paths")
    worker = importlib.import_module("platform_core.runtime.state_store_worker")
    monkeypatch.setattr(controller, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(controller, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(worker, "_INSTALLED_BINDING", None)
    connection_ready = threading.Event()
    close_on_owner = threading.Event()
    owner_closed = threading.Event()
    connections: list[object] = []

    def own_connection() -> None:
        connection = worker.legacyDiagnosticSqliteConnection(tmp_path / "legacy.db")
        connections.append(connection)
        connection_ready.set()
        assert close_on_owner.wait(5)
        connection.close()
        owner_closed.set()

    owner = threading.Thread(target=own_connection, daemon=True)
    owner.start()
    assert connection_ready.wait(5)
    connection = connections[0]
    with pytest.raises(sqlite3.ProgrammingError):
        connection.close()

    runtime_lock_acquired = threading.Event()

    def acquire_runtime_lock() -> None:
        with controller._RUNTIME_BINDING_LOCK:
            runtime_lock_acquired.set()

    contender = threading.Thread(target=acquire_runtime_lock, daemon=True)
    contender.start()
    assert not runtime_lock_acquired.wait(0.2)
    close_on_owner.set()
    assert owner_closed.wait(5)
    owner.join(5)
    contender.join(5)
    assert not owner.is_alive()
    assert not contender.is_alive()
    assert runtime_lock_acquired.is_set()


def test_raw_sql_handle_rejects_foreign_thread_operations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sqlite3

    controller = _controller_state()
    paths = importlib.import_module("platform_core.app_config.paths")
    worker = importlib.import_module("platform_core.runtime.state_store_worker")
    monkeypatch.setattr(controller, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(controller, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(worker, "_INSTALLED_BINDING", None)
    connection = worker.legacyDiagnosticSqliteConnection(tmp_path / "legacy.db")
    errors: list[BaseException] = []

    def mutate_connection() -> None:
        try:
            connection.row_factory = None
        except BaseException as exc:
            errors.append(exc)

    try:
        connection.row_factory = sqlite3.Row
        contender = threading.Thread(target=mutate_connection, daemon=True)
        contender.start()
        contender.join(5)
        assert not contender.is_alive()
        assert len(errors) == 1
        assert isinstance(errors[0], sqlite3.ProgrammingError)
        assert "owner thread" in str(errors[0])
        assert connection.row_factory is sqlite3.Row
    finally:
        connection.close()


def test_deferred_raw_sql_path_owns_one_permit_until_owner_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = _controller_state()
    paths = importlib.import_module("platform_core.app_config.paths")
    worker = importlib.import_module("platform_core.runtime.state_store_worker")
    monkeypatch.setattr(controller, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(controller, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(worker, "_INSTALLED_BINDING", None)
    callback_depths: list[int] = []
    runtime_lock_acquired = threading.Event()

    def resolve_path() -> Path:
        callback_depths.append(worker._diagnosticFenceDepth())
        return tmp_path / "legacy.db"

    connection = worker.legacyDiagnosticSqliteConnectionFromPath(resolve_path)

    def acquire_runtime_lock() -> None:
        with controller._RUNTIME_BINDING_LOCK:
            runtime_lock_acquired.set()

    contender = threading.Thread(target=acquire_runtime_lock, daemon=True)
    contender.start()
    try:
        assert callback_depths == [1]
        assert worker._diagnosticFenceDepth() == 1
        assert not runtime_lock_acquired.wait(0.2)
    finally:
        connection.close()
    contender.join(5)
    assert not contender.is_alive()
    assert runtime_lock_acquired.is_set()
    assert worker._diagnosticFenceDepth() == 0


def test_raw_sql_facade_rejects_resource_escape_methods(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = _controller_state()
    paths = importlib.import_module("platform_core.app_config.paths")
    worker = importlib.import_module("platform_core.runtime.state_store_worker")
    monkeypatch.setattr(controller, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(controller, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(worker, "_INSTALLED_BINDING", None)
    connection = worker.legacyDiagnosticSqliteConnection(tmp_path / "legacy.db")
    escaped = None
    try:
        connection.execute("CREATE TABLE payload(value BLOB)")
        connection.execute("INSERT INTO payload(value) VALUES (zeroblob(4))")
        with pytest.raises(AttributeError, match="unavailable"):
            escaped = connection.blobopen("payload", "value", 1)
    finally:
        if escaped is not None:
            escaped.close()
        connection.close()


def test_raw_sql_facade_rejects_callback_row_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = _controller_state()
    paths = importlib.import_module("platform_core.app_config.paths")
    worker = importlib.import_module("platform_core.runtime.state_store_worker")
    monkeypatch.setattr(controller, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(controller, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(worker, "_INSTALLED_BINDING", None)
    connection = worker.legacyDiagnosticSqliteConnection(tmp_path / "legacy.db")
    try:
        with pytest.raises(TypeError, match="row factory"):
            connection.row_factory = lambda cursor, row: (cursor, row)
    finally:
        connection.close()


def test_legacy_ledger_connection_scope_releases_the_runtime_fence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import config

    controller = _controller_state()
    paths = importlib.import_module("platform_core.app_config.paths")
    worker = importlib.import_module("platform_core.runtime.state_store_worker")
    schema = importlib.import_module("memory.ledger.schema")
    monkeypatch.setattr(controller, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(controller, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(worker, "_INSTALLED_BINDING", None)
    monkeypatch.setattr(config, "EXPERIENCE_POOL", True)
    schema._reset_schema_cache()
    runtime_lock_acquired = threading.Event()
    contender: threading.Thread | None = None

    try:
        with schema._connect(tmp_path / "experience.db"):
            pass

        def acquire_runtime_lock() -> None:
            with controller._RUNTIME_BINDING_LOCK:
                runtime_lock_acquired.set()

        contender = threading.Thread(target=acquire_runtime_lock, daemon=True)
        contender.start()
        assert runtime_lock_acquired.wait(1.0)
    finally:
        schema.close_pool()
        if contender is not None:
            contender.join(5)
        worker._DIAGNOSTIC_FENCE_STATE.depth = 0


def test_legacy_ledger_write_acquires_runtime_fence_before_local_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema = importlib.import_module("memory.ledger.schema")
    observations: list[str] = []

    @contextmanager
    def runtime_fence():
        observations.append("runtime_enter")
        try:
            yield
        finally:
            observations.append("runtime_exit")

    class ObservedLock:
        def __enter__(self):
            observations.append("write_lock_enter")

        def __exit__(self, exc_type, exc, traceback):
            observations.append("write_lock_exit")

    @contextmanager
    def connection_scope(_db_path=None):
        observations.append("connection_enter")
        try:
            yield object()
        finally:
            observations.append("connection_exit")

    monkeypatch.setattr(schema, "legacyDiagnosticStateWorkerAccess", runtime_fence)
    monkeypatch.setattr(schema, "_WRITE_LOCK", ObservedLock())
    monkeypatch.setattr(schema, "_connectUnfenced", connection_scope)

    with schema._writeConnect():
        observations.append("body")

    assert observations == [
        "runtime_enter",
        "write_lock_enter",
        "connection_enter",
        "body",
        "connection_exit",
        "write_lock_exit",
        "runtime_exit",
    ]
