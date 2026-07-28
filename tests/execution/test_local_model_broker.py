"""RED contracts for the anchor-controlled local Ollama broker."""

from __future__ import annotations

import importlib
import inspect
import threading

import ollama
import pytest


def _local_model():
    return importlib.import_module("platform_core.execution.local_model_broker")


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://ollama.example:11434",
        "http://192.168.1.2:11434",
        "http://169.254.169.254:80",
        "http://[::]:11434",
    ],
)
def test_broker_rejects_every_non_loopback_endpoint(endpoint: str) -> None:
    mod = _local_model()
    with pytest.raises(mod.LocalModelUnavailable):
        mod.LocalModelBroker(
            endpoint=endpoint,
            runtime_digest="1" * 64,
            model_digest="2" * 64,
            transport=lambda request: {"message": {"content": "unexpected"}},
        )


def test_missing_capability_refuses_before_prompt_transport() -> None:
    mod = _local_model()
    calls: list[object] = []
    broker = mod.LocalModelBroker(
        endpoint="http://127.0.0.1:11434",
        runtime_digest="1" * 64,
        model_digest="2" * 64,
        transport=lambda request: calls.append(request),
    )

    with pytest.raises(mod.LocalModelUnavailable):
        broker.chat(
            model="pinned-model",
            messages=({"role": "user", "content": "secret context"},),
            authority=None,
        )

    assert calls == []


def test_capsule_mode_refuses_diagnostic_client_before_sdk_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _local_model()
    paths = importlib.import_module("platform_core.app_config.paths")
    calls: list[object] = []
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", object())
    monkeypatch.setattr(ollama, "Client", lambda *args, **kwargs: calls.append((args, kwargs)))

    with pytest.raises(mod.LocalModelUnavailable, match="diagnostic client"):
        mod.buildDiagnosticOllamaClient(host="http://127.0.0.1:11434", timeout=5)

    assert calls == []


@pytest.mark.parametrize("terminal", ["pending", "poisoned"])
def test_nonabsent_runtime_refuses_diagnostic_client_with_paths_inactive(
    monkeypatch: pytest.MonkeyPatch,
    terminal: str,
) -> None:
    mod = _local_model()
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
    monkeypatch.setattr(ollama, "Client", lambda *args, **kwargs: calls.append((args, kwargs)))

    with pytest.raises(mod.LocalModelUnavailable, match="exactly absent"):
        mod.buildDiagnosticOllamaClient(host="http://127.0.0.1:11434", timeout=5)

    assert calls == []


def test_diagnostic_client_rechecks_runtime_before_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _local_model()
    runtime = importlib.import_module("platform_core.runtime.controller_state")
    paths = importlib.import_module("platform_core.app_config.paths")
    calls: list[object] = []

    class Client:
        def __init__(self, **kwargs):
            calls.append(("construct", kwargs))

        def chat(self, **kwargs):
            calls.append(("chat", kwargs))
            return {"message": {"content": "ok"}}

    monkeypatch.setattr(runtime, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(runtime, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(ollama, "Client", Client)
    client = mod.buildDiagnosticOllamaClient(host="http://127.0.0.1:11434", timeout=5)
    monkeypatch.setattr(runtime, "_RUNTIME_INSTALL_TERMINAL", object())

    with pytest.raises(mod.LocalModelUnavailable, match="exactly absent"):
        client.chat(model="model", messages=[])

    assert [kind for kind, _ in calls] == ["construct"]


def test_diagnostic_client_does_not_expose_raw_sdk_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _local_model()
    runtime = importlib.import_module("platform_core.runtime.controller_state")
    paths = importlib.import_module("platform_core.app_config.paths")

    class Client:
        def __init__(self, **kwargs):
            del kwargs

    monkeypatch.setattr(runtime, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(runtime, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(ollama, "Client", Client)
    client = mod.buildDiagnosticOllamaClient(host="http://127.0.0.1:11434")

    with pytest.raises(AttributeError):
        getattr(client, "_client")


def test_diagnostic_client_exposes_only_chat_not_sdk_web_or_blob_methods(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _local_model()
    runtime = importlib.import_module("platform_core.runtime.controller_state")
    paths = importlib.import_module("platform_core.app_config.paths")
    calls: list[str] = []

    class Client:
        def __init__(self, **kwargs):
            del kwargs

        def web_search(self, query: str) -> object:
            calls.append(query)
            return object()

    monkeypatch.setattr(runtime, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(runtime, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(ollama, "Client", Client)
    client = mod.buildDiagnosticOllamaClient(host="http://127.0.0.1:11434")

    with pytest.raises(AttributeError):
        client.web_search("secret")

    assert calls == []


def test_diagnostic_chat_signature_does_not_claim_private_act_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _local_model()
    runtime = importlib.import_module("platform_core.runtime.controller_state")
    paths = importlib.import_module("platform_core.app_config.paths")

    class Client:
        def __init__(self, **kwargs):
            del kwargs

        def chat(self, **kwargs):
            return kwargs

    monkeypatch.setattr(runtime, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(runtime, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(ollama, "Client", Client)
    client = mod.buildDiagnosticOllamaClient(host="http://127.0.0.1:11434")
    parameters = inspect.signature(client.chat).parameters.values()

    assert "act" not in inspect.signature(client.chat).parameters
    assert all(parameter.kind is not inspect.Parameter.VAR_KEYWORD for parameter in parameters)


def test_diagnostic_client_refuses_nonboolean_streaming_before_sdk_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _local_model()
    runtime = importlib.import_module("platform_core.runtime.controller_state")
    paths = importlib.import_module("platform_core.app_config.paths")
    calls: list[object] = []

    class Client:
        def __init__(self, **kwargs):
            del kwargs

        def chat(self, **kwargs):
            calls.append(kwargs)
            return iter(())

    monkeypatch.setattr(runtime, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(runtime, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(ollama, "Client", Client)
    client = mod.buildDiagnosticOllamaClient(host="http://127.0.0.1:11434")

    with pytest.raises(mod.LocalModelUnavailable, match="streaming"):
        client.chat(model="model", messages=[], stream="yes")

    assert calls == []


def test_diagnostic_client_holds_runtime_and_path_fences_through_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _local_model()
    runtime = importlib.import_module("platform_core.runtime.controller_state")
    paths = importlib.import_module("platform_core.app_config.paths")
    entered = threading.Event()
    release = threading.Event()
    runtime_acquired = threading.Event()
    paths_acquired = threading.Event()

    class Client:
        def __init__(self, **kwargs):
            del kwargs

        def chat(self, **kwargs):
            del kwargs
            entered.set()
            assert release.wait(5)
            return {"message": {"content": "ok"}}

    monkeypatch.setattr(runtime, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(runtime, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(ollama, "Client", Client)
    client = mod.buildDiagnosticOllamaClient(host="http://127.0.0.1:11434", timeout=5)

    effect = threading.Thread(
        target=lambda: client.chat(model="model", messages=[])
    )
    effect.start()
    assert entered.wait(5)

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

    release.set()
    effect.join(5)
    runtime_waiter.join(5)
    paths_waiter.join(5)
    assert runtime_acquired.is_set()
    assert paths_acquired.is_set()
