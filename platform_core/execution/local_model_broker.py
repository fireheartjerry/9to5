"""Anchor-controlled local-model broker with pinned loopback routing.

RUN/TEST: python -m pytest tests/execution/test_local_model_broker.py
"""

from __future__ import annotations

import ipaddress
import re
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Generic, Iterator, Mapping, Sequence, TypeVar
from urllib.parse import urlsplit

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,255}$")
_T = TypeVar("_T")


class LocalModelUnavailable(RuntimeError):
    """The local-model endpoint or exact capability evidence is unavailable."""


@contextmanager
def _diagnosticClientPermit() -> Iterator[None]:
    """Hold runtime then path serialization through one local SDK operation."""

    try:
        from platform_core.app_config.paths import controllerPathsActivationFence
        from platform_core.runtime.controller_state import (
            controllerRuntimeStateAbsentPermit,
        )
    except Exception as exc:
        raise LocalModelUnavailable(
            "diagnostic client requires exactly absent controller runtime"
        ) from exc

    stack = ExitStack()
    try:
        stack.enter_context(controllerRuntimeStateAbsentPermit())
        paths_active = stack.enter_context(controllerPathsActivationFence())
    except Exception as exc:
        stack.close()
        raise LocalModelUnavailable(
            "diagnostic client requires exactly absent controller runtime"
        ) from exc
    if paths_active:
        stack.close()
        raise LocalModelUnavailable("diagnostic client is unavailable in capsule mode")
    with stack:
        yield


class _DiagnosticOllamaClient:
    """Expose only guarded chat; the evolving SDK surface stays unreachable."""

    __slots__ = ("__client",)

    def __init__(self, client: Any) -> None:
        self.__client = client

    def chat(
        self,
        model: str = "",
        messages: Sequence[Mapping[str, object]] | None = None,
        *,
        stream: bool = False,
        format: object | None = None,
        options: Mapping[str, object] | object | None = None,
        keep_alive: float | str | None = None,
    ) -> Any:
        if stream is not False:
            raise LocalModelUnavailable(
                "streaming diagnostic client calls lack a retained runtime permit"
            )
        request: dict[str, object] = {"model": model}
        if messages is not None:
            request["messages"] = messages
        if format is not None:
            request["format"] = format
        if options is not None:
            request["options"] = options
        if keep_alive is not None:
            request["keep_alive"] = keep_alive
        with _diagnosticClientPermit():
            return self.__client.chat(**request)

    def close(self) -> None:
        close = getattr(self.__client, "close", None)
        if callable(close):
            close()

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)


def buildDiagnosticOllamaClient(*, host: str, timeout: float | None = None):
    """Build the historical SDK client only before controller-capsule install."""

    with _diagnosticClientPermit():
        import ollama

        options: dict[str, object] = {"host": host}
        if timeout is not None:
            options["timeout"] = timeout
        client = ollama.Client(**options)
    return _DiagnosticOllamaClient(client)


def _time(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise LocalModelUnavailable("local-model capability expiry is invalid") from exc
    if result.tzinfo is None:
        raise LocalModelUnavailable("local-model capability expiry is not absolute")
    return result.astimezone(timezone.utc)


def _endpoint(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise LocalModelUnavailable("local-model endpoint is malformed") from exc
    if (
        parsed.scheme != "http"
        or not host
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise LocalModelUnavailable("local-model endpoint is not a bare HTTP loopback authority")
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise LocalModelUnavailable("local-model endpoint must use a numeric loopback address") from exc
    if not address.is_loopback:
        raise LocalModelUnavailable("local-model endpoint is not loopback")
    return f"http://[{address.compressed}]:{port}" if address.version == 6 else f"http://{address.compressed}:{port}"


@dataclass(frozen=True, slots=True)
class LocalModelCapabilityReceipt:
    receipt_id: str
    endpoint: str
    model: str
    model_digest: str
    runtime_digest: str
    broker_policy_digest: str
    authority_scope_digest: str
    controller_generation: int
    revocation_generation: int
    expires_at: str
    _issuer_identity: int
    _seal: object


class LocalModelBroker(Generic[_T]):
    def __init__(
        self,
        *,
        endpoint: str,
        runtime_digest: str,
        model_digest: str,
        transport: Callable[[Mapping[str, object]], _T],
        broker_policy_digest: str | None = None,
        controller_generation: int = 1,
        revocation_generation: int = 0,
        process_capability: object | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._endpoint = _endpoint(endpoint)
        for value, name in ((runtime_digest, "runtime_digest"), (model_digest, "model_digest")):
            if not isinstance(value, str) or not _DIGEST.fullmatch(value):
                raise LocalModelUnavailable(f"{name} is invalid")
        if broker_policy_digest is not None and not _DIGEST.fullmatch(broker_policy_digest):
            raise LocalModelUnavailable("broker_policy_digest is invalid")
        if controller_generation < 1 or revocation_generation < 0:
            raise LocalModelUnavailable("local-model generations are invalid")
        self._runtime_digest = runtime_digest
        self._model_digest = model_digest
        self._policy_digest = broker_policy_digest or ("0" * 64)
        self._transport = transport
        self._controller_generation = controller_generation
        self._revocation_generation = revocation_generation
        self._process_capability = process_capability
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._identity = id(self)
        self._seal = object()

    def issueCapability(
        self,
        *,
        process_capability: object,
        receipt_id: str,
        model: str,
        authority_scope_digest: str,
        expires_at: str,
    ) -> LocalModelCapabilityReceipt:
        if self._process_capability is None or process_capability is not self._process_capability:
            raise LocalModelUnavailable("process capability differs")
        if not _ID.fullmatch(receipt_id) or not _ID.fullmatch(model):
            raise LocalModelUnavailable("local-model identity is invalid")
        if not _DIGEST.fullmatch(authority_scope_digest):
            raise LocalModelUnavailable("authority scope digest is invalid")
        if _time(expires_at) <= self._clock().astimezone(timezone.utc):
            raise LocalModelUnavailable("local-model capability is already expired")
        return LocalModelCapabilityReceipt(
            receipt_id=receipt_id,
            endpoint=self._endpoint,
            model=model,
            model_digest=self._model_digest,
            runtime_digest=self._runtime_digest,
            broker_policy_digest=self._policy_digest,
            authority_scope_digest=authority_scope_digest,
            controller_generation=self._controller_generation,
            revocation_generation=self._revocation_generation,
            expires_at=expires_at,
            _issuer_identity=self._identity,
            _seal=self._seal,
        )

    def _validate(self, authority: object, model: str) -> LocalModelCapabilityReceipt:
        if type(authority) is not LocalModelCapabilityReceipt:
            raise LocalModelUnavailable("exact process-local local-model capability is required")
        assert isinstance(authority, LocalModelCapabilityReceipt)
        if authority._issuer_identity != self._identity or authority._seal is not self._seal:
            raise LocalModelUnavailable("local-model capability issuer differs")
        if (
            authority.endpoint != self._endpoint
            or authority.model != model
            or authority.model_digest != self._model_digest
            or authority.runtime_digest != self._runtime_digest
            or authority.broker_policy_digest != self._policy_digest
            or authority.controller_generation != self._controller_generation
            or authority.revocation_generation != self._revocation_generation
        ):
            raise LocalModelUnavailable("local-model capability facts changed")
        if _time(authority.expires_at) <= self._clock().astimezone(timezone.utc):
            raise LocalModelUnavailable("local-model capability expired")
        return authority

    def chat(
        self,
        *,
        model: str,
        messages: Sequence[Mapping[str, object]],
        authority: object,
    ) -> _T:
        self._validate(authority, model)
        if not messages or len(messages) > 256:
            raise LocalModelUnavailable("local-model message set is empty or oversized")
        normalized: list[dict[str, str]] = []
        total = 0
        for message in messages:
            role = message.get("role")
            content = message.get("content")
            if role not in {"system", "user", "assistant"} or not isinstance(content, str):
                raise LocalModelUnavailable("local-model message is malformed")
            total += len(content.encode("utf-8"))
            if total > 2 * 1024 * 1024:
                raise LocalModelUnavailable("local-model prompt exceeds its quota")
            normalized.append({"role": role, "content": content})
        return self._transport(
            {
                "endpoint": self._endpoint,
                "model": model,
                "messages": tuple(normalized),
                "redirects": False,
                "proxies": False,
            }
        )

    def revoke(self, generation: int) -> None:
        if type(generation) is not int or generation <= self._revocation_generation:
            raise LocalModelUnavailable("revocation generation must advance")
        self._revocation_generation = generation


__all__ = [
    "LocalModelBroker",
    "LocalModelCapabilityReceipt",
    "LocalModelUnavailable",
    "buildDiagnosticOllamaClient",
]
