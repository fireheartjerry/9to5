"""Deny-by-default boundary for effects deferred beyond this kernel wave.

Task 3 has no effect execution authority.  The guard can produce an inert fact
without constructing a payload, path, client, process, or network object.

RUN/TEST: python -m pytest tests/execution/test_effect_guard.py tests/evolution/test_maintenance_deep_boundaries.py
"""

from __future__ import annotations

import re
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Iterable, Iterator, Literal, TypeVar


class ExternalEffectAuthorityUnavailable(RuntimeError):
    """No durable effect-command authority exists in this kernel wave."""


_T = TypeVar("_T")


@contextmanager
def _legacyDiagnosticEffectPermit() -> Iterator[None]:
    """Hold runtime then path serialization through one legacy effect."""

    try:
        from platform_core.app_config.paths import controllerPathsActivationFence
        from platform_core.runtime.controller_state import (
            controllerRuntimeStateAbsentPermit,
        )
    except Exception as exc:
        raise ExternalEffectAuthorityUnavailable(
            "legacy diagnostic effect requires exactly absent controller runtime"
        ) from exc

    stack = ExitStack()
    try:
        stack.enter_context(controllerRuntimeStateAbsentPermit())
        paths_active = stack.enter_context(controllerPathsActivationFence())
    except Exception as exc:
        stack.close()
        raise ExternalEffectAuthorityUnavailable(
            "legacy diagnostic effect requires exactly absent controller runtime"
        ) from exc
    if paths_active:
        stack.close()
        raise ExternalEffectAuthorityUnavailable(
            "legacy diagnostic network effects are unavailable"
        )
    with stack:
        yield


def _refuseStreaming(kwargs: dict[str, object]) -> None:
    if "stream" in kwargs and kwargs["stream"] is not False:
        raise ExternalEffectAuthorityUnavailable(
            "streaming legacy HTTP responses lack a retained runtime permit"
        )


def _closeCompletedResponse(response: _T) -> _T:
    """Retire a non-streaming response before its authority fence is released."""

    close = getattr(response, "close", None)
    if callable(close):
        close()
    return response


def legacyDiagnosticHttpGet(*args: object, **kwargs: object):
    """Brownfield GET seam; capsule production has no direct network authority."""

    _refuseStreaming(kwargs)
    with _legacyDiagnosticEffectPermit():
        import requests  # type: ignore[import-untyped]

        return _closeCompletedResponse(requests.get(*args, **kwargs))


def legacyDiagnosticHttpPost(*args: object, **kwargs: object):
    """Brownfield POST seam; capsule production has no direct network authority."""

    _refuseStreaming(kwargs)
    with _legacyDiagnosticEffectPermit():
        import requests  # type: ignore[import-untyped]

        return _closeCompletedResponse(requests.post(*args, **kwargs))


def legacyDiagnosticHttpPut(*args: object, **kwargs: object):
    """Brownfield PUT seam; capsule production has no direct network authority."""

    _refuseStreaming(kwargs)
    with _legacyDiagnosticEffectPermit():
        import requests  # type: ignore[import-untyped]

        return _closeCompletedResponse(requests.put(*args, **kwargs))


@contextmanager
def _legacyDiagnosticUrlopenContext(
    args: tuple[object, ...], kwargs: dict[str, object]
) -> Iterator[Any]:
    with _legacyDiagnosticEffectPermit():
        import urllib.request

        with urllib.request.urlopen(  # type: ignore[call-overload]  # noqa: S310
            *args, **kwargs
        ) as response:
            yield response


def legacyDiagnosticUrlopen(*args: object, **kwargs: object) -> Any:
    """Return a same-thread context whose permit spans the response lifetime."""

    # Refuse construction itself after activation, then re-check on entry so a
    # runtime transition between these two moments cannot create authority.
    with _legacyDiagnosticEffectPermit():
        pass
    return _legacyDiagnosticUrlopenContext(args, kwargs)


class _LegacyDiagnosticRequestsSession:
    """A session pool whose every possible network method is independently fenced."""

    # ``__dict__`` preserves the incumbent test-double injection seam while the
    # raw session itself remains name-mangled and underscore access is refused.
    __slots__ = ("__session", "__dict__")

    def __init__(self, session: Any) -> None:
        self.__session = session

    def _invoke(self, name: str, *args: object, **kwargs: object) -> Any:
        _refuseStreaming(kwargs)
        with _legacyDiagnosticEffectPermit():
            result = getattr(self.__session, name)(*args, **kwargs)
            if name in {
                "delete",
                "get",
                "head",
                "options",
                "patch",
                "post",
                "put",
                "request",
                "send",
            }:
                return _closeCompletedResponse(result)
            return result

    def request(self, *args: object, **kwargs: object) -> Any:
        return self._invoke("request", *args, **kwargs)

    def close(self) -> None:
        # Cleanup cannot create new network authority and must remain possible
        # after the controller terminal advances.
        self.__session.close()

    def __enter__(self) -> "_LegacyDiagnosticRequestsSession":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> Literal[False]:
        self.close()
        return False

    def __getattr__(self, name: str) -> Any:
        # The only compatibility surface required by the incumbent is
        # ``request``. Returning adapters, pool managers, or convenience
        # methods would let a network-capable descendant escape this proxy.
        raise AttributeError(name)


def legacyDiagnosticRequestsSession(*args: object, **kwargs: object) -> Any:
    with _legacyDiagnosticEffectPermit():
        import requests  # type: ignore[import-untyped]

        session = requests.Session(*args, **kwargs)
    return _LegacyDiagnosticRequestsSession(session)


@contextmanager
def _legacyDiagnosticSocketContext(
    args: tuple[object, ...], kwargs: dict[str, object]
) -> Iterator[Any]:
    with _legacyDiagnosticEffectPermit():
        import socket

        with socket.socket(*args, **kwargs) as sock:  # type: ignore[arg-type]
            yield sock


def legacyDiagnosticSocket(*args: object, **kwargs: object) -> Any:
    """Return a same-thread context whose permit spans the socket lifetime."""

    with _legacyDiagnosticEffectPermit():
        pass
    return _legacyDiagnosticSocketContext(args, kwargs)


async def legacyDiagnosticDiscordSend(
    send: Callable[..., Awaitable[_T]],
    *args: object,
    **kwargs: object,
) -> _T:
    """Invoke one brownfield Discord send only before capsule installation."""

    with _legacyDiagnosticEffectPermit():
        return await send(*args, **kwargs)


_MAINTENANCE_SEAL = object()
_OPERATION = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")


def _time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ExternalEffectAuthorityUnavailable("maintenance authority expiry is invalid") from exc
    if parsed.tzinfo is None:
        raise ExternalEffectAuthorityUnavailable("maintenance authority expiry is not absolute")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class MaintenanceAuthority:
    operations: frozenset[str]
    controller_generation: int
    expires_at: str
    _process_capability: object
    _seal: object


def issueDiagnosticMaintenanceAuthority(
    *,
    operations: Iterable[str],
    controller_generation: int,
    process_capability: object,
    expires_at: str,
) -> MaintenanceAuthority:
    """Test seam; installed production authority is external and non-serializable."""

    scoped = frozenset(operations)
    if not scoped or any(not isinstance(value, str) or not _OPERATION.fullmatch(value) for value in scoped):
        raise ExternalEffectAuthorityUnavailable("maintenance operation scope is invalid")
    if type(controller_generation) is not int or controller_generation < 1 or process_capability is None:
        raise ExternalEffectAuthorityUnavailable("maintenance authority identity is invalid")
    if _time(expires_at) <= datetime.now(timezone.utc):
        raise ExternalEffectAuthorityUnavailable("maintenance authority already expired")
    return MaintenanceAuthority(
        operations=scoped,
        controller_generation=controller_generation,
        expires_at=expires_at,
        _process_capability=process_capability,
        _seal=_MAINTENANCE_SEAL,
    )


def validateMaintenanceAuthority(
    authority: object,
    *,
    operation: str,
    controller_state_authority: object,
) -> MaintenanceAuthority:
    if type(authority) is not MaintenanceAuthority:
        raise ExternalEffectAuthorityUnavailable("exact maintenance authority is required")
    assert isinstance(authority, MaintenanceAuthority)
    if authority._seal is not _MAINTENANCE_SEAL or authority._process_capability is None:
        raise ExternalEffectAuthorityUnavailable("maintenance authority issuer differs")
    if operation not in authority.operations:
        raise ExternalEffectAuthorityUnavailable("maintenance operation is outside authority")
    if _time(authority.expires_at) <= datetime.now(timezone.utc):
        raise ExternalEffectAuthorityUnavailable("maintenance authority expired")
    from platform_core.runtime.controller_state import ControllerStateAuthority

    if type(controller_state_authority) is not ControllerStateAuthority:
        raise ExternalEffectAuthorityUnavailable("controller-state authority is required")
    return authority


@dataclass(frozen=True, slots=True)
class EffectDeferred:
    effect_kind: str
    reason: str
    controller_generation: int
    activation_authority: bool = False

    def toDict(self) -> dict[str, object]:
        return {
            "activation_authority": False,
            "controller_generation": self.controller_generation,
            "effect_kind": self.effect_kind,
            "reason": self.reason,
            "status": "effect_deferred",
        }


class EffectGuard:
    """Create inert deferral facts; deliberately exposes no enabling method."""

    def __init__(self, *, controller_generation: int) -> None:
        if type(controller_generation) is not int or controller_generation < 1:
            raise ExternalEffectAuthorityUnavailable("controller generation is invalid")
        self._controller_generation = controller_generation

    def defer(
        self,
        *,
        effect_kind: str,
        reason: str,
        payload_factory: Callable[[], object] | None = None,
    ) -> EffectDeferred:
        # payload_factory is intentionally never invoked.  It exists only so a
        # deepest boundary can prove that deferral precedes payload construction.
        del payload_factory
        if not isinstance(effect_kind, str) or not effect_kind or len(effect_kind) > 128:
            raise ExternalEffectAuthorityUnavailable("effect kind is invalid")
        if not isinstance(reason, str) or not reason or len(reason) > 1024:
            raise ExternalEffectAuthorityUnavailable("effect reason is invalid")
        return EffectDeferred(
            effect_kind=effect_kind,
            reason=reason,
            controller_generation=self._controller_generation,
        )


def maintenanceDeferred(operation: str, *, reason: str = "maintenance authority unavailable") -> dict[str, object]:
    """Return a stable compatibility mapping before maintenance input lookup."""

    fact = EffectGuard(controller_generation=1).defer(
        effect_kind=f"maintenance:{operation}",
        reason=reason,
    )
    result = fact.toDict()
    result["status"] = "maintenance_deferred"
    return result


__all__ = [
    "EffectDeferred",
    "EffectGuard",
    "ExternalEffectAuthorityUnavailable",
    "MaintenanceAuthority",
    "issueDiagnosticMaintenanceAuthority",
    "legacyDiagnosticDiscordSend",
    "legacyDiagnosticHttpGet",
    "legacyDiagnosticHttpPost",
    "legacyDiagnosticHttpPut",
    "legacyDiagnosticRequestsSession",
    "legacyDiagnosticSocket",
    "legacyDiagnosticUrlopen",
    "maintenanceDeferred",
    "validateMaintenanceAuthority",
]
