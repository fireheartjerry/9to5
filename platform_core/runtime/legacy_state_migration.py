"""One-use, no-follow legacy state snapshot admission.

RUN/TEST: python -m pytest tests/execution/test_legacy_state_migration.py
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, TypeVar

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}$")
_FORBIDDEN_NAMES = frozenset({".env", "sie_overrides.json"})
_T = TypeVar("_T")


class LegacyStateMigrationRefused(RuntimeError):
    """Legacy state cannot be snapshotted within the one-use migration policy."""


def _is_reparse(info: os.stat_result) -> bool:
    return bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _time(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise LegacyStateMigrationRefused("migration authority expiry is invalid") from exc
    if result.tzinfo is None:
        raise LegacyStateMigrationRefused("migration authority expiry is not absolute")
    return result.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class LegacySnapshotEntry:
    logical_path: str
    size: int
    sha256: str
    payload: bytes


def validateLegacyMigrationInputs(
    roots: Iterable[str | Path],
    *,
    byte_quota: int,
    file_quota: int,
) -> tuple[LegacySnapshotEntry, ...]:
    """Snapshot an explicit allowlist without following links or multi-links."""

    if type(byte_quota) is not int or byte_quota < 0 or type(file_quota) is not int or file_quota < 0:
        raise LegacyStateMigrationRefused("migration quotas are invalid")
    root_paths = tuple(Path(root) for root in roots)
    if len(set(root_paths)) != len(root_paths):
        raise LegacyStateMigrationRefused("migration allowlist contains duplicates")
    entries: list[LegacySnapshotEntry] = []
    total = 0
    for root_index, root in enumerate(root_paths):
        try:
            info = root.lstat()
        except OSError as exc:
            raise LegacyStateMigrationRefused("legacy input is unavailable") from exc
        if root.is_symlink() or _is_reparse(info) or info.st_nlink != 1:
            raise LegacyStateMigrationRefused("legacy input identity is unsafe")
        candidates = (root,) if root.is_file() else tuple(sorted(root.rglob("*")))
        for path in candidates:
            try:
                current = path.lstat()
            except OSError as exc:
                raise LegacyStateMigrationRefused("legacy entry cannot be inspected") from exc
            if path.is_symlink() or _is_reparse(current) or current.st_nlink != 1:
                raise LegacyStateMigrationRefused("legacy entry identity is unsafe")
            if path.name.casefold() in _FORBIDDEN_NAMES:
                raise LegacyStateMigrationRefused("target configuration is not migratable state")
            if path.is_dir():
                continue
            if not path.is_file():
                raise LegacyStateMigrationRefused("legacy entry type is unsupported")
            try:
                payload = path.read_bytes()
            except OSError as exc:
                raise LegacyStateMigrationRefused("legacy entry cannot be read") from exc
            after = path.lstat()
            if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise LegacyStateMigrationRefused("legacy entry raced during snapshot")
            total += len(payload)
            if len(entries) + 1 > file_quota or total > byte_quota:
                raise LegacyStateMigrationRefused("legacy snapshot exceeds its quota")
            relative = path.name if root.is_file() else path.relative_to(root).as_posix()
            entries.append(
                LegacySnapshotEntry(
                    logical_path=f"root-{root_index}/{relative}",
                    size=len(payload),
                    sha256=hashlib.sha256(payload).hexdigest(),
                    payload=payload,
                )
            )
    return tuple(entries)


@dataclass(frozen=True, slots=True)
class LegacyStateMigrationAuthority:
    migration_id: str
    expires_at: str
    _issuer_identity: int
    _seal: object


class LegacyStateMigrationController:
    def __init__(
        self,
        *,
        snapshot_root: str | Path,
        parser: Callable[[tuple[LegacySnapshotEntry, ...]], _T],
        process_capability: object | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._snapshot_root = Path(snapshot_root)
        self._parser = parser
        self._process_capability = process_capability
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._identity = id(self)
        self._seal = object()
        self._consumed: set[str] = set()

    def _issueDiagnosticAuthority(
        self,
        *,
        process_capability: object,
        migration_id: str,
        expires_at: str,
    ) -> LegacyStateMigrationAuthority:
        if self._process_capability is None or process_capability is not self._process_capability:
            raise LegacyStateMigrationRefused("migration process capability differs")
        if not _ID.fullmatch(migration_id):
            raise LegacyStateMigrationRefused("migration_id is invalid")
        if _time(expires_at) <= self._clock().astimezone(timezone.utc):
            raise LegacyStateMigrationRefused("migration authority already expired")
        return LegacyStateMigrationAuthority(
            migration_id=migration_id,
            expires_at=expires_at,
            _issuer_identity=self._identity,
            _seal=self._seal,
        )

    def _validate(self, authority: object) -> LegacyStateMigrationAuthority:
        if type(authority) is not LegacyStateMigrationAuthority:
            raise LegacyStateMigrationRefused("exact process-local migration authority is required")
        assert isinstance(authority, LegacyStateMigrationAuthority)
        if authority._issuer_identity != self._identity or authority._seal is not self._seal:
            raise LegacyStateMigrationRefused("migration authority issuer differs")
        if authority.migration_id in self._consumed:
            raise LegacyStateMigrationRefused("migration authority was already consumed")
        if _time(authority.expires_at) <= self._clock().astimezone(timezone.utc):
            raise LegacyStateMigrationRefused("migration authority expired")
        return authority

    def migrate(
        self,
        roots: Iterable[str | Path],
        *,
        authority: object,
        byte_quota: int = 64 * 1024 * 1024,
        file_quota: int = 100_000,
    ) -> _T:
        validated = self._validate(authority)
        entries = validateLegacyMigrationInputs(
            roots,
            byte_quota=byte_quota,
            file_quota=file_quota,
        )
        result = self._parser(entries)
        self._consumed.add(validated.migration_id)
        return result


__all__ = [
    "LegacySnapshotEntry",
    "LegacyStateMigrationAuthority",
    "LegacyStateMigrationController",
    "LegacyStateMigrationRefused",
    "validateLegacyMigrationInputs",
]
