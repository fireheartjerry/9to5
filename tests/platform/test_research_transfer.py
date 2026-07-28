"""Fail-closed research-transfer intake for post-freeze discoveries."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, TypedDict

import pytest

from platform_core.core.galaxy_evidence import (
    EvidenceState,
    ExperimentManifest,
    canonical_digest,
)
from platform_core.core.research_transfer import (
    ResearchBlocker,
    ResearchClaim,
    ResearchControl,
    ResearchConsumer,
    ResearchQualificationContext,
    ResearchSourceClass,
    ResearchSourceStatus,
    ResearchTrialBinding,
    ResearchTrialAdmissionDecision,
    ResearchTransferLedgerError,
    ResearchTransferRecord,
    evaluate_research_trial,
    load_research_transfer_ledger,
)


SHA_A = "a" * 64
WHEN = "2026-07-19T18:00:00Z"
CONTEXT_CAPTURED = "2026-08-19T17:58:00Z"
CONTEXT_EXPIRES = "2026-08-19T18:03:00Z"
ISSUER_REVISION = "f" * 40
K3_CAPTURE = (
    "docs/superpowers/research/kimi-k3-last30days/"
    "kimi-k3-open-weight-model-architecture-benchmarks-integration-raw-v3.md"
)
K3_WIRE_ERRATUM = (
    "docs/superpowers/research/2026-07-20-kimi-k3-hosted-wire-erratum.md"
)
COUNCIL_CAPTURE = (
    "docs/superpowers/research/2026-07-20-llm-council-research-transfer.md"
)


class _BindingKwargs(TypedDict):
    trial_bindings: Mapping[str, ResearchTrialBinding]
    qualification_contexts: Mapping[str, ResearchQualificationContext]


class _AdmissionBaseKwargs(TypedDict):
    canonical_registry_entries: Mapping[str, str]
    experiment_manifests: Mapping[str, ExperimentManifest]
    trial_bindings: Mapping[str, ResearchTrialBinding]
    at_time: datetime


def _manifest() -> ExperimentManifest:
    return ExperimentManifest(
        experiment_id="fr01-followup-shadow-v1",
        policy_version="galaxy-r3-research-transfer-v1",
        provider_cohort=("deterministic-local",),
        fixture_digest="d" * 64,
        primary_endpoint="matched_p95_latency",
        seeds=(11, 29, 47),
        created_at=WHEN,
    )


def _registered_record() -> ResearchTransferRecord:
    url = "https://example.invalid/paper"
    claim = "The registered source reports a bounded scheduling mechanism."
    return ResearchTransferRecord(
        candidate_id="frontier.fr01.followup",
        registry_id="FR01",
        registry_entry_sha256="c" * 64,
        title="Registered scheduling follow-up",
        source_status=ResearchSourceStatus.PUBLIC_ARTIFACT,
        claims=(
            ResearchClaim(
                url=url,
                locator="Abstract",
                source_class=ResearchSourceClass.PRIMARY,
                retrieved_at=WHEN,
                claim=claim,
                source_response_sha256=SHA_A,
                source_artifact_path="docs/superpowers/research/fixture.md",
                source_artifact_sha256=SHA_A,
                claim_sha256=canonical_digest(
                    {
                        "claim": claim,
                        "locator": "Abstract",
                        "retrieved_at": WHEN,
                        "source_response_sha256": SHA_A,
                        "source_artifact_path": "docs/superpowers/research/fixture.md",
                        "source_artifact_sha256": SHA_A,
                        "source_class": ResearchSourceClass.PRIMARY,
                        "url": url,
                    }
                ),
            ),
        ),
        local_hypothesis="The mechanism may reduce matched tail latency.",
        proposed_consumers=(ResearchConsumer.PULSAR,),
        required_controls=(ResearchControl.PAIRED_REPLAY,),
        experiment_manifest_id=_manifest().receipt_id,
        falsifier="Reject if matched p95 latency or mission fairness regresses.",
        status_recheck_at="2026-08-19T18:00:00Z",
        evidence_state=EvidenceState.QUALIFICATION_ONLY,
        blocked_reasons=(),
        trial_requested=True,
    )


def _binding(
    record: ResearchTransferRecord,
    manifest: ExperimentManifest,
) -> ResearchTrialBinding:
    return ResearchTrialBinding(
        transfer_record_id=record.receipt_id,
        registry_id=record.registry_id or "FR01",
        registry_entry_sha256=record.registry_entry_sha256 or ("c" * 64),
        claim_sha256s=tuple(sorted(claim.claim_sha256 for claim in record.claims)),
        experiment_manifest_id=manifest.receipt_id,
        required_controls=record.required_controls,
        falsifier_sha256=canonical_digest(record.falsifier),
        issuer="external-qualification-controller",
        issuer_revision=ISSUER_REVISION,
        authority_generation=1,
        issued_at=WHEN,
        expires_at="2026-09-19T18:00:00Z",
    )


def _qualification_context(
    binding: ResearchTrialBinding,
    *,
    current_generation: int = 1,
    minimum_valid_generation: int = 1,
    issuer_revision: str = ISSUER_REVISION,
    revoked_binding_ids: tuple[str, ...] = (),
) -> ResearchQualificationContext:
    return ResearchQualificationContext(
        issuer=binding.issuer,
        issuer_revision=issuer_revision,
        current_generation=current_generation,
        minimum_valid_generation=minimum_valid_generation,
        authenticated_binding_ids=(binding.receipt_id,),
        revoked_binding_ids=revoked_binding_ids,
        captured_at=CONTEXT_CAPTURED,
        expires_at=CONTEXT_EXPIRES,
    )


def test_pre_execution_council_intake_is_specified_non_authoritative_and_non_trial() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    records = load_research_transfer_ledger(
        repo_root / "config/galaxy/research-transfers.v1.json",
        artifact_root=repo_root,
    )

    assert len(records) == 2
    record = next(
        item
        for item in records
        if item.candidate_id == "architecture.pre-execution-council.2026-07-20"
    )
    assert record.registry_id is None
    assert record.source_status is ResearchSourceStatus.PUBLIC_ARTIFACT
    assert record.evidence_state is EvidenceState.SPECIFIED
    assert record.blocked_reasons == (
        ResearchBlocker.CANONICAL_REGISTRY_ADMISSION_REQUIRED,
    )
    assert record.trial_requested is False
    assert record.runtime_authority is False
    assert record.shadow_only is True
    assert record.experiment_manifest_id is None
    assert record.status_recheck_at == "2027-01-08T00:00:00Z"
    assert record.proposed_consumers == (ResearchConsumer.SUPERNOVA,)
    assert {control.value for control in record.required_controls} == {
        "advisory-only-output",
        "blinded-review-and-self-exclusion",
        "calibration-and-baseline-ablations",
        "correlation-firewall",
        "disagreement-triggered-verification",
        "dissent-preserving-synthesis",
        "exact-model-and-session-binding",
        "exact-provider-wire-binding",
        "fresh-session-no-model-switch",
        "independent-first-pass",
        "invocation-idempotency-and-receipts",
        "judge-qualification",
        "paired-provider-independent-evaluation",
        "paired-replay",
        "provider-entitlement-and-quota-binding",
        "selective-voi-capacity-gate",
        "scope-and-proactiveness-guard",
        "sparse-bounded-exchange",
    }
    assert len(record.claims) == 6
    assert {claim.source_artifact_path for claim in record.claims} == {
        COUNCIL_CAPTURE
    }
    assert any(
        "92e1fccb1bdcf1bab7221aa9ed90f9dc72529131" in claim.url
        for claim in record.claims
    )
    assert any(
        claim.locator
        == (
            "Atom entry summary for DynaDebate: Breaking Homogeneity in "
            "Multi-Agent Debate with Dynamic Path Generation"
        )
        for claim in record.claims
    )
    assert any(
        claim.locator
        == (
            "Atom entry summary for RankJudge: A Multi-Turn LLM-as-a-Judge "
            "Synthetic Benchmark Generator"
        )
        for claim in record.claims
    )
    assert all("five-commit" not in claim.claim for claim in record.claims)


def test_kimi_k3_intake_is_unavailable_non_authoritative_and_non_trial() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    records = load_research_transfer_ledger(
        repo_root / "config/galaxy/research-transfers.v1.json",
        artifact_root=repo_root,
    )

    assert len(records) == 2
    record = next(
        item for item in records if item.candidate_id == "model.kimi-k3.2026-07-16"
    )
    assert record.candidate_id == "model.kimi-k3.2026-07-16"
    assert record.registry_id is None
    assert record.source_status is ResearchSourceStatus.HOSTED_SERVICE
    assert record.evidence_state is EvidenceState.UNAVAILABLE
    assert record.trial_requested is False
    assert record.runtime_authority is False
    assert record.shadow_only is True
    assert record.experiment_manifest_id is None
    assert record.status_recheck_at == "2026-07-28T00:00:00Z"
    assert {
        "canonical-registry-admission-required",
        "external-spend-forbidden",
        "hardware-capacity-unavailable",
        "license-unverified",
        "offline-runtime-closure-unavailable",
        "technical-report-unavailable",
        "weights-unavailable",
    } == {reason.value for reason in record.blocked_reasons}
    assert {"lensing", "accretion", "supernova"} == {
        consumer.value for consumer in record.proposed_consumers
    }
    assert {
        "exact-model-and-session-binding",
        "exact-provider-wire-binding",
        "fresh-session-no-model-switch",
        "hidden-long-context-recall",
        "no-silent-model-fallback",
        "offline-weight-and-runtime-closure",
        "paired-provider-independent-evaluation",
        "preserved-opaque-reasoning-history",
        "provider-entitlement-and-quota-binding",
        "scope-and-proactiveness-guard",
    } == {control.value for control in record.required_controls}
    assert {claim.source_artifact_path for claim in record.claims} == {
        K3_CAPTURE,
        K3_WIRE_ERRATUM,
    }
    retained_claims = {claim.claim for claim in record.claims}
    assert (
        "Moonshot states that Kimi K3 became available on 2026-07-16 through "
        "Kimi, Kimi Work, Kimi Code, and its API; this hosted release does not "
        "establish downloadable weights or an immutable checkpoint."
    ) in retained_claims
    assert (
        "Moonshot's international Kimi Open Platform uses the OpenAI-compatible "
        "Chat Completions wire at https://api.moonshot.ai/v1 with bearer "
        "authentication; this exact endpoint is distinct from the Kimi Code API."
    ) in retained_claims
    assert (
        "Moonshot's hosted Kimi K3 quickstart names model kimi-k3; requires max "
        "reasoning, exact complete assistant message replay, separated "
        "reasoning/final streaming, final-content-only strict schema parsing, "
        "retained dynamic tool declarations, and fixed token/sampling limits. "
        "These are hosted wire requirements, not evidence of public weights."
    ) in retained_claims
    assert (
        "Kimi Code exposes an OpenAI-compatible endpoint at "
        "https://api.kimi.com/coding/v1 and an Anthropic-compatible endpoint at "
        "https://api.kimi.com/coding/; model k3 requires Moderato or above, its "
        "one-million-token context requires Allegretto or above, and it supports "
        "low, high, and max reasoning rather than the general API's max-only "
        "contract."
    ) in retained_claims
    assert (
        "Kimi Code documentation states that disabling thinking for K3 or K2.7 "
        "routes the request to K2.6, while a mistyped HighSpeed model ID can "
        "silently fall back to standard kimi-for-coding; requested model text "
        "alone therefore cannot prove execution provenance."
    ) in retained_claims
    assert any(
        "technical report with further details is forthcoming, without assigning "
        "the report an exact date"
        in claim
        for claim in retained_claims
    )


def test_hosted_service_status_is_not_public_artifact_trial_eligibility() -> None:
    hosted = replace(
        _registered_record(),
        source_status=ResearchSourceStatus.HOSTED_SERVICE,
        evidence_state=EvidenceState.UNAVAILABLE,
        blocked_reasons=(ResearchBlocker.WEIGHTS_UNAVAILABLE,),
        trial_requested=False,
    )
    with pytest.raises(ValueError, match="public source artifact"):
        replace(hosted, trial_requested=True)


def test_unregistered_research_cannot_request_a_trial() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    record = load_research_transfer_ledger(
        repo_root / "config/galaxy/research-transfers.v1.json",
        artifact_root=repo_root,
    )[0]

    with pytest.raises(ValueError, match="canonical FR registry admission"):
        replace(
            record,
            source_status=ResearchSourceStatus.PUBLIC_ARTIFACT,
            trial_requested=True,
            evidence_state=EvidenceState.QUALIFICATION_ONLY,
            experiment_manifest_id=_manifest().receipt_id,
        )


def test_research_record_can_never_carry_runtime_authority() -> None:
    with pytest.raises(ValueError, match="never runtime authority"):
        replace(_registered_record(), runtime_authority=True)


def test_trial_request_requires_manifest_registry_digest_and_qualification_state() -> None:
    record = _registered_record()

    with pytest.raises(ValueError, match="experiment manifest"):
        replace(record, experiment_manifest_id=None)
    with pytest.raises(ValueError, match="registry entry digest"):
        replace(record, registry_entry_sha256=None)
    with pytest.raises(ValueError, match="qualification_only"):
        replace(record, evidence_state=EvidenceState.IMPLEMENTED_DARK)


def test_registry_membership_is_closed_to_the_approved_fr_range() -> None:
    with pytest.raises(ValueError, match="FR01..FR35"):
        replace(_registered_record(), registry_id="FR36")


def test_trial_admission_exact_matches_registry_manifest_and_recheck() -> None:
    record = _registered_record()
    manifest = _manifest()
    binding = _binding(record, manifest)
    binding_kwargs: _BindingKwargs = {
        "trial_bindings": {record.receipt_id: binding},
        "qualification_contexts": {
            "external-qualification-controller": _qualification_context(binding),
        },
    }

    wrong_registry = evaluate_research_trial(
        record,
        canonical_registry_entries={"FR01": "e" * 64},
        experiment_manifests={manifest.receipt_id: manifest},
        at_time=datetime(2026, 8, 19, 17, 59, tzinfo=timezone.utc),
        **binding_kwargs,
    )
    assert wrong_registry.allowed is False
    assert wrong_registry.reason == "registry-entry-mismatch"

    missing_manifest = evaluate_research_trial(
        record,
        canonical_registry_entries={"FR01": "c" * 64},
        experiment_manifests={},
        at_time=datetime(2026, 8, 19, 17, 59, tzinfo=timezone.utc),
        **binding_kwargs,
    )
    assert missing_manifest.allowed is False
    assert missing_manifest.reason == "experiment-manifest-unavailable"

    admitted = evaluate_research_trial(
        record,
        canonical_registry_entries={"FR01": "c" * 64},
        experiment_manifests={manifest.receipt_id: manifest},
        at_time=datetime(2026, 8, 19, 17, 59, tzinfo=timezone.utc),
        **binding_kwargs,
    )
    assert type(admitted) is ResearchTrialAdmissionDecision
    assert admitted.allowed is True
    assert admitted.reason == "preregistered-shadow-trial"
    assert admitted.runtime_authority is False

    microsecond_clock = evaluate_research_trial(
        record,
        canonical_registry_entries={"FR01": "c" * 64},
        experiment_manifests={manifest.receipt_id: manifest},
        at_time=datetime(
            2026,
            8,
            19,
            17,
            59,
            0,
            123456,
            tzinfo=timezone.utc,
        ),
        **binding_kwargs,
    )
    assert microsecond_clock.allowed is True
    assert microsecond_clock.evaluated_at == "2026-08-19T17:59:00.123456Z"

    expired = evaluate_research_trial(
        record,
        canonical_registry_entries={"FR01": "c" * 64},
        experiment_manifests={manifest.receipt_id: manifest},
        at_time=datetime(2026, 8, 19, 18, 0, tzinfo=timezone.utc),
        **binding_kwargs,
    )
    assert expired.allowed is False
    assert expired.reason == "status-recheck-expired"


def test_claim_digest_is_recomputed_from_location_and_claim() -> None:
    with pytest.raises(ValueError, match="claim_sha256"):
        ResearchClaim(
            url="https://example.invalid/paper",
            locator="Abstract",
            source_class=ResearchSourceClass.PRIMARY,
            retrieved_at=WHEN,
            claim="A claim whose supplied digest is not canonical.",
            source_response_sha256=SHA_A,
            source_artifact_path="docs/superpowers/research/fixture.md",
            source_artifact_sha256=SHA_A,
            claim_sha256=SHA_A,
        )


def test_trial_admission_requires_an_exact_external_binding() -> None:
    record = _registered_record()
    manifest = _manifest()

    missing = evaluate_research_trial(
        record,
        canonical_registry_entries={"FR01": "c" * 64},
        experiment_manifests={manifest.receipt_id: manifest},
        trial_bindings={},
        qualification_contexts={
            "external-qualification-controller": _qualification_context(
                _binding(record, manifest)
            ),
        },
        at_time=datetime(2026, 8, 19, 17, 59, tzinfo=timezone.utc),
    )
    assert missing.allowed is False
    assert missing.reason == "trial-binding-unavailable"

    unrelated = replace(record, candidate_id="unrelated.source.followup")
    laundered = evaluate_research_trial(
        unrelated,
        canonical_registry_entries={"FR01": "c" * 64},
        experiment_manifests={manifest.receipt_id: manifest},
        trial_bindings={record.receipt_id: _binding(record, manifest)},
        qualification_contexts={
            "external-qualification-controller": _qualification_context(
                _binding(record, manifest)
            ),
        },
        at_time=datetime(2026, 8, 19, 17, 59, tzinfo=timezone.utc),
    )
    assert laundered.allowed is False
    assert laundered.reason == "trial-binding-unavailable"

    binding = _binding(record, manifest)
    stale_generation = evaluate_research_trial(
        record,
        canonical_registry_entries={"FR01": "c" * 64},
        experiment_manifests={manifest.receipt_id: manifest},
        trial_bindings={record.receipt_id: binding},
        qualification_contexts={
            "external-qualification-controller": _qualification_context(
                binding,
                current_generation=2,
                minimum_valid_generation=2,
            ),
        },
        at_time=datetime(2026, 8, 19, 17, 59, tzinfo=timezone.utc),
    )
    assert stale_generation.allowed is False
    assert stale_generation.reason == "trial-binding-generation-stale"


@pytest.mark.parametrize(
    ("binding_changes", "expected_reason"),
    (
        ({"transfer_record_id": SHA_A}, "trial-binding-record-mismatch"),
        ({"registry_entry_sha256": "e" * 64}, "trial-binding-registry-mismatch"),
        ({"claim_sha256s": (SHA_A,)}, "trial-binding-claims-mismatch"),
        (
            {"required_controls": (ResearchControl.EXACT_MODEL_AND_SESSION_BINDING,)},
            "trial-binding-controls-mismatch",
        ),
        ({"falsifier_sha256": SHA_A}, "trial-binding-falsifier-mismatch"),
        ({"experiment_manifest_id": SHA_A}, "trial-binding-manifest-mismatch"),
        (
            {"issued_at": "2026-08-19T18:00:00Z"},
            "trial-binding-not-yet-valid",
        ),
        (
            {"expires_at": "2026-08-19T17:58:00Z"},
            "trial-binding-expired",
        ),
    ),
)
def test_trial_binding_exact_match_denial_matrix(
    binding_changes: dict[str, Any],
    expected_reason: str,
) -> None:
    record = _registered_record()
    manifest = _manifest()
    binding = replace(_binding(record, manifest), **binding_changes)

    decision = evaluate_research_trial(
        record,
        canonical_registry_entries={"FR01": "c" * 64},
        experiment_manifests={manifest.receipt_id: manifest},
        trial_bindings={record.receipt_id: binding},
        qualification_contexts={
            binding.issuer: _qualification_context(binding),
        },
        at_time=datetime(2026, 8, 19, 17, 59, tzinfo=timezone.utc),
    )

    assert decision.allowed is False
    assert decision.reason == expected_reason


def test_trial_binding_rejects_untrusted_unauthenticated_and_revoked_contexts() -> None:
    record = _registered_record()
    manifest = _manifest()
    binding = _binding(record, manifest)
    base: _AdmissionBaseKwargs = {
        "canonical_registry_entries": {"FR01": "c" * 64},
        "experiment_manifests": {manifest.receipt_id: manifest},
        "trial_bindings": {record.receipt_id: binding},
        "at_time": datetime(2026, 8, 19, 17, 59, tzinfo=timezone.utc),
    }

    untrusted = evaluate_research_trial(
        record,
        qualification_contexts={
            binding.issuer: _qualification_context(
                binding,
                issuer_revision="e" * 40,
            ),
        },
        **base,
    )
    assert untrusted.reason == "trial-binding-issuer-untrusted"

    unauthenticated_context = replace(
        _qualification_context(binding),
        authenticated_binding_ids=(SHA_A,),
    )
    unauthenticated = evaluate_research_trial(
        record,
        qualification_contexts={binding.issuer: unauthenticated_context},
        **base,
    )
    assert unauthenticated.reason == "trial-binding-unauthenticated"

    revoked = evaluate_research_trial(
        record,
        qualification_contexts={
            binding.issuer: _qualification_context(
                binding,
                revoked_binding_ids=(binding.receipt_id,),
            ),
        },
        **base,
    )
    assert revoked.reason == "trial-binding-revoked"

    issuer_mismatch = evaluate_research_trial(
        record,
        qualification_contexts={
            binding.issuer: replace(
                _qualification_context(binding),
                issuer="different-controller",
            ),
        },
        **base,
    )
    assert issuer_mismatch.reason == "trial-binding-issuer-untrusted"

    stale_context = evaluate_research_trial(
        record,
        qualification_contexts={
            binding.issuer: replace(
                _qualification_context(binding),
                captured_at="2026-07-19T18:00:00Z",
                expires_at="2026-07-19T18:05:00Z",
            ),
        },
        **base,
    )
    assert stale_context.reason == "qualification-context-expired"

    future_context = evaluate_research_trial(
        record,
        qualification_contexts={
            binding.issuer: replace(
                _qualification_context(binding),
                captured_at="2026-08-19T18:00:00Z",
                expires_at="2026-08-19T18:05:00Z",
            ),
        },
        **base,
    )
    assert future_context.reason == "qualification-context-not-yet-valid"


def test_candidate_record_is_content_addressed_and_closed() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    first = load_research_transfer_ledger(
        repo_root / "config/galaxy/research-transfers.v1.json",
        artifact_root=repo_root,
    )[0]
    second = load_research_transfer_ledger(
        repo_root / "config/galaxy/research-transfers.v1.json",
        artifact_root=repo_root,
    )[0]

    assert first.receipt_id == second.receipt_id
    assert len(first.receipt_id) == 64


def _ledger_payload() -> tuple[Path, dict[str, Any]]:
    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "config/galaxy/research-transfers.v1.json"
    return repo_root, json.loads(path.read_text(encoding="utf-8"))


def test_ledger_rejects_tampering_external_spend_and_non_list_fields(
    tmp_path: Path,
) -> None:
    repo_root, payload = _ledger_payload()

    payload["external_spend_allowed"] = True
    path = tmp_path / "external-spend.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ResearchTransferLedgerError, match="external spend"):
        load_research_transfer_ledger(path, artifact_root=repo_root)

    _, payload = _ledger_payload()
    payload["records"][0]["record_id"] = SHA_A
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ResearchTransferLedgerError, match="record_id"):
        load_research_transfer_ledger(path, artifact_root=repo_root)

    _, payload = _ledger_payload()
    payload["records"][0]["required_controls"] = {"paired-replay": True}
    path = tmp_path / "mapping-controls.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ResearchTransferLedgerError, match="required_controls.*list"):
        load_research_transfer_ledger(path, artifact_root=repo_root)

    _, payload = _ledger_payload()
    payload["records"][0]["unexpected_authority"] = True
    path = tmp_path / "extra-key.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ResearchTransferLedgerError, match="keys differ"):
        load_research_transfer_ledger(path, artifact_root=repo_root)

    _, payload = _ledger_payload()
    payload["records"][0]["claims"][0]["source_class"] = "vendor-rumor"
    path = tmp_path / "unknown-source-class.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ResearchTransferLedgerError, match="invalid research claim"):
        load_research_transfer_ledger(path, artifact_root=repo_root)


def test_ledger_rehashes_retained_source_artifacts(tmp_path: Path) -> None:
    repo_root, payload = _ledger_payload()
    referenced = {
        claim["source_artifact_path"]
        for claim in payload["records"][0]["claims"]
    }
    for relative in referenced:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((repo_root / relative).read_bytes())
    capture = tmp_path / next(iter(referenced))
    capture.write_text("drifted capture", encoding="utf-8")
    path = tmp_path / "drifted.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ResearchTransferLedgerError, match="source artifact digest"):
        load_research_transfer_ledger(path, artifact_root=tmp_path)


def test_ledger_rejects_traversal_hard_links_and_oversize_input(tmp_path: Path) -> None:
    repo_root, payload = _ledger_payload()
    payload["records"][0]["claims"][0]["source_artifact_path"] = "../escape.md"
    path = tmp_path / "traversal.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ResearchTransferLedgerError, match="repository-relative"):
        load_research_transfer_ledger(path, artifact_root=repo_root)

    _, payload = _ledger_payload()
    original = tmp_path / "original.json"
    linked = tmp_path / "linked.json"
    original.write_text(json.dumps(payload), encoding="utf-8")
    os.link(original, linked)
    with pytest.raises(ResearchTransferLedgerError, match="cannot read"):
        load_research_transfer_ledger(linked, artifact_root=repo_root)

    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b" " * (2 * 1024 * 1024 + 1))
    with pytest.raises(ResearchTransferLedgerError, match="oversized"):
        load_research_transfer_ledger(oversized, artifact_root=repo_root)


def test_ledger_rejects_reparse_artifact_root(tmp_path: Path) -> None:
    repo_root, _ = _ledger_payload()
    root_link = tmp_path / "root-link"
    try:
        os.symlink(repo_root, root_link, target_is_directory=True)
    except OSError as exc:
        if os.name != "nt":
            pytest.skip(f"directory symlinks unavailable: {exc}")
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(root_link), str(repo_root)],
            check=False,
            capture_output=True,
            text=True,
        )
        if created.returncode != 0:
            pytest.skip(f"directory reparse points unavailable: {created.stderr}")

    try:
        with pytest.raises(ResearchTransferLedgerError, match="artifact_root"):
            load_research_transfer_ledger(
                repo_root / "config/galaxy/research-transfers.v1.json",
                artifact_root=root_link,
            )
    finally:
        if root_link.exists():
            os.rmdir(root_link)
