"""Config knobs + (Task 4) router fallback discipline."""
import importlib
import inspect
from unittest import mock

import config

from platform_core.execution import router
from platform_core.execution.backends.local import LocalEnvironment


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


def test_explicit_nonlocal_refuses_when_fabric_disabled():
    with mock.patch.object(config, "EXECUTION_FABRIC_ENABLED", False):
        with __import__("pytest").raises(_unavailable()):
            router.selectEnvironment({}, {"execution_backend": "docker"}, None)


def test_unknown_backend_is_typed_unavailable():
    with mock.patch.object(config, "EXECUTION_FABRIC_ENABLED", True), \
         mock.patch.object(config, "EXECUTION_BACKEND", "local"):
        with __import__("pytest").raises(_unavailable()):
            router.selectEnvironment({}, {"execution_backend": "does-not-exist"}, None)


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
        router.selectEnvironment({"risk_tier": "hostile"}, {}, None,
                                 trust_grant=grant, trust_scope=scope,
                                 trust_authority=authority)
    lookup.assert_called_once()  # a live grant may be tightened to the stronger configured tier


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
