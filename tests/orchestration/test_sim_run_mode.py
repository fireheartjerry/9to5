"""Tests for the token-light --sim-run mode.

--sim-run runs the FULL orchestrator lifecycle over the live surfaces (Discord/web
stay whatever config says) but swaps brain/executor/replan/review for the zero-API
simulation doubles, so the bot can be exercised end-to-end for free. The launcher and
CLI must thread the flag through, and the built orchestrator must carry the sim doubles.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from notifications import work_launcher
from platform_core.cli.main_cli import _parseArgs


def test_cli_parses_sim_run_flag():
    args = _parseArgs(["--goal", "x", "--sim-run"])
    assert args.sim_run is True
    args2 = _parseArgs(["--goal", "x"])
    assert args2.sim_run is False


def test_buildargv_appends_sim_run_only_when_requested():
    base = work_launcher.WorkRequest(goal="demo", hours=1.0)
    assert "--sim-run" not in work_launcher.buildArgv(base)
    simmed = work_launcher.WorkRequest(goal="demo", hours=1.0, sim=True)
    assert "--sim-run" in work_launcher.buildArgv(simmed)


def test_build_run_orchestrator_uses_sim_doubles_under_sim_run():
    import main
    import platform_core.simulator.simulation as simulation

    class _Args:
        sim_run = True

    orch = main._buildRunOrchestrator(_Args())
    # SimBrain / simRunClaude are wired in — no real ollama.Client / claude subprocess.
    assert isinstance(orch.ollama, simulation.SimBrain)
    assert orch._run_claude is simulation.simRunClaude


def test_build_run_orchestrator_defaults_to_real_orchestrator():
    import main
    import platform_core.simulator.simulation as simulation

    class _Args:
        sim_run = False

    orch = main._buildRunOrchestrator(_Args())
    assert not isinstance(getattr(orch, "ollama", None), simulation.SimBrain)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
