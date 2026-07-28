"""Dark, authority-free schema for capsule-owned controller bootstrap facts.

This module validates lexical wire facts only.  In particular, canonical
Windows path strings are not proof that the named filesystem objects have not
been rebound; the installed capsule must retain and revalidate native handles
before granting runtime authority.  ``external_roots_manifest_digest`` is an
opaque SHA-256 reference to the persisted ``galaxy.external-repository-roots/v1``
manifest owned by ``canonical_repo``; this module deliberately does not invent
or reconstruct a weaker lexical-root manifest.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import ntpath
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import ClassVar

CAPSULE_BOOTSTRAP_SCOPE_SCHEMA = "galaxy.capsule-bootstrap-scope/v1"

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_PORTABLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_UTC_RFC3339_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\+00:00$"
)
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Z]:$")
_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
)
_WINDOWS_INVALID_COMPONENT_CHARS = frozenset('<>:"/\\|?*')

CAPSULE_BOOTSTRAP_SCOPE_WIRE_FIELDS = frozenset(
    {
        "bootstrap_scope_schema",
        "installed_repository_identity",
        "canonical_repository_id",
        "run_id",
        "run_revision",
        "controller_state_root",
        "source_root",
        "installed_controller_root",
        "external_roots_manifest_digest",
        "repository_attestation_digest",
        "expected_base_sha",
        "source_snapshot_receipt_digest",
        "anchor_receipt_digest",
        "boot_receipt_digest",
        "controller_activation_receipt_digest",
        "recovery_receipt_digest",
        "activation_generation",
        "boot_generation",
        "controller_generation",
        "watchdog_generation",
        "revocation_generation",
        "capability_expires_at",
        "run_deadline",
    }
)


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


class CapsuleBootstrapScopeValidationError(ValueError):
    """A bootstrap scope is malformed, ambiguous, or internally inconsistent."""


def _require_exact_str(value: object, name: str) -> str:
    if type(value) is not str:
        raise CapsuleBootstrapScopeValidationError(f"{name} must be an exact string")
    return value


def _require_digest(value: object, name: str) -> str:
    text = _require_exact_str(value, name)
    if _DIGEST_RE.fullmatch(text) is None:
        raise CapsuleBootstrapScopeValidationError(
            f"{name} must be a lowercase SHA-256 digest"
        )
    return text


def _require_git_sha1(value: object, name: str) -> str:
    text = _require_exact_str(value, name)
    if _GIT_SHA1_RE.fullmatch(text) is None:
        raise CapsuleBootstrapScopeValidationError(
            f"{name} must be a full lowercase Git SHA-1"
        )
    return text


def _require_portable_id(value: object, name: str) -> str:
    text = _require_exact_str(value, name)
    if _PORTABLE_ID_RE.fullmatch(text) is None:
        raise CapsuleBootstrapScopeValidationError(
            f"{name} must be a closed portable identifier"
        )
    return text


def _require_exact_int(value: object, name: str, *, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise CapsuleBootstrapScopeValidationError(
            f"{name} must be an exact integer >= {minimum}"
        )
    return value


def _require_canonical_windows_root(value: object, name: str) -> str:
    """Validate one lexical local-drive root without touching the filesystem."""

    text = _require_exact_str(value, name)
    if unicodedata.normalize("NFC", text) != text:
        raise CapsuleBootstrapScopeValidationError(f"{name} root must be NFC-normalized")
    if not text or "/" in text or text.startswith("\\") or text.endswith("\\"):
        raise CapsuleBootstrapScopeValidationError(
            f"{name} root must be an exact local Windows absolute path"
        )
    drive, tail = ntpath.splitdrive(text)
    if (
        _WINDOWS_DRIVE_RE.fullmatch(drive) is None
        or not tail.startswith("\\")
        or tail == "\\"
        or ntpath.normpath(text) != text
        or not ntpath.isabs(text)
    ):
        raise CapsuleBootstrapScopeValidationError(
            f"{name} root must be an exact normalized local Windows absolute path"
        )
    components = tail[1:].split("\\")
    if not components or any(not component for component in components):
        raise CapsuleBootstrapScopeValidationError(
            f"{name} root contains an empty path component"
        )
    for component in components:
        if (
            component in {".", ".."}
            or component.endswith((" ", "."))
            or "~" in component
            or any(character in _WINDOWS_INVALID_COMPONENT_CHARS for character in component)
            or any(ord(character) < 32 for character in component)
        ):
            raise CapsuleBootstrapScopeValidationError(
                f"{name} root contains a noncanonical or aliased path component"
            )
        device_stem = component.partition(".")[0].upper()
        if device_stem in _WINDOWS_RESERVED_NAMES:
            raise CapsuleBootstrapScopeValidationError(
                f"{name} root contains a reserved Windows path component"
            )
    return text


def _path_identity_parts(path: str) -> tuple[str, ...]:
    drive, tail = ntpath.splitdrive(path)
    return (drive.casefold(), *(part.casefold() for part in tail[1:].split("\\")))


def _paths_overlap(left: str, right: str) -> bool:
    left_parts = _path_identity_parts(left)
    right_parts = _path_identity_parts(right)
    shorter = min(len(left_parts), len(right_parts))
    return left_parts[:shorter] == right_parts[:shorter]


def _require_source_disjoint(
    *,
    controller_state_root: str,
    source_root: str,
    installed_controller_root: str,
) -> None:
    if _paths_overlap(source_root, controller_state_root):
        raise CapsuleBootstrapScopeValidationError(
            "source root must not overlap controller state root"
        )
    if _paths_overlap(source_root, installed_controller_root):
        raise CapsuleBootstrapScopeValidationError(
            "source root must not overlap installed controller root"
        )


def _require_canonical_utc_rfc3339(value: object, name: str) -> datetime:
    text = _require_exact_str(value, name)
    if _UTC_RFC3339_RE.fullmatch(text) is None:
        raise CapsuleBootstrapScopeValidationError(
            f"{name} must use canonical UTC RFC3339 seconds with +00:00"
        )
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S+00:00").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise CapsuleBootstrapScopeValidationError(
            f"{name} must be a valid canonical UTC RFC3339 timestamp"
        ) from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%S+00:00") != text:
        raise CapsuleBootstrapScopeValidationError(
            f"{name} must use canonical UTC RFC3339 seconds with +00:00"
        )
    return parsed


@dataclass(frozen=True, slots=True, kw_only=True)
class CapsuleBootstrapScope:
    """Immutable capsule-owned facts carried identically in both OS frames."""

    scope_schema: ClassVar[str] = CAPSULE_BOOTSTRAP_SCOPE_SCHEMA

    installed_repository_identity: str
    canonical_repository_id: str
    run_id: str
    run_revision: int
    controller_state_root: str
    source_root: str
    installed_controller_root: str
    external_roots_manifest_digest: str
    repository_attestation_digest: str
    expected_base_sha: str
    source_snapshot_receipt_digest: str
    anchor_receipt_digest: str
    boot_receipt_digest: str
    controller_activation_receipt_digest: str
    recovery_receipt_digest: str
    activation_generation: int
    boot_generation: int
    controller_generation: int
    watchdog_generation: int
    revocation_generation: int
    capability_expires_at: str
    run_deadline: str

    def __post_init__(self) -> None:
        _validate_scope_fields(self)

    def wire_mapping(self) -> dict[str, object]:
        """Return a detached exact-key mapping for canonical frame encoding."""

        validate_capsule_bootstrap_scope(self)
        return {
            "bootstrap_scope_schema": CAPSULE_BOOTSTRAP_SCOPE_SCHEMA,
            "installed_repository_identity": self.installed_repository_identity,
            "canonical_repository_id": self.canonical_repository_id,
            "run_id": self.run_id,
            "run_revision": self.run_revision,
            "controller_state_root": self.controller_state_root,
            "source_root": self.source_root,
            "installed_controller_root": self.installed_controller_root,
            "external_roots_manifest_digest": self.external_roots_manifest_digest,
            "repository_attestation_digest": self.repository_attestation_digest,
            "expected_base_sha": self.expected_base_sha,
            "source_snapshot_receipt_digest": self.source_snapshot_receipt_digest,
            "anchor_receipt_digest": self.anchor_receipt_digest,
            "boot_receipt_digest": self.boot_receipt_digest,
            "controller_activation_receipt_digest": (
                self.controller_activation_receipt_digest
            ),
            "recovery_receipt_digest": self.recovery_receipt_digest,
            "activation_generation": self.activation_generation,
            "boot_generation": self.boot_generation,
            "controller_generation": self.controller_generation,
            "watchdog_generation": self.watchdog_generation,
            "revocation_generation": self.revocation_generation,
            "capability_expires_at": self.capability_expires_at,
            "run_deadline": self.run_deadline,
        }

    @classmethod
    def from_wire_mapping(cls, value: object) -> CapsuleBootstrapScope:
        """Decode the exact static scope subrecord from one capability frame."""

        if (
            type(value) is not dict
            or frozenset(value) != CAPSULE_BOOTSTRAP_SCOPE_WIRE_FIELDS
        ):
            raise CapsuleBootstrapScopeValidationError(
                "capsule bootstrap scope has unknown or missing wire fields"
            )
        mapping: dict[object, object] = value
        schema = mapping["bootstrap_scope_schema"]
        if type(schema) is not str or schema != CAPSULE_BOOTSTRAP_SCOPE_SCHEMA:
            raise CapsuleBootstrapScopeValidationError(
                "capsule bootstrap scope schema is not supported"
            )
        return cls(
            installed_repository_identity=_require_exact_str(
                mapping["installed_repository_identity"],
                "installed_repository_identity",
            ),
            canonical_repository_id=_require_exact_str(
                mapping["canonical_repository_id"], "canonical_repository_id"
            ),
            run_id=_require_exact_str(mapping["run_id"], "run_id"),
            run_revision=_wire_int(mapping, "run_revision"),
            controller_state_root=_require_exact_str(
                mapping["controller_state_root"], "controller_state_root"
            ),
            source_root=_require_exact_str(mapping["source_root"], "source_root"),
            installed_controller_root=_require_exact_str(
                mapping["installed_controller_root"], "installed_controller_root"
            ),
            external_roots_manifest_digest=_require_exact_str(
                mapping["external_roots_manifest_digest"],
                "external_roots_manifest_digest",
            ),
            repository_attestation_digest=_require_exact_str(
                mapping["repository_attestation_digest"],
                "repository_attestation_digest",
            ),
            expected_base_sha=_require_exact_str(
                mapping["expected_base_sha"], "expected_base_sha"
            ),
            source_snapshot_receipt_digest=_require_exact_str(
                mapping["source_snapshot_receipt_digest"],
                "source_snapshot_receipt_digest",
            ),
            anchor_receipt_digest=_require_exact_str(
                mapping["anchor_receipt_digest"], "anchor_receipt_digest"
            ),
            boot_receipt_digest=_require_exact_str(
                mapping["boot_receipt_digest"], "boot_receipt_digest"
            ),
            controller_activation_receipt_digest=_require_exact_str(
                mapping["controller_activation_receipt_digest"],
                "controller_activation_receipt_digest",
            ),
            recovery_receipt_digest=_require_exact_str(
                mapping["recovery_receipt_digest"], "recovery_receipt_digest"
            ),
            activation_generation=_wire_int(mapping, "activation_generation"),
            boot_generation=_wire_int(mapping, "boot_generation"),
            controller_generation=_wire_int(mapping, "controller_generation"),
            watchdog_generation=_wire_int(mapping, "watchdog_generation"),
            revocation_generation=_wire_int(mapping, "revocation_generation"),
            capability_expires_at=_require_exact_str(
                mapping["capability_expires_at"], "capability_expires_at"
            ),
            run_deadline=_require_exact_str(mapping["run_deadline"], "run_deadline"),
        )

    def canonical_bytes(self) -> bytes:
        """Return canonical strict-UTF-8 bytes for exact frame comparison."""

        return _canonical_json_bytes(self.wire_mapping())

    def digest(self) -> str:
        """Return the domain-separated digest of every static scope field."""

        return capsule_bootstrap_scope_digest(self)


def capsule_bootstrap_scope_digest(scope: CapsuleBootstrapScope) -> str:
    """Return the versioned domain-separated digest for one validated scope."""

    validated = validate_capsule_bootstrap_scope(scope)
    payload = {
        "domain": "galaxy.capsule-bootstrap-scope",
        "scope": validated.wire_mapping(),
        "version": 1,
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _wire_int(mapping: dict[object, object], name: str) -> int:
    value = mapping[name]
    if type(value) is not int:
        raise CapsuleBootstrapScopeValidationError(
            f"{name} must be an exact integer"
        )
    return value


def _validate_scope_fields(scope: CapsuleBootstrapScope) -> None:
    installed_identity = _require_digest(
        scope.installed_repository_identity, "installed_repository_identity"
    )
    repository_id = _require_digest(
        scope.canonical_repository_id, "canonical_repository_id"
    )
    if hmac.compare_digest(installed_identity, repository_id):
        raise CapsuleBootstrapScopeValidationError(
            "installed and canonical repository identities must be distinct"
        )
    _require_portable_id(scope.run_id, "run_id")
    if type(scope.run_revision) is not int or scope.run_revision != 0:
        raise CapsuleBootstrapScopeValidationError(
            "run_revision must be the exact bootstrap revision integer 0"
        )

    state_root = _require_canonical_windows_root(
        scope.controller_state_root, "controller_state_root"
    )
    source_root = _require_canonical_windows_root(scope.source_root, "source_root")
    installed_root = _require_canonical_windows_root(
        scope.installed_controller_root, "installed_controller_root"
    )
    _require_source_disjoint(
        controller_state_root=state_root,
        source_root=source_root,
        installed_controller_root=installed_root,
    )

    _require_digest(
        scope.external_roots_manifest_digest, "external_roots_manifest_digest"
    )
    _require_digest(
        scope.repository_attestation_digest, "repository_attestation_digest"
    )
    _require_git_sha1(scope.expected_base_sha, "expected_base_sha")

    receipt_digests = (
        _require_digest(
            scope.source_snapshot_receipt_digest,
            "source_snapshot_receipt_digest",
        ),
        _require_digest(scope.anchor_receipt_digest, "anchor_receipt_digest"),
        _require_digest(scope.boot_receipt_digest, "boot_receipt_digest"),
        _require_digest(
            scope.controller_activation_receipt_digest,
            "controller_activation_receipt_digest",
        ),
        _require_digest(scope.recovery_receipt_digest, "recovery_receipt_digest"),
    )
    if len(set(receipt_digests)) != len(receipt_digests):
        raise CapsuleBootstrapScopeValidationError(
            "bootstrap receipt role digests must be distinct"
        )

    _require_exact_int(scope.activation_generation, "activation_generation", minimum=1)
    _require_exact_int(scope.boot_generation, "boot_generation", minimum=1)
    _require_exact_int(scope.controller_generation, "controller_generation", minimum=1)
    _require_exact_int(scope.watchdog_generation, "watchdog_generation", minimum=1)
    _require_exact_int(scope.revocation_generation, "revocation_generation", minimum=0)

    expires_at = _require_canonical_utc_rfc3339(
        scope.capability_expires_at, "capability_expires_at"
    )
    deadline = _require_canonical_utc_rfc3339(scope.run_deadline, "run_deadline")
    if deadline > expires_at:
        raise CapsuleBootstrapScopeValidationError(
            "run_deadline must not be after capability_expires_at"
        )

def validate_capsule_bootstrap_scope(value: object) -> CapsuleBootstrapScope:
    """Require and revalidate the exact frozen scope type before trusted use."""

    if type(value) is not CapsuleBootstrapScope:
        raise CapsuleBootstrapScopeValidationError(
            "capsule bootstrap scope must be the exact validated type"
        )
    _validate_scope_fields(value)
    return value


__all__ = [
    "CAPSULE_BOOTSTRAP_SCOPE_SCHEMA",
    "CAPSULE_BOOTSTRAP_SCOPE_WIRE_FIELDS",
    "CapsuleBootstrapScope",
    "CapsuleBootstrapScopeValidationError",
    "capsule_bootstrap_scope_digest",
    "validate_capsule_bootstrap_scope",
]
