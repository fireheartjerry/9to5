"""A brain-authored verify referencing a helper script that was never created (e.g.
``python check_unit_tests.py``) used to fail every attempt with FileNotFoundError, burning
all MAX_SUBTASK_ATTEMPTS retries on a structural authoring defect rather than a real
regression. runVerification now detects a missing literal .py script and falls back to the
executor's own exit status instead (agents/verifier_runner.py::_verifyScriptMissing).

Also covers the companion fix: a broad pytest/unittest verify gets a longer timeout than a
narrow python -c check (agents/verifier_runner.py::_verifyTimeoutSeconds)."""
import config
from agents import verifier
from agents.verifier_runner import _verifyTimeoutSeconds


def test_missing_script_falls_back_to_executor_ok(tmp_path):
    result = verifier.runVerification(
        {"cmd": "python check_unit_tests.py", "expect": "exit_zero"},
        str(tmp_path),
        {"ok": True, "returncode": 0},
    )
    assert result["passed"] is True
    assert result["cmd"] == "python check_unit_tests.py"
    assert "missing" in result["expect"]


def test_missing_script_falls_back_to_executor_failure(tmp_path):
    result = verifier.runVerification(
        {"cmd": "python check_integration_tests.py", "expect": "exit_zero"},
        str(tmp_path),
        {"ok": False, "returncode": 1, "stderr": "executor crashed"},
    )
    assert result["passed"] is False
    assert result["stderr"] == "executor crashed"


def test_existing_script_still_runs_normally(tmp_path):
    script = tmp_path / "check_ok.py"
    script.write_text("print('hi')\n", encoding="utf-8")
    result = verifier.runVerification(
        {"cmd": "python check_ok.py", "expect": "exit_zero"},
        str(tmp_path),
        {"ok": True, "returncode": 0},
    )
    assert result["passed"] is True
    assert result["cmd"] == "python check_ok.py"
    assert result["expect"] == "exit_zero"   # NOT the missing-script fallback path


def test_missing_glob_pattern_not_treated_as_missing_script(tmp_path):
    # A glob (*_test.py) isn't a literal path -- must not trip the missing-script fallback;
    # it runs (and fails naturally, e.g. no matches / bad shell) via the normal path.
    result = verifier.runVerification(
        {"cmd": "python -m pytest tests/*_test.py", "expect": "exit_zero"},
        str(tmp_path),
        {"ok": True, "returncode": 0},
    )
    assert result["expect"] == "exit_zero"   # normal path ran, not the missing-script shortcut


def test_suite_verify_gets_longer_timeout():
    assert _verifyTimeoutSeconds("python -m pytest tests/") == config.VERIFY_SUITE_TIMEOUT_SECONDS
    assert _verifyTimeoutSeconds("pytest tests/test_foo.py") == config.VERIFY_SUITE_TIMEOUT_SECONDS


def test_narrow_verify_keeps_tight_timeout():
    assert _verifyTimeoutSeconds('python -c "import sys; sys.exit(0)"') == config.VERIFY_TIMEOUT_SECONDS
    assert _verifyTimeoutSeconds("python check_ok.py") == config.VERIFY_TIMEOUT_SECONDS


def test_suite_timeout_longer_than_narrow_timeout():
    assert config.VERIFY_SUITE_TIMEOUT_SECONDS > config.VERIFY_TIMEOUT_SECONDS
