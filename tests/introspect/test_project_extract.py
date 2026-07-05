"""Tests for introspect.project_extract: facade, cache, prompt digest, CLI wiring."""
from __future__ import annotations


def test_extract_full_model(fixture_project):
    from introspect import extractProject

    m = extractProject(fixture_project, use_cache=False)
    assert ("pkg/core.py", "pkg/util.py") in m.import_edges
    assert any(c.kind == "test" for c in m.commands)
    assert m.languages[0] == "python" and not m.truncated


def test_extract_truncated_flag(fixture_project):
    from introspect import extractProject

    m = extractProject(fixture_project, max_files=3, use_cache=False)
    assert m.truncated is True
    assert len(m.modules) == 3


def test_extract_cache_hit(fixture_project, tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state" / "tasks", raising=False)
    from introspect import extractProject

    m1 = extractProject(fixture_project)
    m2 = extractProject(fixture_project)
    assert m1 == m2                        # second call served from cache, identical
    cache_dir = tmp_path / "state" / "project_models"
    assert cache_dir.is_dir() and list(cache_dir.glob("*.json"))


def test_context_for_prompt_budget(fixture_project):
    from introspect import extractProject, contextForPrompt

    text = contextForPrompt(extractProject(fixture_project, use_cache=False), budget_chars=800)
    assert len(text) <= 800 and "pkg" in text and "pytest" in text


def test_context_reports_cycle(fixture_project):
    from introspect import extractProject, contextForPrompt

    text = contextForPrompt(extractProject(fixture_project, use_cache=False))
    assert "cycle" in text.lower()         # the deliberate cycle_a<->cycle_b pair counted


def test_git_head_empty_for_non_repo(fixture_project):
    from introspect import extractProject

    m = extractProject(fixture_project, use_cache=False)
    assert m.git_head == ""                # fixture .git dir is fake -> rev-parse fails


def test_cli_module_runs(fixture_project):
    import subprocess
    import sys

    import config

    proc = subprocess.run(
        [sys.executable, "-m", "introspect", str(fixture_project)],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(config.PROJECT_ROOT),
    )
    assert proc.returncode == 0
    assert "pytest" in proc.stdout
