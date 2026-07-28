"""Windows blocked-child gate for one registered no-breakaway Job Object.

The controller starts this trusted helper with a private inherited release handle.
Before release it cannot create target code.  Once assigned to the registered Job,
its target child joins that same no-breakaway Job atomically by Windows inheritance.
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
from ctypes import wintypes


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if len(values) < 4 or values[0] != "--gate-handle" or values[2] != "--":
        return 64
    try:
        gate_handle = int(values[1], 10)
    except ValueError:
        return 64
    target = values[3:]
    if gate_handle <= 0 or not target:
        return 64
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.ReadFile.argtypes = (
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    )
    kernel32.ReadFile.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    marker = ctypes.create_string_buffer(2)
    observed = wintypes.DWORD()
    accepted = kernel32.ReadFile(
        gate_handle, marker, 2, ctypes.byref(observed), None
    )
    kernel32.CloseHandle(gate_handle)
    if not accepted:
        return 65
    if observed.value != 1 or marker.raw[:1] != b"R":
        return 65
    child = subprocess.Popen(target, close_fds=True)
    return child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
