"""RED integration contract for prefix-scoped headers-only repo-map mode."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_headers_only_prefix_isolated_check_is_idempotent():
    listed = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
    ).decode("utf-8").split("\0")
    protected = [
        ROOT / relative
        for relative in listed
        if relative
        and not relative.replace("\\", "/").startswith("bootstrap/galaxy_launcher/")
        and (ROOT / relative).is_file()
    ]
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in protected}
    command = [sys.executable, "tools/repo_map.py", "--headers-only", "--only",
               "bootstrap/galaxy_launcher"]
    first = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert first.returncode == 0, first.stderr
    check = subprocess.run([*command, "--check"], cwd=ROOT, text=True, capture_output=True)
    assert check.returncode == 0, check.stderr
    global_check = subprocess.run(
        [sys.executable, "tools/repo_map.py", "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert global_check.returncode == 0, global_check.stderr
    first_trust = {path: path.read_bytes() for path in
                   (ROOT / "bootstrap" / "galaxy_launcher").rglob("*") if path.is_file()}
    second = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert second.returncode == 0, second.stderr
    second_trust = {path: path.read_bytes() for path in first_trust}
    assert first_trust == second_trust
    assert before == {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in before}


def test_headers_only_requires_a_narrow_repo_relative_prefix():
    source = (ROOT / "tools" / "repo_map.py").read_text("utf-8")
    assert "--headers-only" in source
    for prefix in (".", "..", "C:/9to5", "bootstrap/../platform_core"):
        result = subprocess.run(
            [sys.executable, "tools/repo_map.py", "--headers-only", "--only", prefix],
            cwd=ROOT, text=True, capture_output=True,
        )
        assert result.returncode != 0
