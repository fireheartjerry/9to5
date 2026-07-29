"""Kernel unit suite for platform_core/core: fsio + jsonl_io + clock + git_io.

Covers the item-R4 acceptance list: concurrent atomic writes (threads AND processes,
no FileNotFoundError / torn file), updateJson corrupt-input .bak + warning, iterRecords
torn-tail tolerance (the adversary_trust regression), lock staleness/steal semantics,
bounded tool timeouts (the worktree hang regression), and RunClock deadline edges.
"""
from __future__ import annotations

import errno
import hashlib
import json
import logging
import os
import stat
import subprocess
import sys
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from platform_core.core import clock, fsio, git_io, jsonl_io

_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# fsio: atomic writes
# ---------------------------------------------------------------------------


def test_native_identity_binds_mount_file_id_and_reparse_tag(tmp_path: Path) -> None:
    with fsio.openNativeDirectory(tmp_path) as directory:
        root = directory.identity
        created = directory.createFile("identity.bin", b"identity")
        observed = directory.listEntries()[0].identity

    assert root.mount_id > 0
    assert root.file_id > 0
    assert root.reparse_tag == 0
    assert created == observed
    assert created.mount_id == root.mount_id
    assert created.volume_id == root.volume_id
    assert created.reparse_tag == 0
    assert fsio._sameNativeFileObject(created, replace(created))
    assert not fsio._sameNativeFileObject(
        created,
        replace(created, mount_id=created.mount_id + 1),
    )
    assert not fsio._sameNativeFileObject(
        created,
        replace(created, reparse_tag=0xA0000003),
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows retained-handle cleanup")
def test_windows_open_directory_identity_failure_closes_child_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_path = tmp_path / "child"
    child_path.mkdir()
    with fsio.openNativeDirectory(tmp_path) as parent:
        real_open = fsio._winOpenRelative
        real_identity = fsio._winIdentity
        real_close = fsio._CloseHandle
        opened: list[int] = []
        closed: list[int] = []

        def tracking_open(*args, **kwargs) -> int:
            handle = real_open(*args, **kwargs)
            opened.append(handle)
            return handle

        def fail_child_identity(handle: int) -> fsio.NativeFileIdentity:
            if handle in opened:
                raise OSError("injected child identity failure")
            return real_identity(handle)

        def tracking_close(handle: int) -> bool:
            closed.append(int(handle))
            return bool(real_close(handle))

        monkeypatch.setattr(fsio, "_winOpenRelative", tracking_open)
        monkeypatch.setattr(fsio, "_winIdentity", fail_child_identity)
        monkeypatch.setattr(fsio, "_CloseHandle", tracking_close)
        with pytest.raises(OSError, match="child identity"):
            parent.openDirectory("child")

        assert len(opened) == 1
        assert opened[0] in closed
        with pytest.raises(OSError):
            real_identity(opened[0])


@pytest.mark.skipif(os.name != "nt", reason="Windows retained-handle cleanup")
def test_windows_open_native_directory_identity_failure_closes_root_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_create = fsio._CreateFileW
    real_identity = fsio._winIdentity
    real_close = fsio._CloseHandle
    opened: list[int] = []
    closed: list[int] = []

    def tracking_create(*args, **kwargs):
        handle = real_create(*args, **kwargs)
        opened.append(int(handle))
        return handle

    def fail_root_identity(handle: int) -> fsio.NativeFileIdentity:
        if int(handle) in opened:
            raise OSError("injected root identity failure")
        return real_identity(handle)

    def tracking_close(handle: int) -> bool:
        closed.append(int(handle))
        return bool(real_close(handle))

    monkeypatch.setattr(fsio, "_CreateFileW", tracking_create)
    monkeypatch.setattr(fsio, "_winIdentity", fail_root_identity)
    monkeypatch.setattr(fsio, "_CloseHandle", tracking_close)
    with pytest.raises(OSError, match="root identity"):
        fsio.openNativeDirectory(tmp_path)

    assert len(opened) == 1
    assert opened[0] in closed
    with pytest.raises(OSError):
        real_identity(opened[0])


@pytest.mark.skipif(os.name != "nt", reason="Windows retained-handle cleanup")
@pytest.mark.parametrize("failure_phase", ("identity", "sync"))
def test_windows_create_directory_setup_failure_closes_created_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_phase: str,
) -> None:
    with fsio.openNativeDirectory(tmp_path) as parent:
        real_open = fsio._winOpenRelative
        real_identity = fsio._winIdentity
        real_close = fsio._CloseHandle
        opened: list[int] = []
        closed: list[int] = []

        def tracking_open(*args, **kwargs) -> int:
            handle = real_open(*args, **kwargs)
            opened.append(handle)
            return handle

        def maybe_fail_identity(handle: int) -> fsio.NativeFileIdentity:
            if failure_phase == "identity" and handle in opened:
                raise OSError("injected create identity failure")
            return real_identity(handle)

        def tracking_close(handle: int) -> bool:
            closed.append(int(handle))
            return bool(real_close(handle))

        def maybe_fail_sync() -> None:
            if failure_phase == "sync":
                raise OSError("injected create sync failure")

        monkeypatch.setattr(fsio, "_winOpenRelative", tracking_open)
        monkeypatch.setattr(fsio, "_winIdentity", maybe_fail_identity)
        monkeypatch.setattr(fsio, "_CloseHandle", tracking_close)
        if failure_phase == "sync":
            monkeypatch.setattr(parent, "_syncDirectory", maybe_fail_sync)
        with pytest.raises(OSError, match=f"create {failure_phase}"):
            parent.createDirectory("created")

        assert len(opened) == 1
        assert opened[0] in closed
        with pytest.raises(OSError):
            real_identity(opened[0])


@pytest.mark.skipif(os.name != "nt", reason="Windows retained-handle cleanup")
def test_windows_remove_directory_identity_failure_closes_child_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_path = tmp_path / "child"
    child_path.mkdir()
    with fsio.openNativeDirectory(tmp_path) as parent:
        expected = parent._entry("child").identity
        real_open = fsio._winOpenRelative
        real_identity = fsio._winIdentity
        real_close = fsio._CloseHandle
        opened: list[int] = []
        closed: list[int] = []

        def tracking_open(*args, **kwargs) -> int:
            handle = real_open(*args, **kwargs)
            opened.append(handle)
            return handle

        def fail_child_identity(handle: int) -> fsio.NativeFileIdentity:
            if handle in opened:
                raise OSError("injected remove identity failure")
            return real_identity(handle)

        def tracking_close(handle: int) -> bool:
            closed.append(int(handle))
            return bool(real_close(handle))

        monkeypatch.setattr(fsio, "_winOpenRelative", tracking_open)
        monkeypatch.setattr(fsio, "_winIdentity", fail_child_identity)
        monkeypatch.setattr(fsio, "_CloseHandle", tracking_close)
        with pytest.raises(OSError, match="remove identity"):
            parent.removeDirectory("child", expected=expected)

        assert len(opened) == 1
        assert opened[0] in closed
        with pytest.raises(OSError):
            real_identity(opened[0])


@pytest.mark.skipif(os.name == "nt", reason="POSIX retained-descriptor cleanup")
def test_posix_open_directory_identity_failure_closes_child_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "child").mkdir()
    with fsio.openNativeDirectory(tmp_path) as parent:
        real_open = fsio.os.open
        real_identity = fsio._posixIdentity
        opened: list[int] = []

        def tracking_open(path, flags: int, *args, **kwargs) -> int:
            handle = real_open(path, flags, *args, **kwargs)
            if os.fspath(path) == "child":
                opened.append(handle)
            return handle

        def fail_child_identity(handle: int) -> fsio.NativeFileIdentity:
            if handle in opened:
                raise OSError("injected child identity failure")
            return real_identity(handle)

        monkeypatch.setattr(fsio.os, "open", tracking_open)
        monkeypatch.setattr(fsio, "_posixIdentity", fail_child_identity)
        with pytest.raises(OSError, match="child identity"):
            parent.openDirectory("child")

        assert len(opened) == 1
        with pytest.raises(OSError) as raised:
            os.fstat(opened[0])
        assert raised.value.errno == errno.EBADF


@pytest.mark.skipif(os.name == "nt", reason="POSIX retained-descriptor cleanup")
def test_posix_open_native_directory_identity_failure_closes_root_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_open = fsio.os.open
    real_identity = fsio._posixIdentity
    opened: list[int] = []

    def tracking_open(path, flags: int, *args, **kwargs) -> int:
        handle = real_open(path, flags, *args, **kwargs)
        opened.append(handle)
        return handle

    def fail_root_identity(handle: int) -> fsio.NativeFileIdentity:
        if handle in opened:
            raise OSError("injected root identity failure")
        return real_identity(handle)

    monkeypatch.setattr(fsio.os, "open", tracking_open)
    monkeypatch.setattr(fsio, "_posixIdentity", fail_root_identity)
    with pytest.raises(OSError, match="root identity"):
        fsio.openNativeDirectory(tmp_path)

    assert len(opened) == 1
    with pytest.raises(OSError) as raised:
        os.fstat(opened[0])
    assert raised.value.errno == errno.EBADF


def test_native_delete_intent_binds_exact_name_and_full_identity_digests(
    tmp_path: Path,
) -> None:
    with fsio.openNativeDirectory(tmp_path) as directory:
        target = directory.createFile("target", b"target")
        guard = directory.createFile("guard", b"")

    destination = "résumé.lock"
    quarantine = fsio._nativeDeleteIntentName(
        destination,
        target,
        guard,
        "0123456789abcdef",
    )
    payload = fsio._nativeDeleteIntentPayload(
        destination_name=destination,
        quarantine_name=quarantine,
        target=target,
        guard=guard,
    )
    intent = fsio._parseNativeDeleteIntent(payload)

    assert intent.destination_name == destination
    assert intent.destination_key == hashlib.sha256(
        destination.encode("utf-8")
    ).hexdigest()
    assert intent.target_key == fsio._nativeStableIdentityKey(target)
    assert intent.guard_key == fsio._nativeStableIdentityKey(guard)
    assert len(quarantine.encode("utf-8")) <= 255

    record = json.loads(payload)
    record["destination_name"] = "another.lock"
    base = {key: value for key, value in record.items() if key != "digest"}
    canonical = json.dumps(
        base,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    record["digest"] = hashlib.sha256(canonical).hexdigest()
    rebound = json.dumps(
        record,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    with pytest.raises(OSError, match="binding differs"):
        fsio._parseNativeDeleteIntent(rebound)


def test_same_process_delete_liveness_uses_only_exact_delete_artifacts() -> None:
    artifact = ".galaxy-delete-test-artifact"
    process_start = fsio._NATIVE_PROCESS_START_TOKEN
    assert process_start is not None

    with fsio._activeNativePublication(artifact):
        assert (
            fsio._nativeDeleteOwnerAlive(
                os.getpid(),
                process_start,
                artifact,
            )
            is False
        )

    with fsio._activeNativeDeleteArtifacts(artifact):
        assert (
            fsio._nativeDeleteOwnerAlive(
                os.getpid(),
                process_start,
                artifact,
            )
            is True
        )

    assert (
        fsio._nativeDeleteOwnerAlive(
            os.getpid(),
            process_start,
            artifact,
        )
        is False
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX retained deletion boundary")
@pytest.mark.parametrize("observer", ("qualified", "unsupported"))
def test_unqualified_delete_owner_evidence_is_never_reclaimable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    observer: str,
) -> None:
    target_name = "owned.lock"
    target = tmp_path / target_name
    target.write_bytes(b"owner-a")
    issuer_pid = os.getpid() + 100_000
    real_getpid = os.getpid
    monkeypatch.setattr(fsio, "_NATIVE_PROCESS_START_TOKEN", "0" * 32)

    with fsio.openNativeDirectory(tmp_path) as directory:
        target_identity = directory._entry(target_name).identity
        monkeypatch.setattr(fsio.os, "getpid", lambda: issuer_pid)
        nonce = "0123456789abcdef"
        staging_name = fsio._nativeDeleteStagingName(
            target_name,
            target_identity,
            nonce,
        )
        (tmp_path / staging_name).write_bytes(b"")
        guard_identity = directory._entry(staging_name).identity
        quarantine_name = fsio._nativeDeleteIntentName(
            target_name,
            target_identity,
            guard_identity,
            nonce,
        )
        (tmp_path / staging_name).rename(tmp_path / quarantine_name)
        intent = fsio._nativeDeleteIntentPayload(
            destination_name=target_name,
            quarantine_name=quarantine_name,
            target=target_identity,
            guard=guard_identity,
        )
        quarantine = tmp_path / quarantine_name
        quarantine.write_bytes(intent)
        monkeypatch.setattr(fsio.os, "getpid", real_getpid)
        before = quarantine.read_bytes()

        def observe(_pid: int) -> str:
            if observer == "unsupported":
                raise OSError("process identity unavailable")
            return "a" * 32

        monkeypatch.setattr(fsio, "_nativeProcessStartToken", observe)
        with pytest.raises(
            BlockingIOError,
            match="owner is live or unverifiable",
        ):
            directory.reconcileDeleteFile(target_name)

    assert target.read_bytes() == b"owner-a"
    assert quarantine.read_bytes() == before


def test_native_target_entry_ignores_an_unrelated_disappearing_sibling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target.bin"
    sibling = tmp_path / "disappearing.bin"
    target.write_bytes(b"target")
    sibling.write_bytes(b"sibling")
    removed = False

    if os.name == "nt":
        real_list = fsio._winListDirectory

        def list_then_remove_sibling(handle: int, **kwargs):
            nonlocal removed
            entries = real_list(handle, **kwargs)
            if not removed:
                sibling.unlink()
                removed = True
            return entries

        monkeypatch.setattr(fsio, "_winListDirectory", list_then_remove_sibling)
    else:
        real_open = fsio.os.open

        def open_then_remove_sibling(path, flags, *args, **kwargs):
            nonlocal removed
            if os.fspath(path) == target.name and not removed:
                sibling.unlink()
                removed = True
            return real_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(fsio.os, "open", open_then_remove_sibling)

    with fsio.openNativeDirectory(tmp_path) as directory:
        entry = directory._entry(target.name)

    assert removed is True
    assert entry.name == target.name
    assert entry.identity.size == len(b"target")
    assert target.read_bytes() == b"target"


def test_native_directory_entry_quota_refuses_without_reopening_a_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for index in range(3):
        (tmp_path / f"entry-{index}").write_bytes(str(index).encode("ascii"))

    reopened: list[str] = []
    with fsio.openNativeDirectory(tmp_path) as directory:
        if os.name == "nt":
            real_windows_open = fsio._winOpenRelative

            def observe_windows_open(parent: int, name: str, **kwargs):
                reopened.append(name)
                return real_windows_open(parent, name, **kwargs)

            monkeypatch.setattr(fsio, "_winOpenRelative", observe_windows_open)
        else:
            real_posix_open = fsio.os.open

            def observe_posix_open(path, flags, *args, **kwargs):
                reopened.append(os.fspath(path))
                return real_posix_open(path, flags, *args, **kwargs)

            monkeypatch.setattr(fsio.os, "open", observe_posix_open)

        with pytest.raises(OSError, match="entry quota") as raised:
            directory.listEntries(max_entries=2)

    assert type(raised.value) is fsio.NativeDirectoryQuotaExceeded
    assert reopened == []


def test_native_directory_name_byte_quota_refuses_before_child_reopen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "three").write_bytes(b"payload")

    reopened: list[str] = []
    with fsio.openNativeDirectory(tmp_path) as directory:
        if os.name == "nt":
            real_windows_open = fsio._winOpenRelative

            def observe_windows_open(parent: int, name: str, **kwargs):
                reopened.append(name)
                return real_windows_open(parent, name, **kwargs)

            monkeypatch.setattr(fsio, "_winOpenRelative", observe_windows_open)
        else:
            real_posix_open = fsio.os.open

            def observe_posix_open(path, flags, *args, **kwargs):
                reopened.append(os.fspath(path))
                return real_posix_open(path, flags, *args, **kwargs)

            monkeypatch.setattr(fsio.os, "open", observe_posix_open)

        with pytest.raises(OSError, match="name byte quota") as raised:
            directory.listEntries(max_name_bytes=4)

    assert type(raised.value) is fsio.NativeDirectoryQuotaExceeded
    assert reopened == []


@pytest.mark.parametrize(
    ("limits", "error", "message"),
    [
        ({"max_entries": True}, TypeError, "max_entries must be an integer"),
        ({"max_entries": 0}, ValueError, "max_entries must be positive"),
        (
            {"max_entries": 65_537},
            ValueError,
            "max_entries may only tighten",
        ),
        ({"max_name_bytes": True}, TypeError, "max_name_bytes must be an integer"),
        ({"max_name_bytes": 0}, ValueError, "max_name_bytes must be positive"),
        (
            {"max_name_bytes": 1_025},
            ValueError,
            "max_name_bytes may only tighten",
        ),
    ],
)
def test_native_directory_limits_reject_bool_invalid_and_widening_values(
    tmp_path: Path,
    limits: dict[str, int],
    error: type[Exception],
    message: str,
) -> None:
    with fsio.openNativeDirectory(tmp_path) as directory:
        with pytest.raises(error, match=message):
            directory.listEntries(**limits)


@pytest.mark.skipif(os.name == "nt", reason="POSIX retained scandir boundary")
def test_posix_directory_enumeration_is_incremental_and_stops_at_limit_plus_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for index in range(5):
        (tmp_path / f"entry-{index}").write_bytes(b"payload")
    real_scandir = fsio.os.scandir
    yielded: list[str] = []

    class ObservedScandir:
        def __init__(self, handle: int) -> None:
            self._inner = real_scandir(handle)

        def __enter__(self):
            self._inner.__enter__()
            return self

        def __exit__(self, exc_type, exc, tb):
            return self._inner.__exit__(exc_type, exc, tb)

        def __iter__(self):
            return self

        def __next__(self):
            entry = next(self._inner)
            yielded.append(entry.name)
            if len(yielded) > 3:
                raise AssertionError("enumeration consumed beyond limit + 1")
            return entry

    with fsio.openNativeDirectory(tmp_path) as directory:
        with monkeypatch.context() as isolated:
            isolated.setattr(fsio.os, "scandir", ObservedScandir)
            isolated.setattr(
                fsio.os,
                "listdir",
                lambda _handle: (_ for _ in ()).throw(
                    AssertionError("unbounded listdir must not be used")
                ),
            )
            with pytest.raises(OSError, match="entry quota"):
                directory.listEntries(max_entries=2)

    assert len(yielded) == 3


@pytest.mark.skipif(os.name == "nt", reason="POSIX strict UTF-8 namespace")
def test_posix_directory_enumeration_rejects_non_utf8_names(
    tmp_path: Path,
) -> None:
    raw_name = os.fsencode(tmp_path) + b"/non-utf8-\xff"
    handle = os.open(raw_name, os.O_CREAT | os.O_WRONLY, 0o600)
    os.close(handle)

    with fsio.openNativeDirectory(tmp_path) as directory:
        with pytest.raises(OSError, match="strict UTF-8"):
            directory.listEntries()


@pytest.mark.skipif(os.name == "nt", reason="POSIX direct retained child lookup")
def test_posix_target_entry_does_not_materialize_sibling_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "target.bin").write_bytes(b"target")
    (tmp_path / "sibling.bin").write_bytes(b"sibling")

    with fsio.openNativeDirectory(tmp_path) as directory:
        monkeypatch.setattr(
            fsio.os,
            "listdir",
            lambda _handle: (_ for _ in ()).throw(
                AssertionError("target lookup must not materialize the directory")
            ),
        )
        entry = directory._entry("target.bin")

    assert entry.name == "target.bin"
    assert entry.identity.size == len(b"target")


@pytest.mark.skipif(os.name == "nt", reason="POSIX native component vocabulary")
def test_posix_target_entry_preserves_a_literal_backslash_component(
    tmp_path: Path,
) -> None:
    name = "literal\\backslash.bin"
    (tmp_path / name).write_bytes(b"target")

    with fsio.openNativeDirectory(tmp_path) as directory:
        entry = directory._entry(name)

    assert entry.name == name
    assert entry.identity.size == len(b"target")


_NATIVE_MUTATOR_NAME_CASES = (
    "reconcile_file",
    "create_file",
    "create_directory",
    "copy_file_source",
    "copy_file_destination",
    "copy_range_source",
    "copy_range_destination",
    "set_mode",
    "replace_file_source",
    "replace_file_destination",
    "move_source",
    "move_destination",
    "reconcile_delete",
    "remove_file",
    "remove_directory",
)


def _invokeNativeMutatorNameCase(
    operation: str,
    directory: fsio.NativeDirectoryHandle,
    name: str,
) -> object:
    if operation == "reconcile_file":
        return directory.reconcileCreateOnlyFile(name, b"payload")
    elif operation == "create_file":
        return directory.createFile(name, b"payload")
    elif operation == "create_directory":
        return directory.createDirectory(name)
    elif operation == "copy_file_source":
        return directory.copyFileTo(
            name,
            directory,
            "copy.bin",
            max_bytes=1024,
        )
    elif operation == "copy_file_destination":
        return directory.copyFileTo(
            "source.bin",
            directory,
            name,
            max_bytes=1024,
        )
    elif operation == "copy_range_source":
        return directory.copyFileRangeTo(
            name,
            directory,
            "range.bin",
            offset=0,
            length=1,
        )
    elif operation == "copy_range_destination":
        return directory.copyFileRangeTo(
            "source.bin",
            directory,
            name,
            offset=0,
            length=1,
        )
    elif operation == "set_mode":
        return directory.setFileMode(name, 0o644)
    elif operation == "replace_file_source":
        return directory.replaceFile(name, "target.bin")
    elif operation == "replace_file_destination":
        return directory.replaceFile("incoming.bin", name)
    elif operation == "move_source":
        return directory.moveChild(name, directory, "moved.bin")
    elif operation == "move_destination":
        return directory.moveChild("source.bin", directory, name)
    elif operation == "reconcile_delete":
        return directory.reconcileDeleteFile(name)
    elif operation == "remove_file":
        return directory.removeFile(name)
    elif operation == "remove_directory":
        return directory.removeDirectory(name)
    else:  # pragma: no cover - closed test vocabulary
        raise AssertionError(operation)


def _nativeMutationSurface(root: Path) -> tuple[tuple[object, ...], ...]:
    records: list[tuple[object, ...]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            records.append((relative, "directory"))
        else:
            records.append((relative, "file", path.read_bytes()))
    ads = root / "root" / "ads-host.bin:payload"
    if os.name == "nt" and ads.exists():
        records.append(("root/ads-host.bin:payload", "ads", ads.read_bytes()))
    return tuple(records)


def _prepareNativeMutatorRoot(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    root.mkdir()
    (root / "source.bin").write_bytes(b"source")
    (root / "incoming.bin").write_bytes(b"incoming")
    (root / "target.bin").write_bytes(b"target")
    (root / "ads-host.bin").write_bytes(b"ads-host")
    (root / "nested").mkdir()
    return root


@pytest.mark.parametrize("operation", _NATIVE_MUTATOR_NAME_CASES)
def test_native_public_mutators_reject_parent_traversal_before_effect(
    tmp_path: Path,
    operation: str,
) -> None:
    (tmp_path / "source.bin").write_bytes(b"source")
    (tmp_path / "incoming.bin").write_bytes(b"incoming")
    outside = tmp_path.parent / f"{tmp_path.name}-{operation}-outside"
    traversal = f"../{outside.name}"

    with fsio.openNativeDirectory(tmp_path) as directory:
        with pytest.raises(ValueError, match="child name is invalid"):
            _invokeNativeMutatorNameCase(operation, directory, traversal)

    assert not outside.exists()
    assert (tmp_path / "source.bin").read_bytes() == b"source"
    assert (tmp_path / "incoming.bin").read_bytes() == b"incoming"
    assert not list(tmp_path.glob(".galaxy-publish-*"))


@pytest.mark.parametrize("operation", _NATIVE_MUTATOR_NAME_CASES)
def test_native_public_mutators_reject_oversize_name_before_effect(
    tmp_path: Path,
    operation: str,
) -> None:
    (tmp_path / "source.bin").write_bytes(b"source")
    (tmp_path / "incoming.bin").write_bytes(b"incoming")
    oversize = "x" * 1_025

    with fsio.openNativeDirectory(tmp_path) as directory:
        with pytest.raises(
            fsio.NativeDirectoryQuotaExceeded,
            match="name byte quota",
        ):
            _invokeNativeMutatorNameCase(operation, directory, oversize)

    assert (tmp_path / "source.bin").read_bytes() == b"source"
    assert (tmp_path / "incoming.bin").read_bytes() == b"incoming"
    assert not list(tmp_path.glob(".galaxy-publish-*"))


@pytest.mark.parametrize("operation", _NATIVE_MUTATOR_NAME_CASES)
@pytest.mark.parametrize(
    "invalid_name",
    ("", ".", "..", "nested/child"),
    ids=("empty", "dot", "dotdot", "forward-slash"),
)
def test_native_public_mutator_vocabulary_refuses_before_any_effect(
    tmp_path: Path,
    operation: str,
    invalid_name: str,
) -> None:
    root = _prepareNativeMutatorRoot(tmp_path)
    before = _nativeMutationSurface(tmp_path)

    with fsio.openNativeDirectory(root) as directory:
        with pytest.raises(ValueError, match="child name is invalid"):
            _invokeNativeMutatorNameCase(operation, directory, invalid_name)

    assert _nativeMutationSurface(tmp_path) == before


@pytest.mark.skipif(os.name != "nt", reason="Windows native component vocabulary")
@pytest.mark.parametrize("operation", _NATIVE_MUTATOR_NAME_CASES)
@pytest.mark.parametrize(
    "invalid_name",
    ("nested\\child", "ads-host.bin:payload"),
    ids=("backslash", "colon-ads"),
)
def test_windows_public_mutator_vocabulary_refuses_before_any_effect(
    tmp_path: Path,
    operation: str,
    invalid_name: str,
) -> None:
    root = _prepareNativeMutatorRoot(tmp_path)
    before = _nativeMutationSurface(tmp_path)

    with fsio.openNativeDirectory(root) as directory:
        with pytest.raises(ValueError, match="child name is invalid"):
            _invokeNativeMutatorNameCase(operation, directory, invalid_name)

    assert _nativeMutationSurface(tmp_path) == before


@pytest.mark.skipif(os.name != "nt", reason="Windows native name equivalence")
def test_windows_exact_replay_is_case_insensitive_and_identity_stable(
    tmp_path: Path,
) -> None:
    payload = b"expected"
    with fsio.openNativeDirectory(tmp_path) as directory:
        winner = directory.createFile("Case.bin", payload)
        replayed = directory.reconcileCreateOnlyFile("case.bin", payload)

    assert fsio._sameNativeFileObject(replayed, winner)
    assert (tmp_path / "Case.bin").read_bytes() == payload
    assert len([path for path in tmp_path.iterdir() if path.name.lower() == "case.bin"]) == 1
    assert not list(tmp_path.glob(".galaxy-publish-*"))


@pytest.mark.skipif(os.name != "nt", reason="Windows native name equivalence")
def test_windows_case_variant_with_different_payload_refuses_untouched(
    tmp_path: Path,
) -> None:
    with fsio.openNativeDirectory(tmp_path) as directory:
        winner = directory.createFile("Case.bin", b"winner")
        with pytest.raises(FileExistsError):
            directory.reconcileCreateOnlyFile("case.bin", b"intruder")
        observed = directory._entry("CASE.BIN").identity

    assert fsio._sameNativeFileObject(observed, winner)
    assert (tmp_path / "Case.bin").read_bytes() == b"winner"
    assert not list(tmp_path.glob(".galaxy-publish-*"))


@pytest.mark.skipif(os.name != "nt", reason="Windows native name equivalence")
def test_windows_case_variants_share_publication_debris_quota(
    tmp_path: Path,
) -> None:
    payload = b"expected"
    for index in range(fsio._NATIVE_PUBLICATION_DEBRIS_MAX_SAME_DESTINATION + 1):
        variant = "Case.bin" if index % 2 else "case.bin"
        temporary = tmp_path / fsio._nativePublishTempName(variant, payload)
        temporary.write_bytes(payload)
    before = {
        path.name: path.read_bytes()
        for path in tmp_path.glob(".galaxy-publish-*")
    }

    with fsio.openNativeDirectory(tmp_path) as directory:
        with pytest.raises(
            fsio.NativeDirectoryQuotaExceeded,
            match="same-destination publication debris quota",
        ):
            directory.reconcileCreateOnlyFile("CASE.BIN", payload)

    assert not (tmp_path / "Case.bin").exists()
    assert {
        path.name: path.read_bytes()
        for path in tmp_path.glob(".galaxy-publish-*")
    } == before


@pytest.mark.skipif(os.name != "nt", reason="Windows 8.3 alias identity")
def test_windows_short_alias_lookup_returns_enumerated_long_identity(
    tmp_path: Path,
) -> None:
    long_name = "LongDestinationNameForAlias.bin"
    with fsio.openNativeDirectory(tmp_path) as directory:
        winner = directory.createFile(long_name, b"expected")
        enumerated = next(
            entry for entry in directory.listEntries() if entry.name == long_name
        )
        if not enumerated.short_name:
            pytest.skip("8.3 short-name generation is disabled on this volume")
        via_alias = directory._entry(enumerated.short_name.lower())
        alias_temporaries = [
            tmp_path / fsio._nativePublishTempName(enumerated.short_name, b"expected")
            for _ in range(fsio._NATIVE_PUBLICATION_DEBRIS_MAX_SAME_DESTINATION + 1)
        ]
        for temporary in alias_temporaries:
            temporary.write_bytes(b"expected")
        with pytest.raises(
            fsio.NativeDirectoryQuotaExceeded,
            match="same-destination publication debris quota",
        ):
            directory.reconcileCreateOnlyFile(long_name, b"expected")
        alias_temporaries[-1].unlink()
        replayed = directory.reconcileCreateOnlyFile(long_name, b"expected")

    assert via_alias.name == long_name
    assert via_alias.short_name == enumerated.short_name
    assert fsio._sameNativeFileObject(via_alias.identity, winner)
    assert fsio._sameNativeFileObject(replayed, winner)
    assert not list(tmp_path.glob(".galaxy-publish-*"))


def _preparePosixLiteralMutatorTarget(
    root: Path,
    operation: str,
    name: str,
) -> None:
    if operation in {
        "copy_file_source",
        "copy_range_source",
        "set_mode",
        "replace_file_source",
        "move_source",
        "reconcile_delete",
        "remove_file",
        "replace_file_destination",
    }:
        (root / name).write_bytes(b"candidate")
    elif operation == "remove_directory":
        (root / name).mkdir()


def _assertPosixLiteralMutatorOutcome(
    root: Path,
    operation: str,
    name: str,
) -> None:
    target = root / name
    if operation in {"reconcile_file", "create_file"}:
        assert target.read_bytes() == b"payload"
    elif operation == "create_directory":
        assert target.is_dir()
    elif operation == "copy_file_source":
        assert (root / "copy.bin").read_bytes() == b"candidate"
    elif operation == "copy_file_destination":
        assert target.read_bytes() == b"source"
    elif operation == "copy_range_source":
        assert (root / "range.bin").read_bytes() == b"c"
    elif operation == "copy_range_destination":
        assert target.read_bytes() == b"s"
    elif operation == "set_mode":
        assert target.read_bytes() == b"candidate"
        assert stat.S_IMODE(target.stat().st_mode) == 0o644
    elif operation == "replace_file_source":
        assert not target.exists()
        assert (root / "target.bin").read_bytes() == b"candidate"
    elif operation == "replace_file_destination":
        assert target.read_bytes() == b"incoming"
        assert not (root / "incoming.bin").exists()
    elif operation in {"move_source", "move_destination"}:
        return
    elif operation == "reconcile_delete":
        assert target.read_bytes() == b"candidate"
    elif operation in {"remove_file", "remove_directory"}:
        assert not target.exists()
    else:  # pragma: no cover - closed test vocabulary
        raise AssertionError(operation)


@pytest.mark.skipif(os.name == "nt", reason="POSIX native component vocabulary")
@pytest.mark.parametrize("operation", _NATIVE_MUTATOR_NAME_CASES)
@pytest.mark.parametrize(
    "literal_name",
    ("literal\\child", "literal:child"),
    ids=("backslash", "colon"),
)
def test_posix_public_mutator_vocabulary_preserves_literal_components(
    tmp_path: Path,
    operation: str,
    literal_name: str,
) -> None:
    root = _prepareNativeMutatorRoot(tmp_path)
    _preparePosixLiteralMutatorTarget(root, operation, literal_name)

    with fsio.openNativeDirectory(root) as directory:
        if operation in {"move_source", "move_destination"}:
            before = _nativeMutationSurface(tmp_path)
            with pytest.raises(OSError) as raised:
                _invokeNativeMutatorNameCase(operation, directory, literal_name)
            assert raised.value.errno == errno.ENOTSUP
            assert _nativeMutationSurface(tmp_path) == before
        else:
            result = _invokeNativeMutatorNameCase(operation, directory, literal_name)
            if operation == "create_directory":
                assert isinstance(result, fsio.NativeDirectoryHandle)
                result.close()

    _assertPosixLiteralMutatorOutcome(root, operation, literal_name)


@pytest.mark.skipif(os.name == "nt", reason="POSIX native component vocabulary")
def test_posix_create_and_remove_literal_backslash_components(
    tmp_path: Path,
) -> None:
    file_name = "literal\\file.bin"
    directory_name = "literal\\directory"

    with fsio.openNativeDirectory(tmp_path) as directory:
        created = directory.createFile(file_name, b"payload")
        child = directory.createDirectory(directory_name)
        child.close()
        assert directory.readFile(file_name, max_bytes=16) == b"payload"
        directory.removeFile(file_name, expected=created)
        directory.removeDirectory(directory_name)

    assert not (tmp_path / file_name).exists()
    assert not (tmp_path / directory_name).exists()
    assert not list(tmp_path.glob(".galaxy-*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX retained deletion inventory")
def test_posix_delete_recovery_never_uses_unbounded_listdir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with fsio.openNativeDirectory(tmp_path) as directory:
        monkeypatch.setattr(
            fsio.os,
            "listdir",
            lambda _handle: (_ for _ in ()).throw(
                AssertionError("delete recovery must enumerate incrementally")
            ),
        )
        assert directory.reconcileDeleteFile("absent.lock") == 0


def test_native_directory_stream_copy_is_bounded_and_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()
    payload = os.urandom((3 * 65536) + 137)
    (source_root / "payload.bin").write_bytes(payload)
    writes: list[int] = []

    if os.name == "nt":
        original_write = fsio._winWriteAll

        def observed_write(handle: int, chunk: bytes, *, flush: bool = True) -> None:
            writes.append(len(chunk))
            original_write(handle, chunk, flush=flush)

        monkeypatch.setattr(fsio, "_winWriteAll", observed_write)
    else:
        original_write = fsio._writeAll

        def observed_write(handle: int, chunk: bytes) -> None:
            writes.append(len(chunk))
            original_write(handle, chunk)

        monkeypatch.setattr(fsio, "_writeAll", observed_write)

    with (
        fsio.openNativeDirectory(source_root) as source,
        fsio.openNativeDirectory(destination_root) as destination,
    ):
        expected = source.listEntries()[0].identity
        hashed, source_digest, source_size = source.hashFile(
            "payload.bin",
            max_bytes=len(payload),
            expected=expected,
        )
        copied, digest, size = source.copyFileTo(
            "payload.bin",
            destination,
            "copy.bin",
            max_bytes=len(payload),
            expected=expected,
        )

    assert hashed == expected
    assert source_size == len(payload)
    assert source_digest == hashlib.sha256(payload).hexdigest()
    assert size == len(payload)
    assert copied.size == len(payload)
    assert digest == hashlib.sha256(payload).hexdigest()
    assert (destination_root / "copy.bin").read_bytes() == payload
    assert len(writes) >= 4
    assert max(writes) <= 65536


def test_native_stream_copy_removes_exact_target_when_final_sync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()
    (source_root / "payload.bin").write_bytes(b"bounded payload")
    real_sync = fsio.NativeDirectoryHandle._syncDirectory
    destination_handle = None

    def fail_destination_sync(directory) -> None:
        if directory is destination_handle:
            raise OSError("injected final directory sync failure")
        real_sync(directory)

    monkeypatch.setattr(
        fsio.NativeDirectoryHandle,
        "_syncDirectory",
        fail_destination_sync,
    )
    with (
        fsio.openNativeDirectory(source_root) as source,
        fsio.openNativeDirectory(destination_root) as destination,
    ):
        destination_handle = destination
        with pytest.raises(OSError, match="injected final directory sync failure"):
            source.copyFileTo(
                "payload.bin",
                destination,
                "copy.bin",
                max_bytes=1024,
            )

    if os.name == "nt":
        assert not (destination_root / "copy.bin").exists()
    else:
        # Once publication has completed, a directory-sync refusal also blocks
        # the replayable exact-delete protocol. Preserve the exact bytes as
        # non-authoritative evidence instead of falling back to a racy unlink.
        assert (destination_root / "copy.bin").read_bytes() == b"bounded payload"
        assert not list(destination_root.glob(".galaxy-publish-*"))


@pytest.mark.parametrize("range_copy", [False, True], ids=("full", "range"))
@pytest.mark.skipif(os.name == "nt", reason="POSIX exact failure cleanup")
def test_posix_failed_copy_cleanup_preserves_a_rebound_successor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    range_copy: bool,
) -> None:
    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()
    payload = b"source-payload"
    (source_root / "payload.bin").write_bytes(payload)
    target_handle: int | None = None
    failed = False
    rebound = False
    real_write = fsio._writeAll
    real_close = fsio.os.close

    def fail_first_target_write(handle: int, chunk: bytes) -> None:
        nonlocal failed, target_handle
        if not failed:
            failed = True
            target_handle = handle
            real_write(handle, chunk[:1])
            raise OSError("injected copy failure")
        real_write(handle, chunk)

    def close_then_rebind(handle: int) -> None:
        nonlocal rebound
        real_close(handle)
        if handle == target_handle and not rebound:
            rebound = True
            os.replace(
                destination_root / "copy.bin",
                destination_root / "preserved-a.bin",
            )
            (destination_root / "copy.bin").write_bytes(b"owner-b")

    monkeypatch.setattr(fsio, "_writeAll", fail_first_target_write)
    monkeypatch.setattr(fsio.os, "close", close_then_rebind)
    with (
        fsio.openNativeDirectory(source_root) as source,
        fsio.openNativeDirectory(destination_root) as destination,
    ):
        with pytest.raises(OSError, match="injected copy failure"):
            if range_copy:
                source.copyFileRangeTo(
                    "payload.bin",
                    destination,
                    "copy.bin",
                    offset=0,
                    length=len(payload),
                )
            else:
                source.copyFileTo(
                    "payload.bin",
                    destination,
                    "copy.bin",
                    max_bytes=len(payload),
                )

    assert failed is True
    assert rebound is True
    assert (destination_root / "preserved-a.bin").read_bytes() == payload[:1]
    assert (destination_root / "copy.bin").read_bytes() == b"owner-b"


@pytest.mark.skipif(os.name == "nt", reason="POSIX replayable copy cleanup")
def test_posix_failed_copy_cleanup_hard_death_replays_exact_target(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()
    (source_root / "payload.bin").write_bytes(b"source-payload")
    script = r"""
import os
import sys
from pathlib import Path
from platform_core.core import fsio

source_root = Path(sys.argv[1])
destination_root = Path(sys.argv[2])
real_write = fsio._writeAll
failed = False

def fail_copy_once(handle, payload):
    global failed
    if not failed:
        failed = True
        real_write(handle, payload[:1])
        raise OSError("injected copy failure")
    real_write(handle, payload)

def die_during_cleanup(phase):
    if phase == "first-exchange":
        os._exit(95)

fsio._writeAll = fail_copy_once
fsio._nativeDeletionCrashPoint = die_during_cleanup
with (
    fsio.openNativeDirectory(source_root) as source,
    fsio.openNativeDirectory(destination_root) as destination,
):
    source.copyFileTo(
        "payload.bin",
        destination,
        "copy.bin",
        max_bytes=1024,
    )
"""

    result = subprocess.run(
        [sys.executable, "-c", script, str(source_root), str(destination_root)],
        cwd=_ROOT,
        check=False,
        timeout=30,
    )

    assert result.returncode == 95
    with fsio.openNativeDirectory(destination_root) as destination:
        assert destination.reconcileDeleteFile("copy.bin") >= 1
    assert not (destination_root / "copy.bin").exists()
    assert not list(destination_root.glob(".galaxy-delete-*"))


def test_native_stream_range_copy_retains_identity_and_copies_only_requested_bytes(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()
    payload = bytes(range(256)) * 1024
    (source_root / "pack.bin").write_bytes(payload)

    with (
        fsio.openNativeDirectory(source_root) as source,
        fsio.openNativeDirectory(destination_root) as destination,
    ):
        expected = source.listEntries()[0].identity
        copied, digest, size = source.copyFileRangeTo(
            "pack.bin",
            destination,
            "range.bin",
            offset=65521,
            length=70003,
            expected=expected,
        )

    selected = payload[65521 : 65521 + 70003]
    assert size == len(selected)
    assert copied.size == len(selected)
    assert digest == hashlib.sha256(selected).hexdigest()
    assert (destination_root / "range.bin").read_bytes() == selected

@pytest.mark.timeout(120)
def test_atomic_write_concurrent_threads_and_processes_never_torn(tmp_path):
    target = tmp_path / "shared.json"
    errors: list[Exception] = []
    torn: list[str] = []
    stop = threading.Event()
    payloads = {f"t{i}": json.dumps({"writer": f"t{i}", "pad": "x" * 4000}) for i in range(8)}
    payloads.update({f"p{i}": json.dumps({"writer": f"p{i}", "pad": "y" * 4000}) for i in range(2)})

    def writer(wid: str) -> None:
        try:
            for _ in range(25):
                fsio.atomicWriteText(target, payloads[wid])
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    def reader() -> None:
        valid = set(payloads.values())
        while not stop.is_set():
            try:
                t = target.read_text(encoding="utf-8")
            except (FileNotFoundError, PermissionError):
                continue
            if t and t not in valid:
                torn.append(t[:60])
            time.sleep(0.0005)

    # 2 real child processes hammering the SAME destination through the same kernel.
    code = (
        "import sys; sys.path.insert(0, sys.argv[1])\n"
        "from platform_core.core import fsio\n"
        "for _ in range(25):\n"
        "    fsio.atomicWriteText(sys.argv[2], sys.argv[3])\n"
    )
    procs = [subprocess.Popen([sys.executable, "-c", code, str(_ROOT), str(target),
                               payloads[f"p{i}"]]) for i in range(2)]
    try:
        threads = [threading.Thread(target=writer, args=(f"t{i}",)) for i in range(8)]
        readers = [threading.Thread(target=reader) for _ in range(2)]
        for r in readers:
            r.start()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        rcs = [p.wait(timeout=20) for p in procs]
    finally:
        stop.set()
        for p in procs:
            if p.poll() is None:
                p.kill()
                p.wait(timeout=5)
    for r in readers:
        r.join(timeout=10)

    assert errors == [], f"concurrent atomic writes raised: {errors[:2]}"
    assert rcs == [0, 0], "a child-process writer crashed (FileNotFoundError race?)"
    assert torn == [], f"observed torn read(s): {torn[:1]}"
    assert json.loads(target.read_text(encoding="utf-8"))["writer"] in payloads
    assert list(tmp_path.glob("*.tmp")) == [], "left temp files behind"


def test_atomic_write_json_and_load_json_roundtrip(tmp_path):
    p = tmp_path / "sub" / "data.json"          # parent dir auto-created
    fsio.atomicWriteJson(p, {"a": 1, "b": [1, 2]})
    assert fsio.loadJson(p) == {"a": 1, "b": [1, 2]}


def test_exclusive_create_bytes_never_replaces_existing_owner(tmp_path):
    path = tmp_path / "immutable.bin"
    fsio.exclusiveCreateBytes(path, b"owner-one")
    with pytest.raises(FileExistsError):
        fsio.exclusiveCreateBytes(path, b"owner-one")
    with pytest.raises(FileExistsError):
        fsio.exclusiveCreateBytes(path, b"owner-two")
    assert path.read_bytes() == b"owner-one"


def test_native_publish_temp_name_binds_destination_payload_and_size() -> None:
    first = fsio._nativePublishTempName("immutable.bin", b"payload-one")
    second = fsio._nativePublishTempName("immutable.bin", b"payload-two")

    first_match = fsio._NATIVE_PUBLISH_TEMP_RE.fullmatch(first)
    second_match = fsio._NATIVE_PUBLISH_TEMP_RE.fullmatch(second)

    assert first_match is not None
    assert second_match is not None
    assert first_match.group("destination") == hashlib.sha256(
        b"immutable.bin"
    ).hexdigest()[:32]
    assert first_match.group("payload") == hashlib.sha256(b"payload-one").hexdigest()
    assert first_match.group("size") == f"{len(b'payload-one'):016x}"
    assert second_match.group("payload") == hashlib.sha256(b"payload-two").hexdigest()
    assert first_match.group("payload") != second_match.group("payload")


def test_native_create_only_debris_inspection_is_retained_and_non_mutating(
    tmp_path: Path,
) -> None:
    payload = b"complete-payload"
    temporary_name = fsio._nativePublishTempName("immutable.bin", payload)
    temporary = tmp_path / temporary_name
    temporary.write_bytes(payload[:7])

    with fsio.openNativeDirectory(tmp_path) as directory:
        entries_before = directory.listEntries()
        entry = next(item for item in entries_before if item.name == temporary_name)
        debris = directory.inspectCreateOnlyDebris(entry, max_bytes=1024)

        assert debris is not None
        assert debris.entry == entry
        assert debris.destination_key == hashlib.sha256(b"immutable.bin").hexdigest()[:32]
        assert debris.payload_digest == hashlib.sha256(payload).hexdigest()
        assert debris.payload_size == len(payload)
        assert debris.owner_pid == os.getpid()
        assert debris.owner_start == fsio._NATIVE_PROCESS_START_TOKEN
        assert debris.owner_alive is False
        assert debris.observed == payload[:7]
        assert directory.listEntries() == entries_before

    assert temporary.read_bytes() == payload[:7]


@pytest.mark.parametrize("observer", ("qualified", "unsupported"))
def test_unqualified_publication_owner_is_never_reclaimable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    observer: str,
) -> None:
    payload = b"complete-payload"
    issuer_pid = os.getpid() + 100_000
    real_getpid = os.getpid
    monkeypatch.setattr(fsio, "_NATIVE_PROCESS_START_TOKEN", "0" * 32)
    monkeypatch.setattr(fsio.os, "getpid", lambda: issuer_pid)
    temporary_name = fsio._nativePublishTempName("immutable.bin", payload)
    monkeypatch.setattr(fsio.os, "getpid", real_getpid)
    temporary = tmp_path / temporary_name
    temporary.write_bytes(payload[:7])
    before = temporary.read_bytes()

    def observe(_pid: int) -> str:
        if observer == "unsupported":
            raise OSError("process identity unavailable")
        return "a" * 32

    monkeypatch.setattr(fsio, "_nativeProcessStartToken", observe)
    with fsio.openNativeDirectory(tmp_path) as directory:
        with pytest.raises(OSError, match="debris differs from expected payload"):
            directory.reconcileCreateOnlyFile("immutable.bin", payload)

    assert temporary.read_bytes() == before
    assert not (tmp_path / "immutable.bin").exists()


@pytest.mark.skipif(not hasattr(os, "fork"), reason="POSIX fork identity boundary")
def test_forked_publication_owner_refreshes_birth_identity_until_child_death(
    tmp_path: Path,
) -> None:
    import select
    import warnings

    payload = b"complete-payload"
    parent_token = fsio._currentNativeProcessStartToken()
    ready_read, ready_write = os.pipe()
    release_read, release_write = os.pipe()
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="This process .* is multi-threaded, use of fork\\(\\) may lead to deadlocks in the child",
            category=DeprecationWarning,
        )
        child_pid = os.fork()  # type: ignore[attr-defined]
    if child_pid == 0:  # pragma: no branch - child has its own process result
        try:
            os.close(ready_read)
            os.close(release_write)
            temporary_name = fsio._nativePublishTempName("immutable.bin", payload)
            with fsio._activeNativePublication(temporary_name):
                (tmp_path / temporary_name).write_bytes(payload)
                os.write(ready_write, b"1")
                os.read(release_read, 1)
        finally:
            os._exit(0)

    os.close(ready_write)
    os.close(release_read)
    try:
        readable, _, _ = select.select([ready_read], [], [], 5.0)
        assert readable == [ready_read]
        assert os.read(ready_read, 1) == b"1"
        with fsio.openNativeDirectory(tmp_path) as directory:
            temporary = next(
                entry
                for entry in directory.listEntries()
                if entry.name.startswith(".galaxy-publish-")
            )
            debris = directory.inspectCreateOnlyDebris(
                temporary,
                max_bytes=len(payload),
            )
            assert debris is not None
            assert debris.owner_pid == child_pid
            assert debris.owner_start != parent_token
            assert debris.owner_alive is True

        observer = r"""
import sys
from pathlib import Path
from platform_core.core import fsio

try:
    with fsio.openNativeDirectory(Path(sys.argv[1])) as directory:
        directory.reconcileCreateOnlyFile("immutable.bin", b"complete-payload")
except OSError:
    raise SystemExit(0)
raise SystemExit(71)
"""
        third = subprocess.run(
            [sys.executable, "-c", observer, str(tmp_path)],
            cwd=_ROOT,
            check=False,
            timeout=10,
        )
        assert third.returncode == 0
        assert not (tmp_path / "immutable.bin").exists()
        assert temporary.name in {path.name for path in tmp_path.iterdir()}
    finally:
        try:
            os.write(release_write, b"1")
        except OSError:
            pass
        os.close(release_write)
        os.close(ready_read)
        os.waitpid(child_pid, 0)

    with fsio.openNativeDirectory(tmp_path) as directory:
        recovered = directory.reconcileCreateOnlyFile("immutable.bin", payload)
    assert recovered.size == len(payload)
    assert (tmp_path / "immutable.bin").read_bytes() == payload
    assert not list(tmp_path.glob(".galaxy-publish-*"))


def test_native_debris_inspection_rejects_complete_content_digest_mismatch(
    tmp_path: Path,
) -> None:
    payload = b"complete-payload"
    temporary = tmp_path / fsio._nativePublishTempName("immutable.bin", payload)
    temporary.write_bytes(b"x" * len(payload))

    with fsio.openNativeDirectory(tmp_path) as directory:
        entry = directory._entry(temporary.name)
        with pytest.raises(OSError, match="complete payload digest differs"):
            directory.inspectCreateOnlyDebris(entry, max_bytes=1024)

    assert temporary.read_bytes() == b"x" * len(payload)


def test_native_reconcile_replaces_exact_payload_bound_partial_prefix(
    tmp_path: Path,
) -> None:
    payload = b"complete-payload"
    temporary = tmp_path / fsio._nativePublishTempName("immutable.bin", payload)
    temporary.write_bytes(payload[:7])

    with fsio.openNativeDirectory(tmp_path) as directory:
        published = directory.reconcileCreateOnlyFile("immutable.bin", payload)
        observed = directory._entry("immutable.bin").identity

    assert published == observed
    assert (tmp_path / "immutable.bin").read_bytes() == payload
    assert not temporary.exists()


def test_native_reconcile_republishes_exact_payload_bound_full_temporary(
    tmp_path: Path,
) -> None:
    payload = b"complete-payload"
    temporary = tmp_path / fsio._nativePublishTempName("immutable.bin", payload)
    temporary.write_bytes(payload)

    with fsio.openNativeDirectory(tmp_path) as directory:
        temporary_identity = directory._entry(temporary.name).identity
        published = directory.reconcileCreateOnlyFile("immutable.bin", payload)

    assert not fsio._sameNativeFileObject(published, temporary_identity)
    assert (tmp_path / "immutable.bin").read_bytes() == payload
    assert not temporary.exists()


def test_native_reconcile_replays_fresh_publish_before_old_debris_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"complete-payload"
    temporary = tmp_path / fsio._nativePublishTempName("immutable.bin", payload)
    temporary.write_bytes(payload)
    real_remove = fsio.NativeDirectoryHandle.removeFile
    cleanup_response_lost = False

    def lose_first_cleanup_response(
        directory: fsio.NativeDirectoryHandle,
        name: str,
        *,
        expected: fsio.NativeFileIdentity | None = None,
    ) -> None:
        nonlocal cleanup_response_lost
        if name == temporary.name and not cleanup_response_lost:
            cleanup_response_lost = True
            raise OSError("simulated cleanup response loss")
        real_remove(directory, name, expected=expected)

    with fsio.openNativeDirectory(tmp_path) as directory:
        with monkeypatch.context() as isolated:
            isolated.setattr(
                fsio.NativeDirectoryHandle,
                "removeFile",
                lose_first_cleanup_response,
            )
            with pytest.raises(OSError, match="cleanup response loss"):
                directory.reconcileCreateOnlyFile("immutable.bin", payload)

        final_before_retry = directory._entry("immutable.bin").identity
        assert temporary.read_bytes() == payload
        replayed = directory.reconcileCreateOnlyFile("immutable.bin", payload)

    assert cleanup_response_lost is True
    assert fsio._sameNativeFileObject(replayed, final_before_retry)
    assert (tmp_path / "immutable.bin").read_bytes() == payload
    assert not temporary.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX exact publication cleanup")
def test_posix_failed_publication_cleanup_preserves_a_rebound_temporary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"complete-payload"
    temporary_name = fsio._nativePublishTempName("immutable.bin", payload)
    preserved = tmp_path / "preserved-a.bin"
    target_handle: int | None = None
    rebound = False
    real_open = fsio.os.open
    real_close = fsio.os.close

    def observe_open(path, flags, *args, **kwargs):
        nonlocal target_handle
        handle = real_open(path, flags, *args, **kwargs)
        if os.fspath(path) == temporary_name:
            target_handle = handle
        return handle

    def close_then_rebind(handle: int) -> None:
        nonlocal rebound
        real_close(handle)
        if handle == target_handle and not rebound:
            rebound = True
            os.replace(tmp_path / temporary_name, preserved)
            (tmp_path / temporary_name).write_bytes(b"owner-b")

    def fail_publication(*_args, **_kwargs) -> None:
        raise OSError("injected publication failure")

    with fsio.openNativeDirectory(tmp_path) as directory:
        monkeypatch.setattr(fsio.os, "open", observe_open)
        monkeypatch.setattr(fsio.os, "close", close_then_rebind)
        monkeypatch.setattr(fsio, "_posixRenameNoReplace", fail_publication)
        with pytest.raises(OSError, match="injected publication failure"):
            directory._publishNewFile(
                "immutable.bin",
                payload,
                temporary_name,
            )

    assert rebound is True
    assert preserved.read_bytes() == payload
    assert (tmp_path / temporary_name).read_bytes() == b"owner-b"
    assert not (tmp_path / "immutable.bin").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX replayable publication cleanup")
def test_posix_failed_publication_cleanup_hard_death_replays_exact_temporary(
    tmp_path: Path,
) -> None:
    script = r"""
import os
import sys
from pathlib import Path
from platform_core.core import fsio

root = Path(sys.argv[1])
payload = b"complete-payload"
temporary_name = fsio._nativePublishTempName("immutable.bin", payload)
real_rename = fsio._posixRenameNoReplace

def fail_final_publication(
    source_directory,
    source_name,
    destination_directory,
    destination_name,
):
    if destination_name == "immutable.bin":
        raise OSError("injected publication failure")
    return real_rename(
        source_directory,
        source_name,
        destination_directory,
        destination_name,
    )

def die_during_cleanup(phase):
    if phase == "first-exchange":
        os._exit(96)

fsio._posixRenameNoReplace = fail_final_publication
fsio._nativeDeletionCrashPoint = die_during_cleanup
with fsio.openNativeDirectory(root) as directory:
    directory._publishNewFile("immutable.bin", payload, temporary_name)
"""

    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=_ROOT,
        check=False,
        timeout=30,
    )

    assert result.returncode == 96
    temporaries = list(tmp_path.glob(".galaxy-publish-*"))
    assert len(temporaries) == 1
    with fsio.openNativeDirectory(tmp_path) as directory:
        assert directory.reconcileDeleteFile(temporaries[0].name) >= 1
    assert not (tmp_path / "immutable.bin").exists()
    assert not list(tmp_path.glob(".galaxy-publish-*"))
    assert not list(tmp_path.glob(".galaxy-delete-*"))


@pytest.mark.skipif(os.name != "nt", reason="Windows retained publication ordering")
def test_windows_native_publication_flushes_temp_before_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, bool]] = []
    temporary_handle: int | None = None
    real_write = fsio._winWriteAll
    real_flush = fsio._FlushFileBuffers
    real_rename = fsio._winRenameRelative

    def observed_write(handle: int, payload: bytes, *, flush: bool = True) -> None:
        nonlocal temporary_handle
        temporary_handle = handle
        events.append(("write", flush))
        real_write(handle, payload, flush=flush)

    def observed_flush(handle: int) -> int:
        events.append(("flush", handle == temporary_handle))
        return real_flush(handle)

    def observed_rename(
        source: int,
        destination_directory: int,
        destination_name: str,
        *,
        replace: bool,
    ) -> None:
        events.append(("rename", source == temporary_handle))
        real_rename(
            source,
            destination_directory,
            destination_name,
            replace=replace,
        )

    monkeypatch.setattr(fsio, "_winWriteAll", observed_write)
    monkeypatch.setattr(fsio, "_FlushFileBuffers", observed_flush)
    monkeypatch.setattr(fsio, "_winRenameRelative", observed_rename)

    with fsio.openNativeDirectory(tmp_path) as directory:
        directory.createFile("immutable.bin", b"complete-payload")

    assert events == [
        ("write", False),
        ("flush", True),
        ("rename", True),
    ]


def test_native_reconcile_exact_final_is_idempotent_without_rewrite(
    tmp_path: Path,
) -> None:
    payload = b"complete-payload"

    with fsio.openNativeDirectory(tmp_path) as directory:
        original = directory.createFile("immutable.bin", payload)
        replayed = directory.reconcileCreateOnlyFile("immutable.bin", payload)
        observed = directory._entry("immutable.bin").identity

    assert fsio._sameNativeFileObject(replayed, original)
    assert observed == replayed
    assert (tmp_path / "immutable.bin").read_bytes() == payload


@pytest.mark.parametrize("observed_size", [0, 7, len(b"complete-payload")])
def test_native_reconcile_exact_final_cleans_only_matching_dead_prefix_debris(
    tmp_path: Path,
    observed_size: int,
) -> None:
    payload = b"complete-payload"

    with fsio.openNativeDirectory(tmp_path) as directory:
        original = directory.createFile("immutable.bin", payload)
    temporary = tmp_path / fsio._nativePublishTempName("immutable.bin", payload)
    temporary.write_bytes(payload[:observed_size])

    with fsio.openNativeDirectory(tmp_path) as directory:
        replayed = directory.reconcileCreateOnlyFile("immutable.bin", payload)

    assert fsio._sameNativeFileObject(replayed, original)
    assert (tmp_path / "immutable.bin").read_bytes() == payload
    assert not temporary.exists()


def test_native_reconcile_exact_final_cleans_multiple_matching_dead_prefixes(
    tmp_path: Path,
) -> None:
    payload = b"complete-payload"

    with fsio.openNativeDirectory(tmp_path) as directory:
        original = directory.createFile("immutable.bin", payload)
    temporaries = tuple(
        tmp_path / fsio._nativePublishTempName("immutable.bin", payload)
        for _ in range(3)
    )
    for temporary, size in zip(temporaries, (0, 7, len(payload)), strict=True):
        temporary.write_bytes(payload[:size])

    with fsio.openNativeDirectory(tmp_path) as directory:
        replayed = directory.reconcileCreateOnlyFile("immutable.bin", payload)

    assert fsio._sameNativeFileObject(replayed, original)
    assert (tmp_path / "immutable.bin").read_bytes() == payload
    assert not any(temporary.exists() for temporary in temporaries)


def test_native_reconcile_refuses_malformed_publisher_artifact_without_cleanup(
    tmp_path: Path,
) -> None:
    malformed = tmp_path / ".galaxy-publish-not-authentic.tmp"
    malformed.write_bytes(b"do-not-delete")

    with fsio.openNativeDirectory(tmp_path) as directory:
        with pytest.raises(OSError, match="publisher artifact is malformed"):
            directory.reconcileCreateOnlyFile("immutable.bin", b"complete-payload")

    assert malformed.read_bytes() == b"do-not-delete"
    assert not (tmp_path / "immutable.bin").exists()


def test_native_reconcile_ignores_different_destination_debris_without_cleanup(
    tmp_path: Path,
) -> None:
    other_payload = b"x" * 128
    other = tmp_path / fsio._nativePublishTempName("other.bin", other_payload)
    other.write_bytes(other_payload[:31])

    with fsio.openNativeDirectory(tmp_path) as directory:
        directory.reconcileCreateOnlyFile("immutable.bin", b"small")

    assert (tmp_path / "immutable.bin").read_bytes() == b"small"
    assert other.read_bytes() == other_payload[:31]


def test_native_reconcile_refuses_total_valid_publication_debris_flood_untouched(
    tmp_path: Path,
) -> None:
    for index in range(65):
        payload = f"payload-{index}".encode("ascii")
        temporary = tmp_path / fsio._nativePublishTempName(
            f"other-{index}.bin",
            payload,
        )
        temporary.write_bytes(payload)
    before = {
        path.name: path.read_bytes()
        for path in tmp_path.glob(".galaxy-publish-*")
    }

    with fsio.openNativeDirectory(tmp_path) as directory:
        with pytest.raises(OSError, match="publication debris total quota") as raised:
            directory.reconcileCreateOnlyFile("immutable.bin", b"expected")

    assert type(raised.value) is fsio.NativeDirectoryQuotaExceeded
    assert not (tmp_path / "immutable.bin").exists()
    assert {
        path.name: path.read_bytes()
        for path in tmp_path.glob(".galaxy-publish-*")
    } == before


def test_native_reconcile_reserves_total_debris_capacity_before_fresh_publish(
    tmp_path: Path,
) -> None:
    for index in range(fsio._NATIVE_PUBLICATION_DEBRIS_MAX_TOTAL):
        payload = f"payload-{index}".encode("ascii")
        temporary = tmp_path / fsio._nativePublishTempName(
            f"other-{index}.bin",
            payload,
        )
        temporary.write_bytes(payload)
    before = {
        path.name: path.read_bytes()
        for path in tmp_path.glob(".galaxy-publish-*")
    }

    with fsio.openNativeDirectory(tmp_path) as directory:
        with pytest.raises(
            fsio.NativeDirectoryQuotaExceeded,
            match="publication debris total quota",
        ):
            directory.reconcileCreateOnlyFile("immutable.bin", b"expected")

    assert not (tmp_path / "immutable.bin").exists()
    assert {
        path.name: path.read_bytes()
        for path in tmp_path.glob(".galaxy-publish-*")
    } == before


def test_native_reconcile_refuses_same_destination_debris_flood_untouched(
    tmp_path: Path,
) -> None:
    payload = b"expected"
    for _ in range(17):
        temporary = tmp_path / fsio._nativePublishTempName("immutable.bin", payload)
        temporary.write_bytes(payload)
    before = {
        path.name: path.read_bytes()
        for path in tmp_path.glob(".galaxy-publish-*")
    }

    with fsio.openNativeDirectory(tmp_path) as directory:
        with pytest.raises(
            OSError,
            match="same-destination publication debris quota",
        ) as raised:
            directory.reconcileCreateOnlyFile("immutable.bin", payload)

    assert type(raised.value) is fsio.NativeDirectoryQuotaExceeded
    assert not (tmp_path / "immutable.bin").exists()
    assert {
        path.name: path.read_bytes()
        for path in tmp_path.glob(".galaxy-publish-*")
    } == before


def test_native_reconcile_reserves_same_destination_capacity_before_publish(
    tmp_path: Path,
) -> None:
    payload = b"expected"
    for _ in range(fsio._NATIVE_PUBLICATION_DEBRIS_MAX_SAME_DESTINATION):
        temporary = tmp_path / fsio._nativePublishTempName("immutable.bin", payload)
        temporary.write_bytes(payload)
    before = {
        path.name: path.read_bytes()
        for path in tmp_path.glob(".galaxy-publish-*")
    }

    with fsio.openNativeDirectory(tmp_path) as directory:
        with pytest.raises(
            fsio.NativeDirectoryQuotaExceeded,
            match="same-destination publication debris quota",
        ):
            directory.reconcileCreateOnlyFile("immutable.bin", payload)

    assert not (tmp_path / "immutable.bin").exists()
    assert {
        path.name: path.read_bytes()
        for path in tmp_path.glob(".galaxy-publish-*")
    } == before


def test_native_publication_directory_capacity_uses_production_inventory_bound() -> None:
    assert fsio._NATIVE_PUBLICATION_DIRECTORY_MAX_ENTRIES == 65_536
    assert (
        fsio._NATIVE_PUBLICATION_DIRECTORY_MAX_ENTRIES
        == fsio._NATIVE_DIRECTORY_MAX_ENTRIES
    )


def test_native_publication_refuses_full_directory_inventory_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fsio, "_NATIVE_PUBLICATION_DIRECTORY_MAX_ENTRIES", 4)
    root = tmp_path / "root"
    root.mkdir()
    for index in range(4):
        (root / f"ordinary-{index}.bin").write_bytes(str(index).encode("ascii"))
    before = {
        path.name: path.read_bytes()
        for path in root.iterdir()
    }

    with fsio.openNativeDirectory(root) as directory:
        with pytest.raises(
            fsio.NativeDirectoryQuotaExceeded,
            match="directory.*capacity",
        ):
            directory.reconcileCreateOnlyFile("immutable.bin", b"expected")

    assert not (root / "immutable.bin").exists()
    assert {
        path.name: path.read_bytes()
        for path in root.iterdir()
    } == before


def test_native_publication_refuses_partial_at_directory_ceiling_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fsio, "_NATIVE_PUBLICATION_DIRECTORY_MAX_ENTRIES", 4)
    root = tmp_path / "root"
    root.mkdir()
    for index in range(3):
        (root / f"ordinary-{index}.bin").write_bytes(str(index).encode("ascii"))
    payload = b"expected"
    partial = root / fsio._nativePublishTempName("immutable.bin", payload)
    partial.write_bytes(payload[:3])

    before = {path.name: path.read_bytes() for path in root.iterdir()}
    with fsio.openNativeDirectory(root) as directory:
        with pytest.raises(
            fsio.NativeDirectoryQuotaExceeded,
            match="directory.*capacity",
        ):
            directory.reconcileCreateOnlyFile("immutable.bin", payload)

    assert not (root / "immutable.bin").exists()
    assert partial.read_bytes() == payload[:3]
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before
    assert len(list(root.iterdir())) == 4


def test_native_publication_promotes_complete_retained_temp_at_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fsio, "_NATIVE_PUBLICATION_DIRECTORY_MAX_ENTRIES", 4)
    root = tmp_path / "root"
    root.mkdir()
    for index in range(3):
        (root / f"ordinary-{index}.bin").write_bytes(str(index).encode("ascii"))
    payload = b"expected"
    temporary = root / fsio._nativePublishTempName("immutable.bin", payload)
    temporary.write_bytes(payload)

    with fsio.openNativeDirectory(root) as directory:
        retained = directory._entry(temporary.name).identity
        published = directory.reconcileCreateOnlyFile("immutable.bin", payload)
        replayed = directory.reconcileCreateOnlyFile("immutable.bin", payload)

    assert fsio._sameNativeFileObject(published, retained)
    assert fsio._sameNativeFileObject(replayed, retained)
    assert (root / "immutable.bin").read_bytes() == payload
    assert not temporary.exists()
    assert not list(root.glob(".galaxy-publish-*"))
    assert len(list(root.iterdir())) == 4


def test_native_publication_max_minus_one_crash_is_recoverable_at_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    for index in range(3):
        (root / f"ordinary-{index}.bin").write_bytes(str(index).encode("ascii"))
    child = r"""
import os
import sys
from pathlib import Path
from platform_core.core import fsio

root = Path(sys.argv[1])
payload = b"expected"
fsio._NATIVE_PUBLICATION_DIRECTORY_MAX_ENTRIES = 4
def crash_before_publish(*_args, **_kwargs):
    os._exit(91)
if os.name == "nt":
    fsio._winRenameRelative = crash_before_publish
else:
    fsio._posixRenameNoReplace = crash_before_publish
with fsio.openNativeDirectory(root) as directory:
    temporary = fsio._nativePublishTempName("immutable.bin", payload)
    directory._publishNewFile("immutable.bin", payload, temporary)
raise SystemExit(92)
"""
    result = subprocess.run(
        [sys.executable, "-c", child, str(root)],
        cwd=_ROOT,
        check=False,
        timeout=30,
    )
    assert result.returncode == 91
    debris = list(root.glob(".galaxy-publish-*"))
    assert len(debris) == 1
    assert len(list(root.iterdir())) == 4

    monkeypatch.setattr(fsio, "_NATIVE_PUBLICATION_DIRECTORY_MAX_ENTRIES", 4)
    with fsio.openNativeDirectory(root) as directory:
        retained = directory._entry(debris[0].name).identity
        recovered = directory.reconcileCreateOnlyFile("immutable.bin", b"expected")

    assert fsio._sameNativeFileObject(recovered, retained)
    assert (root / "immutable.bin").read_bytes() == b"expected"
    assert not list(root.glob(".galaxy-publish-*"))
    assert len(list(root.iterdir())) == 4


@pytest.mark.parametrize("scope", ("total", "same-destination"))
def test_native_publication_capacity_admission_is_cross_process_atomic(
    tmp_path: Path,
    scope: str,
) -> None:
    payload = b"expected"
    if scope == "total":
        for index in range(fsio._NATIVE_PUBLICATION_DEBRIS_MAX_TOTAL - 1):
            seeded_payload = f"payload-{index}".encode("ascii")
            temporary = tmp_path / fsio._nativePublishTempName(
                f"other-{index}.bin",
                seeded_payload,
            )
            temporary.write_bytes(seeded_payload)
        destinations = ("fresh-a.bin", "fresh-b.bin")
        expected_count = fsio._NATIVE_PUBLICATION_DEBRIS_MAX_TOTAL
    else:
        for _ in range(fsio._NATIVE_PUBLICATION_DEBRIS_MAX_SAME_DESTINATION - 1):
            temporary = tmp_path / fsio._nativePublishTempName(
                "immutable.bin",
                payload,
            )
            temporary.write_bytes(payload)
        destinations = ("immutable.bin", "immutable.bin")
        expected_count = fsio._NATIVE_PUBLICATION_DEBRIS_MAX_SAME_DESTINATION

    barrier = tmp_path / "barrier"
    barrier.mkdir()
    child = r"""
import os
import sys
import time
from pathlib import Path
from platform_core.core import fsio

root = Path(sys.argv[1])
barrier = Path(sys.argv[2])
destination = sys.argv[3]
payload = b"expected"
(barrier / f"{os.getpid()}.ready").write_text("ready", encoding="ascii")
deadline = time.monotonic() + 20.0
while not (barrier / "go").exists():
    if time.monotonic() >= deadline:
        raise SystemExit(72)
    time.sleep(0.005)

def crash_after_temp(*_args, **_kwargs):
    os._exit(91)

if os.name == "nt":
    fsio._winRenameRelative = crash_after_temp
else:
    fsio._posixRenameNoReplace = crash_after_temp

try:
    with fsio.openNativeDirectory(root) as directory:
        temporary_name = fsio._nativePublishTempName(destination, payload)
        directory._publishNewFile(destination, payload, temporary_name)
except fsio.NativeDirectoryQuotaExceeded:
    raise SystemExit(73)
raise SystemExit(74)
"""
    children = [
        subprocess.Popen(
            [sys.executable, "-c", child, str(tmp_path), str(barrier), destination],
            cwd=_ROOT,
        )
        for destination in destinations
    ]
    try:
        deadline = time.monotonic() + 20.0
        while len(list(barrier.glob("*.ready"))) != 2:
            if time.monotonic() >= deadline:
                raise AssertionError("publication admission children missed the barrier")
            time.sleep(0.005)
        (barrier / "go").write_text("go", encoding="ascii")
        return_codes = sorted(child.wait(timeout=30) for child in children)
    finally:
        for process in children:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    assert return_codes == [73, 91]
    debris = list(tmp_path.glob(".galaxy-publish-*"))
    assert len(debris) == expected_count
    assert not any((tmp_path / destination).exists() for destination in destinations)


def test_native_reconcile_reclaims_and_publishes_under_one_capacity_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    control = tmp_path / "control"
    root.mkdir()
    control.mkdir()
    payload = b"expected"
    for index in range(fsio._NATIVE_PUBLICATION_DEBRIS_MAX_TOTAL - 2):
        seeded_payload = f"payload-{index}".encode("ascii")
        (root / fsio._nativePublishTempName(
            f"other-{index}.bin",
            seeded_payload,
        )).write_bytes(seeded_payload)
    partial = root / fsio._nativePublishTempName("immutable.bin", payload)
    partial.write_bytes(payload[:3])

    ready = control / "ready"
    reclaimed = control / "reclaimed"
    occupied = control / "occupied"
    child = r"""
import sys
import time
from pathlib import Path
from platform_core.core import fsio

root = Path(sys.argv[1])
ready = Path(sys.argv[2])
reclaimed = Path(sys.argv[3])
occupied = Path(sys.argv[4])
ready.write_text("ready", encoding="ascii")
deadline = time.monotonic() + 20.0
while not reclaimed.exists():
    if time.monotonic() >= deadline:
        raise SystemExit(72)
    time.sleep(0.005)
try:
    with fsio.openNativeDirectory(root) as directory:
        with directory._publicationAdmission():
            payload = b"competitor"
            temporary = fsio._nativePublishTempName("competitor.bin", payload)
            (root / temporary).write_bytes(payload)
            occupied.write_text(temporary, encoding="ascii")
except BlockingIOError:
    raise SystemExit(73)
"""
    competitor = subprocess.Popen(
        [
            sys.executable,
            "-c",
            child,
            str(root),
            str(ready),
            str(reclaimed),
            str(occupied),
        ],
        cwd=_ROOT,
    )
    real_remove = fsio.NativeDirectoryHandle.removeFile

    def remove_then_offer_capacity(
        directory: fsio.NativeDirectoryHandle,
        name: str,
        *,
        expected: fsio.NativeFileIdentity | None = None,
    ) -> None:
        real_remove(directory, name, expected=expected)
        if name != partial.name:
            return
        reclaimed.write_text("reclaimed", encoding="ascii")
        deadline = time.monotonic() + 0.5
        while not occupied.exists() and time.monotonic() < deadline:
            time.sleep(0.005)

    try:
        deadline = time.monotonic() + 20.0
        while not ready.exists():
            if competitor.poll() is not None:
                raise AssertionError(
                    f"capacity competitor exited early: {competitor.returncode}"
                )
            if time.monotonic() >= deadline:
                raise AssertionError("capacity competitor missed readiness")
            time.sleep(0.005)
        monkeypatch.setattr(
            fsio.NativeDirectoryHandle,
            "removeFile",
            remove_then_offer_capacity,
        )
        with fsio.openNativeDirectory(root) as directory:
            published = directory.reconcileCreateOnlyFile("immutable.bin", payload)
        assert competitor.wait(timeout=10) == 0
    finally:
        if competitor.poll() is None:
            competitor.kill()
            competitor.wait(timeout=5)

    assert published.size == len(payload)
    assert (root / "immutable.bin").read_bytes() == payload
    assert not partial.exists()
    assert occupied.exists()
    assert len(list(root.glob(".galaxy-publish-*"))) == (
        fsio._NATIVE_PUBLICATION_DEBRIS_MAX_TOTAL - 1
    )


def test_native_reconcile_same_payload_is_cross_process_idempotent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    control = tmp_path / "control"
    root.mkdir()
    control.mkdir()
    child = r"""
import os
import sys
import time
import traceback
from pathlib import Path
from platform_core.core import fsio

root = Path(sys.argv[1])
control = Path(sys.argv[2])
payload = b"shared-payload"
(control / f"{os.getpid()}.ready").write_text("ready", encoding="ascii")
deadline = time.monotonic() + 20.0
while not (control / "go").exists():
    if time.monotonic() >= deadline:
        raise SystemExit(72)
    time.sleep(0.005)

real_list = fsio.NativeDirectoryHandle.listEntries
delayed = False
def synchronize_absent_inventory(directory, *args, **kwargs):
    global delayed
    entries = real_list(directory, *args, **kwargs)
    if not delayed and not any(entry.name == "immutable.bin" for entry in entries):
        delayed = True
        time.sleep(0.35)
    return entries

fsio.NativeDirectoryHandle.listEntries = synchronize_absent_inventory
try:
    with fsio.openNativeDirectory(root) as directory:
        identity = directory.reconcileCreateOnlyFile("immutable.bin", payload)
    if identity.size != len(payload):
        raise SystemExit(74)
except BaseException:
    traceback.print_exc()
    raise SystemExit(75)
raise SystemExit(0)
"""
    children = [
        subprocess.Popen(
            [sys.executable, "-c", child, str(root), str(control)],
            cwd=_ROOT,
        )
        for _ in range(2)
    ]
    try:
        deadline = time.monotonic() + 20.0
        while len(list(control.glob("*.ready"))) != 2:
            if any(process.poll() is not None for process in children):
                raise AssertionError("same-payload publisher exited before barrier")
            if time.monotonic() >= deadline:
                raise AssertionError("same-payload publishers missed readiness")
            time.sleep(0.005)
        (control / "go").write_text("go", encoding="ascii")
        return_codes = sorted(process.wait(timeout=30) for process in children)
    finally:
        for process in children:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    assert return_codes == [0, 0]
    assert (root / "immutable.bin").read_bytes() == b"shared-payload"
    assert not list(root.glob(".galaxy-publish-*"))


def test_native_publication_admission_refuses_a_live_holder_within_bound(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    control = tmp_path / "control"
    root.mkdir()
    control.mkdir()
    ready = control / "ready"
    release = control / "release"
    child = r"""
import sys
import time
from pathlib import Path
from platform_core.core import fsio

root = Path(sys.argv[1])
ready = Path(sys.argv[2])
release = Path(sys.argv[3])
with fsio.openNativeDirectory(root) as directory:
    with directory._publicationAdmission():
        ready.write_text("ready", encoding="ascii")
        deadline = time.monotonic() + 3.0
        while not release.exists() and time.monotonic() < deadline:
            time.sleep(0.005)
"""
    holder = subprocess.Popen(
        [sys.executable, "-c", child, str(root), str(ready), str(release)],
        cwd=_ROOT,
    )
    try:
        deadline = time.monotonic() + 20.0
        while not ready.exists():
            if holder.poll() is not None:
                raise AssertionError(
                    f"publication admission holder exited early: {holder.returncode}"
                )
            if time.monotonic() >= deadline:
                raise AssertionError("publication admission holder missed readiness")
            time.sleep(0.005)

        before = tuple(root.iterdir())
        started = time.monotonic()
        with fsio.openNativeDirectory(root) as directory:
            with pytest.raises(BlockingIOError) as raised:
                directory.reconcileCreateOnlyFile("immutable.bin", b"expected")
        elapsed = time.monotonic() - started

        assert raised.value.errno == errno.EBUSY
        assert elapsed < 2.0
        assert tuple(root.iterdir()) == before
    finally:
        release.write_text("release", encoding="ascii")
        try:
            holder.wait(timeout=5)
        except subprocess.TimeoutExpired:
            holder.kill()
            holder.wait(timeout=5)

    assert holder.returncode == 0


def test_native_publication_admission_refuses_same_handle_thread_within_bound(
    tmp_path: Path,
) -> None:
    acquired = threading.Event()
    release = threading.Event()
    holder_errors: list[BaseException] = []

    with fsio.openNativeDirectory(tmp_path) as directory:

        def hold_admission() -> None:
            try:
                with directory._publicationAdmission():
                    acquired.set()
                    if not release.wait(timeout=5):
                        raise AssertionError("same-handle holder missed release")
            except BaseException as exc:
                holder_errors.append(exc)

        holder = threading.Thread(target=hold_admission, daemon=True)
        holder.start()
        assert acquired.wait(timeout=5)
        before = tuple(tmp_path.iterdir())
        started = time.monotonic()
        try:
            with pytest.raises(BlockingIOError) as raised:
                directory.reconcileCreateOnlyFile("immutable.bin", b"expected")
        finally:
            release.set()
            holder.join(timeout=5)
        elapsed = time.monotonic() - started

    assert not holder.is_alive()
    assert holder_errors == []
    assert raised.value.errno == errno.EBUSY
    assert elapsed < 1.0
    assert tuple(tmp_path.iterdir()) == before


def test_lock_recovery_refuses_admission_without_mutating_stale_evidence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    lock_path = root / "owned.lock"
    lock_path.write_bytes(b"424242")
    old = time.time() - 7200
    os.utime(lock_path, (old, old))
    debris = root / fsio._nativePublishTempName(lock_path.name, b"dead")
    debris.write_bytes(b"dead")
    before = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.iterdir()
    }
    acquired = threading.Event()
    release = threading.Event()
    holder_errors: list[BaseException] = []

    def hold_admission() -> None:
        try:
            with fsio.openNativeDirectory(root) as directory:
                with directory._publicationAdmission():
                    acquired.set()
                    if not release.wait(timeout=5):
                        raise AssertionError("lock recovery holder missed release")
        except BaseException as exc:  # noqa: BLE001 - retained thread evidence
            holder_errors.append(exc)

    holder = threading.Thread(target=hold_admission, daemon=True)
    holder.start()
    assert acquired.wait(timeout=5)
    try:
        assert fsio.tryAcquireLockLease(
            lock_path,
            owner_alive=lambda _pid: False,
        ) is None
    finally:
        release.set()
        holder.join(timeout=5)

    assert not holder.is_alive()
    assert holder_errors == []
    assert {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.iterdir()
    } == before


def test_concurrent_process_lock_acquisition_has_one_exact_winner(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "contended.lock"
    control = tmp_path / "control"
    control.mkdir()
    # Two separate budgets. STARTUP covers interpreter start plus the
    # `platform_core` import in each child and measures nothing this test
    # asserts, so it must be generous or slow process births are reported as
    # lock-semantics failures. ELECTION covers only the post-`go` window, which
    # is the actual invariant, so it stays tight. RELEASE must exceed the
    # parent's worst case after `go` (ELECTION for the winner plus ELECTION for
    # the loser's refusal) or the winner can time out at exit 73 before the
    # parent ever writes `release`.
    STARTUP_TIMEOUT_SECONDS = 120.0
    ELECTION_TIMEOUT_SECONDS = 20.0
    RELEASE_TIMEOUT_SECONDS = 4.0 * ELECTION_TIMEOUT_SECONDS
    child = r"""
import os
import sys
import time
from pathlib import Path
from platform_core.core import fsio

lock_path = Path(sys.argv[1])
control = Path(sys.argv[2])
startup_timeout = float(sys.argv[3])
release_timeout = float(sys.argv[4])
(control / f"{os.getpid()}.ready").write_text("ready", encoding="ascii")
deadline = time.monotonic() + startup_timeout
while not (control / "go").exists():
    if time.monotonic() >= deadline:
        raise SystemExit(72)
    time.sleep(0.005)
lease = fsio.tryAcquireLockLease(lock_path)
if lease is None:
    raise SystemExit(83)
(control / f"{os.getpid()}.winner").write_text("winner", encoding="ascii")
deadline = time.monotonic() + release_timeout
while not (control / "release").exists():
    if time.monotonic() >= deadline:
        raise SystemExit(73)
    time.sleep(0.005)
fsio.releaseLock(lease)
raise SystemExit(0)
"""
    children = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                child,
                str(lock_path),
                str(control),
                str(STARTUP_TIMEOUT_SECONDS),
                str(RELEASE_TIMEOUT_SECONDS),
            ],
            cwd=_ROOT,
        )
        for _ in range(2)
    ]
    try:
        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
        while len(list(control.glob("*.ready"))) != 2:
            if any(process.poll() is not None for process in children):
                raise AssertionError("lock contender exited before barrier")
            if time.monotonic() >= deadline:
                raise AssertionError("lock contenders missed readiness")
            time.sleep(0.005)
        (control / "go").write_text("go", encoding="ascii")
        deadline = time.monotonic() + ELECTION_TIMEOUT_SECONDS
        while len(list(control.glob("*.winner"))) != 1:
            if time.monotonic() >= deadline:
                raise AssertionError("lock contender did not elect one winner")
            time.sleep(0.005)
        deadline = time.monotonic() + ELECTION_TIMEOUT_SECONDS
        while 83 not in {
            process.poll()
            for process in children
            if process.poll() is not None
        }:
            if time.monotonic() >= deadline:
                raise AssertionError("losing lock contender did not refuse")
            time.sleep(0.005)
        (control / "release").write_text("release", encoding="ascii")
        return_codes = sorted(process.wait(timeout=30) for process in children)
    finally:
        for process in children:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    assert return_codes == [0, 83]
    assert not lock_path.exists()
    assert not list(tmp_path.glob(".galaxy-publish-*"))
    assert not list(tmp_path.glob(".galaxy-delete-*"))


def test_same_thread_close_refuses_inside_publication_lifecycle_fence(
    tmp_path: Path,
) -> None:
    directory = fsio.openNativeDirectory(tmp_path)
    try:
        with directory._publicationAdmission():
            started = time.monotonic()
            with pytest.raises(BlockingIOError) as raised:
                directory.close()
            assert time.monotonic() - started < 0.2
            assert raised.value.errno == errno.EBUSY
            assert directory.identity.is_directory
        created = directory.createFile("after-refusal.bin", b"usable")
        assert created.size == len(b"usable")
    finally:
        directory.close()


def test_foreign_close_refuses_while_publication_is_paused_without_handle_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = fsio.openNativeDirectory(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []
    real_publish = fsio.NativeDirectoryHandle._publishNewFileUnlocked

    def paused_publish(
        current: fsio.NativeDirectoryHandle,
        name: str,
        payload: bytes,
        temporary_name: str,
    ) -> fsio.NativeFileIdentity:
        entered.set()
        if not release.wait(timeout=5):
            raise AssertionError("paused publisher missed release")
        return real_publish(current, name, payload, temporary_name)

    monkeypatch.setattr(
        fsio.NativeDirectoryHandle,
        "_publishNewFileUnlocked",
        paused_publish,
    )

    def publish() -> None:
        try:
            directory.createFile("published.bin", b"expected")
        except BaseException as exc:  # noqa: BLE001 - retained thread evidence
            errors.append(exc)

    publisher = threading.Thread(target=publish, daemon=True)
    publisher.start()
    assert entered.wait(timeout=5)
    started = time.monotonic()
    try:
        with pytest.raises(BlockingIOError) as raised:
            directory.close()
        assert raised.value.errno == errno.EBUSY
        assert time.monotonic() - started < 1.5
    finally:
        release.set()
        publisher.join(timeout=5)
        assert directory.identity.is_directory
        directory.close()

    assert not publisher.is_alive()
    assert errors == []
    assert (tmp_path / "published.bin").read_bytes() == b"expected"
    assert not list(tmp_path.glob(".galaxy-publish-*"))


def test_foreign_close_refuses_while_directory_inventory_is_paused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "one.bin").write_bytes(b"one")
    directory = fsio.openNativeDirectory(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []
    if os.name == "nt":
        real_inventory = fsio._winListDirectory

        def paused_inventory(*args: object, **kwargs: object):
            entered.set()
            if not release.wait(timeout=5):
                raise AssertionError("paused inventory missed release")
            return real_inventory(*args, **kwargs)  # type: ignore[call-arg]

        monkeypatch.setattr(fsio, "_winListDirectory", paused_inventory)
    else:
        real_inventory = fsio._posixListDirectoryNames

        def paused_inventory(*args: object, **kwargs: object):
            entered.set()
            if not release.wait(timeout=5):
                raise AssertionError("paused inventory missed release")
            return real_inventory(*args, **kwargs)  # type: ignore[call-arg]

        monkeypatch.setattr(fsio, "_posixListDirectoryNames", paused_inventory)

    def inventory() -> None:
        try:
            directory.listEntries()
        except BaseException as exc:  # noqa: BLE001 - retained thread evidence
            errors.append(exc)

    worker = threading.Thread(target=inventory, daemon=True)
    worker.start()
    assert entered.wait(timeout=5)
    try:
        with pytest.raises(BlockingIOError) as raised:
            directory.close()
        assert raised.value.errno == errno.EBUSY
    finally:
        release.set()
        worker.join(timeout=5)
        directory.close()

    assert not worker.is_alive()
    assert errors == []


def test_foreign_close_refuses_while_create_directory_is_paused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = fsio.openNativeDirectory(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []
    if os.name == "nt":
        seam_name = "_winOpenRelative"
    else:
        seam_name = "open"
    real_open = getattr(fsio, seam_name) if os.name == "nt" else os.open

    def paused_open(*args: object, **kwargs: object):
        name = args[1] if os.name == "nt" else args[0]
        if name == "child":
            entered.set()
            if not release.wait(timeout=5):
                raise AssertionError("paused directory create missed release")
        return real_open(*args, **kwargs)  # type: ignore[call-arg]

    if os.name == "nt":
        monkeypatch.setattr(fsio, seam_name, paused_open)
    else:
        monkeypatch.setattr(fsio.os, "open", paused_open)

    def create() -> None:
        child = None
        try:
            child = directory.createDirectory("child")
        except BaseException as exc:  # noqa: BLE001 - retained thread evidence
            errors.append(exc)
        finally:
            if child is not None:
                child.close()

    worker = threading.Thread(target=create, daemon=True)
    worker.start()
    assert entered.wait(timeout=5)
    try:
        with pytest.raises(BlockingIOError) as raised:
            directory.close()
        assert raised.value.errno == errno.EBUSY
    finally:
        release.set()
        worker.join(timeout=5)
        directory.close()

    assert not worker.is_alive()
    assert errors == []
    assert (tmp_path / "child").is_dir()


def test_copy_fences_both_handles_and_opposite_transfers_do_not_abba(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    left_root = tmp_path / "left"
    right_root = tmp_path / "right"
    left_root.mkdir()
    right_root.mkdir()
    (left_root / "left.bin").write_bytes(b"left")
    (right_root / "right.bin").write_bytes(b"right")
    left = fsio.openNativeDirectory(left_root)
    right = fsio.openNativeDirectory(right_root)
    entered = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []
    seam_name = "_winWriteAll" if os.name == "nt" else "_writeAll"
    real_write = getattr(fsio, seam_name)
    paused = False

    def paused_write(*args: object, **kwargs: object):
        nonlocal paused
        if not paused:
            paused = True
            entered.set()
            if not release.wait(timeout=5):
                raise AssertionError("paused copy missed release")
        return real_write(*args, **kwargs)

    monkeypatch.setattr(fsio, seam_name, paused_write)

    def copy_left_to_right() -> None:
        try:
            left.copyFileTo(
                "left.bin",
                right,
                "left-copy.bin",
                max_bytes=16,
            )
        except BaseException as exc:  # noqa: BLE001 - retained thread evidence
            errors.append(exc)

    first = threading.Thread(target=copy_left_to_right, daemon=True)
    first.start()
    assert entered.wait(timeout=5)
    try:
        for directory in (left, right):
            with pytest.raises(BlockingIOError) as raised:
                directory.close()
            assert raised.value.errno == errno.EBUSY
    finally:
        release.set()
        first.join(timeout=5)

    barrier = threading.Barrier(2)

    def opposite(
        source: fsio.NativeDirectoryHandle,
        source_name: str,
        destination: fsio.NativeDirectoryHandle,
        destination_name: str,
    ) -> None:
        try:
            barrier.wait(timeout=5)
            source.copyFileTo(
                source_name,
                destination,
                destination_name,
                max_bytes=16,
            )
        except BaseException as exc:  # noqa: BLE001 - retained thread evidence
            errors.append(exc)

    workers = [
        threading.Thread(
            target=opposite,
            args=(left, "left.bin", right, "left-copy-2.bin"),
            daemon=True,
        ),
        threading.Thread(
            target=opposite,
            args=(right, "right.bin", left, "right-copy.bin"),
            daemon=True,
        ),
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)
    left.close()
    right.close()

    assert not first.is_alive()
    assert all(not worker.is_alive() for worker in workers)
    assert errors == []
    assert (right_root / "left-copy.bin").read_bytes() == b"left"
    assert (right_root / "left-copy-2.bin").read_bytes() == b"left"
    assert (left_root / "right-copy.bin").read_bytes() == b"right"


@pytest.mark.parametrize("operation", ("mode", "replace", "remove-directory"))
def test_close_refuses_during_other_retained_handle_operations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    directory = fsio.openNativeDirectory(tmp_path)
    if operation == "mode":
        (tmp_path / "target.bin").write_bytes(b"target")
        target_name = "target.bin"
    elif operation == "replace":
        (tmp_path / "source.bin").write_bytes(b"source")
        (tmp_path / "target.bin").write_bytes(b"target")
        target_name = "source.bin"
    else:
        (tmp_path / "child").mkdir()
        target_name = "child"
    entered = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []
    real_entry = fsio.NativeDirectoryHandle._entry
    paused = False

    def paused_entry(
        current: fsio.NativeDirectoryHandle,
        name: str,
        **kwargs: object,
    ) -> fsio.NativeDirectoryEntry:
        nonlocal paused
        if name == target_name and not paused:
            paused = True
            entered.set()
            if not release.wait(timeout=5):
                raise AssertionError("paused retained operation missed release")
        return real_entry(current, name, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(fsio.NativeDirectoryHandle, "_entry", paused_entry)

    def mutate() -> None:
        try:
            if operation == "mode":
                directory.setFileMode("target.bin", 0o644)
            elif operation == "replace":
                directory.replaceFile("source.bin", "target.bin")
            else:
                directory.removeDirectory("child")
        except BaseException as exc:  # noqa: BLE001 - retained thread evidence
            errors.append(exc)

    worker = threading.Thread(target=mutate, daemon=True)
    worker.start()
    assert entered.wait(timeout=5)
    try:
        with pytest.raises(BlockingIOError) as raised:
            directory.close()
        assert raised.value.errno == errno.EBUSY
    finally:
        release.set()
        worker.join(timeout=10)
        directory.close()

    assert not worker.is_alive()
    assert errors == []


def test_posix_close_real_close_then_error_is_logically_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.name == "nt":
        return
    directory = fsio.openNativeDirectory(tmp_path)
    retained_fd = directory._handle
    real_close = os.close

    def close_then_error(fd: int) -> None:
        real_close(fd)
        raise OSError(errno.EIO, "reported after real close")

    monkeypatch.setattr(fsio.os, "close", close_then_error)
    with pytest.raises(OSError, match="reported after real close"):
        directory.close()
    monkeypatch.setattr(fsio.os, "close", real_close)
    reused = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        assert reused == retained_fd
        directory.close()
        with pytest.raises(OSError, match="closed"):
            directory.listEntries()
        assert os.fstat(reused).st_ino == tmp_path.stat().st_ino
    finally:
        os.close(reused)


def test_inherited_native_directory_handle_refuses_child_use_after_fork(
    tmp_path: Path,
) -> None:
    if not hasattr(os, "fork"):
        return
    directory = fsio.openNativeDirectory(tmp_path)
    read_end, write_end = os.pipe()
    pid = os.fork()
    if pid == 0:  # pragma: no cover - assertions are reported through the pipe
        os.close(read_end)
        try:
            directory.listEntries()
        except OSError as exc:
            os.write(write_end, f"refused:{exc.errno}".encode("ascii"))
        else:
            os.write(write_end, b"accepted")
        finally:
            os.close(write_end)
        os._exit(0)
    os.close(write_end)
    try:
        result = os.read(read_end, 128)
        _, status = os.waitpid(pid, 0)
        assert os.waitstatus_to_exitcode(status) == 0
        assert result.startswith(b"refused:")
        assert directory.identity.is_directory
    finally:
        os.close(read_end)
        directory.close()


def test_open_native_directory_refuses_a_linked_ancestor_without_outside_access(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel.bin").write_bytes(b"untouched")
    link = tmp_path / "linked"
    if os.name == "nt":
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(outside)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return
    else:
        link.symlink_to(outside, target_is_directory=True)
    try:
        with pytest.raises(OSError):
            fsio.openNativeDirectory(link)
        with pytest.raises(OSError):
            fsio.tryAcquireLockLease(link / "created" / "owned.lock")
        assert not (outside / "created").exists()
        assert (outside / "sentinel.bin").read_bytes() == b"untouched"
    finally:
        if os.name == "nt" and link.exists():
            os.rmdir(link)


def test_open_native_directory_refuses_ancestor_replacement_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    safe = root / "safe"
    outside = tmp_path / "outside"
    safe.mkdir(parents=True)
    outside.mkdir()
    (outside / "sentinel.bin").write_bytes(b"untouched")
    real_open = fsio.NativeDirectoryHandle.openDirectory
    replaced = False
    junction_created = False

    def replace_then_open(
        directory: fsio.NativeDirectoryHandle,
        name: str,
        *args: object,
        **kwargs: object,
    ) -> fsio.NativeDirectoryHandle:
        nonlocal replaced, junction_created
        if name == "safe" and not replaced:
            replaced = True
            safe.rename(root / "parked")
            if os.name == "nt":
                result = subprocess.run(
                    [
                        "cmd.exe",
                        "/d",
                        "/c",
                        "mklink",
                        "/J",
                        str(safe),
                        str(outside),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0:
                    (root / "parked").rename(safe)
                    return real_open(directory, name, *args, **kwargs)  # type: ignore[arg-type]
                junction_created = True
            else:
                safe.symlink_to(outside, target_is_directory=True)
        return real_open(directory, name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        fsio.NativeDirectoryHandle,
        "openDirectory",
        replace_then_open,
    )
    try:
        with pytest.raises(OSError):
            fsio.openNativeDirectory(safe)
    finally:
        if os.name == "nt" and junction_created and safe.exists():
            os.rmdir(safe)

    assert (outside / "sentinel.bin").read_bytes() == b"untouched"


@pytest.mark.skipif(os.name == "nt", reason="POSIX deletion lifecycle fence")
def test_foreign_close_refuses_while_posix_delete_is_paused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target.bin"
    target.write_bytes(b"expected")
    directory = fsio.openNativeDirectory(tmp_path)
    expected = directory._entry(target.name).identity
    entered = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def pause(phase: str) -> None:
        if phase != "staging-open":
            return
        entered.set()
        if not release.wait(timeout=5):
            raise AssertionError("paused deletion missed release")

    monkeypatch.setattr(fsio, "_nativeDeletionCrashPoint", pause)

    def delete() -> None:
        try:
            directory.removeFile(target.name, expected=expected)
        except BaseException as exc:  # noqa: BLE001 - retained thread evidence
            errors.append(exc)

    deleter = threading.Thread(target=delete, daemon=True)
    deleter.start()
    assert entered.wait(timeout=5)
    try:
        with pytest.raises(BlockingIOError) as raised:
            directory.close()
        assert raised.value.errno == errno.EBUSY
    finally:
        release.set()
        deleter.join(timeout=5)
        assert directory.identity.is_directory
        directory.close()

    assert not deleter.is_alive()
    assert errors == []
    assert not target.exists()
    assert not list(tmp_path.glob(".galaxy-delete-*"))


@pytest.mark.skipif(os.name != "nt", reason="Windows publication mutex boundary")
def test_windows_publication_mutex_release_failure_preserves_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_release = fsio._ReleaseMutex
    release_attempted = False

    def release_then_report_failure(mutex: int) -> bool:
        nonlocal release_attempted
        release_attempted = True
        assert real_release(mutex)
        return False

    monkeypatch.setattr(fsio, "_ReleaseMutex", release_then_report_failure)
    with fsio.openNativeDirectory(tmp_path) as directory:
        result = directory.reconcileCreateOnlyFile("immutable.bin", b"expected")
        with pytest.raises(BlockingIOError) as poisoned:
            directory.reconcileCreateOnlyFile("second.bin", b"second")

    assert release_attempted is True
    assert poisoned.value.errno == errno.EBUSY
    assert result.size == len(b"expected")
    assert (tmp_path / "immutable.bin").read_bytes() == b"expected"
    assert not (tmp_path / "second.bin").exists()
    assert not list(tmp_path.glob(".galaxy-publish-*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX publication flock boundary")
def test_posix_publication_unlock_failure_preserves_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import fcntl

    real_flock = fcntl.flock
    unlock_attempted = False

    def unlock_then_report_failure(handle: int, operation: int) -> None:
        nonlocal unlock_attempted
        real_flock(handle, operation)
        if operation == fcntl.LOCK_UN:
            unlock_attempted = True
            raise OSError("injected publication unlock refusal")

    monkeypatch.setattr(fcntl, "flock", unlock_then_report_failure)
    with fsio.openNativeDirectory(tmp_path) as directory:
        result = directory.reconcileCreateOnlyFile("immutable.bin", b"expected")
        with pytest.raises(BlockingIOError) as poisoned:
            directory.reconcileCreateOnlyFile("second.bin", b"second")

    assert unlock_attempted is True
    assert poisoned.value.errno == errno.EBUSY
    assert result.size == len(b"expected")
    assert (tmp_path / "immutable.bin").read_bytes() == b"expected"
    assert not (tmp_path / "second.bin").exists()
    assert not list(tmp_path.glob(".galaxy-publish-*"))


def test_dead_lock_publication_debris_flood_is_validated_before_any_reap(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "owned.lock"
    payload = b"999999999"
    for _ in range(17):
        temporary = tmp_path / fsio._nativePublishTempName(lock_path.name, payload)
        temporary.write_bytes(payload)
    before = {
        path.name: path.read_bytes()
        for path in tmp_path.glob(".galaxy-publish-*")
    }

    with fsio.openNativeDirectory(tmp_path) as directory:
        with pytest.raises(
            OSError,
            match="same-destination publication debris quota",
        ) as raised:
            fsio._maybeReapDeadLockPublicationDebris(
                directory,
                lock_path.name,
                lock_path,
            )

    assert type(raised.value) is fsio.NativeDirectoryQuotaExceeded
    assert {
        path.name: path.read_bytes()
        for path in tmp_path.glob(".galaxy-publish-*")
    } == before


@pytest.mark.parametrize(
    ("debris_payload", "observed"),
    [
        (b"COMPLETE-PAYLOAD", b"COMPLETE"),
        (b"complete-payload", b"not-a-prefix"),
    ],
    ids=("wrong-payload-digest", "non-prefix-bytes"),
)
def test_native_reconcile_refuses_mismatched_same_destination_debris_untouched(
    tmp_path: Path,
    debris_payload: bytes,
    observed: bytes,
) -> None:
    expected = b"complete-payload"
    temporary = tmp_path / fsio._nativePublishTempName(
        "immutable.bin",
        debris_payload,
    )
    temporary.write_bytes(observed)

    with fsio.openNativeDirectory(tmp_path) as directory:
        with pytest.raises(OSError, match="debris differs from expected payload"):
            directory.reconcileCreateOnlyFile("immutable.bin", expected)

    assert temporary.read_bytes() == observed
    assert not (tmp_path / "immutable.bin").exists()


def test_native_reconcile_refuses_unsafe_matching_debris_untouched(
    tmp_path: Path,
) -> None:
    payload = b"complete-payload"
    unsafe = tmp_path / fsio._nativePublishTempName("immutable.bin", payload)
    unsafe.mkdir()

    with fsio.openNativeDirectory(tmp_path) as directory:
        with pytest.raises(OSError, match="debris is unsafe"):
            directory.reconcileCreateOnlyFile("immutable.bin", payload)

    assert unsafe.is_dir()
    assert not (tmp_path / "immutable.bin").exists()


def test_native_reconcile_refuses_hard_linked_matching_debris_untouched(
    tmp_path: Path,
) -> None:
    payload = b"complete-payload"
    unsafe = tmp_path / fsio._nativePublishTempName("immutable.bin", payload)
    unsafe.write_bytes(payload[:7])
    alias = tmp_path / "publisher-alias.bin"
    os.link(unsafe, alias)

    with fsio.openNativeDirectory(tmp_path) as directory:
        with pytest.raises(OSError, match="debris is unsafe"):
            directory.reconcileCreateOnlyFile("immutable.bin", payload)

    assert unsafe.read_bytes() == payload[:7]
    assert alias.read_bytes() == payload[:7]
    assert os.path.samefile(unsafe, alias)
    assert not (tmp_path / "immutable.bin").exists()


def test_native_reconcile_refuses_reparse_matching_debris_untouched(
    tmp_path: Path,
) -> None:
    payload = b"complete-payload"
    target = tmp_path / "publisher-target.bin"
    target.write_bytes(payload[:7])
    unsafe = tmp_path / fsio._nativePublishTempName("immutable.bin", payload)
    try:
        unsafe.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"file symlink creation is unavailable: {exc}")

    with fsio.openNativeDirectory(tmp_path) as directory:
        with pytest.raises(OSError, match="debris is unsafe"):
            directory.reconcileCreateOnlyFile("immutable.bin", payload)

    assert unsafe.is_symlink()
    assert unsafe.read_bytes() == payload[:7]
    assert target.read_bytes() == payload[:7]
    assert not (tmp_path / "immutable.bin").exists()


def test_native_reconcile_refuses_active_matching_debris_untouched(
    tmp_path: Path,
) -> None:
    payload = b"complete-payload"
    temporary_name = fsio._nativePublishTempName("immutable.bin", payload)
    temporary = tmp_path / temporary_name
    temporary.write_bytes(payload[:7])

    with fsio._activeNativePublication(temporary_name):
        with fsio.openNativeDirectory(tmp_path) as directory:
            with pytest.raises(OSError, match="debris differs from expected payload"):
                directory.reconcileCreateOnlyFile("immutable.bin", payload)

    assert temporary.read_bytes() == payload[:7]
    assert not (tmp_path / "immutable.bin").exists()


def test_native_reconcile_refuses_unverifiable_matching_owner_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"complete-payload"
    local_name = fsio._nativePublishTempName("immutable.bin", payload)
    foreign_name = local_name.replace(
        f"-{os.getpid()}-{fsio._NATIVE_PROCESS_START_TOKEN}-",
        f"-424242-{'a' * 32}-",
        1,
    )
    temporary = tmp_path / foreign_name
    temporary.write_bytes(payload[:7])

    def unavailable(_pid: int) -> str | None:
        raise OSError("birth identity unavailable")

    monkeypatch.setattr(fsio, "_nativeProcessStartToken", unavailable)
    with fsio.openNativeDirectory(tmp_path) as directory:
        with pytest.raises(OSError, match="debris differs from expected payload"):
            directory.reconcileCreateOnlyFile("immutable.bin", payload)

    assert temporary.read_bytes() == payload[:7]
    assert not (tmp_path / "immutable.bin").exists()


def test_native_reconcile_refuses_ambiguous_matching_debris_untouched(
    tmp_path: Path,
) -> None:
    payload = b"complete-payload"
    temporaries = tuple(
        tmp_path / fsio._nativePublishTempName("immutable.bin", payload)
        for _ in range(2)
    )
    for index, temporary in enumerate(temporaries, start=1):
        temporary.write_bytes(payload[: index + 3])

    with fsio.openNativeDirectory(tmp_path) as directory:
        with pytest.raises(OSError, match="debris is ambiguous"):
            directory.reconcileCreateOnlyFile("immutable.bin", payload)

    assert [temporary.read_bytes() for temporary in temporaries] == [
        payload[:4],
        payload[:5],
    ]
    assert not (tmp_path / "immutable.bin").exists()


def test_hard_death_before_create_only_publish_never_leaves_partial_final(
    tmp_path,
):
    path = tmp_path / "immutable.bin"
    script = r"""
import os
import sys
from pathlib import Path
from platform_core.core import fsio

def die_before_publish(*args, **kwargs):
    os._exit(91)

if os.name == "nt":
    fsio._winRenameRelative = die_before_publish
else:
    fsio._posixRenameNoReplace = die_before_publish
fsio.exclusiveCreateBytes(Path(sys.argv[1]), b"partial-must-never-publish")
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        cwd=_ROOT,
        check=False,
        timeout=30,
    )

    assert result.returncode == 91
    assert not path.exists()
    debris = list(tmp_path.glob(".galaxy-publish-*.tmp"))
    assert len(debris) == 1
    before = debris[0].read_bytes()
    with pytest.raises(OSError, match="create-only publication debris"):
        fsio.exclusiveCreateBytes(path, b"complete")
    assert not path.exists()
    assert debris[0].read_bytes() == before
    fsio.exclusiveCreateBytes(path, b"partial-must-never-publish")
    assert path.read_bytes() == b"partial-must-never-publish"
    assert list(tmp_path.glob(".galaxy-publish-*.tmp")) == []


def test_hard_death_during_create_only_write_reaps_only_owned_partial_debris(
    tmp_path,
):
    path = tmp_path / "immutable.bin"
    script = r"""
import os
import sys
from pathlib import Path
from platform_core.core import fsio

if os.name == "nt":
    original = fsio._winWriteAll
    def die_during_write(handle, payload, *, flush=True):
        assert flush is False
        original(handle, payload[: max(1, len(payload) // 2)], flush=False)
        os._exit(92)
    fsio._winWriteAll = die_during_write
else:
    original = fsio._writeAll
    def die_during_write(handle, payload):
        original(handle, payload[: max(1, len(payload) // 2)])
        os.fsync(handle)
        os._exit(92)
    fsio._writeAll = die_during_write
fsio.exclusiveCreateBytes(Path(sys.argv[1]), b"complete-payload")
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        cwd=_ROOT,
        check=False,
        timeout=30,
    )

    assert result.returncode == 92
    assert not path.exists()
    assert list(tmp_path.glob(".galaxy-publish-*.tmp"))
    fsio.exclusiveCreateBytes(path, b"complete-payload")
    assert path.read_bytes() == b"complete-payload"
    assert list(tmp_path.glob(".galaxy-publish-*.tmp")) == []


def test_hard_death_after_create_only_publish_replays_exact_final_identity(
    tmp_path: Path,
) -> None:
    path = tmp_path / "immutable.bin"
    script = r"""
import os
import sys
from pathlib import Path
from platform_core.core import fsio

original = fsio.NativeDirectoryHandle._publishNewFileUnlocked
def die_after_publish(directory, name, payload, temporary_name):
    result = original(directory, name, payload, temporary_name)
    os._exit(93)
fsio.NativeDirectoryHandle._publishNewFileUnlocked = die_after_publish
fsio.exclusiveCreateBytes(Path(sys.argv[1]), b"complete-payload")
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        cwd=_ROOT,
        check=False,
        timeout=30,
    )

    assert result.returncode == 93
    assert path.read_bytes() == b"complete-payload"
    with fsio.openNativeDirectory(tmp_path) as directory:
        original_identity = directory._entry(path.name).identity
        replayed = directory.reconcileCreateOnlyFile(path.name, b"complete-payload")

    assert fsio._sameNativeFileObject(replayed, original_identity)
    assert replayed == original_identity
    assert list(tmp_path.glob(".galaxy-publish-*.tmp")) == []


def test_create_only_reaps_inactive_current_process_publication(tmp_path):
    payload = b"complete-payload"
    stale = tmp_path / fsio._nativePublishTempName("immutable.bin", payload)
    stale.write_bytes(payload)

    with fsio.openNativeDirectory(tmp_path) as directory:
        directory.createFile("immutable.bin", payload)

    assert (tmp_path / "immutable.bin").read_bytes() == payload
    assert list(tmp_path.glob(".galaxy-publish-*.tmp")) == []


def test_durable_atomic_replace_bytes_has_no_temporary_residue(tmp_path):
    path = tmp_path / "head.json"
    fsio.durableAtomicReplaceBytes(path, b"first")
    fsio.durableAtomicReplaceBytes(path, b"second")
    assert path.read_bytes() == b"second"
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.skipif(os.name != "nt", reason="Windows retained-handle boundary")
def test_native_directory_handle_survives_path_rebinding(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    (root / "evidence.txt").write_bytes(b"original")

    with fsio.openNativeDirectory(root) as directory:
        moved = tmp_path / "candidate-moved"
        root.rename(moved)
        root.mkdir()
        (root / "evidence.txt").write_bytes(b"replacement")

        entries = directory.listEntries()
        assert [entry.name for entry in entries] == ["evidence.txt"]
        assert directory.readFile("evidence.txt", max_bytes=32) == b"original"

    assert (root / "evidence.txt").read_bytes() == b"replacement"
    assert (moved / "evidence.txt").read_bytes() == b"original"


@pytest.mark.skipif(os.name != "nt", reason="Windows retained-handle boundary")
def test_native_directory_mutations_target_retained_identity(tmp_path):
    root = tmp_path / "canonical"
    root.mkdir()
    (root / "tracked.txt").write_bytes(b"old")

    with fsio.openNativeDirectory(root) as directory:
        moved = tmp_path / "canonical-held"
        root.rename(moved)
        root.mkdir()
        (root / "tracked.txt").write_bytes(b"outside")

        directory.createFile("tracked.tmp", b"new")
        directory.replaceFile("tracked.tmp", "tracked.txt")
        with directory.createDirectory("tombstone") as tombstone:
            directory.moveChild("tracked.txt", tombstone, "tracked.txt")
            assert tombstone.readFile("tracked.txt", max_bytes=16) == b"new"
            tombstone.removeFile("tracked.txt")
        directory.removeDirectory("tombstone")

    assert (root / "tracked.txt").read_bytes() == b"outside"
    assert list(moved.iterdir()) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX in-place retained-read race")
def test_native_read_rejects_same_size_in_place_rewrite(tmp_path, monkeypatch):
    path = tmp_path / "payload.bin"
    path.write_bytes(b"a" * (128 * 1024))
    original_read = fsio.os.read
    raced = False

    def read_then_rewrite(fd, size):
        nonlocal raced
        block = original_read(fd, size)
        if block and not raced:
            raced = True
            with path.open("r+b", buffering=0) as stream:
                stream.write(b"b" * (128 * 1024))
                os.fsync(stream.fileno())
        return block

    monkeypatch.setattr(fsio.os, "read", read_then_rewrite)
    with fsio.openNativeDirectory(tmp_path) as directory:
        with pytest.raises(OSError, match="raced retained read"):
            directory.readFile(path.name, max_bytes=128 * 1024)


@pytest.mark.skipif(os.name != "nt", reason="Windows retained-handle move boundary")
def test_windows_native_move_revalidates_the_published_source_identity(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    (source / "owned.bin").write_bytes(b"owned")

    real_entry = fsio.NativeDirectoryHandle._entry
    destination_reads = 0

    def report_rebound_destination(directory, name):
        nonlocal destination_reads
        entry = real_entry(directory, name)
        if name == "moved.bin" and entry.name == name:
            destination_reads += 1
            return replace(
                entry,
                identity=replace(entry.identity, file_id=entry.identity.file_id + 1),
            )
        return entry

    monkeypatch.setattr(
        fsio.NativeDirectoryHandle,
        "_entry",
        report_rebound_destination,
    )
    with fsio.openNativeDirectory(source) as source_directory:
        expected = real_entry(source_directory, "owned.bin").identity
        with fsio.openNativeDirectory(destination) as destination_directory:
            with pytest.raises(OSError, match="published.*identity"):
                source_directory.moveChild(
                    "owned.bin",
                    destination_directory,
                    "moved.bin",
                    expected=expected,
                )

    assert destination_reads == 1
    assert (destination / "moved.bin").read_bytes() == b"owned"


@pytest.mark.parametrize(
    ("same_directory", "source_is_directory"),
    [(True, False), (False, False), (False, True)],
    ids=("same-dir-file", "cross-dir-file", "cross-dir-directory"),
)
@pytest.mark.skipif(os.name == "nt", reason="POSIX generic move is unavailable")
def test_posix_generic_move_is_enotsup_without_mutation(
    tmp_path: Path,
    same_directory: bool,
    source_is_directory: bool,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    owned = source / "owned"
    if source_is_directory:
        owned.mkdir()
    else:
        owned.write_bytes(b"owned")
    destination_root = source if same_directory else destination

    with fsio.openNativeDirectory(source) as source_directory:
        expected = source_directory._entry("owned").identity
        with fsio.openNativeDirectory(destination_root) as destination_directory:
            with pytest.raises(OSError, match="generic POSIX move") as raised:
                source_directory.moveChild(
                    "owned",
                    destination_directory,
                    "moved",
                    expected=expected,
                )

    assert raised.value.errno == errno.ENOTSUP
    if source_is_directory:
        assert owned.is_dir()
    else:
        assert owned.read_bytes() == b"owned"
    assert not (destination_root / "moved").exists()
    assert not list(source.glob(".galaxy-delete-*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX generic move is unavailable")
def test_posix_generic_move_refuses_multilink_before_mutation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    owned = source / "owned"
    alias = source / "alias"
    owned.write_bytes(b"owned")
    os.link(owned, alias)

    with (
        fsio.openNativeDirectory(source) as source_directory,
        fsio.openNativeDirectory(destination) as destination_directory,
    ):
        with pytest.raises(OSError, match="generic POSIX move") as raised:
            source_directory.moveChild(
                "owned",
                destination_directory,
                "moved",
            )

    assert raised.value.errno == errno.ENOTSUP
    assert owned.read_bytes() == b"owned"
    assert alias.read_bytes() == b"owned"
    assert os.path.samefile(owned, alias)
    assert not (destination / "moved").exists()


@pytest.mark.parametrize(
    ("source_name", "destination_name", "error", "message"),
    [
        ("../owned", "moved", ValueError, "child name is invalid"),
        ("owned", "../moved", ValueError, "child name is invalid"),
        (
            "x" * 1_025,
            "moved",
            fsio.NativeDirectoryQuotaExceeded,
            "name byte quota",
        ),
        (
            "owned",
            "x" * 1_025,
            fsio.NativeDirectoryQuotaExceeded,
            "name byte quota",
        ),
    ],
)
@pytest.mark.skipif(os.name == "nt", reason="POSIX generic move is unavailable")
def test_posix_generic_move_validates_names_before_enotsup_or_mutation(
    tmp_path: Path,
    source_name: str,
    destination_name: str,
    error: type[Exception],
    message: str,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    (source / "owned").write_bytes(b"owned")

    with (
        fsio.openNativeDirectory(source) as source_directory,
        fsio.openNativeDirectory(destination) as destination_directory,
    ):
        with pytest.raises(error, match=message):
            source_directory.moveChild(
                source_name,
                destination_directory,
                destination_name,
            )

    assert (source / "owned").read_bytes() == b"owned"
    assert list(destination.iterdir()) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX retained deletion boundary")
def test_posix_remove_preserves_a_successor_rebound_after_entry_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "owned.lock"
    preserved = tmp_path / "owned-preserved.lock"
    target.write_bytes(b"owner-a")
    real_entry = fsio.NativeDirectoryHandle._entry
    rebound = False

    with fsio.openNativeDirectory(tmp_path) as directory:
        expected = real_entry(directory, target.name).identity

        def rebind_after_entry(
            observed_directory: fsio.NativeDirectoryHandle,
            name: str,
        ) -> fsio.NativeDirectoryEntry:
            nonlocal rebound
            entry = real_entry(observed_directory, name)
            if name == target.name and not rebound:
                target.rename(preserved)
                target.write_bytes(b"owner-b")
                rebound = True
            return entry

        monkeypatch.setattr(
            fsio.NativeDirectoryHandle,
            "_entry",
            rebind_after_entry,
        )
        with pytest.raises(OSError, match="identity.*race|identity differs"):
            directory.removeFile(target.name, expected=expected)

    assert rebound is True
    assert target.read_bytes() == b"owner-b"
    assert preserved.read_bytes() == b"owner-a"
    with fsio.openNativeDirectory(tmp_path) as directory:
        with pytest.raises(FileExistsError):
            directory.createFile(target.name, b"owner-c")


@pytest.mark.skipif(os.name == "nt", reason="POSIX retained deletion boundary")
def test_posix_remove_restores_a_successor_rebound_after_retained_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "owned.lock"
    preserved = tmp_path / "owned-preserved.lock"
    target.write_bytes(b"owner-a")
    real_identity = fsio._posixIdentity
    file_observations = 0
    rebound = False

    with fsio.openNativeDirectory(tmp_path) as directory:
        expected = directory._entry(target.name).identity

        def identify_then_rebind(handle: int) -> fsio.NativeFileIdentity:
            nonlocal file_observations, rebound
            identity = real_identity(handle)
            if not identity.is_directory:
                file_observations += 1
            if file_observations == 2 and not rebound:
                target.rename(preserved)
                target.write_bytes(b"owner-b")
                rebound = True
            return identity

        monkeypatch.setattr(fsio, "_posixIdentity", identify_then_rebind)
        with pytest.raises(OSError, match="identity differs|raced|preserved"):
            directory.removeFile(target.name, expected=expected)

    assert rebound is True
    assert target.read_bytes() == b"owner-b"
    assert preserved.read_bytes() == b"owner-a"
    with fsio.openNativeDirectory(tmp_path) as directory:
        with pytest.raises(FileExistsError):
            directory.createFile(target.name, b"owner-c")


@pytest.mark.skipif(os.name == "nt", reason="POSIX retained deletion boundary")
def test_posix_remove_guard_blocks_admission_during_quarantine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "owned.lock"
    target.write_bytes(b"owner-a")
    real_exchange = fsio._posixRenameExchange
    admission_probed = False

    with fsio.openNativeDirectory(tmp_path) as directory:
        expected = directory._entry(target.name).identity

        def exchange_then_probe(
            directory_handle: int,
            source_name: str,
            destination_name: str,
        ) -> None:
            nonlocal admission_probed
            real_exchange(directory_handle, source_name, destination_name)
            if not admission_probed:
                admission_probed = True
                with pytest.raises(FileExistsError):
                    directory.createFile(target.name, b"owner-c")

        monkeypatch.setattr(fsio, "_posixRenameExchange", exchange_then_probe)
        directory.removeFile(target.name, expected=expected)

    assert admission_probed is True
    assert not target.exists()
    assert not list(tmp_path.glob(".galaxy-delete-*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX retained deletion boundary")
@pytest.mark.parametrize("failure_ordinal", (1, 2, 3))
def test_posix_delete_guard_fsync_refusal_is_replayable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_ordinal: int,
) -> None:
    target = tmp_path / "owned.lock"
    target.write_bytes(b"owner-a")
    real_fsync = fsio.os.fsync
    guard_fsyncs = 0

    with fsio.openNativeDirectory(tmp_path) as directory:
        expected = directory._entry(target.name).identity

        def fail_selected_guard_fsync(handle: int) -> None:
            nonlocal guard_fsyncs
            if not stat.S_ISDIR(os.fstat(handle).st_mode):
                guard_fsyncs += 1
                if guard_fsyncs == failure_ordinal:
                    raise OSError("injected guard fsync refusal")
            real_fsync(handle)

        with monkeypatch.context() as faults:
            faults.setattr(fsio.os, "fsync", fail_selected_guard_fsync)
            with pytest.raises(OSError, match="injected guard fsync refusal"):
                directory.removeFile(target.name, expected=expected)

    with fsio.openNativeDirectory(tmp_path) as directory:
        directory.reconcileDeleteFile(target.name)
    assert target.read_bytes() == b"owner-a"
    assert not list(tmp_path.glob(".galaxy-delete-*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX retained deletion boundary")
@pytest.mark.parametrize("failure_ordinal", (1, 2, 3, 4, 5, 6))
def test_posix_delete_parent_sync_refusal_is_replayable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_ordinal: int,
) -> None:
    target = tmp_path / "owned.lock"
    target.write_bytes(b"owner-a")
    real_sync = fsio.NativeDirectoryHandle._syncDirectory
    parent_syncs = 0

    with fsio.openNativeDirectory(tmp_path) as directory:
        expected = directory._entry(target.name).identity

        def fail_selected_parent_sync(
            observed: fsio.NativeDirectoryHandle,
        ) -> None:
            nonlocal parent_syncs
            if observed is directory:
                parent_syncs += 1
                if parent_syncs == failure_ordinal:
                    raise OSError("injected parent sync refusal")
            real_sync(observed)

        with monkeypatch.context() as faults:
            faults.setattr(
                fsio.NativeDirectoryHandle,
                "_syncDirectory",
                fail_selected_parent_sync,
            )
            with pytest.raises(OSError, match="injected parent sync refusal"):
                directory.removeFile(target.name, expected=expected)

    with fsio.openNativeDirectory(tmp_path) as directory:
        directory.reconcileDeleteFile(target.name)
    if failure_ordinal <= 3:
        assert target.read_bytes() == b"owner-a"
    else:
        assert not target.exists()
    assert not list(tmp_path.glob(".galaxy-delete-*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX retained deletion boundary")
def test_posix_delete_cleanup_sync_refusal_does_not_relabel_durable_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "owned.lock"
    target.write_bytes(b"owner-a")
    real_sync = fsio.NativeDirectoryHandle._syncDirectory
    parent_syncs = 0

    with fsio.openNativeDirectory(tmp_path) as directory:
        expected = directory._entry(target.name).identity

        def fail_cleanup_parent_sync(
            observed: fsio.NativeDirectoryHandle,
        ) -> None:
            nonlocal parent_syncs
            if observed is directory:
                parent_syncs += 1
                if parent_syncs == 7:
                    raise OSError("injected post-commit cleanup sync refusal")
            real_sync(observed)

        monkeypatch.setattr(
            fsio.NativeDirectoryHandle,
            "_syncDirectory",
            fail_cleanup_parent_sync,
        )
        directory.removeFile(target.name, expected=expected)

    assert parent_syncs == 7
    assert not target.exists()
    assert not list(tmp_path.glob(".galaxy-delete-*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX retained deletion boundary")
def test_posix_delete_persistent_guard_unlink_refusal_retains_exact_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "owned.lock"
    target.write_bytes(b"owner-a")
    real_unlink = fsio.NativeDirectoryHandle._unlinkPosixDeleteChild
    quarantine_unlinks = 0

    def refuse_final_guard_unlink(
        directory: fsio.NativeDirectoryHandle,
        name: str,
        *,
        expected_key: tuple[int, int, bool, bool, int, int],
    ) -> None:
        nonlocal quarantine_unlinks
        if name.startswith(".galaxy-delete-v2-"):
            quarantine_unlinks += 1
            if quarantine_unlinks >= 2:
                raise PermissionError("injected persistent guard unlink refusal")
        real_unlink(directory, name, expected_key=expected_key)

    with fsio.openNativeDirectory(tmp_path) as directory:
        expected = directory._entry(target.name).identity
        with monkeypatch.context() as faults:
            faults.setattr(
                fsio.NativeDirectoryHandle,
                "_unlinkPosixDeleteChild",
                refuse_final_guard_unlink,
            )
            directory.removeFile(target.name, expected=expected)

    assert quarantine_unlinks == 3
    assert not target.exists()
    artifacts = list(tmp_path.glob(".galaxy-delete-*"))
    assert len(artifacts) == 1
    with fsio.openNativeDirectory(tmp_path) as directory:
        entry = directory._entry(artifacts[0].name)
        intent = directory._readDeleteIntentAt(entry, required=True)
        assert intent is not None
        assert intent.destination_name == target.name
        assert fsio._nativeStableIdentityKey(entry.identity) == intent.guard_key
        assert directory.reconcileDeleteFile(target.name) == 1

    assert not target.exists()
    assert not list(tmp_path.glob(".galaxy-delete-*"))


def _injectPosixDeletionCloseFailures(
    monkeypatch: pytest.MonkeyPatch,
    *,
    target_name: str,
) -> tuple[dict[str, int], list[str]]:
    """Close both retained deletion fds, then report one failure per close."""

    real_open = fsio.os.open
    real_close = fsio.os.close
    handles: dict[str, int] = {}
    close_attempts: list[str] = []

    def tracked_open(path, flags: int, *args, **kwargs) -> int:
        handle = real_open(path, flags, *args, **kwargs)
        component = os.fspath(path)
        path_only = getattr(os, "O_PATH", 0)
        if component == target_name and not (path_only and flags & path_only):
            handles.setdefault("retained", handle)
        elif component.startswith(".galaxy-delete-stage-v1-"):
            handles.setdefault("guard", handle)
        return handle

    def close_then_report_failure(handle: int) -> None:
        real_close(handle)
        for label, expected in handles.items():
            if handle == expected and label not in close_attempts:
                close_attempts.append(label)
                raise OSError(f"injected {label} close failure")

    monkeypatch.setattr(fsio.os, "open", tracked_open)
    monkeypatch.setattr(fsio.os, "close", close_then_report_failure)
    return handles, close_attempts


@pytest.mark.skipif(os.name == "nt", reason="POSIX deletion close semantics")
def test_posix_delete_close_failures_after_commit_do_not_relabel_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "owned.lock"
    target.write_bytes(b"owner-a")
    handles, close_attempts = _injectPosixDeletionCloseFailures(
        monkeypatch,
        target_name=target.name,
    )

    with fsio.openNativeDirectory(tmp_path) as directory:
        expected = directory._entry(target.name).identity
        directory.removeFile(target.name, expected=expected)

    assert close_attempts == ["retained", "guard"]
    assert set(handles) == {"retained", "guard"}
    for handle in handles.values():
        with pytest.raises(OSError) as raised:
            os.fstat(handle)
        assert raised.value.errno == errno.EBADF
    assert not target.exists()
    assert not list(tmp_path.glob(".galaxy-delete-*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX deletion close semantics")
def test_posix_delete_close_failures_preserve_the_primary_precommit_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "owned.lock"
    target.write_bytes(b"owner-a")
    handles, close_attempts = _injectPosixDeletionCloseFailures(
        monkeypatch,
        target_name=target.name,
    )

    def fail_precommit(phase: str) -> None:
        if phase == "staging-open":
            raise RuntimeError("injected primary precommit failure")

    monkeypatch.setattr(fsio, "_nativeDeletionCrashPoint", fail_precommit)
    with fsio.openNativeDirectory(tmp_path) as directory:
        expected = directory._entry(target.name).identity
        with pytest.raises(RuntimeError, match="primary precommit"):
            directory.removeFile(target.name, expected=expected)

    assert close_attempts == ["retained", "guard"]
    assert set(handles) == {"retained", "guard"}
    for handle in handles.values():
        with pytest.raises(OSError) as raised:
            os.fstat(handle)
        assert raised.value.errno == errno.EBADF
    assert target.read_bytes() == b"owner-a"
    artifacts = list(tmp_path.glob(".galaxy-delete-*"))
    assert len(artifacts) == 1
    with fsio.openNativeDirectory(tmp_path) as directory:
        assert directory.reconcileDeleteFile(target.name) == 1
    assert not list(tmp_path.glob(".galaxy-delete-*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX deletion intent classification")
def test_posix_delete_treats_an_ordinary_marker_bearing_file_as_payload(
    tmp_path: Path,
) -> None:
    target = tmp_path / "ordinary.bin"
    target.write_bytes(
        b"ordinary user payload containing "
        + fsio._NATIVE_DELETE_INTENT_SCHEMA.encode("ascii")
        + b" but no authenticated intent"
    )

    with fsio.openNativeDirectory(tmp_path) as directory:
        expected = directory._entry(target.name).identity
        directory.removeFile(target.name, expected=expected)

    assert not target.exists()
    assert not list(tmp_path.glob(".galaxy-delete-*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX deletion setup cleanup")
def test_posix_delete_nonce_setup_failure_closes_retained_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "ordinary.bin"
    target.write_bytes(b"expected")
    with fsio.openNativeDirectory(tmp_path) as directory:
        expected = directory._entry(target.name).identity
        real_open = fsio.os.open
        retained: list[int] = []

        def tracking_open(path, flags: int, *args, **kwargs) -> int:
            handle = real_open(path, flags, *args, **kwargs)
            path_only = getattr(os, "O_PATH", 0)
            if (
                os.fspath(path) == target.name
                and not (path_only and flags & path_only)
            ):
                retained.append(handle)
            return handle

        def fail_nonce(_size: int) -> bytes:
            raise OSError("injected deletion nonce failure")

        monkeypatch.setattr(fsio.os, "open", tracking_open)
        monkeypatch.setattr(fsio.os, "urandom", fail_nonce)
        with pytest.raises(OSError, match="nonce failure"):
            directory.removeFile(target.name, expected=expected)

        assert retained
        assert len(set(retained)) == 1
        with pytest.raises(OSError) as raised:
            os.fstat(retained[-1])
        assert raised.value.errno == errno.EBADF

    assert target.read_bytes() == b"expected"
    assert not list(tmp_path.glob(".galaxy-delete-*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX retained deletion boundary")
@pytest.mark.parametrize(
    "phase",
    (
        "staging-open",
        "staging-create",
        "intent-rename-empty",
        "intent-payload-prefix",
        "guard-create",
        "first-exchange",
        "quarantine-unlink",
        "public-guard-unlink",
    ),
)
def test_posix_delete_hard_death_replays_every_linear_prefix(
    tmp_path: Path,
    phase: str,
) -> None:
    target = tmp_path / "owned.lock"
    child = r"""
import os
import sys
from pathlib import Path
from platform_core.core import fsio

target = Path(sys.argv[1])
phase = sys.argv[2]
target.write_bytes(b"owner-a")

def crash(observed):
    if observed == phase:
        os._exit(91)

fsio._nativeDeletionCrashPoint = crash
with fsio.openNativeDirectory(target.parent) as directory:
    expected = directory._entry(target.name).identity
    directory.removeFile(target.name, expected=expected)
raise SystemExit(92)
"""
    result = subprocess.run(
        [sys.executable, "-c", child, str(target), phase],
        cwd=_ROOT,
        check=False,
        timeout=30,
    )

    assert result.returncode == 91
    with fsio.openNativeDirectory(tmp_path) as directory:
        directory.reconcileDeleteFile(target.name)
    if phase in {
        "staging-open",
        "staging-create",
        "intent-rename-empty",
        "intent-payload-prefix",
        "guard-create",
    }:
        assert target.read_bytes() == b"owner-a"
    else:
        assert not target.exists()
    assert not list(tmp_path.glob(".galaxy-delete-*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX retained deletion boundary")
def test_posix_delete_hard_death_after_successor_restore_preserves_b(
    tmp_path: Path,
) -> None:
    target = tmp_path / "owned.lock"
    preserved = tmp_path / "owner-a-preserved.lock"
    child = r"""
import os
import sys
from pathlib import Path
from platform_core.core import fsio

target = Path(sys.argv[1])
preserved = Path(sys.argv[2])
target.write_bytes(b"owner-a")
real_exchange = fsio._posixRenameExchange
first = True

def rebind_then_exchange(directory, source, destination):
    global first
    if first:
        first = False
        target.rename(preserved)
        target.write_bytes(b"owner-b")
    return real_exchange(directory, source, destination)

def crash(phase):
    if phase == "successor-restore":
        os._exit(91)

fsio._posixRenameExchange = rebind_then_exchange
fsio._nativeDeletionCrashPoint = crash
with fsio.openNativeDirectory(target.parent) as directory:
    expected = directory._entry(target.name).identity
    directory.removeFile(target.name, expected=expected)
raise SystemExit(92)
"""
    result = subprocess.run(
        [sys.executable, "-c", child, str(target), str(preserved)],
        cwd=_ROOT,
        check=False,
        timeout=30,
    )

    assert result.returncode == 91
    assert target.read_bytes() == b"owner-b"
    assert preserved.read_bytes() == b"owner-a"
    assert fsio.tryAcquireLockLease(
        target,
        owner_alive=lambda _pid: False,
    ) is None
    assert target.read_bytes() == b"owner-b"
    assert not list(tmp_path.glob(".galaxy-delete-*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX retained deletion boundary")
def test_posix_delete_live_owner_and_guard_are_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "owned.lock"
    ready = tmp_path / "ready"
    child = r"""
import os
import sys
import time
from pathlib import Path
from platform_core.core import fsio

target = Path(sys.argv[1])
ready = Path(sys.argv[2])
target.write_text(str(os.getpid()), encoding="ascii")

def pause(phase):
    if phase == "first-exchange":
        ready.write_text("ready", encoding="ascii")
        while True:
            time.sleep(0.05)

fsio._nativeDeletionCrashPoint = pause
with fsio.openNativeDirectory(target.parent) as directory:
    expected = directory._entry(target.name).identity
    directory.removeFile(target.name, expected=expected)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", child, str(target), str(ready)],
        cwd=_ROOT,
    )
    try:
        deadline = time.monotonic() + 5.0
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        before = {
            path.name: (path.stat().st_ino, path.read_bytes())
            for path in tmp_path.iterdir()
            if path.name.startswith(".galaxy-delete-") or path == target
        }

        assert fsio.tryAcquireLockLease(
            target,
            owner_alive=lambda _pid: False,
        ) is None
        after = {
            path.name: (path.stat().st_ino, path.read_bytes())
            for path in tmp_path.iterdir()
            if path.name.startswith(".galaxy-delete-") or path == target
        }
        assert after == before
    finally:
        process.kill()
        process.wait(timeout=10)

    before_unverifiable = {
        path.name: (path.stat().st_ino, path.read_bytes())
        for path in tmp_path.iterdir()
        if path.name.startswith(".galaxy-delete-") or path == target
    }

    def unavailable(_pid: int) -> str | None:
        raise OSError("process identity unavailable")

    with monkeypatch.context() as isolated:
        isolated.setattr(fsio, "_nativeProcessStartToken", unavailable)
        assert fsio.tryAcquireLockLease(
            target,
            owner_alive=lambda _pid: False,
        ) is None
    after_unverifiable = {
        path.name: (path.stat().st_ino, path.read_bytes())
        for path in tmp_path.iterdir()
        if path.name.startswith(".galaxy-delete-") or path == target
    }
    assert after_unverifiable == before_unverifiable

    with fsio.fileLock(
        target,
        timeout=0.5,
        poll=0.005,
        owner_alive=lambda _pid: False,
    ):
        assert target.exists()
    assert not list(tmp_path.glob(".galaxy-delete-*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX retained deletion boundary")
def test_posix_delete_malformed_bound_debris_fails_closed(
    tmp_path: Path,
) -> None:
    target = tmp_path / "owned.lock"
    target.write_bytes(b"owner-a")
    destination_key = hashlib.sha256(target.name.encode("utf-8")).hexdigest()
    debris = tmp_path / f".galaxy-delete-v2-{destination_key}-malformed"
    debris.write_bytes(b"not-an-intent")

    with pytest.raises(OSError, match="deletion artifact name is malformed"):
        fsio.tryAcquireLockLease(
            target,
            owner_alive=lambda _pid: False,
        )
    assert target.read_bytes() == b"owner-a"
    assert debris.read_bytes() == b"not-an-intent"


def test_posix_delete_reserves_combined_namespace_before_first_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.name == "nt":
        return
    target = tmp_path / "owned.lock"
    target.write_bytes(b"owner-a")
    monkeypatch.setattr(fsio, "_NATIVE_MUTATION_DEBRIS_MAX_TOTAL", 2)
    for index in range(2):
        payload = f"payload-{index}".encode("ascii")
        (tmp_path / fsio._nativePublishTempName(f"other-{index}", payload)).write_bytes(
            payload
        )
    before = {
        path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()
    }

    with fsio.openNativeDirectory(tmp_path) as directory:
        expected = directory._entry(target.name).identity
        with pytest.raises(
            fsio.NativeDirectoryQuotaExceeded,
            match="deletion debris total quota",
        ):
            directory.removeFile(target.name, expected=expected)

    assert {
        path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()
    } == before


def test_posix_delete_reserves_same_destination_debris_before_first_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.name == "nt":
        return
    target = tmp_path / "owned.lock"
    target.write_bytes(b"owner-a")
    monkeypatch.setattr(fsio, "_NATIVE_DELETE_DEBRIS_MAX_SAME_DESTINATION", 1)
    with fsio.openNativeDirectory(tmp_path) as directory:
        expected = directory._entry(target.name).identity
        for index in range(2):
            debris = tmp_path / fsio._nativeDeleteStagingName(
                target.name,
                expected,
                f"{index:016x}",
            )
            debris.write_bytes(b"")
        before = {
            path.name: path.read_bytes()
            for path in tmp_path.iterdir()
            if path.is_file()
        }
        with pytest.raises(
            fsio.NativeDirectoryQuotaExceeded,
            match="same-destination deletion debris quota",
        ):
            directory.removeFile(target.name, expected=expected)

    assert {
        path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()
    } == before


def test_posix_delete_max_minus_one_hard_death_replays_without_exceeding_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.name == "nt":
        return
    root = tmp_path / "root"
    root.mkdir()
    target = root / "owned.lock"
    target.write_bytes(b"owner-a")
    for index in range(2):
        (root / f"ordinary-{index}").write_bytes(b"ordinary")
    child = r"""
import os
import sys
from pathlib import Path
from platform_core.core import fsio

root = Path(sys.argv[1])
fsio._NATIVE_PUBLICATION_DIRECTORY_MAX_ENTRIES = 4
def crash(phase):
    if phase == "staging-open":
        os._exit(91)
fsio._nativeDeletionCrashPoint = crash
with fsio.openNativeDirectory(root) as directory:
    expected = directory._entry("owned.lock").identity
    directory.removeFile("owned.lock", expected=expected)
raise SystemExit(92)
"""
    result = subprocess.run(
        [sys.executable, "-c", child, str(root)],
        cwd=_ROOT,
        check=False,
        timeout=30,
    )
    assert result.returncode == 91
    assert len(list(root.iterdir())) == 4
    assert target.read_bytes() == b"owner-a"

    monkeypatch.setattr(fsio, "_NATIVE_PUBLICATION_DIRECTORY_MAX_ENTRIES", 4)
    with fsio.openNativeDirectory(root) as directory:
        expected = directory._entry(target.name).identity
        directory.removeFile(target.name, expected=expected)

    assert not target.exists()
    assert not list(root.glob(".galaxy-delete-*"))
    assert len(list(root.iterdir())) == 2


def test_posix_delete_exact_directory_cap_refuses_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.name == "nt":
        return
    root = tmp_path / "root"
    root.mkdir()
    target = root / "owned.lock"
    target.write_bytes(b"owner-a")
    for index in range(3):
        (root / f"ordinary-{index}").write_bytes(b"ordinary")
    before = {path.name: path.read_bytes() for path in root.iterdir()}

    monkeypatch.setattr(fsio, "_NATIVE_PUBLICATION_DIRECTORY_MAX_ENTRIES", 4)
    with fsio.openNativeDirectory(root) as directory:
        expected = directory._entry(target.name).identity
        with pytest.raises(
            fsio.NativeDirectoryQuotaExceeded,
            match="directory.*capacity",
        ):
            directory.removeFile(target.name, expected=expected)

    assert {path.name: path.read_bytes() for path in root.iterdir()} == before
    assert not list(root.glob(".galaxy-delete-*"))


def test_posix_delete_directory_capacity_admission_is_cross_process_atomic(
    tmp_path: Path,
) -> None:
    if os.name == "nt":
        return
    root = tmp_path / "root"
    control = tmp_path / "control"
    root.mkdir()
    control.mkdir()
    for name in ("a.lock", "b.lock", "ordinary"):
        (root / name).write_bytes(name.encode("ascii"))
    child = r"""
import os
import sys
import time
from pathlib import Path
from platform_core.core import fsio

root = Path(sys.argv[1])
control = Path(sys.argv[2])
name = sys.argv[3]
fsio._NATIVE_PUBLICATION_DIRECTORY_MAX_ENTRIES = 4
(control / f"{os.getpid()}.ready").write_text("ready", encoding="ascii")
deadline = time.monotonic() + 20
while not (control / "go").exists():
    if time.monotonic() >= deadline:
        raise SystemExit(72)
    time.sleep(0.005)
def crash(phase):
    if phase == "staging-open":
        os._exit(91)
fsio._nativeDeletionCrashPoint = crash
try:
    with fsio.openNativeDirectory(root) as directory:
        expected = directory._entry(name).identity
        directory.removeFile(name, expected=expected)
except fsio.NativeDirectoryQuotaExceeded:
    raise SystemExit(73)
raise SystemExit(74)
"""
    children = [
        subprocess.Popen(
            [sys.executable, "-c", child, str(root), str(control), name],
            cwd=_ROOT,
        )
        for name in ("a.lock", "b.lock")
    ]
    try:
        deadline = time.monotonic() + 20
        while len(list(control.glob("*.ready"))) != 2:
            if time.monotonic() >= deadline:
                raise AssertionError("delete contenders missed readiness")
            time.sleep(0.005)
        (control / "go").write_text("go", encoding="ascii")
        return_codes = sorted(process.wait(timeout=30) for process in children)
    finally:
        for process in children:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    assert return_codes == [73, 91]
    assert len(list(root.iterdir())) == 4
    assert len(list(root.glob(".galaxy-delete-*"))) == 1
    assert (root / "a.lock").exists()
    assert (root / "b.lock").exists()


def test_lock_stale_steal_structural_failure_propagates_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "owned.lock"
    target.write_bytes(b"424242")
    old = time.time() - 7200
    os.utime(target, (old, old))
    before = target.read_bytes()

    def structural_failure(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.ENOTSUP, "qualified deletion unavailable")

    monkeypatch.setattr(
        fsio.NativeDirectoryHandle,
        "_removeFileAdmitted",
        structural_failure,
    )
    with pytest.raises(OSError) as raised:
        fsio.tryAcquireLockLease(target, owner_alive=lambda _pid: False)

    assert raised.value.errno == errno.ENOTSUP
    assert target.read_bytes() == before


def test_native_remove_refuses_multi_link_target_untouched(tmp_path: Path) -> None:
    target = tmp_path / "owned.lock"
    alias = tmp_path / "owned-alias.lock"
    target.write_bytes(b"owner-a")
    os.link(target, alias)

    with fsio.openNativeDirectory(tmp_path) as directory:
        expected = directory._entry(target.name).identity
        with pytest.raises(OSError, match="single-link"):
            directory.removeFile(target.name, expected=expected)

    assert target.read_bytes() == b"owner-a"
    assert alias.read_bytes() == b"owner-a"
    assert os.path.samefile(target, alias)


def test_native_remove_refuses_a_cross_mount_identity_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "owned.lock"
    target.write_bytes(b"owner-a")
    real_entry = fsio.NativeDirectoryHandle._entry

    def report_cross_mount(
        directory: fsio.NativeDirectoryHandle,
        name: str,
    ) -> fsio.NativeDirectoryEntry:
        entry = real_entry(directory, name)
        if name == target.name:
            return replace(
                entry,
                identity=replace(
                    entry.identity,
                    mount_id=entry.identity.mount_id + 1,
                ),
            )
        return entry

    monkeypatch.setattr(
        fsio.NativeDirectoryHandle,
        "_entry",
        report_cross_mount,
    )
    with fsio.openNativeDirectory(tmp_path) as directory:
        with pytest.raises(OSError, match="volume|mount"):
            directory.removeFile(target.name)

    assert target.read_bytes() == b"owner-a"


def test_native_replace_binds_and_revalidates_both_file_identities(
    tmp_path,
    monkeypatch,
):
    (tmp_path / "incoming").write_bytes(b"new")
    (tmp_path / "target").write_bytes(b"old")
    real_entry = fsio.NativeDirectoryHandle._entry

    with fsio.openNativeDirectory(tmp_path) as directory:
        source = real_entry(directory, "incoming").identity
        destination = real_entry(directory, "target").identity
        target_reads = 0

        def report_rebound_publication(observed_directory, name):
            nonlocal target_reads
            entry = real_entry(observed_directory, name)
            if name == "target":
                target_reads += 1
                if target_reads == 2:
                    return replace(
                        entry,
                        identity=replace(
                            entry.identity,
                            file_id=entry.identity.file_id + 1,
                        ),
                    )
            return entry

        monkeypatch.setattr(
            fsio.NativeDirectoryHandle,
            "_entry",
            report_rebound_publication,
        )
        with pytest.raises(OSError, match="published.*identity"):
            directory.replaceFile(
                "incoming",
                "target",
                expected_source=source,
                expected_destination=destination,
            )

    assert target_reads == 2
    assert (tmp_path / "target").read_bytes() == b"new"


@pytest.mark.skipif(os.name != "nt", reason="Windows retained replace boundary")
def test_windows_native_replace_never_overwrites_a_rebound_destination(
    tmp_path,
    monkeypatch,
):
    (tmp_path / "incoming").write_bytes(b"new")
    (tmp_path / "target").write_bytes(b"old")
    real_rename = fsio._winRenameRelative
    raced = False

    def rebind_before_first_rename(source, destination_directory, name, *, replace):
        nonlocal raced
        if not raced:
            raced = True
            os.replace(tmp_path / "target", tmp_path / "attacker-moved")
            (tmp_path / "target").write_bytes(b"intruder")
        return real_rename(
            source,
            destination_directory,
            name,
            replace=replace,
        )

    monkeypatch.setattr(fsio, "_winRenameRelative", rebind_before_first_rename)
    with fsio.openNativeDirectory(tmp_path) as directory:
        source = directory._entry("incoming").identity
        destination = directory._entry("target").identity
        with pytest.raises(OSError):
            directory.replaceFile(
                "incoming",
                "target",
                expected_source=source,
                expected_destination=destination,
            )

    assert raced
    assert (tmp_path / "incoming").read_bytes() == b"new"
    assert (tmp_path / "target").read_bytes() == b"intruder"
    displaced = list(tmp_path.glob(".galaxy-replace-*.old"))
    assert len(displaced) == 1
    assert displaced[0].read_bytes() == b"old"


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable-mode boundary")
def test_native_file_mode_is_applied_through_the_retained_handle(tmp_path):
    with fsio.openNativeDirectory(tmp_path) as directory:
        identity = directory.createFile("program", b"#!/bin/sh\n")
        executable = directory.setFileMode("program", 0o755, expected=identity)
        assert executable.mode & 0o777 == 0o755
        ordinary = directory.setFileMode("program", 0o644, expected=executable)
        assert ordinary.mode & 0o777 == 0o644

    assert (tmp_path / "program").stat().st_mode & 0o777 == 0o644


def test_load_json_missing_is_silent_default(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="core.fsio"):
        assert fsio.loadJson(tmp_path / "nope.json", default={"d": 1}) == {"d": 1}
    assert caplog.records == []                 # missing file: no warning


def test_load_json_corrupt_warns_and_returns_default(tmp_path, caplog):
    p = tmp_path / "bad.json"
    p.write_text("{not json!!!", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="core.fsio"):
        assert fsio.loadJson(p, default=None) is None
    assert any("unreadable" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# fsio: updateJson
# ---------------------------------------------------------------------------

def test_update_json_corrupt_input_preserved_as_bak_with_warning(tmp_path, caplog):
    p = tmp_path / "state.json"
    p.write_text("{torn-mid-write", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="core.fsio"):
        out = fsio.updateJson(p, lambda d: {**d, "runs": 1}, default={})
    assert out == {"runs": 1}
    assert json.loads(p.read_text(encoding="utf-8")) == {"runs": 1}
    bak = tmp_path / "state.json.bak"
    assert bak.read_text(encoding="utf-8") == "{torn-mid-write"   # evidence preserved
    assert any("corrupt JSON preserved" in r.message for r in caplog.records)


def test_update_json_mutate_in_place_and_replacement(tmp_path):
    p = tmp_path / "d.json"

    def bump(d):
        d["n"] = d.get("n", 0) + 1              # in-place (returns None)

    assert fsio.updateJson(p, bump, default={}) == {"n": 1}
    assert fsio.updateJson(p, lambda d: {"n": d["n"] + 10}) == {"n": 11}   # replacement
    assert fsio.loadJson(p) == {"n": 11}


def test_update_json_with_lock_serializes_and_cleans_up(tmp_path):
    p = tmp_path / "locked.json"
    fsio.updateJson(p, lambda d: {"v": 1}, default={}, lock=True)
    assert fsio.loadJson(p) == {"v": 1}
    assert not (tmp_path / "locked.json.lock").exists()   # released after the write


# ---------------------------------------------------------------------------
# fsio: pid locks
# ---------------------------------------------------------------------------

def test_lock_fresh_is_never_stolen(tmp_path):
    lp = tmp_path / "x.lock"
    assert fsio.tryAcquireLock(lp) is True
    assert fsio.tryAcquireLock(lp) is False               # held + fresh -> refused


def test_lock_stale_by_age_is_stolen_after_restat(tmp_path):
    lp = tmp_path / "x.lock"
    lp.write_text("12345", encoding="utf-8")
    old = time.time() - 7200
    os.utime(lp, (old, old))
    assert fsio.tryAcquireLock(lp, stale_after=3600) is True
    assert lp.read_text(encoding="utf-8").strip() == str(os.getpid())   # we own it now


def test_lock_dead_owner_is_stolen_live_owner_is_not(tmp_path):
    lp = tmp_path / "x.lock"
    lp.write_text("999999999", encoding="utf-8")
    lease = fsio.tryAcquireLockLease(
        lp,
        stale_after=3600,
        owner_alive=lambda pid: False,
    )
    assert lease is not None
    fsio.releaseLock(lease)
    lp.write_text(str(os.getpid()), encoding="utf-8")
    assert fsio.tryAcquireLock(lp, stale_after=3600, owner_alive=lambda pid: True) is False


def test_lock_unreadable_owner_is_conservatively_alive(tmp_path):
    lp = tmp_path / "x.lock"
    lp.write_text("garbage-not-a-pid", encoding="utf-8")
    # owner_alive is available but the pid can't be read -> never steal the unprovable.
    assert fsio.tryAcquireLock(lp, stale_after=3600, owner_alive=lambda pid: False) is False


def test_file_lock_context_manager_and_timeout(tmp_path):
    lp = tmp_path / "cm.lock"
    with fsio.fileLock(lp, timeout=2.0):
        assert lp.exists()
        with pytest.raises(TimeoutError):
            with fsio.fileLock(lp, timeout=0.2, poll=0.02):
                pass
    assert not lp.exists()                                # released on exit
    with fsio.fileLock(lp, timeout=2.0):                  # re-acquirable
        pass


def test_file_lock_recovers_its_exact_post_publish_lost_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lp = tmp_path / "lost-response.lock"
    real_reconcile = fsio.NativeDirectoryHandle._reconcileCreateOnlyFileAdmitted
    response_lost = False

    def publish_then_lose_response(
        directory: fsio.NativeDirectoryHandle,
        name: str,
        payload: bytes,
        *,
        accept_existing: bool,
    ) -> fsio.NativeFileIdentity:
        nonlocal response_lost
        identity = real_reconcile(
            directory,
            name,
            payload,
            accept_existing=accept_existing,
        )
        if name == lp.name and not accept_existing and not response_lost:
            response_lost = True
            raise OSError("simulated post-publication lost response")
        return identity

    monkeypatch.setattr(
        fsio.NativeDirectoryHandle,
        "_reconcileCreateOnlyFileAdmitted",
        publish_then_lose_response,
    )

    with fsio.fileLock(lp, timeout=0.2, poll=0.01):
        owner = lp.read_text(encoding="ascii")
        owner_pid, process_start, owner_sequence = owner.split(":")
        assert owner_pid == str(os.getpid())
        assert process_start == fsio._NATIVE_PROCESS_START_TOKEN
        assert len(owner_sequence) == 16

    assert response_lost is True
    assert not lp.exists()


def test_file_lock_reuses_one_unique_owner_across_polls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lp = tmp_path / "poll-owner.lock"
    real_attempt = fsio._tryAcquireLockLease
    observed_payloads: list[bytes] = []

    def delay_first_two_attempts(
        path,
        *,
        stale_after: float,
        owner_alive,
        owner_payload: bytes,
        recover_exact_publication: bool,
    ):
        observed_payloads.append(owner_payload)
        if len(observed_payloads) < 3:
            return None
        return real_attempt(
            path,
            stale_after=stale_after,
            owner_alive=owner_alive,
            owner_payload=owner_payload,
            recover_exact_publication=recover_exact_publication,
        )

    monkeypatch.setattr(fsio, "_tryAcquireLockLease", delay_first_two_attempts)

    with fsio.fileLock(lp, timeout=0.2, poll=0.001):
        first_owner = lp.read_bytes()
    with fsio.fileLock(lp, timeout=0.2, poll=0.001):
        second_owner = lp.read_bytes()

    assert observed_payloads[:3] == [first_owner, first_owner, first_owner]
    assert observed_payloads[3] == second_owner
    assert first_owner != second_owner


def test_file_lock_reaps_only_proven_dead_foreign_owner_publication(
    tmp_path: Path,
) -> None:
    lp = tmp_path / "dead-publication.lock"
    script = r"""
import os
import sys
from pathlib import Path
from platform_core.core import fsio

def die_before_publish(*args, **kwargs):
    os._exit(93)

if os.name == "nt":
    fsio._winRenameRelative = die_before_publish
else:
    fsio._posixRenameNoReplace = die_before_publish
with fsio.fileLock(Path(sys.argv[1]), timeout=1.0):
    raise AssertionError("publication crash hook did not run")
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(lp)],
        cwd=_ROOT,
        check=False,
        timeout=30,
    )

    assert result.returncode == 93
    assert not lp.exists()
    debris = list(tmp_path.glob(".galaxy-publish-*.tmp"))
    assert len(debris) == 1

    with fsio.fileLock(lp, timeout=0.2, poll=0.01):
        assert lp.exists()

    assert not lp.exists()
    assert not debris[0].exists()


def test_file_lock_reclaims_fresh_proven_dead_owner(tmp_path: Path) -> None:
    lp = tmp_path / "dead-owner.lock"
    lp.write_text("999999999", encoding="utf-8")
    observations: list[int] = []

    with fsio.fileLock(
        lp,
        timeout=0.2,
        poll=0.01,
        owner_alive=lambda pid: observations.append(pid) or False,
    ):
        owner_pid, process_start, owner_sequence = lp.read_text(
            encoding="utf-8"
        ).strip().split(":")
        assert owner_pid == str(os.getpid())
        assert process_start == fsio._NATIVE_PROCESS_START_TOKEN
        assert len(owner_sequence) == 16

    assert observations == [999999999]


def test_file_lock_refuses_old_proven_live_owner_until_timeout(
    tmp_path: Path,
) -> None:
    lp = tmp_path / "live-owner.lock"
    lp.write_text(str(os.getpid()), encoding="utf-8")
    old = time.time() - 7200
    os.utime(lp, (old, old))
    observations: list[int] = []

    with pytest.raises(TimeoutError):
        with fsio.fileLock(
            lp,
            timeout=0.05,
            poll=0.01,
            owner_alive=lambda pid: observations.append(pid) or True,
        ):
            pass

    assert observations
    assert set(observations) == {os.getpid()}
    assert lp.read_text(encoding="utf-8").strip() == str(os.getpid())


def test_file_lock_conservatively_refuses_unreadable_unknown_owner(
    tmp_path: Path,
) -> None:
    lp = tmp_path / "unknown-owner.lock"
    lp.write_text("not-a-pid", encoding="utf-8")
    old = time.time() - 7200
    os.utime(lp, (old, old))
    observations: list[int] = []

    with pytest.raises(TimeoutError):
        with fsio.fileLock(
            lp,
            timeout=0.05,
            poll=0.01,
            owner_alive=lambda pid: observations.append(pid) or False,
        ):
            pass

    assert observations == []
    assert lp.read_text(encoding="utf-8") == "not-a-pid"


def test_file_lock_refuses_reclaim_when_owner_liveness_probe_errors(
    tmp_path: Path,
) -> None:
    lp = tmp_path / "probe-error.lock"
    lp.write_text("424242", encoding="utf-8")
    old = time.time() - 7200
    os.utime(lp, (old, old))
    observations: list[int] = []

    def unavailable(pid: int) -> bool:
        observations.append(pid)
        raise RuntimeError("liveness unavailable")

    assert fsio.tryAcquireLock(lp, owner_alive=unavailable) is False
    assert observations == [424242]
    assert lp.read_text(encoding="utf-8") == "424242"


def test_file_lock_owner_a_cannot_unlink_owner_b_successor_or_admit_c(
    tmp_path: Path,
) -> None:
    lp = tmp_path / "successor.lock"

    with fsio.fileLock(lp, timeout=0.2, poll=0.01):
        # Model A's lock being displaced and B winning the next exclusive create.
        lp.unlink()
        lease_b = fsio.tryAcquireLockLease(lp)
        assert lease_b is not None

    # A's delayed context-manager cleanup must target only A's exact object.
    assert lp.exists()
    assert fsio.tryAcquireLockLease(lp) is None
    fsio.releaseLock(lease_b)


def test_path_only_release_cannot_unlink_owner_b_successor_or_admit_c(
    tmp_path: Path,
) -> None:
    lp = tmp_path / "legacy-successor.lock"

    assert fsio.tryAcquireLock(lp) is True
    lp.unlink()
    assert fsio.tryAcquireLock(lp) is True
    owner_b = lp.read_bytes()

    # A retained no identity.  Its delayed path-only release must fail closed:
    # deleting whatever now occupies the name would delete B and admit C.
    with pytest.raises(TypeError, match="exact lock lease"):
        fsio.releaseLock(lp)

    assert lp.read_bytes() == owner_b
    assert fsio.tryAcquireLock(lp) is False


def test_exact_nonblocking_lease_release_preserves_a_successor(
    tmp_path: Path,
) -> None:
    lp = tmp_path / "leased-successor.lock"

    lease_a = fsio.tryAcquireLockLease(lp)
    assert lease_a is not None
    lp.unlink()
    lease_b = fsio.tryAcquireLockLease(lp)
    assert lease_b is not None
    owner_b = lp.read_bytes()

    fsio.releaseLock(lease_a)
    assert lp.read_bytes() == owner_b
    assert fsio.tryAcquireLockLease(lp) is None

    fsio.releaseLock(lease_b)
    assert not lp.exists()


def test_exact_lease_release_retries_a_transient_mutation_fence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lp = tmp_path / "release-fence.lock"
    lease = fsio.tryAcquireLockLease(lp)
    assert lease is not None
    real_remove = fsio.NativeDirectoryHandle.removeFile
    calls = 0

    def busy_once(
        directory: fsio.NativeDirectoryHandle,
        name: str,
        *,
        expected: fsio.NativeFileIdentity | None = None,
    ) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise BlockingIOError(fsio.errno.EBUSY, "mutation fence busy", name)
        real_remove(directory, name, expected=expected)

    monkeypatch.setattr(fsio.NativeDirectoryHandle, "removeFile", busy_once)
    fsio.releaseLock(lease)

    assert calls == 2
    assert not lp.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX deletion-fence contention")
def test_posix_file_lock_release_survives_concurrent_recovery_scans(
    tmp_path: Path,
) -> None:
    lp = tmp_path / "concurrent-release.lock"
    start = threading.Barrier(4)
    errors: list[BaseException] = []
    completed = 0

    def worker() -> None:
        nonlocal completed
        try:
            start.wait(timeout=5)
            for _ in range(20):
                with fsio.fileLock(lp, timeout=3.0, poll=0.0005):
                    completed += 1
        except BaseException as exc:  # noqa: BLE001 - retained cross-thread evidence
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert completed == 80
    assert not lp.exists()
    assert not list(tmp_path.glob(".galaxy-delete-*"))


def test_stale_reclaimer_c_cannot_unlink_b_after_observing_a(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lp = tmp_path / "stale-successor.lock"
    lp.write_text("111111", encoding="utf-8")
    old = time.time() - 7200
    os.utime(lp, (old, old))
    real_remove = fsio.NativeDirectoryHandle._removeFileAdmitted
    replaced = False

    def replace_before_expected_remove(
        directory: fsio.NativeDirectoryHandle,
        name: str,
        *,
        expected: fsio.NativeFileIdentity | None = None,
    ) -> None:
        nonlocal replaced
        if name == lp.name and not replaced:
            replaced = True
            lp.unlink()
            lp.write_text("222222", encoding="utf-8")
        real_remove(directory, name, expected=expected)

    monkeypatch.setattr(
        fsio.NativeDirectoryHandle,
        "_removeFileAdmitted",
        replace_before_expected_remove,
    )

    assert fsio.tryAcquireLock(lp, stale_after=3600) is False
    assert replaced is True
    assert lp.read_text(encoding="utf-8") == "222222"


def test_file_lock_normal_cleanup_allows_exact_reacquire(tmp_path: Path) -> None:
    lp = tmp_path / "reacquire.lock"

    with fsio.fileLock(lp, timeout=0.2, poll=0.01):
        assert lp.exists()
    assert not lp.exists()

    with fsio.fileLock(lp, timeout=0.2, poll=0.01):
        assert lp.exists()
    assert not lp.exists()


# ---------------------------------------------------------------------------
# jsonl_io
# ---------------------------------------------------------------------------

def test_iter_records_torn_tail_keeps_history(tmp_path):
    p = tmp_path / "log.jsonl"
    for i in range(5):
        jsonl_io.appendRecord(p, {"i": i})
    with p.open("a", encoding="utf-8") as fh:
        fh.write('{"i": 5, "torn')                        # crash mid-append
    records, skipped = jsonl_io.iterRecords(p)
    assert [r["i"] for r in records] == [0, 1, 2, 3, 4]   # N-1 records survive
    assert skipped == 1


def test_iter_records_missing_file(tmp_path):
    assert jsonl_io.iterRecords(tmp_path / "nope.jsonl") == ([], 0)


def test_append_record_rotates_past_max_bytes(tmp_path):
    p = tmp_path / "audit.jsonl"
    for i in range(30):
        jsonl_io.appendRecord(p, {"i": i, "pad": "x" * 10}, max_bytes=100)
    assert (tmp_path / "audit.jsonl.1").exists()
    assert jsonl_io.readTail(p, 5)                         # still readable after rotation


def test_read_tail_returns_last_n_oldest_first(tmp_path):
    p = tmp_path / "t.jsonl"
    for i in range(10):
        jsonl_io.appendRecord(p, {"i": i})
    assert [r["i"] for r in jsonl_io.readTail(p, 3)] == [7, 8, 9]
    assert jsonl_io.readTail(tmp_path / "nope.jsonl", 3) == []


# ---------------------------------------------------------------------------
# clock
# ---------------------------------------------------------------------------

def test_now_iso_formats_are_seconds_precision_and_aware():
    utc = clock.nowIsoUtc()
    local = clock.nowIsoLocal()
    assert utc.endswith("+00:00")
    assert datetime.fromisoformat(utc).tzinfo is not None
    assert datetime.fromisoformat(local).tzinfo is not None


def test_parse_iso_and_elapsed_handle_naive_aware_and_garbage():
    assert clock.parseIso(None) is None
    assert clock.parseIso("not-a-date") is None
    aware = (datetime.now().astimezone() - timedelta(seconds=90)).isoformat()
    naive = (datetime.now() - timedelta(seconds=90)).isoformat()
    assert 85 <= clock.elapsedSecondsSince(aware) <= 120
    assert 85 <= clock.elapsedSecondsSince(naive) <= 120   # naive compared in its own frame
    assert clock.elapsedSecondsSince("garbage") == 0.0


def test_fmt_elapsed_and_elapsed_str():
    assert clock.fmtElapsed(42) == "42s"
    assert clock.fmtElapsed(5 * 60) == "5m"
    assert clock.fmtElapsed(2 * 3600 + 15 * 60) == "2h 15m"
    assert clock.fmtElapsed(-3) == "0s"
    assert clock.elapsedStr(None) == "—"
    assert clock.elapsedStr("not-a-date") == "—"
    future = (datetime.now() + timedelta(hours=1)).isoformat()
    assert clock.elapsedStr(future) == "0s"                # clamped, matches dashboard


def test_eta_str_paced_and_unknowable():
    started = (datetime.now().astimezone() - timedelta(minutes=10)).isoformat()
    assert clock.etaStr(started, done=1, total=2).startswith("~")
    assert clock.etaStr(started, done=0, total=5) == "—"
    assert clock.etaStr(started, done=5, total=5) == "—"
    assert clock.etaStr(None, done=1, total=2) == "—"


def test_run_clock_deadline_edges():
    now = datetime.now().astimezone()
    assert clock.RunClock(None).remainingSeconds() is None
    assert clock.RunClock(None).passed() is False
    assert clock.RunClock("garbage").passed() is False
    assert clock.RunClock(now.isoformat()).passed() is True            # exactly-now counts
    future = clock.RunClock((now + timedelta(hours=1)).isoformat())
    assert future.passed() is False
    assert 3500 <= future.remainingSeconds() <= 3600
    assert future.remainingHours() == pytest.approx(1.0, abs=0.05)
    past = clock.RunClock((now - timedelta(minutes=1)).isoformat())
    assert past.passed() is True
    assert past.remainingSeconds() < 0


# ---------------------------------------------------------------------------
# git_io
# ---------------------------------------------------------------------------

def test_run_tool_timeout_kills_hung_child():
    t0 = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        git_io.runTool([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1.5)
    assert time.monotonic() - t0 < 15, "hung child was not bounded by the timeout"


def test_run_git_never_prompts_and_reports_non_repo(tmp_path):
    r = git_io.runGit("rev-parse", "--is-inside-work-tree", cwd=tmp_path, timeout=30)
    assert r.returncode != 0                    # returned (no hang, no prompt), not raised
    ok, reason = git_io.gitPreflight(tmp_path, timeout=30)
    assert ok is False
    assert reason == "not a git repository"


def test_gate_commands_tiers_share_repo_checks_and_return_fresh_copies():
    repo = git_io.gateCommands("repo_checks")
    pre = git_io.gateCommands("pre_pr")
    assert pre[:3] == repo                      # pre_pr = repo checks + the fast suite
    assert len(pre) == len(repo) + 1
    assert "pytest" in " ".join(pre[-1])
    repo[0].append("MUTATED")                   # must not leak into the shared table
    assert git_io.gateCommands("repo_checks")[0][-1] != "MUTATED"
