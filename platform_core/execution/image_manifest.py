"""Strict reader for the reviewed nine-role offline activation image lock.

RUN/TEST: python -m pytest tests/execution/test_galaxy_images.py
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from platform_core.core.fsio import readNoFollowBytes

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
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


class ActivationImageManifestRefused(ValueError):
    """The offline image lock is incomplete, ambiguous, or malformed."""


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ActivationImageManifestRefused(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ActivationImageManifestRefused(f"invalid {name}")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ActivationImageManifestRefused(f"invalid {name}")
    return value


@dataclass(frozen=True, slots=True)
class ActivationImage:
    role: str
    archive: str
    archive_sha256: str
    archive_size: int
    image_digest: str
    config_digest: str
    runtime_digest: str
    sbom_digest: str
    security_profile_digest: str
    toolchain_digest: str
    package_manifest_digest: str
    base_digest: str

    @classmethod
    def fromDict(cls, value: object) -> "ActivationImage":
        if not isinstance(value, dict):
            raise ActivationImageManifestRefused("image record must be an object")
        role = _text(value.get("role"), "image role")
        if role not in _ROLES:
            raise ActivationImageManifestRefused(f"unknown image role: {role}")
        archive_size = value.get("archive_size")
        if type(archive_size) is not int or archive_size <= 0:
            raise ActivationImageManifestRefused("archive_size must be positive")
        return cls(
            role=role,
            archive=_text(value.get("archive"), "archive"),
            archive_sha256=_digest(value.get("archive_sha256"), "archive_sha256"),
            archive_size=archive_size,
            image_digest=_digest(value.get("manifest_digest"), "manifest_digest"),
            config_digest=_digest(value.get("config_digest"), "config_digest"),
            runtime_digest=_digest(value.get("runtime_digest"), "runtime_digest"),
            sbom_digest=_digest(value.get("sbom_digest"), "sbom_digest"),
            security_profile_digest=_digest(
                value.get("security_profile_digest"), "security_profile_digest"
            ),
            toolchain_digest=_digest(value.get("toolchain_digest"), "toolchain_digest"),
            package_manifest_digest=_digest(
                value.get("package_manifest_digest"), "package_manifest_digest"
            ),
            base_digest=_digest(value.get("base_digest"), "base_digest"),
        )


@dataclass(frozen=True, slots=True)
class ActivationImageManifest:
    schema: str
    images: tuple[ActivationImage, ...]
    network_acquisition_closed: bool

    def forRole(self, role: str) -> ActivationImage:
        matches = tuple(image for image in self.images if image.role == role)
        if len(matches) != 1:
            raise ActivationImageManifestRefused(f"role is not uniquely bound: {role}")
        return matches[0]


def loadActivationImageManifest(path: str | Path) -> ActivationImageManifest:
    """Load and validate the exact closed role set from a no-follow file read."""

    source = Path(path)
    raw = readNoFollowBytes(source, max_bytes=2 * 1024 * 1024)
    try:
        decoded = raw.decode("utf-8", errors="strict")
        value = json.loads(decoded, object_pairs_hook=_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ActivationImageManifestRefused("image lock is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ActivationImageManifestRefused("image lock must be an object")
    if value.get("schema") != "galaxy.activation-images/v1":
        raise ActivationImageManifestRefused("image lock schema differs")
    if value.get("network_acquisition_closed") is not True:
        raise ActivationImageManifestRefused("network acquisition closure is not proven")
    records = value.get("images")
    if not isinstance(records, list):
        raise ActivationImageManifestRefused("images must be a list")
    images = tuple(ActivationImage.fromDict(record) for record in records)
    roles = tuple(image.role for image in images)
    if len(roles) != len(set(roles)) or frozenset(roles) != _ROLES:
        raise ActivationImageManifestRefused("image roles are duplicate or incomplete")
    return ActivationImageManifest(
        schema="galaxy.activation-images/v1",
        images=images,
        network_acquisition_closed=True,
    )


__all__ = [
    "ActivationImage",
    "ActivationImageManifest",
    "ActivationImageManifestRefused",
    "loadActivationImageManifest",
]
