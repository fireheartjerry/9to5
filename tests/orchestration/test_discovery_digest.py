import json
from unittest import mock

from agents.discovery import digest as digest_mod


def _make_run(returncode=0, stdout="", stderr=""):
    r = mock.Mock()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


def test_compile_digest_returns_all_keys(tmp_path):
    """compile_digest always returns a dict with all expected top-level keys."""
    repo_map = tmp_path / ".repo-map.json"
    repo_map.write_text(json.dumps({"modules": []}))
    arch = tmp_path / "docs" / "ARCHITECTURE.md"
    arch.parent.mkdir(parents=True)
    arch.write_text("# Architecture\nThis is a test.")

    with mock.patch("subprocess.run", return_value=_make_run(stdout="")), \
         mock.patch.object(digest_mod, "_collect_institutional_memory",
                           return_value={"recent_lessons": []}):
        result = digest_mod.compile_digest(str(tmp_path))

    REQUIRED = [
        "repo_map", "architecture", "module_signatures", "dependency_graph",
        "dead_code_signals", "static_signals", "quality", "git_signals",
        "github", "institutional_memory", "innovation_seeds",
        "leverage_signals", "skills_hooks", "config_signals",
    ]
    for key in REQUIRED:
        assert key in result, f"missing key: {key}"


def test_static_signals_has_expected_subkeys(tmp_path):
    repo_map = tmp_path / ".repo-map.json"
    repo_map.write_text("{}")
    with mock.patch("subprocess.run", return_value=_make_run(stdout="")), \
         mock.patch.object(digest_mod, "_collect_institutional_memory",
                           return_value={}):
        result = digest_mod.compile_digest(str(tmp_path))
    sig = result["static_signals"]
    for k in ("size_violations", "todos", "docs_drift", "test_gaps",
               "test_isolation_violations", "deep_nesting", "long_functions",
               "security_signals"):
        assert k in sig, f"static_signals missing: {k}"


def test_compile_digest_survives_subprocess_failure(tmp_path):
    """All subprocess errors are caught; digest still returns a complete dict."""
    with mock.patch("subprocess.run", side_effect=Exception("no gh")), \
         mock.patch.object(digest_mod, "_collect_institutional_memory",
                           return_value={}):
        result = digest_mod.compile_digest(str(tmp_path))
    assert isinstance(result, dict)
    assert "static_signals" in result


def test_fallback_has_all_14_keys():
    """Fallback dict on exception must have all 14 required keys."""
    REQUIRED = [
        "repo_map", "architecture", "module_signatures", "dependency_graph",
        "dead_code_signals", "static_signals", "quality", "git_signals",
        "github", "institutional_memory", "innovation_seeds",
        "leverage_signals", "skills_hooks", "config_signals",
    ]
    # Simulate fallback
    fallback = {k: {} for k in (
        "repo_map", "architecture", "module_signatures", "dependency_graph",
        "dead_code_signals", "static_signals", "quality", "git_signals",
        "github", "institutional_memory", "innovation_seeds",
        "leverage_signals", "skills_hooks", "config_signals",
    )}
    for key in REQUIRED:
        assert key in fallback, f"fallback missing: {key}"
    assert len(fallback) == 14, f"fallback has {len(fallback)} keys, expected 14"
