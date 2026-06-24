# epoch.py
"""Primitive 2 -- the epoch pin. An immutable per-run snapshot of governing config +
a self.code bytecode fingerprint, written into task meta. Pins "the running self is the
imported bytecode + start-of-run config, full stop." See spec."""
from __future__ import annotations

import copy
import hashlib
import subprocess
from dataclasses import dataclass
from typing import Any, Optional

import identity


def _gitSha() -> Optional[str]:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(identity.PROJECT_ROOT),
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


def fingerprint() -> dict[str, Any]:
    """A content hash of every self.code module + the git SHA. Two runs with identical
    loop code produce identical fingerprints; any edit flips one file's hash."""
    files: dict[str, str] = {}
    for path in identity.selfCodeFiles():
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            data = b""
        files[str(path).lower()] = hashlib.sha256(data).hexdigest()
    return {"git_sha": _gitSha(), "files": files}


import config  # noqa: E402 -- intentional late import to avoid circular deps

# The config constants whose values govern a run and must be pinned (the hook + loop read
# these from the epoch, never a live re-import). Mirrors config.SIE_TUNABLE_KNOBS + flags.
_PINNED_KNOBS: tuple[str, ...] = (
    "MAX_SUBTASK_ATTEMPTS", "RETRIEVAL_K", "ADVERSARY_HEARTBEAT_EVERY",
    "PROMPT_PROMOTE_MIN_USES", "CONFIDENCE_DEFER_THRESHOLD", "SELFMOD_ALLOW_CORE",
)


@dataclass(frozen=True)
class Epoch:
    config_knobs: dict[str, Any]
    universe: dict[str, Any]
    brain_tag: Optional[str]
    code: dict[str, Any]            # the fingerprint()
    core_protected_files: tuple     # pinned CORE_PROTECTED_FILES (so a mid-run edit cannot change it)

    def toDict(self) -> dict[str, Any]:
        return {"config_knobs": dict(self.config_knobs),
                "universe": copy.deepcopy(self.universe),
                "brain_tag": self.brain_tag,
                "code": copy.deepcopy(self.code),
                "core_protected_files": list(self.core_protected_files)}

    @classmethod
    def fromDict(cls, d: dict[str, Any]) -> "Epoch":
        return cls(config_knobs=dict(d.get("config_knobs") or {}),
                   universe=dict(d.get("universe") or {}),
                   brain_tag=d.get("brain_tag"), code=d.get("code") or {},
                   core_protected_files=tuple(d.get("core_protected_files") or []))


def snapshot(*, universe: Optional[dict] = None, brain_tag: Optional[str] = None) -> Epoch:
    """Freeze governing state at process/run start. Deep-copies values so later mutation
    of config or the universe dict cannot change what was pinned."""
    knobs = {k: getattr(config, k, None) for k in _PINNED_KNOBS}
    uni = dict(universe or {})
    uni["hard_boundaries"] = list(uni.get("hard_boundaries") or [])
    core_files = tuple(getattr(config, "CORE_PROTECTED_FILES", ()) or ())
    return Epoch(config_knobs=knobs, universe=uni, brain_tag=brain_tag, code=fingerprint(),
                 core_protected_files=core_files)


def diverged(pinned: Epoch) -> bool:
    """True iff the on-disk self.code differs from what was pinned at snapshot time."""
    return fingerprint()["files"] != pinned.code.get("files", {})
