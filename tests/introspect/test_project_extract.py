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


def test_cache_dir_inside_root_does_not_self_invalidate(fixture_project, monkeypatch):
    """Cache dir under the scanned root must not perturb the mtime hash that keys it
    (else self-extraction never cache-hits -- the 9to5 PROJECT_ROOT case)."""
    from introspect import project_extract

    cache_dir = fixture_project / "state" / "project_models"
    monkeypatch.setattr(project_extract, "_cacheDir", lambda: cache_dir)
    before = project_extract._mtimeHash(fixture_project)
    cache_dir.mkdir(parents=True)
    (cache_dir / "abc.json").write_text("{}", encoding="utf-8")
    assert project_extract._mtimeHash(fixture_project) == before


def test_cache_invalidated_by_content_edit(fixture_project, tmp_path, monkeypatch):
    """Editing a file (HEAD unchanged) must invalidate the cache -- the dirty-tree path."""
    import os
    import config
    from introspect import project_extract

    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state" / "tasks", raising=False)
    # Simulate a real git repo whose HEAD does not move across uncommitted edits.
    monkeypatch.setattr(project_extract, "_gitHead", lambda _root: "deadbeefcafe")
    m1 = project_extract.extractProject(fixture_project)
    util = fixture_project / "pkg" / "util.py"
    util.write_text('"""Edited util, no side effects."""\n\ndef helper():\n    return 2\n',
                    encoding="utf-8")
    # Bump mtime explicitly: coarse filesystem mtime resolution must not flake this.
    stat = util.stat()
    os.utime(util, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))
    m2 = project_extract.extractProject(fixture_project)
    util1 = next(m.side_effects for m in m1.modules if m.path == "pkg/util.py")
    util2 = next(m.side_effects for m in m2.modules if m.path == "pkg/util.py")
    assert "subprocess" in util1
    assert "subprocess" not in util2       # stale cache would still report it


def test_cache_key_includes_max_files(fixture_project, tmp_path, monkeypatch):
    """A truncated extract must not be served for a later, larger max_files call."""
    import config
    from introspect import extractProject

    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state" / "tasks", raising=False)
    m1 = extractProject(fixture_project, max_files=1)
    assert m1.truncated is True and len(m1.modules) == 1
    m2 = extractProject(fixture_project, max_files=100)
    assert m2.truncated is False
    assert len(m2.modules) > 1             # stale cache would return the 1-module model


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
