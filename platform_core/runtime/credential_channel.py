"""Typed, non-secret evidence for credential-channel destruction.

The serialized receipt is evidence only.  Runtime authority is supplied by the
sealed broker/verifier composition in :mod:`platform_core.execution.credential_broker`.

RUN/TEST: python -m pytest tests/execution/test_credential_broker.py
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, cast

from platform_core.core.fsio import (
    NativeFileIdentity,
    assertNoReparsePath,
    exclusiveCreateBytes,
    openNativeDirectory,
    readNoFollowBytes,
)

_SCHEMA = "galaxy.credential-channel-destruction/v1"
_INTENT_SCHEMA = "galaxy.credential-channel-destruction-intent/v1"
_MAX_RECEIPT_BYTES = 16 * 1024
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_CHANNEL_BYTES_MAX = 65_536
_FACTORY_TOKEN = object()


class CredentialChannelEvidenceRefused(RuntimeError):
    """Credential-channel evidence is malformed, forged, or ambiguously encoded."""


@dataclass(frozen=True, slots=True)
class _IssuedChannelLifecycleObject:
    value: object
    broker: object
    seal: object
    kind: str


_ISSUED_CHANNEL_OBJECTS_LOCK = threading.RLock()
_ISSUED_CHANNEL_OBJECTS: dict[int, _IssuedChannelLifecycleObject] = {}


def _register_channel_object(
    value: object,
    *,
    broker: object,
    seal: object,
    kind: str,
) -> None:
    with _ISSUED_CHANNEL_OBJECTS_LOCK:
        _ISSUED_CHANNEL_OBJECTS[id(value)] = _IssuedChannelLifecycleObject(
            value=value,
            broker=broker,
            seal=seal,
            kind=kind,
        )


def _require_channel_object(value: object, *, kind: str) -> None:
    try:
        broker = getattr(value, "_broker")
        seal = getattr(value, "_seal")
        identity = getattr(value, "_identity")
    except AttributeError as exc:
        raise CredentialChannelEvidenceRefused(
            f"credential {kind} process-local binding is incomplete"
        ) from exc
    with _ISSUED_CHANNEL_OBJECTS_LOCK:
        issued = _ISSUED_CHANNEL_OBJECTS.get(id(value))
    if (
        issued is None
        or issued.value is not value
        or issued.broker is not broker
        or issued.seal is not seal
        or issued.kind != kind
        or identity != id(value)
    ):
        raise CredentialChannelEvidenceRefused(
            f"credential {kind} is copied, reflected, or not broker-issued"
        )


def _exact_broker(value: object) -> Any:
    """Return only a live process-local broker issued by the broker module.

    Credential evidence deliberately calls broker lifecycle methods through the
    exact class, not through stored callables.  That keeps mutation authority in
    one broker object and prevents a factory caller from substituting no-op or
    re-entrant commit callbacks.
    """

    from platform_core.execution.credential_broker import (
        CredentialBroker,
        CredentialBrokerRefused,
    )

    if type(value) is not CredentialBroker:
        raise CredentialChannelEvidenceRefused(
            "credential channel lifecycle requires the exact live broker"
        )
    try:
        CredentialBroker._requireChannelLifecycleBroker(value)
    except (CredentialBrokerRefused, AttributeError, TypeError, ValueError) as exc:
        raise CredentialChannelEvidenceRefused(
            "credential channel lifecycle broker binding differs"
        ) from exc
    return value


def _canonical_now(clock: Callable[[], datetime]) -> str:
    observed = clock()
    if not isinstance(observed, datetime) or observed.tzinfo is None:
        raise CredentialChannelEvidenceRefused(
            "credential channel clock must be timezone-aware"
        )
    return observed.astimezone(timezone.utc).isoformat()


def _channel_name(secret_channel_id: str) -> str:
    _require_id(secret_channel_id, "secret_channel_id")
    return hashlib.sha256(secret_channel_id.encode("utf-8")).hexdigest() + ".channel"


def _receipt_name(receipt_digest: str) -> str:
    _require_digest(receipt_digest, "receipt")
    return receipt_digest + ".json"


def _intent_body(resource: Any) -> dict[str, object]:
    return {
        "cleanup_locator_digest": resource.cleanup_locator_digest,
        "issuer_id": resource.issuer_id,
        "resource_id": resource.resource_id,
        "revocation_generation": resource.revocation_generation,
        "schema": _INTENT_SCHEMA,
        "secret_channel_id": resource.secret_channel_id,
        "transaction_id": resource.transaction_id,
    }


def _intent_digest(resource: Any) -> str:
    return hashlib.sha256(_canonical(_intent_body(resource))).hexdigest()


def _prepared_intent_name(resource: Any) -> str:
    return _intent_digest(resource) + ".prepared.json"


def _terminal_intent_name(resource: Any) -> str:
    return _intent_digest(resource) + ".terminal.json"


def _stable_identity(value: NativeFileIdentity) -> tuple[int, int, bool, bool, int, int]:
    return (
        value.volume_id,
        value.file_id,
        value.is_directory,
        value.is_reparse,
        value.mount_id,
        value.reparse_tag,
    )


def _safe_store_root(value: str | Path, *, create: bool) -> Path:
    root = Path(value)
    try:
        if create:
            root.mkdir(parents=True, exist_ok=True)
        root = assertNoReparsePath(root)
    except OSError as exc:
        raise CredentialChannelEvidenceRefused(
            "credential channel store root is unsafe"
        ) from exc
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise CredentialChannelEvidenceRefused(
            "credential channel store root is unsafe"
        )
    return root


def _safe_child(root: Path, name: str, *, create: bool) -> Path:
    child = root / name
    try:
        if create:
            child.mkdir(exist_ok=True)
        child = assertNoReparsePath(child)
    except OSError as exc:
        raise CredentialChannelEvidenceRefused(
            "credential channel store child is unsafe"
        ) from exc
    if not child.is_dir() or child.is_symlink():
        raise CredentialChannelEvidenceRefused(
            "credential channel store child is unsafe"
        )
    return child


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _require_id(value: object, name: str) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise CredentialChannelEvidenceRefused(f"{name} is invalid")
    return value


def _require_digest(value: object, name: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise CredentialChannelEvidenceRefused(f"{name} digest is invalid")
    return value


def _require_time(value: object, name: str) -> str:
    if type(value) is not str:
        raise CredentialChannelEvidenceRefused(f"{name} is invalid")
    try:
        observed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CredentialChannelEvidenceRefused(f"{name} is invalid") from exc
    if observed.tzinfo is None:
        raise CredentialChannelEvidenceRefused(f"{name} must be absolute")
    canonical = observed.astimezone(timezone.utc).isoformat()
    if canonical != value:
        raise CredentialChannelEvidenceRefused(
            f"{name} must use its exact canonical UTC encoding"
        )
    return value


def _closed_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CredentialChannelEvidenceRefused("receipt contains a duplicate key")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True, kw_only=True)
class CredentialChannelDestructionIntent:
    """Immutable PREPARED intent; it never claims deletion or absence."""

    transaction_id: str
    resource_id: str
    secret_channel_id: str
    issuer_id: str
    revocation_generation: int
    cleanup_locator_digest: str
    intent_digest: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.transaction_id, "transaction_id"),
            (self.resource_id, "resource_id"),
            (self.secret_channel_id, "secret_channel_id"),
            (self.issuer_id, "issuer_id"),
        ):
            _require_id(value, name)
        if type(self.revocation_generation) is not int or self.revocation_generation < 1:
            raise CredentialChannelEvidenceRefused(
                "revocation_generation must be a positive integer"
            )
        _require_digest(self.cleanup_locator_digest, "cleanup_locator")
        _require_digest(self.intent_digest, "intent")
        if self.intent_digest != hashlib.sha256(_canonical(self._body())).hexdigest():
            raise CredentialChannelEvidenceRefused(
                "destruction intent digest differs from its body"
            )

    def _body(self) -> dict[str, object]:
        return {
            "cleanup_locator_digest": self.cleanup_locator_digest,
            "issuer_id": self.issuer_id,
            "resource_id": self.resource_id,
            "revocation_generation": self.revocation_generation,
            "schema": _INTENT_SCHEMA,
            "secret_channel_id": self.secret_channel_id,
            "transaction_id": self.transaction_id,
        }

    @classmethod
    def issue(cls, resource: Any) -> "CredentialChannelDestructionIntent":
        body = _intent_body(resource)
        return cls(
            transaction_id=resource.transaction_id,
            resource_id=resource.resource_id,
            secret_channel_id=resource.secret_channel_id,
            issuer_id=resource.issuer_id,
            revocation_generation=resource.revocation_generation,
            cleanup_locator_digest=resource.cleanup_locator_digest,
            intent_digest=hashlib.sha256(_canonical(body)).hexdigest(),
        )

    def toBytes(self) -> bytes:
        return _canonical({**self._body(), "intent_digest": self.intent_digest})

    @classmethod
    def fromBytes(cls, raw: bytes) -> "CredentialChannelDestructionIntent":
        if type(raw) is not bytes or len(raw) > _MAX_RECEIPT_BYTES:
            raise CredentialChannelEvidenceRefused(
                "destruction intent bytes exceed their bound"
            )
        try:
            payload = json.loads(
                raw.decode("utf-8", errors="strict"),
                object_pairs_hook=_closed_object,
                parse_constant=lambda value: (_ for _ in ()).throw(
                    CredentialChannelEvidenceRefused(
                        f"intent contains forbidden JSON constant {value}"
                    )
                ),
            )
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CredentialChannelEvidenceRefused(
                "destruction intent is not strict JSON"
            ) from exc
        keys = {
            "cleanup_locator_digest",
            "intent_digest",
            "issuer_id",
            "resource_id",
            "revocation_generation",
            "schema",
            "secret_channel_id",
            "transaction_id",
        }
        if not isinstance(payload, dict) or set(payload) != keys:
            raise CredentialChannelEvidenceRefused(
                "destruction intent schema is not closed"
            )
        if payload["schema"] != _INTENT_SCHEMA or _canonical(payload) != raw:
            raise CredentialChannelEvidenceRefused(
                "destruction intent encoding is not canonical"
            )
        return cls(
            transaction_id=payload["transaction_id"],
            resource_id=payload["resource_id"],
            secret_channel_id=payload["secret_channel_id"],
            issuer_id=payload["issuer_id"],
            revocation_generation=payload["revocation_generation"],
            cleanup_locator_digest=payload["cleanup_locator_digest"],
            intent_digest=payload["intent_digest"],
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CredentialChannelDestructionReceipt:
    """Content-addressed public evidence for one exact destroyed secret channel."""

    transaction_id: str
    resource_id: str
    secret_channel_id: str
    issuer_id: str
    revocation_generation: int
    cleanup_locator_digest: str
    destroyed_at: str
    receipt_digest: str

    def __post_init__(self) -> None:
        _require_id(self.transaction_id, "transaction_id")
        _require_id(self.resource_id, "resource_id")
        _require_id(self.secret_channel_id, "secret_channel_id")
        _require_id(self.issuer_id, "issuer_id")
        if type(self.revocation_generation) is not int or self.revocation_generation < 1:
            raise CredentialChannelEvidenceRefused(
                "revocation_generation must be a positive integer"
            )
        _require_digest(self.cleanup_locator_digest, "cleanup_locator")
        _require_time(self.destroyed_at, "destroyed_at")
        _require_digest(self.receipt_digest, "receipt")
        if self.receipt_digest != hashlib.sha256(_canonical(self._body())).hexdigest():
            raise CredentialChannelEvidenceRefused("receipt digest differs from its body")

    def _body(self) -> dict[str, object]:
        return {
            "cleanup_locator_digest": self.cleanup_locator_digest,
            "destroyed_at": self.destroyed_at,
            "issuer_id": self.issuer_id,
            "resource_id": self.resource_id,
            "revocation_generation": self.revocation_generation,
            "schema": _SCHEMA,
            "secret_channel_id": self.secret_channel_id,
            "transaction_id": self.transaction_id,
        }

    @classmethod
    def issue(
        cls,
        *,
        transaction_id: str,
        resource_id: str,
        secret_channel_id: str,
        issuer_id: str,
        revocation_generation: int,
        cleanup_locator_digest: str,
        destroyed_at: str,
    ) -> "CredentialChannelDestructionReceipt":
        body = {
            "cleanup_locator_digest": cleanup_locator_digest,
            "destroyed_at": destroyed_at,
            "issuer_id": issuer_id,
            "resource_id": resource_id,
            "revocation_generation": revocation_generation,
            "schema": _SCHEMA,
            "secret_channel_id": secret_channel_id,
            "transaction_id": transaction_id,
        }
        return cls(
            transaction_id=transaction_id,
            resource_id=resource_id,
            secret_channel_id=secret_channel_id,
            issuer_id=issuer_id,
            revocation_generation=revocation_generation,
            cleanup_locator_digest=cleanup_locator_digest,
            destroyed_at=destroyed_at,
            receipt_digest=hashlib.sha256(_canonical(body)).hexdigest(),
        )

    def toDict(self) -> dict[str, object]:
        return {**self._body(), "receipt_digest": self.receipt_digest}

    def toBytes(self) -> bytes:
        return _canonical(self.toDict())

    @classmethod
    def fromBytes(cls, raw: bytes) -> "CredentialChannelDestructionReceipt":
        if type(raw) is not bytes or len(raw) > _MAX_RECEIPT_BYTES:
            raise CredentialChannelEvidenceRefused("receipt bytes exceed their bound")
        try:
            payload = json.loads(
                raw.decode("utf-8", errors="strict"),
                object_pairs_hook=_closed_object,
                parse_constant=lambda value: (_ for _ in ()).throw(
                    CredentialChannelEvidenceRefused(
                        f"receipt contains forbidden JSON constant {value}"
                    )
                ),
            )
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CredentialChannelEvidenceRefused("receipt is not strict JSON") from exc
        keys = {
            "cleanup_locator_digest",
            "destroyed_at",
            "issuer_id",
            "receipt_digest",
            "resource_id",
            "revocation_generation",
            "schema",
            "secret_channel_id",
            "transaction_id",
        }
        if not isinstance(payload, dict) or set(payload) != keys:
            raise CredentialChannelEvidenceRefused("receipt schema is not closed")
        if payload["schema"] != _SCHEMA or _canonical(payload) != raw:
            raise CredentialChannelEvidenceRefused("receipt encoding is not canonical")
        return cls(
            transaction_id=payload["transaction_id"],
            resource_id=payload["resource_id"],
            secret_channel_id=payload["secret_channel_id"],
            issuer_id=payload["issuer_id"],
            revocation_generation=payload["revocation_generation"],
            cleanup_locator_digest=payload["cleanup_locator_digest"],
            destroyed_at=payload["destroyed_at"],
            receipt_digest=payload["receipt_digest"],
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CredentialChannelAbsenceObservation:
    """Fresh process-local observation of a protected terminal channel record."""

    transaction_id: str
    resource_id: str
    secret_channel_id: str
    issuer_id: str
    revocation_generation: int
    cleanup_locator_digest: str
    receipt_digest: str
    destroyed_at: str
    observed_at: str
    absent: bool
    _verifier_identity: int
    _seal: object

    def __post_init__(self) -> None:
        for value, name in (
            (self.transaction_id, "transaction_id"),
            (self.resource_id, "resource_id"),
            (self.secret_channel_id, "secret_channel_id"),
            (self.issuer_id, "issuer_id"),
        ):
            _require_id(value, name)
        if type(self.revocation_generation) is not int or self.revocation_generation < 1:
            raise CredentialChannelEvidenceRefused(
                "revocation_generation must be a positive integer"
            )
        _require_digest(self.cleanup_locator_digest, "cleanup_locator")
        _require_digest(self.receipt_digest, "receipt")
        _require_time(self.destroyed_at, "destroyed_at")
        _require_time(self.observed_at, "observed_at")
        if self.absent is not True:
            raise CredentialChannelEvidenceRefused(
                "credential channel observation must prove absence"
            )

    def toDict(self) -> dict[str, object]:
        return {
            "absent": self.absent,
            "cleanup_locator_digest": self.cleanup_locator_digest,
            "destroyed_at": self.destroyed_at,
            "issuer_id": self.issuer_id,
            "observed_at": self.observed_at,
            "receipt_digest": self.receipt_digest,
            "resource_id": self.resource_id,
            "revocation_generation": self.revocation_generation,
            "secret_channel_id": self.secret_channel_id,
            "transaction_id": self.transaction_id,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class CredentialChannelDeletedObservation:
    """Sealed preterminal proof that the exact retained channel is absent."""

    transaction_id: str
    resource_id: str
    secret_channel_id: str
    issuer_id: str
    revocation_generation: int
    cleanup_locator_digest: str
    intent_digest: str
    observed_at: str
    absent: bool
    _verifier_identity: int
    _seal: object

    def __post_init__(self) -> None:
        for value, name in (
            (self.transaction_id, "transaction_id"),
            (self.resource_id, "resource_id"),
            (self.secret_channel_id, "secret_channel_id"),
            (self.issuer_id, "issuer_id"),
        ):
            _require_id(value, name)
        if type(self.revocation_generation) is not int or self.revocation_generation < 1:
            raise CredentialChannelEvidenceRefused(
                "revocation_generation must be a positive integer"
            )
        _require_digest(self.cleanup_locator_digest, "cleanup_locator")
        _require_digest(self.intent_digest, "intent")
        _require_time(self.observed_at, "observed_at")
        if self.absent is not True:
            raise CredentialChannelEvidenceRefused(
                "credential deletion observation must prove absence"
            )


class CredentialChannelDestroyer:
    """Exact broker-issued authority that zeroes and removes one bound channel."""

    __slots__ = (
        "_broker",
        "_channels",
        "_directory_identities",
        "_identity",
        "_intents",
        "_issuer_id",
        "_receipts",
        "_root",
        "_root_identity",
        "_bound_resource",
        "_seal",
        "_absence_verifier",
        "_coordinator",
    )

    def __init__(
        self,
        *,
        broker: object,
        absence_verifier: CredentialChannelAbsenceVerifier,
        coordinator: object,
        resource: object,
        _factory: object,
    ) -> None:
        if _factory is not _FACTORY_TOKEN:
            raise CredentialChannelEvidenceRefused(
                "credential channel destroyer requires sealed broker composition"
            )
        exact_broker = _exact_broker(broker)
        self._broker = exact_broker
        self._root = _safe_store_root(exact_broker._root, create=False)
        self._channels = _safe_child(self._root, "channels", create=False)
        self._receipts = _safe_child(self._root, "destruction-receipts", create=False)
        self._intents = _safe_child(self._root, "destruction-intents", create=False)
        _require_id(exact_broker._issuer_id, "issuer_id")
        self._issuer_id = exact_broker._issuer_id
        if type(absence_verifier) is not CredentialChannelAbsenceVerifier:
            raise CredentialChannelEvidenceRefused(
                "credential channel destroyer requires its exact sealed verifier"
            )
        absence_verifier._requireIssued()
        from platform_core.runtime.attempt_journal import (
            AttemptPersistenceAuthorityRefused,
            _CredentialJournalCoordinator,
        )

        if type(coordinator) is not _CredentialJournalCoordinator:
            raise CredentialChannelEvidenceRefused(
                "credential channel destroyer requires an exact journal coordinator"
            )
        try:
            exact_resource = coordinator.current(resource)
        except AttemptPersistenceAuthorityRefused as exc:
            raise CredentialChannelEvidenceRefused(
                "credential channel destroyer coordinator binding differs"
            ) from exc
        if coordinator._broker is not exact_broker:
            raise CredentialChannelEvidenceRefused(
                "credential channel destroyer broker and coordinator differ"
            )
        if absence_verifier._broker is not exact_broker:
            raise CredentialChannelEvidenceRefused(
                "credential channel destroyer broker and verifier differ"
            )
        self._absence_verifier = absence_verifier
        self._coordinator = coordinator
        self._bound_resource = exact_resource
        self._identity = id(self)
        self._seal = object()
        with openNativeDirectory(self._root) as directory:
            self._root_identity = _stable_identity(directory.identity)
        self._directory_identities = self._observe_child_identities()

    def _requireIssued(self) -> None:
        _require_channel_object(self, kind="destroyer")
        _exact_broker(self._broker)

    def _observe_child_identities(
        self,
    ) -> dict[str, tuple[int, int, bool, bool, int, int]]:
        identities: dict[str, tuple[int, int, bool, bool, int, int]] = {}
        for name, path in (
            ("channels", self._channels),
            ("destruction-receipts", self._receipts),
            ("destruction-intents", self._intents),
        ):
            try:
                with openNativeDirectory(path) as directory:
                    identities[name] = _stable_identity(directory.identity)
            except OSError as exc:
                raise CredentialChannelEvidenceRefused(
                    "credential channel store child is unavailable"
                ) from exc
        return identities

    @staticmethod
    def _resource(value: object) -> Any:
        from platform_core.runtime.candidate import (
            CredentialResourceState,
            ResourceRole,
            RuntimeResourceLease,
        )

        if type(value) is not RuntimeResourceLease:
            raise CredentialChannelEvidenceRefused(
                "credential channel operation requires an exact runtime resource"
            )
        observed = cast(Any, value)
        if observed.role is not ResourceRole.CREDENTIAL_LEASE:
            raise CredentialChannelEvidenceRefused(
                "credential channel operation requires a credential resource"
            )
        if observed.state not in {
            CredentialResourceState.REGISTERED,
            CredentialResourceState.ISSUED,
            CredentialResourceState.INJECTED,
            CredentialResourceState.REVOKED_OR_EXPIRED,
            CredentialResourceState.DESTROYED,
        }:
            raise CredentialChannelEvidenceRefused(
                "credential channel resource state is unsupported"
            )
        return observed

    def _revalidate_root(self) -> None:
        with openNativeDirectory(_safe_store_root(self._root, create=False)) as root:
            if _stable_identity(root.identity) != self._root_identity:
                raise CredentialChannelEvidenceRefused(
                    "credential channel store identity changed"
                )
        for name, path in (
            ("channels", self._channels),
            ("destruction-receipts", self._receipts),
            ("destruction-intents", self._intents),
        ):
            try:
                with openNativeDirectory(_safe_child(self._root, name, create=False)) as child:
                    observed = _stable_identity(child.identity)
            except OSError as exc:
                raise CredentialChannelEvidenceRefused(
                    "credential channel store child is unavailable"
                ) from exc
            if observed != self._directory_identities[name]:
                raise CredentialChannelEvidenceRefused(
                    f"credential channel store child identity changed: {name}"
                )

    def _broker_now(self) -> datetime:
        from platform_core.execution.credential_broker import CredentialBroker

        return CredentialBroker._clockNow(_exact_broker(self._broker))

    def revoke(self, resource: object) -> object:
        from platform_core.execution.credential_broker import (
            CredentialBroker,
            CredentialBrokerRefused,
        )

        self._requireIssued()
        broker = _exact_broker(self._broker)
        try:
            with CredentialBroker._channelGuard(broker):
                self._revokeGuarded(resource)
                try:
                    return self._coordinator.commitRevoked(resource)
                except Exception as exc:
                    from platform_core.runtime.attempt_journal import (
                        AttemptPersistenceAuthorityRefused,
                    )

                    if isinstance(exc, AttemptPersistenceAuthorityRefused):
                        raise CredentialChannelEvidenceRefused(
                            "credential revoked state could not be committed exactly"
                        ) from exc
                    raise
        except CredentialBrokerRefused as exc:
            raise CredentialChannelEvidenceRefused(
                "credential broker revocation lifecycle refused"
            ) from exc

    def _revokeGuarded(self, resource: object) -> None:
        observed = self._resource(resource)
        if observed.issuer_id != self._issuer_id:
            raise CredentialChannelEvidenceRefused(
                "credential channel issuer differs"
            )
        try:
            self._coordinator.current(observed)
        except Exception as exc:
            from platform_core.runtime.attempt_journal import (
                AttemptPersistenceAuthorityRefused,
            )

            if isinstance(exc, AttemptPersistenceAuthorityRefused):
                raise CredentialChannelEvidenceRefused(
                    "credential channel resource binding differs"
                ) from exc
            raise
        self._revalidate_root()
        from platform_core.execution.credential_broker import CredentialBroker

        broker = _exact_broker(self._broker)
        CredentialBroker._zeroSecret(broker, observed.resource_id)
        CredentialBroker._markRevoked(broker, observed)
        self._revalidate_root()

    def _load_receipt(self, digest: str) -> CredentialChannelDestructionReceipt:
        try:
            raw = readNoFollowBytes(
                self._receipts / _receipt_name(digest),
                max_bytes=_MAX_RECEIPT_BYTES,
            )
        except (OSError, ValueError) as exc:
            raise CredentialChannelEvidenceRefused(
                "credential destruction receipt is unavailable"
            ) from exc
        return CredentialChannelDestructionReceipt.fromBytes(raw)

    def _persist_receipt(
        self,
        receipt: CredentialChannelDestructionReceipt,
    ) -> CredentialChannelDestructionReceipt:
        path = self._receipts / _receipt_name(receipt.receipt_digest)
        raw = receipt.toBytes()
        try:
            exclusiveCreateBytes(path, raw)
        except FileExistsError:
            existing = self._load_receipt(receipt.receipt_digest)
            if existing != receipt:
                raise CredentialChannelEvidenceRefused(
                    "credential destruction receipt collision"
                )
            return existing
        except OSError as exc:
            raise CredentialChannelEvidenceRefused(
                "credential destruction receipt could not be persisted"
            ) from exc
        return self._load_receipt(receipt.receipt_digest)

    def _load_prepared_intent(
        self,
        resource: Any,
    ) -> CredentialChannelDestructionIntent:
        try:
            raw = readNoFollowBytes(
                self._intents / _prepared_intent_name(resource),
                max_bytes=_MAX_RECEIPT_BYTES,
            )
        except (OSError, ValueError) as exc:
            raise CredentialChannelEvidenceRefused(
                "prepared credential destruction intent is unavailable"
            ) from exc
        intent = CredentialChannelDestructionIntent.fromBytes(raw)
        _validate_intent_binding(intent, resource)
        return intent

    def _persist_prepared_intent(
        self,
        resource: Any,
        intent: CredentialChannelDestructionIntent,
    ) -> CredentialChannelDestructionIntent:
        _validate_intent_binding(intent, resource)
        path = self._intents / _prepared_intent_name(resource)
        raw = intent.toBytes()
        try:
            exclusiveCreateBytes(path, raw)
        except FileExistsError:
            existing = self._load_prepared_intent(resource)
            if existing != intent:
                raise CredentialChannelEvidenceRefused(
                    "prepared credential destruction intent collision"
                )
            return existing
        except OSError as exc:
            raise CredentialChannelEvidenceRefused(
                "prepared credential destruction intent could not be persisted"
            ) from exc
        return self._load_prepared_intent(resource)

    def _prepare_intent(self, resource: Any) -> CredentialChannelDestructionIntent:
        try:
            return self._load_prepared_intent(resource)
        except CredentialChannelEvidenceRefused as exc:
            try:
                return self._persist_prepared_intent(
                    resource,
                    CredentialChannelDestructionIntent.issue(resource),
                )
            except FileExistsError:
                raise exc

    def _load_terminal_intent(
        self,
        resource: Any,
        *,
        optional: bool = False,
    ) -> CredentialChannelDestructionReceipt | None:
        try:
            raw = readNoFollowBytes(
                self._intents / _terminal_intent_name(resource),
                max_bytes=_MAX_RECEIPT_BYTES,
            )
        except FileNotFoundError:
            if optional:
                return None
            raise CredentialChannelEvidenceRefused(
                "terminal credential destruction intent is unavailable"
            )
        except (OSError, ValueError) as exc:
            raise CredentialChannelEvidenceRefused(
                "terminal credential destruction intent is unavailable"
            ) from exc
        receipt = CredentialChannelDestructionReceipt.fromBytes(raw)
        _validate_static_receipt_binding(receipt, resource)
        return receipt

    def _persist_terminal_intent(
        self,
        resource: Any,
        receipt: CredentialChannelDestructionReceipt,
    ) -> CredentialChannelDestructionReceipt:
        _validate_static_receipt_binding(receipt, resource)
        path = self._intents / _terminal_intent_name(resource)
        try:
            exclusiveCreateBytes(path, receipt.toBytes())
        except FileExistsError:
            existing = self._load_terminal_intent(resource)
            if existing != receipt:
                raise CredentialChannelEvidenceRefused(
                    "terminal credential destruction intent collision"
                )
            return existing
        except OSError as exc:
            raise CredentialChannelEvidenceRefused(
                "terminal credential destruction intent could not be persisted"
            ) from exc
        persisted = self._load_terminal_intent(resource)
        assert persisted is not None
        return persisted

    def _existing_terminal_receipt(
        self,
        resource: Any,
    ) -> CredentialChannelDestructionReceipt | None:
        existing = self._load_terminal_intent(resource, optional=True)
        if existing is not None:
            _validate_terminal_chronology(existing, resource)
            return existing
        from platform_core.execution.credential_broker import CredentialBroker

        terminal = CredentialBroker._loadTerminalReceipt(
            _exact_broker(self._broker),
            resource,
        )
        if terminal is not None:
            _validate_static_receipt_binding(terminal, resource)
            _validate_terminal_chronology(terminal, resource)
            return self._persist_terminal_intent(resource, terminal)
        return None

    def _select_terminal_receipt(
        self,
        resource: Any,
        deletion_observation: CredentialChannelDeletedObservation,
    ) -> CredentialChannelDestructionReceipt:
        existing = self._existing_terminal_receipt(resource)
        if existing is not None:
            return existing
        self._absence_verifier._requireDeletedObservation(
            deletion_observation,
            resource,
        )
        receipt = CredentialChannelDestructionReceipt.issue(
            transaction_id=resource.transaction_id,
            resource_id=resource.resource_id,
            secret_channel_id=resource.secret_channel_id,
            issuer_id=resource.issuer_id,
            revocation_generation=resource.revocation_generation,
            cleanup_locator_digest=resource.cleanup_locator_digest,
            destroyed_at=_canonical_now(self._broker_now),
        )
        _validate_terminal_chronology(receipt, resource)
        if datetime.fromisoformat(receipt.destroyed_at) < datetime.fromisoformat(
            deletion_observation.observed_at
        ):
            raise CredentialChannelEvidenceRefused(
                "terminal destruction timestamp predates fresh channel absence"
            )
        return self._persist_terminal_intent(resource, receipt)

    def _remove_channel(self, secret_channel_id: str) -> None:
        name = _channel_name(secret_channel_id)
        try:
            directory = openNativeDirectory(self._channels)
        except OSError as exc:
            raise CredentialChannelEvidenceRefused(
                "credential channel directory is unavailable"
            ) from exc
        with directory:
            try:
                entry = next(
                    item for item in directory.listEntries() if item.name == name
                )
            except StopIteration:
                return
            if (
                entry.identity.is_directory
                or entry.identity.is_reparse
                or entry.identity.link_count != 1
                or entry.identity.size > _CHANNEL_BYTES_MAX
            ):
                raise CredentialChannelEvidenceRefused(
                    "credential channel artifact is unsafe"
                )
            try:
                directory.removeFile(name, expected=entry.identity)
            except OSError as exc:
                raise CredentialChannelEvidenceRefused(
                    "credential channel artifact could not be destroyed exactly"
                ) from exc

    def destroy(self, resource: object) -> CredentialChannelDestructionReceipt:
        from platform_core.execution.credential_broker import (
            CredentialBroker,
            CredentialBrokerRefused,
        )

        self._requireIssued()
        broker = _exact_broker(self._broker)
        try:
            with CredentialBroker._channelGuard(broker):
                try:
                    observed = self._resource(self._coordinator.current(resource))
                except Exception as exc:
                    from platform_core.runtime.attempt_journal import (
                        AttemptPersistenceAuthorityRefused,
                    )

                    if isinstance(exc, AttemptPersistenceAuthorityRefused):
                        raise CredentialChannelEvidenceRefused(
                            "credential channel resource binding differs"
                        ) from exc
                    raise
                if observed.state.value in {"registered", "issued", "injected"}:
                    self._revokeGuarded(observed)
                    try:
                        observed = self._coordinator.commitRevoked(observed)
                    except Exception as exc:
                        from platform_core.runtime.attempt_journal import (
                            AttemptPersistenceAuthorityRefused,
                        )

                        if isinstance(exc, AttemptPersistenceAuthorityRefused):
                            raise CredentialChannelEvidenceRefused(
                                "credential revoked state could not be committed exactly"
                            ) from exc
                        raise
                receipt = self._destroyGuarded(observed)
                try:
                    self._coordinator.commitDestroyed(
                        observed,
                        receipt=receipt,
                        verifier=self._absence_verifier,
                    )
                except Exception as exc:
                    from platform_core.runtime.attempt_journal import (
                        AttemptPersistenceAuthorityRefused,
                    )

                    if isinstance(exc, AttemptPersistenceAuthorityRefused):
                        raise CredentialChannelEvidenceRefused(
                            "credential destroyed state could not be committed exactly"
                        ) from exc
                    raise
                return receipt
        except CredentialBrokerRefused as exc:
            raise CredentialChannelEvidenceRefused(
                "credential broker destruction lifecycle refused"
            ) from exc

    def _destroyGuarded(
        self,
        resource: object,
    ) -> CredentialChannelDestructionReceipt:
        observed = self._resource(resource)
        if observed.issuer_id != self._issuer_id:
            raise CredentialChannelEvidenceRefused(
                "credential channel issuer differs"
            )
        try:
            self._coordinator.current(observed)
        except Exception as exc:
            from platform_core.runtime.attempt_journal import (
                AttemptPersistenceAuthorityRefused,
            )

            if isinstance(exc, AttemptPersistenceAuthorityRefused):
                raise CredentialChannelEvidenceRefused(
                    "credential channel resource binding differs"
                ) from exc
            raise
        if observed.state.value == "destroyed":
            self._revalidate_root()
            destroyed_receipt = self._load_receipt(
                observed.credential_destruction_receipt_digest
            )
            _validate_receipt_binding(destroyed_receipt, observed)
            self._load_prepared_intent(observed)
            if self._load_terminal_intent(observed) != destroyed_receipt:
                raise CredentialChannelEvidenceRefused(
                    "terminal credential destruction intent differs from its receipt"
                )
            return destroyed_receipt
        self._revalidate_root()
        from platform_core.execution.credential_broker import CredentialBroker

        broker = _exact_broker(self._broker)
        CredentialBroker._zeroSecret(broker, observed.resource_id)
        intent = self._prepare_intent(observed)
        self._remove_channel(observed.secret_channel_id)
        receipt = self._existing_terminal_receipt(observed)
        if receipt is None:
            deletion_observation = self._absence_verifier.observeDeleted(
                observed,
                intent,
            )
            receipt = self._select_terminal_receipt(
                observed,
                deletion_observation,
            )
        persisted = self._persist_receipt(receipt)
        CredentialBroker._markDestroyed(broker, observed, persisted)
        self._revalidate_root()
        return persisted


def _validate_intent_binding(
    intent: CredentialChannelDestructionIntent,
    resource: Any,
) -> None:
    exact = (
        ("transaction", intent.transaction_id, resource.transaction_id),
        ("resource", intent.resource_id, resource.resource_id),
        ("channel", intent.secret_channel_id, resource.secret_channel_id),
        ("issuer", intent.issuer_id, resource.issuer_id),
        (
            "revocation generation",
            intent.revocation_generation,
            resource.revocation_generation,
        ),
        (
            "cleanup locator",
            intent.cleanup_locator_digest,
            resource.cleanup_locator_digest,
        ),
        ("intent digest", intent.intent_digest, _intent_digest(resource)),
    )
    for label, observed, expected in exact:
        if observed != expected:
            raise CredentialChannelEvidenceRefused(
                f"credential destruction intent {label} differs"
            )


def _validate_static_receipt_binding(
    receipt: CredentialChannelDestructionReceipt,
    resource: Any,
) -> None:
    exact = (
        ("transaction", receipt.transaction_id, resource.transaction_id),
        ("resource", receipt.resource_id, resource.resource_id),
        ("channel", receipt.secret_channel_id, resource.secret_channel_id),
        ("issuer", receipt.issuer_id, resource.issuer_id),
        (
            "revocation generation",
            receipt.revocation_generation,
            resource.revocation_generation,
        ),
        (
            "cleanup locator",
            receipt.cleanup_locator_digest,
            resource.cleanup_locator_digest,
        ),
    )
    for label, observed, expected in exact:
        if observed != expected:
            raise CredentialChannelEvidenceRefused(
                f"credential destruction receipt {label} differs"
            )


def _validate_receipt_binding(
    receipt: CredentialChannelDestructionReceipt,
    resource: Any,
) -> None:
    _validate_static_receipt_binding(receipt, resource)
    for label, observed, expected in (
        (
            "destroyed timestamp",
            receipt.destroyed_at,
            resource.credential_destroyed_at,
        ),
        (
            "receipt digest",
            receipt.receipt_digest,
            resource.credential_destruction_receipt_digest,
        ),
    ):
        if observed != expected:
            raise CredentialChannelEvidenceRefused(
                f"credential destruction receipt {label} differs"
            )


def _validate_terminal_chronology(
    receipt: CredentialChannelDestructionReceipt,
    resource: Any,
) -> None:
    _require_time(resource.updated_at, "resource updated_at")
    if datetime.fromisoformat(receipt.destroyed_at) < datetime.fromisoformat(
        resource.updated_at
    ):
        raise CredentialChannelEvidenceRefused(
            "credential destruction clock rollback predates the resource observation"
        )


class CredentialChannelAbsenceVerifier:
    """Fresh protected-root verifier; persisted receipts never self-authorize."""

    __slots__ = (
        "_broker",
        "_channels",
        "_directory_identities",
        "_identity",
        "_intents",
        "_issuer_id",
        "_receipts",
        "_root",
        "_root_identity",
        "_seal",
    )

    def __init__(
        self,
        *,
        broker: object,
        _factory: object,
    ) -> None:
        if _factory is not _FACTORY_TOKEN:
            raise CredentialChannelEvidenceRefused(
                "credential absence verifier requires sealed broker composition"
            )
        exact_broker = _exact_broker(broker)
        self._broker = exact_broker
        self._root = _safe_store_root(exact_broker._root, create=False)
        self._channels = _safe_child(self._root, "channels", create=False)
        self._receipts = _safe_child(
            self._root,
            "destruction-receipts",
            create=False,
        )
        self._intents = _safe_child(
            self._root,
            "destruction-intents",
            create=False,
        )
        _require_id(exact_broker._issuer_id, "issuer_id")
        self._issuer_id = exact_broker._issuer_id
        self._identity = id(self)
        self._seal = object()
        with openNativeDirectory(self._root) as directory:
            self._root_identity = _stable_identity(directory.identity)
        self._directory_identities = self._observe_child_identities()

    def _requireIssued(self) -> None:
        _require_channel_object(self, kind="verifier")
        _exact_broker(self._broker)

    def _observe_child_identities(
        self,
    ) -> dict[str, tuple[int, int, bool, bool, int, int]]:
        identities: dict[str, tuple[int, int, bool, bool, int, int]] = {}
        for name, path in (
            ("channels", self._channels),
            ("destruction-receipts", self._receipts),
            ("destruction-intents", self._intents),
        ):
            try:
                with openNativeDirectory(path) as directory:
                    identities[name] = _stable_identity(directory.identity)
            except OSError as exc:
                raise CredentialChannelEvidenceRefused(
                    "credential absence verifier child is unavailable"
                ) from exc
        return identities

    def _revalidate_directories(self) -> None:
        with openNativeDirectory(_safe_store_root(self._root, create=False)) as root:
            if _stable_identity(root.identity) != self._root_identity:
                raise CredentialChannelEvidenceRefused(
                    "credential absence verifier root identity changed"
                )
        for name in ("channels", "destruction-receipts", "destruction-intents"):
            try:
                path = _safe_child(self._root, name, create=False)
                with openNativeDirectory(path) as child:
                    observed = _stable_identity(child.identity)
            except OSError as exc:
                raise CredentialChannelEvidenceRefused(
                    "credential absence verifier child is unavailable"
                ) from exc
            if observed != self._directory_identities[name]:
                raise CredentialChannelEvidenceRefused(
                    f"credential absence verifier child identity changed: {name}"
                )

    def _broker_now(self) -> datetime:
        from platform_core.execution.credential_broker import CredentialBroker

        return CredentialBroker._clockNow(_exact_broker(self._broker))

    def _broker_terminal_metadata_absent(self, resource: object) -> bool:
        from platform_core.execution.credential_broker import CredentialBroker

        return CredentialBroker._terminalMetadataAbsent(
            _exact_broker(self._broker),
            resource,
        )

    def _broker_terminal_metadata_exact(
        self,
        resource: object,
        receipt: CredentialChannelDestructionReceipt,
    ) -> bool:
        from platform_core.execution.credential_broker import CredentialBroker

        return CredentialBroker._terminalMetadataExact(
            _exact_broker(self._broker),
            resource,
            receipt,
        )

    def _load(self, resource: Any) -> CredentialChannelDestructionReceipt:
        receipt = self._load_digest(
            resource.credential_destruction_receipt_digest
        )
        _validate_receipt_binding(receipt, resource)
        return receipt

    def _load_digest(self, digest: str) -> CredentialChannelDestructionReceipt:
        try:
            raw = readNoFollowBytes(
                self._receipts
                / _receipt_name(digest),
                max_bytes=_MAX_RECEIPT_BYTES,
            )
        except (OSError, ValueError) as exc:
            raise CredentialChannelEvidenceRefused(
                "credential destruction receipt is unavailable"
            ) from exc
        return CredentialChannelDestructionReceipt.fromBytes(raw)

    def _load_prepared_intent(
        self,
        resource: Any,
    ) -> CredentialChannelDestructionIntent:
        try:
            raw = readNoFollowBytes(
                self._intents / _prepared_intent_name(resource),
                max_bytes=_MAX_RECEIPT_BYTES,
            )
        except (OSError, ValueError) as exc:
            raise CredentialChannelEvidenceRefused(
                "prepared credential destruction intent is unavailable"
            ) from exc
        intent = CredentialChannelDestructionIntent.fromBytes(raw)
        _validate_intent_binding(intent, resource)
        return intent

    def _load_terminal_intent(
        self,
        resource: Any,
    ) -> CredentialChannelDestructionReceipt:
        try:
            raw = readNoFollowBytes(
                self._intents / _terminal_intent_name(resource),
                max_bytes=_MAX_RECEIPT_BYTES,
            )
        except (OSError, ValueError) as exc:
            raise CredentialChannelEvidenceRefused(
                "terminal credential destruction intent is unavailable"
            ) from exc
        receipt = CredentialChannelDestructionReceipt.fromBytes(raw)
        _validate_receipt_binding(receipt, resource)
        return receipt

    def _terminal_intent_absent(self, resource: Any) -> None:
        try:
            readNoFollowBytes(
                self._intents / _terminal_intent_name(resource),
                max_bytes=_MAX_RECEIPT_BYTES,
            )
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            raise CredentialChannelEvidenceRefused(
                "terminal credential destruction state is unobservable"
            ) from exc
        raise CredentialChannelEvidenceRefused(
            "terminal credential destruction state already exists"
        )

    def _observe_channel_absent(self, resource: Any) -> None:
        self._revalidate_directories()
        name = _channel_name(resource.secret_channel_id)
        try:
            with openNativeDirectory(self._channels) as channels:
                pinned = self._directory_identities["channels"]
                if _stable_identity(channels.identity) != pinned:
                    raise CredentialChannelEvidenceRefused(
                        "credential channel directory identity changed"
                    )
                try:
                    channels.readFile(name, max_bytes=_CHANNEL_BYTES_MAX)
                except FileNotFoundError:
                    pass
                except (OSError, ValueError) as exc:
                    raise CredentialChannelEvidenceRefused(
                        "credential channel absence is unobservable"
                    ) from exc
                else:
                    raise CredentialChannelEvidenceRefused(
                        "credential channel remains present"
                    )
                if _stable_identity(channels.identity) != pinned:
                    raise CredentialChannelEvidenceRefused(
                        "credential channel directory identity raced absence"
                    )
        except CredentialChannelEvidenceRefused:
            raise
        except OSError as exc:
            raise CredentialChannelEvidenceRefused(
                "credential channel absence is unobservable"
            ) from exc
        self._revalidate_directories()

    def observeDeleted(
        self,
        resource: object,
        intent: CredentialChannelDestructionIntent,
    ) -> CredentialChannelDeletedObservation:
        self._requireIssued()
        from platform_core.runtime.candidate import (
            CredentialResourceState,
            ResourceRole,
            RuntimeResourceLease,
        )

        if type(resource) is not RuntimeResourceLease:
            raise CredentialChannelEvidenceRefused(
                "credential deletion observation requires an exact runtime resource"
            )
        observed = cast(Any, resource)
        if (
            observed.role is not ResourceRole.CREDENTIAL_LEASE
            or observed.state
            not in {
                CredentialResourceState.REGISTERED,
                CredentialResourceState.REVOKED_OR_EXPIRED,
            }
            or observed.issuer_id != self._issuer_id
        ):
            raise CredentialChannelEvidenceRefused(
                "credential deletion observation resource differs"
            )
        if type(intent) is not CredentialChannelDestructionIntent:
            raise CredentialChannelEvidenceRefused(
                "credential deletion observation requires exact prepared intent"
            )
        _validate_intent_binding(intent, observed)
        self._revalidate_directories()
        if self._load_prepared_intent(observed) != intent:
            raise CredentialChannelEvidenceRefused(
                "prepared credential destruction intent changed"
            )
        self._terminal_intent_absent(observed)
        if self._broker_terminal_metadata_absent(observed) is not True:
            raise CredentialChannelEvidenceRefused(
                "credential broker terminal metadata already exists"
            )
        self._observe_channel_absent(observed)
        observed_at = _canonical_now(self._broker_now)
        if datetime.fromisoformat(observed_at) < datetime.fromisoformat(
            observed.updated_at
        ):
            raise CredentialChannelEvidenceRefused(
                "credential absence clock rollback predates resource state"
            )
        return CredentialChannelDeletedObservation(
            transaction_id=observed.transaction_id,
            resource_id=observed.resource_id,
            secret_channel_id=observed.secret_channel_id,
            issuer_id=observed.issuer_id,
            revocation_generation=observed.revocation_generation,
            cleanup_locator_digest=observed.cleanup_locator_digest,
            intent_digest=intent.intent_digest,
            observed_at=observed_at,
            absent=True,
            _verifier_identity=self._identity,
            _seal=self._seal,
        )

    def _requireDeletedObservation(
        self,
        observation: object,
        resource: Any,
    ) -> None:
        self._requireIssued()
        if type(observation) is not CredentialChannelDeletedObservation:
            raise CredentialChannelEvidenceRefused(
                "terminal destruction requires exact fresh absence observation"
            )
        exact = cast(Any, observation)
        if (
            exact._verifier_identity != self._identity
            or exact._seal is not self._seal
            or exact.transaction_id != resource.transaction_id
            or exact.resource_id != resource.resource_id
            or exact.secret_channel_id != resource.secret_channel_id
            or exact.issuer_id != resource.issuer_id
            or exact.revocation_generation != resource.revocation_generation
            or exact.cleanup_locator_digest != resource.cleanup_locator_digest
            or exact.intent_digest != _intent_digest(resource)
            or exact.absent is not True
        ):
            raise CredentialChannelEvidenceRefused(
                "fresh credential absence observation binding differs"
            )

    def verifyTransition(
        self,
        resource: object,
        receipt: CredentialChannelDestructionReceipt,
    ) -> CredentialChannelAbsenceObservation:
        self._requireIssued()
        from platform_core.runtime.candidate import (
            CredentialResourceState,
            ResourceRole,
            RuntimeResourceLease,
        )

        if type(resource) is not RuntimeResourceLease:
            raise CredentialChannelEvidenceRefused(
                "credential terminal transition requires an exact runtime resource"
            )
        observed = cast(Any, resource)
        if type(receipt) is not CredentialChannelDestructionReceipt:
            raise CredentialChannelEvidenceRefused(
                "credential terminal transition requires an exact receipt"
            )
        if observed.state is CredentialResourceState.DESTROYED:
            observation = self.verify(observed)
            if observation.receipt_digest != receipt.receipt_digest:
                raise CredentialChannelEvidenceRefused(
                    "credential terminal replay receipt differs"
                )
            return observation
        if (
            observed.role is not ResourceRole.CREDENTIAL_LEASE
            or observed.state
            not in {
                CredentialResourceState.REGISTERED,
                CredentialResourceState.REVOKED_OR_EXPIRED,
            }
            or observed.issuer_id != self._issuer_id
        ):
            raise CredentialChannelEvidenceRefused(
                "credential terminal transition resource differs"
            )
        _validate_static_receipt_binding(receipt, observed)
        _validate_terminal_chronology(receipt, observed)
        self._revalidate_directories()
        if self._load_digest(receipt.receipt_digest) != receipt:
            raise CredentialChannelEvidenceRefused(
                "credential terminal receipt changed"
            )
        self._load_prepared_intent(observed)
        terminal = self._load_terminal_intent_static(observed)
        if terminal != receipt:
            raise CredentialChannelEvidenceRefused(
                "terminal credential destruction intent differs from its receipt"
            )
        if self._broker_terminal_metadata_exact(observed, receipt) is not True:
            raise CredentialChannelEvidenceRefused(
                "credential broker terminal metadata differs"
            )
        self._observe_channel_absent(observed)
        observed_at = _canonical_now(self._broker_now)
        if datetime.fromisoformat(observed_at) < datetime.fromisoformat(
            receipt.destroyed_at
        ):
            raise CredentialChannelEvidenceRefused(
                "credential absence observation predates destruction"
            )
        return CredentialChannelAbsenceObservation(
            transaction_id=receipt.transaction_id,
            resource_id=receipt.resource_id,
            secret_channel_id=receipt.secret_channel_id,
            issuer_id=receipt.issuer_id,
            revocation_generation=receipt.revocation_generation,
            cleanup_locator_digest=receipt.cleanup_locator_digest,
            receipt_digest=receipt.receipt_digest,
            destroyed_at=receipt.destroyed_at,
            observed_at=observed_at,
            absent=True,
            _verifier_identity=self._identity,
            _seal=self._seal,
        )

    def _requireAbsenceObservation(
        self,
        observation: object,
        resource: Any,
        receipt: CredentialChannelDestructionReceipt,
    ) -> None:
        self._requireIssued()
        if type(observation) is not CredentialChannelAbsenceObservation:
            raise CredentialChannelEvidenceRefused(
                "credential terminal transition returned an untyped absence observation"
            )
        exact = cast(Any, observation)
        if (
            exact._verifier_identity != self._identity
            or exact._seal is not self._seal
            or exact.transaction_id != resource.transaction_id
            or exact.resource_id != resource.resource_id
            or exact.secret_channel_id != resource.secret_channel_id
            or exact.issuer_id != resource.issuer_id
            or exact.revocation_generation != resource.revocation_generation
            or exact.cleanup_locator_digest != resource.cleanup_locator_digest
            or exact.receipt_digest != receipt.receipt_digest
            or exact.destroyed_at != receipt.destroyed_at
            or exact.absent is not True
        ):
            raise CredentialChannelEvidenceRefused(
                "credential terminal absence observation binding differs"
            )

    def _load_terminal_intent_static(
        self,
        resource: Any,
    ) -> CredentialChannelDestructionReceipt:
        try:
            raw = readNoFollowBytes(
                self._intents / _terminal_intent_name(resource),
                max_bytes=_MAX_RECEIPT_BYTES,
            )
        except (OSError, ValueError) as exc:
            raise CredentialChannelEvidenceRefused(
                "terminal credential destruction intent is unavailable"
            ) from exc
        receipt = CredentialChannelDestructionReceipt.fromBytes(raw)
        _validate_static_receipt_binding(receipt, resource)
        return receipt

    def verify(self, resource: object) -> CredentialChannelAbsenceObservation:
        self._requireIssued()
        from platform_core.runtime.candidate import (
            CredentialResourceState,
            ResourceRole,
            RuntimeResourceLease,
        )

        if type(resource) is not RuntimeResourceLease:
            raise CredentialChannelEvidenceRefused(
                "credential absence requires an exact typed runtime resource"
            )
        observed_resource = cast(Any, resource)
        if (
            observed_resource.role is not ResourceRole.CREDENTIAL_LEASE
            or observed_resource.state is not CredentialResourceState.DESTROYED
        ):
            raise CredentialChannelEvidenceRefused(
                "credential absence requires a DESTROYED credential resource"
            )
        if observed_resource.issuer_id != self._issuer_id:
            raise CredentialChannelEvidenceRefused(
                "credential absence verifier issuer differs"
            )
        self._revalidate_directories()
        receipt = self._load(observed_resource)
        self._load_prepared_intent(observed_resource)
        if self._load_terminal_intent(observed_resource) != receipt:
            raise CredentialChannelEvidenceRefused(
                "terminal credential destruction intent differs from its receipt"
            )
        if self._broker_terminal_metadata_exact(observed_resource, receipt) is not True:
            raise CredentialChannelEvidenceRefused(
                "credential broker terminal metadata differs"
            )
        name = _channel_name(observed_resource.secret_channel_id)
        try:
            with openNativeDirectory(self._channels) as channels:
                channels.readFile(name, max_bytes=_CHANNEL_BYTES_MAX)
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            raise CredentialChannelEvidenceRefused(
                "credential channel absence is unobservable"
            ) from exc
        else:
            raise CredentialChannelEvidenceRefused(
                "credential channel remains present"
            )
        if self._load(observed_resource) != receipt:
            raise CredentialChannelEvidenceRefused(
                "credential destruction receipt changed during absence observation"
            )
        self._revalidate_directories()
        observed_at = _canonical_now(self._broker_now)
        if datetime.fromisoformat(observed_at) < datetime.fromisoformat(
            receipt.destroyed_at
        ):
            raise CredentialChannelEvidenceRefused(
                "credential absence observation predates destruction"
            )
        return CredentialChannelAbsenceObservation(
            transaction_id=receipt.transaction_id,
            resource_id=receipt.resource_id,
            secret_channel_id=receipt.secret_channel_id,
            issuer_id=receipt.issuer_id,
            revocation_generation=receipt.revocation_generation,
            cleanup_locator_digest=receipt.cleanup_locator_digest,
            receipt_digest=receipt.receipt_digest,
            destroyed_at=receipt.destroyed_at,
            observed_at=observed_at,
            absent=True,
            _verifier_identity=self._identity,
            _seal=self._seal,
        )

def _createCredentialChannelDestroyer(
    *,
    broker: object,
    absence_verifier: CredentialChannelAbsenceVerifier,
    coordinator: object,
    resource: object,
) -> CredentialChannelDestroyer:
    destroyer = CredentialChannelDestroyer(
        broker=broker,
        absence_verifier=absence_verifier,
        coordinator=coordinator,
        resource=resource,
        _factory=_FACTORY_TOKEN,
    )
    _register_channel_object(
        destroyer,
        broker=destroyer._broker,
        seal=destroyer._seal,
        kind="destroyer",
    )
    return destroyer


def _createCredentialChannelAbsenceVerifier(
    *,
    broker: object,
) -> CredentialChannelAbsenceVerifier:
    verifier = CredentialChannelAbsenceVerifier(
        broker=broker,
        _factory=_FACTORY_TOKEN,
    )
    _register_channel_object(
        verifier,
        broker=verifier._broker,
        seal=verifier._seal,
        kind="verifier",
    )
    return verifier


__all__ = [
    "CredentialChannelAbsenceObservation",
    "CredentialChannelDeletedObservation",
    "CredentialChannelAbsenceVerifier",
    "CredentialChannelDestructionReceipt",
    "CredentialChannelDestroyer",
    "CredentialChannelEvidenceRefused",
]
