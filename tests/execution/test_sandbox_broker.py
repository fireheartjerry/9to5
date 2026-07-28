"""RED contracts for the credentialless clone command broker."""

from __future__ import annotations

import importlib
import subprocess
import threading
from pathlib import Path

import pytest


def _broker():
    return importlib.import_module("platform_core.execution.sandbox_broker")


def test_missing_authority_refuses_before_runner_or_path_observation(tmp_path: Path) -> None:
    mod = _broker()
    clone = tmp_path / "clone"
    clone.mkdir()
    calls: list[object] = []
    broker = mod.SandboxCommandBroker(
        clone_root=clone,
        runner=lambda request: calls.append(request),
        allowed_operations=frozenset({"repo_read"}),
    )

    with pytest.raises(mod.SandboxBrokerRefused):
        broker.execute(
            mod.BrokerRequest(operation="repo_read", path="missing.txt"),
            authority=None,
        )

    assert calls == []


@pytest.mark.parametrize(
    "path",
    ["../goldstone", "/host/goldstone", "C:/host/goldstone", ".git/config"],
)
def test_broker_path_normalization_rejects_escape_and_git_metadata(
    tmp_path: Path, path: str
) -> None:
    mod = _broker()
    clone = tmp_path / "clone"
    clone.mkdir()
    with pytest.raises(mod.SandboxBrokerRefused):
        mod.normalizeBrokerPath(clone, path)


def test_broker_rejects_symlink_components(tmp_path: Path) -> None:
    mod = _broker()
    clone = tmp_path / "clone"
    outside = tmp_path / "outside"
    clone.mkdir()
    outside.mkdir()
    link = clone / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable for this account")

    with pytest.raises(mod.SandboxBrokerRefused):
        mod.normalizeBrokerPath(clone, "link/goldstone")


def test_capsule_mode_refuses_legacy_process_before_launch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _broker()
    paths = importlib.import_module("platform_core.app_config.paths")
    calls: list[object] = []
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", object())
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    with pytest.raises(mod.SandboxBrokerRefused, match="legacy diagnostic"):
        mod.runLegacyProcess(["git", "status"])

    assert calls == []


def test_capsule_mode_refuses_legacy_automation_before_factory_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _broker()
    paths = importlib.import_module("platform_core.app_config.paths")
    calls: list[object] = []
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", object())

    with pytest.raises(mod.SandboxBrokerRefused, match="legacy diagnostic"):
        mod.legacyDiagnosticAutomationCall(
            lambda *args, **kwargs: calls.append((args, kwargs)),
            "secret",
        )

    assert calls == []


@pytest.mark.parametrize("terminal", ["pending", "poisoned"])
def test_nonabsent_runtime_refuses_legacy_process_with_paths_inactive(
    monkeypatch: pytest.MonkeyPatch,
    terminal: str,
) -> None:
    mod = _broker()
    runtime = importlib.import_module("platform_core.runtime.controller_state")
    paths = importlib.import_module("platform_core.app_config.paths")
    calls: list[object] = []
    runtime_terminal = (
        runtime._PendingControllerRuntimeStateInstallation(object(), threading.get_ident())
        if terminal == "pending"
        else runtime._PoisonedControllerRuntimeStateInstallation("bootstrap", "failure")
    )
    monkeypatch.setattr(runtime, "_RUNTIME_INSTALL_TERMINAL", runtime_terminal)
    monkeypatch.setattr(runtime, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    with pytest.raises(mod.SandboxBrokerRefused, match="exactly absent"):
        mod.runLegacyProcess(["git", "status"])

    assert calls == []


def test_legacy_process_holds_runtime_and_path_fences_through_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _broker()
    runtime = importlib.import_module("platform_core.runtime.controller_state")
    paths = importlib.import_module("platform_core.app_config.paths")
    entered = threading.Event()
    release = threading.Event()
    runtime_acquired = threading.Event()
    paths_acquired = threading.Event()

    def blocked_run(*args, **kwargs):
        del args, kwargs
        entered.set()
        assert release.wait(5)
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(runtime, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(runtime, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(subprocess, "run", blocked_run)

    effect = threading.Thread(target=lambda: mod.runLegacyProcess(["git", "status"]))
    effect.start()
    assert entered.wait(5)

    runtime_waiter = threading.Thread(
        target=lambda: (
            runtime._RUNTIME_BINDING_LOCK.acquire(),
            runtime_acquired.set(),
            runtime._RUNTIME_BINDING_LOCK.release(),
        )
    )
    paths_waiter = threading.Thread(
        target=lambda: (
            paths._CONTROLLER_PATHS_LOCK.acquire(),
            paths_acquired.set(),
            paths._CONTROLLER_PATHS_LOCK.release(),
        )
    )
    runtime_waiter.start()
    paths_waiter.start()
    assert not runtime_acquired.wait(0.1)
    assert not paths_acquired.wait(0.1)

    release.set()
    effect.join(5)
    runtime_waiter.join(5)
    paths_waiter.join(5)
    assert not effect.is_alive()
    assert runtime_acquired.is_set()
    assert paths_acquired.is_set()


@pytest.mark.parametrize("name", ["popenLegacyProcess", "legacyDiagnosticAutomationCall"])
def test_retained_legacy_process_and_automation_surfaces_fail_closed_before_effect(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    mod = _broker()
    runtime = importlib.import_module("platform_core.runtime.controller_state")
    paths = importlib.import_module("platform_core.app_config.paths")
    calls: list[object] = []
    monkeypatch.setattr(runtime, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(runtime, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: calls.append((args, kwargs)))

    with pytest.raises(mod.SandboxBrokerRefused, match="retained.*unavailable"):
        if name == "popenLegacyProcess":
            mod.popenLegacyProcess(["python", "-V"])
        else:
            mod.legacyDiagnosticAutomationCall(lambda: calls.append("automation"))

    assert calls == []


def test_explicit_automation_lease_holds_fences_until_same_thread_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _broker()
    runtime = importlib.import_module("platform_core.runtime.controller_state")
    paths = importlib.import_module("platform_core.app_config.paths")
    runtime_acquired = threading.Event()
    paths_acquired = threading.Event()
    stopped: list[bool] = []

    class Resource:
        marker = "resource"

        def stop(self) -> None:
            stopped.append(True)

    class Factory:
        def start(self) -> Resource:
            return Resource()

    monkeypatch.setattr(runtime, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(runtime, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    resource = mod.legacyDiagnosticAutomationLease(Factory).start()
    assert resource.marker == "resource"

    def claim(lock, event: threading.Event) -> None:
        with lock:
            event.set()

    runtime_waiter = threading.Thread(
        target=claim, args=(runtime._RUNTIME_BINDING_LOCK, runtime_acquired)
    )
    paths_waiter = threading.Thread(
        target=claim, args=(paths._CONTROLLER_PATHS_LOCK, paths_acquired)
    )
    runtime_waiter.start()
    paths_waiter.start()
    assert not runtime_acquired.wait(0.1)
    assert not paths_acquired.wait(0.1)

    resource.stop()
    runtime_waiter.join(5)
    paths_waiter.join(5)
    assert stopped == [True]
    assert runtime_acquired.is_set()
    assert paths_acquired.is_set()


def test_automation_lease_proxy_does_not_expose_raw_sdk_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _broker()
    runtime = importlib.import_module("platform_core.runtime.controller_state")
    paths = importlib.import_module("platform_core.app_config.paths")

    class Resource:
        def stop(self) -> None:
            return None

    class Factory:
        def start(self) -> Resource:
            return Resource()

    monkeypatch.setattr(runtime, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(runtime, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    resource = mod.legacyDiagnosticAutomationLease(Factory).start()
    try:
        with pytest.raises(AttributeError):
            getattr(resource, "_resource")
    finally:
        resource.stop()


def test_automation_context_resource_cannot_escape_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _broker()
    runtime = importlib.import_module("platform_core.runtime.controller_state")
    paths = importlib.import_module("platform_core.app_config.paths")

    class Resource:
        marker = "resource"

    class Context:
        def __enter__(self) -> Resource:
            return Resource()

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

    monkeypatch.setattr(runtime, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(runtime, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    escaped = None
    with mod.legacyDiagnosticAutomationLease(Context) as resource:
        escaped = resource
        assert resource.marker == "resource"

    assert escaped is not None
    with pytest.raises(mod.SandboxBrokerRefused, match="creating thread"):
        _ = escaped.marker
