"""Live landing authority is exact, expiring, revocable, and non-serializable."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest

from platform_core.runtime import candidate as candidate_mod
from platform_core.runtime.candidate import (
    LandingAuthorityIssuer,
    LandingAuthorityRefused,
    validatePromotionRecoveryAuthority,
)
from platform_core.runtime.receipts import PromotionAuthorization

SHA_A = "a" * 40
SHA_B = "b" * 40
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64
DIGEST_E = "e" * 64
DIGEST_F = "f" * 64


def _authorization() -> PromotionAuthorization:
    return PromotionAuthorization(
        transaction_id="tx-001",
        task_id="task-001",
        subtask_id="subtask-001",
        staging_receipt_id=DIGEST_A,
        verification_receipt_id=DIGEST_B,
        review_receipt_id=DIGEST_C,
        proposed_revision=SHA_A,
        proposed_tree=SHA_B,
        proposed_diff_digest=DIGEST_D,
        spec_digest=DIGEST_E,
        policy_digest=DIGEST_F,
    )


def _issuer(now: datetime) -> tuple[LandingAuthorityIssuer, object]:
    capability = object()
    issuer = candidate_mod._buildDiagnosticLandingAuthorityIssuer(
        run_id="run-001",
        controller_generation=7,
        watchdog_generation=11,
        process_capability=capability,
        clock=lambda: now,
    )
    return issuer, capability


def test_repository_caller_cannot_mint_a_run_admission_issuer() -> None:
    now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(LandingAuthorityRefused, match="installed run admission"):
        LandingAuthorityIssuer(
            run_id="run-001",
            controller_generation=7,
            watchdog_generation=11,
            process_capability=object(),
            clock=lambda: now,
        )


def test_exact_live_landing_authority_validates_only_its_bound_chain() -> None:
    now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    issuer, capability = _issuer(now)
    admission = issuer.issueRunAdmission(
        process_capability=capability,
        deadline=now + timedelta(minutes=5),
    )
    authorization = _authorization()
    authority = issuer.issueLandingAuthority(
        admission=admission,
        authorization=authorization,
    )

    assert issuer.validateLandingAuthority(authority, authorization) is authority
    with pytest.raises(LandingAuthorityRefused, match="scope"):
        issuer.validateLandingAuthority(
            authority,
            replace(authorization, proposed_diff_digest="0" * 64),
        )


def test_landing_authority_rejects_boolean_copy_revocation_and_expiry() -> None:
    now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    observed = [now]
    capability = object()
    issuer = candidate_mod._buildDiagnosticLandingAuthorityIssuer(
        run_id="run-001",
        controller_generation=7,
        watchdog_generation=11,
        process_capability=capability,
        clock=lambda: observed[0],
    )
    authorization = _authorization()
    admission = issuer.issueRunAdmission(
        process_capability=capability,
        deadline=now + timedelta(seconds=1),
    )
    authority = issuer.issueLandingAuthority(
        admission=admission,
        authorization=authorization,
    )

    with pytest.raises(LandingAuthorityRefused, match="live"):
        issuer.validateLandingAuthority(True, authorization)
    with pytest.raises(LandingAuthorityRefused, match="live"):
        issuer.validateLandingAuthority(replace(authority), authorization)

    issuer.revokeLandingAuthority(authority)
    with pytest.raises(LandingAuthorityRefused, match="live"):
        issuer.validateLandingAuthority(authority, authorization)

    later = issuer.issueLandingAuthority(
        admission=admission,
        authorization=authorization,
    )
    observed[0] = now + timedelta(seconds=2)
    with pytest.raises(LandingAuthorityRefused, match="expired"):
        issuer.validateLandingAuthority(later, authorization)

    observed[0] = now
    with pytest.raises(LandingAuthorityRefused, match="active|live|expired"):
        issuer.validateLandingAuthority(later, authorization)


def test_backward_clock_observation_terminally_retires_landing_issuer() -> None:
    now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    observed = [now]
    capability = object()
    issuer = candidate_mod._buildDiagnosticLandingAuthorityIssuer(
        run_id="run-001",
        controller_generation=7,
        watchdog_generation=11,
        process_capability=capability,
        clock=lambda: observed[0],
    )
    admission = issuer.issueRunAdmission(
        process_capability=capability,
        deadline=now + timedelta(minutes=5),
    )
    observed[0] = now + timedelta(minutes=2)
    assert issuer._validateAdmission(admission) is admission

    observed[0] = now + timedelta(minutes=1)
    with pytest.raises(LandingAuthorityRefused, match="clock|backward|live"):
        issuer._validateAdmission(admission)

    observed[0] = now + timedelta(minutes=3)
    with pytest.raises(LandingAuthorityRefused, match="issuer|live"):
        issuer._validateAdmission(admission)


def test_forged_copies_cannot_revoke_live_landing_or_admission() -> None:
    now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    issuer, capability = _issuer(now)
    authorization = _authorization()
    admission = issuer.issueRunAdmission(
        process_capability=capability,
        deadline=now + timedelta(minutes=5),
    )
    landing = issuer.issueLandingAuthority(
        admission=admission,
        authorization=authorization,
    )

    issuer.revokeLandingAuthority(replace(landing))
    issuer.revokeRunAdmission(replace(admission))

    assert issuer._validateAdmission(admission) is admission
    assert issuer.validateLandingAuthority(landing, authorization) is landing


def test_issuer_clock_cannot_be_retargeted_to_extend_admission_lifetime() -> None:
    now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    observed = [now]
    capability = object()
    issuer = candidate_mod._buildDiagnosticLandingAuthorityIssuer(
        run_id="run-001",
        controller_generation=7,
        watchdog_generation=11,
        process_capability=capability,
        clock=lambda: observed[0],
    )
    admission = issuer.issueRunAdmission(
        process_capability=capability,
        deadline=now + timedelta(seconds=1),
    )
    observed[0] = now + timedelta(seconds=2)
    object.__setattr__(issuer, "_clock", lambda: now)

    with pytest.raises(LandingAuthorityRefused, match="issuer|scope|changed"):
        issuer._validateAdmission(admission)


def test_issuer_quiescence_oracle_cannot_be_retargeted() -> None:
    now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    capability = object()
    issuer = candidate_mod._buildDiagnosticLandingAuthorityIssuer(
        run_id="run-001",
        controller_generation=7,
        watchdog_generation=11,
        process_capability=capability,
        clock=lambda: now,
        recovery_quiescence_probe=lambda _transaction_id: False,
    )
    admission = issuer.issueRunAdmission(
        process_capability=capability,
        deadline=now + timedelta(minutes=5),
    )
    object.__setattr__(
        issuer,
        "_recovery_quiescence_probe",
        lambda _transaction_id: True,
    )

    with pytest.raises(LandingAuthorityRefused, match="issuer|scope|changed"):
        issuer.issueRecoveryAuthority(
            admission=admission,
            repository_id=DIGEST_A,
            transaction_id="tx-001",
        )


_LANDING_AUTHORIZATION_FIELDS = frozenset(
    {
        "transaction_id",
        "task_id",
        "subtask_id",
        "proposed_revision",
        "proposed_tree",
        "staging_receipt_id",
        "verification_receipt_id",
        "review_receipt_id",
        "selection_receipt_id",
        "proposed_diff_digest",
        "spec_digest",
        "policy_digest",
    }
)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("run_id", "run-002"),
        ("transaction_id", "tx-002"),
        ("task_id", "task-002"),
        ("subtask_id", "subtask-002"),
        ("proposed_revision", "c" * 40),
        ("proposed_tree", "d" * 40),
        ("staging_receipt_id", "1" * 64),
        ("verification_receipt_id", "2" * 64),
        ("review_receipt_id", "3" * 64),
        ("selection_receipt_id", "4" * 64),
        ("proposed_diff_digest", "5" * 64),
        ("spec_digest", "6" * 64),
        ("policy_digest", "7" * 64),
        ("controller_generation", 8),
        ("watchdog_generation", 12),
        ("revocation_generation", 1),
        ("outer_scope_digest", "8" * 64),
        ("deadline", datetime(2026, 7, 16, 12, 10, tzinfo=timezone.utc)),
        ("issuer_instance_id", "other-issuer"),
        ("admission_id", "other-admission"),
        ("landing_id", "other-landing"),
        ("_process_capability", object()),
        ("_authority_token", object()),
        ("_issuer", object()),
    ),
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_exact_landing_authority_rejects_every_in_place_field_mutation(
    field: str,
    replacement: object,
) -> None:
    """Exact-object lookup must not bless a retargeted authority in place."""

    now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    issuer, capability = _issuer(now)
    authorization = _authorization()
    admission = issuer.issueRunAdmission(
        process_capability=capability,
        deadline=now + timedelta(minutes=5),
    )
    authority = issuer.issueLandingAuthority(
        admission=admission,
        authorization=authorization,
    )
    assert issuer.validateLandingAuthority(authority, authorization) is authority

    object.__setattr__(authority, field, replacement)
    retargeted_authorization = (
        cast(Any, replace)(authorization, **{field: replacement})
        if field in _LANDING_AUTHORIZATION_FIELDS
        else authorization
    )

    with pytest.raises(LandingAuthorityRefused):
        issuer.validateLandingAuthority(authority, retargeted_authorization)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("run_id", "run-002"),
        ("run_revision", 1),
        ("installed_repository_identity", DIGEST_A),
        ("canonical_repository_id", DIGEST_B),
        ("outer_scope_digest", DIGEST_C),
        ("capsule_scope_digest", DIGEST_D),
        ("external_roots_manifest_digest", DIGEST_E),
        ("anchor_receipt_digest", DIGEST_F),
        ("boot_receipt_digest", "1" * 64),
        ("controller_activation_receipt_digest", "2" * 64),
        ("recovery_receipt_digest", "3" * 64),
        ("source_snapshot_receipt_digest", "4" * 64),
        ("activation_generation", 1),
        ("boot_generation", 1),
        ("controller_generation", 8),
        ("watchdog_generation", 12),
        ("revocation_generation", 1),
        ("deadline", datetime(2026, 7, 16, 13, 0, tzinfo=timezone.utc)),
        ("repository_attestation_digest", "5" * 64),
        ("expected_base_sha", "c" * 40),
        ("task_id", "task-002"),
        ("raw_intent_digest", "6" * 64),
        ("spec_digest", "7" * 64),
        ("child_pid", 999),
        ("issuer_instance_id", "other-issuer"),
        ("admission_id", "other-admission"),
        ("_process_capability", object()),
        ("_authority_token", object()),
    ),
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_exact_run_admission_rejects_every_in_place_field_mutation(
    field: str,
    replacement: object,
) -> None:
    now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    issuer, capability = _issuer(now)
    admission = issuer.issueRunAdmission(
        process_capability=capability,
        deadline=now + timedelta(minutes=5),
    )
    assert issuer._validateAdmission(admission) is admission

    object.__setattr__(admission, field, replacement)

    with pytest.raises(LandingAuthorityRefused):
        issuer._validateAdmission(admission)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("run_id", "run-002"),
        ("repository_id", DIGEST_B),
        ("transaction_id", "tx-002"),
        ("controller_generation", 8),
        ("watchdog_generation", 12),
        ("revocation_generation", 1),
        ("outer_scope_digest", DIGEST_C),
        ("deadline", datetime(2026, 7, 16, 13, 0, tzinfo=timezone.utc)),
        ("issuer_instance_id", "other-issuer"),
        ("admission_id", "other-admission"),
        ("recovery_id", "other-recovery"),
        ("_process_capability", object()),
        ("_authority_token", object()),
        ("_issuer", object()),
    ),
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_exact_recovery_authority_rejects_every_in_place_field_mutation(
    field: str,
    replacement: object,
) -> None:
    now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    capability = object()
    issuer = candidate_mod._buildDiagnosticLandingAuthorityIssuer(
        run_id="run-001",
        controller_generation=7,
        watchdog_generation=11,
        process_capability=capability,
        clock=lambda: now,
        recovery_quiescence_probe=lambda _transaction_id: True,
    )
    admission = issuer.issueRunAdmission(
        process_capability=capability,
        deadline=now + timedelta(minutes=5),
    )
    recovery = issuer.issueRecoveryAuthority(
        admission=admission,
        repository_id=DIGEST_A,
        transaction_id="tx-001",
    )
    assert (
        issuer.validateRecoveryAuthority(
            recovery,
            repository_id=DIGEST_A,
            transaction_id="tx-001",
        )
        is recovery
    )

    object.__setattr__(recovery, field, replacement)

    with pytest.raises(LandingAuthorityRefused):
        issuer.validateRecoveryAuthority(
            recovery,
            repository_id=(DIGEST_B if field == "repository_id" else DIGEST_A),
            transaction_id=("tx-002" if field == "transaction_id" else "tx-001"),
        )


def test_recovery_authority_cannot_cross_live_admission_repository() -> None:
    now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    capability = object()
    issuer = LandingAuthorityIssuer(
        run_id="run-001",
        canonical_repository_id=DIGEST_A,
        controller_generation=7,
        watchdog_generation=11,
        process_capability=capability,
        clock=lambda: now,
        recovery_quiescence_probe=lambda _transaction_id: True,
        _construction_authority=candidate_mod._DIAGNOSTIC_LANDING_ISSUER_CONSTRUCTION,
    )
    admission = issuer.issueRunAdmission(
        process_capability=capability,
        deadline=now + timedelta(minutes=5),
    )

    with pytest.raises(LandingAuthorityRefused, match="repository"):
        issuer.issueRecoveryAuthority(
            admission=admission,
            repository_id=DIGEST_B,
            transaction_id="tx-001",
        )


def test_generation_or_admission_loss_invalidates_landing_authority() -> None:
    now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    issuer, capability = _issuer(now)
    authorization = _authorization()
    admission = issuer.issueRunAdmission(
        process_capability=capability,
        deadline=now + timedelta(minutes=5),
    )
    authority = issuer.issueLandingAuthority(
        admission=admission,
        authorization=authorization,
    )

    issuer.advanceWatchdog(12)
    with pytest.raises(LandingAuthorityRefused, match="watchdog"):
        issuer.validateLandingAuthority(authority, authorization)

    issuer = candidate_mod._buildDiagnosticLandingAuthorityIssuer(
        run_id="run-001",
        controller_generation=7,
        watchdog_generation=11,
        process_capability=capability,
        clock=lambda: now,
    )
    admission = issuer.issueRunAdmission(
        process_capability=capability,
        deadline=now + timedelta(minutes=5),
    )
    authority = issuer.issueLandingAuthority(
        admission=admission,
        authorization=authorization,
    )
    issuer.revokeRunAdmission(admission)
    with pytest.raises(LandingAuthorityRefused, match="admission"):
        issuer.validateLandingAuthority(authority, authorization)


def test_landing_authority_cannot_be_serialized_as_durable_power() -> None:
    now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    issuer, capability = _issuer(now)
    authorization = _authorization()
    authority = issuer.issueLandingAuthority(
        admission=issuer.issueRunAdmission(
            process_capability=capability,
            deadline=now + timedelta(minutes=5),
        ),
        authorization=authorization,
    )

    with pytest.raises(TypeError):
        json.dumps(authority)


def test_recovery_authority_requires_quiescence_and_exact_transaction() -> None:
    now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    capability = object()
    quiescent: set[str] = set()
    issuer = candidate_mod._buildDiagnosticLandingAuthorityIssuer(
        run_id="run-001",
        controller_generation=7,
        watchdog_generation=11,
        process_capability=capability,
        clock=lambda: now,
        recovery_quiescence_probe=lambda transaction_id: transaction_id in quiescent,
    )
    admission = issuer.issueRunAdmission(
        process_capability=capability,
        deadline=now + timedelta(minutes=5),
    )

    with pytest.raises(LandingAuthorityRefused, match="quiescent"):
        issuer.issueRecoveryAuthority(
            admission=admission,
            repository_id=DIGEST_A,
            transaction_id="tx-001",
        )

    quiescent.add("tx-001")
    recovery = issuer.issueRecoveryAuthority(
        admission=admission,
        repository_id=DIGEST_A,
        transaction_id="tx-001",
    )
    assert (
        validatePromotionRecoveryAuthority(
            recovery,
            repository_id=DIGEST_A,
            transaction_id="tx-001",
        )
        is recovery
    )
    with pytest.raises(LandingAuthorityRefused, match="scope"):
        validatePromotionRecoveryAuthority(
            recovery,
            repository_id=DIGEST_A,
            transaction_id="tx-002",
        )


def test_recovery_authority_is_unavailable_without_a_quiescence_oracle() -> None:
    now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    issuer, capability = _issuer(now)
    admission = issuer.issueRunAdmission(
        process_capability=capability,
        deadline=now + timedelta(minutes=5),
    )

    with pytest.raises(LandingAuthorityRefused, match="quiescence"):
        issuer.issueRecoveryAuthority(
            admission=admission,
            repository_id=DIGEST_A,
            transaction_id="tx-001",
        )
