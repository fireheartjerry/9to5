"""Non-secret durable credential lease planning and in-memory issuance.

Durable records contain only cleanup and digest metadata.  Credential bytes are
held in a private bytearray, can never be serialized through the public record,
and are zeroed on revocation.

RUN/TEST: python -m pytest tests/execution/test_credential_broker.py
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, cast

from platform_core.core.fsio import (
    durableAtomicReplaceBytes,
    exclusiveCreateBytes,
    fileLock,
    readNoFollowBytes,
)
from platform_core.execution.pre_execution import (
    observeLegacyPath,
)
from platform_core.runtime.candidate import (
    CredentialResourceState,
    ResourceRole,
    RuntimeResourceLease,
    processStartToken,
    validateRuntimeResourceRegistration,
)
from platform_core.runtime.attempt_journal import (
    AttemptJournal,
    AttemptPersistenceAuthorityRefused,
    _CredentialJournalCoordinator,
)
from platform_core.runtime.credential_channel import (
    CredentialChannelAbsenceVerifier,
    CredentialChannelDestructionReceipt,
    CredentialChannelDestroyer,
    CredentialChannelEvidenceRefused,
    _channel_name,
    _createCredentialChannelAbsenceVerifier,
    _createCredentialChannelDestroyer,
)

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_STATES = frozenset(
    {"registered", "issued", "injected", "revoked_or_expired", "destroyed"}
)


class CredentialBrokerRefused(RuntimeError):
    """Credential issuance cannot prove its exact authority and cleanup scope."""


@dataclass(frozen=True, slots=True)
class _IssuedBrokerJournalAuthority:
    authority: object
    broker: object
    broker_seal: object
    normalized_root: str


_BROKER_JOURNAL_AUTHORITIES_LOCK = threading.RLock()
_BROKER_JOURNAL_AUTHORITIES: dict[int, _IssuedBrokerJournalAuthority] = {}


def _validateCredentialBrokerJournalAuthority(
    *,
    broker: object,
    authority: object,
    broker_root: str,
) -> bool:
    with _BROKER_JOURNAL_AUTHORITIES_LOCK:
        issued = _BROKER_JOURNAL_AUTHORITIES.get(id(authority))
    return bool(
        issued is not None
        and issued.authority is authority
        and issued.broker is broker
        and getattr(broker, "_seal", None) is issued.broker_seal
        and issued.normalized_root == broker_root
    )


def _time(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise CredentialBrokerRefused("credential timestamp is invalid") from exc
    if result.tzinfo is None:
        raise CredentialBrokerRefused("credential timestamp is not absolute")
    return result.astimezone(timezone.utc)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _credentialLockOwnerAlive(pid: int) -> bool:
    """Return False only when the native process-birth probe proves no owner."""

    try:
        return processStartToken(pid) is not None
    except Exception:  # noqa: BLE001 - an unavailable liveness oracle is unknown
        return True


def _metadata_name(lease_id: str) -> str:
    """Keep logical identifiers out of Windows path-component syntax."""

    if not isinstance(lease_id, str) or not _ID.fullmatch(lease_id):
        raise CredentialBrokerRefused("lease_id is invalid")
    return hashlib.sha256(lease_id.encode("utf-8")).hexdigest() + ".json"


def _closed_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("credential metadata contains a duplicate key")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class CredentialLeaseMetadata:
    lease_id: str
    transaction_id: str
    provider: str
    state: str
    channel_locator_digest: str
    issued_at: str
    expires_at: str
    auth_mode: str = ""
    secret_channel_id: str = ""
    secret_fingerprint: str = ""
    issuer_id: str = ""
    revocation_generation: int = 0
    destruction_receipt_digest: str = ""
    destroyed_at: str = ""
    holder_pid: int = 0
    holder_start_token: str = ""

    def __post_init__(self) -> None:
        for value, name in ((self.lease_id, "lease_id"), (self.transaction_id, "transaction_id")):
            if not isinstance(value, str) or not _ID.fullmatch(value):
                raise CredentialBrokerRefused(f"{name} is invalid")
        if self.provider not in {"claude", "codex"}:
            raise CredentialBrokerRefused("provider is unavailable")
        if self.state not in _STATES:
            raise CredentialBrokerRefused("credential state is invalid")
        if not _DIGEST.fullmatch(self.channel_locator_digest):
            raise CredentialBrokerRefused("channel locator digest is invalid")
        if _time(self.expires_at) <= _time(self.issued_at):
            raise CredentialBrokerRefused("credential expiry must follow issuance")
        for value, name in (
            (self.auth_mode, "auth_mode"),
            (self.secret_channel_id, "secret_channel_id"),
            (self.issuer_id, "issuer_id"),
        ):
            if not isinstance(value, str) or not _ID.fullmatch(value):
                raise CredentialBrokerRefused(f"{name} is invalid")
        if (
            type(self.revocation_generation) is not int
            or self.revocation_generation < 1
        ):
            raise CredentialBrokerRefused("revocation_generation is invalid")
        if self.secret_fingerprint and not _DIGEST.fullmatch(self.secret_fingerprint):
            raise CredentialBrokerRefused("secret fingerprint is invalid")
        if self.state in {"issued", "injected"} and not self.secret_fingerprint:
            raise CredentialBrokerRefused(
                "materialized credential requires a secret fingerprint"
            )
        if self.state in {"issued", "injected"}:
            if (
                type(self.holder_pid) is not int
                or self.holder_pid <= 0
                or type(self.holder_start_token) is not str
                or not self.holder_start_token
                or len(self.holder_start_token) > 512
            ):
                raise CredentialBrokerRefused(
                    "materialized credential requires an exact process holder"
                )
        elif self.holder_pid or self.holder_start_token:
            if (
                type(self.holder_pid) is not int
                or self.holder_pid <= 0
                or type(self.holder_start_token) is not str
                or not self.holder_start_token
                or len(self.holder_start_token) > 512
            ):
                raise CredentialBrokerRefused("credential process holder is invalid")
        terminal = bool(self.destruction_receipt_digest or self.destroyed_at)
        if self.state == "destroyed":
            if (
                not _DIGEST.fullmatch(self.destruction_receipt_digest)
                or not self.destroyed_at
            ):
                raise CredentialBrokerRefused(
                    "destroyed credential requires exact destruction evidence"
                )
            _time(self.destroyed_at)
        elif terminal:
            raise CredentialBrokerRefused(
                "credential destruction evidence is terminal-only"
            )

    def toDict(self) -> dict[str, object]:
        return {
            "channel_locator_digest": self.channel_locator_digest,
            "expires_at": self.expires_at,
            "auth_mode": self.auth_mode,
            "destruction_receipt_digest": self.destruction_receipt_digest,
            "destroyed_at": self.destroyed_at,
            "issued_at": self.issued_at,
            "issuer_id": self.issuer_id,
            "holder_pid": self.holder_pid,
            "holder_start_token": self.holder_start_token,
            "lease_id": self.lease_id,
            "provider": self.provider,
            "revocation_generation": self.revocation_generation,
            "secret_channel_id": self.secret_channel_id,
            "secret_fingerprint": self.secret_fingerprint,
            "state": self.state,
            "transaction_id": self.transaction_id,
        }


@dataclass(frozen=True, slots=True)
class CredentialIssueAuthority:
    transaction_id: str
    provider: str
    deadline: str
    resource_id: str
    secret_channel_id: str
    resource_contract_digest: str
    _issuer_identity: int
    _seal: object


@dataclass(slots=True)
class _IssuedCredentialAuthority:
    authority: CredentialIssueAuthority
    resource: RuntimeResourceLease
    resource_contract_digest: str
    coordinator: _CredentialJournalCoordinator
    lease: CredentialLease | None = None


class CredentialLease:
    """One non-serializable in-memory credential plus durable public metadata."""

    __slots__ = ("_metadata", "_secret")

    def __init__(self, metadata: CredentialLeaseMetadata, secret: bytes) -> None:
        self._metadata = metadata
        self._secret = bytearray(secret)

    @property
    def metadata(self) -> CredentialLeaseMetadata:
        return self._metadata

    def secretView(self) -> memoryview:
        if self.metadata.state in {"revoked_or_expired", "destroyed"} or not self._secret:
            raise CredentialBrokerRefused("credential lease is no longer live")
        return memoryview(self._secret).toreadonly()

    def _destroy(self) -> None:
        for index in range(len(self._secret)):
            self._secret[index] = 0


@dataclass(slots=True)
class _IssuedCredentialLease:
    lease: CredentialLease
    broker: object
    broker_seal: object
    normalized_root: str
    resource: RuntimeResourceLease
    resource_contract_digest: str
    coordinator: _CredentialJournalCoordinator
    metadata: CredentialLeaseMetadata


_CREDENTIAL_LEASES_LOCK = threading.RLock()
_CREDENTIAL_LEASES: dict[int, _IssuedCredentialLease] = {}
_CREDENTIAL_HOLDERS: dict[tuple[str, str], dict[int, _IssuedCredentialLease]] = {}


class CredentialBroker:
    def __init__(
        self,
        *,
        metadata_root: str | Path,
        secret_provider: Callable[[str], bytes],
        process_capability: object | None = None,
        attempt_journal: AttemptJournal | None = None,
        issuer_id: str = "diagnostic-credential-broker",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._root = Path(metadata_root)
        self._secret_provider = secret_provider
        self._process_capability = process_capability
        if attempt_journal is not None and type(attempt_journal) is not AttemptJournal:
            raise CredentialBrokerRefused("attempt_journal must be exact")
        self._attempt_journal = attempt_journal
        if not isinstance(issuer_id, str) or not _ID.fullmatch(issuer_id):
            raise CredentialBrokerRefused("issuer_id is invalid")
        self._issuer_id = issuer_id
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._identity = id(self)
        self._seal = object()
        self._journal_authority = object()
        normalized_root = os.path.normcase(os.path.abspath(self._root))
        with _BROKER_JOURNAL_AUTHORITIES_LOCK:
            _BROKER_JOURNAL_AUTHORITIES[id(self._journal_authority)] = (
                _IssuedBrokerJournalAuthority(
                    authority=self._journal_authority,
                    broker=self,
                    broker_seal=self._seal,
                    normalized_root=normalized_root,
                )
            )
        self._leases: dict[str, CredentialLease] = {}
        self._authorities: dict[int, _IssuedCredentialAuthority] = {}
        self._authority_by_resource: dict[
            tuple[str, str], CredentialIssueAuthority
        ] = {}
        self._coordinators: dict[
            tuple[str, str],
            _CredentialJournalCoordinator,
        ] = {}
        self._channel_guard = threading.RLock()
        self._absence_verifier: CredentialChannelAbsenceVerifier | None = None
        self._channel_destroyers: dict[
            tuple[str, str], CredentialChannelDestroyer
        ] = {}

    @contextmanager
    def _channelGuard(self) -> Iterator[None]:
        with self._channel_guard:
            self._ensureRoot()
            with fileLock(
                self._root / ".credential-channel.lock",
                timeout=30,
                owner_alive=_credentialLockOwnerAlive,
            ):
                self._ensureRoot()
                yield

    def _clockNow(self) -> datetime:
        return self._clock()

    def _requireChannelLifecycleBroker(self) -> None:
        """Prove this exact instance still owns its process-local broker seal."""

        normalized_root = os.path.normcase(os.path.abspath(self._root))
        if not _validateCredentialBrokerJournalAuthority(
            broker=self,
            authority=self._journal_authority,
            broker_root=normalized_root,
        ):
            raise CredentialBrokerRefused(
                "credential channel lifecycle broker authority differs"
            )
        if type(self._issuer_id) is not str or not _ID.fullmatch(self._issuer_id):
            raise CredentialBrokerRefused(
                "credential channel lifecycle broker issuer differs"
            )

    def _coordinator(
        self,
        resource: RuntimeResourceLease,
    ) -> _CredentialJournalCoordinator:
        journal = self._attempt_journal
        if type(journal) is not AttemptJournal:
            raise CredentialBrokerRefused(
                "credential operation requires an exact attempt journal"
            )
        key = (resource.transaction_id, resource.resource_id)
        existing = self._coordinators.get(key)
        if existing is not None:
            try:
                existing.current(resource)
            except AttemptPersistenceAuthorityRefused as exc:
                raise CredentialBrokerRefused(
                    "credential journal coordinator binding differs"
                ) from exc
            return existing
        try:
            coordinator = journal._createCredentialJournalCoordinator(
                resource=resource,
                broker=self,
                broker_authority=self._journal_authority,
                broker_root=self._root,
            )
        except (AttemptPersistenceAuthorityRefused, OSError, ValueError) as exc:
            raise CredentialBrokerRefused(
                "credential resource has no exact durable preregistration"
            ) from exc
        self._coordinators[key] = coordinator
        return coordinator

    def issueAuthority(
        self,
        *,
        process_capability: object,
        resource: RuntimeResourceLease,
        transaction_id: str,
        provider: str,
        deadline: str,
    ) -> CredentialIssueAuthority:
        if self._process_capability is None or process_capability is not self._process_capability:
            raise CredentialBrokerRefused("process capability differs")
        if not _ID.fullmatch(transaction_id):
            raise CredentialBrokerRefused("transaction_id is invalid")
        if provider not in {"claude", "codex"}:
            raise CredentialBrokerRefused("provider is unavailable")
        if type(resource) is not RuntimeResourceLease:
            raise CredentialBrokerRefused(
                "credential authority requires an exact registered resource"
            )
        try:
            validateRuntimeResourceRegistration(resource)
        except (TypeError, ValueError) as exc:
            raise CredentialBrokerRefused(
                "credential authority resource contract differs"
            ) from exc
        if (
            resource.transaction_id != transaction_id
            or resource.provider != provider
            or resource.expires_at != deadline
            or resource.issuer_id != self._issuer_id
        ):
            raise CredentialBrokerRefused("credential authority resource scope differs")
        if _time(deadline) <= self._clock().astimezone(timezone.utc):
            raise CredentialBrokerRefused("credential authority expired")
        coordinator = self._coordinator(resource)
        registration = coordinator.registration
        if registration != resource:
            raise CredentialBrokerRefused(
                "credential authority resource differs from durable preregistration"
            )
        contract_digest = coordinator.registration_contract_digest
        key = (resource.transaction_id, resource.resource_id)
        replay = self._authority_by_resource.get(key)
        if replay is not None:
            registered_authority = self._authorities.get(id(replay))
            if (
                registered_authority is None
                or registered_authority.authority is not replay
                or registered_authority.resource is not resource
                or replay.transaction_id != transaction_id
                or replay.provider != provider
                or replay.deadline != deadline
                or replay.resource_contract_digest != contract_digest
            ):
                raise CredentialBrokerRefused(
                    "credential authority replay binding differs"
                )
            return replay
        authority = CredentialIssueAuthority(
            transaction_id=transaction_id,
            provider=provider,
            deadline=deadline,
            resource_id=resource.resource_id,
            secret_channel_id=resource.secret_channel_id,
            resource_contract_digest=contract_digest,
            _issuer_identity=self._identity,
            _seal=self._seal,
        )
        self._authorities[id(authority)] = _IssuedCredentialAuthority(
            authority=authority,
            resource=resource,
            resource_contract_digest=contract_digest,
            coordinator=coordinator,
        )
        self._authority_by_resource[key] = authority
        return authority

    def _validate(
        self,
        authority: object,
        *,
        transaction_id: str,
        provider: str,
        deadline: str,
        resource: RuntimeResourceLease,
    ) -> CredentialIssueAuthority:
        if type(authority) is not CredentialIssueAuthority:
            raise CredentialBrokerRefused("exact process-local credential authority is required")
        assert isinstance(authority, CredentialIssueAuthority)
        registered = self._authorities.get(id(authority))
        if registered is None or registered.authority is not authority:
            raise CredentialBrokerRefused("credential authority binding is not exact")
        if authority._issuer_identity != self._identity or authority._seal is not self._seal:
            raise CredentialBrokerRefused("credential authority issuer differs")
        if authority.transaction_id != transaction_id or authority.provider != provider:
            raise CredentialBrokerRefused("credential authority scope differs")
        coordinator = registered.coordinator
        try:
            coordinator.current(resource)
        except AttemptPersistenceAuthorityRefused as exc:
            raise CredentialBrokerRefused(
                "credential authority durable binding differs"
            ) from exc
        contract_digest = coordinator.registration_contract_digest
        if (
            authority.resource_id != resource.resource_id
            or authority.secret_channel_id != resource.secret_channel_id
            or authority.resource_contract_digest != contract_digest
            or registered.resource is not resource
            or registered.resource_contract_digest != contract_digest
        ):
            raise CredentialBrokerRefused("credential authority resource binding differs")
        now = self._clock().astimezone(timezone.utc)
        if _time(authority.deadline) <= now or _time(deadline) <= now:
            raise CredentialBrokerRefused("credential authority expired")
        if _time(deadline) > _time(authority.deadline):
            raise CredentialBrokerRefused("credential deadline exceeds authority")
        return authority

    def _path(self, lease_id: str) -> Path:
        return self._root / _metadata_name(lease_id)

    def _channelPath(self, secret_channel_id: str) -> Path:
        if not isinstance(secret_channel_id, str) or not _ID.fullmatch(secret_channel_id):
            raise CredentialBrokerRefused("secret_channel_id is invalid")
        return self._root / "channels" / _channel_name(secret_channel_id)

    def _ensureRoot(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        if self._root.is_symlink() or not observeLegacyPath(self._root.is_dir):
            raise CredentialBrokerRefused("credential metadata root is unsafe")
        for name in ("channels", "destruction-receipts", "destruction-intents"):
            child = self._root / name
            child.mkdir(exist_ok=True)
            if child.is_symlink() or not observeLegacyPath(child.is_dir):
                raise CredentialBrokerRefused("credential store child is unsafe")
            if os.name != "nt":
                child.chmod(0o700)
        if os.name != "nt":
            self._root.chmod(0o700)

    def _persist(self, metadata: CredentialLeaseMetadata, *, create: bool = False) -> None:
        payload = _canonical(metadata.toDict())
        path = self._path(metadata.lease_id)
        if create:
            exclusiveCreateBytes(path, payload)
        else:
            durableAtomicReplaceBytes(path, payload)
        if os.name != "nt":
            path.chmod(0o600)

    def _loadMetadata(self, resource_id: str) -> CredentialLeaseMetadata:
        try:
            raw = readNoFollowBytes(self._path(resource_id), max_bytes=16 * 1024)
            payload = json.loads(
                raw.decode("utf-8", errors="strict"),
                object_pairs_hook=_closed_object,
            )
            if not isinstance(payload, dict) or _canonical(payload) != raw:
                raise ValueError("credential metadata is not canonical")
            metadata = CredentialLeaseMetadata(**payload)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise CredentialBrokerRefused(
                "credential metadata is unavailable or malformed"
            ) from exc
        if metadata.lease_id != resource_id:
            raise CredentialBrokerRefused("credential metadata identity differs")
        return metadata

    def _metadataMatchesResource(
        self,
        metadata: CredentialLeaseMetadata,
        resource: RuntimeResourceLease,
    ) -> bool:
        return bool(
            metadata.lease_id == resource.resource_id
            and metadata.transaction_id == resource.transaction_id
            and metadata.provider == resource.provider
            and metadata.channel_locator_digest == resource.cleanup_locator_digest
            and metadata.expires_at == resource.expires_at
            and metadata.auth_mode == resource.auth_mode
            and metadata.secret_channel_id == resource.secret_channel_id
            and metadata.issuer_id == resource.issuer_id == self._issuer_id
            and metadata.revocation_generation == resource.revocation_generation
        )

    @staticmethod
    def _holderIsLive(metadata: CredentialLeaseMetadata) -> bool:
        if metadata.holder_pid <= 0 or not metadata.holder_start_token:
            return False
        try:
            return processStartToken(metadata.holder_pid) == metadata.holder_start_token
        except (OSError, ValueError):
            return False

    def _registerLease(
        self,
        *,
        lease: CredentialLease,
        resource: RuntimeResourceLease,
        coordinator: _CredentialJournalCoordinator,
    ) -> None:
        binding = _IssuedCredentialLease(
            lease=lease,
            broker=self,
            broker_seal=self._seal,
            normalized_root=os.path.normcase(os.path.abspath(self._root)),
            resource=resource,
            resource_contract_digest=coordinator.registration_contract_digest,
            coordinator=coordinator,
            metadata=lease.metadata,
        )
        key = (binding.normalized_root, resource.resource_id)
        with _CREDENTIAL_LEASES_LOCK:
            _CREDENTIAL_LEASES[id(lease)] = binding
            _CREDENTIAL_HOLDERS.setdefault(key, {})[id(lease)] = binding
        self._leases[resource.resource_id] = lease

    def _requireLease(self, lease: object) -> _IssuedCredentialLease:
        if type(lease) is not CredentialLease:
            raise CredentialBrokerRefused("exact broker-issued credential lease is required")
        assert isinstance(lease, CredentialLease)
        with _CREDENTIAL_LEASES_LOCK:
            binding = _CREDENTIAL_LEASES.get(id(lease))
        if (
            binding is None
            or binding.lease is not lease
            or binding.broker is not self
            or binding.broker_seal is not self._seal
            or binding.normalized_root
            != os.path.normcase(os.path.abspath(self._root))
            or binding.metadata != lease.metadata
            or self._leases.get(binding.resource.resource_id) is not lease
            or binding.resource_contract_digest
            != binding.coordinator.registration_contract_digest
        ):
            raise CredentialBrokerRefused("credential lease ownership binding differs")
        current = self._loadMetadata(binding.resource.resource_id)
        if current != binding.metadata:
            raise CredentialBrokerRefused(
                "credential lease differs from fresh durable broker state"
            )
        try:
            binding.coordinator.current(binding.resource)
        except AttemptPersistenceAuthorityRefused as exc:
            raise CredentialBrokerRefused(
                "credential lease durable journal binding differs"
            ) from exc
        return binding

    def _updateHolders(self, metadata: CredentialLeaseMetadata) -> None:
        key = (
            os.path.normcase(os.path.abspath(self._root)),
            metadata.lease_id,
        )
        with _CREDENTIAL_LEASES_LOCK:
            holders = tuple(_CREDENTIAL_HOLDERS.get(key, {}).values())
            for binding in holders:
                if (
                    binding.normalized_root != key[0]
                    or binding.resource.resource_id != metadata.lease_id
                    or not self._metadataMatchesResource(metadata, binding.resource)
                ):
                    raise CredentialBrokerRefused(
                        "credential holder registry binding differs"
                    )
                binding.metadata = metadata
                object.__setattr__(binding.lease, "_metadata", metadata)

    def _zeroHolders(self, metadata: CredentialLeaseMetadata) -> None:
        key = (
            os.path.normcase(os.path.abspath(self._root)),
            metadata.lease_id,
        )
        if self._holderIsLive(metadata) and metadata.holder_pid != os.getpid():
            raise CredentialBrokerRefused(
                "credential bytes remain live in another exact process holder"
            )
        with _CREDENTIAL_LEASES_LOCK:
            holders = tuple(_CREDENTIAL_HOLDERS.get(key, {}).values())
            if (
                self._holderIsLive(metadata)
                and metadata.holder_pid == os.getpid()
                and not holders
            ):
                raise CredentialBrokerRefused(
                    "credential process holder cannot be zeroed exactly"
                )
            for binding in holders:
                if (
                    binding.normalized_root != key[0]
                    or binding.resource.resource_id != metadata.lease_id
                    or binding.metadata.secret_fingerprint
                    != metadata.secret_fingerprint
                ):
                    raise CredentialBrokerRefused(
                        "credential holder registry binding differs"
                    )
                binding.lease._destroy()

    def issue(
        self,
        *,
        resource: RuntimeResourceLease | None = None,
        transaction_id: str = "",
        provider: str = "",
        deadline: str = "",
        authority: object,
    ) -> CredentialLease:
        self._validateIssueRequest(
            resource=resource,
            transaction_id=transaction_id,
            provider=provider,
            deadline=deadline,
            authority=authority,
        )
        with self._channelGuard():
            return self._issueLocked(
                resource=resource,
                transaction_id=transaction_id,
                provider=provider,
                deadline=deadline,
                authority=authority,
            )

    def _validateIssueRequest(
        self,
        *,
        resource: RuntimeResourceLease | None,
        transaction_id: str,
        provider: str,
        deadline: str,
        authority: object,
    ) -> RuntimeResourceLease:
        if type(resource) is not RuntimeResourceLease:
            raise CredentialBrokerRefused(
                "credential issuance requires an exact preregistered resource"
            )
        registered = cast(RuntimeResourceLease, resource)
        if (
            (transaction_id and transaction_id != registered.transaction_id)
            or (provider and provider != registered.provider)
            or (deadline and deadline != registered.expires_at)
        ):
            raise CredentialBrokerRefused(
                "credential issue request differs from its registered resource"
            )
        transaction_id = registered.transaction_id
        provider = registered.provider
        deadline = registered.expires_at
        self._validate(
            authority,
            transaction_id=transaction_id,
            provider=provider,
            deadline=deadline,
            resource=registered,
        )
        try:
            validateRuntimeResourceRegistration(registered)
        except (TypeError, ValueError) as exc:
            raise CredentialBrokerRefused(
                "credential registration contract differs"
            ) from exc
        if (
            registered.role is not ResourceRole.CREDENTIAL_LEASE
            or registered.state is not CredentialResourceState.REGISTERED
            or registered.issuer_id != self._issuer_id
        ):
            raise CredentialBrokerRefused("credential registration authority differs")
        return registered

    def _issueLocked(
        self,
        *,
        resource: RuntimeResourceLease | None = None,
        transaction_id: str = "",
        provider: str = "",
        deadline: str = "",
        authority: object,
    ) -> CredentialLease:
        registered = self._validateIssueRequest(
            resource=resource,
            transaction_id=transaction_id,
            provider=provider,
            deadline=deadline,
            authority=authority,
        )
        transaction_id = registered.transaction_id
        provider = registered.provider
        deadline = registered.expires_at
        authority_record = self._authorities.get(id(authority))
        if authority_record is None or authority_record.authority is not authority:
            raise CredentialBrokerRefused("credential authority binding is not exact")
        if authority_record.lease is not None:
            binding = self._requireLease(authority_record.lease)
            if binding.resource is not registered:
                raise CredentialBrokerRefused(
                    "credential authority replay resource differs"
                )
            try:
                authority_record.coordinator.commitIssued(
                    registered,
                    secret_fingerprint=binding.metadata.secret_fingerprint,
                )
            except AttemptPersistenceAuthorityRefused as exc:
                raise CredentialBrokerRefused(
                    "credential issued journal reconciliation refused"
                ) from exc
            return authority_record.lease
        issued = self._clock().astimezone(timezone.utc).isoformat()
        metadata = CredentialLeaseMetadata(
            lease_id=registered.resource_id,
            transaction_id=transaction_id,
            provider=provider,
            state="registered",
            channel_locator_digest=registered.cleanup_locator_digest,
            issued_at=issued,
            expires_at=deadline,
            auth_mode=registered.auth_mode,
            secret_channel_id=registered.secret_channel_id,
            issuer_id=registered.issuer_id,
            revocation_generation=registered.revocation_generation,
        )
        self._ensureRoot()
        try:
            self._persist(metadata, create=True)
        except FileExistsError:
            metadata = self._loadMetadata(registered.resource_id)
            if not self._metadataMatchesResource(metadata, registered):
                raise CredentialBrokerRefused(
                    "credential durable registration binding differs"
                )
            if metadata.state in {"revoked_or_expired", "destroyed", "injected"}:
                raise CredentialBrokerRefused(
                    "credential durable state cannot be issued"
                )
            if self._holderIsLive(metadata) and metadata.holder_pid != os.getpid():
                raise CredentialBrokerRefused(
                    "credential is retained by another live process"
                )
        raw_buffer: bytearray | None = None
        try:
            channel_path = self._channelPath(registered.secret_channel_id)
            try:
                raw = readNoFollowBytes(channel_path, max_bytes=65_536)
            except FileNotFoundError:
                raw = b""
            except (OSError, ValueError) as exc:
                raise CredentialBrokerRefused(
                    "credential secret channel is unavailable"
                ) from exc
            if raw:
                if (
                    metadata.state == "issued"
                    and hashlib.sha256(raw).hexdigest()
                    != metadata.secret_fingerprint
                ):
                    raise CredentialBrokerRefused(
                        "credential secret channel fingerprint differs"
                    )
            elif metadata.state == "issued":
                raise CredentialBrokerRefused(
                    "issued credential secret channel is missing"
                )
            else:
                raw = self._secret_provider(provider)
                if type(raw) is not bytes or not raw or len(raw) > 65_536:
                    raise CredentialBrokerRefused(
                        "credential provider returned invalid secret bytes"
                    )
            raw_buffer = bytearray(raw)
            if metadata.state == "registered" and not channel_path.exists():
                try:
                    exclusiveCreateBytes(channel_path, bytes(raw_buffer))
                except OSError as exc:
                    raise CredentialBrokerRefused(
                        "credential secret channel could not be materialized"
                    ) from exc
            if os.name != "nt":
                channel_path.chmod(0o600)
            holder_token = processStartToken(os.getpid())
            if not holder_token:
                raise CredentialBrokerRefused(
                    "credential process holder cannot be identified"
                )
            metadata = replace(
                metadata,
                state="issued",
                secret_fingerprint=hashlib.sha256(raw).hexdigest(),
                holder_pid=os.getpid(),
                holder_start_token=holder_token,
            )
            self._persist(metadata)
            lease = CredentialLease(metadata, raw)
            self._registerLease(
                lease=lease,
                resource=registered,
                coordinator=authority_record.coordinator,
            )
            authority_record.lease = lease
            try:
                authority_record.coordinator.commitIssued(
                    registered,
                    secret_fingerprint=metadata.secret_fingerprint,
                )
            except AttemptPersistenceAuthorityRefused as exc:
                raise CredentialBrokerRefused(
                    "credential issued journal reconciliation refused"
                ) from exc
            for index in range(len(raw_buffer)):
                raw_buffer[index] = 0
            return lease
        except BaseException:
            if raw_buffer is not None:
                for index in range(len(raw_buffer)):
                    raw_buffer[index] = 0
                raw_buffer.clear()
            raise

    def markInjected(self, lease: CredentialLease) -> None:
        with self._channelGuard():
            self._markInjectedLocked(lease)

    def _markInjectedLocked(self, lease: CredentialLease) -> None:
        binding = self._requireLease(lease)
        if binding.metadata.state not in {"issued", "injected"}:
            raise CredentialBrokerRefused("credential lease is not issuable")
        if binding.metadata.state == "issued":
            updated = replace(binding.metadata, state="injected")
            self._persist(updated)
            self._updateHolders(updated)
        try:
            binding.coordinator.commitInjected(binding.resource)
        except AttemptPersistenceAuthorityRefused as exc:
            raise CredentialBrokerRefused(
                "credential injected journal reconciliation refused"
            ) from exc

    def revoke(self, lease: CredentialLease) -> None:
        with self._channelGuard():
            self._revokeLocked(lease)

    def _revokeLocked(self, lease: CredentialLease) -> None:
        binding = self._requireLease(lease)
        if binding.metadata.state not in {
            "issued",
            "injected",
            "revoked_or_expired",
        }:
            raise CredentialBrokerRefused("credential lease is not revocable")
        self._zeroHolders(binding.metadata)
        if binding.metadata.state != "revoked_or_expired":
            updated = replace(
                binding.metadata,
                state="revoked_or_expired",
                holder_pid=0,
                holder_start_token="",
            )
            self._persist(updated)
            self._updateHolders(updated)
        try:
            binding.coordinator.commitRevoked(binding.resource)
        except AttemptPersistenceAuthorityRefused as exc:
            raise CredentialBrokerRefused(
                "credential revoked journal reconciliation refused"
            ) from exc

    def _zeroSecret(self, resource_id: str) -> None:
        try:
            metadata = self._loadMetadata(resource_id)
        except CredentialBrokerRefused:
            key = (
                os.path.normcase(os.path.abspath(self._root)),
                resource_id,
            )
            with _CREDENTIAL_LEASES_LOCK:
                holders = tuple(_CREDENTIAL_HOLDERS.get(key, {}).values())
            if self._path(resource_id).exists() or holders:
                raise
            return
        self._zeroHolders(metadata)

    def _markRevoked(self, resource: object) -> None:
        if type(resource) is not RuntimeResourceLease:
            raise CredentialBrokerRefused(
                "credential revocation metadata requires an exact resource"
            )
        observed = cast(RuntimeResourceLease, resource)
        if (
            observed.role is not ResourceRole.CREDENTIAL_LEASE
            or observed.issuer_id != self._issuer_id
            or observed.state
            not in {
                CredentialResourceState.REGISTERED,
                CredentialResourceState.ISSUED,
                CredentialResourceState.INJECTED,
                CredentialResourceState.REVOKED_OR_EXPIRED,
            }
        ):
            raise CredentialBrokerRefused(
                "credential revocation metadata authority differs"
            )
        tombstone = CredentialLeaseMetadata(
            lease_id=observed.resource_id,
            transaction_id=observed.transaction_id,
            provider=observed.provider,
            state="revoked_or_expired",
            channel_locator_digest=observed.cleanup_locator_digest,
            issued_at=observed.created_at,
            expires_at=observed.expires_at,
            auth_mode=observed.auth_mode,
            secret_channel_id=observed.secret_channel_id,
            secret_fingerprint=observed.secret_fingerprint,
            issuer_id=observed.issuer_id,
            revocation_generation=observed.revocation_generation,
        )
        try:
            self._persist(tombstone, create=True)
            return
        except FileExistsError:
            current = self._loadMetadata(observed.resource_id)
        except OSError as exc:
            raise CredentialBrokerRefused(
                "credential revocation tombstone could not be persisted"
            ) from exc
        exact = (
            current.transaction_id == observed.transaction_id
            and current.provider == observed.provider
            and current.auth_mode == observed.auth_mode
            and current.secret_channel_id == observed.secret_channel_id
            and current.issuer_id == observed.issuer_id == self._issuer_id
            and current.revocation_generation == observed.revocation_generation
            and current.channel_locator_digest == observed.cleanup_locator_digest
            and current.secret_fingerprint == observed.secret_fingerprint
        )
        if not exact or current.state not in {
            "registered",
            "issued",
            "injected",
            "revoked_or_expired",
        }:
            raise CredentialBrokerRefused(
                "credential revocation metadata binding differs"
            )
        if current.state != "revoked_or_expired":
            current = replace(
                current,
                state="revoked_or_expired",
                holder_pid=0,
                holder_start_token="",
            )
            self._persist(current)
        self._updateHolders(current)

    def _markDestroyed(
        self,
        resource: object,
        receipt: CredentialChannelDestructionReceipt,
    ) -> None:
        if type(resource) is not RuntimeResourceLease:
            raise CredentialBrokerRefused(
                "credential destruction metadata requires an exact resource"
            )
        observed_resource = cast(Any, resource)
        current = self._loadMetadata(observed_resource.resource_id)
        exact = (
            current.transaction_id == observed_resource.transaction_id
            and current.provider == observed_resource.provider
            and current.auth_mode == observed_resource.auth_mode
            and current.secret_channel_id == observed_resource.secret_channel_id
            and current.issuer_id == observed_resource.issuer_id == self._issuer_id
            and current.revocation_generation == observed_resource.revocation_generation
            and current.channel_locator_digest == observed_resource.cleanup_locator_digest
            and current.secret_fingerprint == observed_resource.secret_fingerprint
            and receipt.transaction_id == observed_resource.transaction_id
            and receipt.resource_id == observed_resource.resource_id
            and receipt.secret_channel_id == observed_resource.secret_channel_id
            and receipt.issuer_id == observed_resource.issuer_id
            and receipt.revocation_generation == observed_resource.revocation_generation
            and receipt.cleanup_locator_digest == observed_resource.cleanup_locator_digest
        )
        if not exact:
            raise CredentialBrokerRefused(
                "credential destruction metadata binding differs"
            )
        # AJ15c(b): terminal broker truth does not rest on the receipt alone.
        # Re-prove channel absence here, independently of the journal fence that
        # allowed this call, so a channel that came back cannot be recorded as
        # destroyed.
        try:
            channel_present = self._channelPath(
                observed_resource.secret_channel_id
            ).exists()
        except OSError as exc:
            raise CredentialBrokerRefused(
                "credential channel absence is unobservable"
            ) from exc
        if channel_present:
            raise CredentialBrokerRefused(
                "credential channel remains present at terminal destruction"
            )
        if current.state == "destroyed":
            if (
                current.destruction_receipt_digest != receipt.receipt_digest
                or current.destroyed_at != receipt.destroyed_at
            ):
                raise CredentialBrokerRefused(
                    "credential destruction metadata collision"
                )
            self._updateHolders(current)
            self._leases.pop(current.lease_id, None)
            return
        terminal = replace(
            current,
            state="destroyed",
            destruction_receipt_digest=receipt.receipt_digest,
            destroyed_at=receipt.destroyed_at,
        )
        self._persist(terminal)
        self._updateHolders(terminal)
        self._leases.pop(terminal.lease_id, None)

    def _loadTerminalReceipt(
        self,
        resource: object,
    ) -> CredentialChannelDestructionReceipt | None:
        if type(resource) is not RuntimeResourceLease:
            raise CredentialBrokerRefused(
                "credential terminal receipt requires an exact resource"
            )
        observed_resource = cast(Any, resource)
        current = self._loadMetadata(observed_resource.resource_id)
        if current.state != "destroyed":
            return None
        if not (
            current.transaction_id == observed_resource.transaction_id
            and current.provider == observed_resource.provider
            and current.auth_mode == observed_resource.auth_mode
            and current.secret_channel_id == observed_resource.secret_channel_id
            and current.issuer_id == observed_resource.issuer_id == self._issuer_id
            and current.revocation_generation == observed_resource.revocation_generation
            and current.channel_locator_digest == observed_resource.cleanup_locator_digest
            and current.secret_fingerprint == observed_resource.secret_fingerprint
        ):
            raise CredentialBrokerRefused(
                "credential terminal receipt metadata binding differs"
            )
        try:
            raw = readNoFollowBytes(
                self._root
                / "destruction-receipts"
                / f"{current.destruction_receipt_digest}.json",
                max_bytes=16 * 1024,
            )
            receipt = CredentialChannelDestructionReceipt.fromBytes(raw)
        except (OSError, ValueError, CredentialChannelEvidenceRefused) as exc:
            raise CredentialBrokerRefused(
                "credential terminal receipt is unavailable"
            ) from exc
        if (
            receipt.receipt_digest != current.destruction_receipt_digest
            or receipt.destroyed_at != current.destroyed_at
        ):
            raise CredentialBrokerRefused(
                "credential terminal receipt metadata differs"
            )
        return receipt

    def _terminalMetadataExact(
        self,
        resource: object,
        receipt: CredentialChannelDestructionReceipt,
    ) -> bool:
        if type(resource) is not RuntimeResourceLease:
            return False
        observed_resource = cast(Any, resource)
        try:
            current = self._loadMetadata(observed_resource.resource_id)
        except CredentialBrokerRefused:
            return False
        return bool(
            current.state == "destroyed"
            and current.transaction_id == observed_resource.transaction_id
            and current.provider == observed_resource.provider
            and current.auth_mode == observed_resource.auth_mode
            and current.secret_channel_id == observed_resource.secret_channel_id
            and current.issuer_id == observed_resource.issuer_id == self._issuer_id
            and current.revocation_generation == observed_resource.revocation_generation
            and current.channel_locator_digest == observed_resource.cleanup_locator_digest
            and current.secret_fingerprint == observed_resource.secret_fingerprint
            and current.destruction_receipt_digest == receipt.receipt_digest
            and current.destroyed_at == receipt.destroyed_at
        )

    def _terminalMetadataAbsent(self, resource: object) -> bool:
        if type(resource) is not RuntimeResourceLease:
            return False
        observed_resource = cast(Any, resource)
        try:
            current = self._loadMetadata(observed_resource.resource_id)
        except CredentialBrokerRefused:
            return False
        return bool(
            current.state != "destroyed"
            and not current.destruction_receipt_digest
            and not current.destroyed_at
            and current.transaction_id == observed_resource.transaction_id
            and current.provider == observed_resource.provider
            and current.auth_mode == observed_resource.auth_mode
            and current.secret_channel_id == observed_resource.secret_channel_id
            and current.issuer_id == observed_resource.issuer_id == self._issuer_id
            and current.revocation_generation == observed_resource.revocation_generation
            and current.channel_locator_digest
            == observed_resource.cleanup_locator_digest
            and current.secret_fingerprint == observed_resource.secret_fingerprint
        )

    def _requireProcessCapability(self, process_capability: object) -> None:
        if (
            self._process_capability is None
            or process_capability is not self._process_capability
        ):
            raise CredentialBrokerRefused("process capability differs")

    def channelDestroyer(
        self,
        *,
        process_capability: object,
        resource: RuntimeResourceLease,
    ) -> CredentialChannelDestroyer:
        self._requireProcessCapability(process_capability)
        if type(resource) is not RuntimeResourceLease:
            raise CredentialBrokerRefused(
                "credential destroyer requires an exact durable resource"
            )
        with self._channelGuard():
            coordinator = self._coordinator(resource)
            key = (resource.transaction_id, resource.resource_id)
            existing = self._channel_destroyers.get(key)
            if existing is not None:
                self._freshAbsenceVerifierLocked(resource)
                return existing
            try:
                verifier = self._freshAbsenceVerifierLocked(resource)
                destroyer = _createCredentialChannelDestroyer(
                    broker=self,
                    absence_verifier=verifier,
                    coordinator=coordinator,
                    resource=resource,
                )
                self._channel_destroyers[key] = destroyer
                return destroyer
            except CredentialChannelEvidenceRefused as exc:
                raise CredentialBrokerRefused(
                    "credential channel destroyer is unavailable"
                ) from exc

    def _freshAbsenceVerifierLocked(
        self,
        resource: RuntimeResourceLease | None = None,
    ) -> CredentialChannelAbsenceVerifier:
        if self._absence_verifier is None:
            # Journal verification runs while holding its own attempt lock.  These
            # callbacks stay read-only and deliberately do not acquire the broker
            # guard, preserving the sole mutation order: broker guard -> journal.
            self._absence_verifier = _createCredentialChannelAbsenceVerifier(
                broker=self,
            )
        if resource is not None:
            try:
                self._coordinator(resource).bindVerifier(
                    self._absence_verifier,
                    resource,
                )
            except AttemptPersistenceAuthorityRefused as exc:
                raise CredentialBrokerRefused(
                    "credential verifier journal binding is unavailable"
                ) from exc
        return self._absence_verifier

    def freshAbsenceVerifier(
        self,
        *,
        process_capability: object,
        resource: RuntimeResourceLease | None = None,
    ) -> CredentialChannelAbsenceVerifier:
        self._requireProcessCapability(process_capability)
        with self._channelGuard():
            try:
                return self._freshAbsenceVerifierLocked(resource)
            except CredentialChannelEvidenceRefused as exc:
                raise CredentialBrokerRefused(
                    "credential channel absence verifier is unavailable"
                ) from exc


__all__ = [
    "CredentialBroker",
    "CredentialBrokerRefused",
    "CredentialIssueAuthority",
    "CredentialLease",
    "CredentialLeaseMetadata",
]
