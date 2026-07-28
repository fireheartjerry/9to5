"""Behavioral contracts for the dark capsule bootstrap-scope schema."""
from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError

import pytest

from platform_core.runtime.bootstrap_scope import (
    CAPSULE_BOOTSTRAP_SCOPE_SCHEMA,
    CAPSULE_BOOTSTRAP_SCOPE_WIRE_FIELDS,
    CapsuleBootstrapScope,
    CapsuleBootstrapScopeValidationError,
    capsule_bootstrap_scope_digest,
    validate_capsule_bootstrap_scope,
)


_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64
_DIGEST_C = "c" * 64
_DIGEST_D = "d" * 64
_DIGEST_E = "e" * 64
_DIGEST_F = "f" * 64
_DIGEST_0 = "0" * 64
_DIGEST_1 = "1" * 64
_DIGEST_2 = "2" * 64
_DIGEST_3 = "3" * 64
_SOURCE_ROOT = r"C:\Repositories\9to5"
_INSTALLED_ROOT = r"C:\ProgramData\Galaxy\Controller"
_STATE_ROOT = r"C:\ProgramData\Galaxy\Controller\state\repo-a"


def _scope_values() -> dict[str, object]:
    values: dict[str, object] = {
        "installed_repository_identity": _DIGEST_A,
        "canonical_repository_id": _DIGEST_B,
        "run_id": "run-2026.07.20:bootstrap_01",
        "run_revision": 0,
        "controller_state_root": _STATE_ROOT,
        "source_root": _SOURCE_ROOT,
        "installed_controller_root": _INSTALLED_ROOT,
        "external_roots_manifest_digest": _DIGEST_2,
        "repository_attestation_digest": _DIGEST_C,
        "expected_base_sha": "4" * 40,
        "source_snapshot_receipt_digest": _DIGEST_D,
        "anchor_receipt_digest": _DIGEST_E,
        "boot_receipt_digest": _DIGEST_F,
        "controller_activation_receipt_digest": _DIGEST_0,
        "recovery_receipt_digest": _DIGEST_1,
        "activation_generation": 2,
        "boot_generation": 3,
        "controller_generation": 4,
        "watchdog_generation": 5,
        "revocation_generation": 0,
        "capability_expires_at": "2099-01-01T01:00:00+00:00",
        "run_deadline": "2099-01-01T00:30:00+00:00",
    }
    return values


def _scope() -> CapsuleBootstrapScope:
    return _construct_scope(_scope_values())


def _construct_scope(values: dict[str, object]) -> CapsuleBootstrapScope:
    return CapsuleBootstrapScope(**values)  # type: ignore[arg-type]


def test_scope_is_frozen_slotted_keyword_only_and_uses_fixed_schema() -> None:
    scope = _scope()

    assert scope.scope_schema == CAPSULE_BOOTSTRAP_SCOPE_SCHEMA
    assert not hasattr(scope, "__dict__")
    with pytest.raises(FrozenInstanceError):
        scope.run_id = "retargeted"  # type: ignore[misc]
    with pytest.raises(TypeError):
        CapsuleBootstrapScope(  # type: ignore[call-arg,misc]
            *_scope_values().values()
        )


def test_wire_mapping_round_trips_exact_fields_and_canonical_bytes() -> None:
    scope = _scope()
    mapping = scope.wire_mapping()

    assert frozenset(mapping) == CAPSULE_BOOTSTRAP_SCOPE_WIRE_FIELDS
    assert mapping["bootstrap_scope_schema"] == CAPSULE_BOOTSTRAP_SCOPE_SCHEMA
    assert CapsuleBootstrapScope.from_wire_mapping(mapping) == scope
    assert scope.canonical_bytes() == json.dumps(
        mapping,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    mapping["run_id"] = "retargeted"
    assert scope.run_id == "run-2026.07.20:bootstrap_01"


def test_scope_digest_is_domain_separated_and_deterministic() -> None:
    scope = _scope()
    expected_payload = json.dumps(
        {
            "domain": "galaxy.capsule-bootstrap-scope",
            "scope": scope.wire_mapping(),
            "version": 1,
        },
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    expected = hashlib.sha256(expected_payload).hexdigest()
    assert scope.digest() == expected
    assert capsule_bootstrap_scope_digest(scope) == expected
    assert expected != hashlib.sha256(scope.canonical_bytes()).hexdigest()


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("installed_repository_identity", "A" * 64),
        ("canonical_repository_id", "b" * 63),
        ("repository_attestation_digest", "g" * 64),
        ("source_snapshot_receipt_digest", ""),
        ("anchor_receipt_digest", None),
        ("boot_receipt_digest", 7),
        ("controller_activation_receipt_digest", "0" * 63),
        ("recovery_receipt_digest", "1" * 65),
        ("external_roots_manifest_digest", "not-a-digest"),
        ("expected_base_sha", "4" * 64),
        ("run_id", "contains a space"),
        ("run_id", "x" * 129),
    ],
)
def test_constructor_rejects_malformed_digest_oid_and_identifier_fields(
    field_name: str,
    replacement: object,
) -> None:
    values = _scope_values()
    values[field_name] = replacement

    with pytest.raises(CapsuleBootstrapScopeValidationError):
        _construct_scope(values)


def test_constructor_requires_distinct_repository_identities_and_receipt_roles() -> None:
    same_identity = _scope_values()
    same_identity["canonical_repository_id"] = same_identity[
        "installed_repository_identity"
    ]
    with pytest.raises(CapsuleBootstrapScopeValidationError, match="distinct"):
        _construct_scope(same_identity)

    duplicate_receipt = _scope_values()
    duplicate_receipt["recovery_receipt_digest"] = duplicate_receipt[
        "boot_receipt_digest"
    ]
    with pytest.raises(CapsuleBootstrapScopeValidationError, match="distinct"):
        _construct_scope(duplicate_receipt)


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("run_revision", 1),
        ("run_revision", False),
        ("activation_generation", 0),
        ("activation_generation", True),
        ("boot_generation", -1),
        ("controller_generation", 0),
        ("watchdog_generation", 0),
        ("revocation_generation", -1),
        ("revocation_generation", False),
    ],
)
def test_constructor_enforces_exact_bootstrap_and_generation_integers(
    field_name: str,
    replacement: object,
) -> None:
    values = _scope_values()
    values[field_name] = replacement

    with pytest.raises(CapsuleBootstrapScopeValidationError):
        _construct_scope(values)


@pytest.mark.parametrize(
    "bad_root",
    [
        r"c:\ProgramData\Galaxy\State",
        "C:/ProgramData/Galaxy/State",
        "C:\\ProgramData\\Galaxy\\State\\",
        r"C:\ProgramData\.\Galaxy\State",
        r"C:\ProgramData\Galaxy\..\State",
        r"C:\ProgramData\\Galaxy\State",
        r"\\server\share\Galaxy\State",
        r"\\?\C:\ProgramData\Galaxy\State",
        r"\\.\C:\ProgramData\Galaxy\State",
        r"C:ProgramData\Galaxy\State",
        r"\ProgramData\Galaxy\State",
        r"ProgramData\Galaxy\State",
        "C:\\",
        r"C:\ProgramData\GALAX~1\State",
        r"C:\ProgramData\Galaxy.\State",
        r"C:\ProgramData\Galaxy \State",
        r"C:\ProgramData\NUL\State",
        r"C:\ProgramData\Galaxy:stream\State",
    ],
)
def test_constructor_rejects_noncanonical_or_aliased_windows_roots(
    bad_root: str,
) -> None:
    values = _scope_values()
    values["controller_state_root"] = bad_root

    with pytest.raises(CapsuleBootstrapScopeValidationError, match="root"):
        _construct_scope(values)


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("controller_state_root", r"C:\Repositories\9to5\state"),
        ("controller_state_root", r"C:\Repositories"),
        ("installed_controller_root", r"C:\Repositories\9to5\controller"),
        ("installed_controller_root", r"C:\Repositories"),
        ("source_root", r"C:\ProgramData\Galaxy\Controller\source"),
    ],
)
def test_constructor_rejects_source_overlap_in_either_direction(
    field_name: str,
    replacement: str,
) -> None:
    values = _scope_values()
    values[field_name] = replacement

    with pytest.raises(CapsuleBootstrapScopeValidationError, match="overlap"):
        _construct_scope(values)


def test_constructor_allows_state_root_beneath_installed_controller_root() -> None:
    assert _scope().controller_state_root.startswith(_INSTALLED_ROOT + "\\")


def test_external_roots_manifest_digest_is_an_opaque_persisted_manifest_reference() -> None:
    values = _scope_values()
    values["external_roots_manifest_digest"] = _DIGEST_3

    scope = _construct_scope(values)

    assert scope.external_roots_manifest_digest == _DIGEST_3


@pytest.mark.parametrize(
    "timestamp",
    [
        "2099-01-01T00:00:00Z",
        "2099-01-01T00:00:00-05:00",
        "2099-01-01T00:00:00.000000+00:00",
        "2099-01-01t00:00:00+00:00",
        "2099-01-01T00:00+00:00",
        "2099-02-30T00:00:00+00:00",
        "2099-01-01T00:00:00",
        " 2099-01-01T00:00:00+00:00",
    ],
)
def test_constructor_requires_one_canonical_utc_rfc3339_encoding(
    timestamp: str,
) -> None:
    values = _scope_values()
    values["run_deadline"] = timestamp

    with pytest.raises(CapsuleBootstrapScopeValidationError, match="run_deadline"):
        _construct_scope(values)


def test_constructor_rejects_deadline_after_capability_expiry_but_allows_equality() -> None:
    values = _scope_values()
    values["run_deadline"] = "2099-01-01T01:00:01+00:00"
    with pytest.raises(CapsuleBootstrapScopeValidationError, match="after"):
        _construct_scope(values)

    equal = _scope_values()
    equal["run_deadline"] = equal["capability_expires_at"]
    assert _construct_scope(equal).run_deadline == equal["capability_expires_at"]


def test_from_wire_mapping_rejects_nonexact_mapping_schema_keys_and_value_types() -> None:
    mapping = _scope().wire_mapping()

    class DictSubclass(dict[str, object]):
        pass

    attacks: list[object] = [
        {key: value for key, value in mapping.items() if key != "run_id"},
        {**mapping, "unexpected": "field"},
        {**mapping, "bootstrap_scope_schema": "galaxy.capsule-bootstrap-scope/v2"},
        {**mapping, "bootstrap_scope_schema": 1},
        {**mapping, "controller_generation": True},
        DictSubclass(mapping),
    ]

    for attack in attacks:
        with pytest.raises(CapsuleBootstrapScopeValidationError):
            CapsuleBootstrapScope.from_wire_mapping(attack)


def test_explicit_validation_rechecks_a_tampered_frozen_instance() -> None:
    scope = _scope()
    object.__setattr__(scope, "run_revision", 1)

    with pytest.raises(CapsuleBootstrapScopeValidationError):
        validate_capsule_bootstrap_scope(scope)
    with pytest.raises(CapsuleBootstrapScopeValidationError):
        scope.wire_mapping()
    with pytest.raises(CapsuleBootstrapScopeValidationError):
        scope.canonical_bytes()
    with pytest.raises(CapsuleBootstrapScopeValidationError):
        capsule_bootstrap_scope_digest(scope)
