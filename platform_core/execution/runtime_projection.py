"""External, content-addressed runtime projection for one model transaction.

Generated settings, context, task snapshots, session data, and telemetry are
kept outside both canonical and candidate repositories so they cannot enter a
staged revision.

RUN/TEST: python -m pytest tests/execution/test_runtime_projection.py
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from platform_core.core.fsio import (
    assertNoReparsePath,
    exclusiveCreateBytes,
    readNoFollowBytes,
)

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}$")
_MAX_CONTEXT = 2 * 1024 * 1024
_MAX_JSON = 2 * 1024 * 1024


class RuntimeProjectionRefused(RuntimeError):
    """The projection cannot prove external ownership and exact contents."""


def _canonical(value: object) -> bytes:
    try:
        raw = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise RuntimeProjectionRefused("projection JSON is not canonicalizable") from exc
    if len(raw) > _MAX_JSON:
        raise RuntimeProjectionRefused("projection JSON exceeds its quota")
    return raw


def _resolved(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except OSError as exc:
        raise RuntimeProjectionRefused("projection path cannot be normalized") from exc


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _assert_external(path: Path, forbidden_roots: tuple[Path, ...]) -> None:
    candidate = _resolved(path)
    for forbidden in forbidden_roots:
        blocked = _resolved(Path(forbidden))
        if _within(candidate, blocked) or _within(blocked, candidate):
            raise RuntimeProjectionRefused("runtime projection overlaps a forbidden root")


def _mkdir(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        assertNoReparsePath(path)
        if path.is_symlink() or not path.is_dir():
            raise RuntimeProjectionRefused("projection directory identity is unsafe")
        if os.name != "nt":
            path.chmod(0o700)
    except OSError as exc:
        raise RuntimeProjectionRefused("projection directory cannot be created safely") from exc


def _create_or_verify(path: Path, payload: bytes) -> None:
    try:
        exclusiveCreateBytes(path, payload)
    except FileExistsError:
        try:
            observed = readNoFollowBytes(path, max_bytes=max(len(payload), 1) + 1)
        except OSError as exc:
            raise RuntimeProjectionRefused("existing projection file cannot be verified") from exc
        if observed != payload:
            raise RuntimeProjectionRefused("existing projection file differs")
    except OSError as exc:
        raise RuntimeProjectionRefused("projection file cannot be created") from exc
    if os.name != "nt":
        path.chmod(0o600)


def _manifest_payload(
    *, transaction_id: str, settings: bytes, context: bytes, task_snapshot: bytes
) -> dict[str, object]:
    return {
        "schema": "galaxy.runtime-projection/v1",
        "transaction_id": transaction_id,
        "files": {
            "context.bin": {
                "sha256": hashlib.sha256(context).hexdigest(),
                "size": len(context),
            },
            "settings.json": {
                "sha256": hashlib.sha256(settings).hexdigest(),
                "size": len(settings),
            },
            "task.json": {
                "sha256": hashlib.sha256(task_snapshot).hexdigest(),
                "size": len(task_snapshot),
            },
        },
        "writable_directories": ["session", "telemetry"],
        "activation_authority": False,
    }


@dataclass(frozen=True, slots=True)
class RuntimeProjection:
    root: Path
    settings_path: Path
    context_path: Path
    task_snapshot_path: Path
    session_root: Path
    telemetry_root: Path
    manifest_path: Path
    manifest_digest: str

    @classmethod
    def create(
        cls,
        *,
        root: str | Path,
        transaction_id: str,
        settings: Mapping[str, Any],
        context: bytes,
        task_snapshot: Mapping[str, Any],
        forbidden_roots: tuple[Path, ...] = (),
    ) -> "RuntimeProjection":
        if not isinstance(transaction_id, str) or not _ID.fullmatch(transaction_id):
            raise RuntimeProjectionRefused("transaction_id is invalid")
        if type(context) is not bytes or len(context) > _MAX_CONTEXT:
            raise RuntimeProjectionRefused("context must be bounded immutable bytes")
        base = Path(root)
        projection_root = base / transaction_id
        _assert_external(projection_root, tuple(Path(item) for item in forbidden_roots))
        _mkdir(projection_root)
        session_root = projection_root / "session"
        telemetry_root = projection_root / "telemetry"
        _mkdir(session_root)
        _mkdir(telemetry_root)

        settings_raw = _canonical(dict(settings))
        task_raw = _canonical(dict(task_snapshot))
        settings_path = projection_root / "settings.json"
        context_path = projection_root / "context.bin"
        task_path = projection_root / "task.json"
        _create_or_verify(settings_path, settings_raw)
        _create_or_verify(context_path, context)
        _create_or_verify(task_path, task_raw)

        manifest_raw = _canonical(
            _manifest_payload(
                transaction_id=transaction_id,
                settings=settings_raw,
                context=context,
                task_snapshot=task_raw,
            )
        )
        manifest_path = projection_root / "manifest.json"
        _create_or_verify(manifest_path, manifest_raw)
        return cls(
            root=projection_root,
            settings_path=settings_path,
            context_path=context_path,
            task_snapshot_path=task_path,
            session_root=session_root,
            telemetry_root=telemetry_root,
            manifest_path=manifest_path,
            manifest_digest=hashlib.sha256(manifest_raw).hexdigest(),
        )

    def recomputeManifestDigest(self) -> str:
        raw = readNoFollowBytes(self.manifest_path, max_bytes=_MAX_JSON + 1)
        value = json.loads(raw.decode("utf-8", errors="strict"))
        if _canonical(value) != raw:
            raise RuntimeProjectionRefused("runtime projection manifest is not canonical")
        files = value.get("files") if isinstance(value, dict) else None
        if not isinstance(files, dict):
            raise RuntimeProjectionRefused("runtime projection manifest is malformed")
        observed = {
            "context.bin": self.context_path,
            "settings.json": self.settings_path,
            "task.json": self.task_snapshot_path,
        }
        for name, path in observed.items():
            record = files.get(name)
            if not isinstance(record, dict):
                raise RuntimeProjectionRefused("runtime projection file record is missing")
            payload = readNoFollowBytes(path, max_bytes=_MAX_JSON + 1)
            if record.get("size") != len(payload) or record.get("sha256") != hashlib.sha256(
                payload
            ).hexdigest():
                raise RuntimeProjectionRefused("runtime projection file differs from manifest")
        return hashlib.sha256(raw).hexdigest()


__all__ = ["RuntimeProjection", "RuntimeProjectionRefused"]
