# epoch.py
"""Primitive 2 -- the epoch pin. An immutable per-run snapshot of governing config +
a self.code bytecode fingerprint, written into task meta. Pins "the running self is the
imported bytecode + start-of-run config, full stop." See spec."""
from __future__ import annotations

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
        files[path.lower()] = hashlib.sha256(data).hexdigest()
    return {"git_sha": _gitSha(), "files": files}
