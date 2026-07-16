"""Inactive-by-default contracts for the installed Windows service host."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "bootstrap" / "galaxy_launcher" / "singularity_service.py"


def test_service_self_test_is_canonical_and_has_no_activation_authority(tmp_path):
    completed = subprocess.run(
        [sys.executable, "-I", "-S", str(SERVICE), "--self-test"],
        cwd=tmp_path,
        env={},
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    receipt = json.loads(completed.stdout)
    assert receipt == {
        "activation_authority": False,
        "accepted_commands": ["interrogate", "shutdown", "stop"],
        "schema": "galaxy.singularity-service-self-test/v1",
        "service_state": "stopped",
    }
