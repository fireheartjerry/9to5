"""Tests for P7 tools/devx + selfmod-runner fixes (B38-B43).

Covers: the selfmod gate defaults to pytest (not `unittest discover`), the generated AGENTS.md /
repo-health commands advertise pytest, `dev.py check` tolerates deleted paths, the slow-report
subprocess pipe decodes UTF-8, and size-audit honestly documents its tracked-only scope.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tools"))

import selfmod  # noqa: E402
import repo_map_render  # noqa: E402
import dev_checks  # noqa: E402
import dev_reports  # noqa: E402
import size_audit  # noqa: E402


# ==== B38: selfmod default runner is the pytest form ====
def test_default_test_command_is_pytest():
    assert selfmod.DEFAULT_TEST_COMMAND == ["python", "-m", "pytest", "tests", "-x", "-q"]


def test_default_runner_uses_pytest_not_unittest(monkeypatch):
    captured = {}

    class _CP:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _CP()

    monkeypatch.setattr(selfmod.subprocess, "run", _fake_run)
    passed, status, _ = selfmod._default_test_runner("/some/dir")
    assert passed is True
    assert status == "passed"
    assert captured["cmd"] == ["python", "-m", "pytest", "tests", "-x", "-q"]
    assert "unittest" not in captured["cmd"]


# ==== B39: generated AGENTS.md advertises pytest, not unittest discover ====
def test_root_agents_md_uses_pytest_fast_lane():
    text = repo_map_render.render_root_agents_md({"modules": {}})
    assert "unittest discover" not in text
    assert "python tools/dev.py fast" in text


# ==== B40: repo_health no longer advertises unittest discover ====
def test_repo_health_no_unittest_discover():
    src = (REPO_ROOT / "scripts" / "repo_health.py").read_text(encoding="utf-8")
    assert "unittest discover" not in src
    assert "pytest" in src


# ==== B41: cmd_check filters deleted paths instead of failing ====
def test_py_files_drops_deleted_paths():
    existing = str((REPO_ROOT / "tools" / "dev_checks.py"))
    deleted = "tools/this_file_was_deleted_zzz.py"
    result = dev_checks._py_files([existing, deleted])
    assert existing in result
    assert deleted not in result


def test_exists_handles_relative_and_absolute():
    assert dev_checks._exists("tools/dev_checks.py")
    assert not dev_checks._exists("tools/nope_does_not_exist_zzz.py")


# ==== B42: slow-report subprocess pipe decodes UTF-8 without raising ====
def test_run_tee_decodes_utf8(tmp_path):
    out_path = tmp_path / "report.md"
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    # Emit chars that are NOT valid cp1252 -> would crash a cp1252 pipe.
    cmd = [sys.executable, "-c", "print('check ✓ box █ café')"]
    rc = dev_reports._run_tee(cmd, out_path, env=env)
    assert rc == 0
    assert out_path.exists()


# ==== B43: size-audit documents its tracked-only scope honestly ====
def test_size_audit_help_documents_exclusions(capsys):
    rc = size_audit.main(["--help"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "tests/" in out
    assert "untracked" in out.lower()


def test_size_audit_docstring_admits_scope():
    assert "tracked" in (size_audit.__doc__ or "").lower()


# ==== size_audit imports as a module from repo root (BUG: bare `import repo_map`) ====
def test_size_audit_importable_as_module_from_repo_root():
    """`from tools import size_audit; size_audit.collect()` must work from repo root
    (tools/ NOT on sys.path). A clean subprocess guarantees an unpolluted path -- the
    in-process test above puts tools/ on sys.path, which masks the regression."""
    code = "from tools import size_audit; assert size_audit.collect()[0], 'empty'; print('OK')"
    cp = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert cp.returncode == 0, f"module import failed:\n{cp.stderr}"
    assert "OK" in cp.stdout


# ==== size-audit still gates; none of the P7 files are must_split ====
def test_size_audit_p7_files_not_must_split():
    import json

    cp = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "size_audit.py"), "--json"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert cp.returncode == 0
    data = json.loads(cp.stdout)
    p7 = {
        "tools/dev_checks.py",
        "tools/dev_reports.py",
        "tools/size_audit.py",
        "tools/repo_map_render.py",
        "scripts/repo_health.py",
        "selfmod.py",
    }
    offenders = [r["path"] for r in data["files"] if r["path"] in p7 and r["bucket"] == "must_split"]
    assert offenders == [], f"P7 files over 450 lines: {offenders}"
