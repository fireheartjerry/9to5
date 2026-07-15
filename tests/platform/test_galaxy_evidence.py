from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
import json
from pathlib import Path

import pytest

from platform_core.core.galaxy_evidence import (
    AnalysisReceipt,
    ArtifactDigest,
    AssignmentReceipt,
    BehaviorCapability,
    CapacityTruth,
    EvidenceGate,
    EvidenceFreshness,
    EvidenceState,
    ExperimentManifest,
    ObservationReceipt,
    PromotionRecommendation,
    ProviderBillingMode,
    RollbackReceipt,
    SyntheticMetric,
    TruthGap,
    TruthGapLedgerError,
    ZeroCostRunPolicy,
    deterministic_seed,
    load_truth_gap_ledger,
    verify_truth_gap_ledger,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
REVISION = "1" * 40
WHEN = "2026-07-14T12:00:00Z"


def _manifest() -> ExperimentManifest:
    return ExperimentManifest(
        experiment_id="clarification-shadow-v1",
        policy_version="galaxy-r3-wave0",
        provider_cohort=("local", "subscription"),
        fixture_digest=SHA_A,
        primary_endpoint="wrong_path_execution",
        seeds=(11, 29, 47),
        created_at=WHEN,
    )


def _assignment() -> AssignmentReceipt:
    return AssignmentReceipt(
        manifest_id=_manifest().receipt_id,
        unit_id="fixture-0042",
        treatment="preplanning-probe",
        assignment_probability=Decimal("0.5"),
        seed=29,
        policy_version="galaxy-r3-wave0",
        provider="local",
        capability_profile_id="read-only-snapshot-v1",
        quota_state=CapacityTruth.AVAILABLE,
        source_revision=REVISION,
        fixture_digest=SHA_A,
        assigned_at=WHEN,
    )


def _observation() -> ObservationReceipt:
    assignment = _assignment()
    return ObservationReceipt.from_assignment(
        assignment,
        outcome=(
            ("blocked", False),
            ("wrong_path", False),
        ),
        observed_at=WHEN,
    )


def test_truth_gap_registry_is_stable_and_complete() -> None:
    assert len(TruthGap) == 15
    assert TruthGap.COMPLETION_BEFORE_COLLECTION.evidence_id == "galaxy.truth-gap.01.v1"
    assert TruthGap.IMPORT_BEFORE_ADMISSION.evidence_id == "galaxy.truth-gap.15.v1"
    assert len({gap.evidence_id for gap in TruthGap}) == 15


def test_evidence_freshness_binds_source_tests_and_fixture() -> None:
    evidence = EvidenceFreshness(
        truth_gap=TruthGap.UNENFORCED_ZERO_COST,
        state=EvidenceState.IMPLEMENTED_DARK,
        source_revision=REVISION,
        source_paths=(ArtifactDigest("platform_core/runtime/action_risk.py", SHA_A),),
        test_paths=(ArtifactDigest("tests/platform/test_galaxy_evidence.py", SHA_B),),
        fixture_digest=SHA_A,
        observed_at=WHEN,
    )

    assert evidence.evidence_id == "galaxy.truth-gap.07.v1"
    assert evidence.is_fresh(
        source_revision=REVISION,
        path_digests={
            "platform_core/runtime/action_risk.py": SHA_A,
            "tests/platform/test_galaxy_evidence.py": SHA_B,
        },
        fixture_digest=SHA_A,
    )
    assert not evidence.is_fresh(
        source_revision=REVISION,
        path_digests={
            "platform_core/runtime/action_risk.py": SHA_B,
            "tests/platform/test_galaxy_evidence.py": SHA_B,
        },
        fixture_digest=SHA_A,
    )


@pytest.mark.parametrize(
    ("billing_mode", "price", "quota", "capacity", "reason"),
    [
        (ProviderBillingMode.API_KEY, Decimal("0"), CapacityTruth.AVAILABLE,
         CapacityTruth.AVAILABLE, "external-spend-forbidden"),
        (ProviderBillingMode.UNKNOWN, None, CapacityTruth.AVAILABLE,
         CapacityTruth.AVAILABLE, "billing-mode-unknown"),
        (ProviderBillingMode.SUBSCRIPTION, None, CapacityTruth.AVAILABLE,
         CapacityTruth.AVAILABLE, "price-unknown"),
        (ProviderBillingMode.SUBSCRIPTION, Decimal("0"), CapacityTruth.UNKNOWN,
         CapacityTruth.AVAILABLE, "quota-unknown"),
        (ProviderBillingMode.LOCAL, Decimal("0"), CapacityTruth.AVAILABLE,
         CapacityTruth.UNKNOWN, "capacity-unknown"),
    ],
)
def test_zero_cost_preflight_fails_closed(
    billing_mode: ProviderBillingMode,
    price: Decimal | None,
    quota: CapacityTruth,
    capacity: CapacityTruth,
    reason: str,
) -> None:
    decision = ZeroCostRunPolicy().preflight(
        billing_mode=billing_mode,
        price_usd=price,
        quota_state=quota,
        capacity_state=capacity,
    )

    assert decision.allowed is False
    assert decision.reason == reason
    assert decision.external_spend_allowed is False


@pytest.mark.parametrize("billing_mode", [ProviderBillingMode.LOCAL, ProviderBillingMode.SUBSCRIPTION])
def test_zero_cost_preflight_allows_known_zero_cost_capacity(billing_mode: ProviderBillingMode) -> None:
    decision = ZeroCostRunPolicy().preflight(
        billing_mode=billing_mode,
        price_usd=Decimal("0"),
        quota_state=CapacityTruth.AVAILABLE,
        capacity_state=CapacityTruth.AVAILABLE,
    )
    assert decision.allowed is True
    assert decision.reason == "admitted-zero-cost"


def test_external_spend_policy_cannot_be_enabled() -> None:
    with pytest.raises(ValueError, match="external spend is frozen off"):
        ZeroCostRunPolicy(external_spend_allowed=True)


def test_seed_registry_is_deterministic_and_domain_separated() -> None:
    assert deterministic_seed("exp-a", "unit-7", 3) == deterministic_seed("exp-a", "unit-7", 3)
    assert deterministic_seed("exp-a", "unit-7", 3) != deterministic_seed("exp-a", "unit-7", 4)
    assert deterministic_seed("exp-a", "unit-7", 3) != deterministic_seed("exp-b", "unit-7", 3)


def test_manifest_is_immutable_canonical_and_shadow_only() -> None:
    manifest = _manifest()
    assert manifest.shadow_only is True
    assert manifest.receipt_id == _manifest().receipt_id
    with pytest.raises(FrozenInstanceError):
        manifest.primary_endpoint = "changed"  # type: ignore[misc]
    with pytest.raises(ValueError, match="shadow_only"):
        replace(manifest, shadow_only=False)


@pytest.mark.parametrize("probability", [Decimal("0"), Decimal("-0.1"), Decimal("1.01")])
def test_assignment_probability_is_closed(probability: Decimal) -> None:
    with pytest.raises(ValueError, match="assignment_probability"):
        replace(_assignment(), assignment_probability=probability)


def test_observation_carries_all_assignment_provenance() -> None:
    assignment = _assignment()
    observation = _observation()

    assert observation.assignment_id == assignment.receipt_id
    assert observation.policy_version == assignment.policy_version
    assert observation.provider == assignment.provider
    assert observation.assignment_probability == assignment.assignment_probability
    assert observation.capability_profile_id == assignment.capability_profile_id
    assert observation.quota_state == assignment.quota_state
    assert observation.source_revision == assignment.source_revision
    assert observation.fixture_digest == assignment.fixture_digest
    assert observation.parent_receipt_ids == (assignment.receipt_id,)


def test_complete_shadow_receipt_chain_is_content_addressed() -> None:
    observation = _observation()
    analysis = AnalysisReceipt(
        manifest_id=_manifest().receipt_id,
        observation_ids=(observation.receipt_id,),
        analyst_identity="independent-local-analysis-v1",
        primary_endpoint="wrong_path_execution",
        estimate=Decimal("-0.12"),
        confidence_interval=(Decimal("-0.20"), Decimal("-0.04")),
        analyzed_at=WHEN,
    )
    recommendation = PromotionRecommendation(
        analysis_id=analysis.receipt_id,
        recommendation="continue-shadow",
        reason="minimum sample size not met",
        recommended_at=WHEN,
    )
    rollback = RollbackReceipt(
        recommendation_id=recommendation.receipt_id,
        rollback_target="incumbent-c16bbebe",
        reason="shadow campaign complete",
        rolled_back_at=WHEN,
    )

    assert analysis.parent_receipt_ids == (observation.receipt_id,)
    assert recommendation.parent_receipt_ids == (analysis.receipt_id,)
    assert rollback.parent_receipt_ids == (recommendation.receipt_id,)
    assert all(r.shadow_only for r in (observation, analysis, recommendation, rollback))
    assert len({r.receipt_id for r in (observation, analysis, recommendation, rollback)}) == 4


def test_synthetic_metrics_are_unknown_until_measured() -> None:
    metric = SyntheticMetric.unknown("qd-diversity", reason="legacy constant")
    assert metric.value is None
    assert metric.known is False
    with pytest.raises(ValueError, match="verified measurement"):
        SyntheticMetric(name="qd-diversity", value=Decimal("1"), measurement_receipt_id=None)


def test_behavior_capabilities_have_explicit_closed_evidence_keys() -> None:
    assert {
        capability.value
        for capability in BehaviorCapability
    } >= {
        "human-nature-couplings",
        "external-council-seats",
        "adaptive-evolution",
        "society",
        "solution-fork",
        "execution-fabric",
    }
    assert len({capability.evidence_key for capability in BehaviorCapability}) == len(BehaviorCapability)


def test_full_stack_cannot_grant_authority_when_evidence_policy_is_enforced() -> None:
    decision = EvidenceGate.evaluate(
        capability=BehaviorCapability.HUMAN_NATURE_COUPLINGS,
        legacy_enabled=True,
        policy_enforced=True,
        evidence_state=EvidenceState.QUALIFIED,
        activation_receipt_id=None,
    )
    assert decision.allowed is False
    assert decision.reason == "activation-receipt-required"


def test_evidence_state_alone_never_implies_runtime_authority() -> None:
    decision = EvidenceGate.evaluate(
        capability=BehaviorCapability.ADAPTIVE_EVOLUTION,
        legacy_enabled=True,
        policy_enforced=True,
        evidence_state=EvidenceState.QUALIFIED,
        activation_receipt_id=SHA_A,
    )
    assert decision.allowed is False
    assert decision.reason == "evidence-not-active"


def test_active_evidence_and_external_activation_receipt_can_admit() -> None:
    decision = EvidenceGate.evaluate(
        capability=BehaviorCapability.SOCIETY,
        legacy_enabled=True,
        policy_enforced=True,
        evidence_state=EvidenceState.ACTIVE,
        activation_receipt_id=SHA_A,
    )
    assert decision.allowed is True
    assert decision.reason == "externally-activated"
    assert decision.authority_receipt_id == SHA_A


def test_shadow_gate_preserves_the_pinned_incumbent_behavior() -> None:
    decision = EvidenceGate.evaluate(
        capability=BehaviorCapability.EXECUTION_FABRIC,
        legacy_enabled=True,
        policy_enforced=False,
        evidence_state=EvidenceState.SPECIFIED,
        activation_receipt_id=None,
    )
    assert decision.allowed is True
    assert decision.reason == "incumbent-baseline"
    assert decision.shadow_observation is True


def test_repository_truth_gap_ledger_is_complete_and_fresh() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    records = load_truth_gap_ledger(repo_root / "config/galaxy/truth-gaps.v1.json")
    report = verify_truth_gap_ledger(repo_root=repo_root, records=records)
    assert len(records) == 15
    assert {record.truth_gap for record in records} == set(TruthGap)
    dark_gaps = {TruthGap.SYNTHETIC_METRICS, TruthGap.ALL_ON_ACTIVATION}
    assert all(
        next(record for record in records if record.truth_gap is gap).state
        is EvidenceState.IMPLEMENTED_DARK
        for gap in dark_gaps
    )
    assert all(
        record.state is EvidenceState.SPECIFIED
        for record in records
        if record.truth_gap not in dark_gaps
    )
    assert report.valid is True
    assert report.stale_evidence_ids == ()


def test_truth_gap_ledger_detects_stale_source_hash(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    source = repo_root / "config/galaxy/truth-gaps.v1.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["truth_gaps"][0]["source_paths"][0]["sha256"] = SHA_B
    altered = tmp_path / "truth-gaps.v1.json"
    altered.write_text(json.dumps(payload), encoding="utf-8")

    report = verify_truth_gap_ledger(
        repo_root=repo_root,
        records=load_truth_gap_ledger(altered),
    )
    assert report.valid is False
    assert report.stale_evidence_ids == ("galaxy.truth-gap.01.v1",)


def test_truth_gap_ledger_rejects_missing_gap(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    source = repo_root / "config/galaxy/truth-gaps.v1.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["truth_gaps"].pop()
    altered = tmp_path / "truth-gaps.v1.json"
    altered.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(TruthGapLedgerError, match="exactly the 15"):
        load_truth_gap_ledger(altered)
