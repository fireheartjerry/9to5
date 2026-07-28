"""Authority-bound retained-handle backing of the ControlBus.

Covers cross-process serialization, source-message ingestion dedup, deterministic
drain ordering, monotone spend truth, inert legacy target state, and the shared
``waitDecision`` gate wait."""
from contextlib import contextmanager
import importlib
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import config
from platform_core.runtime import autonomy_allowance as al
from platform_core.runtime import control_store
from platform_core.runtime.control import ControlBus


# ---------------------------------------------------------------------------
# authority / storage boundary
# ---------------------------------------------------------------------------


def _diagnostic_controller_binding(tmp_path, *, suffix: str):
    from platform_core.runtime import controller_state

    root = tmp_path / f"diagnostic-controller-state-{suffix}"
    authority = controller_state.issueDiagnosticControllerStateAuthority(
        root=root,
        repository_id=f"repo_consumer_{suffix}",
        controller_generation=7,
        process_capability=object(),
        expires_at="2099-01-01T00:00:00+00:00",
    )
    return (
        controller_state.ControllerStateStore(root=root, authority=authority),
        authority,
    )


def _installed_controller_binding(tmp_path, *, suffix: str):
    """Build a complete live installed bundle without activating runtime paths."""

    from platform_core.runtime import bootstrap_authority
    from platform_core.runtime import controller_state
    from tests.control.test_installed_bootstrap_authority import _consume_outer

    scope, _spawn_result, outer = _consume_outer(tmp_path, suffix=suffix)
    bundle = bootstrap_authority.deriveInstalledBootstrapAuthorities(
        outer_capabilities=outer
    )
    authority = bundle.controller_state_authority
    runtime_install_capability = controller_state._controllerAuthorityScope(
        authority
    ).runtime_install_capability
    return (
        controller_state.ControllerStateStore(
            root=scope.controller_state_root,
            authority=authority,
            _runtime_install_capability=runtime_install_capability,
            _bootstrap_authorities=bundle,
        ),
        authority,
    )


_CONSUMER_INSTALLERS = (
    (
        "platform_core.runtime.control_store",
        "installControlStore",
        "ControlStoreUnavailable",
    ),
    ("state.task_io", "installTaskStateStore", "TaskStateStoreUnavailable"),
    (
        "platform_core.runtime.heartbeat",
        "installHeartbeatStore",
        "HeartbeatStoreUnavailable",
    ),
    (
        "notifications.surfaces.terminal_ipc",
        "installTerminalIpcStore",
        "TerminalIpcStoreUnavailable",
    ),
)


@pytest.mark.parametrize(
    ("module_name", "installer_name", "error_name"),
    _CONSUMER_INSTALLERS,
)
def test_direct_consumer_installer_rejects_installed_authority(
    tmp_path,
    monkeypatch,
    module_name,
    installer_name,
    error_name,
):
    module = importlib.import_module(module_name)
    store, authority = _installed_controller_binding(tmp_path, suffix=installer_name)
    monkeypatch.setattr(module, "_INSTALLED_BINDING", None, raising=False)
    try:
        with pytest.raises(getattr(module, error_name), match="diagnostic"):
            getattr(module, installer_name)(store=store, authority=authority)
        assert module._INSTALLED_BINDING is None
    finally:
        store.close()


@pytest.mark.parametrize(
    ("module_name", "installer_name", "error_name"),
    _CONSUMER_INSTALLERS,
)
def test_direct_consumer_installer_rejects_closed_diagnostic_store(
    tmp_path,
    monkeypatch,
    module_name,
    installer_name,
    error_name,
):
    module = importlib.import_module(module_name)
    store, authority = _diagnostic_controller_binding(
        tmp_path,
        suffix=installer_name,
    )
    store.close()
    monkeypatch.setattr(module, "_INSTALLED_BINDING", None, raising=False)

    with pytest.raises(getattr(module, error_name), match="open"):
        getattr(module, installer_name)(store=store, authority=authority)
    assert module._INSTALLED_BINDING is None


@pytest.mark.parametrize(
    ("module_name", "installer_name", "error_name"),
    _CONSUMER_INSTALLERS,
)
def test_direct_consumer_installer_rejects_active_controller_paths(
    tmp_path,
    monkeypatch,
    module_name,
    installer_name,
    error_name,
):
    module = importlib.import_module(module_name)
    store, authority = _diagnostic_controller_binding(
        tmp_path,
        suffix=f"active-{installer_name}",
    )
    monkeypatch.setattr(module, "_INSTALLED_BINDING", None, raising=False)
    monkeypatch.setattr(
        module,
        "_controllerPathsActive",
        lambda: True,
        raising=False,
    )
    try:
        with pytest.raises(getattr(module, error_name), match="after activation"):
            getattr(module, installer_name)(store=store, authority=authority)
        assert module._INSTALLED_BINDING is None
    finally:
        store.close()


def test_controller_runtime_exact_absence_excludes_every_terminal(monkeypatch):
    from platform_core.runtime import controller_state

    monkeypatch.setattr(controller_state, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(controller_state, "_RUNTIME_INSTALL_TERMINAL", None)
    assert controller_state.controllerRuntimeStateExactlyAbsent()

    pending = controller_state._PendingControllerRuntimeStateInstallation(
        bootstrap_authorities=object(),
        owner_thread_id=threading.get_ident(),
    )
    monkeypatch.setattr(controller_state, "_RUNTIME_INSTALL_TERMINAL", pending)
    assert not controller_state.controllerRuntimeStateExactlyAbsent()

    monkeypatch.setattr(controller_state, "_RUNTIME_INSTALL_TERMINAL", None)
    assert controller_state.controllerRuntimeStateExactlyAbsent()
    monkeypatch.setattr(controller_state, "_RUNTIME_BINDING", object())
    assert not controller_state.controllerRuntimeStateExactlyAbsent()


@pytest.mark.parametrize(
    ("module_name", "installer_name", "error_name"),
    _CONSUMER_INSTALLERS,
)
def test_direct_consumer_installer_rejects_poisoned_inactive_runtime(
    tmp_path,
    monkeypatch,
    module_name,
    installer_name,
    error_name,
):
    from platform_core.runtime import controller_state

    module = importlib.import_module(module_name)
    store, authority = _diagnostic_controller_binding(
        tmp_path,
        suffix=f"poisoned-{installer_name}",
    )
    poison = controller_state._PoisonedControllerRuntimeStateInstallation(
        bootstrap_id="poisoned-test",
        reason="ambiguous-precommit",
    )
    monkeypatch.setattr(controller_state, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(controller_state, "_RUNTIME_INSTALL_TERMINAL", poison)
    monkeypatch.setattr(module, "_INSTALLED_BINDING", None, raising=False)
    monkeypatch.setattr(
        module,
        "_controllerPathsActive",
        lambda: False,
        raising=False,
    )
    try:
        with pytest.raises(getattr(module, error_name), match="exactly absent"):
            getattr(module, installer_name)(store=store, authority=authority)
        assert module._INSTALLED_BINDING is None
    finally:
        store.close()


@pytest.mark.parametrize(
    "module_name",
    [entry[0] for entry in _CONSUMER_INSTALLERS],
)
def test_active_consumer_resolves_central_runtime_without_local_publication(
    tmp_path,
    monkeypatch,
    module_name,
):
    from platform_core.app_config import paths
    from platform_core.runtime import controller_state

    module = importlib.import_module(module_name)
    store, authority = _installed_controller_binding(tmp_path, suffix=module_name)
    local_sentinel = object()
    central = SimpleNamespace(store=store, authority=authority)
    resolver_calls = 0
    fence_held = False

    @contextmanager
    def observed_path_fence():
        nonlocal fence_held
        assert not fence_held
        fence_held = True
        try:
            yield True
        finally:
            fence_held = False

    def resolve_central():
        nonlocal resolver_calls
        assert not fence_held
        resolver_calls += 1
        if resolver_calls % 2:
            raise controller_state.ControllerStateRefused(
                "runtime installation has not published yet"
            )
        return central

    monkeypatch.setattr(module, "_INSTALLED_BINDING", local_sentinel, raising=False)
    monkeypatch.setattr(
        module,
        "_controllerPathsActive",
        lambda: True,
        raising=False,
    )
    monkeypatch.setattr(
        controller_state,
        "currentControllerRuntimeStateBinding",
        resolve_central,
        raising=False,
    )
    monkeypatch.setattr(
        paths,
        "controllerPathsActivationFence",
        observed_path_fence,
    )
    try:
        binding = module._binding()
        assert binding.store is store
        assert binding.authority is authority
        rebound = module._binding()
        assert rebound.store is store
        assert rebound.authority is authority
        assert resolver_calls == 4
        assert module._INSTALLED_BINDING is local_sentinel
    finally:
        store.close()


@pytest.mark.parametrize(
    "module_name",
    [entry[0] for entry in _CONSUMER_INSTALLERS],
)
def test_consumer_lookup_cannot_invert_runtime_install_lock_order(
    tmp_path,
    monkeypatch,
    module_name,
):
    """Installer runtime->path order cannot cycle with a consumer lookup."""

    from platform_core.app_config import paths
    from platform_core.runtime import controller_state

    module = importlib.import_module(module_name)
    store, authority = _installed_controller_binding(
        tmp_path,
        suffix=f"lock-order-{module_name}",
    )
    central = SimpleNamespace(store=store, authority=authority)
    runtime_lock = threading.Lock()
    path_lock = threading.Lock()
    runtime_held = threading.Event()
    consumer_waiting = threading.Event()
    installer_acquired_path = threading.Event()
    lock_inversion = threading.Event()
    errors: list[BaseException] = []
    results = []

    @contextmanager
    def observed_path_fence():
        if not path_lock.acquire(timeout=1.0):
            raise AssertionError("consumer could not acquire the path fence")
        try:
            yield True
        finally:
            path_lock.release()

    def resolve_central():
        consumer_waiting.set()
        if not runtime_lock.acquire(timeout=1.0):
            raise controller_state.ControllerStateRefused(
                "consumer timed out waiting for the runtime lock"
            )
        try:
            return central
        finally:
            runtime_lock.release()

    def install_runtime() -> None:
        try:
            with runtime_lock:
                runtime_held.set()
                if not consumer_waiting.wait(timeout=1.0):
                    raise AssertionError("consumer never attempted central lookup")
                if not path_lock.acquire(timeout=0.25):
                    lock_inversion.set()
                    return
                try:
                    installer_acquired_path.set()
                finally:
                    path_lock.release()
        except BaseException as exc:
            errors.append(exc)

    def lookup() -> None:
        try:
            results.append(module._binding())
        except BaseException as exc:
            errors.append(exc)

    monkeypatch.setattr(module, "_INSTALLED_BINDING", None, raising=False)
    monkeypatch.setattr(
        controller_state,
        "currentControllerRuntimeStateBinding",
        resolve_central,
    )
    monkeypatch.setattr(
        paths,
        "controllerPathsActivationFence",
        observed_path_fence,
    )
    installer = threading.Thread(target=install_runtime, daemon=True)
    consumer = threading.Thread(target=lookup, daemon=True)
    try:
        installer.start()
        assert runtime_held.wait(timeout=1.0)
        consumer.start()
        installer.join(timeout=2.0)
        consumer.join(timeout=2.0)

        assert not installer.is_alive()
        assert not consumer.is_alive()
        assert not errors
        assert not lock_inversion.is_set()
        assert installer_acquired_path.is_set()
        assert len(results) == 1
        assert results[0].store is store
        assert results[0].authority is authority
    finally:
        store.close()


@pytest.mark.parametrize(
    ("module_name", "installer_name", "error_name"),
    _CONSUMER_INSTALLERS,
)
def test_poisoned_inactive_runtime_blocks_preinstalled_diagnostic_effect(
    tmp_path,
    monkeypatch,
    module_name,
    installer_name,
    error_name,
):
    from platform_core.runtime import controller_state

    module = importlib.import_module(module_name)
    store, authority = _diagnostic_controller_binding(
        tmp_path,
        suffix=f"effect-{installer_name}",
    )
    legacy_root = tmp_path / f"legacy-{installer_name}"
    monkeypatch.setattr(controller_state, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(controller_state, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(module, "_INSTALLED_BINDING", None, raising=False)
    monkeypatch.setattr(
        module,
        "_controllerPathsActive",
        lambda: False,
        raising=False,
    )
    getattr(module, installer_name)(store=store, authority=authority)
    task_state = None
    if module_name == "state.task_io":
        from state.task import TaskState

        monkeypatch.setattr(config, "STATE_DIR", legacy_root / "tasks")
        task_state = TaskState.create("poisoned task", 1.0)
    poison = controller_state._PoisonedControllerRuntimeStateInstallation(
        bootstrap_id="poisoned-test",
        reason="ambiguous-precommit",
    )
    monkeypatch.setattr(controller_state, "_RUNTIME_INSTALL_TERMINAL", poison)

    try:
        if module_name == "platform_core.runtime.control_store":
            logical_id = module._logical("poisoned-control")
            with pytest.raises(getattr(module, error_name), match="exactly absent"):
                module.setFlag("poisoned-control", "abort", True)
        elif module_name == "state.task_io":
            assert task_state is not None
            logical_id = module._logicalTask(task_state.task_id)
            with pytest.raises(getattr(module, error_name), match="exactly absent"):
                task_state.save()
        elif module_name == "platform_core.runtime.heartbeat":
            monkeypatch.setattr(config, "HEARTBEAT_DIR", legacy_root / "heartbeats")
            logical_id = module._logicalHeartbeat("poisoned-heartbeat")
            module.writeHeartbeat("poisoned-heartbeat", seq=1)
        else:
            nav_path = legacy_root / "ipc" / "terminal_nav.json"
            monkeypatch.setattr(module, "NAV_PATH", nav_path)
            logical_id = "ipc/terminal-nav"
            module.write_nav(2, "raw", True)

        # Restore exact absence only to inspect the diagnostic store.  A
        # poisoned runtime correctly rejects even direct diagnostic reads.
        monkeypatch.setattr(controller_state, "_RUNTIME_INSTALL_TERMINAL", None)
        with pytest.raises(FileNotFoundError):
            store.readJson(logical_id, authority=authority)
        assert not legacy_root.exists()
    finally:
        store.close()


def test_terminal_legacy_effect_serializes_before_poison(monkeypatch, tmp_path):
    from notifications.surfaces import terminal_ipc as ipc
    from platform_core.app_config import paths
    from platform_core.runtime import controller_state

    poison_path = tmp_path / "legacy" / "terminal_nav.json"
    poison_started = threading.Event()
    poison_committed = threading.Event()
    post_poison_effect = threading.Event()
    path_fence_missing = threading.Event()
    order: list[str] = []
    threads: list[threading.Thread] = []
    path_fence_held = False
    monkeypatch.setattr(controller_state, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(controller_state, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(ipc, "_INSTALLED_BINDING", None, raising=False)
    monkeypatch.setattr(ipc, "_controllerPathsActive", lambda: False)
    monkeypatch.setattr(ipc, "NAV_PATH", poison_path)

    @contextmanager
    def observed_path_fence():
        nonlocal path_fence_held
        assert not path_fence_held
        path_fence_held = True
        try:
            yield False
        finally:
            path_fence_held = False

    def poison_runtime() -> None:
        poison_started.set()
        with controller_state._RUNTIME_BINDING_LOCK:
            controller_state._RUNTIME_INSTALL_TERMINAL = (
                controller_state._PoisonedControllerRuntimeStateInstallation(
                    bootstrap_id="race-test",
                    reason="ambiguous-precommit",
                )
            )
            order.append("poison")
            poison_committed.set()

    def observed_legacy_write(*_args, **_kwargs) -> None:
        if not path_fence_held:
            path_fence_missing.set()
        poisoner = threading.Thread(target=poison_runtime, daemon=True)
        threads.append(poisoner)
        poisoner.start()
        assert poison_started.wait(timeout=1.0)
        if poison_committed.wait(timeout=0.1):
            post_poison_effect.set()
        order.append("effect")

    monkeypatch.setattr(ipc.fsio, "atomicWriteJson", observed_legacy_write)
    monkeypatch.setattr(
        paths,
        "controllerPathsActivationFence",
        observed_path_fence,
    )
    ipc.write_nav(3, "raw", True)
    assert len(threads) == 1
    threads[0].join(timeout=2.0)

    assert not threads[0].is_alive()
    assert not post_poison_effect.is_set()
    assert not path_fence_missing.is_set()
    assert order == ["effect", "poison"]
    assert not poison_path.exists()


def test_poisoned_terminal_without_binding_never_reaches_legacy_path(
    monkeypatch,
    tmp_path,
):
    from notifications.surfaces import terminal_ipc as ipc
    from platform_core.runtime import controller_state

    poison_path = tmp_path / "legacy" / "terminal_nav.json"
    poison = controller_state._PoisonedControllerRuntimeStateInstallation(
        bootstrap_id="poisoned-test",
        reason="ambiguous-precommit",
    )
    monkeypatch.setattr(controller_state, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(controller_state, "_RUNTIME_INSTALL_TERMINAL", poison)
    monkeypatch.setattr(ipc, "_INSTALLED_BINDING", None, raising=False)
    monkeypatch.setattr(ipc, "_controllerPathsActive", lambda: False)
    monkeypatch.setattr(ipc, "NAV_PATH", poison_path)

    ipc.write_nav(4, "raw", True)
    assert ipc.read_nav() == {"page_idx": 0, "mode": "summary", "frozen": False}
    assert not poison_path.exists()


@pytest.mark.parametrize(
    "module_name",
    [entry[0] for entry in _CONSUMER_INSTALLERS],
)
def test_inactive_diagnostic_binding_read_holds_local_lock(monkeypatch, module_name):
    module = importlib.import_module(module_name)
    local_sentinel = object()

    class ObservedLock:
        def __init__(self) -> None:
            self.entries = 0

        def __enter__(self):
            self.entries += 1
            return self

        def __exit__(self, *_exc) -> None:
            return None

    observed = ObservedLock()
    monkeypatch.setattr(
        module,
        "_controllerPathsActive",
        lambda: False,
        raising=False,
    )
    monkeypatch.setattr(module, "_INSTALLED_BINDING", local_sentinel, raising=False)
    monkeypatch.setattr(module, "_BINDING_LOCK", observed)

    assert module._binding() is local_sentinel
    assert observed.entries == 1


def test_store_is_native_json_without_a_path_only_database_engine():
    ControlBus("t-schema").requestPause()
    binding = control_store._binding()
    assert binding.store.readJson(
        control_store._logical("t-schema"), authority=binding.authority
    )["schema"] == "galaxy.control-task/v2"
    source = Path(control_store.__file__).read_text(encoding="utf-8")
    assert "sqlite3.connect" not in source


def test_production_refuses_without_capsule_binding_before_target_path_lookup(
    monkeypatch,
):
    class PoisonPath:
        def __fspath__(self):
            raise AssertionError("target STATE_DIR was observed")

    monkeypatch.setattr(control_store, "_DB_OVERRIDE", None)
    monkeypatch.setattr(control_store, "_INSTALLED_BINDING", None)
    monkeypatch.setattr(config, "STATE_DIR", PoisonPath(), raising=False)
    with pytest.raises(control_store.ControlStoreUnavailable):
        control_store.setFlag("t-no-authority", "abort", True)


def test_db_path_derives_from_state_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(control_store, "_DB_OVERRIDE", None, raising=False)
    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state" / "tasks", raising=False)
    assert control_store._dbPath() == tmp_path / "state" / "control.db"


# ---------------------------------------------------------------------------
# flags / decisions
# ---------------------------------------------------------------------------
def test_flag_roundtrip_types():
    tid = "t-flags"
    control_store.setFlag(tid, "abort", True)
    control_store.setFlag(tid, "seen_discord_id", "12345")
    control_store.setFlag(tid, "pending_gate", None)
    assert control_store.getFlag(tid, "abort") is True
    assert control_store.getFlag(tid, "seen_discord_id") == "12345"
    assert control_store.getFlag(tid, "pending_gate") is None
    assert control_store.getFlag(tid, "missing", "dflt") == "dflt"
    control_store.setFlag(tid, "abort", False)   # overwrite in place (PK upsert)
    assert control_store.getFlag(tid, "abort") is False


def test_decisions_are_per_task_and_clearable():
    control_store.setDecision("t-a", "plan", "approve")
    control_store.setDecision("t-b", "plan", "reject")
    assert control_store.getDecision("t-a", "plan") == "approve"
    assert control_store.getDecision("t-b", "plan") == "reject"
    control_store.clearDecision("t-a", "plan")
    assert control_store.getDecision("t-a", "plan") is None
    assert control_store.getDecision("t-b", "plan") == "reject"


# ---------------------------------------------------------------------------
# ops queue
# ---------------------------------------------------------------------------
def test_pushop_reports_dedup():
    assert control_store.pushOp("t-ops", {"op": "retry"}, "m1") is True
    assert control_store.pushOp("t-ops", {"op": "retry"}, "m1") is False   # same message
    assert control_store.pushOp("t-ops", {"op": "retry"}, "m2") is True    # new message
    assert len(control_store.drainOps("t-ops")) == 2


def test_source_msg_dedup_is_per_task():
    control_store.pushOp("t-x", {"op": "retry"}, "77")
    control_store.pushOp("t-y", {"op": "retry"}, "77")
    assert len(control_store.drainOps("t-x")) == 1
    assert len(control_store.drainOps("t-y")) == 1


def test_drain_removes_and_orders():
    for i in range(5):
        control_store.pushOp("t-drain", {"op": "add", "title": f"t{i}"})
    ops = control_store.drainOps("t-drain")
    assert [o["title"] for o in ops] == [f"t{i}" for i in range(5)]
    assert control_store.drainOps("t-drain") == []


def test_garbage_op_row_is_dropped_not_fatal():
    control_store.pushOp("t-garbage", {"op": "add", "title": "good"})
    binding = control_store._binding()
    logical = control_store._logical("t-garbage")
    document = binding.store.readJson(logical, authority=binding.authority)
    document["ops"].append({"sequence": 999, "op": "not-an-object"})
    binding.store.writeJson(logical, document, authority=binding.authority)
    assert ControlBus("t-garbage").load()["plan_ops"] == [{"op": "add", "title": "good"}]
    ops = control_store.drainOps("t-garbage")
    assert ops == [{"op": "add", "title": "good"}]


# ---------------------------------------------------------------------------
# spend ledger (Epic 4): idempotent, monotonic, un-zeroable
# ---------------------------------------------------------------------------
def test_ledger_same_attempt_id_charges_once():
    bus = ControlBus("t-ledger")
    al.meterSpend(bus, 0.10, attempt_id="s1:1")
    al.meterSpend(bus, 0.10, attempt_id="s1:1")   # retry double-fire -> ignored
    al.meterSpend(bus, 0.25, attempt_id="s1:2")
    assert abs(al.spent(bus) - 0.35) < 1e-9


def test_ledger_survives_clear_run_start_and_op_churn():
    """clearForRunStart / drain / corrupt op rows can never zero the money (the old
    corrupt-rebuild path reset autonomy_spent_usd to 0.0)."""
    bus = ControlBus("t-ledger2")
    al.meterSpend(bus, 1.50, attempt_id="a1")
    bus.pushOp({"op": "add", "title": "x"})
    bus.clearForRunStart()
    bus.drainOps()
    assert abs(al.spent(bus) - 1.50) < 1e-9
    assert abs(bus.load()["autonomy_spent_usd"] - 1.50) < 1e-9


def test_ledger_wiped_only_by_explicit_full_clear():
    bus = ControlBus("t-ledger3")
    al.meterSpend(bus, 0.42, attempt_id="x")
    bus.clear()
    assert al.spent(bus) == 0.0


# ---------------------------------------------------------------------------
# legacy target state is inert (migration has its own one-use authority)
# ---------------------------------------------------------------------------
_LEGACY = {
    "abort": True,
    "pause": False,
    "decisions": {"plan": "approve", "pre_pr": None},
    "plan_ops": [{"op": "add", "title": "carried"}],
    "seen_discord_id": "555",
    "pending_gate": "pre_pr",
    "autonomy_spent_usd": 1.25,
    "autonomy_metered_attempts": ["st-001:1", "st-001:2"],
}


def _freshStore(tmp_path, monkeypatch, legacy_files: dict):
    legacy_dir = tmp_path / "legacy_control"
    legacy_dir.mkdir()
    for name, data in legacy_files.items():
        (legacy_dir / name).write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(config, "CONTROL_DIR", legacy_dir, raising=False)
    monkeypatch.setattr(control_store, "_DB_OVERRIDE",
                        tmp_path / "fresh" / "control.db", raising=False)
    return legacy_dir


def test_legacy_json_is_not_observed_or_renamed_by_control_store(tmp_path, monkeypatch):
    legacy_dir = _freshStore(tmp_path, monkeypatch, {"t-legacy.json": _LEGACY})
    before = (legacy_dir / "t-legacy.json").read_bytes()
    d = ControlBus("t-legacy").load()
    assert d["abort"] is False
    assert d["decisions"]["plan"] is None
    assert d["plan_ops"] == []
    assert d["autonomy_spent_usd"] == 0.0
    assert (legacy_dir / "t-legacy.json").read_bytes() == before
    assert not (legacy_dir / "t-legacy.json.migrated").exists()


def test_control_store_exposes_no_ambient_legacy_importer():
    for name in ("_migrateLegacyJson", "_importLegacyTask"):
        assert not hasattr(control_store, name)


def test_migration_skips_bad_file_and_still_serves(tmp_path, monkeypatch):
    legacy_dir = _freshStore(tmp_path, monkeypatch,
                             {"t-ok.json": {"abort": True}})
    (legacy_dir / "t-bad.json").write_text("{ not valid json :::", encoding="utf-8")
    assert ControlBus("t-ok").isAbort() is False
    assert (legacy_dir / "t-bad.json").exists()   # left in place, never retired


# ---------------------------------------------------------------------------
# load() shape + lifecycle
# ---------------------------------------------------------------------------
def test_fresh_bus_load_is_blank_shape():
    d = ControlBus("t-blank").load()
    assert d["abort"] is False and d["pause"] is False
    assert d["kill_subprocess"] is False and d["force_replan"] is False
    assert d["decisions"] == {"plan": None, "pre_pr": None, "action_risk": None, "council_risk": None}
    assert d["plan_ops"] == [] and d["seen_discord_id"] is None
    assert d["pending_gate"] is None and d["autonomy_spent_usd"] == 0.0


def test_clear_task_resets_everything():
    bus = ControlBus("t-clear")
    bus.requestAbort()
    bus.decide("plan", "approve")
    bus.pushOp({"op": "retry"}, source_msg_id="9")
    bus.clear()
    d = bus.load()
    assert d["abort"] is False and d["decisions"]["plan"] is None and d["plan_ops"] == []
    # a cleared source_msg_id can be ingested again (fresh task lifecycle)
    bus.pushOp({"op": "retry"}, source_msg_id="9")
    assert len(bus.drainOps()) == 1


# ---------------------------------------------------------------------------
# waitDecision matrix: decision / abort / timeout / night-mode / escape
# ---------------------------------------------------------------------------
def test_waitdecision_returns_verdict():
    bus = ControlBus("t-wd1")
    threading.Timer(0.05, lambda: bus.decide("pre_pr", "approve")).start()
    assert bus.waitDecision("pre_pr", timeout=5.0, poll=0.01) == "approve"


def test_waitdecision_abort_escapes():
    bus = ControlBus("t-wd2")
    threading.Timer(0.05, bus.requestAbort).start()
    assert bus.waitDecision("pre_pr", timeout=5.0, poll=0.01) == "abort"


def test_waitdecision_timeout_returns_none():
    bus = ControlBus("t-wd3")
    start = time.time()
    assert bus.waitDecision("pre_pr", timeout=0.05, poll=0.01) is None
    assert time.time() - start < 2.0


def test_waitdecision_night_mode_caps_unbounded_wait(monkeypatch):
    monkeypatch.setattr(config, "NIGHT_MODE", True, raising=False)
    monkeypatch.setattr(config, "NIGHT_MODE_PAUSE_TIMEOUT", 0.05, raising=False)
    bus = ControlBus("t-wd4")
    assert bus.waitDecision("pre_pr", timeout=None, poll=0.01) is None


def test_waitdecision_escape_and_on_tick():
    bus = ControlBus("t-wd5")
    ticks = []
    verdict = bus.waitDecision("pre_pr", timeout=None, poll=0.01,
                               on_tick=lambda: ticks.append(1),
                               escape=lambda: len(ticks) >= 3)
    assert verdict is None
    assert len(ticks) >= 3


def test_waitdecision_decision_beats_timeout_on_same_tick():
    bus = ControlBus("t-wd6")
    bus.decide("plan", "reject")
    assert bus.waitDecision("plan", timeout=0.0, poll=0.01) == "reject"


def test_control_store_rows_are_never_a_live_trust_grant_factory():
    for name in ("issueWorkloadGrant", "loadWorkloadGrant", "restoreWorkloadGrant",
                 "mintOperatorAuthority"):
        assert not hasattr(control_store, name)


def test_unknown_authority_shaped_flags_are_rejected_and_never_projected():
    task_id = "t-untrusted-authority-row"
    flag_key = "operator_launch_authority"
    decision_gate = "operator_spec_approval"

    with pytest.raises(ValueError, match="unknown control flag"):
        control_store.setFlag(task_id, flag_key, {"trusted": True})
    with pytest.raises(ValueError, match="authority-shaped control decision gate"):
        control_store.setDecision(task_id, decision_gate, "approve")

    # A copied/tampered durable document remains inert evidence even when it
    # bypasses the public namespace validator through the diagnostic store.
    binding = control_store._binding()
    logical = control_store._logical(task_id)
    document = control_store._blankDocument()
    document["flags"][flag_key] = {"trusted": True}
    document["decisions"][decision_gate] = "approve"
    binding.store.writeJson(logical, document, authority=binding.authority)

    assert control_store.getFlag(task_id, flag_key, "missing") == "missing"
    assert control_store.getDecision(task_id, decision_gate) is None
    snapshot = control_store.snapshot(task_id)
    assert flag_key not in snapshot["flags"]
    assert decision_gate not in snapshot["decisions"]
