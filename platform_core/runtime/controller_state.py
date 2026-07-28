"""Authority-bound external controller state and writer inventory.

Authoritative JSON uses retained native directory handles and logical IDs.  No
caller-supplied path can escape the anchor-attested root.

RUN/TEST: python -m pytest tests/control/test_external_controller_state.py tests/execution/test_external_state_writers.py
"""

from __future__ import annotations

import ast
import copy
import errno
import json
import os
import re
import secrets
import stat
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, TypeVar, cast

from platform_core.core.fsio import NativeDirectoryHandle, assertNoReparsePath, openNativeDirectory

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}$")
_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_DIAGNOSTIC_SEAL = object()
_INSTALLED_SEAL = object()
_MAX_JSON = 16 * 1024 * 1024
_LOCK_NAME = ".controller-state.lock"
_LOCK_TIMEOUT_SECONDS = 30.0
_T = TypeVar("_T")


class ControllerStateRefused(RuntimeError):
    """The controller-state request is unbound, unsafe, or ambiguous."""


class _ControllerStateStoreConstructionCleanupError(ControllerStateRefused):
    """Retained constructor resources could not be unwound exactly."""

    def __init__(self, cleanup_errors: tuple[BaseException, ...]) -> None:
        super().__init__("controller-state constructor cleanup is ambiguous")
        self.cleanup_errors = cleanup_errors


def _controller_paths_active() -> bool:
    try:
        from platform_core.app_config.paths import controllerPathsActive

        return bool(controllerPathsActive())
    except Exception:
        # Ambiguous bootstrap state never permits diagnostic authority creation.
        return True


def _time(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ControllerStateRefused("controller-state authority expiry is invalid") from exc
    if result.tzinfo is None:
        raise ControllerStateRefused("controller-state authority expiry is not absolute")
    return result.astimezone(timezone.utc)


def _root(value: str | Path) -> Path:
    try:
        path = Path(value)
    except (TypeError, OSError) as exc:
        raise ControllerStateRefused("controller-state root is invalid") from exc
    if not path.is_absolute():
        raise ControllerStateRefused("controller-state root must be absolute")
    try:
        return path.resolve(strict=False)
    except OSError as exc:
        raise ControllerStateRefused("controller-state root cannot be normalized") from exc


def _canonical(value: object) -> bytes:
    try:
        raw = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ControllerStateRefused("controller-state JSON is not canonicalizable") from exc
    if len(raw) > _MAX_JSON:
        raise ControllerStateRefused("controller-state JSON exceeds its quota")
    return raw


def _logical(value: str) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ControllerStateRefused("controller-state logical ID is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ControllerStateRefused("controller-state logical ID traverses")
    if not path.parts or any(not _PART.fullmatch(part) for part in path.parts):
        raise ControllerStateRefused("controller-state logical ID has an invalid component")
    return tuple(path.parts)


@dataclass(frozen=True, slots=True)
class ControllerStateAuthority:
    """Opaque process-local handle; all scope remains issuer-owned."""

    authority_id: str
    _token: object

    @property
    def root(self) -> str:
        return _controllerAuthorityScope(self).root

    @property
    def repository_id(self) -> str:
        return _controllerAuthorityScope(self).repository_id

    @property
    def controller_generation(self) -> int:
        return _controllerAuthorityScope(self).controller_generation

    @property
    def expires_at(self) -> str:
        return _controllerAuthorityScope(self).expires_at


@dataclass(frozen=True, slots=True)
class _ControllerStateAuthorityScope:
    root: str
    source_root: str
    installed_controller_root: str
    repository_id: str
    controller_generation: int
    expires_at: str
    process_capability: object
    provenance: str
    seal: object
    outer_scope_digest: str
    capsule_scope_digest: str
    child_pid: int
    activation_generation: int
    boot_generation: int
    watchdog_generation: int
    revocation_generation: int
    bootstrap_guard: object | None
    runtime_install_capability: object | None


@dataclass(frozen=True, slots=True)
class _IssuedControllerStateAuthority:
    authority: ControllerStateAuthority
    token: object
    scope: _ControllerStateAuthorityScope
    scope_digest: bytes


_AUTHORITY_REGISTRY_LOCK = threading.RLock()
_AUTHORITY_REGISTRY: dict[str, _IssuedControllerStateAuthority] = {}
_MAX_AUTHORITY_ID_ATTEMPTS = 32


def _isDiagnosticScope(scope: _ControllerStateAuthorityScope) -> bool:
    return (
        scope.provenance == "diagnostic"
        and scope.seal is _DIAGNOSTIC_SEAL
        and scope.bootstrap_guard is None
    )


def _controllerAuthorityScopeDigest(scope: _ControllerStateAuthorityScope) -> bytes:
    return _canonical(
        {
            "controller_generation": scope.controller_generation,
            "expires_at": scope.expires_at,
            "process_capability_identity": id(scope.process_capability),
            "provenance": scope.provenance,
            "repository_id": scope.repository_id,
            "root": scope.root,
            "source_root": scope.source_root,
            "installed_controller_root": scope.installed_controller_root,
            "seal_identity": id(scope.seal),
            "outer_scope_digest": scope.outer_scope_digest,
            "capsule_scope_digest": scope.capsule_scope_digest,
            "child_pid": scope.child_pid,
            "activation_generation": scope.activation_generation,
            "boot_generation": scope.boot_generation,
            "watchdog_generation": scope.watchdog_generation,
            "revocation_generation": scope.revocation_generation,
            "bootstrap_guard_identity": id(scope.bootstrap_guard),
            "runtime_install_capability_identity": id(
                scope.runtime_install_capability
            ),
        }
    )


def _controllerAuthorityScope(
    authority: object,
) -> _ControllerStateAuthorityScope:
    if type(authority) is not ControllerStateAuthority:
        raise ControllerStateRefused("exact controller-state authority is required")
    assert isinstance(authority, ControllerStateAuthority)
    with _AUTHORITY_REGISTRY_LOCK:
        issued = _AUTHORITY_REGISTRY.get(authority.authority_id)
        if (
            issued is None
            or issued.authority is not authority
            or authority._token is not issued.token
            or issued.scope_digest != _controllerAuthorityScopeDigest(issued.scope)
        ):
            raise ControllerStateRefused("controller-state authority issuer differs")
        return issued.scope


def _bootstrapEpochPermit(scope: _ControllerStateAuthorityScope):
    """Return the installed epoch permit without weakening diagnostic behavior."""

    if scope.bootstrap_guard is None:
        return nullcontext()
    permit_factory = getattr(scope.bootstrap_guard, "bootstrapEpochPermit", None)
    if not callable(permit_factory):
        raise ControllerStateRefused(
            "controller-state bootstrap permit is unavailable"
        )
    return permit_factory(
        outer_scope_digest=scope.outer_scope_digest,
        capsule_scope_digest=scope.capsule_scope_digest,
        controller_generation=scope.controller_generation,
        watchdog_generation=scope.watchdog_generation,
        revocation_generation=scope.revocation_generation,
        child_pid=scope.child_pid,
        activation_generation=scope.activation_generation,
        boot_generation=scope.boot_generation,
    )


@contextmanager
def _heldBootstrapEpoch(scope: _ControllerStateAuthorityScope):
    """Translate permit-entry refusal while preserving operation exceptions."""

    permit = _bootstrapEpochPermit(scope)
    with ExitStack() as stack:
        try:
            stack.enter_context(permit)
        except Exception as exc:
            raise ControllerStateRefused(
                "controller-state bootstrap permit is no longer live"
            ) from exc
        yield


@contextmanager
def _heldInstalledBootstrapAuthorities(value: object):
    """Translate complete-bundle permit entry refusal at the store boundary."""

    from platform_core.runtime.bootstrap_authority import (
        _installedBootstrapRuntimePermit,
    )

    permit = _installedBootstrapRuntimePermit(value)
    with ExitStack() as stack:
        try:
            projection = stack.enter_context(permit)
        except Exception as exc:
            raise ControllerStateRefused(
                "controller-state bootstrap bundle is no longer live"
            ) from exc
        yield projection


def _registerControllerStateAuthority(
    scope: _ControllerStateAuthorityScope,
) -> ControllerStateAuthority:
    for _attempt in range(_MAX_AUTHORITY_ID_ATTEMPTS):
        authority_id = secrets.token_hex(32)
        if (
            type(authority_id) is not str
            or re.fullmatch(r"[0-9a-f]{64}", authority_id) is None
        ):
            raise ControllerStateRefused(
                "controller-state authority ID generator is invalid"
            )
        token = object()
        authority = ControllerStateAuthority(authority_id=authority_id, _token=token)
        issued = _IssuedControllerStateAuthority(
            authority=authority,
            token=token,
            scope=scope,
            scope_digest=_controllerAuthorityScopeDigest(scope),
        )
        with _AUTHORITY_REGISTRY_LOCK:
            if authority_id in _AUTHORITY_REGISTRY:
                continue
            _AUTHORITY_REGISTRY[authority_id] = issued
            return authority
    raise ControllerStateRefused(
        "controller-state authority ID collision budget exhausted"
    )


def _retireControllerStateAuthority(authority: object) -> None:
    """Remove only the exact unpublished authority during bundle rollback."""

    if type(authority) is not ControllerStateAuthority:
        return
    assert isinstance(authority, ControllerStateAuthority)
    with _AUTHORITY_REGISTRY_LOCK:
        issued = _AUTHORITY_REGISTRY.get(authority.authority_id)
        if issued is not None and issued.authority is authority:
            _AUTHORITY_REGISTRY.pop(authority.authority_id, None)


def issueDiagnosticControllerStateAuthority(
    *,
    root: str | Path,
    repository_id: str,
    controller_generation: int,
    process_capability: object,
    expires_at: str,
) -> ControllerStateAuthority:
    """Test seam; installed production receives this from the external anchor."""

    from platform_core.app_config.paths import controllerPathsActivationFence

    # Minting and path publication share one linearization point.  Keep the
    # path lock across registration so activation cannot slip between the
    # inactive observation and the issuer-owned authority record.
    with controllerRuntimeStateAbsentPermit():
        with controllerPathsActivationFence() as paths_active:
            if paths_active or _controller_paths_active():
                raise ControllerStateRefused(
                    "diagnostic controller-state authority is unavailable after activation"
                )
            if (
                type(repository_id) is not str
                or not _ID.fullmatch(repository_id)
                or type(controller_generation) is not int
                or controller_generation < 1
            ):
                raise ControllerStateRefused(
                    "controller-state authority scope is invalid"
                )
            if process_capability is None:
                raise ControllerStateRefused(
                    "controller-state process capability is required"
                )
            if _time(expires_at) <= datetime.now(timezone.utc):
                raise ControllerStateRefused(
                    "controller-state authority already expired"
                )
            scope = _ControllerStateAuthorityScope(
                root=str(_root(root)),
                source_root="",
                installed_controller_root="",
                repository_id=repository_id,
                controller_generation=controller_generation,
                expires_at=expires_at,
                process_capability=process_capability,
                provenance="diagnostic",
                seal=_DIAGNOSTIC_SEAL,
                outer_scope_digest="",
                capsule_scope_digest="",
                child_pid=0,
                activation_generation=0,
                boot_generation=0,
                watchdog_generation=0,
                revocation_generation=0,
                bootstrap_guard=None,
                runtime_install_capability=None,
            )
            return _registerControllerStateAuthority(scope)


def _buildInstalledControllerStateAuthority(
    *,
    resolved_outer_capabilities: object,
    bootstrap_guard: object,
) -> ControllerStateAuthority:
    """Private bundle builder; caller-supplied scope facts are intentionally absent."""

    outer = resolved_outer_capabilities
    scope = getattr(outer, "bootstrap_scope", None)
    if scope is None or bootstrap_guard is None:
        raise ControllerStateRefused("installed bootstrap scope is unavailable")
    outer_scope_digest = getattr(outer, "scope_digest", None)
    if type(outer_scope_digest) is not str:
        raise ControllerStateRefused("installed outer scope digest is unavailable")
    return _registerControllerStateAuthority(
        _ControllerStateAuthorityScope(
            root=scope.controller_state_root,
            source_root=scope.source_root,
            installed_controller_root=scope.installed_controller_root,
            repository_id=scope.canonical_repository_id,
            controller_generation=scope.controller_generation,
            expires_at=scope.capability_expires_at,
            process_capability=getattr(outer, "process_capability"),
            provenance="installed",
            seal=_INSTALLED_SEAL,
            outer_scope_digest=outer_scope_digest,
            capsule_scope_digest=scope.digest(),
            child_pid=getattr(outer, "child_pid"),
            activation_generation=scope.activation_generation,
            boot_generation=scope.boot_generation,
            watchdog_generation=scope.watchdog_generation,
            revocation_generation=scope.revocation_generation,
            bootstrap_guard=bootstrap_guard,
            runtime_install_capability=object(),
        )
    )


def deriveInstalledControllerStateAuthority(
    *,
    outer_capabilities: object,
) -> ControllerStateAuthority:
    """Project the memoized controller authority from one atomic bootstrap bundle."""

    from platform_core.runtime.bootstrap_authority import (
        deriveInstalledBootstrapAuthorities,
    )

    return deriveInstalledBootstrapAuthorities(
        outer_capabilities=outer_capabilities
    ).controller_state_authority


def validateControllerStateAuthority(
    authority: object,
    *,
    root: str | Path | None = None,
    repository_id: str | None = None,
    controller_generation: int | None = None,
) -> ControllerStateAuthority:
    """Pure exact-type validation shared by config and state boundaries."""

    scope = _controllerAuthorityScope(authority)
    diagnostic = (
        scope.provenance == "diagnostic"
        and scope.seal is _DIAGNOSTIC_SEAL
        and scope.outer_scope_digest == ""
        and scope.capsule_scope_digest == ""
        and scope.child_pid == 0
        and scope.activation_generation == 0
        and scope.boot_generation == 0
        and scope.watchdog_generation == 0
        and scope.revocation_generation == 0
        and scope.bootstrap_guard is None
        and scope.source_root == ""
        and scope.installed_controller_root == ""
        and scope.runtime_install_capability is None
    )
    installed = (
        scope.provenance == "installed"
        and scope.seal is _INSTALLED_SEAL
        and re.fullmatch(r"[0-9a-f]{64}", scope.outer_scope_digest) is not None
        and re.fullmatch(r"[0-9a-f]{64}", scope.capsule_scope_digest) is not None
        and scope.child_pid == os.getpid()
        and scope.activation_generation >= 1
        and scope.boot_generation >= 1
        and scope.watchdog_generation >= 1
        and scope.revocation_generation >= 0
        and scope.bootstrap_guard is not None
        and Path(scope.source_root).is_absolute()
        and Path(scope.installed_controller_root).is_absolute()
        and scope.runtime_install_capability is not None
    )
    if (not diagnostic and not installed) or scope.process_capability is None:
        raise ControllerStateRefused("controller-state authority issuer differs")
    if installed:
        validate_guard = getattr(
            scope.bootstrap_guard,
            "validateBootstrapEpoch",
            None,
        )
        if not callable(validate_guard):
            raise ControllerStateRefused("controller-state bootstrap guard is unavailable")
        try:
            validate_guard(
                outer_scope_digest=scope.outer_scope_digest,
                capsule_scope_digest=scope.capsule_scope_digest,
                controller_generation=scope.controller_generation,
                watchdog_generation=scope.watchdog_generation,
                revocation_generation=scope.revocation_generation,
                child_pid=scope.child_pid,
                activation_generation=scope.activation_generation,
                boot_generation=scope.boot_generation,
            )
        except Exception as exc:
            raise ControllerStateRefused(
                "controller-state bootstrap authority is no longer live"
            ) from exc
    if _time(scope.expires_at) <= datetime.now(timezone.utc):
        raise ControllerStateRefused("controller-state authority expired")
    if root is not None and scope.root != str(_root(root)):
        raise ControllerStateRefused("controller-state authority root differs")
    if repository_id is not None and scope.repository_id != repository_id:
        raise ControllerStateRefused("controller-state repository differs")
    if (
        controller_generation is not None
        and scope.controller_generation != controller_generation
    ):
        raise ControllerStateRefused("controller-state generation differs")
    assert isinstance(authority, ControllerStateAuthority)
    return authority


def isDiagnosticControllerStateAuthority(authority: object) -> bool:
    """Return diagnostic provenance only after exact authority validation."""

    validateControllerStateAuthority(authority)
    scope = _controllerAuthorityScope(authority)
    return scope.provenance == "diagnostic" and scope.seal is _DIAGNOSTIC_SEAL


def isInstalledControllerStateAuthority(authority: object) -> bool:
    """Return installed provenance only after exact authority validation."""

    validateControllerStateAuthority(authority)
    scope = _controllerAuthorityScope(authority)
    return scope.provenance == "installed" and scope.seal is _INSTALLED_SEAL


def _validateControllerRuntimePathInstallation(
    authority: object,
    *,
    source_root: str | Path,
    installed_root: str | Path,
    runtime_install_capability: object,
) -> tuple[str, str]:
    """Validate the private bundle-owned path publication capability."""

    validated = validateControllerStateAuthority(authority)
    scope = _controllerAuthorityScope(validated)
    if (
        scope.provenance != "installed"
        or scope.seal is not _INSTALLED_SEAL
        or runtime_install_capability is not scope.runtime_install_capability
    ):
        raise ControllerStateRefused(
            "installed controller paths require the runtime composition permit"
        )
    source = str(_root(source_root))
    installed = str(_root(installed_root))
    if source != scope.source_root or installed != scope.installed_controller_root:
        raise ControllerStateRefused(
            "runtime controller paths differ from installed bootstrap scope"
        )
    return source, installed


def validateControllerStateProcessCapability(
    authority: object,
    process_capability: object,
) -> None:
    """Compare a caller-held capability without exposing the issued object."""

    validateControllerStateAuthority(authority)
    if process_capability is not _controllerAuthorityScope(authority).process_capability:
        raise ControllerStateRefused("controller-state process capability differs")


@dataclass(slots=True)
class _ControllerStateOperationOutcome:
    """Poison facts exported only after every inner authority lock unwinds."""

    poison_cause: ControllerStateRefused | None = None
    result_committed: bool = False


class ControllerStateStore:
    """Retained-handle JSON store rooted at one exact external authority."""

    def __init__(
        self,
        *,
        root: str | Path,
        authority: object,
        _runtime_install_capability: object | None = None,
        _bootstrap_authorities: object | None = None,
    ) -> None:
        from platform_core.app_config.paths import controllerPathsActivationFence

        initial_scope = _controllerAuthorityScope(authority)
        diagnostic = _isDiagnosticScope(initial_scope)
        if diagnostic:
            if (
                _runtime_install_capability is not None
                or _bootstrap_authorities is not None
            ):
                raise ControllerStateRefused(
                    "diagnostic store cannot consume runtime composition authority"
                )
        elif (
            initial_scope.provenance != "installed"
            or initial_scope.seal is not _INSTALLED_SEAL
            or _runtime_install_capability
            is not initial_scope.runtime_install_capability
            or _bootstrap_authorities is None
        ):
            raise ControllerStateRefused(
                "installed store requires the exact runtime composition bundle"
            )

        runtime_permit = (
            controllerRuntimeStateAbsentPermit()
            if diagnostic
            else nullcontext()
        )
        # Diagnostic construction retains runtime -> path through its final
        # filesystem effect. Installed construction instead requires the exact
        # private capability already held by the central runtime transaction.
        with runtime_permit:
            with controllerPathsActivationFence() as paths_active:
                bootstrap_permit: AbstractContextManager[Any]
                if diagnostic:
                    bootstrap_permit = nullcontext(None)
                else:
                    bootstrap_permit = _heldInstalledBootstrapAuthorities(
                        _bootstrap_authorities
                    )
                with bootstrap_permit as projection:
                    validated = validateControllerStateAuthority(authority)
                    scope = _controllerAuthorityScope(validated)
                    if projection is not None and (
                        projection.controller_state_authority is not validated
                        or projection.bundle is not _bootstrap_authorities
                    ):
                        raise ControllerStateRefused(
                            "installed store bootstrap projection differs"
                        )
                    self._initialize(
                        root=root,
                        validated=validated,
                        scope=scope,
                        paths_active=paths_active,
                        bootstrap_authorities=_bootstrap_authorities,
                    )

    def _initialize(
        self,
        *,
        root: str | Path,
        validated: ControllerStateAuthority,
        scope: _ControllerStateAuthorityScope,
        paths_active: bool,
        bootstrap_authorities: object | None,
    ) -> None:
        if _isDiagnosticScope(scope) and (
            paths_active or _controller_paths_active()
        ):
            raise ControllerStateRefused(
                "diagnostic controller-state store is unavailable after activation"
            )
        expected = _root(root)
        if scope.root != str(expected):
            raise ControllerStateRefused("controller-state authority root or issuer differs")
        expires_at = _time(scope.expires_at)

        def require_live() -> None:
            if expires_at <= datetime.now(timezone.utc):
                raise ControllerStateRefused("controller-state authority expired")
            if scope.bootstrap_guard is not None:
                validate_guard = getattr(
                    scope.bootstrap_guard,
                    "validateBootstrapEpoch",
                    None,
                )
                if not callable(validate_guard):
                    raise ControllerStateRefused(
                        "controller-state bootstrap guard is unavailable"
                    )
                try:
                    validate_guard(
                        outer_scope_digest=scope.outer_scope_digest,
                        capsule_scope_digest=scope.capsule_scope_digest,
                        controller_generation=scope.controller_generation,
                        watchdog_generation=scope.watchdog_generation,
                        revocation_generation=scope.revocation_generation,
                        child_pid=scope.child_pid,
                        activation_generation=scope.activation_generation,
                        boot_generation=scope.boot_generation,
                    )
                except Exception as exc:
                    raise ControllerStateRefused(
                        "controller-state bootstrap authority is no longer live"
                    ) from exc

        require_live()
        if scope.process_capability is None:
            raise ControllerStateRefused("controller-state process capability is absent")
        descriptor: int | None = None
        try:
            assertNoReparsePath(expected.parent)
            require_live()
            expected.mkdir(exist_ok=True)
            assertNoReparsePath(expected)
            if expected.is_symlink() or not expected.is_dir():
                raise ControllerStateRefused("controller-state root identity is unsafe")
            if os.name != "nt":
                expected.chmod(0o700)
            self._handle = openNativeDirectory(expected)
            entries = {entry.name: entry for entry in self._handle.listEntries()}
            lock_entry = entries.get(_LOCK_NAME)
            if lock_entry is None:
                try:
                    require_live()
                    self._handle.createFile(_LOCK_NAME, b"\0")
                except FileExistsError:
                    # Another diagnostic/controller process may initialize the
                    # same attested root concurrently. Reobserve the exact child.
                    entries = {
                        entry.name: entry for entry in self._handle.listEntries()
                    }
                    lock_entry = entries.get(_LOCK_NAME)
                    if lock_entry is None:
                        raise
                    lock_identity = lock_entry.identity
                    if (
                        lock_identity.is_reparse
                        or lock_identity.is_directory
                        or lock_identity.link_count != 1
                        or lock_identity.size != 1
                    ):
                        raise ControllerStateRefused(
                            "controller-state lock identity is unsafe"
                        )
            else:
                lock_identity = lock_entry.identity
                if (
                    lock_identity.is_reparse
                    or lock_identity.is_directory
                    or lock_identity.link_count != 1
                    or lock_identity.size != 1
                ):
                    raise ControllerStateRefused("controller-state lock identity is unsafe")
            lock_path = expected / _LOCK_NAME
            assertNoReparsePath(lock_path)
            flags = os.O_RDWR
            if hasattr(os, "O_BINARY"):
                flags |= os.O_BINARY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            require_live()
            descriptor = os.open(lock_path, flags)
            observed = os.fstat(descriptor)
            visible = os.lstat(lock_path)
            if (
                not stat.S_ISREG(observed.st_mode)
                or observed.st_nlink != 1
                or observed.st_size != 1
                or (observed.st_dev, observed.st_ino)
                != (visible.st_dev, visible.st_ino)
            ):
                os.close(descriptor)
                descriptor = None
                raise ControllerStateRefused("controller-state lock identity raced")
            # The lock is synchronization metadata, not state.  Retaining this exact
            # descriptor makes cross-process updates serialize even if the root's
            # path name is later rebound; authoritative data still traverses only
            # through ``NativeDirectoryHandle`` below.
            self._lock_stream = os.fdopen(descriptor, "r+b", buffering=0)
            descriptor = None
            self._thread_lock = threading.RLock()
            self._operation_owner_thread_id: int | None = None
            self._operation_violation = False
            self._operation_pending_poison: ControllerStateRefused | None = None
            self._operation_result_committed = False
            self._closed = False
            require_live()
            self._root = expected
            self._authority = validated
            self._bootstrap_authorities = bootstrap_authorities
        except BaseException as exc:
            cleanup_errors: list[BaseException] = []
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except BaseException as cleanup_error:
                    cleanup_errors.append(cleanup_error)
            stream = getattr(self, "_lock_stream", None)
            if stream is not None:
                try:
                    stream.close()
                except BaseException as cleanup_error:
                    cleanup_errors.append(cleanup_error)
            handle = getattr(self, "_handle", None)
            if handle is not None:
                try:
                    handle.close()
                except BaseException as cleanup_error:
                    cleanup_errors.append(cleanup_error)
            if cleanup_errors:
                raise _ControllerStateStoreConstructionCleanupError(
                    tuple(cleanup_errors)
                ) from exc
            if isinstance(exc, ControllerStateRefused):
                raise
            if isinstance(exc, OSError):
                raise ControllerStateRefused(
                    "controller-state root cannot be retained safely"
                ) from exc
            raise

    def close(self) -> None:
        from platform_core.app_config.paths import controllerPathsActivationFence

        with controllerPathsActivationFence():
            with self._thread_lock:
                if self._operation_owner_thread_id == threading.get_ident():
                    self._operation_violation = True
                    raise ControllerStateRefused(
                        "controller-state close is unavailable during an operation"
                    )
                if self._closed:
                    return
                self._closed = True
                errors = self._closeResourcesUnlocked()
                if errors:
                    raise ControllerStateRefused(
                        "controller-state store resources could not be closed safely"
                    ) from errors[0]

    def _closeResourcesUnlocked(self) -> list[BaseException]:
        """Close both retained resources after the caller marks the store closed."""

        errors: list[BaseException] = []
        try:
            self._lock_stream.close()
        except BaseException as exc:
            errors.append(exc)
        try:
            self._handle.close()
        except BaseException as exc:
            errors.append(exc)
        return errors

    def __enter__(self) -> "ControllerStateStore":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def _validateAuthority(self, authority: object) -> ControllerStateAuthority:
        if authority is not self._authority or type(authority) is not ControllerStateAuthority:
            raise ControllerStateRefused("controller-state authority identity differs")
        return validateControllerStateAuthority(authority)

    def _validateInstallableAuthority(
        self,
        authority: object,
    ) -> ControllerStateAuthority:
        """Require one open store before any process-local consumer binds it."""

        # Authority validation acquires the watchdog registry.  Store operations
        # acquire that registry before ``_thread_lock``, so retaining the store
        # lock here would create the inverse store -> watchdog order.
        validated = self._validateAuthority(authority)
        with self._thread_lock:
            if self._closed:
                raise ControllerStateRefused("controller-state store is closed")
        return validated

    @contextmanager
    def _authorizedOperation(self, authority: object):
        """Hold the activation fence through one exact store transaction."""

        from platform_core.app_config.paths import controllerPathsActivationFence

        if authority is not self._authority or type(authority) is not ControllerStateAuthority:
            raise ControllerStateRefused(
                "controller-state authority identity differs"
            )
        bootstrap_authorities = self._bootstrap_authorities
        runtime_permit = (
            controllerRuntimeStateAbsentPermit()
            if bootstrap_authorities is None
            else nullcontext()
        )
        outcome = _ControllerStateOperationOutcome()
        try:
            with runtime_permit:
                with controllerPathsActivationFence() as paths_active:
                    bootstrap_permit: AbstractContextManager[Any]
                    if bootstrap_authorities is None:
                        bootstrap_permit = nullcontext(None)
                    else:
                        bootstrap_permit = _heldInstalledBootstrapAuthorities(
                            bootstrap_authorities
                        )
                    with bootstrap_permit as projection:
                        validated = self._validateAuthority(authority)
                        if projection is not None and (
                            projection.controller_state_authority is not validated
                            or projection.bundle is not bootstrap_authorities
                        ):
                            raise ControllerStateRefused(
                                "installed store bootstrap projection differs"
                            )
                        if isDiagnosticControllerStateAuthority(validated) and (
                            paths_active or _controller_paths_active()
                        ):
                            raise ControllerStateRefused(
                                "diagnostic controller-state operation is unavailable after activation"
                            )
                        scope = _controllerAuthorityScope(validated)
                        expires_at = _time(scope.expires_at)

                        def require_live() -> None:
                            if datetime.now(timezone.utc) >= expires_at:
                                raise ControllerStateRefused(
                                    "controller-state authority expired"
                                )
                            if projection is not None:
                                projection.require_live()
                            if (
                                self._operation_owner_thread_id == threading.get_ident()
                                and self._operation_violation
                            ):
                                raise ControllerStateRefused(
                                    "nested controller-state operation invalidated its outer operation"
                                )

                        with self._exclusive(
                            require_live=require_live,
                            outcome=outcome,
                        ):
                            yield require_live
        finally:
            # Global poison takes the runtime lock.  It must happen only after
            # path, bundle, watchdog, landing, and store/process locks unwind.
            if bootstrap_authorities is not None and outcome.poison_cause is not None:
                _poisonLiveRuntimeStore(
                    bootstrap_authorities=bootstrap_authorities,
                    store=self,
                    primary=outcome.poison_cause,
                )

    @contextmanager
    def _exclusive(
        self,
        *,
        require_live: Callable[[], None],
        outcome: _ControllerStateOperationOutcome,
    ):
        """Serialize a complete retained-handle read/modify/publish transaction."""

        with self._thread_lock:
            owner_thread_id = threading.get_ident()
            if self._operation_owner_thread_id == owner_thread_id:
                self._operation_violation = True
                raise ControllerStateRefused(
                    "nested controller-state operation is unavailable"
                )
            if self._closed:
                raise ControllerStateRefused("controller-state store is closed")
            self._operation_owner_thread_id = owner_thread_id
            self._operation_violation = False
            self._operation_pending_poison = None
            self._operation_result_committed = False
            deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
            locked = False
            unlock_error: BaseException | None = None
            try:
                require_live()
                self._lock_stream.seek(0)
                while True:
                    require_live()
                    try:
                        if os.name == "nt":
                            import msvcrt

                            msvcrt.locking(self._lock_stream.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            import fcntl

                            fcntl.flock(  # type: ignore[attr-defined]
                                self._lock_stream.fileno(),
                                fcntl.LOCK_EX  # type: ignore[attr-defined]
                                | fcntl.LOCK_NB,  # type: ignore[attr-defined]
                            )
                        locked = True
                        require_live()
                        break
                    except OSError as exc:
                        if exc.errno not in {
                            errno.EACCES,
                            errno.EAGAIN,
                            errno.EDEADLK,
                        }:
                            raise ControllerStateRefused(
                                "controller-state process lock failed"
                            ) from exc
                        require_live()
                        if time.monotonic() >= deadline:
                            raise ControllerStateRefused(
                                "controller-state process lock timed out"
                            ) from exc
                        time.sleep(0.01)
                yield
            finally:
                if locked:
                    try:
                        self._lock_stream.seek(0)
                        if os.name == "nt":
                            import msvcrt

                            msvcrt.locking(
                                self._lock_stream.fileno(), msvcrt.LK_UNLCK, 1
                            )
                        else:
                            import fcntl

                            fcntl.flock(  # type: ignore[attr-defined]
                                self._lock_stream.fileno(),
                                fcntl.LOCK_UN,  # type: ignore[attr-defined]
                            )
                    except BaseException as exc:
                        unlock_error = exc
                pending_poison = self._operation_pending_poison
                result_committed = self._operation_result_committed
                self._operation_owner_thread_id = None
                self._operation_violation = False
                self._operation_pending_poison = None
                self._operation_result_committed = False
                if unlock_error is not None:
                    unlock_poison = ControllerStateRefused(
                        "controller-state process lock release failed"
                    )
                    outcome.poison_cause = unlock_poison
                    self._closed = True
                    self._closeResourcesUnlocked()
                    raise ControllerStateRefused(
                        "controller-state process lock release failed; store poisoned"
                    ) from unlock_error
                if pending_poison is not None:
                    # A child-handle close failure poisons future traversal, but the
                    # retained process lock must be released before root resources
                    # close.  A completed terminal publication remains successful;
                    # a non-terminal prefix (for example only the backup) does not.
                    outcome.poison_cause = pending_poison
                    outcome.result_committed = result_committed
                    self._closed = True
                    self._closeResourcesUnlocked()
                    if not result_committed:
                        raise ControllerStateRefused(
                            "controller-state operation became ambiguous; store poisoned"
                        ) from pending_poison

    def _recordOperationPoison(
        self,
        primary: BaseException,
        *,
        message: str,
        result_committed: bool,
    ) -> None:
        poison = ControllerStateRefused(message)
        poison.__cause__ = primary
        if self._operation_pending_poison is None:
            self._operation_pending_poison = poison
        self._operation_result_committed = (
            self._operation_result_committed or result_committed
        )

    def _directory(self, parts: tuple[str, ...], *, create: bool) -> tuple[NativeDirectoryHandle, list[NativeDirectoryHandle]]:
        current = self._handle
        opened: list[NativeDirectoryHandle] = []
        try:
            for part in parts:
                entries = {entry.name: entry for entry in current.listEntries()}
                entry = entries.get(part)
                if entry is None:
                    if not create:
                        raise FileNotFoundError(part)
                    child = current.createDirectory(part)
                else:
                    if (
                        entry.identity.is_reparse
                        or not entry.identity.is_directory
                        or (os.name == "nt" and entry.identity.link_count != 1)
                    ):
                        raise ControllerStateRefused(
                            "controller-state directory identity is unsafe"
                        )
                    child = current.openDirectory(part, expected=entry.identity)
                opened.append(child)
                current = child
            return current, opened
        except BaseException:
            self._closeOpenedAfterPublication(opened, result_committed=False)
            raise

    @staticmethod
    def _closeOpened(opened: list[NativeDirectoryHandle]) -> None:
        first_error: BaseException | None = None
        for handle in reversed(opened):
            try:
                handle.close()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise ControllerStateRefused(
                "controller-state child handles could not be closed safely"
            ) from first_error

    def _closeOpenedAfterPublication(
        self,
        opened: list[NativeDirectoryHandle],
        *,
        result_committed: bool,
    ) -> None:
        """Defer poisoning until after the retained process lock is released."""

        try:
            self._closeOpened(opened)
        except ControllerStateRefused as exc:
            self._recordOperationPoison(
                exc,
                message="controller-state child cleanup outcome is ambiguous",
                result_committed=result_committed,
            )
            if not result_committed:
                raise

    def _commitBytes(
        self,
        logical_id: str,
        payload: bytes,
        *,
        require_live: Callable[[], None],
        result_commit: bool = True,
    ) -> None:
        parts = _logical(logical_id)
        require_live()
        directory, opened = self._directory(parts[:-1], create=True)
        name = f"{parts[-1]}.json"
        temporary = f".{parts[-1]}.{os.urandom(12).hex()}.tmp"
        publication_committed = False
        try:
            require_live()
            entries = {entry.name: entry for entry in directory.listEntries()}
            destination = entries.get(name)
            require_live()
            if destination is None:
                try:
                    directory.reconcileCreateOnlyFile(name, payload)
                except BaseException as exc:
                    self._recordOperationPoison(
                        exc,
                        message=(
                            "controller-state native create-only outcome is ambiguous"
                        ),
                        result_committed=False,
                    )
                    raise
                publication_committed = True
            else:
                if (
                    destination.identity.is_reparse
                    or destination.identity.is_directory
                    or destination.identity.link_count != 1
                ):
                    raise ControllerStateRefused("controller-state destination identity is unsafe")
                created = directory.createFile(temporary, payload)
                require_live()
                try:
                    directory.replaceFile(
                        temporary,
                        name,
                        expected_source=created,
                        expected_destination=destination.identity,
                    )
                except BaseException as exc:
                    self._recordOperationPoison(
                        exc,
                        message="controller-state native replace outcome is ambiguous",
                        result_committed=False,
                    )
                    raise
                publication_committed = True
        except BaseException:
            try:
                entries = {entry.name: entry for entry in directory.listEntries()}
                partial = entries.get(temporary)
                if partial is not None:
                    try:
                        directory.removeFile(temporary, expected=partial.identity)
                    except BaseException as exc:
                        self._recordOperationPoison(
                            exc,
                            message="controller-state temporary cleanup outcome is ambiguous",
                            result_committed=False,
                        )
            except BaseException as exc:
                self._recordOperationPoison(
                    exc,
                    message="controller-state failed-commit cleanup is ambiguous",
                    result_committed=False,
                )
            raise
        finally:
            if publication_committed:
                self._closeOpenedAfterPublication(
                    opened,
                    result_committed=result_commit,
                )
            else:
                self._closeOpenedAfterPublication(
                    opened,
                    result_committed=False,
                )

    def _readJsonUnlocked(self, logical_id: str) -> object:
        parts = _logical(logical_id)
        directory, opened = self._directory(parts[:-1], create=False)
        try:
            raw = directory.readFile(f"{parts[-1]}.json", max_bytes=_MAX_JSON)
        finally:
            self._closeOpenedAfterPublication(opened, result_committed=False)
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ControllerStateRefused("controller-state JSON is corrupt") from exc
        if _canonical(value) != raw:
            raise ControllerStateRefused("controller-state JSON is not canonical")
        return value

    def writeJson(self, logical_id: str, value: object, *, authority: object) -> None:
        with self._authorizedOperation(authority) as require_live:
            payload = _canonical(value)
            require_live()
            self._commitBytes(logical_id, payload, require_live=require_live)

    def readJson(self, logical_id: str, *, authority: object) -> object:
        with self._authorizedOperation(authority) as require_live:
            result = self._readJsonUnlocked(logical_id)
            require_live()
            return result

    def listJsonIds(
        self,
        logical_prefix: str,
        *,
        authority: object,
    ) -> tuple[str, ...]:
        """List direct JSON children below one retained logical directory.

        The result contains logical IDs, never host paths.  Temporary publication
        files and subdirectories are not documents; a JSON-shaped child with an
        unsafe identity or name is tampering and fails the entire observation.
        """

        with self._authorizedOperation(authority) as require_live:
            parts = _logical(logical_prefix)
            try:
                directory, opened = self._directory(parts, create=False)
            except FileNotFoundError:
                require_live()
                return ()
            try:
                result: list[str] = []
                for entry in directory.listEntries():
                    if not entry.name.endswith(".json"):
                        continue
                    stem = entry.name.removesuffix(".json")
                    if not _PART.fullmatch(stem):
                        raise ControllerStateRefused(
                            "controller-state JSON child name is unsafe"
                        )
                    if (
                        entry.identity.is_reparse
                        or entry.identity.is_directory
                        or entry.identity.link_count != 1
                    ):
                        raise ControllerStateRefused(
                            "controller-state JSON child identity is unsafe"
                        )
                    result.append("/".join((*parts, stem)))
                observed = tuple(result)
                require_live()
                return observed
            finally:
                self._closeOpenedAfterPublication(
                    opened,
                    result_committed=False,
                )

    def replaceJsonWithBackup(
        self,
        logical_id: str,
        backup_logical_id: str,
        value: object,
        *,
        authority: object,
    ) -> None:
        """Publish JSON after durably retaining the prior valid document.

        Both publications occur under one cross-process exclusive transaction.
        A crash after the backup commit but before replacement leaves the old
        primary intact; a corrupt primary is never silently overwritten.
        """

        with self._authorizedOperation(authority) as require_live:
            if _logical(logical_id) == _logical(backup_logical_id):
                raise ControllerStateRefused("controller-state backup aliases primary")
            payload = _canonical(value)
            missing = object()
            try:
                previous = self._readJsonUnlocked(logical_id)
            except FileNotFoundError:
                previous = missing
            if previous is not missing:
                require_live()
                self._commitBytes(
                    backup_logical_id,
                    _canonical(previous),
                    require_live=require_live,
                    result_commit=False,
                )
            require_live()
            self._commitBytes(
                logical_id,
                payload,
                require_live=require_live,
            )

    def updateJson(
        self,
        logical_id: str,
        *,
        default: object,
        mutate: Callable[[object], _T],
        authority: object,
    ) -> _T:
        """Atomically read, transform, and publish one logical JSON document.

        ``mutate`` receives a deep copy, so a failed canonicalization or publication
        cannot leak an unpersisted mutation into the caller's retained object graph.
        """

        with self._authorizedOperation(authority) as require_live:
            try:
                current = self._readJsonUnlocked(logical_id)
            except FileNotFoundError:
                current = copy.deepcopy(default)
            candidate = mutate(copy.deepcopy(current))
            payload = _canonical(candidate)
            detached = json.loads(payload.decode("utf-8", errors="strict"))
            require_live()
            self._commitBytes(logical_id, payload, require_live=require_live)
            return cast(_T, detached)

    def deleteJson(self, logical_id: str, *, authority: object) -> bool:
        """Delete one exact logical document; missing is an idempotent no-op."""

        with self._authorizedOperation(authority) as require_live:
            parts = _logical(logical_id)
            deletion_committed = False
            try:
                directory, opened = self._directory(parts[:-1], create=False)
            except FileNotFoundError:
                require_live()
                return False
            try:
                name = f"{parts[-1]}.json"
                entries = {entry.name: entry for entry in directory.listEntries()}
                entry = entries.get(name)
                if entry is None:
                    require_live()
                    return False
                if (
                    entry.identity.is_reparse
                    or entry.identity.is_directory
                    or entry.identity.link_count != 1
                ):
                    raise ControllerStateRefused(
                        "controller-state deletion identity is unsafe"
                    )
                require_live()
                try:
                    directory.removeFile(name, expected=entry.identity)
                except BaseException as exc:
                    self._recordOperationPoison(
                        exc,
                        message="controller-state native deletion outcome is ambiguous",
                        result_committed=False,
                    )
                    raise
                deletion_committed = True
                return True
            finally:
                if deletion_committed:
                    self._closeOpenedAfterPublication(
                        opened,
                        result_committed=True,
                    )
                else:
                    self._closeOpenedAfterPublication(
                        opened,
                        result_committed=False,
                    )


@dataclass(frozen=True, slots=True)
class ControllerRuntimeStateBinding:
    """One process-local installation of every core controller-state consumer."""

    bootstrap_authorities: object
    store: ControllerStateStore
    authority: ControllerStateAuthority
    source_root: str
    installed_root: str


@dataclass(frozen=True, slots=True)
class _PendingControllerRuntimeStateInstallation:
    bootstrap_authorities: object
    owner_thread_id: int


@dataclass(frozen=True, slots=True)
class _PoisonedControllerRuntimeStateInstallation:
    bootstrap_id: str
    reason: str


_RUNTIME_BINDING_LOCK = threading.RLock()
_RUNTIME_FENCE_STATE = threading.local()
_RUNTIME_BINDING: ControllerRuntimeStateBinding | None = None
_RUNTIME_INSTALL_TERMINAL: (
    ControllerRuntimeStateBinding
    | _PendingControllerRuntimeStateInstallation
    | _PoisonedControllerRuntimeStateInstallation
    | None
) = None


def _runtimeInstallNoop(_stage: str) -> None:
    return None


_RUNTIME_INSTALL_FAILPOINT: Callable[[str], None] = _runtimeInstallNoop


def _runtimeFallbackDepth() -> int:
    depth = getattr(_RUNTIME_FENCE_STATE, "fallback_depth", 0)
    return depth if type(depth) is int and depth >= 0 else 0


def _requireControllerRuntimeTransitionAllowed() -> None:
    """Refuse same-thread composition from inside config/fallback callbacks."""

    if _runtimeFallbackDepth() > 0:
        raise ControllerStateRefused(
            "controller runtime transition is reentrant through a fallback fence"
        )


def controllerRuntimeStateExactlyAbsent() -> bool:
    """Return true only before any central runtime installation has begun.

    This intentionally consults no configuration or path state.  Consumers use
    it outside every path/local lock to distinguish a clean pre-install process
    from pending, live, poisoned, or internally inconsistent runtime terminals.
    """

    with _RUNTIME_BINDING_LOCK:
        return _RUNTIME_INSTALL_TERMINAL is None and _RUNTIME_BINDING is None


@contextmanager
def controllerRuntimeStateConfigFence() -> Iterator[bool]:
    """Hold runtime composition stable while configuration selects its source.

    ``True`` means the pristine pre-install state.  When false, configuration
    may use an already-published immutable controller projection, but it must
    reject every ambient fallback.
    """

    with _RUNTIME_BINDING_LOCK:
        depth = _runtimeFallbackDepth()
        _RUNTIME_FENCE_STATE.fallback_depth = depth + 1
        try:
            yield _RUNTIME_INSTALL_TERMINAL is None and _RUNTIME_BINDING is None
        finally:
            _RUNTIME_FENCE_STATE.fallback_depth = depth


@contextmanager
def controllerRuntimeStateAbsentPermit() -> Iterator[None]:
    """Hold the runtime lock while an inactive-path fallback performs one effect."""

    with _RUNTIME_BINDING_LOCK:
        if _RUNTIME_INSTALL_TERMINAL is not None or _RUNTIME_BINDING is not None:
            raise ControllerStateRefused(
                "controller runtime installation is not exactly absent"
            )
        depth = _runtimeFallbackDepth()
        _RUNTIME_FENCE_STATE.fallback_depth = depth + 1
        try:
            yield
        finally:
            _RUNTIME_FENCE_STATE.fallback_depth = depth


def _poisonRuntimeInstallation(
    *,
    bootstrap_authorities: object,
    store: ControllerStateStore | None,
    primary: BaseException,
) -> list[BaseException]:
    """Publish the fail-closed terminal before best-effort descendant cleanup."""

    bootstrap_id = getattr(bootstrap_authorities, "bootstrap_id", "")
    # Never let attacker-controlled exception metadata veto terminal poison.
    # Bootstrap accepts only a bounded diagnostic label; the original exception
    # remains attached as the raised cause for local troubleshooting.
    reason = "controller-runtime-installation-failure"
    global _RUNTIME_BINDING, _RUNTIME_INSTALL_TERMINAL
    _RUNTIME_BINDING = None
    _RUNTIME_INSTALL_TERMINAL = _PoisonedControllerRuntimeStateInstallation(
        bootstrap_id=bootstrap_id if isinstance(bootstrap_id, str) else "",
        reason=reason,
    )
    cleanup_errors: list[BaseException] = []
    try:
        from platform_core.runtime.bootstrap_authority import (
            _poisonInstalledBootstrapAuthorities,
        )

        _poisonInstalledBootstrapAuthorities(
            bootstrap_authorities,
            reason=reason,
        )
    except BaseException as exc:
        cleanup_errors.append(exc)
    if store is not None:
        try:
            store.close()
        except BaseException as exc:
            cleanup_errors.append(exc)
    return cleanup_errors


def _poisonLiveRuntimeStore(
    *,
    bootstrap_authorities: object,
    store: ControllerStateStore,
    primary: BaseException,
) -> None:
    """Permanently poison an installed store after inner lock scopes unwind."""

    with _RUNTIME_BINDING_LOCK:
        terminal = _RUNTIME_INSTALL_TERMINAL
        if isinstance(terminal, _PoisonedControllerRuntimeStateInstallation):
            return
        # A mismatch is itself fail-closed inconsistency.  The exact bundle and
        # store still identify which descendants must be retired.
        _poisonRuntimeInstallation(
            bootstrap_authorities=bootstrap_authorities,
            store=store,
            primary=primary,
        )


@contextmanager
def _controllerRuntimeConsumerPermit(
    *,
    expected_bundle: object | None = None,
) -> Iterator[ControllerRuntimeStateBinding]:
    """Retain the complete installed epoch through one descendant effect."""

    from platform_core.app_config.paths import controllerPathsActivationFence

    with _RUNTIME_BINDING_LOCK:
        terminal = _RUNTIME_INSTALL_TERMINAL
        if isinstance(terminal, _PoisonedControllerRuntimeStateInstallation):
            raise ControllerStateRefused(
                "controller runtime installation is permanently poisoned"
            )
        if (
            not isinstance(terminal, ControllerRuntimeStateBinding)
            or _RUNTIME_BINDING is not terminal
        ):
            raise ControllerStateRefused(
                "controller runtime state binding is unavailable"
            )
        if (
            expected_bundle is not None
            and terminal.bootstrap_authorities is not expected_bundle
        ):
            raise ControllerStateRefused(
                "controller runtime bootstrap identity differs"
            )
        with controllerPathsActivationFence() as paths_active:
            if not paths_active:
                raise ControllerStateRefused(
                    "controller runtime paths are not active"
                )
            with _heldInstalledBootstrapAuthorities(
                terminal.bootstrap_authorities
            ) as projection:
                if (
                    projection.bundle is not terminal.bootstrap_authorities
                    or projection.controller_state_authority is not terminal.authority
                    or projection.source_root != terminal.source_root
                    or projection.installed_controller_root != terminal.installed_root
                ):
                    raise ControllerStateRefused(
                        "controller runtime bootstrap projection differs"
                    )
                terminal.store._validateInstallableAuthority(terminal.authority)
                projection.require_live()
                yield terminal
                try:
                    if (
                        _RUNTIME_INSTALL_TERMINAL is not terminal
                        or _RUNTIME_BINDING is not terminal
                    ):
                        raise ControllerStateRefused(
                            "controller runtime changed during consumer effect"
                        )
                    projection.require_live()
                    terminal.store._validateInstallableAuthority(
                        terminal.authority
                    )
                except ControllerStateRefused:
                    raise
                except Exception as exc:
                    raise ControllerStateRefused(
                        "controller runtime became unavailable during consumer effect"
                    ) from exc


def currentControllerRuntimeStateBinding() -> ControllerRuntimeStateBinding:
    """Return the one exact live central binding used by all core consumers."""

    with _RUNTIME_BINDING_LOCK:
        terminal = _RUNTIME_INSTALL_TERMINAL
        if isinstance(terminal, _PoisonedControllerRuntimeStateInstallation):
            raise ControllerStateRefused(
                "controller runtime installation is permanently poisoned"
            )
        if not isinstance(terminal, ControllerRuntimeStateBinding):
            raise ControllerStateRefused(
                "controller runtime state binding is unavailable"
            )
        if _RUNTIME_BINDING is not terminal:
            raise ControllerStateRefused(
                "controller runtime state binding terminal is inconsistent"
            )
        try:
            from platform_core.runtime.bootstrap_authority import (
                validateInstalledBootstrapAuthorities,
            )

            validateInstalledBootstrapAuthorities(terminal.bootstrap_authorities)
            terminal.store._validateInstallableAuthority(terminal.authority)
        except Exception as exc:
            raise ControllerStateRefused(
                "controller runtime state binding is no longer live"
            ) from exc
        return terminal


def installControllerRuntimeState(
    *,
    bootstrap_authorities: object,
) -> ControllerRuntimeStateBinding:
    """Install one exact external store into all core mutable-state boundaries.

    This is the process-local composition seam for the verified boot capsule.
    It accepts only one exact opaque bundle, derives every root and authority
    from its issuer-owned record, and publishes one central consumer binding.
    Clean precommit failure closes retained resources and permits exact retry;
    any commit-start or ambiguous-cleanup failure permanently poisons the epoch.
    """

    _requireControllerRuntimeTransitionAllowed()

    from platform_core.runtime.bootstrap_authority import (
        _installedBootstrapRuntimePermit,
        validateInstalledBootstrapAuthorities,
    )

    try:
        validated_bundle = validateInstalledBootstrapAuthorities(
            bootstrap_authorities
        )
        authority = validated_bundle.controller_state_authority
        source = validated_bundle.source_root
        installed = validated_bundle.installed_controller_root
    except Exception as exc:
        raise ControllerStateRefused(
            "exact live installed bootstrap bundle is required"
        ) from exc
    authority_scope = _controllerAuthorityScope(authority)
    runtime_install_capability = authority_scope.runtime_install_capability
    if runtime_install_capability is None:
        raise ControllerStateRefused(
            "installed runtime path capability is unavailable"
        )

    global _RUNTIME_BINDING, _RUNTIME_INSTALL_TERMINAL
    with _RUNTIME_BINDING_LOCK:
        terminal = _RUNTIME_INSTALL_TERMINAL
        if isinstance(terminal, ControllerRuntimeStateBinding):
            if (
                terminal.bootstrap_authorities is validated_bundle
                and _RUNTIME_BINDING is terminal
            ):
                try:
                    live_bundle = validateInstalledBootstrapAuthorities(
                        terminal.bootstrap_authorities
                    )
                    if live_bundle is not validated_bundle:
                        raise ControllerStateRefused(
                            "controller runtime bootstrap identity changed"
                        )
                    terminal.store._validateInstallableAuthority(
                        terminal.authority
                    )
                except Exception as exc:
                    raise ControllerStateRefused(
                        "controller runtime state binding is no longer live"
                    ) from exc
                return terminal
            raise ControllerStateRefused(
                "controller runtime state is already installed with different facts"
            )
        if isinstance(terminal, _PoisonedControllerRuntimeStateInstallation):
            raise ControllerStateRefused(
                "controller runtime installation is permanently poisoned"
            )
        if isinstance(terminal, _PendingControllerRuntimeStateInstallation):
            raise ControllerStateRefused(
                "controller runtime installation is already pending"
            )

        pending = _PendingControllerRuntimeStateInstallation(
            bootstrap_authorities=validated_bundle,
            owner_thread_id=threading.get_ident(),
        )
        _RUNTIME_INSTALL_TERMINAL = pending
        store: ControllerStateStore | None = None
        reservation = None
        commit_started = False
        try:
            from platform_core.app_config.paths import (
                _ControllerPathsReservationCleanupError,
                _reserveRuntimeControllerPathsInstallation,
            )

            with _reserveRuntimeControllerPathsInstallation(
                authority=authority,
                source_root=source,
                installed_root=installed,
                runtime_install_capability=runtime_install_capability,
            ) as held_reservation:
                reservation = held_reservation
                with _installedBootstrapRuntimePermit(
                    validated_bundle
                ) as projection:
                    if (
                        projection.bundle is not validated_bundle
                        or projection.controller_state_authority is not authority
                        or projection.source_root != source
                        or projection.installed_controller_root != installed
                    ):
                        raise ControllerStateRefused(
                            "runtime-install bundle projection changed"
                        )
                    projection.require_live()
                    store = ControllerStateStore(
                        root=authority_scope.root,
                        authority=authority,
                        _runtime_install_capability=runtime_install_capability,
                        _bootstrap_authorities=validated_bundle,
                    )
                    binding = ControllerRuntimeStateBinding(
                        bootstrap_authorities=validated_bundle,
                        store=store,
                        authority=authority,
                        source_root=source,
                        installed_root=installed,
                    )
                    _RUNTIME_INSTALL_FAILPOINT("store_prepared")
                    projection.require_live()
                    _RUNTIME_INSTALL_FAILPOINT("before_paths_commit")
                    commit_started = True
                    held_reservation.commit()
                    _RUNTIME_INSTALL_FAILPOINT("paths_committed")
                    projection.require_live()
                    _RUNTIME_BINDING = binding
                    _RUNTIME_INSTALL_TERMINAL = binding
                    _RUNTIME_INSTALL_FAILPOINT("runtime_binding_published")
                    return binding
        except BaseException as primary:
            publication_started = commit_started or bool(
                reservation is not None and reservation.publicationStarted
            )
            reservation_cleanup_ambiguous = bool(
                reservation is not None and not reservation.cleanupComplete
            ) or isinstance(primary, _ControllerPathsReservationCleanupError)
            store_cleanup_ambiguous = isinstance(
                primary,
                _ControllerStateStoreConstructionCleanupError,
            )
            if (
                publication_started
                or reservation_cleanup_ambiguous
                or store_cleanup_ambiguous
            ):
                cleanup_errors = _poisonRuntimeInstallation(
                    bootstrap_authorities=validated_bundle,
                    store=store,
                    primary=primary,
                )
                if publication_started:
                    message = "controller runtime installation is permanently poisoned"
                elif store_cleanup_ambiguous:
                    message = "controller runtime store cleanup is ambiguous and poisoned"
                else:
                    message = (
                        "controller runtime reservation cleanup is ambiguous and poisoned"
                    )
                if cleanup_errors:
                    message += " after incomplete cleanup"
                raise ControllerStateRefused(message) from primary

            cleanup_error: BaseException | None = None
            if store is not None:
                try:
                    store.close()
                except BaseException as exc:
                    cleanup_error = exc
            if cleanup_error is not None:
                _poisonRuntimeInstallation(
                    bootstrap_authorities=validated_bundle,
                    store=store,
                    primary=cleanup_error,
                )
                raise ControllerStateRefused(
                    "controller runtime precommit rollback is ambiguous and poisoned"
                ) from primary
            if _RUNTIME_INSTALL_TERMINAL is pending:
                _RUNTIME_INSTALL_TERMINAL = None
            _RUNTIME_BINDING = None
            raise


@dataclass(frozen=True, slots=True)
class StateWriterFinding:
    path: str
    line: int
    category: str
    expression: str


def _call_name(node: ast.Call) -> str:
    value = node.func
    parts: list[str] = []
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts))


def auditExternalStateWriters(
    paths: Iterable[Path],
    *,
    allowed_boundaries: Mapping[str, frozenset[str]],
) -> tuple[StateWriterFinding, ...]:
    """Statically enumerate ambient target-state and path-only native writers."""

    findings: list[StateWriterFinding] = []
    for source in sorted(Path(path) for path in paths):
        try:
            text = source.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(source))
        except (OSError, UnicodeError, SyntaxError):
            findings.append(StateWriterFinding(str(source), 0, "unparseable", ""))
            continue
        normalized = source.as_posix()
        allowed = allowed_boundaries.get(normalized, frozenset())
        for node in ast.walk(tree):
            category = ""
            expression = ""
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if node.value.id == "config" and node.attr in {
                    "STATE_DIR",
                    "LOG_DIR",
                    "VAULT_ROOT",
                    "TASKS_DIR",
                }:
                    category = "target_state_path"
                    expression = f"config.{node.attr}"
            if isinstance(node, ast.Call):
                name = _call_name(node)
                if name in {"sqlite3.connect", "chromadb.PersistentClient"}:
                    category = "path_only_native_engine"
                    expression = name
            if category and category not in allowed:
                findings.append(
                    StateWriterFinding(normalized, getattr(node, "lineno", 0), category, expression)
                )
    return tuple(sorted(findings, key=lambda item: (item.path, item.line, item.category)))


def task3StateWriterInventory(root: Path) -> tuple[Path, ...]:
    from tools.galaxy_plan_manifest import parse_plan, select_paths

    plan = root / "docs/superpowers/plans/2026-07-13-galaxy-r3-transactional-kernel.md"
    tasks = parse_plan(plan.read_text(encoding="utf-8"), through=3)
    return tuple(root / path for path in select_paths(tasks, (3,), "production-python"))


def reviewedTask3StateWriterAllowlist(root: Path) -> dict[str, frozenset[str]]:
    # These modules consume the capsule-installed ``PathsCfg`` projection.  They
    # receive no waiver for a path-only native engine: only the logical state
    # worker below may own one of those.
    projected_path_consumers = {
        "human_nature/faculties/identity/continuity.py",
        "human_nature/faculties/runtime/psyche_store.py",
        "learning/evolution/curator.py",
        "learning/evolution/promote.py",
        "memory/stores/user_prefs.py",
        "notifications/runtime/reflection_post.py",
        "notifications/runtime/work_launcher.py",
        "platform_core/ops/retention.py",
        "platform_core/runtime/control_store.py",
        "platform_core/runtime/heartbeat.py",
        "platform_core/runtime/trajectory.py",
        "state/task_io.py",
        "state/task_schema.py",
    }
    result = {
        (root / "platform_core/runtime/controller_state.py").as_posix(): frozenset(
            {"path_only_native_engine", "target_state_path"}
        ),
        (root / "platform_core/runtime/state_store_worker.py").as_posix(): frozenset(
            {"path_only_native_engine"}
        ),
        (root / "containers/galaxy/state_store_entrypoint.py").as_posix(): frozenset(
            {"path_only_native_engine"}
        ),
    }
    result.update(
        {
            (root / path).as_posix(): frozenset({"target_state_path"})
            for path in projected_path_consumers
        }
    )
    return result


__all__ = [
    "ControllerStateAuthority",
    "ControllerStateRefused",
    "ControllerStateStore",
    "deriveInstalledControllerStateAuthority",
    "ControllerRuntimeStateBinding",
    "StateWriterFinding",
    "auditExternalStateWriters",
    "issueDiagnosticControllerStateAuthority",
    "isDiagnosticControllerStateAuthority",
    "isInstalledControllerStateAuthority",
    "installControllerRuntimeState",
    "currentControllerRuntimeStateBinding",
    "reviewedTask3StateWriterAllowlist",
    "task3StateWriterInventory",
    "validateControllerStateAuthority",
    "validateControllerStateProcessCapability",
]
