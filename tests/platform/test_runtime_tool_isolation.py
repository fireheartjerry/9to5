"""RED contracts for optional neutral host diagnostics."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def _probe():
    return importlib.import_module("platform_core.execution.neutral_host_probe")


def test_neutral_probe_rejects_relative_or_unpinned_executable_before_runner() -> None:
    mod = _probe()
    calls: list[object] = []
    with pytest.raises(mod.NeutralHostProbeUnavailable):
        mod.runNeutralHostProbe(
            executable=Path("nvidia-smi"),
            expected_digest="",
            argv=("--query-gpu=name",),
            runner=lambda request: calls.append(request),
        )
    assert calls == []


def test_neutral_probe_environment_does_not_inherit_routing_or_credentials(monkeypatch) -> None:
    mod = _probe()
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "goldstone")
    monkeypatch.setenv("GIT_DIR", "C:/canonical/.git")
    environment = mod.buildNeutralProbeEnvironment(system_root="C:/Windows")
    assert environment == {
        "PATH": "C:/Windows/System32",
        "SYSTEMROOT": "C:/Windows",
        "WINDIR": "C:/Windows",
    }
