"""RED contracts for immutable, broker-only repository pre-execution reads."""

from __future__ import annotations

import importlib
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest


def _pre_execution():
    return importlib.import_module("platform_core.execution.pre_execution")


def test_missing_snapshot_authority_refuses_before_snapshot_observation(tmp_path: Path) -> None:
    mod = _pre_execution()
    snapshot = tmp_path / "missing-snapshot"
    broker = mod.PreExecutionReadBroker(
        snapshot_root=snapshot,
        authority=None,
        max_read_bytes=4096,
        max_entries=32,
    )

    with pytest.raises(mod.PreExecutionUnavailable):
        broker.read("README.md")

    assert not snapshot.exists()


def test_snapshot_broker_rejects_symlink_escape_and_never_runs_repo_code(
    tmp_path: Path,
) -> None:
    mod = _pre_execution()
    snapshot = tmp_path / "snapshot"
    outside = tmp_path / "outside"
    snapshot.mkdir()
    outside.mkdir()
    (outside / "goldstone").write_text("secret", encoding="utf-8")
    link = snapshot / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable for this account")
    authority = mod.issueDiagnosticPreExecutionSnapshotAuthority(
        snapshot_root=snapshot,
        base_revision="1" * 40,
        manifest_digest="2" * 64,
        controller_generation=3,
        process_capability=object(),
        expires_at="2099-01-01T00:00:00+00:00",
    )
    broker = mod.PreExecutionReadBroker(
        snapshot_root=snapshot,
        authority=authority,
        max_read_bytes=4096,
        max_entries=32,
    )

    with pytest.raises(mod.PreExecutionUnavailable):
        broker.read("link/goldstone")
    assert "exec" not in broker.operations
    assert "subprocess" not in broker.operations


def test_capsule_mode_refuses_legacy_reads_before_path_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _pre_execution()
    paths = importlib.import_module("platform_core.app_config.paths")
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", object())
    target = tmp_path / "must-not-be-observed.txt"

    with pytest.raises(mod.PreExecutionUnavailable, match="legacy diagnostic"):
        mod.readLegacyText(target, encoding="utf-8")

    assert not target.exists()


def test_capsule_mode_refuses_legacy_path_observation_and_mutation_callables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _pre_execution()
    paths = importlib.import_module("platform_core.app_config.paths")
    calls: list[str] = []
    monkeypatch.setattr(paths, "_CONTROLLER_PATHS", object())

    with pytest.raises(mod.PreExecutionUnavailable, match="legacy diagnostic"):
        mod.observeLegacyPath(lambda: calls.append("observe"))
    with pytest.raises(mod.PreExecutionUnavailable, match="legacy diagnostic"):
        mod.mutateLegacyPath(lambda: calls.append("mutate"))

    assert calls == []


@pytest.mark.parametrize(
    ("opener_name", "patched_target"),
    (
        ("openLegacyFile", "path"),
        ("openLegacyBuiltin", "builtin"),
        ("openLegacyTar", "tar"),
    ),
)
def test_legacy_openers_close_the_handle_before_releasing_runtime_and_path_fences(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    opener_name: str,
    patched_target: str,
) -> None:
    mod = _pre_execution()
    events: list[str] = []

    class TrackedHandle:
        closed = False

        def __enter__(self) -> "TrackedHandle":
            events.append("handle-enter")
            return self

        def __exit__(self, *_exc: object) -> None:
            self.closed = True
            events.append("handle-close")

    handle = TrackedHandle()

    @contextmanager
    def retained_fences() -> Iterator[None]:
        events.append("fences-enter")
        try:
            yield
        finally:
            assert handle.closed
            events.append("fences-exit")

    monkeypatch.setattr(mod, "_legacyDiagnosticAccess", retained_fences)
    if patched_target == "path":
        monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: handle)
    elif patched_target == "builtin":
        monkeypatch.setattr("builtins.open", lambda *_args, **_kwargs: handle)
    else:
        import tarfile

        monkeypatch.setattr(tarfile, "open", lambda *_args, **_kwargs: handle)

    with getattr(mod, opener_name)(tmp_path / "artifact") as opened:
        assert opened is handle
        assert events == ["fences-enter", "handle-enter"]

    assert events == ["fences-enter", "handle-enter", "handle-close", "fences-exit"]
