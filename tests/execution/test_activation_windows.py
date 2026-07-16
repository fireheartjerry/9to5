"""OS-native containment checks for sealed activation probe children."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import importlib
from pathlib import Path
import sys

import psutil


def _module():
    return importlib.import_module("bootstrap.galaxy_launcher.activation_windows")


def _token_is_restricted(process_id: int) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    advapi32.OpenProcessToken.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    )
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.IsTokenRestricted.argtypes = (wintypes.HANDLE,)
    advapi32.IsTokenRestricted.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    process = kernel32.OpenProcess(0x1000, False, process_id)
    assert process
    token = wintypes.HANDLE()
    try:
        assert advapi32.OpenProcessToken(process, 0x0008, ctypes.byref(token))
        return bool(advapi32.IsTokenRestricted(token))
    finally:
        if token:
            kernel32.CloseHandle(token)
        kernel32.CloseHandle(process)


def test_restricted_child_is_suspended_empty_and_os_restricted(tmp_path):
    mod = _module()
    empty = tmp_path / "empty"
    empty.mkdir()
    child = mod.create_restricted_process(
        [sys.executable, "-I", "-S", "-c", "import time;time.sleep(30)"],
        cwd=empty,
        environment={},
        suspended=True,
    )
    try:
        process = psutil.Process(child.process_id)
        assert _token_is_restricted(child.process_id)
        assert Path(process.cwd()).resolve() == empty.resolve()
        assert not {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"} & set(process.environ())
        child.resume()
        assert process.is_running()
    finally:
        child.terminate()
        child.close()
