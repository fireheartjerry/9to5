"""Atomic dark derivation of installed controller bootstrap authorities.

The opaque outer transfer is the sole input.  Static capsule facts, dynamic
operator approval, child PID, and frame provenance are never accepted again as
caller arguments.  This module remains source-dark until the installed capsule
supplies the real receipt chain and persistent revocation channel.
"""
from __future__ import annotations

import secrets
import threading
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from platform_core.execution.authority_watchdog import AuthorityWatchdog
    from platform_core.runtime.candidate import (
        LandingAuthorityIssuer,
        RunAdmissionAuthority,
    )
    from platform_core.runtime.controller_state import ControllerStateAuthority
    from platform_core.runtime.operator_launch import AuthorizedOuterCapabilities


class BootstrapAuthorityRefused(RuntimeError):
    """A bootstrap transfer is stale, partial, replayed, or no longer live."""


@dataclass(frozen=True, slots=True, eq=False)
class InstalledBootstrapAuthorities:
    """Opaque exact-object handle for one completely published authority bundle."""

    bootstrap_id: str
    _token: object = field(repr=False, compare=False)

    @property
    def controller_state_authority(self) -> ControllerStateAuthority:
        return _bundle_record(self, require_live=False).controller_state_authority

    @property
    def authority_watchdog(self) -> AuthorityWatchdog:
        return _bundle_record(self, require_live=False).authority_watchdog

    @property
    def landing_issuer(self) -> LandingAuthorityIssuer:
        return _bundle_record(self, require_live=False).landing_issuer

    @property
    def run_admission(self) -> RunAdmissionAuthority:
        return _bundle_record(self, require_live=False).run_admission

    @property
    def source_root(self) -> str:
        return _bundle_record(self, require_live=False).source_root

    @property
    def installed_controller_root(self) -> str:
        return _bundle_record(self, require_live=False).installed_controller_root

    @property
    def outer_scope_digest(self) -> str:
        return _bundle_record(self, require_live=False).outer_scope_digest

    @property
    def capsule_scope_digest(self) -> str:
        return _bundle_record(self, require_live=False).capsule_scope_digest


@dataclass(frozen=True, slots=True)
class _IssuedInstalledBootstrapAuthorities:
    bundle: InstalledBootstrapAuthorities
    token: object
    outer_capabilities: AuthorizedOuterCapabilities
    transfer_id: str
    outer_scope_digest: str
    capsule_scope_digest: str
    source_root: str
    installed_controller_root: str
    controller_state_authority: ControllerStateAuthority
    authority_watchdog: AuthorityWatchdog
    landing_issuer: LandingAuthorityIssuer
    run_admission: RunAdmissionAuthority


@dataclass(frozen=True, slots=True)
class _RuntimeInstallProjection:
    """Issuer-owned facts retained while the complete bootstrap epoch is held."""

    bundle: InstalledBootstrapAuthorities
    controller_state_authority: ControllerStateAuthority
    source_root: str
    installed_controller_root: str
    require_live: Callable[[], None] = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class _PoisonedBootstrapTransfer:
    transfer_id: str
    outer_scope_digest: str
    reason: str
    bootstrap_id: str | None = None
    bundle: InstalledBootstrapAuthorities | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    token: object | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class _PendingBootstrapTransfer:
    """Fail-closed terminal installed before any descendant can be constructed."""

    transfer_id: str
    outer_scope_digest: str


_BOOTSTRAP_LOCK = threading.RLock()
_BOOTSTRAP_REGISTRY: dict[str, _IssuedInstalledBootstrapAuthorities] = {}
_TRANSFER_TERMINALS: dict[
    str,
    _IssuedInstalledBootstrapAuthorities
    | _PendingBootstrapTransfer
    | _PoisonedBootstrapTransfer,
] = {}
_MAX_BOOTSTRAP_ID_ATTEMPTS = 32


def _guard_scope(record: _IssuedInstalledBootstrapAuthorities) -> dict[str, object]:
    admission = record.run_admission
    return {
        "outer_scope_digest": record.outer_scope_digest,
        "capsule_scope_digest": record.capsule_scope_digest,
        "controller_generation": admission.controller_generation,
        "watchdog_generation": admission.watchdog_generation,
        "revocation_generation": admission.revocation_generation,
        "child_pid": admission.child_pid,
        "activation_generation": admission.activation_generation,
        "boot_generation": admission.boot_generation,
    }


def _bundle_record(
    value: object,
    *,
    require_live: bool,
) -> _IssuedInstalledBootstrapAuthorities:
    if type(value) is not InstalledBootstrapAuthorities:
        raise BootstrapAuthorityRefused("exact installed bootstrap bundle is required")
    assert isinstance(value, InstalledBootstrapAuthorities)
    with _BOOTSTRAP_LOCK:
        record = _BOOTSTRAP_REGISTRY.get(value.bootstrap_id)
        if (
            record is None
            or record.bundle is not value
            or record.token is not value._token
        ):
            raise BootstrapAuthorityRefused("installed bootstrap bundle is not live")
        if require_live:
            validate_epoch = getattr(
                record.authority_watchdog,
                "validateBootstrapEpoch",
                None,
            )
            if not callable(validate_epoch):
                raise BootstrapAuthorityRefused(
                    "installed bootstrap watchdog is unavailable"
                )
            try:
                validate_epoch(**_guard_scope(record))
            except Exception as exc:
                raise BootstrapAuthorityRefused(
                    "installed bootstrap bundle is expired or revoked"
                ) from exc
        return record


def validateInstalledBootstrapAuthorities(
    value: object,
) -> InstalledBootstrapAuthorities:
    """Require the exact complete live bundle object from this process."""

    record = _bundle_record(value, require_live=True)
    try:
        from platform_core.runtime.controller_state import (
            validateControllerStateAuthority,
        )

        validateControllerStateAuthority(record.controller_state_authority)
        record.landing_issuer._validateAdmission(record.run_admission)
    except Exception as exc:
        raise BootstrapAuthorityRefused(
            "installed bootstrap bundle descendant is no longer live"
        ) from exc
    assert isinstance(value, InstalledBootstrapAuthorities)
    return value


def _requireRuntimeInstallRecordLiveLocked(
    record: _IssuedInstalledBootstrapAuthorities,
) -> None:
    """Validate one exact runtime-install record while all issuer locks are held."""

    if (
        _BOOTSTRAP_REGISTRY.get(record.bundle.bootstrap_id) is not record
        or _TRANSFER_TERMINALS.get(record.transfer_id) is not record
        or record.bundle._token is not record.token
    ):
        raise BootstrapAuthorityRefused(
            "runtime-install bootstrap bundle is not live"
        )
    try:
        guard_scope = _guard_scope(record)
        record.authority_watchdog.validateBootstrapEpoch(
            outer_scope_digest=cast(str, guard_scope["outer_scope_digest"]),
            capsule_scope_digest=cast(str, guard_scope["capsule_scope_digest"]),
            controller_generation=cast(int, guard_scope["controller_generation"]),
            watchdog_generation=cast(int, guard_scope["watchdog_generation"]),
            revocation_generation=cast(int, guard_scope["revocation_generation"]),
            child_pid=cast(int, guard_scope["child_pid"]),
            activation_generation=cast(int, guard_scope["activation_generation"]),
            boot_generation=cast(int, guard_scope["boot_generation"]),
        )
        record.landing_issuer._requireIssuerScopeLocked()
        if not record.landing_issuer._live:
            raise BootstrapAuthorityRefused(
                "runtime-install landing issuer is not live"
            )
        admission = record.landing_issuer._validateAdmissionLocked(
            record.run_admission
        )
        if admission is not record.run_admission:
            raise BootstrapAuthorityRefused(
                "runtime-install run admission identity differs"
            )

        from platform_core.runtime.controller_state import (
            validateControllerStateAuthority,
        )

        validateControllerStateAuthority(record.controller_state_authority)
    except BootstrapAuthorityRefused:
        raise
    except Exception as exc:
        raise BootstrapAuthorityRefused(
            "runtime-install bootstrap descendant is not live"
        ) from exc


@contextmanager
def _installedBootstrapRuntimePermit(
    value: object,
) -> Iterator[_RuntimeInstallProjection]:
    """Retain the exact bundle epoch through one runtime-install publication.

    The caller owns the controller-path activation lock before entering.  This
    context then preserves the global order ``path -> bundle -> watchdog ->
    landing issuer`` and keeps the exact initial run admission pinned throughout.
    """

    if type(value) is not InstalledBootstrapAuthorities:
        raise BootstrapAuthorityRefused(
            "exact installed bootstrap bundle is required"
        )
    assert isinstance(value, InstalledBootstrapAuthorities)
    with _BOOTSTRAP_LOCK:
        record = _BOOTSTRAP_REGISTRY.get(value.bootstrap_id)
        if (
            record is None
            or record.bundle is not value
            or record.token is not value._token
            or _TRANSFER_TERMINALS.get(record.transfer_id) is not record
        ):
            raise BootstrapAuthorityRefused(
                "exact live installed bootstrap bundle is required"
            )

        guard_scope = _guard_scope(record)
        permit = record.authority_watchdog.bootstrapEpochPermit(
            outer_scope_digest=cast(str, guard_scope["outer_scope_digest"]),
            capsule_scope_digest=cast(str, guard_scope["capsule_scope_digest"]),
            controller_generation=cast(int, guard_scope["controller_generation"]),
            watchdog_generation=cast(int, guard_scope["watchdog_generation"]),
            revocation_generation=cast(int, guard_scope["revocation_generation"]),
            child_pid=cast(int, guard_scope["child_pid"]),
            activation_generation=cast(int, guard_scope["activation_generation"]),
            boot_generation=cast(int, guard_scope["boot_generation"]),
        )
        with ExitStack() as stack:
            try:
                stack.enter_context(permit)
            except Exception as exc:
                raise BootstrapAuthorityRefused(
                    "runtime-install bootstrap epoch is not live"
                ) from exc
            with record.landing_issuer._lock:
                _requireRuntimeInstallRecordLiveLocked(record)
                owner_thread_id = threading.get_ident()
                active = True

                def require_live() -> None:
                    if not active or threading.get_ident() != owner_thread_id:
                        raise BootstrapAuthorityRefused(
                            "runtime-install permit is not active"
                        )
                    _requireRuntimeInstallRecordLiveLocked(record)

                projection = _RuntimeInstallProjection(
                    bundle=record.bundle,
                    controller_state_authority=record.controller_state_authority,
                    source_root=record.source_root,
                    installed_controller_root=record.installed_controller_root,
                    require_live=require_live,
                )
                try:
                    yield projection
                finally:
                    active = False


def _poisonInstalledBootstrapAuthorities(
    value: object,
    *,
    reason: str,
) -> None:
    """Permanently kill one exact bundle after ambiguous runtime installation.

    The poisoned transfer terminal is published before descendant cleanup, so a
    cleanup failure can never reopen the original transfer or permit reminting.
    Repeating the operation with the same exact bundle is idempotent.
    """

    if type(value) is not InstalledBootstrapAuthorities:
        raise BootstrapAuthorityRefused(
            "exact installed bootstrap bundle is required"
        )
    if type(reason) is not str or not reason or len(reason) > 256:
        raise BootstrapAuthorityRefused(
            "runtime-install poison reason is invalid"
        )
    assert isinstance(value, InstalledBootstrapAuthorities)
    with _BOOTSTRAP_LOCK:
        record = _BOOTSTRAP_REGISTRY.get(value.bootstrap_id)
        if record is None:
            for terminal in _TRANSFER_TERMINALS.values():
                if (
                    isinstance(terminal, _PoisonedBootstrapTransfer)
                    and terminal.bootstrap_id == value.bootstrap_id
                ):
                    if terminal.bundle is value and terminal.token is value._token:
                        return
                    raise BootstrapAuthorityRefused(
                        "exact installed bootstrap bundle is required"
                    )
            raise BootstrapAuthorityRefused(
                "installed bootstrap bundle is not live"
            )
        if (
            record.bundle is not value
            or record.token is not value._token
            or _TRANSFER_TERMINALS.get(record.transfer_id) is not record
        ):
            raise BootstrapAuthorityRefused(
                "exact live installed bootstrap bundle is required"
            )

        _TRANSFER_TERMINALS[record.transfer_id] = _PoisonedBootstrapTransfer(
            transfer_id=record.transfer_id,
            outer_scope_digest=record.outer_scope_digest,
            reason=reason,
            bootstrap_id=value.bootstrap_id,
            bundle=value,
            token=record.token,
        )
        _BOOTSTRAP_REGISTRY.pop(value.bootstrap_id, None)

        cleanup_errors: list[BaseException] = []
        try:
            from platform_core.execution.authority_watchdog import (
                _poisonBootstrapEpoch,
            )

            _poisonBootstrapEpoch(record.authority_watchdog)
        except BaseException as exc:
            cleanup_errors.append(exc)
        try:
            from platform_core.runtime.controller_state import (
                _retireControllerStateAuthority,
            )

            _retireControllerStateAuthority(record.controller_state_authority)
        except BaseException as exc:
            cleanup_errors.append(exc)
        try:
            with record.landing_issuer._lock:
                try:
                    record.landing_issuer._retireAdmissionLocked(
                        record.run_admission.admission_id
                    )
                except BaseException as exc:
                    cleanup_errors.append(exc)
                try:
                    record.landing_issuer._retireIssuerLocked()
                except BaseException as exc:
                    cleanup_errors.append(exc)
        except BaseException as exc:
            cleanup_errors.append(exc)
        if cleanup_errors:
            raise BootstrapAuthorityRefused(
                "runtime-install bootstrap poison cleanup is incomplete"
            ) from cleanup_errors[0]


def _new_bundle_identity() -> tuple[str, object, InstalledBootstrapAuthorities]:
    for _attempt in range(_MAX_BOOTSTRAP_ID_ATTEMPTS):
        bootstrap_id = secrets.token_hex(32)
        if (
            type(bootstrap_id) is not str
            or len(bootstrap_id) != 64
            or any(character not in "0123456789abcdef" for character in bootstrap_id)
        ):
            raise BootstrapAuthorityRefused(
                "installed bootstrap bundle ID generator is invalid"
            )
        if bootstrap_id in _BOOTSTRAP_REGISTRY:
            continue
        token = object()
        return (
            bootstrap_id,
            token,
            InstalledBootstrapAuthorities(bootstrap_id=bootstrap_id, _token=token),
        )
    raise BootstrapAuthorityRefused(
        "installed bootstrap bundle ID collision budget exhausted"
    )


def _validate_cached(
    record: _IssuedInstalledBootstrapAuthorities,
    *,
    outer_capabilities: AuthorizedOuterCapabilities,
    outer_scope_digest: str,
) -> InstalledBootstrapAuthorities:
    if (
        record.outer_capabilities is not outer_capabilities
        or record.outer_scope_digest != outer_scope_digest
    ):
        raise BootstrapAuthorityRefused(
            "bootstrap transfer replay scope differs from its terminal record"
        )
    validateInstalledBootstrapAuthorities(record.bundle)
    return record.bundle


def deriveInstalledBootstrapAuthorities(
    *,
    outer_capabilities: object,
) -> InstalledBootstrapAuthorities:
    """Atomically derive or replay the complete installed bootstrap bundle."""

    from platform_core.runtime import operator_launch as operator

    initial_outer = operator._resolve_authorized_outer_capabilities(
        outer_capabilities
    )
    typed_outer_capabilities = cast("AuthorizedOuterCapabilities", outer_capabilities)
    transfer_id = getattr(outer_capabilities, "transfer_id", None)
    if type(transfer_id) is not str:
        raise BootstrapAuthorityRefused("outer transfer identity is unavailable")
    initial_digest = initial_outer.scope_digest

    from platform_core.app_config.paths import controllerPathsActivationFence

    with controllerPathsActivationFence() as paths_active:
        with _BOOTSTRAP_LOCK:
            # Pin the exact outer issuance from the second validation through
            # complete cache publication.  The global order is path -> bundle
            # -> outer -> watchdog -> descendant registries.
            with operator._OUTER_CAPABILITY_REGISTRY_LOCK:
                outer = operator._resolve_authorized_outer_capabilities(
                    outer_capabilities
                )
                if outer.scope_digest != initial_digest:
                    raise BootstrapAuthorityRefused(
                        "outer transfer changed before bootstrap publication"
                    )
                terminal = _TRANSFER_TERMINALS.get(transfer_id)
                if isinstance(terminal, _IssuedInstalledBootstrapAuthorities):
                    return _validate_cached(
                        terminal,
                        outer_capabilities=typed_outer_capabilities,
                        outer_scope_digest=outer.scope_digest,
                    )
                if isinstance(terminal, _PoisonedBootstrapTransfer):
                    raise BootstrapAuthorityRefused(
                        "bootstrap transfer is permanently poisoned: "
                        + terminal.reason
                    )
                if isinstance(terminal, _PendingBootstrapTransfer):
                    raise BootstrapAuthorityRefused(
                        "bootstrap transfer has a poisoned pending publication"
                    )
                if paths_active:
                    raise BootstrapAuthorityRefused(
                        "controller paths activated before bootstrap derivation"
                    )

                scope = outer.bootstrap_scope
                pending = _PendingBootstrapTransfer(
                    transfer_id=transfer_id,
                    outer_scope_digest=outer.scope_digest,
                )
                # Install the fail-closed terminal before generating an ID or
                # constructing any descendant.  If a later terminal write is
                # unavailable, this exact pending object still forbids remint.
                _TRANSFER_TERMINALS[transfer_id] = pending
                bootstrap_id, token, bundle = _new_bundle_identity()
                watchdog = None
                controller_authority = None
                publishing_terminal = False
                try:
                    from platform_core.execution.authority_watchdog import (
                        AuthorityWatchdog,
                    )
                    from platform_core.runtime.candidate import (
                        _buildInstalledLandingAuthorityIssuer,
                    )
                    from platform_core.runtime.controller_state import (
                        _buildInstalledControllerStateAuthority,
                    )

                    watchdog = AuthorityWatchdog(
                        controller_generation=scope.controller_generation,
                        watchdog_generation=scope.watchdog_generation,
                        revocation_generation=scope.revocation_generation,
                        bootstrap_outer_scope_digest=outer.scope_digest,
                        bootstrap_capsule_scope_digest=scope.digest(),
                        bootstrap_child_pid=outer.child_pid,
                        # The complete bundle cannot outlive its earliest
                        # descendant.  This makes validation and replay agree.
                        bootstrap_expires_at=scope.run_deadline,
                        bootstrap_activation_generation=scope.activation_generation,
                        bootstrap_boot_generation=scope.boot_generation,
                    )
                    with watchdog.bootstrapEpochPermit(
                        outer_scope_digest=outer.scope_digest,
                        capsule_scope_digest=scope.digest(),
                        controller_generation=scope.controller_generation,
                        watchdog_generation=scope.watchdog_generation,
                        revocation_generation=scope.revocation_generation,
                        child_pid=outer.child_pid,
                        activation_generation=scope.activation_generation,
                        boot_generation=scope.boot_generation,
                    ):
                        landing_issuer, admission = (
                            _buildInstalledLandingAuthorityIssuer(
                                resolved_outer_capabilities=outer,
                                bootstrap_guard=watchdog,
                            )
                        )
                        controller_authority = (
                            _buildInstalledControllerStateAuthority(
                                resolved_outer_capabilities=outer,
                                bootstrap_guard=watchdog,
                            )
                        )
                        record = _IssuedInstalledBootstrapAuthorities(
                            bundle=bundle,
                            token=token,
                            outer_capabilities=typed_outer_capabilities,
                            transfer_id=transfer_id,
                            outer_scope_digest=outer.scope_digest,
                            capsule_scope_digest=scope.digest(),
                            source_root=scope.source_root,
                            installed_controller_root=scope.installed_controller_root,
                            controller_state_authority=controller_authority,
                            authority_watchdog=watchdog,
                            landing_issuer=landing_issuer,
                            run_admission=admission,
                        )
                        watchdog.validateBootstrapEpoch(
                            outer_scope_digest=outer.scope_digest,
                            capsule_scope_digest=scope.digest(),
                            controller_generation=scope.controller_generation,
                            watchdog_generation=scope.watchdog_generation,
                            revocation_generation=scope.revocation_generation,
                            child_pid=outer.child_pid,
                            activation_generation=scope.activation_generation,
                            boot_generation=scope.boot_generation,
                        )
                        _BOOTSTRAP_REGISTRY[bootstrap_id] = record
                        # Recheck after the first registry write and directly
                        # before the pending terminal becomes live.  Both
                        # registries remain unobservable under _BOOTSTRAP_LOCK.
                        watchdog.validateBootstrapEpoch(
                            outer_scope_digest=outer.scope_digest,
                            capsule_scope_digest=scope.digest(),
                            controller_generation=scope.controller_generation,
                            watchdog_generation=scope.watchdog_generation,
                            revocation_generation=scope.revocation_generation,
                            child_pid=outer.child_pid,
                            activation_generation=scope.activation_generation,
                            boot_generation=scope.boot_generation,
                        )
                        publishing_terminal = True
                        _TRANSFER_TERMINALS[transfer_id] = record
                        return bundle
                except BaseException as exc:
                    cleanup_errors: list[BaseException] = []
                    if watchdog is not None:
                        try:
                            from platform_core.execution.authority_watchdog import (
                                _poisonBootstrapEpoch,
                            )

                            _poisonBootstrapEpoch(watchdog)
                        except BaseException as cleanup_exc:
                            cleanup_errors.append(cleanup_exc)
                    if controller_authority is not None:
                        try:
                            from platform_core.runtime.controller_state import (
                                _retireControllerStateAuthority,
                            )

                            _retireControllerStateAuthority(controller_authority)
                        except BaseException as cleanup_exc:
                            cleanup_errors.append(cleanup_exc)
                    _BOOTSTRAP_REGISTRY.pop(bootstrap_id, None)
                    if (
                        _TRANSFER_TERMINALS.get(transfer_id) is pending
                        and not publishing_terminal
                    ):
                        try:
                            _TRANSFER_TERMINALS[transfer_id] = (
                                _PoisonedBootstrapTransfer(
                                    transfer_id=transfer_id,
                                    outer_scope_digest=outer.scope_digest,
                                    reason=type(exc).__name__,
                                )
                            )
                        except BaseException:
                            # The already-installed pending terminal is itself
                            # fail-closed; inability to improve its diagnostic
                            # label cannot reopen or remint the transfer.
                            pass
                    elif _TRANSFER_TERMINALS.get(transfer_id) is not pending:
                        cleanup_errors.append(
                            BootstrapAuthorityRefused(
                                "bootstrap transfer terminal changed during rollback"
                            )
                        )
                    if cleanup_errors:
                        raise BootstrapAuthorityRefused(
                            "partial bootstrap cleanup is ambiguous"
                        ) from cleanup_errors[0]
                    raise


def _revokeInstalledBootstrapAuthorities(
    value: object,
    *,
    generation: int,
) -> None:
    """Test/internal seam for the future external revocation channel."""

    record = _bundle_record(value, require_live=True)
    revoke = getattr(record.authority_watchdog, "revoke", None)
    if not callable(revoke):
        raise BootstrapAuthorityRefused("installed bootstrap watchdog cannot revoke")
    revoke(generation)


__all__ = [
    "BootstrapAuthorityRefused",
    "InstalledBootstrapAuthorities",
    "deriveInstalledBootstrapAuthorities",
    "validateInstalledBootstrapAuthorities",
]
