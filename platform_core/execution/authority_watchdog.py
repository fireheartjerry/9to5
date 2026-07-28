"""Process-local launch authority and revocation admission watchdog.

RUN/TEST: python -m pytest tests/execution/test_authority_watchdog.py
"""

from __future__ import annotations

import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass, fields, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypeVar, cast

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}$")
_OID = re.compile(r"^[0-9a-f]{40}$")
_T = TypeVar("_T")
_NO_LAUNCH_OUTCOME = object()
_WATCHDOG_VALUE_SCOPE_FIELDS = (
    "_controller_generation",
    "_watchdog_generation",
    "_revocation_generation",
    "_bootstrap_outer_scope_digest",
    "_bootstrap_capsule_scope_digest",
    "_bootstrap_child_pid",
    "_bootstrap_expires_at",
    "_bootstrap_activation_generation",
    "_bootstrap_boot_generation",
    "_identity",
)
_WATCHDOG_IDENTITY_SCOPE_FIELDS = (
    "_clock",
    "_resource_probe",
    "_canonical_probe",
    "_trust_probe",
    "_capability_probe",
    "_journal_probe",
    "_seal",
)


class ExecutionLaunchRefused(RuntimeError):
    """The live watchdog cannot authorize process release."""


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ExecutionLaunchRefused("watchdog clock must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse(value: str) -> datetime:
    try:
        return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except (TypeError, ValueError) as exc:
        raise ExecutionLaunchRefused("launch deadline is invalid") from exc


@dataclass(frozen=True, slots=True)
class ExecutionLaunchAuthority:
    transaction_id: str
    resource_id: str
    clone_root: str
    clone_ownership_nonce: str
    runner_kind: str
    capability_receipt_id: str
    capability_process_grant_nonce: str
    trust_receipt_id: str
    trust_grant_nonce: str
    issuer_generation: int
    canonical_base: str
    journal_phase: str
    controller_generation: int
    watchdog_generation: int
    revocation_generation: int
    deadline: str
    _issuer_identity: int
    _seal: object


@dataclass(frozen=True, slots=True)
class _ExecutionLaunchRecord:
    """Issuer-owned copy of a launch scope, detached from the returned token."""

    authority: ExecutionLaunchAuthority
    value_scope: tuple[tuple[str, object], ...]
    seal: object
    state: str = "pending"
    outcome: object = _NO_LAUNCH_OUTCOME


def _launchValueScope(
    authority: ExecutionLaunchAuthority,
) -> tuple[tuple[str, object], ...]:
    """Snapshot every value field while retaining the seal by identity."""

    return tuple(
        (field.name, getattr(authority, field.name))
        for field in fields(authority)
        if field.name != "_seal"
    )


def _launchRecordMatches(
    record: _ExecutionLaunchRecord,
    authority: ExecutionLaunchAuthority,
) -> bool:
    if record.authority is not authority or authority._seal is not record.seal:
        return False
    observed = _launchValueScope(authority)
    if len(observed) != len(record.value_scope):
        return False
    return all(
        observed_name == expected_name
        and type(observed_value) is type(expected_value)
        and observed_value == expected_value
        for (observed_name, observed_value), (expected_name, expected_value) in zip(
            observed,
            record.value_scope,
            strict=True,
        )
    )


def _observeProbe(name: str, probe: Callable[..., object], *args: object) -> object:
    try:
        return probe(*args)
    except Exception as exc:
        raise ExecutionLaunchRefused(f"{name} probe failed closed") from exc


class AuthorityWatchdog:
    """Own the exclusive check/start gate for one controller generation."""

    def __init__(
        self,
        *,
        controller_generation: int,
        watchdog_generation: int,
        revocation_generation: int,
        clock: Callable[[], datetime] | None = None,
        resource_probe: Callable[[str], bool] | None = None,
        canonical_probe: Callable[[], str] | None = None,
        trust_probe: Callable[[ExecutionLaunchAuthority], bool] | None = None,
        capability_probe: Callable[[ExecutionLaunchAuthority], bool] | None = None,
        journal_probe: Callable[[ExecutionLaunchAuthority], bool] | None = None,
        bootstrap_outer_scope_digest: str = "",
        bootstrap_capsule_scope_digest: str = "",
        bootstrap_child_pid: int = 0,
        bootstrap_expires_at: str = "",
        bootstrap_activation_generation: int = 0,
        bootstrap_boot_generation: int = 0,
    ) -> None:
        if (
            type(controller_generation) is not int
            or controller_generation < 1
            or type(watchdog_generation) is not int
            or watchdog_generation < 1
            or type(revocation_generation) is not int
            or revocation_generation < 0
        ):
            raise ExecutionLaunchRefused("watchdog generations are invalid")
        self._controller_generation = controller_generation
        self._watchdog_generation = watchdog_generation
        self._revocation_generation = revocation_generation
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._resource_probe = resource_probe
        self._canonical_probe = canonical_probe
        self._trust_probe = trust_probe
        self._capability_probe = capability_probe
        self._journal_probe = journal_probe
        initial_observation: datetime | None = None
        bootstrap_values = (
            bootstrap_outer_scope_digest,
            bootstrap_capsule_scope_digest,
            bootstrap_expires_at,
        )
        if any(bootstrap_values):
            initial_observation = _utc(self._clock())
            if (
                any(
                    not isinstance(value, str)
                    or re.fullmatch(r"[0-9a-f]{64}", value) is None
                    for value in bootstrap_values[:2]
                )
                or type(bootstrap_child_pid) is not int
                or bootstrap_child_pid <= 0
                or type(bootstrap_activation_generation) is not int
                or bootstrap_activation_generation < 1
                or type(bootstrap_boot_generation) is not int
                or bootstrap_boot_generation < 1
                or not isinstance(bootstrap_expires_at, str)
                or _parse(bootstrap_expires_at) <= initial_observation
            ):
                raise ExecutionLaunchRefused("bootstrap watchdog scope is invalid")
        elif (
            bootstrap_child_pid != 0
            or bootstrap_activation_generation != 0
            or bootstrap_boot_generation != 0
        ):
            raise ExecutionLaunchRefused("bootstrap watchdog scope is incomplete")
        self._bootstrap_outer_scope_digest = bootstrap_outer_scope_digest
        self._bootstrap_capsule_scope_digest = bootstrap_capsule_scope_digest
        self._bootstrap_child_pid = bootstrap_child_pid
        self._bootstrap_expires_at = bootstrap_expires_at
        self._bootstrap_activation_generation = bootstrap_activation_generation
        self._bootstrap_boot_generation = bootstrap_boot_generation
        self._seal = object()
        self._identity = id(self)
        self._lock = threading.RLock()
        self._live = True
        self._terminal_reason = "watchdog is not live"
        self._latest_observed_time = initial_observation
        self._issued: dict[int, _ExecutionLaunchRecord] = {}
        self._captureIssuerScopeLocked()

    def _captureIssuerScopeLocked(self) -> None:
        self._issuer_value_scope = tuple(
            (name, getattr(self, name)) for name in _WATCHDOG_VALUE_SCOPE_FIELDS
        )
        self._issuer_identity_scope = tuple(
            (name, getattr(self, name)) for name in _WATCHDOG_IDENTITY_SCOPE_FIELDS
        )

    def _requireIssuerScopeLocked(self) -> None:
        try:
            for name, expected in self._issuer_identity_scope:
                if getattr(self, name) is not expected:
                    raise ExecutionLaunchRefused("watchdog issuer scope changed")
            for name, expected in self._issuer_value_scope:
                observed = getattr(self, name)
                if type(observed) is not type(expected) or observed != expected:
                    raise ExecutionLaunchRefused("watchdog issuer scope changed")
        except AttributeError as exc:
            raise ExecutionLaunchRefused("watchdog issuer scope changed") from exc

    def currentTime(self) -> datetime:
        """Return the watchdog's normalized current time for bound descendants."""

        with self._lock:
            return self._requireLiveLocked()

    def _requireLiveLocked(self) -> datetime:
        self._requireIssuerScopeLocked()
        if not self._live:
            raise ExecutionLaunchRefused(self._terminal_reason)
        now = _utc(self._clock())
        if (
            self._latest_observed_time is not None
            and now < self._latest_observed_time
        ):
            self._retireLocked(
                "watchdog clock moved backward; authority is terminally retired"
            )
            raise ExecutionLaunchRefused(
                self._terminal_reason
            )
        self._latest_observed_time = now
        if (
            self._bootstrap_expires_at
            and _parse(self._bootstrap_expires_at) <= now
        ):
            self._retireLocked("installed bootstrap watchdog expired")
            raise ExecutionLaunchRefused(self._terminal_reason)
        return now

    def _retireLocked(self, reason: str = "watchdog is not live") -> None:
        """Irreversibly close this process-local authority epoch."""

        self._terminal_reason = reason
        self._live = False
        self._issued.clear()

    def validateBootstrapEpoch(
        self,
        *,
        outer_scope_digest: str,
        capsule_scope_digest: str,
        controller_generation: int,
        watchdog_generation: int,
        revocation_generation: int,
        child_pid: int,
        activation_generation: int,
        boot_generation: int,
    ) -> None:
        """Revalidate the one installed bootstrap epoch under the watchdog lock."""

        with self._lock:
            self._requireLiveLocked()
            if not self._bootstrap_outer_scope_digest:
                raise ExecutionLaunchRefused("watchdog has no installed bootstrap scope")
            if (
                outer_scope_digest != self._bootstrap_outer_scope_digest
                or capsule_scope_digest != self._bootstrap_capsule_scope_digest
                or type(controller_generation) is not int
                or controller_generation != self._controller_generation
                or type(watchdog_generation) is not int
                or watchdog_generation != self._watchdog_generation
                or type(revocation_generation) is not int
                or revocation_generation != self._revocation_generation
                or type(child_pid) is not int
                or child_pid != self._bootstrap_child_pid
                or type(activation_generation) is not int
                or activation_generation != self._bootstrap_activation_generation
                or type(boot_generation) is not int
                or boot_generation != self._bootstrap_boot_generation
            ):
                raise ExecutionLaunchRefused(
                    "installed bootstrap watchdog scope is no longer live"
                )

    @contextmanager
    def bootstrapEpochPermit(
        self,
        *,
        outer_scope_digest: str,
        capsule_scope_digest: str,
        controller_generation: int,
        watchdog_generation: int,
        revocation_generation: int,
        child_pid: int,
        activation_generation: int,
        boot_generation: int,
    ):
        """Hold the shared epoch lock across one descendant admission/effect."""

        with self._lock:
            self.validateBootstrapEpoch(
                outer_scope_digest=outer_scope_digest,
                capsule_scope_digest=capsule_scope_digest,
                controller_generation=controller_generation,
                watchdog_generation=watchdog_generation,
                revocation_generation=revocation_generation,
                child_pid=child_pid,
                activation_generation=activation_generation,
                boot_generation=boot_generation,
            )
            yield

    def advanceWatchdog(self, generation: int) -> None:
        """Monotonically retire every authority from the prior watchdog epoch."""

        with self._lock:
            self._requireLiveLocked()
            if self._bootstrap_outer_scope_digest:
                raise ExecutionLaunchRefused(
                    "installed bootstrap watchdog generation is externally owned"
                )
            if type(generation) is not int or generation <= self._watchdog_generation:
                raise ExecutionLaunchRefused(
                    "watchdog generation must advance monotonically"
                )
            self._watchdog_generation = generation
            self._captureIssuerScopeLocked()

    def issueExecutionLaunchAuthority(
        self,
        *,
        transaction_id: str,
        resource_id: str,
        clone_root: str,
        clone_ownership_nonce: str,
        runner_kind: str,
        capability_receipt_id: str,
        capability_process_grant_nonce: str,
        trust_receipt_id: str,
        trust_grant_nonce: str,
        issuer_generation: int,
        canonical_base: str,
        journal_phase: str,
        deadline: str,
    ) -> ExecutionLaunchAuthority:
        with self._lock:
            now = self._requireLiveLocked()
            if self._bootstrap_outer_scope_digest and any(
                probe is None
                for probe in (
                    self._resource_probe,
                    self._canonical_probe,
                    self._trust_probe,
                    self._capability_probe,
                    self._journal_probe,
                )
            ):
                raise ExecutionLaunchRefused(
                    "installed bootstrap watchdog lacks execution admission probes"
                )
            for value, name in (
                (transaction_id, "transaction_id"),
                (resource_id, "resource_id"),
                (clone_ownership_nonce, "clone_ownership_nonce"),
                (capability_receipt_id, "capability_receipt_id"),
                (capability_process_grant_nonce, "capability_process_grant_nonce"),
                (trust_receipt_id, "trust_receipt_id"),
                (trust_grant_nonce, "trust_grant_nonce"),
            ):
                if not isinstance(value, str) or not _ID.fullmatch(value):
                    raise ExecutionLaunchRefused(f"{name} is invalid")
            if runner_kind not in {"local", "docker"}:
                raise ExecutionLaunchRefused("runner kind is unavailable")
            if type(issuer_generation) is not int or issuer_generation < 1:
                raise ExecutionLaunchRefused("launch issuer generation is invalid")
            if not _OID.fullmatch(canonical_base):
                raise ExecutionLaunchRefused("launch canonical base is invalid")
            if journal_phase != "ready":
                raise ExecutionLaunchRefused("launch journal phase is not ready")
            root = Path(clone_root)
            if not root.is_absolute():
                raise ExecutionLaunchRefused("clone root must be absolute")
            expires = _parse(deadline)
            if expires <= now:
                raise ExecutionLaunchRefused("launch authority is already expired")
            if (
                self._bootstrap_expires_at
                and expires > _parse(self._bootstrap_expires_at)
            ):
                raise ExecutionLaunchRefused(
                    "launch deadline exceeds bootstrap expiry"
                )
            if self._resource_probe is not None and _observeProbe(
                "runtime resource",
                self._resource_probe,
                resource_id,
            ) is not True:
                raise ExecutionLaunchRefused(
                    "runtime resource probe did not return exact true"
                )
            now = self._requireLiveLocked()
            if expires <= now:
                raise ExecutionLaunchRefused(
                    "launch authority expired before publication"
                )
            authority = ExecutionLaunchAuthority(
                transaction_id=transaction_id,
                resource_id=resource_id,
                clone_root=str(root),
                clone_ownership_nonce=clone_ownership_nonce,
                runner_kind=runner_kind,
                capability_receipt_id=capability_receipt_id,
                capability_process_grant_nonce=capability_process_grant_nonce,
                trust_receipt_id=trust_receipt_id,
                trust_grant_nonce=trust_grant_nonce,
                issuer_generation=issuer_generation,
                canonical_base=canonical_base,
                journal_phase=journal_phase,
                controller_generation=self._controller_generation,
                watchdog_generation=self._watchdog_generation,
                revocation_generation=self._revocation_generation,
                deadline=deadline,
                _issuer_identity=self._identity,
                _seal=self._seal,
            )
            self._issued[id(authority)] = _ExecutionLaunchRecord(
                authority=authority,
                value_scope=_launchValueScope(authority),
                seal=self._seal,
            )
            return authority

    def validateExecutionLaunchAuthority(self, authority: object) -> ExecutionLaunchAuthority:
        with self._lock:
            now = self._requireLiveLocked()
            if type(authority) is not ExecutionLaunchAuthority:
                raise ExecutionLaunchRefused("launch authority must be the exact process-local type")
            assert isinstance(authority, ExecutionLaunchAuthority)
            record = self._issued.get(id(authority))
            if record is None or not _launchRecordMatches(record, authority):
                raise ExecutionLaunchRefused("launch authority is not the issued object")
            if authority._issuer_identity != self._identity or authority._seal is not self._seal:
                raise ExecutionLaunchRefused("launch authority issuer differs")
            if authority.controller_generation != self._controller_generation:
                raise ExecutionLaunchRefused("controller generation differs")
            if authority.watchdog_generation != self._watchdog_generation:
                raise ExecutionLaunchRefused("watchdog generation differs")
            if authority.revocation_generation != self._revocation_generation:
                raise ExecutionLaunchRefused("authority was revoked")
            if _parse(authority.deadline) <= now:
                raise ExecutionLaunchRefused("launch authority expired")
            if self._resource_probe is not None and _observeProbe(
                "runtime resource",
                self._resource_probe,
                authority.resource_id,
            ) is not True:
                raise ExecutionLaunchRefused(
                    "runtime resource probe did not return exact true"
                )
            if self._canonical_probe is not None:
                canonical = _observeProbe("canonical base", self._canonical_probe)
                if type(canonical) is not str or canonical != authority.canonical_base:
                    raise ExecutionLaunchRefused(
                        "canonical base changed after launch authority issue"
                    )
            if self._trust_probe is not None and _observeProbe(
                "workload trust",
                self._trust_probe,
                authority,
            ) is not True:
                raise ExecutionLaunchRefused(
                    "workload trust probe did not return exact true"
                )
            if self._capability_probe is not None and _observeProbe(
                "capability enforcement",
                self._capability_probe,
                authority,
            ) is not True:
                raise ExecutionLaunchRefused(
                    "capability enforcement probe did not return exact true"
                )
            if self._journal_probe is not None and _observeProbe(
                "attempt journal",
                self._journal_probe,
                authority,
            ) is not True:
                raise ExecutionLaunchRefused(
                    "attempt journal probe did not return exact true"
                )
            now = self._requireLiveLocked()
            if _parse(authority.deadline) <= now:
                raise ExecutionLaunchRefused(
                    "launch authority expired while admission probes ran"
                )
            return authority

    def releaseStart(
        self, authority: object, starter: Callable[[], _T]
    ) -> _T:
        """Validate and release start while holding the exclusive admission gate."""

        with self._lock:
            self._requireLiveLocked()
            if type(authority) is not ExecutionLaunchAuthority:
                raise ExecutionLaunchRefused(
                    "launch authority must be the exact process-local type"
                )
            assert isinstance(authority, ExecutionLaunchAuthority)
            record = self._issued.get(id(authority))
            if record is None or not _launchRecordMatches(record, authority):
                raise ExecutionLaunchRefused("launch authority is not the issued object")
            if record.state == "started":
                return cast(_T, record.outcome)
            if record.state != "pending":
                raise ExecutionLaunchRefused(
                    "launch outcome is indeterminate or terminal"
                )
            self.validateExecutionLaunchAuthority(authority)
            starting = replace(record, state="starting")
            self._issued[id(authority)] = starting
            try:
                outcome = starter()
            except BaseException:
                current = self._issued.get(id(authority))
                if current is starting:
                    self._issued[id(authority)] = replace(
                        starting,
                        state="indeterminate",
                    )
                raise
            current = self._issued.get(id(authority))
            if current is not starting:
                raise ExecutionLaunchRefused(
                    "launch authority changed during start; outcome is indeterminate"
                )
            self._issued[id(authority)] = replace(
                starting,
                state="started",
                outcome=outcome,
            )
            return outcome

    def revoke(self, generation: int) -> None:
        with self._lock:
            self._requireLiveLocked()
            if type(generation) is not int or generation <= self._revocation_generation:
                raise ExecutionLaunchRefused("revocation generation must advance monotonically")
            self._revocation_generation = generation
            self._captureIssuerScopeLocked()
            self._retireLocked()

    def stop(self) -> None:
        with self._lock:
            self._requireIssuerScopeLocked()
            self._retireLocked()


def _poisonBootstrapEpoch(value: object) -> None:
    """Trusted rollback kill fence that does not dispatch through an instance."""

    if type(value) is not AuthorityWatchdog:
        raise ExecutionLaunchRefused("exact bootstrap watchdog is required")
    assert isinstance(value, AuthorityWatchdog)
    with value._lock:
        value._retireLocked()


def validateLaunchAuthority(
    *,
    watchdog: object,
    authority: object,
    caller_work_dir: object = None,
) -> tuple[ExecutionLaunchAuthority, str]:
    """Pure guarded-entry seam; derive the only work directory from the token."""

    if type(watchdog) is not AuthorityWatchdog:
        raise ExecutionLaunchRefused("exact process-local authority watchdog is required")
    assert isinstance(watchdog, AuthorityWatchdog)
    validated = watchdog.validateExecutionLaunchAuthority(authority)
    if caller_work_dir is not None:
        if not isinstance(caller_work_dir, str) or caller_work_dir != validated.clone_root:
            raise ExecutionLaunchRefused("caller work directory conflicts with launch authority")
    return validated, validated.clone_root


__all__ = [
    "AuthorityWatchdog",
    "ExecutionLaunchAuthority",
    "ExecutionLaunchRefused",
    "validateLaunchAuthority",
]
