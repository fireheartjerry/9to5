"""Config knobs + (Task 4) router fallback discipline."""
import importlib
import inspect
from types import SimpleNamespace
from unittest import mock

import config
import pytest
from platform_core.execution import environment as environment_contracts
from platform_core.execution import router, wiring
from platform_core.execution.backends.clone import CloneEnvironment
from platform_core.execution.backends.local import LocalEnvironment
from platform_core.execution.environment import (
    EnvHandle,
    EnvironmentUnavailable,
    ExecutionContext,
    ResolvedExecutionPolicy,
)
from platform_core.execution.launch_guard import TransactionalKernelInactive


def _trust_authority(mod, tmp_path):
    return mod.OperatorTrustAuthority(
        issuer_id="operator-router-test", revocation_generation=1,
        process_capability=object(), evidence_store=tmp_path / "trust.sqlite",
    )


def test_execution_config_defaults_to_today(monkeypatch):
    monkeypatch.setenv("FULL_STACK", "0")   # master off -> assert the conservative ship-dark fallback
    # R12: assert the CODED defaults (env scrubbed) -- a production install .env may
    # legitimately enable the fabric; the router behavior tests below cover both states.
    for k in ("EXECUTION_FABRIC_ENABLED", "EXECUTION_BACKEND", "EXECUTION_REMOTE_KIND",
              "DOCKER_EXECUTOR_IMAGE", "EXECUTION_PROVISION_TIMEOUT_SECONDS"):
        monkeypatch.delenv(k, raising=False)
    from platform_core.app_config.settings import EpicFlags
    flags = EpicFlags()
    assert flags.EXECUTION_FABRIC_ENABLED is False      # master gate OFF by default
    assert flags.EXECUTION_BACKEND == "local"           # default backend
    assert flags.EXECUTION_BACKEND_BY_RISK == {}        # empty until Epic 4 lands
    assert flags.EXECUTION_REMOTE_KIND in ("ssh", "modal", "daytona", "e2b")
    assert flags.EXECUTION_PROVISION_TIMEOUT_SECONDS > 0
    # Facade exposure stays live (env-layered).
    assert isinstance(config.EXECUTION_BACKEND_BY_RISK, dict)
    assert isinstance(config.DOCKER_EXECUTOR_IMAGE, str) and config.DOCKER_EXECUTOR_IMAGE
    assert isinstance(config.EXECUTION_PROVISION_TIMEOUT_SECONDS, int)


def _unavailable():
    return importlib.import_module("platform_core.execution.environment").EnvironmentUnavailable


def _local_clone_policy() -> ResolvedExecutionPolicy:
    return ResolvedExecutionPolicy(
        requested_backend="worktree",
        runner_kind="local",
        landing_backend="clone",
        read_only=False,
    )


def _validated_trust(receipt_id: str = "trust-receipt-1") -> SimpleNamespace:
    return SimpleNamespace(receipt_id=receipt_id)


def test_wiring_maps_worktree_to_local_runner_clone_landing_without_side_effects():
    state = SimpleNamespace(meta={})
    with (
        mock.patch.object(wiring, "requireTransactionalKernelActive") as guard,
        mock.patch.object(wiring._env_router, "selectEnvironment") as select,
        mock.patch.object(wiring._env_router, "provision") as provision,
    ):
        policy = wiring.resolveExecutionPolicy(
            state,
            {"execution_backend": "worktree"},
        )

    assert type(policy) is ResolvedExecutionPolicy
    assert (
        policy.requested_backend,
        policy.runner_kind,
        policy.landing_backend,
        policy.read_only,
    ) == ("worktree", "local", "clone", False)
    guard.assert_not_called()
    select.assert_not_called()
    provision.assert_not_called()


def test_wiring_refuses_mutating_remote_before_guard_router_or_resources():
    state = SimpleNamespace(meta={})
    with (
        mock.patch.object(wiring, "requireTransactionalKernelActive") as guard,
        mock.patch.object(wiring._env_router, "selectEnvironment") as select,
        mock.patch.object(wiring._env_router, "provision") as provision,
        pytest.raises(EnvironmentUnavailable, match="remote.*sealed candidate") as raised,
    ):
        wiring.resolveExecutionPolicy(state, {"execution_backend": "remote"})

    assert raised.value.backend == "remote"
    guard.assert_not_called()
    select.assert_not_called()
    provision.assert_not_called()


def test_provision_for_attempt_checks_immutable_guard_before_router_calls():
    with (
        mock.patch.object(
            wiring,
            "requireTransactionalKernelActive",
            side_effect=TransactionalKernelInactive("sealed inactive kernel"),
        ) as guard,
        mock.patch.object(wiring._env_router, "selectEnvironment") as select,
        mock.patch.object(wiring._env_router, "provision") as provision,
        pytest.raises(TransactionalKernelInactive, match="inactive kernel"),
    ):
        wiring.provisionForAttempt(
            _local_clone_policy(),
            "attempt-1",
            transaction_id="transaction-1",
            state=SimpleNamespace(meta={}),
            subtask={"subtask_id": "subtask-1"},
            exec_cwd="/canonical",
        )

    guard.assert_called_once_with()
    select.assert_not_called()
    provision.assert_not_called()


def test_local_runner_without_exact_trust_refuses_before_landing_resolution():
    events = []

    def refuse_trust(*args, **kwargs):
        del args, kwargs
        events.append("validate-trust")
        raise EnvironmentUnavailable("local", "exact live workload trust is required")

    def legacy_select(*args, **kwargs):
        del args, kwargs
        events.append("legacy-select")
        raise EnvironmentUnavailable("clone", "legacy selection was reached")

    with (
        mock.patch.object(wiring, "requireTransactionalKernelActive"),
        mock.patch.object(
            router,
            "validateLocalRunnerEligibility",
            side_effect=refuse_trust,
            create=True,
        ) as validate,
        mock.patch.object(
            router,
            "resolveInstalledLandingEnvironment",
            create=True,
        ) as resolve_landing,
        mock.patch.object(router, "selectEnvironment", side_effect=legacy_select) as select,
        mock.patch.object(router, "provision") as provision,
        pytest.raises(EnvironmentUnavailable),
    ):
        wiring.provisionForAttempt(
            _local_clone_policy(),
            "attempt-1",
            transaction_id="transaction-1",
            state=SimpleNamespace(task_id="task-1", meta={}),
            subtask={"subtask_id": "subtask-1"},
            exec_cwd="/canonical",
            backend_registry=object(),
        )

    assert events == ["validate-trust"]
    validate.assert_called_once()
    resolve_landing.assert_not_called()
    select.assert_not_called()
    provision.assert_not_called()


@pytest.mark.parametrize("fabric_enabled", (False, True))
def test_attempt_uses_installed_clone_landing_independently_of_fabric_flag(
    monkeypatch,
    fabric_enabled,
):
    monkeypatch.setattr(config, "EXECUTION_FABRIC_ENABLED", fabric_enabled)
    events = []
    registry = object()
    environment = SimpleNamespace(NAME="clone", teardown=mock.Mock())
    lease = SimpleNamespace(
        attempt_id="attempt-1",
        transaction_id="transaction-1",
        task_id="task-1",
        subtask_id="subtask-1",
        runner_kind="local",
    )
    handle = EnvHandle(work_dir="/candidate", backend="clone", runtime_token=lease)

    def validate(*args, **kwargs):
        del args, kwargs
        events.append("validate-trust")
        return _validated_trust()

    def resolve(*args, **kwargs):
        del args, kwargs
        events.append("resolve-installed-landing")
        return environment

    def legacy_select(*args, **kwargs):
        del args, kwargs
        events.append("legacy-select")
        return environment

    def provision(*args, **kwargs):
        del args, kwargs
        events.append("provision")
        return environment, handle

    with (
        mock.patch.object(wiring, "requireTransactionalKernelActive"),
        mock.patch.object(
            router,
            "validateLocalRunnerEligibility",
            side_effect=validate,
            create=True,
        ),
        mock.patch.object(
            router,
            "resolveInstalledLandingEnvironment",
            side_effect=resolve,
            create=True,
        ) as resolve_landing,
        mock.patch.object(router, "selectEnvironment", side_effect=legacy_select) as select,
        mock.patch.object(router, "provision", side_effect=provision),
    ):
        context = wiring.provisionForAttempt(
            _local_clone_policy(),
            lease.attempt_id,
            transaction_id=lease.transaction_id,
            state=SimpleNamespace(task_id=lease.task_id, meta={}),
            subtask={"subtask_id": lease.subtask_id},
            exec_cwd="/canonical",
            backend_registry=registry,
            trust_grant=object(),
            trust_scope={"task_id": lease.task_id},
            trust_authority=object(),
        )

    assert type(context) is ExecutionContext
    assert events == ["validate-trust", "resolve-installed-landing", "provision"]
    resolve_landing.assert_called_once_with(registry, backend="clone")
    select.assert_not_called()


@pytest.mark.parametrize("requested_backend", ("local", "worktree"))
def test_provision_for_attempt_removes_task_routing_override_before_clone_selection(
    tmp_path,
    requested_backend,
):
    state = SimpleNamespace(task_id="task-1", meta={})
    subtask = {
        "subtask_id": "subtask-1",
        "title": "preserved title",
        "metadata": {"preserved": True},
        "execution_backend": requested_backend,
    }
    policy = wiring.resolveExecutionPolicy(state, subtask)
    environment = SimpleNamespace(NAME="clone", teardown=mock.Mock())
    handle = EnvHandle(
        work_dir=str(tmp_path / "candidate"),
        backend="clone",
        runtime_token=SimpleNamespace(
            attempt_id="attempt-1",
            transaction_id="transaction-1",
            task_id="task-1",
            subtask_id="subtask-1",
            runner_kind="local",
        ),
    )
    captured = {}

    def provision(selected, **kwargs):
        captured["environment"] = selected
        captured["subtask"] = kwargs["subtask"]
        return selected, handle

    with (
        mock.patch.object(wiring, "requireTransactionalKernelActive"),
        mock.patch.object(
            wiring._env_router,
            "validateLocalRunnerEligibility",
            return_value=_validated_trust(),
        ),
        mock.patch.object(
            wiring._env_router,
            "resolveInstalledLandingEnvironment",
            return_value=environment,
        ) as resolve_landing,
        mock.patch.object(wiring._env_router, "selectEnvironment") as select,
        mock.patch.object(
            wiring._env_router,
            "provision",
            side_effect=provision,
        ),
    ):
        wiring.provisionForAttempt(
            policy,
            "attempt-1",
            transaction_id="transaction-1",
            state=state,
            subtask=subtask,
            exec_cwd=str(tmp_path / "canonical"),
            backend_registry=object(),
        )

    assert captured == {
        "environment": environment,
        "subtask": {
            "subtask_id": "subtask-1",
            "title": "preserved title",
            "metadata": {"preserved": True},
        },
    }
    resolve_landing.assert_called_once()
    select.assert_not_called()


@pytest.mark.parametrize(
    ("field", "foreign_value"),
    (
        ("attempt_id", "attempt-other"),
        ("transaction_id", "transaction-other"),
        ("task_id", "task-other"),
        ("subtask_id", "subtask-other"),
        ("runner_kind", "docker"),
    ),
)
def test_provision_for_attempt_refuses_foreign_lease_without_direct_teardown(
    field,
    foreign_value,
):
    environment = SimpleNamespace(NAME="clone", teardown=mock.Mock())
    lease_identity = {
        "attempt_id": "attempt-1",
        "transaction_id": "transaction-1",
        "task_id": "task-1",
        "subtask_id": "subtask-1",
        "runner_kind": "local",
    }
    lease_identity[field] = foreign_value
    handle = EnvHandle(
        work_dir="/candidate",
        backend="clone",
        runtime_token=SimpleNamespace(**lease_identity),
    )
    with (
        mock.patch.object(wiring, "requireTransactionalKernelActive"),
        mock.patch.object(
            router,
            "validateLocalRunnerEligibility",
            return_value=_validated_trust(),
            create=True,
        ),
        mock.patch.object(
            router,
            "resolveInstalledLandingEnvironment",
            return_value=environment,
            create=True,
        ),
        mock.patch.object(wiring._env_router, "selectEnvironment", return_value=environment),
        mock.patch.object(wiring._env_router, "provision", return_value=(environment, handle)),
        pytest.raises(EnvironmentUnavailable, match="identity differs") as raised,
    ):
        wiring.provisionForAttempt(
            _local_clone_policy(),
            "attempt-1",
            transaction_id="transaction-1",
            state=SimpleNamespace(task_id="task-1", meta={}),
            subtask={"subtask_id": "subtask-1"},
            exec_cwd="/canonical",
            backend_registry=object(),
            trust_grant=object(),
            trust_scope={"task_id": "task-1"},
            trust_authority=object(),
        )

    assert raised.value.backend == "clone"
    environment.teardown.assert_not_called()


def test_provision_for_attempt_passes_frozen_typed_identity_scope_to_router(tmp_path):
    captured = {}
    environment = SimpleNamespace(NAME="clone", teardown=mock.Mock())
    lease = SimpleNamespace(
        attempt_id="attempt-1",
        transaction_id="transaction-1",
        task_id="task-1",
        subtask_id="subtask-1",
        runner_kind="local",
    )
    handle = EnvHandle(
        work_dir=str(tmp_path / "candidate"),
        backend="clone",
        runtime_token=lease,
    )

    def provision(selected, **kwargs):
        captured["environment"] = selected
        captured["scope"] = kwargs["policy"]
        return selected, handle

    with (
        mock.patch.object(wiring, "requireTransactionalKernelActive"),
        mock.patch.object(
            wiring._env_router,
            "validateLocalRunnerEligibility",
            return_value=_validated_trust(),
        ),
        mock.patch.object(
            wiring._env_router,
            "resolveInstalledLandingEnvironment",
            return_value=environment,
        ),
        mock.patch.object(wiring._env_router, "selectEnvironment") as select,
        mock.patch.object(wiring._env_router, "provision", side_effect=provision),
    ):
        context = wiring.provisionForAttempt(
            _local_clone_policy(),
            lease.attempt_id,
            transaction_id=lease.transaction_id,
            state=SimpleNamespace(task_id=lease.task_id, meta={}),
            subtask={"subtask_id": lease.subtask_id},
            exec_cwd=str(tmp_path / "canonical"),
            backend_registry=object(),
        )

    assert type(context) is ExecutionContext
    scope_type = getattr(environment_contracts, "AttemptProvisionScope", None)
    assert scope_type is not None, "router provisioning lacks a typed per-attempt identity scope"
    scope = captured["scope"]
    assert type(scope) is scope_type
    assert scope.attempt_id == lease.attempt_id
    assert scope.transaction_id == lease.transaction_id
    assert scope.task_id == lease.task_id
    assert scope.subtask_id == lease.subtask_id
    assert scope.runner_kind == lease.runner_kind
    assert scope.trust_receipt_id == "trust-receipt-1"
    assert scope_type.__dataclass_params__.frozen is True
    select.assert_not_called()


def test_explicit_nonlocal_refuses_when_fabric_disabled():
    with mock.patch.object(config, "EXECUTION_FABRIC_ENABLED", False):
        with __import__("pytest").raises(_unavailable()):
            router.selectEnvironment({}, {"execution_backend": "docker"}, None)


def test_unknown_backend_is_typed_unavailable():
    with mock.patch.object(config, "EXECUTION_FABRIC_ENABLED", True), \
         mock.patch.object(config, "EXECUTION_BACKEND", "local"):
        with __import__("pytest").raises(_unavailable()):
            router.selectEnvironment({}, {"execution_backend": "does-not-exist"}, None)


def test_transactional_clone_route_requires_controller_owned_composition(monkeypatch):
    monkeypatch.setattr(config, "EXECUTION_FABRIC_ENABLED", True)
    with __import__("pytest").raises(_unavailable(), match="clone.*composition"):
        router.selectEnvironment({}, {"execution_backend": "clone"}, None)


def test_controller_composition_routes_clone_and_legacy_worktree_without_rebuild(
    monkeypatch,
):
    monkeypatch.setattr(config, "EXECUTION_FABRIC_ENABLED", True)
    clone = CloneEnvironment(clone_factory=lambda **_: None, kernel=object())
    registry = router._buildDiagnosticExecutionBackendRegistry(clone)

    selected = router.selectEnvironment(
        {},
        {"execution_backend": "clone"},
        None,
        backend_registry=registry,
    )
    assert selected is clone

    legacy = router.selectEnvironment(
        {},
        {"execution_backend": "worktree"},
        None,
        backend_registry=registry,
    )
    assert legacy.clone_environment is clone
    assert legacy.healthCheck() is True


def test_false_health_check_is_typed_unavailable():
    class _Unhealthy(LocalEnvironment):
        NAME = "unhealthy"
        def healthCheck(self):
            return False
    with mock.patch.object(config, "EXECUTION_FABRIC_ENABLED", True), \
         mock.patch.object(router, "_backendClass", return_value=_Unhealthy):
        with __import__("pytest").raises(_unavailable()):
            router.selectEnvironment({}, {"execution_backend": "unhealthy"}, None)


def test_provision_failure_is_typed_and_never_falls_back():
    class _Boom(LocalEnvironment):
        NAME = "boom"
        def provision(self, *, task_state, subtask, base_dir, policy):
            raise RuntimeError("provision blew up")
    with mock.patch.object(router, "LocalEnvironment") as local, \
         __import__("pytest").raises(_unavailable()):
        router.provision(_Boom(), task_state=None, subtask={"subtask_id": "s1"},
                         base_dir="/repo")
    local.assert_not_called()


def test_provision_success_returns_same_env_and_handle():
    env, handle = router.provision(LocalEnvironment(), task_state=None,
                                   subtask=None, base_dir="/repo")
    assert isinstance(env, LocalEnvironment) and handle.work_dir == "/repo"


def test_finalize_calls_collect_then_teardown():
    calls = []
    class _Spy(LocalEnvironment):
        def collectChanges(self, handle, *, task_state, subtask):
            calls.append("collect")
            return {"backend": "spy", "merged": True}
        def teardown(self, handle):
            calls.append("teardown")
    env = _Spy()
    handle = env.provision(task_state=None, subtask=None, base_dir="/repo", policy=None)
    summary = router.finalize(env, handle, None, None)
    assert calls == ["collect", "teardown"]
    assert summary == {"backend": "spy", "merged": True}


# --- Task 13: backend tag in surfaces_used (SIE learning, non-load-bearing) ---
import platform_core.core.surfaces as surfaces


def test_surfaces_used_tags_backend():
    used = surfaces.surfaces_used({"prompt": "do x", "execution_backend": "worktree"})
    assert "backend:worktree" in used


def test_surfaces_used_no_backend_tag_by_default():
    used = surfaces.surfaces_used({"prompt": "do x"})
    assert not any(t.startswith("backend:") for t in used)


def test_local_without_live_scope_bound_grant_is_typed_refusal():
    with mock.patch.object(config, "EXECUTION_FABRIC_ENABLED", False):
        with __import__("pytest").raises(_unavailable()):
            router.selectEnvironment({}, {"execution_backend": "local"}, None)


def test_implicit_and_explicit_local_succeed_only_with_exact_live_grant(tmp_path):
    trust_mod = importlib.import_module("platform_core.runtime.execution_trust")
    authority = _trust_authority(trust_mod, tmp_path)
    scope = dict(repository_attestation_digest="repo", expected_base_sha="a" * 40,
                 task_id="task", acceptance_spec_digest="spec",
                 capability_profile="trusted_local")
    grant = authority.issueWorkloadGrant(**scope)
    for subtask in ({}, {"execution_backend": "local"}):
        with mock.patch.object(config, "EXECUTION_FABRIC_ENABLED", False):
            env = router.selectEnvironment({}, subtask, None, trust_grant=grant,
                                           trust_scope=scope, trust_authority=authority)
        assert isinstance(env, LocalEnvironment)


@__import__("pytest").mark.parametrize(("field", "value"), [
    ("repository_attestation_digest", "wrong"), ("expected_base_sha", "b" * 40),
    ("task_id", "wrong"), ("acceptance_spec_digest", "wrong"),
    ("capability_profile", "read_only"),
])
def test_local_scope_attacks_refuse_before_backend_lookup_or_provision(tmp_path, field, value):
    trust_mod = importlib.import_module("platform_core.runtime.execution_trust")
    authority = _trust_authority(trust_mod, tmp_path)
    scope = dict(repository_attestation_digest="repo", expected_base_sha="a" * 40,
                 task_id="task", acceptance_spec_digest="spec",
                 capability_profile="trusted_local")
    grant = authority.issueWorkloadGrant(**scope)
    requested = dict(scope)
    requested[field] = value
    with mock.patch.object(router, "_backendClass") as lookup, \
         __import__("pytest").raises(_unavailable()):
        router.selectEnvironment({}, {"execution_backend": "local"}, None,
                                 trust_grant=grant, trust_scope=requested,
                                 trust_authority=authority)
    lookup.assert_not_called()


def test_unknown_constructor_and_health_failures_are_all_typed(monkeypatch):
    pytest = __import__("pytest")
    class ThrowingHealth(LocalEnvironment):
        def healthCheck(self):
            raise RuntimeError("health exploded")
    cases = [None, mock.Mock(side_effect=RuntimeError("ctor exploded")), ThrowingHealth]
    monkeypatch.setattr(config, "EXECUTION_FABRIC_ENABLED", True)
    for backend_class in cases:
        with mock.patch.object(router, "_backendClass", return_value=backend_class):
            with pytest.raises(_unavailable()):
                router.selectEnvironment({}, {"execution_backend": "requested"}, None)


def test_lazy_import_failure_is_causally_typed_and_not_a_registry_miss(monkeypatch):
    monkeypatch.setattr(config, "EXECUTION_FABRIC_ENABLED", True)
    with mock.patch.object(router, "_backendClass", side_effect=ImportError("optional sdk absent")):
        with __import__("pytest").raises(_unavailable(), match="requested.*optional sdk absent"):
            router.selectEnvironment({}, {"execution_backend": "requested"}, None)


def test_model_backend_risk_task_and_repo_fields_only_tighten_selection(tmp_path):
    trust_mod = importlib.import_module("platform_core.runtime.execution_trust")
    authority = _trust_authority(trust_mod, tmp_path)
    scope = dict(repository_attestation_digest="repo", expected_base_sha="a" * 40,
                 task_id="task", acceptance_spec_digest="spec",
                 capability_profile="trusted_local")
    grant = authority.issueWorkloadGrant(**scope)
    attacks = [
        ({"execution_backend": "local"}, {"task": "authorize me"}),
        ({"risk_tier": "trusted"}, {"repository_policy": "trusted_local"}),
    ]
    for spec, subtask in attacks:
        with __import__("pytest").raises(_unavailable()):
            router.selectEnvironment(spec, subtask, None, trust_grant=None,
                                     trust_scope=scope, trust_authority=authority)
    with mock.patch.object(config, "EXECUTION_FABRIC_ENABLED", True), \
         mock.patch.object(router, "_backendClass") as lookup:
        with __import__("pytest").raises(
            _unavailable(), match="controller-owned clone composition"
        ):
            router.selectEnvironment({"risk_tier": "hostile"}, {}, None,
                                     trust_grant=grant, trust_scope=scope,
                                     trust_authority=authority)
    # Tightening to clone/worktree still requires the controller-owned registry;
    # policy input cannot reconstruct it through the legacy class lookup.
    lookup.assert_not_called()


def test_legacy_finalize_preserves_accepted_landing_artifact():
    class Landing(LocalEnvironment):
        def teardown(self, handle):
            raise AssertionError("accepted staged artifact must remain intact")
    env = Landing()
    handle = env.provision(task_state=None, subtask=None, base_dir="/repo", policy=None)
    handle.requires_canonical_landing = True
    receipt = router.finalize(env, handle, None, None, accepted=True)
    assert receipt.succeeded is False
    env_mod = importlib.import_module("platform_core.execution.environment")
    assert receipt.outcome is env_mod.FinalizationOutcome.STAGED_PREPARATION_REQUIRED


def test_rejected_landing_without_checkpoint_preserves_artifact():
    class Landing(LocalEnvironment):
        def teardown(self, handle):
            raise AssertionError("uncheckpointed artifact must not be destroyed")
    env = Landing()
    handle = env.provision(task_state=None, subtask=None, base_dir="/repo", policy=None)
    handle.requires_canonical_landing = True
    prepared = router.prepare(env, handle, None, None, accepted=False)
    assert prepared.error
    assert "recovery unavailable" in prepared.error.lower()
    assert prepared.summary.get("artifact_preserved") is True


def test_router_exposes_typed_prepare_then_authorized_complete_boundary():
    prepare = inspect.signature(router.prepare)
    complete = inspect.signature(router.complete)
    assert list(prepare.parameters) == ["env", "handle", "task_state", "subtask", "accepted"]
    assert prepare.parameters["accepted"].kind is inspect.Parameter.KEYWORD_ONLY
    assert list(complete.parameters) == [
        "env", "handle", "prepared", "authorization", "landing_authority",
    ]
    assert complete.parameters["authorization"].kind is inspect.Parameter.KEYWORD_ONLY
    assert complete.parameters["landing_authority"].kind is inspect.Parameter.KEYWORD_ONLY


def test_accepted_prepare_calls_staged_hook_and_complete_requires_evidence_plus_live_authority():
    env_mod = importlib.import_module("platform_core.execution.environment")
    calls = []
    prepared = env_mod.PreparedFinalization(
        accepted=True, requires_revision_verification=True, runtime_token=object())
    class Staged(LocalEnvironment):
        def prepareChanges(self, handle, *, task_state, subtask):
            calls.append("prepare")
            return prepared
        def completeChanges(self, *args, **kwargs):
            calls.append("complete")
            raise AssertionError("completion reached without both authorities")
    env = Staged()
    handle = env.provision(task_state=None, subtask=None, base_dir="/candidate", policy=None)
    handle.requires_canonical_landing = True
    assert router.prepare(env, handle, None, None, accepted=True) is prepared
    for authorization, landing in ((None, None), (object(), None), (None, object())):
        receipt = router.complete(env, handle, prepared, authorization=authorization,
                                  landing_authority=landing)
        assert receipt.outcome is env_mod.FinalizationOutcome.AUTHORIZATION_REQUIRED
    assert calls == ["prepare"]
