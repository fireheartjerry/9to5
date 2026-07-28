"""RED contracts for universal credentialless exact-revision verification."""

from __future__ import annotations

import inspect

from agents.review import verification


def test_acceptance_runner_requires_authority_before_every_other_argument() -> None:
    parameters = tuple(inspect.signature(verification._runVector).parameters)
    assert parameters[0] == "authority"
    assert parameters[1] == "argv"


def test_verifier_has_no_install_root_or_canonical_workdir_fallback() -> None:
    assert not hasattr(verification, "_normalizeWorkDir")


def test_verification_authority_contract_is_exported_by_review_boundary() -> None:
    assert hasattr(verification, "VerificationCommandAuthority")
    assert hasattr(verification, "VerificationCommandRefused")
