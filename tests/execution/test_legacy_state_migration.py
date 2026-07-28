"""RED contracts for one-use, no-follow legacy state migration."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def _migration():
    return importlib.import_module("platform_core.runtime.legacy_state_migration")


def test_missing_migration_authority_refuses_before_input_observation(tmp_path: Path) -> None:
    mod = _migration()
    legacy = tmp_path / "legacy"
    parsed: list[object] = []
    controller = mod.LegacyStateMigrationController(
        snapshot_root=tmp_path / "snapshots",
        parser=lambda manifest: parsed.append(manifest),
    )

    with pytest.raises(mod.LegacyStateMigrationRefused):
        controller.migrate((legacy,), authority=None)

    assert parsed == []
    assert not legacy.exists()
    assert not (tmp_path / "snapshots").exists()


def test_migration_rejects_symlinked_allowlisted_input(tmp_path: Path) -> None:
    mod = _migration()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "legacy-link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable for this account")

    with pytest.raises(mod.LegacyStateMigrationRefused):
        mod.validateLegacyMigrationInputs((link,), byte_quota=1024, file_quota=8)
