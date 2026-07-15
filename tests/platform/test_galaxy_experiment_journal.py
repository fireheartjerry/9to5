from __future__ import annotations

import sqlite3
from dataclasses import replace
from decimal import Decimal

import pytest

from platform_core.core.galaxy_evidence import (
    AnalysisReceipt,
    AssignmentReceipt,
    CapacityTruth,
    ExperimentManifest,
    ObservationReceipt,
    PromotionRecommendation,
    RollbackReceipt,
)
from platform_core.core.galaxy_experiments import (
    ParentReceiptMissing,
    ReceiptLineageMismatch,
    ShadowEvidenceJournal,
)


SHA = "a" * 64
REVISION = "1" * 40
WHEN = "2026-07-14T12:00:00Z"


def _chain():
    manifest = ExperimentManifest(
        experiment_id="wave0-shadow",
        policy_version="galaxy-r3-wave0",
        provider_cohort=("deterministic-local",),
        fixture_digest=SHA,
        primary_endpoint="wrong_path_execution",
        seeds=(7,),
        created_at=WHEN,
    )
    assignment = AssignmentReceipt(
        manifest_id=manifest.receipt_id,
        unit_id="fixture-1",
        treatment="ambiguity-score",
        assignment_probability=Decimal("1"),
        seed=7,
        policy_version=manifest.policy_version,
        provider="deterministic-local",
        capability_profile_id="object-only-goal-text-v1",
        quota_state=CapacityTruth.AVAILABLE,
        source_revision=REVISION,
        fixture_digest=SHA,
        assigned_at=WHEN,
    )
    observation = ObservationReceipt.from_assignment(
        assignment,
        outcome=(("decision", "probe-proposed"), ("score", 5)),
        observed_at=WHEN,
    )
    analysis = AnalysisReceipt(
        manifest_id=manifest.receipt_id,
        observation_ids=(observation.receipt_id,),
        analyst_identity="independent-deterministic-v1",
        primary_endpoint=manifest.primary_endpoint,
        estimate=Decimal("0"),
        confidence_interval=(Decimal("0"), Decimal("0")),
        analyzed_at=WHEN,
    )
    recommendation = PromotionRecommendation(
        analysis_id=analysis.receipt_id,
        recommendation="continue-shadow",
        reason="qualification not started",
        recommended_at=WHEN,
    )
    rollback = RollbackReceipt(
        recommendation_id=recommendation.receipt_id,
        rollback_target="incumbent-c16bbebe",
        reason="shadow authority is always reversible",
        rolled_back_at=WHEN,
    )
    return manifest, assignment, observation, analysis, recommendation, rollback


def test_journal_uses_wal_full_sync_and_create_only_schema(tmp_path) -> None:
    path = tmp_path / "shadow-evidence.db"
    with ShadowEvidenceJournal(path) as journal:
        assert journal.journal_mode == "wal"
        assert journal.synchronous == "full"
        assert journal.integrity_check() == "ok"


def test_append_is_idempotent_for_exact_same_receipt(tmp_path) -> None:
    manifest = _chain()[0]
    with ShadowEvidenceJournal(tmp_path / "evidence.db") as journal:
        assert journal.append(manifest) is True
        assert journal.append(manifest) is False
        assert journal.count() == 1


def test_child_before_parent_fails_closed(tmp_path) -> None:
    assignment = _chain()[1]
    with ShadowEvidenceJournal(tmp_path / "evidence.db") as journal:
        with pytest.raises(ParentReceiptMissing, match=assignment.manifest_id):
            journal.append(assignment)
        assert journal.count() == 0


def test_complete_chain_is_atomic_durable_and_replayable(tmp_path) -> None:
    path = tmp_path / "evidence.db"
    chain = _chain()
    with ShadowEvidenceJournal(path) as journal:
        assert journal.append_chain(chain) == len(chain)
        assert journal.count() == len(chain)
        tail = journal.fetch(chain[-1].receipt_id)
        assert tail is not None
        assert tail.parent_receipt_ids == (chain[-2].receipt_id,)
        assert tail.payload["rollback_target"] == "incumbent-c16bbebe"

    with ShadowEvidenceJournal(path) as reopened:
        assert reopened.count() == len(chain)
        assert reopened.verify_chain(chain[-1].receipt_id) == tuple(
            receipt.receipt_id for receipt in reversed(chain)
        )


def test_chain_transaction_rolls_back_when_a_parent_is_missing(tmp_path) -> None:
    manifest, assignment, observation, analysis, recommendation, rollback = _chain()
    with ShadowEvidenceJournal(tmp_path / "evidence.db") as journal:
        with pytest.raises(ParentReceiptMissing):
            journal.append_chain((manifest, observation, analysis, recommendation, rollback))
        assert journal.count() == 0


def test_database_triggers_reject_update_and_delete(tmp_path) -> None:
    path = tmp_path / "evidence.db"
    manifest = _chain()[0]
    with ShadowEvidenceJournal(path) as journal:
        journal.append(manifest)

    connection = sqlite3.connect(path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE shadow_receipts SET receipt_type = 'RollbackReceipt' WHERE receipt_id = ?",
                (manifest.receipt_id,),
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "DELETE FROM shadow_receipts WHERE receipt_id = ?", (manifest.receipt_id,)
            )
    finally:
        connection.close()


def test_assignment_must_match_immutable_manifest(tmp_path) -> None:
    manifest, assignment, *_ = _chain()
    assignment = replace(assignment, seed=99)
    with ShadowEvidenceJournal(tmp_path / "evidence.db") as journal:
        journal.append(manifest)
        with pytest.raises(ReceiptLineageMismatch, match="seed"):
            journal.append(assignment)


def test_observation_provenance_must_match_assignment(tmp_path) -> None:
    manifest, assignment, observation, *_ = _chain()
    observation = replace(observation, provider="unassigned-provider")
    with ShadowEvidenceJournal(tmp_path / "evidence.db") as journal:
        journal.append_chain((manifest, assignment))
        with pytest.raises(ReceiptLineageMismatch, match="provider"):
            journal.append(observation)
