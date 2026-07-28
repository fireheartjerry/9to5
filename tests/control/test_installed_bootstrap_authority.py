"""Dark contracts for atomic installed bootstrap-authority derivation."""
from __future__ import annotations

import copy
import hashlib
import os
import pickle
import subprocess
import sys
import threading
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import pytest

from platform_core.runtime.bootstrap_scope import (
    CapsuleBootstrapScope,
)


class _Worker:
    def __init__(self) -> None:
        self.runs = 0

    def run(self, **_launch: object) -> dict[str, bytes]:
        self.runs += 1
        return {"length_prefixed_bytes": b'{"schema":1,"goal":"safe"}'}

    def revoke_and_quiesce_tree(self) -> dict[str, bool]:
        return {
            "all_descendants_dead": True,
            "credential_channels_revoked": True,
        }


class _Channel:
    @staticmethod
    def drain_preexisting_input() -> bool:
        return False

    @staticmethod
    def exchange(frame: object, *, nonce: str) -> str:
        return f"APPROVE SPEC {getattr(frame, 'digest')} NONCE {nonce}"


class _SameProcessChildFactory:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.consumer_handles: tuple[int, ...] = ()

    def spawn(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        descriptors = kwargs["capability_handles"]
        assert isinstance(descriptors, tuple)
        self.consumer_handles = tuple(os.dup(value) for value in descriptors)
        return type(
            "SameProcessChild",
            (),
            {"pid": os.getpid(), "authority_pid": os.getpid()},
        )()


def _scope(tmp_path: Path, *, suffix: str = "a") -> CapsuleBootstrapScope:
    source = str((tmp_path / f"source-{suffix}").resolve())
    installed = str((tmp_path / f"installed-{suffix}").resolve())
    state = str((tmp_path / f"state-{suffix}").resolve())
    canonical_repository_id = hashlib.sha256(
        f"canonical-{suffix}".encode("ascii")
    ).hexdigest()
    attestation = hashlib.sha256(f"attestation-{suffix}".encode("ascii")).hexdigest()
    roots_digest = hashlib.sha256(
        f"persisted-root-manifest-{suffix}".encode("ascii")
    ).hexdigest()
    return CapsuleBootstrapScope(
        installed_repository_identity=hashlib.sha256(
            f"installed-{suffix}".encode("ascii")
        ).hexdigest(),
        canonical_repository_id=canonical_repository_id,
        run_id=f"run-{suffix}",
        run_revision=0,
        controller_state_root=state,
        source_root=source,
        installed_controller_root=installed,
        external_roots_manifest_digest=roots_digest,
        repository_attestation_digest=attestation,
        expected_base_sha="a" * 40,
        source_snapshot_receipt_digest=hashlib.sha256(
            f"snapshot-{suffix}".encode("ascii")
        ).hexdigest(),
        anchor_receipt_digest=hashlib.sha256(
            f"anchor-{suffix}".encode("ascii")
        ).hexdigest(),
        boot_receipt_digest=hashlib.sha256(
            f"boot-{suffix}".encode("ascii")
        ).hexdigest(),
        controller_activation_receipt_digest=hashlib.sha256(
            f"activation-{suffix}".encode("ascii")
        ).hexdigest(),
        recovery_receipt_digest=hashlib.sha256(
            f"recovery-{suffix}".encode("ascii")
        ).hexdigest(),
        activation_generation=3,
        boot_generation=5,
        controller_generation=7,
        watchdog_generation=11,
        revocation_generation=0,
        capability_expires_at="2099-01-01T01:00:00+00:00",
        run_deadline="2099-01-01T00:30:00+00:00",
    )


def _consume_outer(tmp_path: Path, *, suffix: str = "a"):
    import platform_core.runtime.operator_launch as operator

    scope = _scope(tmp_path, suffix=suffix)
    authority = operator._issueDiagnosticCapsuleBootstrapAuthority(scope)
    child = _SameProcessChildFactory()
    launcher = operator.OperatorLauncher(
        bootstrap_authority=authority,
        worker=_Worker(),
        operator_channel=_Channel(),
        child_factory=child,
        nonce_factory=lambda: "1" * 64,
    )
    proposal = launcher.propose(raw_intent="do safe work", task_id=f"task-{suffix}")
    result = launcher.approve_and_spawn(proposal)
    with operator._PARENT_BINDINGS_LOCK:
        for handle in child.consumer_handles:
            operator._PARENT_BINDINGS[handle] = os.getpid()
    try:
        outer = operator.consume_outer_capabilities(
            argv=cast(list[str], child.calls[0]["argv"]),
            capability_handles=child.consumer_handles,
        )
    finally:
        for handle in child.consumer_handles:
            try:
                os.close(handle)
            except OSError:
                pass
    return scope, result, outer


def test_launcher_rejects_raw_scope_and_legacy_scope_kwargs_before_worker_use(
    tmp_path: Path,
) -> None:
    import platform_core.runtime.operator_launch as operator

    worker = _Worker()
    scope = _scope(tmp_path)
    common = {
        "worker": worker,
        "operator_channel": _Channel(),
        "child_factory": _SameProcessChildFactory(),
    }
    launcher_type = cast(Any, operator.OperatorLauncher)

    with pytest.raises((operator.OperatorLaunchRefused, TypeError)):
        launcher_type(bootstrap_authority=scope, **common)
    with pytest.raises(TypeError):
        launcher_type(
            bootstrap_authority=operator._issueDiagnosticCapsuleBootstrapAuthority(
                scope
            ),
            repository_attestation_digest="d" * 64,
            expected_base_sha="a" * 40,
            issuer_generation=7,
            canonical_spec_path=tmp_path / "caller-spec.json",
            **common,
        )

    assert worker.runs == 0
    assert not (tmp_path / "caller-spec.json").exists()


def test_launcher_derives_spec_path_beneath_capsule_state_root(tmp_path: Path) -> None:
    scope, result, outer = _consume_outer(tmp_path)

    expected = (
        Path(scope.controller_state_root)
        / "specs"
        / hashlib.sha256(scope.run_id.encode("ascii")).hexdigest()
        / "R0"
        / f"{hashlib.sha256(b'task-a').hexdigest()}.json"
    )
    assert result.canonical_spec_path == str(expected)
    assert expected.read_bytes() == b'{"goal":"safe","schema":1}'
    assert not hasattr(outer, "controller_state_root")


def test_capsule_bootstrap_authority_can_be_claimed_by_only_one_launcher(
    tmp_path: Path,
) -> None:
    import platform_core.runtime.operator_launch as operator

    authority = operator._issueDiagnosticCapsuleBootstrapAuthority(_scope(tmp_path))
    operator.OperatorLauncher(
        bootstrap_authority=authority,
        worker=_Worker(),
        operator_channel=_Channel(),
        child_factory=_SameProcessChildFactory(),
    )

    with pytest.raises(
        operator.OperatorLaunchRefused,
        match="claim|already|live|launcher",
    ):
        operator.OperatorLauncher(
            bootstrap_authority=authority,
            worker=_Worker(),
            operator_channel=_Channel(),
            child_factory=_SameProcessChildFactory(),
        )


def test_one_launcher_cannot_approve_and_spawn_twice(tmp_path: Path) -> None:
    import platform_core.runtime.operator_launch as operator

    authority = operator._issueDiagnosticCapsuleBootstrapAuthority(_scope(tmp_path))
    child = _SameProcessChildFactory()
    launcher = operator.OperatorLauncher(
        bootstrap_authority=authority,
        worker=_Worker(),
        operator_channel=_Channel(),
        child_factory=child,
        nonce_factory=lambda: "1" * 64,
    )
    proposal = launcher.propose(raw_intent="do safe work", task_id="task-a")
    launcher.approve_and_spawn(proposal)
    for handle in child.consumer_handles:
        os.close(handle)

    try:
        with pytest.raises(
            operator.OperatorApprovalRefused,
            match="already|once|spent|terminal|replay",
        ):
            launcher.approve_and_spawn(proposal)
    finally:
        for handle in child.consumer_handles:
            try:
                os.close(handle)
            except OSError:
                pass

    assert len(child.calls) == 1


def test_installed_derivation_is_atomic_memoized_and_facades_are_projections(
    tmp_path: Path,
) -> None:
    import platform_core.runtime.bootstrap_authority as bootstrap
    import platform_core.runtime.candidate as candidate
    import platform_core.runtime.controller_state as state
    import platform_core.runtime.operator_launch as operator

    scope, _result, outer = _consume_outer(tmp_path)
    bundle = bootstrap.deriveInstalledBootstrapAuthorities(
        outer_capabilities=outer
    )

    assert (
        state.deriveInstalledControllerStateAuthority(
            outer_capabilities=outer
        )
        is bundle.controller_state_authority
    )
    replay_issuer, replay_admission = candidate.deriveLandingAuthorityIssuer(
        outer_capabilities=outer
    )
    assert replay_issuer is bundle.landing_issuer
    assert replay_admission is bundle.run_admission
    assert bundle.capsule_scope_digest == scope.digest()
    assert len(bundle.outer_scope_digest) == 64
    assert bundle.outer_scope_digest != bundle.capsule_scope_digest
    assert bundle.source_root == scope.source_root
    assert bundle.installed_controller_root == scope.installed_controller_root
    assert bundle.controller_state_authority.root == scope.controller_state_root
    assert bundle.controller_state_authority.repository_id == scope.canonical_repository_id
    assert bundle.run_admission.run_id == scope.run_id
    assert bundle.run_admission.run_revision == 0
    assert bundle.run_admission.canonical_repository_id == scope.canonical_repository_id
    assert bundle.run_admission.boot_receipt_digest == scope.boot_receipt_digest
    assert (
        bundle.run_admission.source_snapshot_receipt_digest
        == scope.source_snapshot_receipt_digest
    )
    assert bundle.run_admission.revocation_generation == scope.revocation_generation

    resolved_outer = operator._resolve_authorized_outer_capabilities(outer)
    record = bootstrap._bundle_record(bundle, require_live=True)
    controller_scope = state._controllerAuthorityScope(
        bundle.controller_state_authority
    )
    assert {
        "transfer_id": record.transfer_id,
        "outer_capabilities": record.outer_capabilities,
        "outer_scope_digest": record.outer_scope_digest,
        "capsule_scope_digest": record.capsule_scope_digest,
        "source_root": record.source_root,
        "installed_controller_root": record.installed_controller_root,
    } == {
        "transfer_id": outer.transfer_id,
        "outer_capabilities": outer,
        "outer_scope_digest": resolved_outer.scope_digest,
        "capsule_scope_digest": scope.digest(),
        "source_root": scope.source_root,
        "installed_controller_root": scope.installed_controller_root,
    }
    assert {
        "root": controller_scope.root,
        "repository_id": controller_scope.repository_id,
        "controller_generation": controller_scope.controller_generation,
        "expires_at": controller_scope.expires_at,
        "process_capability": controller_scope.process_capability,
        "outer_scope_digest": controller_scope.outer_scope_digest,
        "capsule_scope_digest": controller_scope.capsule_scope_digest,
        "child_pid": controller_scope.child_pid,
        "activation_generation": controller_scope.activation_generation,
        "boot_generation": controller_scope.boot_generation,
        "watchdog_generation": controller_scope.watchdog_generation,
        "revocation_generation": controller_scope.revocation_generation,
        "bootstrap_guard": controller_scope.bootstrap_guard,
    } == {
        "root": scope.controller_state_root,
        "repository_id": scope.canonical_repository_id,
        "controller_generation": scope.controller_generation,
        "expires_at": scope.capability_expires_at,
        "process_capability": resolved_outer.process_capability,
        "outer_scope_digest": resolved_outer.scope_digest,
        "capsule_scope_digest": scope.digest(),
        "child_pid": resolved_outer.child_pid,
        "activation_generation": scope.activation_generation,
        "boot_generation": scope.boot_generation,
        "watchdog_generation": scope.watchdog_generation,
        "revocation_generation": scope.revocation_generation,
        "bootstrap_guard": bundle.authority_watchdog,
    }
    issuer = bundle.landing_issuer
    admission = bundle.run_admission
    expected_run_scope = {
        "run_id": scope.run_id,
        "run_revision": scope.run_revision,
        "installed_repository_identity": scope.installed_repository_identity,
        "canonical_repository_id": scope.canonical_repository_id,
        "outer_scope_digest": resolved_outer.scope_digest,
        "capsule_scope_digest": scope.digest(),
        "external_roots_manifest_digest": scope.external_roots_manifest_digest,
        "anchor_receipt_digest": scope.anchor_receipt_digest,
        "boot_receipt_digest": scope.boot_receipt_digest,
        "controller_activation_receipt_digest": (
            scope.controller_activation_receipt_digest
        ),
        "recovery_receipt_digest": scope.recovery_receipt_digest,
        "source_snapshot_receipt_digest": scope.source_snapshot_receipt_digest,
        "activation_generation": scope.activation_generation,
        "boot_generation": scope.boot_generation,
        "controller_generation": scope.controller_generation,
        "watchdog_generation": scope.watchdog_generation,
        "revocation_generation": scope.revocation_generation,
        "repository_attestation_digest": scope.repository_attestation_digest,
        "expected_base_sha": scope.expected_base_sha,
        "task_id": resolved_outer.task_id,
        "raw_intent_digest": resolved_outer.raw_intent_digest,
        "spec_digest": resolved_outer.spec_digest,
        "child_pid": resolved_outer.child_pid,
    }
    assert {
        name: getattr(issuer, name) for name in expected_run_scope
    } == expected_run_scope
    assert {
        name: getattr(admission, name) for name in expected_run_scope
    } == expected_run_scope
    assert issuer._process_capability is resolved_outer.process_capability
    assert admission._process_capability is resolved_outer.process_capability
    assert issuer._bootstrap_guard is bundle.authority_watchdog
    assert issuer._run_deadline == datetime.fromisoformat(scope.run_deadline)
    assert admission.deadline == datetime.fromisoformat(scope.run_deadline)
    watchdog_scope = bundle.authority_watchdog
    assert {
        "controller_generation": watchdog_scope._controller_generation,
        "watchdog_generation": watchdog_scope._watchdog_generation,
        "revocation_generation": watchdog_scope._revocation_generation,
        "outer_scope_digest": watchdog_scope._bootstrap_outer_scope_digest,
        "capsule_scope_digest": watchdog_scope._bootstrap_capsule_scope_digest,
        "child_pid": watchdog_scope._bootstrap_child_pid,
        "expires_at": watchdog_scope._bootstrap_expires_at,
        "activation_generation": (
            watchdog_scope._bootstrap_activation_generation
        ),
        "boot_generation": watchdog_scope._bootstrap_boot_generation,
    } == {
        "controller_generation": scope.controller_generation,
        "watchdog_generation": scope.watchdog_generation,
        "revocation_generation": scope.revocation_generation,
        "outer_scope_digest": resolved_outer.scope_digest,
        "capsule_scope_digest": scope.digest(),
        "child_pid": resolved_outer.child_pid,
        "expires_at": scope.run_deadline,
        "activation_generation": scope.activation_generation,
        "boot_generation": scope.boot_generation,
    }


def test_installed_derivation_rejects_every_legacy_caller_scope_kwarg_without_observation(
    tmp_path: Path,
) -> None:
    import platform_core.runtime.candidate as candidate
    import platform_core.runtime.controller_state as state

    _scope_value, _result, outer = _consume_outer(tmp_path)

    class ExplodingPath:
        observed = False

        def __fspath__(self) -> str:
            self.observed = True
            raise AssertionError("legacy caller path was observed")

    exploding = ExplodingPath()
    derive_controller = cast(Any, state.deriveInstalledControllerStateAuthority)
    derive_landing = cast(Any, candidate.deriveLandingAuthorityIssuer)
    with pytest.raises(TypeError):
        derive_controller(
            outer_capabilities=outer,
            root=exploding,
            repository_id="retargeted",
            controller_generation=999,
            expires_at="2099-01-01T00:00:00+00:00",
        )
    with pytest.raises(TypeError):
        derive_landing(
            outer_capabilities=outer,
            run_id="retargeted",
            controller_generation=999,
            watchdog_generation=999,
            deadline=object(),
            clock=lambda: (_ for _ in ()).throw(
                AssertionError("legacy caller clock was observed")
            ),
            recovery_quiescence_probe=lambda _transaction_id: True,
        )
    assert exploding.observed is False


def test_concurrent_exact_replay_returns_one_complete_bundle(tmp_path: Path) -> None:
    import platform_core.runtime.bootstrap_authority as bootstrap

    _scope_value, _result, outer = _consume_outer(tmp_path)
    barrier = threading.Barrier(12)
    bundles: list[object] = []
    errors: list[BaseException] = []

    def derive() -> None:
        try:
            barrier.wait(timeout=5)
            bundles.append(
                bootstrap.deriveInstalledBootstrapAuthorities(
                    outer_capabilities=outer
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=derive) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    assert len(bundles) == 12
    assert all(bundle is bundles[0] for bundle in bundles)


def test_revocation_advance_invalidates_controller_admission_and_landing_descendants(
    tmp_path: Path,
) -> None:
    import platform_core.runtime.bootstrap_authority as bootstrap
    import platform_core.runtime.controller_state as state
    from platform_core.runtime.candidate import LandingAuthorityRefused

    _scope_value, _result, outer = _consume_outer(tmp_path)
    bundle = bootstrap.deriveInstalledBootstrapAuthorities(
        outer_capabilities=outer
    )

    bootstrap._revokeInstalledBootstrapAuthorities(bundle, generation=1)

    with pytest.raises(bootstrap.BootstrapAuthorityRefused, match="revok|live"):
        bootstrap.validateInstalledBootstrapAuthorities(bundle)
    with pytest.raises(bootstrap.BootstrapAuthorityRefused, match="revok|live"):
        bootstrap.deriveInstalledBootstrapAuthorities(
            outer_capabilities=outer
        )
    with pytest.raises(state.ControllerStateRefused, match="revok|generation|live"):
        state.validateControllerStateAuthority(bundle.controller_state_authority)
    with pytest.raises(LandingAuthorityRefused, match="revok|generation|live"):
        bundle.landing_issuer._validateAdmission(bundle.run_admission)


def test_bundle_validation_requires_its_exact_initial_admission_to_remain_live(
    tmp_path: Path,
) -> None:
    import platform_core.runtime.bootstrap_authority as bootstrap

    _scope_value, _result, outer = _consume_outer(tmp_path)
    bundle = bootstrap.deriveInstalledBootstrapAuthorities(
        outer_capabilities=outer
    )
    bundle.landing_issuer.revokeRunAdmission(bundle.run_admission)

    with pytest.raises(bootstrap.BootstrapAuthorityRefused, match="descendant|live"):
        bootstrap.validateInstalledBootstrapAuthorities(bundle)
    with pytest.raises(bootstrap.BootstrapAuthorityRefused, match="descendant|live"):
        bootstrap.deriveInstalledBootstrapAuthorities(
            outer_capabilities=outer
        )


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("task_id", "task-other"),
        ("spec_digest", "9" * 64),
    ),
)
def test_installed_admission_cannot_mint_landing_for_another_workload(
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    import platform_core.runtime.bootstrap_authority as bootstrap
    from platform_core.runtime.candidate import LandingAuthorityRefused
    from platform_core.runtime.receipts import PromotionAuthorization

    _scope_value, _result, outer = _consume_outer(tmp_path, suffix=field)
    bundle = bootstrap.deriveInstalledBootstrapAuthorities(
        outer_capabilities=outer
    )
    authorization = PromotionAuthorization(
        transaction_id="tx-workload-scope",
        task_id=bundle.run_admission.task_id,
        subtask_id="subtask-a",
        staging_receipt_id="1" * 64,
        verification_receipt_id="2" * 64,
        review_receipt_id="3" * 64,
        proposed_revision="4" * 40,
        proposed_tree="5" * 40,
        proposed_diff_digest="6" * 64,
        spec_digest=bundle.run_admission.spec_digest,
        policy_digest="7" * 64,
    )
    retargeted = replace(authorization, **{field: replacement})

    with pytest.raises(LandingAuthorityRefused, match="workload|task|spec"):
        bundle.landing_issuer.issueLandingAuthority(
            admission=bundle.run_admission,
            authorization=retargeted,
        )


def test_landing_publication_and_shared_revocation_are_one_serial_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import platform_core.runtime.bootstrap_authority as bootstrap
    from platform_core.runtime.candidate import LandingAuthorityRefused
    from platform_core.runtime.receipts import PromotionAuthorization

    _scope_value, _result, outer = _consume_outer(tmp_path)
    bundle = bootstrap.deriveInstalledBootstrapAuthorities(
        outer_capabilities=outer
    )
    authorization = PromotionAuthorization(
        transaction_id="tx-bootstrap-race",
        task_id="task-a",
        subtask_id="subtask-a",
        staging_receipt_id="1" * 64,
        verification_receipt_id="2" * 64,
        review_receipt_id="3" * 64,
        proposed_revision="4" * 40,
        proposed_tree="5" * 40,
        proposed_diff_digest="6" * 64,
        spec_digest=bundle.run_admission.spec_digest,
        policy_digest="7" * 64,
    )
    conversion_entered = threading.Event()
    permit_conversion = threading.Event()
    revoker_started = threading.Event()
    revocation_returned = threading.Event()
    issued: list[object] = []
    errors: list[BaseException] = []
    original_from_value = cast(Any, PromotionAuthorization.from_value).__func__

    def blocking_from_value(cls: type[PromotionAuthorization], value: object):
        conversion_entered.set()
        if not permit_conversion.wait(timeout=5):
            raise AssertionError("authorization conversion was not released")
        return original_from_value(cls, value)

    monkeypatch.setattr(
        PromotionAuthorization,
        "from_value",
        classmethod(blocking_from_value),
    )

    def issue() -> None:
        try:
            issued.append(
                bundle.landing_issuer.issueLandingAuthority(
                    admission=bundle.run_admission,
                    authorization=authorization,
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    def revoke() -> None:
        revoker_started.set()
        bootstrap._revokeInstalledBootstrapAuthorities(bundle, generation=1)
        revocation_returned.set()

    issuer_thread = threading.Thread(target=issue)
    revoker_thread = threading.Thread(target=revoke)
    issuer_thread.start()
    assert conversion_entered.wait(timeout=5)
    revoker_thread.start()
    assert revoker_started.wait(timeout=5)

    # The watchdog permit is the linearization fence: revocation cannot return
    # while descendant publication remains between validation and registry write.
    assert not revocation_returned.wait(timeout=0.25)
    permit_conversion.set()
    issuer_thread.join(timeout=5)
    revoker_thread.join(timeout=5)

    assert not issuer_thread.is_alive()
    assert not revoker_thread.is_alive()
    assert errors == []
    assert len(issued) == 1
    assert revocation_returned.is_set()
    with pytest.raises(LandingAuthorityRefused, match="revok|generation|live"):
        bundle.landing_issuer.validateLandingAuthority(issued[0], authorization)


def test_bundle_handle_rejects_copy_deepcopy_replace_pickle_and_manual_clone(
    tmp_path: Path,
) -> None:
    import platform_core.runtime.bootstrap_authority as bootstrap

    _scope_value, _result, outer = _consume_outer(tmp_path)
    bundle = bootstrap.deriveInstalledBootstrapAuthorities(
        outer_capabilities=outer
    )
    clones = (
        copy.copy(bundle),
        copy.deepcopy(bundle),
        replace(bundle),
        pickle.loads(pickle.dumps(bundle)),
        bootstrap.InstalledBootstrapAuthorities(
            bootstrap_id=bundle.bootstrap_id,
            _token=bundle._token,
        ),
    )

    assert bootstrap.validateInstalledBootstrapAuthorities(bundle) is bundle
    for clone in clones:
        assert clone is not bundle
        with pytest.raises(
            bootstrap.BootstrapAuthorityRefused,
            match="exact|live",
        ):
            bootstrap.validateInstalledBootstrapAuthorities(clone)


def test_activation_first_refuses_without_descendant_registry_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import platform_core.app_config.paths as paths
    import platform_core.execution.authority_watchdog as watchdog
    import platform_core.runtime.bootstrap_authority as bootstrap
    import platform_core.runtime.candidate as candidate
    import platform_core.runtime.controller_state as state

    _scope_value, _result, outer = _consume_outer(tmp_path)
    bootstrap_before = dict(bootstrap._BOOTSTRAP_REGISTRY)
    terminals_before = dict(bootstrap._TRANSFER_TERMINALS)
    controllers_before = dict(state._AUTHORITY_REGISTRY)
    descendant_calls: list[str] = []

    def unexpected_descendant(name: str):
        def refuse(*_args: object, **_kwargs: object) -> object:
            descendant_calls.append(name)
            raise AssertionError(f"{name} ran after path activation")

        return refuse

    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", object())
    monkeypatch.setattr(
        watchdog,
        "AuthorityWatchdog",
        unexpected_descendant("watchdog"),
    )
    monkeypatch.setattr(
        candidate,
        "_buildInstalledLandingAuthorityIssuer",
        unexpected_descendant("landing"),
    )
    monkeypatch.setattr(
        state,
        "_buildInstalledControllerStateAuthority",
        unexpected_descendant("controller"),
    )

    with pytest.raises(
        bootstrap.BootstrapAuthorityRefused,
        match="paths activated",
    ):
        bootstrap.deriveInstalledBootstrapAuthorities(
            outer_capabilities=outer
        )

    assert descendant_calls == []
    assert bootstrap._BOOTSTRAP_REGISTRY == bootstrap_before
    assert bootstrap._TRANSFER_TERMINALS == terminals_before
    assert state._AUTHORITY_REGISTRY == controllers_before


def test_derived_bundle_exact_replay_survives_later_path_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import platform_core.app_config.paths as paths
    import platform_core.runtime.bootstrap_authority as bootstrap

    _scope_value, _result, outer = _consume_outer(tmp_path)
    bundle = bootstrap.deriveInstalledBootstrapAuthorities(
        outer_capabilities=outer
    )

    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", object())

    assert (
        bootstrap.deriveInstalledBootstrapAuthorities(
            outer_capabilities=outer
        )
        is bundle
    )


def test_fake_clock_expiry_invalidates_bundle_descendants_and_cached_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import platform_core.execution.authority_watchdog as watchdog
    import platform_core.runtime.bootstrap_authority as bootstrap
    import platform_core.runtime.controller_state as state
    from platform_core.runtime.candidate import LandingAuthorityRefused

    observed_time = [datetime(2098, 12, 31, tzinfo=timezone.utc)]
    original_watchdog = watchdog.AuthorityWatchdog
    watchdog_factory = cast(Any, original_watchdog)

    def build_watchdog(**kwargs: object):
        return watchdog_factory(
            **kwargs,
            clock=lambda: observed_time[0],
        )

    monkeypatch.setattr(watchdog, "AuthorityWatchdog", build_watchdog)
    _scope_value, _result, outer = _consume_outer(tmp_path)
    bundle = bootstrap.deriveInstalledBootstrapAuthorities(
        outer_capabilities=outer
    )

    assert bootstrap.validateInstalledBootstrapAuthorities(bundle) is bundle
    assert state.validateControllerStateAuthority(
        bundle.controller_state_authority
    ) is bundle.controller_state_authority
    assert (
        bundle.landing_issuer._validateAdmission(bundle.run_admission)
        is bundle.run_admission
    )

    observed_time[0] = datetime(2099, 1, 1, 0, 30, tzinfo=timezone.utc)

    with pytest.raises(bootstrap.BootstrapAuthorityRefused, match="expired|revoked"):
        bootstrap.validateInstalledBootstrapAuthorities(bundle)
    with pytest.raises(state.ControllerStateRefused, match="longer live|expired"):
        state.validateControllerStateAuthority(bundle.controller_state_authority)
    with pytest.raises(LandingAuthorityRefused, match="longer live|expired"):
        bundle.landing_issuer._validateAdmission(bundle.run_admission)
    with pytest.raises(
        bootstrap.BootstrapAuthorityRefused,
        match="expired|revoked|descendants",
    ):
        bootstrap.deriveInstalledBootstrapAuthorities(
            outer_capabilities=outer
        )


def test_installed_store_construction_rechecks_epoch_before_lock_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import platform_core.execution.authority_watchdog as watchdog
    import platform_core.runtime.bootstrap_authority as bootstrap
    import platform_core.runtime.controller_state as state

    observed_time = [datetime(2098, 12, 31, tzinfo=timezone.utc)]
    original_watchdog = watchdog.AuthorityWatchdog
    watchdog_factory = cast(Any, original_watchdog)

    def build_watchdog(**kwargs: object):
        return watchdog_factory(
            **kwargs,
            clock=lambda: observed_time[0],
        )

    monkeypatch.setattr(watchdog, "AuthorityWatchdog", build_watchdog)
    scope, _result, outer = _consume_outer(tmp_path)
    bundle = bootstrap.deriveInstalledBootstrapAuthorities(
        outer_capabilities=outer
    )
    controller_root = Path(scope.controller_state_root)
    original_mkdir = Path.mkdir

    def expire_after_root_observation(
        path: Path,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        original_mkdir(
            path,
            mode=mode,
            parents=parents,
            exist_ok=exist_ok,
        )
        if path == controller_root:
            observed_time[0] = datetime(
                2099,
                1,
                1,
                0,
                30,
                tzinfo=timezone.utc,
            )

    monkeypatch.setattr(Path, "mkdir", expire_after_root_observation)

    with pytest.raises(state.ControllerStateRefused, match="bootstrap|expired|live"):
        state.ControllerStateStore(
            root=controller_root,
            authority=bundle.controller_state_authority,
            _runtime_install_capability=state._controllerAuthorityScope(
                bundle.controller_state_authority
            ).runtime_install_capability,
            _bootstrap_authorities=bundle,
        )

    assert not (controller_root / ".controller-state.lock").exists()


def test_partial_construction_is_poisoned_retired_and_never_reminted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import platform_core.runtime.bootstrap_authority as bootstrap
    import platform_core.runtime.candidate as candidate
    import platform_core.runtime.controller_state as state
    from platform_core.runtime.candidate import LandingAuthorityRefused

    _scope_value, _result, outer = _consume_outer(tmp_path)
    bootstrap_ids_before = set(bootstrap._BOOTSTRAP_REGISTRY)
    controller_ids_before = set(state._AUTHORITY_REGISTRY)
    captured: dict[str, object] = {}
    original_landing_builder = candidate._buildInstalledLandingAuthorityIssuer
    original_controller_builder = state._buildInstalledControllerStateAuthority

    def capture_landing(**kwargs: object):
        issuer, admission = original_landing_builder(**kwargs)
        captured["issuer"] = issuer
        captured["admission"] = admission
        return issuer, admission

    def capture_controller(**kwargs: object):
        authority = original_controller_builder(**kwargs)
        captured["controller"] = authority
        return authority

    class FailFirstPublication(dict[str, object]):
        def __setitem__(self, key: str, value: object) -> None:
            del key, value
            raise RuntimeError("injected bundle publication failure")

    monkeypatch.setattr(
        candidate,
        "_buildInstalledLandingAuthorityIssuer",
        capture_landing,
    )
    monkeypatch.setattr(
        state,
        "_buildInstalledControllerStateAuthority",
        capture_controller,
    )
    monkeypatch.setattr(
        bootstrap,
        "_BOOTSTRAP_REGISTRY",
        FailFirstPublication(bootstrap._BOOTSTRAP_REGISTRY),
    )

    with pytest.raises(RuntimeError, match="injected bundle publication failure"):
        bootstrap.deriveInstalledBootstrapAuthorities(
            outer_capabilities=outer
        )

    issuer = captured["issuer"]
    admission = captured["admission"]
    controller = captured["controller"]
    with pytest.raises(LandingAuthorityRefused, match="longer live"):
        getattr(issuer, "_validateAdmission")(admission)
    with pytest.raises(state.ControllerStateRefused, match="issuer differs"):
        state.validateControllerStateAuthority(controller)

    assert set(bootstrap._BOOTSTRAP_REGISTRY) == bootstrap_ids_before
    assert set(state._AUTHORITY_REGISTRY) == controller_ids_before
    terminal = bootstrap._TRANSFER_TERMINALS[outer.transfer_id]
    assert type(terminal) is bootstrap._PoisonedBootstrapTransfer
    with pytest.raises(bootstrap.BootstrapAuthorityRefused, match="poisoned"):
        bootstrap.deriveInstalledBootstrapAuthorities(
            outer_capabilities=outer
        )


def test_terminal_live_publication_failure_keeps_preconstruction_poison(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import platform_core.runtime.bootstrap_authority as bootstrap
    import platform_core.runtime.controller_state as state

    _scope_value, _result, outer = _consume_outer(
        tmp_path,
        suffix="terminal-publication",
    )
    bootstrap_ids_before = set(bootstrap._BOOTSTRAP_REGISTRY)
    controller_ids_before = set(state._AUTHORITY_REGISTRY)

    class FailEveryWriteAfterPending(dict[str, object]):
        writes = 0

        def __setitem__(self, key: str, value: object) -> None:
            self.writes += 1
            if self.writes > 1:
                raise RuntimeError("injected persistent terminal publication failure")
            super().__setitem__(key, value)

    terminals = FailEveryWriteAfterPending(bootstrap._TRANSFER_TERMINALS)
    monkeypatch.setattr(bootstrap, "_TRANSFER_TERMINALS", terminals)

    with pytest.raises(
        RuntimeError,
        match="injected persistent terminal publication failure",
    ):
        bootstrap.deriveInstalledBootstrapAuthorities(
            outer_capabilities=outer
    )

    assert terminals.writes == 2
    assert outer.transfer_id in terminals
    assert type(terminals[outer.transfer_id]) is bootstrap._PendingBootstrapTransfer
    assert set(bootstrap._BOOTSTRAP_REGISTRY) == bootstrap_ids_before
    assert set(state._AUTHORITY_REGISTRY) == controller_ids_before

    with pytest.raises(bootstrap.BootstrapAuthorityRefused, match="poison|pending"):
        bootstrap.deriveInstalledBootstrapAuthorities(
            outer_capabilities=outer
        )
    assert terminals.writes == 2


def test_expiry_during_controller_construction_rolls_back_and_poison_transfer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import platform_core.execution.authority_watchdog as watchdog
    import platform_core.runtime.bootstrap_authority as bootstrap
    import platform_core.runtime.controller_state as state

    observed_time = [datetime(2098, 12, 31, tzinfo=timezone.utc)]

    class FakeClockWatchdog(watchdog.AuthorityWatchdog):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs, clock=lambda: observed_time[0])

    captured: dict[str, object] = {}
    original_controller_builder = state._buildInstalledControllerStateAuthority

    def expire_after_controller_registration(**kwargs: object):
        authority = original_controller_builder(**kwargs)
        captured["controller"] = authority
        observed_time[0] = datetime(2099, 1, 1, 0, 30, tzinfo=timezone.utc)
        return authority

    monkeypatch.setattr(watchdog, "AuthorityWatchdog", FakeClockWatchdog)
    monkeypatch.setattr(
        state,
        "_buildInstalledControllerStateAuthority",
        expire_after_controller_registration,
    )
    _scope_value, _result, outer = _consume_outer(
        tmp_path,
        suffix="construction-expiry",
    )
    bootstrap_ids_before = set(bootstrap._BOOTSTRAP_REGISTRY)
    controller_ids_before = set(state._AUTHORITY_REGISTRY)

    with pytest.raises(watchdog.ExecutionLaunchRefused, match="expired|live"):
        bootstrap.deriveInstalledBootstrapAuthorities(
            outer_capabilities=outer
        )

    assert set(bootstrap._BOOTSTRAP_REGISTRY) == bootstrap_ids_before
    assert set(state._AUTHORITY_REGISTRY) == controller_ids_before
    with pytest.raises(state.ControllerStateRefused, match="issuer differs"):
        state.validateControllerStateAuthority(captured["controller"])
    terminal = bootstrap._TRANSFER_TERMINALS[outer.transfer_id]
    assert type(terminal) is bootstrap._PoisonedBootstrapTransfer
    with pytest.raises(bootstrap.BootstrapAuthorityRefused, match="poison"):
        bootstrap.deriveInstalledBootstrapAuthorities(
            outer_capabilities=outer
        )


def test_expiry_during_bundle_registry_publication_rolls_back_before_live_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import platform_core.execution.authority_watchdog as watchdog
    import platform_core.runtime.bootstrap_authority as bootstrap
    import platform_core.runtime.controller_state as state

    observed_time = [datetime(2098, 12, 31, tzinfo=timezone.utc)]

    class FakeClockWatchdog(watchdog.AuthorityWatchdog):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs, clock=lambda: observed_time[0])

    class ExpireAfterBundleWrite(dict[str, object]):
        writes = 0

        def __setitem__(self, key: str, value: object) -> None:
            super().__setitem__(key, value)
            self.writes += 1
            observed_time[0] = datetime(2099, 1, 1, 0, 30, tzinfo=timezone.utc)

    monkeypatch.setattr(watchdog, "AuthorityWatchdog", FakeClockWatchdog)
    registry = ExpireAfterBundleWrite(bootstrap._BOOTSTRAP_REGISTRY)
    monkeypatch.setattr(bootstrap, "_BOOTSTRAP_REGISTRY", registry)
    _scope_value, _result, outer = _consume_outer(
        tmp_path,
        suffix="publication-expiry",
    )
    bootstrap_ids_before = set(registry)
    controller_ids_before = set(state._AUTHORITY_REGISTRY)

    with pytest.raises(watchdog.ExecutionLaunchRefused, match="expired|live"):
        bootstrap.deriveInstalledBootstrapAuthorities(
            outer_capabilities=outer
        )

    assert registry.writes == 1
    assert set(registry) == bootstrap_ids_before
    assert set(state._AUTHORITY_REGISTRY) == controller_ids_before
    terminal = bootstrap._TRANSFER_TERMINALS[outer.transfer_id]
    assert type(terminal) is bootstrap._PoisonedBootstrapTransfer
    with pytest.raises(bootstrap.BootstrapAuthorityRefused, match="poison"):
        bootstrap.deriveInstalledBootstrapAuthorities(
            outer_capabilities=outer
        )


@pytest.mark.parametrize(
    "failure_stage",
    ("watchdog", "landing", "admission", "controller"),
)
def test_every_descendant_construction_failure_prefix_is_terminally_poisoned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    import platform_core.execution.authority_watchdog as watchdog
    import platform_core.runtime.bootstrap_authority as bootstrap
    import platform_core.runtime.candidate as candidate
    import platform_core.runtime.controller_state as state

    _scope_value, _result, outer = _consume_outer(
        tmp_path,
        suffix=f"prefix-{failure_stage}",
    )
    bootstrap_ids_before = set(bootstrap._BOOTSTRAP_REGISTRY)
    controller_ids_before = set(state._AUTHORITY_REGISTRY)
    calls = [0]

    def fail(*_args: object, **_kwargs: object) -> object:
        calls[0] += 1
        assert type(
            bootstrap._TRANSFER_TERMINALS.get(outer.transfer_id)
        ) is bootstrap._PendingBootstrapTransfer
        raise RuntimeError(f"injected {failure_stage} construction failure")

    if failure_stage == "watchdog":
        monkeypatch.setattr(watchdog, "AuthorityWatchdog", fail)
    elif failure_stage == "landing":
        monkeypatch.setattr(
            candidate,
            "_buildInstalledLandingAuthorityIssuer",
            fail,
        )
    elif failure_stage == "admission":
        monkeypatch.setattr(
            candidate.LandingAuthorityIssuer,
            "issueRunAdmission",
            fail,
        )
    else:
        monkeypatch.setattr(
            state,
            "_buildInstalledControllerStateAuthority",
            fail,
        )

    with pytest.raises(RuntimeError, match=f"injected {failure_stage}"):
        bootstrap.deriveInstalledBootstrapAuthorities(
            outer_capabilities=outer
        )

    assert calls == [1]
    assert set(bootstrap._BOOTSTRAP_REGISTRY) == bootstrap_ids_before
    assert set(state._AUTHORITY_REGISTRY) == controller_ids_before
    terminal = bootstrap._TRANSFER_TERMINALS[outer.transfer_id]
    assert type(terminal) is bootstrap._PoisonedBootstrapTransfer

    with pytest.raises(bootstrap.BootstrapAuthorityRefused, match="poison"):
        bootstrap.deriveInstalledBootstrapAuthorities(
            outer_capabilities=outer
        )
    assert calls == [1]


def test_derive_first_serializes_path_activation_then_replays_exact_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import platform_core.app_config.paths as paths
    import platform_core.runtime.bootstrap_authority as bootstrap
    import platform_core.runtime.candidate as candidate

    _scope_value, _result, outer = _consume_outer(
        tmp_path,
        suffix="derive-first-race",
    )
    construction_entered = threading.Event()
    release_construction = threading.Event()
    activation_started = threading.Event()
    activation_returned = threading.Event()
    bundles: list[object] = []
    errors: list[BaseException] = []
    original_landing_builder = candidate._buildInstalledLandingAuthorityIssuer

    def blocking_landing_builder(**kwargs: object):
        construction_entered.set()
        if not release_construction.wait(timeout=5):
            raise AssertionError("bootstrap construction was not released")
        return original_landing_builder(**kwargs)

    monkeypatch.setattr(
        candidate,
        "_buildInstalledLandingAuthorityIssuer",
        blocking_landing_builder,
    )

    def derive() -> None:
        try:
            bundles.append(
                bootstrap.deriveInstalledBootstrapAuthorities(
                    outer_capabilities=outer
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    def activate() -> None:
        activation_started.set()
        with paths._CONTROLLER_PATHS_LOCK:
            monkeypatch.setattr(paths, "_CONTROLLER_PATHS", object())
        activation_returned.set()

    derive_thread = threading.Thread(target=derive)
    activation_thread = threading.Thread(target=activate)
    derive_thread.start()
    assert construction_entered.wait(timeout=5)
    activation_thread.start()
    assert activation_started.wait(timeout=5)
    assert not activation_returned.wait(timeout=0.25)
    release_construction.set()
    derive_thread.join(timeout=5)
    activation_thread.join(timeout=5)

    assert not derive_thread.is_alive()
    assert not activation_thread.is_alive()
    assert errors == []
    assert len(bundles) == 1
    assert activation_returned.is_set()
    assert paths.controllerPathsActive()
    assert (
        bootstrap.deriveInstalledBootstrapAuthorities(
            outer_capabilities=outer
        )
        is bundles[0]
    )


def test_cold_activation_first_refuses_before_authority_descendant_imports(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    code = f"""
import sys
from pathlib import Path
import platform_core.app_config.paths as paths
from tests.control.test_installed_bootstrap_authority import _consume_outer

_scope, _result, outer = _consume_outer(
    Path({str(tmp_path)!r}), suffix='cold-activation-first')
descendants = (
    'platform_core.execution.authority_watchdog',
    'platform_core.runtime.candidate',
)
assert 'platform_core.runtime.controller_state' in sys.modules
assert not any(name in sys.modules for name in descendants), [
    name for name in descendants if name in sys.modules]
paths._CONTROLLER_PATHS = object()
import platform_core.runtime.bootstrap_authority as bootstrap
try:
    bootstrap.deriveInstalledBootstrapAuthorities(outer_capabilities=outer)
except bootstrap.BootstrapAuthorityRefused as exc:
    assert 'paths activated' in str(exc)
else:
    raise AssertionError('activation-first derivation unexpectedly succeeded')
assert not any(name in sys.modules for name in descendants), [
    name for name in descendants if name in sys.modules]
assert 'platform_core.runtime.controller_state' in sys.modules
assert not bootstrap._BOOTSTRAP_REGISTRY
assert not bootstrap._TRANSFER_TERMINALS
print('cold-activation-first-refused')
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(repo_root)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "cold-activation-first-refused"
    )


def test_execution_watchdog_import_keeps_normal_config_inert(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    code = """
import sys
import platform_core.execution as execution

for name in (
    'config',
    'platform_core.app_config.settings',
    'platform_core.execution.router',
):
    assert name not in sys.modules, name

from platform_core.execution import authority_watchdog
assert authority_watchdog.AuthorityWatchdog is not None
for name in (
    'config',
    'platform_core.app_config.settings',
    'platform_core.execution.router',
):
    assert name not in sys.modules, name

from platform_core.execution import AttemptProvisionScope
assert execution.AttemptProvisionScope is AttemptProvisionScope
assert 'platform_core.execution.environment' in sys.modules
assert 'platform_core.execution.router' not in sys.modules
assert 'platform_core.app_config.settings' not in sys.modules
assert 'config' not in sys.modules
print('execution-watchdog-import-config-inert')
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(repo_root)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        "execution-watchdog-import-config-inert"
    )


def test_controller_store_initialization_and_revocation_have_one_serial_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import platform_core.runtime.bootstrap_authority as bootstrap
    import platform_core.runtime.controller_state as state

    scope, _result, outer = _consume_outer(
        tmp_path,
        suffix="controller-init-revoke",
    )
    bundle = bootstrap.deriveInstalledBootstrapAuthorities(
        outer_capabilities=outer
    )
    controller_root = Path(scope.controller_state_root)
    initialization_entered = threading.Event()
    release_initialization = threading.Event()
    revocation_started = threading.Event()
    revocation_returned = threading.Event()
    stores: list[state.ControllerStateStore] = []
    errors: list[BaseException] = []
    original_mkdir = Path.mkdir

    def blocking_mkdir(
        path: Path,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        if path == controller_root:
            initialization_entered.set()
            if not release_initialization.wait(timeout=5):
                raise AssertionError("controller initialization was not released")
        original_mkdir(
            path,
            mode=mode,
            parents=parents,
            exist_ok=exist_ok,
        )

    monkeypatch.setattr(Path, "mkdir", blocking_mkdir)

    def initialize() -> None:
        try:
            stores.append(
                state.ControllerStateStore(
                    root=controller_root,
                    authority=bundle.controller_state_authority,
                    _runtime_install_capability=state._controllerAuthorityScope(
                        bundle.controller_state_authority
                    ).runtime_install_capability,
                    _bootstrap_authorities=bundle,
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    def revoke() -> None:
        revocation_started.set()
        bootstrap._revokeInstalledBootstrapAuthorities(bundle, generation=1)
        revocation_returned.set()

    initializer_thread = threading.Thread(target=initialize)
    revoker_thread = threading.Thread(target=revoke)
    initializer_thread.start()
    assert initialization_entered.wait(timeout=5)
    revoker_thread.start()
    assert revocation_started.wait(timeout=5)
    assert not revocation_returned.wait(timeout=0.25)
    release_initialization.set()
    initializer_thread.join(timeout=5)
    revoker_thread.join(timeout=5)

    assert not initializer_thread.is_alive()
    assert not revoker_thread.is_alive()
    assert errors == []
    assert len(stores) == 1
    assert revocation_returned.is_set()
    try:
        with pytest.raises(state.ControllerStateRefused, match="revok|live"):
            stores[0].writeJson(
                "after-revocation",
                {"forbidden": True},
                authority=bundle.controller_state_authority,
            )
    finally:
        stores[0].close()


def test_runtime_install_permit_revalidates_initial_admission_before_publication(
    tmp_path: Path,
) -> None:
    import platform_core.runtime.bootstrap_authority as bootstrap

    scope, _result, outer = _consume_outer(
        tmp_path,
        suffix="runtime-install-admission-revocation",
    )
    bundle = bootstrap.deriveInstalledBootstrapAuthorities(
        outer_capabilities=outer
    )

    with bootstrap._installedBootstrapRuntimePermit(bundle) as projection:
        assert projection.bundle is bundle
        assert projection.controller_state_authority is (
            bundle.controller_state_authority
        )
        assert projection.source_root == scope.source_root
        assert projection.installed_controller_root == (
            scope.installed_controller_root
        )

        bundle.landing_issuer.revokeRunAdmission(bundle.run_admission)

        with pytest.raises(
            bootstrap.BootstrapAuthorityRefused,
            match="admission|live",
        ):
            projection.require_live()


def test_runtime_install_permit_refuses_an_exact_field_copy(
    tmp_path: Path,
) -> None:
    import platform_core.runtime.bootstrap_authority as bootstrap

    _scope_value, _result, outer = _consume_outer(
        tmp_path,
        suffix="runtime-install-copied-bundle",
    )
    bundle = bootstrap.deriveInstalledBootstrapAuthorities(
        outer_capabilities=outer
    )

    with pytest.raises(
        bootstrap.BootstrapAuthorityRefused,
        match="exact|live",
    ):
        with bootstrap._installedBootstrapRuntimePermit(replace(bundle)):
            raise AssertionError("copied bootstrap bundle entered the permit")


def test_runtime_install_poison_is_permanent_idempotent_and_blocks_replay(
    tmp_path: Path,
) -> None:
    import platform_core.runtime.bootstrap_authority as bootstrap
    import platform_core.runtime.candidate as candidate
    import platform_core.runtime.controller_state as state

    _scope_value, _result, outer = _consume_outer(
        tmp_path,
        suffix="runtime-install-permanent-poison",
    )
    bundle = bootstrap.deriveInstalledBootstrapAuthorities(
        outer_capabilities=outer
    )
    controller = bundle.controller_state_authority
    issuer = bundle.landing_issuer
    admission = bundle.run_admission

    with pytest.raises(
        bootstrap.BootstrapAuthorityRefused,
        match="exact|live",
    ):
        bootstrap._poisonInstalledBootstrapAuthorities(
            replace(bundle),
            reason="copied runtime-install failure",
        )

    bootstrap._poisonInstalledBootstrapAuthorities(
        bundle,
        reason="postcommit runtime-install failure",
    )
    bootstrap._poisonInstalledBootstrapAuthorities(
        bundle,
        reason="postcommit runtime-install failure",
    )

    with pytest.raises(
        bootstrap.BootstrapAuthorityRefused,
        match="live|poison|revok",
    ):
        bootstrap.validateInstalledBootstrapAuthorities(bundle)
    with pytest.raises(state.ControllerStateRefused, match="issuer|live|revok"):
        state.validateControllerStateAuthority(controller)
    with pytest.raises(candidate.LandingAuthorityRefused, match="live|bootstrap"):
        issuer._validateAdmission(admission)
    with pytest.raises(
        bootstrap.BootstrapAuthorityRefused,
        match="poison",
    ):
        bootstrap.deriveInstalledBootstrapAuthorities(
            outer_capabilities=outer
        )
