"""RED contracts for deny-by-default external effect boundaries."""

from __future__ import annotations

import asyncio
import importlib
import threading
import urllib.request

import pytest
import requests


def _effects():
    return importlib.import_module("platform_core.runtime.effect_guard")


def test_deferred_effect_is_returned_before_payload_construction() -> None:
    mod = _effects()
    calls: list[str] = []
    guard = mod.EffectGuard(controller_generation=7)

    result = guard.defer(
        effect_kind="discord_send",
        reason="durable effect command wave is inactive",
        payload_factory=lambda: calls.append("payload") or {"secret": "must-not-exist"},
    )

    assert isinstance(result, mod.EffectDeferred)
    assert result.effect_kind == "discord_send"
    assert result.controller_generation == 7
    assert result.activation_authority is False
    assert calls == []


def test_guard_has_no_runtime_enable_or_serialized_authority_surface() -> None:
    mod = _effects()
    public = {name for name in dir(mod.EffectGuard) if not name.startswith("_")}
    assert not public.intersection({"activate", "allow", "enable", "fromDict", "from_dict"})


def test_capsule_mode_refuses_legacy_network_before_client_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _effects()
    paths = importlib.import_module("platform_core.app_config.paths")
    calls: list[object] = []
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", object())
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: calls.append((args, kwargs)))

    with pytest.raises(mod.ExternalEffectAuthorityUnavailable, match="legacy diagnostic"):
        mod.legacyDiagnosticHttpGet("http://127.0.0.1:1/health")

    assert calls == []


def test_capsule_mode_refuses_legacy_discord_before_send_callable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _effects()
    paths = importlib.import_module("platform_core.app_config.paths")
    calls: list[object] = []
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", object())

    async def send(*args, **kwargs):
        calls.append((args, kwargs))

    with pytest.raises(mod.ExternalEffectAuthorityUnavailable, match="legacy diagnostic"):
        asyncio.run(mod.legacyDiagnosticDiscordSend(send, "secret"))

    assert calls == []


def test_discord_send_holds_runtime_and_path_fences_through_await(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _effects()
    runtime = importlib.import_module("platform_core.runtime.controller_state")
    paths = importlib.import_module("platform_core.app_config.paths")
    entered = threading.Event()
    release = threading.Event()
    runtime_acquired = threading.Event()
    paths_acquired = threading.Event()
    monkeypatch.setattr(runtime, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(runtime, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)

    async def send() -> str:
        entered.set()
        assert await asyncio.to_thread(release.wait, 5)
        return "sent"

    async def scenario() -> None:
        task = asyncio.create_task(mod.legacyDiagnosticDiscordSend(send))
        while not entered.is_set():
            await asyncio.sleep(0)

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
        assert await task == "sent"
        runtime_waiter.join(5)
        paths_waiter.join(5)

    asyncio.run(scenario())
    assert runtime_acquired.is_set()
    assert paths_acquired.is_set()


@pytest.mark.parametrize(
    "name,args",
    [
        ("legacyDiagnosticUrlopen", ("http://127.0.0.1:1/",)),
        ("legacyDiagnosticRequestsSession", ()),
        ("legacyDiagnosticSocket", ()),
    ],
)
def test_capsule_mode_refuses_extended_legacy_network_factories(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    args: tuple[object, ...],
) -> None:
    mod = _effects()
    paths = importlib.import_module("platform_core.app_config.paths")
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", object())

    with pytest.raises(mod.ExternalEffectAuthorityUnavailable, match="legacy diagnostic"):
        getattr(mod, name)(*args)


@pytest.mark.parametrize("terminal", ["pending", "poisoned"])
def test_nonabsent_runtime_refuses_http_with_paths_inactive_before_call(
    monkeypatch: pytest.MonkeyPatch,
    terminal: str,
) -> None:
    mod = _effects()
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
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: calls.append((args, kwargs)))

    with pytest.raises(mod.ExternalEffectAuthorityUnavailable, match="exactly absent"):
        mod.legacyDiagnosticHttpGet("http://127.0.0.1:1/health")

    assert calls == []


def test_http_effect_holds_runtime_and_path_fences_until_response_is_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _effects()
    runtime = importlib.import_module("platform_core.runtime.controller_state")
    paths = importlib.import_module("platform_core.app_config.paths")
    entered = threading.Event()
    release = threading.Event()
    runtime_acquired = threading.Event()
    paths_acquired = threading.Event()

    def blocked_get(*args, **kwargs):
        del args, kwargs
        entered.set()
        assert release.wait(5)
        return object()

    monkeypatch.setattr(runtime, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(runtime, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(requests, "get", blocked_get)

    effect = threading.Thread(
        target=lambda: mod.legacyDiagnosticHttpGet("http://127.0.0.1:1/health")
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


def test_urlopen_defers_request_and_holds_permits_for_response_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _effects()
    runtime = importlib.import_module("platform_core.runtime.controller_state")
    paths = importlib.import_module("platform_core.app_config.paths")
    calls: list[object] = []
    runtime_acquired = threading.Event()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return b"ok"

    monkeypatch.setattr(runtime, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(runtime, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *args, **kwargs: calls.append((args, kwargs)) or Response(),
    )

    resource = mod.legacyDiagnosticUrlopen("http://127.0.0.1:1/")
    assert calls == []
    with resource as response:
        assert response.read() == b"ok"
        waiter = threading.Thread(
            target=lambda: (
                runtime._RUNTIME_BINDING_LOCK.acquire(),
                runtime_acquired.set(),
                runtime._RUNTIME_BINDING_LOCK.release(),
            )
        )
        waiter.start()
        assert not runtime_acquired.wait(0.1)
    waiter.join(5)
    assert runtime_acquired.is_set()
    assert len(calls) == 1


def test_session_proxy_rechecks_runtime_before_each_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _effects()
    runtime = importlib.import_module("platform_core.runtime.controller_state")
    paths = importlib.import_module("platform_core.app_config.paths")
    calls: list[object] = []

    class Session:
        def request(self, *args, **kwargs):
            calls.append((args, kwargs))
            return object()

        def close(self) -> None:
            return None

    monkeypatch.setattr(runtime, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(runtime, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(requests, "Session", Session)
    session = mod.legacyDiagnosticRequestsSession()
    monkeypatch.setattr(runtime, "_RUNTIME_INSTALL_TERMINAL", object())

    with pytest.raises(mod.ExternalEffectAuthorityUnavailable, match="exactly absent"):
        session.request("GET", "http://127.0.0.1:1/")

    assert calls == []


def test_session_proxy_does_not_expose_raw_network_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _effects()
    runtime = importlib.import_module("platform_core.runtime.controller_state")
    paths = importlib.import_module("platform_core.app_config.paths")

    class Session:
        def close(self) -> None:
            return None

    monkeypatch.setattr(runtime, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(runtime, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(requests, "Session", Session)
    session = mod.legacyDiagnosticRequestsSession()

    with pytest.raises(AttributeError):
        getattr(session, "_session")


def test_session_proxy_does_not_return_adapter_escape_hatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _effects()
    runtime = importlib.import_module("platform_core.runtime.controller_state")
    paths = importlib.import_module("platform_core.app_config.paths")

    class Session:
        def get_adapter(self, url: str) -> object:
            del url
            return object()

        def close(self) -> None:
            return None

    monkeypatch.setattr(runtime, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(runtime, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(requests, "Session", Session)
    session = mod.legacyDiagnosticRequestsSession()

    with pytest.raises(AttributeError):
        session.get_adapter("https://example.invalid")


@pytest.mark.parametrize("stream", [True, 1, "yes"])
def test_streaming_requests_fail_before_network_call(
    monkeypatch: pytest.MonkeyPatch,
    stream: object,
) -> None:
    mod = _effects()
    runtime = importlib.import_module("platform_core.runtime.controller_state")
    paths = importlib.import_module("platform_core.app_config.paths")
    calls: list[object] = []
    monkeypatch.setattr(runtime, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(runtime, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: calls.append((args, kwargs)))

    with pytest.raises(mod.ExternalEffectAuthorityUnavailable, match="streaming"):
        mod.legacyDiagnosticHttpGet("http://127.0.0.1:1/", stream=stream)

    assert calls == []


def test_nonstreaming_http_response_is_closed_before_permit_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _effects()
    runtime = importlib.import_module("platform_core.runtime.controller_state")
    paths = importlib.import_module("platform_core.app_config.paths")

    class Response:
        closed = False

        def close(self) -> None:
            self.closed = True

    response = Response()
    monkeypatch.setattr(runtime, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(runtime, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: response)

    assert mod.legacyDiagnosticHttpGet("http://127.0.0.1:1/") is response
    assert response.closed is True


def test_socket_factory_is_lazy_and_rechecks_runtime_on_context_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _effects()
    runtime = importlib.import_module("platform_core.runtime.controller_state")
    paths = importlib.import_module("platform_core.app_config.paths")
    calls: list[object] = []
    monkeypatch.setattr(runtime, "_RUNTIME_INSTALL_TERMINAL", None)
    monkeypatch.setattr(runtime, "_RUNTIME_BINDING", None)
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", None)

    import socket

    monkeypatch.setattr(socket, "socket", lambda *args, **kwargs: calls.append((args, kwargs)))
    resource = mod.legacyDiagnosticSocket()
    monkeypatch.setattr(runtime, "_RUNTIME_INSTALL_TERMINAL", object())

    with pytest.raises(mod.ExternalEffectAuthorityUnavailable, match="exactly absent"):
        with resource:
            pass

    assert calls == []
