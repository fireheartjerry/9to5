"""RED contracts for the exact nine-role offline runtime image manifest."""

from __future__ import annotations

import importlib
from pathlib import Path

_ROLES = frozenset(
    {
        "candidate_parser",
        "command_sandbox",
        "credentialed_driver",
        "object_parser",
        "reviewer",
        "source_fetcher",
        "source_parser",
        "state_store",
        "verifier",
    }
)


def _images():
    return importlib.import_module("platform_core.execution.image_manifest")


def test_activation_image_lock_has_exact_roles_and_complete_digest_bindings() -> None:
    mod = _images()
    lock = mod.loadActivationImageManifest(
        Path("bootstrap/galaxy_launcher/activation_images.lock.json")
    )

    assert lock.schema == "galaxy.activation-images/v1"
    assert frozenset(image.role for image in lock.images) == _ROLES
    assert len(lock.images) == len(_ROLES)
    assert lock.network_acquisition_closed is True
    for image in lock.images:
        assert len(image.archive_sha256) == 64
        assert len(image.image_digest) == 64
        assert len(image.runtime_digest) == 64
        assert len(image.sbom_digest) == 64
        assert len(image.security_profile_digest) == 64


def test_runtime_role_lookup_is_total_and_does_not_fallback() -> None:
    mod = _images()
    lock = mod.loadActivationImageManifest(
        Path("bootstrap/galaxy_launcher/activation_images.lock.json")
    )
    assert {lock.forRole(role).role for role in _ROLES} == _ROLES
