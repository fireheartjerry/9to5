"""RED subprocess contracts for the external intentionally inactive capsule."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "bootstrap" / "galaxy_launcher" / "__main__.py"
DEVELOPER_REDIRECT = (
    ROOT / "bootstrap" / "galaxy_launcher" / "developer_redirect.ps1"
)


def _require_capsule_entrypoint() -> None:
    assert ENTRY.is_file(), (
        "external inactive capsule entrypoint is not implemented: "
        f"{ENTRY}"
    )


def test_capsule_runs_isolated_from_poisoned_target_and_refuses_before_target_import(tmp_path):
    _require_capsule_entrypoint()
    poison = tmp_path / "poison"
    poison.mkdir()
    goldstone = tmp_path / "executed"
    for name in ("sitecustomize.py", "usercustomize.py", "main.py"):
        (poison / name).write_text(f"open(r'{goldstone}','w').write('{name}')", encoding="utf-8")
    env = {"PYTHONPATH": str(poison), "PYTHONSTARTUP": str(poison / "main.py"),
           "GALAXY_ACTIVE": "1", "PATH": ""}
    cp = subprocess.run([sys.executable, "-I", "-S", str(ENTRY), "run"], cwd=poison,
                        env=env, text=True, capture_output=True, timeout=15)
    assert cp.returncode != 0, (
        f"inactive capsule unexpectedly succeeded\nstdout={cp.stdout}\nstderr={cp.stderr}")
    result = json.loads(cp.stdout)
    assert result["error_type"] == "TransactionalKernelInactive"
    assert result["target_imported"] is False
    assert not goldstone.exists()


def test_direct_checkout_invocation_without_boot_capability_refuses(tmp_path):
    _require_capsule_entrypoint()
    cp = subprocess.run([sys.executable, str(ENTRY), "run", "--target", str(ROOT)],
                        cwd=ROOT, env={}, text=True, capture_output=True, timeout=15)
    assert cp.returncode != 0, (
        f"direct invocation unexpectedly succeeded\nstdout={cp.stdout}\nstderr={cp.stderr}")
    assert json.loads(cp.stdout)["error_type"] == "BootCapabilityUnavailable"


def test_developer_redirect_is_request_only_and_has_no_checkout_fallback(tmp_path):
    powershell = shutil.which("powershell.exe")
    assert powershell and DEVELOPER_REDIRECT.is_file()
    source = DEVELOPER_REDIRECT.read_text(encoding="utf-8")
    for forbidden in ("main.py", "run.ps1", "$PROFILE", "C:\\9to5"):
        assert forbidden.casefold() not in source.casefold()
    cp = subprocess.run(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(DEVELOPER_REDIRECT),
            "-SelfTestContract",
        ],
        cwd=tmp_path,
        env={"SystemRoot": os.environ["SystemRoot"], "WINDIR": os.environ["WINDIR"]},
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert cp.returncode == 0, f"stdout={cp.stdout}\nstderr={cp.stderr}"
    contract = json.loads(cp.stdout)
    assert contract == {
        "activation_authority": False,
        "checkout_fallback": False,
        "client_flags": [
            "--request-only",
            "--require-server-validated-client-digest",
        ],
        "fresh_host_flags": ["-NoLogo", "-NoProfile", "-NonInteractive"],
        "schema": "galaxy.developer-redirect/v1",
    }
