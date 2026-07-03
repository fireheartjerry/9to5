"""Fail-closed CI affected-test resolution (tools/ci_affected.py)."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))
import ci_affected  # noqa: E402


def _decide(files):
    return ci_affected.decide(files, repo_root=REPO_ROOT)


class TestFailClosed:
    def test_non_py_file_falls_back(self):
        d = _decide(["agents/executor.py", "pytest.ini"])
        assert d.ok is False

    def test_sensitive_files_fall_back(self):
        for f in ("tests/conftest.py", "conftest.py", "pytest.ini", "requirements.txt",
                  "requirements-dev.txt", "config.py", ".github/workflows/tests.yml",
                  "tools/repo_map.py", "tests/factories.py", "tests/progress_reporter.py",
                  "tools/ci_affected.py", "tools/affected_tests.py"):
            assert _decide([f]).ok is False, f

    def test_deleted_py_file_falls_back(self):
        d = _decide(["agents/this_module_was_deleted_xyz.py"])
        assert d.ok is False and "missing" in d.reason.lower()

    def test_too_many_files_falls_back(self):
        files = ["agents/executor.py"] * 26
        assert _decide(files).ok is False and "too many" in _decide(files).reason.lower()

    def test_empty_change_set_falls_back(self):
        assert _decide([]).ok is False

    def test_dot_prefixed_path_not_corrupted(self):
        # a .py under a dot-dir must be judged by its true path, not a dot-stripped one
        d = _decide([".github/scripts/does_not_exist_probe.py"])
        assert d.ok is False
        assert "github" in d.reason and ".github" in d.reason  # leading dot preserved in reason


class TestHappyPath:
    def test_changed_test_covers_itself(self):
        me = "tests/platform/test_ci_affected.py"
        d = _decide([me])
        assert d.ok is True and me in d.targets

    def test_mapped_source_file_yields_test_targets(self):
        # tools/size_audit.py is non-sensitive and has tests/.../test_*size* coverage or similar
        d = _decide(["tools/size_audit.py"])
        # either it maps (ok + targets) or fails closed — but must NEVER be ok with empty targets
        if d.ok:
            assert d.targets and all(t.startswith("tests/") for t in d.targets)

    def test_ok_decision_never_has_empty_targets(self):
        d = _decide(["tests/platform/test_ci_affected.py"])
        assert (d.ok and d.targets) or (not d.ok)
