"""Closed command broker for a credentialless candidate sandbox.

The credentialed model driver can submit only typed operations.  Path
normalization is repo-relative, component-by-component, and rejects Git metadata
and link traversal before the injected container runner is called.

RUN/TEST: python -m pytest tests/execution/test_sandbox_broker.py
"""

from __future__ import annotations

import os
import re
import threading
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Generic, Iterator, TypeVar

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}$")
_OPERATIONS = frozenset(
    {"repo_read", "repo_list", "repo_search", "repo_apply_patch", "repo_exec"}
)
_T = TypeVar("_T")


class SandboxBrokerRefused(RuntimeError):
    """The broker request cannot be confined to its registered clone resource."""


@contextmanager
def _legacyDiagnosticProcessPermit() -> Iterator[None]:
    """Hold runtime then path serialization for one brownfield process effect."""

    try:
        from platform_core.app_config.paths import controllerPathsActivationFence
        from platform_core.runtime.controller_state import (
            controllerRuntimeStateAbsentPermit,
        )
    except Exception as exc:
        raise SandboxBrokerRefused(
            "legacy diagnostic process requires exactly absent controller runtime"
        ) from exc

    stack = ExitStack()
    try:
        stack.enter_context(controllerRuntimeStateAbsentPermit())
        paths_active = stack.enter_context(controllerPathsActivationFence())
    except Exception as exc:
        stack.close()
        raise SandboxBrokerRefused(
            "legacy diagnostic process requires exactly absent controller runtime"
        ) from exc
    if paths_active:
        stack.close()
        raise SandboxBrokerRefused("legacy diagnostic process launch is unavailable")
    with stack:
        yield


def runLegacyProcess(*args: object, **kwargs: object) -> Any:
    """Brownfield subprocess seam, structurally disabled after capsule install."""

    with _legacyDiagnosticProcessPermit():
        import subprocess

        return subprocess.run(*args, **kwargs)  # type: ignore[call-overload]


def popenLegacyProcess(*args: object, **kwargs: object) -> Any:
    """Refuse retained child processes until the installed launcher owns them."""

    del args, kwargs
    with _legacyDiagnosticProcessPermit():
        raise SandboxBrokerRefused(
            "retained legacy process launch is unavailable; use the installed launcher"
        )


def legacyDiagnosticAutomationCall(
    operation: Callable[..., _T],
    *args: object,
    **kwargs: object,
) -> _T:
    """Refuse generic retained automation until it has an explicit lifetime."""

    del operation, args, kwargs
    with _legacyDiagnosticProcessPermit():
        raise SandboxBrokerRefused(
            "retained legacy automation is unavailable; use an authority-bound adapter"
        )


class _LegacyDiagnosticAutomationResource:
    """Delegate to one resource while its same-thread permit remains live."""

    __slots__ = ("__lease", "__resource")

    def __init__(self, lease: "LegacyDiagnosticAutomationLease", resource: Any) -> None:
        self.__lease = lease
        self.__resource = resource

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        self.__lease._requireOwner()
        return getattr(self.__resource, name)

    def stop(self) -> None:
        self.__lease._stopResource(self.__resource, "stop")

    def close(self) -> None:
        self.__lease._stopResource(self.__resource, "close")


class _LegacyDiagnosticAutomationContextResource:
    """Prevent a context-owned SDK root from escaping its authority lifetime."""

    __slots__ = ("__lease", "__resource")

    def __init__(self, lease: "LegacyDiagnosticAutomationLease", resource: Any) -> None:
        self.__lease = lease
        self.__resource = resource

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        self.__lease._requireOwner()
        return getattr(self.__resource, name)


class LegacyDiagnosticAutomationLease:
    """Explicit same-thread lifetime for a retained brownfield automation SDK."""

    __slots__ = (
        "_args",
        "_context",
        "_kwargs",
        "_operation",
        "_owner_thread_id",
        "_resource",
        "_stack",
    )

    def __init__(
        self,
        operation: Callable[..., Any],
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> None:
        self._operation = operation
        self._args = args
        self._kwargs = kwargs
        self._context: Any | None = None
        self._owner_thread_id: int | None = None
        self._resource: Any | None = None
        self._stack: ExitStack | None = None

    def _openFactory(self) -> Any:
        if self._stack is not None:
            raise SandboxBrokerRefused("automation lease is not reusable")
        self._owner_thread_id = threading.get_ident()
        stack = ExitStack()
        try:
            stack.enter_context(_legacyDiagnosticProcessPermit())
            result = self._operation(*self._args, **self._kwargs)
        except BaseException:
            stack.close()
            self._owner_thread_id = None
            raise
        self._stack = stack
        return result

    def _requireOwner(self) -> None:
        if self._stack is None or self._owner_thread_id != threading.get_ident():
            raise SandboxBrokerRefused(
                "automation lease must remain on its creating thread"
            )

    def _release(self) -> None:
        self._requireOwner()
        assert self._stack is not None
        stack = self._stack
        self._stack = None
        self._resource = None
        self._context = None
        self._owner_thread_id = None
        stack.close()

    def _stopResource(self, resource: Any, method: str) -> None:
        self._requireOwner()
        if resource is not self._resource:
            raise SandboxBrokerRefused("automation lease resource differs")
        try:
            getattr(resource, method)()
        finally:
            self._release()

    def start(self) -> Any:
        factory = self._openFactory()
        try:
            start = getattr(factory, "start", None)
            if not callable(start):
                raise SandboxBrokerRefused(
                    "automation lease factory has no start method"
                )
            resource = start()
        except BaseException:
            self._release()
            raise
        self._resource = resource
        return _LegacyDiagnosticAutomationResource(self, resource)

    def __enter__(self) -> Any:
        context = self._openFactory()
        try:
            resource = context.__enter__()
        except BaseException:
            self._release()
            raise
        self._context = context
        self._resource = resource
        return _LegacyDiagnosticAutomationContextResource(self, resource)

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        self._requireOwner()
        assert self._context is not None
        try:
            suppressed = bool(self._context.__exit__(exc_type, exc, tb))
        finally:
            self._release()
        return suppressed


def legacyDiagnosticAutomationLease(
    operation: Callable[..., Any],
    *args: object,
    **kwargs: object,
) -> LegacyDiagnosticAutomationLease:
    """Create an inert lease; authority is checked only on ``start``/entry."""

    return LegacyDiagnosticAutomationLease(operation, args, kwargs)


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise SandboxBrokerRefused("broker authority deadline is invalid") from exc
    if parsed.tzinfo is None:
        raise SandboxBrokerRefused("broker authority deadline is not absolute")
    return parsed.astimezone(timezone.utc)


def _relative_parts(value: str) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise SandboxBrokerRefused("broker path must be a non-empty POSIX relative path")
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or re.match(r"^[A-Za-z]:", value):
        raise SandboxBrokerRefused("absolute broker paths are forbidden")
    parts = candidate.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise SandboxBrokerRefused("broker path traversal is forbidden")
    if parts[0].casefold() == ".git" or any(part.casefold() == ".git" for part in parts):
        raise SandboxBrokerRefused("Git metadata is outside the broker surface")
    return tuple(parts)


def _is_reparse(info: os.stat_result) -> bool:
    return bool(getattr(info, "st_file_attributes", 0) & 0x400)


def normalizeBrokerPath(clone_root: str | Path, value: str) -> str:
    """Validate a logical repo-relative path without following link components."""

    root = Path(clone_root)
    if not root.is_absolute():
        raise SandboxBrokerRefused("clone root must be absolute")
    try:
        root_info = root.lstat()
    except OSError as exc:
        raise SandboxBrokerRefused("clone root is unavailable") from exc
    if root.is_symlink() or _is_reparse(root_info) or not root.is_dir():
        raise SandboxBrokerRefused("clone root identity is unsafe")
    parts = _relative_parts(value)
    current = root
    for index, part in enumerate(parts):
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            # Missing leaf/descendants are legal for a future write, but every
            # existing ancestor has already been checked without following it.
            break
        except OSError as exc:
            raise SandboxBrokerRefused("broker path cannot be inspected safely") from exc
        if current.is_symlink() or _is_reparse(info):
            raise SandboxBrokerRefused("broker path traverses a link or reparse point")
        if index < len(parts) - 1 and not current.is_dir():
            raise SandboxBrokerRefused("broker path ancestor is not a directory")
    return "/".join(parts)


@dataclass(frozen=True, slots=True)
class BrokerRequest:
    operation: str
    path: str = ""
    query: str = ""
    patch: str = ""
    argv: tuple[str, ...] = ()
    cwd: str = "."
    timeout_seconds: float = 60.0
    max_output_bytes: int = 2 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.operation not in _OPERATIONS:
            raise SandboxBrokerRefused("broker operation is unknown")
        if type(self.timeout_seconds) not in {int, float} or not (0 < self.timeout_seconds <= 600):
            raise SandboxBrokerRefused("broker timeout is outside policy")
        if type(self.max_output_bytes) is not int or not (0 < self.max_output_bytes <= 16 * 1024 * 1024):
            raise SandboxBrokerRefused("broker output quota is outside policy")
        for value, name in ((self.query, "query"), (self.patch, "patch")):
            if not isinstance(value, str) or "\x00" in value:
                raise SandboxBrokerRefused(f"broker {name} is invalid")
        if any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in self.argv):
            raise SandboxBrokerRefused("broker argv is invalid")


@dataclass(frozen=True, slots=True)
class SandboxCommandAuthority:
    transaction_id: str
    resource_id: str
    clone_root: str
    allowed_operations: frozenset[str]
    deadline: str
    _issuer_identity: int
    _seal: object


class SandboxCommandBroker(Generic[_T]):
    """Validate typed operations before dispatch to an injected container runner."""

    def __init__(
        self,
        *,
        clone_root: str | Path,
        runner: Callable[[BrokerRequest], _T],
        allowed_operations: frozenset[str],
        process_capability: object | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not allowed_operations or not allowed_operations <= _OPERATIONS:
            raise SandboxBrokerRefused("broker operation policy is invalid")
        self._clone_root = Path(clone_root)
        self._runner = runner
        self._allowed_operations = allowed_operations
        self._process_capability = process_capability
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._seal = object()
        self._identity = id(self)

    def issueAuthority(
        self,
        *,
        process_capability: object,
        transaction_id: str,
        resource_id: str,
        deadline: str,
    ) -> SandboxCommandAuthority:
        if self._process_capability is None or process_capability is not self._process_capability:
            raise SandboxBrokerRefused("process capability differs")
        for value, name in ((transaction_id, "transaction_id"), (resource_id, "resource_id")):
            if not isinstance(value, str) or not _ID.fullmatch(value):
                raise SandboxBrokerRefused(f"{name} is invalid")
        if _parse_time(deadline) <= self._clock().astimezone(timezone.utc):
            raise SandboxBrokerRefused("broker authority is already expired")
        return SandboxCommandAuthority(
            transaction_id=transaction_id,
            resource_id=resource_id,
            clone_root=str(self._clone_root),
            allowed_operations=self._allowed_operations,
            deadline=deadline,
            _issuer_identity=self._identity,
            _seal=self._seal,
        )

    def _validateAuthority(self, authority: object) -> SandboxCommandAuthority:
        if type(authority) is not SandboxCommandAuthority:
            raise SandboxBrokerRefused("exact process-local broker authority is required")
        assert isinstance(authority, SandboxCommandAuthority)
        if authority._issuer_identity != self._identity or authority._seal is not self._seal:
            raise SandboxBrokerRefused("broker authority issuer differs")
        if authority.clone_root != str(self._clone_root):
            raise SandboxBrokerRefused("broker authority clone differs")
        if authority.allowed_operations != self._allowed_operations:
            raise SandboxBrokerRefused("broker authority operation policy differs")
        if _parse_time(authority.deadline) <= self._clock().astimezone(timezone.utc):
            raise SandboxBrokerRefused("broker authority expired")
        return authority

    def execute(self, request: BrokerRequest, *, authority: object) -> _T:
        validated = self._validateAuthority(authority)
        if type(request) is not BrokerRequest or request.operation not in validated.allowed_operations:
            raise SandboxBrokerRefused("request is outside broker authority")
        path = request.path
        cwd = request.cwd
        if request.operation != "repo_exec" and not path:
            raise SandboxBrokerRefused("broker operation requires a path")
        if path:
            path = normalizeBrokerPath(self._clone_root, path)
        if cwd == ".":
            cwd = "."
        else:
            cwd = normalizeBrokerPath(self._clone_root, cwd)
        if request.operation == "repo_exec" and not request.argv:
            raise SandboxBrokerRefused("repo_exec requires typed argv")
        return self._runner(replace(request, path=path, cwd=cwd))


__all__ = [
    "BrokerRequest",
    "SandboxBrokerRefused",
    "SandboxCommandAuthority",
    "SandboxCommandBroker",
    "LegacyDiagnosticAutomationLease",
    "legacyDiagnosticAutomationCall",
    "legacyDiagnosticAutomationLease",
    "normalizeBrokerPath",
    "popenLegacyProcess",
    "runLegacyProcess",
]
