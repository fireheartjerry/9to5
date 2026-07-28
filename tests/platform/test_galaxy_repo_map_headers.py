"""RED integration contract for prefix-scoped headers-only repo-map mode."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import repo_map  # noqa: E402
import repo_map_outputs  # noqa: E402


def test_headers_only_keeps_tracked_files_on_the_canonical_inventory(
    tmp_path, monkeypatch
):
    package = tmp_path / "pkg" / "__init__.py"
    tracked = tmp_path / "pkg" / "tracked.py"
    reviewed_untracked = tmp_path / "pkg" / "reviewed.py"
    for path in (package, tracked, reviewed_untracked):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('"""fixture"""\n', encoding="utf-8")
    monkeypatch.setattr(repo_map, "REPO_ROOT", tmp_path)

    tracked_paths = [package, tracked]
    expanded_paths = [package, reviewed_untracked, tracked]
    tracked_test = tmp_path / "tests" / "test_tracked.py"
    expanded_test = tmp_path / "tests" / "test_reviewed.py"
    _, tracked_modules, tracked_tests = repo_map_outputs._header_inventory(
        tracked,
        tracked_paths=tracked_paths,
        expanded_paths=expanded_paths,
        tracked_test_paths=[tracked_test],
        expanded_test_paths=[tracked_test, expanded_test],
    )
    _, untracked_modules, untracked_tests = repo_map_outputs._header_inventory(
        reviewed_untracked,
        tracked_paths=tracked_paths,
        expanded_paths=expanded_paths,
        tracked_test_paths=[tracked_test],
        expanded_test_paths=[tracked_test, expanded_test],
    )

    assert tracked_modules == {"pkg", "pkg.tracked"}
    assert untracked_modules == {"pkg", "pkg.reviewed", "pkg.tracked"}
    assert tracked_tests == [tracked_test]
    assert untracked_tests == [tracked_test, expanded_test]


@pytest.mark.timeout(180)
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
    global_command = [sys.executable, "tools/repo_map.py", "--check"]
    before_global = subprocess.run(
        global_command, cwd=ROOT, text=True, capture_output=True
    )
    first = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert first.returncode == 0, first.stderr
    check = subprocess.run([*command, "--check"], cwd=ROOT, text=True, capture_output=True)
    assert check.returncode == 0, check.stderr
    global_check = subprocess.run(global_command, cwd=ROOT, text=True, capture_output=True)
    assert (
        global_check.returncode,
        global_check.stdout,
        global_check.stderr,
    ) == (
        before_global.returncode,
        before_global.stdout,
        before_global.stderr,
    )
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
