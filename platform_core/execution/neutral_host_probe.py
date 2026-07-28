"""Closed optional host diagnostic boundary.

The controller supplies an absolute digest-pinned executable and an injected
runner.  This module does not search PATH or inherit the ambient environment.

RUN/TEST: python -m pytest tests/platform/test_runtime_tool_isolation.py
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, TypeVar

from platform_core.core.fsio import readNoFollowBytes

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_T = TypeVar("_T")


class NeutralHostProbeUnavailable(RuntimeError):
    """A neutral diagnostic cannot prove its exact closed execution facts."""


@dataclass(frozen=True, slots=True)
class NeutralHostProbeRequest:
    executable: str
    argv: tuple[str, ...]
    cwd: str
    environment: Mapping[str, str]
    timeout_seconds: float = 5.0
    max_output_bytes: int = 65_536


def buildNeutralProbeEnvironment(*, system_root: str) -> dict[str, str]:
    """Build the minimal Windows diagnostic environment without ambient reads."""

    if not isinstance(system_root, str) or not system_root or "\x00" in system_root:
        raise NeutralHostProbeUnavailable("system_root is invalid")
    root = system_root.rstrip("/\\")
    if not root:
        raise NeutralHostProbeUnavailable("system_root is invalid")
    separator = "/" if "/" in root and "\\" not in root else "\\"
    return {
        "PATH": f"{root}{separator}System32",
        "SYSTEMROOT": root,
        "WINDIR": root,
    }


def _default_environment(executable: Path) -> dict[str, str]:
    if os.name == "nt":
        drive = executable.drive or "C:"
        return buildNeutralProbeEnvironment(system_root=f"{drive}\\Windows")
    return {"HOME": "/nonexistent", "LANG": "C.UTF-8", "PATH": "/usr/bin:/bin"}


def runNeutralHostProbe(
    *,
    executable: Path,
    expected_digest: str,
    argv: tuple[str, ...],
    runner: Callable[[NeutralHostProbeRequest], _T],
) -> _T:
    """Validate the pinned tool and submit one bounded request to ``runner``."""

    if type(executable) is not Path or not executable.is_absolute():
        raise NeutralHostProbeUnavailable("probe executable must be an absolute Path")
    if not _DIGEST.fullmatch(expected_digest):
        raise NeutralHostProbeUnavailable("probe executable digest is invalid")
    if any(not isinstance(value, str) or not value or "\x00" in value for value in argv):
        raise NeutralHostProbeUnavailable("probe argv is invalid")
    try:
        info = executable.lstat()
    except OSError as exc:
        raise NeutralHostProbeUnavailable("probe executable is unavailable") from exc
    if executable.is_symlink() or not executable.is_file() or info.st_nlink != 1:
        raise NeutralHostProbeUnavailable("probe executable identity is unsafe")
    raw = readNoFollowBytes(executable, max_bytes=64 * 1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != expected_digest:
        raise NeutralHostProbeUnavailable("probe executable digest differs")
    with tempfile.TemporaryDirectory(prefix="galaxy-neutral-probe-") as temporary:
        request = NeutralHostProbeRequest(
            executable=str(executable),
            argv=(str(executable), *argv),
            cwd=temporary,
            environment=_default_environment(executable),
        )
        return runner(request)


__all__ = [
    "NeutralHostProbeRequest",
    "NeutralHostProbeUnavailable",
    "buildNeutralProbeEnvironment",
    "runNeutralHostProbe",
]
