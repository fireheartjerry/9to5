"""Credentialless POSIX child gate used by the registered process launcher.

The helper is intentionally tiny: the controller creates it in a new session, keeps
the target blocked on an inherited anonymous pipe, persists the process identity, and
then writes one release byte.  EOF or any byte other than the exact release marker is
a refusal; target code is never imported in the gate process.
"""
from __future__ import annotations

import os
import sys


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if len(values) < 3 or values[0] != "--gate-fd" or values[2] != "--":
        return 64
    try:
        gate_fd = int(values[1], 10)
    except ValueError:
        return 64
    target = values[3:]
    if gate_fd < 0 or not target:
        return 64
    try:
        released = os.read(gate_fd, 2)
    finally:
        os.close(gate_fd)
    if released != b"R":
        return 65
    os.execvpe(target[0], target, os.environ)
    return 70  # pragma: no cover - execvpe either replaces the process or raises


if __name__ == "__main__":  # pragma: no branch
    raise SystemExit(main())
