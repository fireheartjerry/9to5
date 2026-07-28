"""Immutable snapshot read broker, planning projection, and boundary inventory.

RUN/TEST: python -m pytest tests/execution/test_pre_execution_isolation.py tests/orchestration/test_planning_projection.py tests/execution/test_deep_boundary_inventory.py
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Iterator, Mapping, TypeVar

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_OID = re.compile(r"^[0-9a-f]{40}$")
_DIAGNOSTIC_SEAL = object()
_OPERATIONS = frozenset({"read", "list", "search", "git_facts", "static_scan"})
_PROCESS_CALLS = frozenset(
    {
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.Popen",
        "subprocess.run",
        "os.popen",
        "os.system",
    }
)
_NETWORK_CALLS = frozenset(
    {
        "aiohttp.ClientSession",
        "http.client.HTTPConnection",
        "http.client.HTTPSConnection",
        "httpx.AsyncClient",
        "httpx.Client",
        "socket.create_connection",
        "socket.getaddrinfo",
        "socket.gethostbyaddr",
        "socket.gethostbyname",
        "socket.socket",
        "urllib.request.urlopen",
        "urllib.request.urlretrieve",
        "websockets.connect",
        "websockets.serve",
    }
)
_NETWORK_PREFIXES = (
    "aiohttp.request",
    "httpx.delete",
    "httpx.get",
    "httpx.head",
    "httpx.patch",
    "httpx.post",
    "httpx.put",
    "httpx.request",
    "requests.delete",
    "requests.get",
    "requests.head",
    "requests.options",
    "requests.patch",
    "requests.post",
    "requests.put",
    "requests.request",
    "requests.Session",
)
_BROWSER_NATIVE_PREFIXES = (
    "async_playwright",
    "pyautogui.",
    "pywinauto.",
    "selenium.webdriver.",
    "sync_playwright",
    "uiautomation.",
    "webdriver.",
    "win32com.client.Dispatch",
)
_FILESYSTEM_OBSERVATIONS = frozenset(
    {"exists", "is_dir", "is_file", "iterdir", "lstat", "stat"}
)
_FILESYSTEM_MUTATIONS = frozenset(
    {"chmod", "mkdir", "rmdir", "touch", "unlink", "write_bytes", "write_text"}
)
_T = TypeVar("_T")
_EXPLICIT_FILESYSTEM_MUTATIONS = frozenset(
    {
        "os.chmod",
        "os.makedirs",
        "os.mkdir",
        "os.remove",
        "os.rename",
        "os.replace",
        "os.rmdir",
        "os.unlink",
        "shutil.copy",
        "shutil.copy2",
        "shutil.copyfile",
        "shutil.copytree",
        "shutil.move",
        "shutil.rmtree",
    }
)


class PreExecutionUnavailable(RuntimeError):
    """Immutable source-plane containment or bounded context is unavailable."""


@contextmanager
def _legacyDiagnosticAccess() -> Iterator[None]:
    """Retain runtime -> path exclusion through one brownfield host effect."""

    from platform_core.app_config.paths import controllerPathsActivationFence
    from platform_core.runtime.controller_state import (
        ControllerStateRefused,
        controllerRuntimeStateAbsentPermit,
    )

    permit = controllerRuntimeStateAbsentPermit()
    try:
        permit.__enter__()
    except ControllerStateRefused as exc:
        raise PreExecutionUnavailable(
            "legacy diagnostic repository access requires an absent runtime"
        ) from exc
    try:
        with controllerPathsActivationFence() as paths_active:
            if paths_active:
                raise PreExecutionUnavailable(
                    "legacy diagnostic repository reads are unavailable"
                )
            yield
    finally:
        permit.__exit__(None, None, None)


def _requireLegacyDiagnosticRead() -> None:
    """Compatibility probe for callers that do not themselves perform I/O."""

    with _legacyDiagnosticAccess():
        return None


def readLegacyText(path: str | Path, *args: object, **kwargs: object) -> str:
    with _legacyDiagnosticAccess():
        return Path(path).read_text(*args, **kwargs)  # type: ignore[arg-type]


def readLegacyBytes(path: str | Path, *args: object, **kwargs: object) -> bytes:
    with _legacyDiagnosticAccess():
        return Path(path).read_bytes(*args, **kwargs)  # type: ignore[arg-type]


@contextmanager
def openLegacyFile(
    path: str | Path,
    *args: object,
    **kwargs: object,
) -> Iterator[Any]:
    with _legacyDiagnosticAccess():
        with Path(path).open(*args, **kwargs) as handle:  # type: ignore[call-overload]
            yield handle


@contextmanager
def openLegacyBuiltin(
    path: object,
    *args: object,
    **kwargs: object,
) -> Iterator[Any]:
    with _legacyDiagnosticAccess():
        with open(path, *args, **kwargs) as handle:  # type: ignore[call-overload]
            yield handle


@contextmanager
def openLegacyTar(
    path: str | Path,
    *args: object,
    **kwargs: object,
) -> Iterator[Any]:
    import tarfile

    with _legacyDiagnosticAccess():
        with tarfile.open(path, *args, **kwargs) as handle:  # type: ignore[call-overload]
            yield handle


def globLegacy(root: str | Path, pattern: str) -> tuple[Path, ...]:
    with _legacyDiagnosticAccess():
        return tuple(Path(root).glob(pattern))


def rglobLegacy(root: str | Path, pattern: str) -> tuple[Path, ...]:
    with _legacyDiagnosticAccess():
        return tuple(Path(root).rglob(pattern))


def globPatternLegacy(pattern: str, *, recursive: bool = False) -> tuple[str, ...]:
    import glob

    with _legacyDiagnosticAccess():
        return tuple(glob.glob(pattern, recursive=recursive))


def observeLegacyPath(
    operation: Callable[..., _T],
    *args: object,
    **kwargs: object,
) -> _T:
    """Run one brownfield host-path observation only before capsule install."""

    with _legacyDiagnosticAccess():
        return operation(*args, **kwargs)


def mutateLegacyPath(
    operation: Callable[..., _T],
    *args: object,
    **kwargs: object,
) -> _T:
    """Run one brownfield host-path mutation only before capsule install."""

    with _legacyDiagnosticAccess():
        return operation(*args, **kwargs)


def iterdirLegacy(root: str | Path) -> tuple[Path, ...]:
    with _legacyDiagnosticAccess():
        return tuple(Path(root).iterdir())


def walkLegacy(
    root: str | Path,
    *args: object,
    **kwargs: object,
) -> Any:
    def retained_walk() -> Iterator[tuple[str, list[str], list[str]]]:
        with _legacyDiagnosticAccess():
            yield from os.walk(root, *args, **kwargs)  # type: ignore[arg-type]

    return retained_walk()


def _time(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise PreExecutionUnavailable("pre-execution authority expiry is invalid") from exc
    if result.tzinfo is None:
        raise PreExecutionUnavailable("pre-execution authority expiry is not absolute")
    return result.astimezone(timezone.utc)


def _root(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise PreExecutionUnavailable("snapshot root must be absolute")
    try:
        return path.resolve(strict=False)
    except OSError as exc:
        raise PreExecutionUnavailable("snapshot root cannot be normalized") from exc


def _relative(value: str) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise PreExecutionUnavailable("snapshot path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or re.match(r"^[A-Za-z]:", value):
        raise PreExecutionUnavailable("snapshot path must be repo-relative")
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise PreExecutionUnavailable("snapshot path traverses")
    return tuple(path.parts)


def _is_reparse(info: os.stat_result) -> bool:
    return bool(getattr(info, "st_file_attributes", 0) & 0x400)


@dataclass(frozen=True, slots=True)
class PreExecutionSnapshotAuthority:
    snapshot_root: str
    base_revision: str
    manifest_digest: str
    controller_generation: int
    expires_at: str
    _process_capability: object
    _seal: object


def issueDiagnosticPreExecutionSnapshotAuthority(
    *,
    snapshot_root: str | Path,
    base_revision: str,
    manifest_digest: str,
    controller_generation: int,
    process_capability: object,
    expires_at: str,
) -> PreExecutionSnapshotAuthority:
    if not _OID.fullmatch(base_revision) or not _DIGEST.fullmatch(manifest_digest):
        raise PreExecutionUnavailable("snapshot authority revision or manifest is invalid")
    if type(controller_generation) is not int or controller_generation < 1 or process_capability is None:
        raise PreExecutionUnavailable("snapshot authority generation or process capability is invalid")
    if _time(expires_at) <= datetime.now(timezone.utc):
        raise PreExecutionUnavailable("snapshot authority already expired")
    return PreExecutionSnapshotAuthority(
        snapshot_root=str(_root(snapshot_root)),
        base_revision=base_revision,
        manifest_digest=manifest_digest,
        controller_generation=controller_generation,
        expires_at=expires_at,
        _process_capability=process_capability,
        _seal=_DIAGNOSTIC_SEAL,
    )


class PreExecutionReadBroker:
    """Read/list/search immutable snapshot bytes without execution authority."""

    operations = _OPERATIONS

    def __init__(
        self,
        *,
        snapshot_root: str | Path,
        authority: object,
        max_read_bytes: int,
        max_entries: int,
    ) -> None:
        if type(max_read_bytes) is not int or not (0 < max_read_bytes <= 16 * 1024 * 1024):
            raise PreExecutionUnavailable("snapshot read quota is invalid")
        if type(max_entries) is not int or not (0 < max_entries <= 1_000_000):
            raise PreExecutionUnavailable("snapshot entry quota is invalid")
        self._snapshot_root_input = Path(snapshot_root)
        self._authority = authority
        self._max_read_bytes = max_read_bytes
        self._max_entries = max_entries

    def _validate(self) -> tuple[Path, PreExecutionSnapshotAuthority]:
        authority = self._authority
        if type(authority) is not PreExecutionSnapshotAuthority:
            raise PreExecutionUnavailable("exact pre-execution snapshot authority is required")
        assert isinstance(authority, PreExecutionSnapshotAuthority)
        if authority._seal is not _DIAGNOSTIC_SEAL or authority._process_capability is None:
            raise PreExecutionUnavailable("snapshot authority issuer differs")
        root = _root(self._snapshot_root_input)
        if authority.snapshot_root != str(root):
            raise PreExecutionUnavailable("snapshot authority root differs")
        if _time(authority.expires_at) <= datetime.now(timezone.utc):
            raise PreExecutionUnavailable("snapshot authority expired")
        try:
            info = root.lstat()
        except OSError as exc:
            raise PreExecutionUnavailable("snapshot root is unavailable") from exc
        if root.is_symlink() or _is_reparse(info) or not root.is_dir():
            raise PreExecutionUnavailable("snapshot root identity is unsafe")
        return root, authority

    def _path(self, logical_path: str) -> Path:
        root, _ = self._validate()
        parts = _relative(logical_path)
        current = root
        for index, part in enumerate(parts):
            current = current / part
            try:
                info = current.lstat()
            except OSError as exc:
                raise PreExecutionUnavailable("snapshot path is unavailable") from exc
            if current.is_symlink() or _is_reparse(info):
                raise PreExecutionUnavailable("snapshot path traverses a link or reparse point")
            if index < len(parts) - 1 and not current.is_dir():
                raise PreExecutionUnavailable("snapshot path ancestor is not a directory")
        return current

    def read(self, logical_path: str) -> bytes:
        path = self._path(logical_path)
        try:
            before = path.lstat()
            if not path.is_file() or before.st_nlink != 1 or before.st_size > self._max_read_bytes:
                raise PreExecutionUnavailable("snapshot file type or size is outside policy")
            with path.open("rb") as stream:
                payload = stream.read(self._max_read_bytes + 1)
            after = path.lstat()
        except OSError as exc:
            raise PreExecutionUnavailable("snapshot file cannot be read safely") from exc
        if len(payload) > self._max_read_bytes:
            raise PreExecutionUnavailable("snapshot read exceeds its quota")
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise PreExecutionUnavailable("snapshot file raced during read")
        return payload

    def list(self, logical_path: str = "") -> tuple[str, ...]:
        root, _ = self._validate()
        path = root if not logical_path else self._path(logical_path)
        if not path.is_dir():
            raise PreExecutionUnavailable("snapshot list target is not a directory")
        try:
            entries = tuple(sorted(path.iterdir(), key=lambda item: item.name))
        except OSError as exc:
            raise PreExecutionUnavailable("snapshot directory cannot be listed") from exc
        if len(entries) > self._max_entries:
            raise PreExecutionUnavailable("snapshot directory exceeds its entry quota")
        result: list[str] = []
        for entry in entries:
            info = entry.lstat()
            if entry.is_symlink() or _is_reparse(info):
                raise PreExecutionUnavailable("snapshot directory contains a link or reparse point")
            result.append(entry.name)
        return tuple(result)


def normalizePlanningProjection(value: object) -> dict[str, object]:
    """Return canonical repo-relative planning facts or fail closed."""

    if not isinstance(value, Mapping):
        raise PreExecutionUnavailable("planning projection must be a mapping")
    result: dict[str, object] = {}
    for key, raw in value.items():
        if not isinstance(key, str) or not isinstance(raw, list):
            raise PreExecutionUnavailable("planning projection shape is invalid")
        normalized: list[str] = []
        for item in raw:
            if not isinstance(item, str):
                raise PreExecutionUnavailable("planning projection value is not text")
            if key == "verify_targets":
                if re.search(r"(?:^|\s)(?:[A-Za-z]:[\\/]|/|\\\\)", item):
                    raise PreExecutionUnavailable("verify target contains an absolute path")
                normalized.append(item)
            else:
                normalized.append("/".join(_relative(item)))
        result[key] = normalized
    return result


@dataclass(frozen=True, slots=True)
class PreExecutionContextReceipt:
    base_revision: str
    snapshot_digest: str
    spec_digest: str
    facts_digest: str
    canonical_bytes: bytes

    @classmethod
    def create(
        cls,
        *,
        base_revision: str,
        snapshot_digest: str,
        spec_digest: str,
        facts: Mapping[str, object],
        max_bytes: int,
    ) -> "PreExecutionContextReceipt":
        if not _OID.fullmatch(base_revision) or not _DIGEST.fullmatch(snapshot_digest) or not _DIGEST.fullmatch(spec_digest):
            raise PreExecutionUnavailable("context receipt binding is invalid")
        normalized = normalizePlanningProjection(facts)
        raw = json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        if type(max_bytes) is not int or max_bytes <= 0 or len(raw) > max_bytes:
            raise PreExecutionUnavailable("context receipt exceeds its quota")
        return cls(
            base_revision=base_revision,
            snapshot_digest=snapshot_digest,
            spec_digest=spec_digest,
            facts_digest=hashlib.sha256(raw).hexdigest(),
            canonical_bytes=raw,
        )


@dataclass(frozen=True, slots=True)
class BoundaryFinding:
    path: str
    line: int
    category: str
    expression: str


def _expression_name(value: ast.expr) -> str:
    if isinstance(value, ast.Call):
        return _expression_name(value.func)
    if isinstance(value, ast.Subscript):
        return _expression_name(value.value)
    if isinstance(value, ast.Name):
        return value.id
    if not isinstance(value, ast.Attribute):
        return ""
    parts: list[str] = []
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    elif isinstance(value, (ast.Call, ast.Subscript)):
        base = _expression_name(value)
        if base:
            parts.append(base)
    return ".".join(reversed(parts))


def _call_name(node: ast.Call) -> str:
    return _expression_name(node.func)


def _openCategory(node: ast.Call, name: str) -> str:
    if name == "self.open" or not (name == "open" or name.endswith(".open")):
        return ""
    mode_index = 1 if name == "open" else 0
    mode_node: ast.expr | None = None
    if len(node.args) > mode_index:
        mode_node = node.args[mode_index]
    for keyword in node.keywords:
        if keyword.arg == "mode":
            mode_node = keyword.value
    if isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str):
        if any(marker in mode_node.value for marker in "wax+"):
            return "raw_filesystem_mutation"
        return "raw_repository_read"
    # An omitted mode is read-only. A dynamic mode is not evidence of read-only
    # behavior, so force it through the mutation boundary.
    return "raw_repository_read" if mode_node is None else "raw_filesystem_mutation"


def _looksLikePathReceiver(name: str) -> bool:
    receiver = name.rpartition(".")[0].rpartition(".")[2].casefold()
    return receiver in {
        "d",
        "destination",
        "dst",
        "f",
        "file",
        "p",
        "parent",
        "path",
        "root",
        "source",
        "src",
        "target",
        "temp",
        "tmp",
        "workspace",
    } or receiver.endswith(("_dir", "_file", "_path", "_root"))


def _isDirectSelfMethod(name: str) -> bool:
    return name.startswith("self.") and name.count(".") == 1


def _boundaryCategories(node: ast.Call) -> frozenset[str]:
    name = _call_name(node)
    leaf = name.rpartition(".")[2]
    categories: set[str] = set()
    if name in {"ollama.Client", "ollama.chat"}:
        categories.add("raw_local_model")
    if name in _PROCESS_CALLS:
        categories.add("repository_process")
    if name in _NETWORK_CALLS or name.startswith(_NETWORK_PREFIXES):
        categories.add("raw_network")
    if name.startswith(_BROWSER_NATIVE_PREFIXES):
        categories.add("raw_browser_native")

    open_category = _openCategory(node, name)
    if open_category:
        categories.add(open_category)
    if (
        name in {"read_text", "read_bytes", "glob", "rglob"}
        or name.endswith((".read_text", ".read_bytes", ".glob", ".rglob"))
    ):
        categories.add("raw_repository_read")
    if (
        (leaf in _FILESYSTEM_OBSERVATIONS and not _isDirectSelfMethod(name))
        or name
        in {
            "os.listdir",
            "os.lstat",
            "os.path.exists",
            "os.path.getsize",
            "os.path.isdir",
            "os.path.isfile",
            "os.path.lexists",
            "os.scandir",
            "os.stat",
            "os.walk",
        }
    ):
        categories.add("raw_filesystem_observation")
    if (
        name in _EXPLICIT_FILESYSTEM_MUTATIONS
        or (leaf in _FILESYSTEM_MUTATIONS and not _isDirectSelfMethod(name))
        or (leaf in {"rename", "replace"} and _looksLikePathReceiver(name))
    ):
        categories.add("raw_filesystem_mutation")

    lowered = name.casefold()
    if (
        name.endswith(".send_message")
        and "interaction.response" in lowered
    ) or (
        name.endswith(".send")
        and any(
            marker in lowered
            for marker in (
                "channel",
                "discord",
                "interaction.followup",
                "message.channel",
                "webhook",
            )
        )
    ):
        categories.add("raw_effect")
    return frozenset(categories)


def auditProductionBoundaries(
    paths: Iterable[Path],
    *,
    allowed_boundaries: Mapping[str, frozenset[str]],
) -> tuple[BoundaryFinding, ...]:
    """Enumerate unbrokered provider, process, host I/O, and effect calls."""

    findings: list[BoundaryFinding] = []
    for source in sorted(Path(path) for path in paths):
        normalized = source.as_posix()
        try:
            text = source.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(source))
        except (OSError, UnicodeError, SyntaxError):
            findings.append(BoundaryFinding(normalized, 0, "unparseable", ""))
            continue
        allowed = allowed_boundaries.get(normalized, frozenset())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            for category in _boundaryCategories(node):
                if category in allowed:
                    continue
                findings.append(
                    BoundaryFinding(normalized, getattr(node, "lineno", 0), category, name)
                )
    return tuple(sorted(findings, key=lambda item: (item.path, item.line, item.category)))


def task3ProductionInventory(root: Path) -> tuple[Path, ...]:
    from tools.galaxy_plan_manifest import parse_plan, select_paths

    plan = root / "docs/superpowers/plans/2026-07-13-galaxy-r3-transactional-kernel.md"
    tasks = parse_plan(plan.read_text(encoding="utf-8"), through=3)
    return tuple(root / path for path in select_paths(tasks, (3,), "production-python"))


def reviewedTask3BoundaryAllowlist(root: Path) -> dict[str, frozenset[str]]:
    """Small reviewed kernel boundary set; orchestration callers receive no waiver."""

    relative = {
        "platform_core/execution/backends/clone.py": {"repository_process"},
        "platform_core/execution/credential_broker.py": {
            "raw_filesystem_mutation"
        },
        "platform_core/execution/local_model_broker.py": {"raw_local_model"},
        "platform_core/execution/pre_execution.py": {
            "raw_filesystem_mutation",
            "raw_filesystem_observation",
            "raw_repository_read",
        },
        "platform_core/execution/neutral_host_probe.py": {
            "raw_filesystem_observation",
            "raw_repository_read",
        },
        "platform_core/execution/runtime_projection.py": {
            "raw_filesystem_mutation",
            "raw_filesystem_observation",
        },
        "platform_core/execution/sandbox_broker.py": {
            "raw_filesystem_observation",
            "repository_process",
        },
        "platform_core/execution/source_acquisition.py": {"raw_network"},
        "platform_core/runtime/attempt_journal.py": {
            "raw_filesystem_mutation"
        },
        "platform_core/runtime/candidate.py": {
            "raw_filesystem_mutation",
            "raw_filesystem_observation",
            "raw_repository_read",
        },
        "platform_core/runtime/controller_state.py": {
            "raw_filesystem_mutation",
            "raw_filesystem_observation",
            "raw_repository_read",
        },
        "platform_core/runtime/effect_guard.py": {"raw_network"},
        "platform_core/runtime/legacy_state_migration.py": {
            "raw_filesystem_observation",
            "raw_repository_read",
        },
        "platform_core/runtime/operator_launch.py": {
            "raw_filesystem_mutation",
            "raw_repository_read",
        },
        "platform_core/runtime/receipts.py": {"raw_filesystem_mutation"},
        "containers/galaxy/state_store_entrypoint.py": {
            "raw_filesystem_mutation"
        },
    }
    return {
        (root / path).as_posix(): frozenset(categories)
        for path, categories in relative.items()
    }


__all__ = [
    "BoundaryFinding",
    "PreExecutionContextReceipt",
    "PreExecutionReadBroker",
    "PreExecutionSnapshotAuthority",
    "PreExecutionUnavailable",
    "auditProductionBoundaries",
    "globLegacy",
    "globPatternLegacy",
    "issueDiagnosticPreExecutionSnapshotAuthority",
    "iterdirLegacy",
    "mutateLegacyPath",
    "normalizePlanningProjection",
    "openLegacyBuiltin",
    "openLegacyFile",
    "openLegacyTar",
    "readLegacyBytes",
    "readLegacyText",
    "observeLegacyPath",
    "reviewedTask3BoundaryAllowlist",
    "rglobLegacy",
    "task3ProductionInventory",
    "walkLegacy",
]
