"""Host-side client for a networkless logical-ID state-store worker.

No request contains a path or SQL string.  The separately mounted worker owns one
non-authoritative engine subtree and exposes only a closed KV schema.

RUN/TEST: python -m pytest tests/execution/test_external_state_writers.py
"""

from __future__ import annotations

import json
import re
import secrets
import sqlite3
import threading
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, cast

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_OPERATIONS = frozenset({"kv_get", "kv_put", "kv_delete", "kv_list"})


class StateStoreWorkerRefused(RuntimeError):
    """The logical state-worker request or authority is invalid."""


class StateStoreWorkerUnavailableReason(str, Enum):
    """Closed reasons why the production worker cannot acquire authority."""

    BOOT_RESOURCE_LIFECYCLE_UNAVAILABLE = "boot_resource_lifecycle_unavailable"


class StateStoreWorkerUnavailable(StateStoreWorkerRefused):
    """Production worker authority is structurally unavailable, not degraded."""

    def __init__(self, reason: StateStoreWorkerUnavailableReason) -> None:
        if type(reason) is not StateStoreWorkerUnavailableReason:
            raise TypeError("state-worker unavailability reason must use the closed enum")
        self.reason = reason
        super().__init__(f"state-worker unavailable: {reason.value}")


@dataclass(frozen=True, slots=True)
class StateStoreWorkerBinding:
    client: "StateStoreWorkerClient"
    authority: "StateStoreWorkerAuthority"
    bootstrap_authorities: object
    controller_runtime_binding: object
    controller_generation: int
    watchdog_generation: int
    revocation_generation: int
    activation_generation: int
    boot_generation: int
    child_pid: int


def _time(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise StateStoreWorkerRefused("state-worker authority expiry is invalid") from exc
    if result.tzinfo is None:
        raise StateStoreWorkerRefused("state-worker authority expiry is not absolute")
    return result.astimezone(timezone.utc)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise StateStoreWorkerRefused("state-worker value is not canonicalizable") from exc


@dataclass(frozen=True, slots=True)
class StateStoreRequest:
    request_id: str
    operation: str
    database_id: str
    namespace: str
    key: str = ""
    value: object = None

    def __post_init__(self) -> None:
        for item, name in (
            (self.request_id, "request_id"),
            (self.database_id, "database_id"),
            (self.namespace, "namespace"),
        ):
            if not isinstance(item, str) or not _ID.fullmatch(item):
                raise StateStoreWorkerRefused(f"{name} is invalid")
        if self.operation not in _OPERATIONS:
            raise StateStoreWorkerRefused("state-worker operation is unknown")
        if self.operation in {"kv_get", "kv_put", "kv_delete"} and not _ID.fullmatch(self.key):
            raise StateStoreWorkerRefused("state-worker key is invalid")
        if len(_canonical(self.value)) > 4 * 1024 * 1024:
            raise StateStoreWorkerRefused("state-worker value exceeds its quota")

    def toDict(self) -> dict[str, object]:
        return {
            "database_id": self.database_id,
            "key": self.key,
            "namespace": self.namespace,
            "operation": self.operation,
            "request_id": self.request_id,
            "value": self.value,
        }


@dataclass(frozen=True, slots=True, eq=False)
class StateStoreWorkerAuthority:
    authority_id: str
    resource_id: str
    database_ids: frozenset[str]
    deadline: str
    _issuer_identity: int
    _seal: object
    _token: object


@dataclass(frozen=True, slots=True)
class _IssuedStateStoreWorkerAuthority:
    authority: StateStoreWorkerAuthority
    token: object
    resource_id: str
    database_ids: frozenset[str]
    deadline: str


@dataclass(frozen=True, slots=True)
class StateStoreResponse:
    request_id: str
    resource_id: str
    result: object
    request_digest: str
    result_digest: str
    signature: str


class StateStoreWorkerClient:
    def __init__(
        self,
        *,
        resource_id: str,
        database_ids: frozenset[str],
        rpc: Callable[[Mapping[str, object]], object],
        process_capability: object,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if (
            type(resource_id) is not str
            or not _ID.fullmatch(resource_id)
            or type(database_ids) is not frozenset
            or not database_ids
            or any(
                type(value) is not str or not _ID.fullmatch(value)
                for value in database_ids
            )
        ):
            raise StateStoreWorkerRefused(
                "state-worker resource scope requires an exact immutable frozenset"
            )
        if process_capability is None:
            raise StateStoreWorkerRefused("state-worker process capability is required")
        self._resource_id = resource_id
        self._database_ids = database_ids
        self._rpc = rpc
        self._process_capability = process_capability
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._identity = id(self)
        self._seal = object()
        self._authority_lock = threading.RLock()
        self._authorities: dict[str, _IssuedStateStoreWorkerAuthority] = {}

    def issueAuthority(
        self,
        *,
        process_capability: object,
        deadline: str,
    ) -> StateStoreWorkerAuthority:
        if process_capability is not self._process_capability:
            raise StateStoreWorkerRefused("state-worker process capability differs")
        if _time(deadline) <= self._clock().astimezone(timezone.utc):
            raise StateStoreWorkerRefused("state-worker authority already expired")
        for _attempt in range(32):
            authority_id = f"authority_{secrets.token_hex(16)}"
            token = object()
            authority = StateStoreWorkerAuthority(
                authority_id=authority_id,
                resource_id=self._resource_id,
                database_ids=self._database_ids,
                deadline=deadline,
                _issuer_identity=self._identity,
                _seal=self._seal,
                _token=token,
            )
            record = _IssuedStateStoreWorkerAuthority(
                authority=authority,
                token=token,
                resource_id=self._resource_id,
                database_ids=self._database_ids,
                deadline=deadline,
            )
            with self._authority_lock:
                if authority_id in self._authorities:
                    continue
                self._authorities[authority_id] = record
                return authority
        raise StateStoreWorkerRefused("state-worker authority ID budget exhausted")

    def _validateAuthority(
        self,
        authority: object,
    ) -> _IssuedStateStoreWorkerAuthority:
        if type(authority) is not StateStoreWorkerAuthority:
            raise StateStoreWorkerRefused(
                "exact process-local state-worker authority is required"
            )
        assert isinstance(authority, StateStoreWorkerAuthority)
        with self._authority_lock:
            record = self._authorities.get(authority.authority_id)
            if (
                record is None
                or record.authority is not authority
                or record.token is not authority._token
                or authority._issuer_identity != self._identity
                or authority._seal is not self._seal
                or authority.resource_id != record.resource_id
                or authority.database_ids != record.database_ids
                or authority.deadline != record.deadline
            ):
                raise StateStoreWorkerRefused(
                    "state-worker authority issuer or scope differs"
                )
            if _time(record.deadline) <= self._clock().astimezone(timezone.utc):
                raise StateStoreWorkerRefused("state-worker authority expired")
            return record

    def execute(self, request: StateStoreRequest, *, authority: object) -> StateStoreResponse:
        """Refuse synthetic installed execution until boot-resource admission."""

        raise StateStoreWorkerUnavailable(
            StateStoreWorkerUnavailableReason.BOOT_RESOURCE_LIFECYCLE_UNAVAILABLE
        )


_INSTALLED_BINDING: StateStoreWorkerBinding | None = None
_BINDING_LOCK = threading.RLock()
_DIAGNOSTIC_FENCE_STATE = threading.local()


def _diagnosticFenceDepth() -> int:
    depth = getattr(_DIAGNOSTIC_FENCE_STATE, "depth", 0)
    return depth if type(depth) is int and depth >= 0 else 0


def _requireDiagnosticAccessLive() -> None:
    from platform_core.runtime.controller_state import (
        controllerRuntimeStateExactlyAbsent,
    )

    if not controllerRuntimeStateExactlyAbsent():
        raise StateStoreWorkerRefused(
            "legacy diagnostic state access requires an absent runtime"
        )
    if _controllerPathsActive() or _INSTALLED_BINDING is not None:
        raise StateStoreWorkerRefused(
            "legacy diagnostic state access is unavailable"
        )


@contextmanager
def legacyDiagnosticStateWorkerAccess() -> Iterator[None]:
    """Retain runtime -> path -> worker exclusion through one legacy effect.

    Callers enter this before resolving any caller-controlled or ambient path.
    The worker entrypoints enter it before request construction, closing both
    build-to-effect races and request-callback activation races without
    transferring a path into the logical RPC.
    """

    from platform_core.app_config.paths import controllerPathsActivationFence
    from platform_core.runtime.controller_state import (
        ControllerStateRefused,
        controllerRuntimeStateAbsentPermit,
    )

    try:
        with controllerRuntimeStateAbsentPermit():
            with controllerPathsActivationFence() as paths_active:
                with _BINDING_LOCK:
                    if paths_active:
                        raise StateStoreWorkerRefused(
                            "legacy diagnostic state access is unavailable"
                        )
                    _requireDiagnosticAccessLive()
                    depth = _diagnosticFenceDepth()
                    _DIAGNOSTIC_FENCE_STATE.depth = depth + 1
                    try:
                        yield
                    finally:
                        _DIAGNOSTIC_FENCE_STATE.depth = depth
    except ControllerStateRefused as exc:
        raise StateStoreWorkerRefused(
            "legacy diagnostic state access requires an absent runtime"
        ) from exc


def installStateStoreWorker(
    *,
    bootstrap_authorities: object,
    client: StateStoreWorkerClient,
    authority: StateStoreWorkerAuthority,
) -> StateStoreWorkerBinding:
    """Refuse until boot has durably registered and attested the real worker.

    A live controller bundle cannot turn an in-process callback into a
    separately contained state-store resource.  The future installed seam must
    consume an issuer-owned boot-resource transfer proving a journaled STARTED
    lease, exact OCI/mount/security facts, private bounded IPC, and recovery of
    every prior generation.  Until that producer exists, installed authority is
    deliberately structurally unavailable; diagnostic compatibility remains
    behind ``legacyDiagnosticStateWorkerAccess`` only.
    """

    raise StateStoreWorkerUnavailable(
        StateStoreWorkerUnavailableReason.BOOT_RESOURCE_LIFECYCLE_UNAVAILABLE
    )


def _controllerPathsActive() -> bool:
    try:
        from platform_core.app_config.paths import controllerPathsActive

        return bool(controllerPathsActive())
    except Exception:
        # An ambiguous capsule/configuration state is not permission to use a
        # host path.  The legacy diagnostic fallback is available only when the
        # ordinary brownfield configuration is positively inactive.
        return True


def executeStateOperation(
    *,
    database_id: str,
    namespace: str,
    operation: str,
    key: str = "",
    value: object = None,
    authority: object = None,
    legacy_path: str | Path | None = None,
) -> object:
    """Execute one closed logical operation through the installed worker.

    Before activation, an explicit legacy path may drive the same container
    entrypoint in-process for brownfield tests.  Capsule mode disables that
    compatibility path completely; callers must present the exact installed
    process-local authority and no request ever contains a path or SQL string.
    """

    with _BINDING_LOCK:
        binding = _INSTALLED_BINDING
    if binding is not None:
        raise StateStoreWorkerUnavailable(
            StateStoreWorkerUnavailableReason.BOOT_RESOURCE_LIFECYCLE_UNAVAILABLE
        )
    if legacy_path is None:
        raise StateStoreWorkerUnavailable(
            StateStoreWorkerUnavailableReason.BOOT_RESOURCE_LIFECYCLE_UNAVAILABLE
        )
    try:
        with legacyDiagnosticStateWorkerAccess():
            request = StateStoreRequest(
                request_id=f"request_{secrets.token_hex(16)}",
                operation=operation,
                database_id=database_id,
                namespace=namespace,
                key=key,
                value=value,
            )
            path = Path(legacy_path)
            _requireDiagnosticAccessLive()
            if not path.is_absolute():
                raise StateStoreWorkerRefused(
                    "legacy diagnostic state path must be absolute"
                )
            from containers.galaxy import state_store_entrypoint

            root = path.parent / f".{path.name}.state-worker"
            return state_store_entrypoint._handleAtDiagnosticRoot(
                root,
                request.toDict(),
            )
    except StateStoreWorkerRefused as exc:
        if "runtime" in str(exc) or "path must be absolute" in str(exc):
            raise
        raise StateStoreWorkerRefused("state-worker binding is unavailable") from exc


class _FencedDiagnosticSqliteConnection:
    """Connection proxy that owns the diagnostic permits until exact close."""

    __slots__ = ("__connection", "__permit", "__closed", "__owner_thread_id")

    def __init__(
        self,
        connection: Any,
        permit: AbstractContextManager[None],
    ) -> None:
        self.__connection = connection
        self.__permit = permit
        self.__closed = False
        self.__owner_thread_id = threading.get_ident()

    def __getattr__(self, name: str) -> Any:
        self._requireLive()
        raise AttributeError(f"diagnostic SQL connection method {name!r} is unavailable")

    def _requireLive(self) -> None:
        if self.__closed:
            raise sqlite3.ProgrammingError("Cannot operate on a closed database.")
        self._requireOwnerThread()
        _requireDiagnosticAccessLive()

    def _requireOwnerThread(self) -> None:
        if threading.get_ident() != self.__owner_thread_id:
            raise sqlite3.ProgrammingError(
                "diagnostic SQL connection must be used on its owner thread"
            )

    def _wrapResult(self, value: object) -> object:
        if isinstance(value, sqlite3.Cursor):
            return _FencedDiagnosticSqliteCursor(value, self)
        return value

    @property
    def row_factory(self) -> Any:
        self._requireLive()
        return self.__connection.row_factory

    @row_factory.setter
    def row_factory(self, value: Any) -> None:
        self._requireLive()
        if value is not None and value is not sqlite3.Row:
            raise TypeError("diagnostic SQL row factory must be sqlite3.Row or None")
        self.__connection.row_factory = value

    def execute(
        self,
        sql: str,
        parameters: Any = (),
    ) -> "_FencedDiagnosticSqliteCursor":
        self._requireLive()
        return cast(
            "_FencedDiagnosticSqliteCursor",
            self._wrapResult(self.__connection.execute(sql, parameters)),
        )

    def executemany(
        self,
        sql: str,
        parameters: Any,
    ) -> "_FencedDiagnosticSqliteCursor":
        self._requireLive()
        return cast(
            "_FencedDiagnosticSqliteCursor",
            self._wrapResult(self.__connection.executemany(sql, parameters)),
        )

    def cursor(self) -> "_FencedDiagnosticSqliteCursor":
        self._requireLive()
        return cast(
            "_FencedDiagnosticSqliteCursor",
            self._wrapResult(self.__connection.cursor()),
        )

    def commit(self) -> None:
        self._requireLive()
        self.__connection.commit()

    def rollback(self) -> None:
        self._requireLive()
        self.__connection.rollback()

    def __enter__(self) -> "_FencedDiagnosticSqliteConnection":
        self._requireLive()
        self.__connection.__enter__()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> object:
        try:
            self._requireLive()
        except StateStoreWorkerRefused:
            try:
                self.__connection.rollback()
            except sqlite3.Error:
                pass
            raise
        return self.__connection.__exit__(exc_type, exc, traceback)

    def close(self) -> None:
        if self.__closed:
            return
        self._requireOwnerThread()
        self.__connection.close()
        self.__closed = True
        self.__permit.__exit__(None, None, None)


class _FencedDiagnosticSqliteCursor:
    """Prevent a cursor retained from the connection from escaping its fence."""

    __slots__ = ("__cursor", "__owner")

    def __init__(
        self,
        cursor: sqlite3.Cursor,
        owner: _FencedDiagnosticSqliteConnection,
    ) -> None:
        self.__cursor = cursor
        self.__owner = owner

    @property
    def connection(self) -> _FencedDiagnosticSqliteConnection:
        self.__owner._requireLive()
        return self.__owner

    def __getattr__(self, name: str) -> Any:
        self.__owner._requireLive()
        raise AttributeError(f"diagnostic SQL cursor member {name!r} is unavailable")

    @property
    def lastrowid(self) -> object:
        self.__owner._requireLive()
        return self.__cursor.lastrowid

    @property
    def rowcount(self) -> int:
        self.__owner._requireLive()
        return int(self.__cursor.rowcount)

    @property
    def description(self) -> object:
        self.__owner._requireLive()
        return self.__cursor.description

    def execute(self, sql: str, parameters: Any = ()) -> "_FencedDiagnosticSqliteCursor":
        self.__owner._requireLive()
        self.__cursor.execute(sql, parameters)
        return self

    def executemany(
        self,
        sql: str,
        parameters: Any,
    ) -> "_FencedDiagnosticSqliteCursor":
        self.__owner._requireLive()
        self.__cursor.executemany(sql, parameters)
        return self

    def fetchone(self) -> object:
        self.__owner._requireLive()
        return self.__cursor.fetchone()

    def fetchmany(self, size: int | None = None) -> list[object]:
        self.__owner._requireLive()
        if size is None:
            return self.__cursor.fetchmany()
        return self.__cursor.fetchmany(size)

    def fetchall(self) -> list[object]:
        self.__owner._requireLive()
        return self.__cursor.fetchall()

    def __iter__(self) -> "_FencedDiagnosticSqliteCursor":
        self.__owner._requireLive()
        return self

    def __next__(self) -> object:
        self.__owner._requireLive()
        return next(self.__cursor)

    def close(self) -> None:
        self.__owner._requireOwnerThread()
        self.__cursor.close()


def _legacyDiagnosticSqliteConnectionFromResolver(
    resolve_path: Callable[[], str | Path],
) -> _FencedDiagnosticSqliteConnection:
    """Open one raw diagnostic connection under exactly one retained permit."""

    permit = legacyDiagnosticStateWorkerAccess()
    try:
        permit.__enter__()
    except StateStoreWorkerRefused as exc:
        if "runtime" in str(exc):
            raise
        raise StateStoreWorkerRefused("raw SQL compatibility is unavailable") from exc
    try:
        target = Path(resolve_path())
        _requireDiagnosticAccessLive()
        if not target.is_absolute():
            raise StateStoreWorkerRefused("diagnostic SQL path must be absolute")
        from containers.galaxy import state_store_entrypoint

        connection = state_store_entrypoint._openDiagnosticConnection(target)
    except BaseException:
        permit.__exit__(None, None, None)
        raise
    return _FencedDiagnosticSqliteConnection(connection, permit)


def legacyDiagnosticSqliteConnectionFromPath(
    resolve_path: Callable[[], str | Path],
) -> _FencedDiagnosticSqliteConnection:
    """Resolve a diagnostic path only after the sole retained permit is live."""

    if not callable(resolve_path):
        raise TypeError("diagnostic SQL path resolver must be callable")
    return _legacyDiagnosticSqliteConnectionFromResolver(resolve_path)


def legacyDiagnosticSqliteConnection(path: str | Path) -> Any:
    """Return a brownfield-only SQL connection; unavailable after capsule install.

    This is deliberately absent from the worker RPC.  It keeps existing schema
    migration tests executable under the global launch embargo while production
    callers are forced onto logical operations or typed unavailability.
    """

    return _legacyDiagnosticSqliteConnectionFromResolver(lambda: path)


__all__ = [
    "StateStoreWorkerBinding",
    "StateStoreRequest",
    "StateStoreResponse",
    "StateStoreWorkerAuthority",
    "StateStoreWorkerClient",
    "StateStoreWorkerRefused",
    "StateStoreWorkerUnavailable",
    "StateStoreWorkerUnavailableReason",
    "executeStateOperation",
    "installStateStoreWorker",
    "legacyDiagnosticStateWorkerAccess",
    "legacyDiagnosticSqliteConnection",
    "legacyDiagnosticSqliteConnectionFromPath",
]
