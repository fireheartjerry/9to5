"""Guard: the ``unittest discover`` / bare-runner live-creds footgun stays purged.

``unittest discover`` (and `python tests/test_x.py`) bypass the pytest-only conftest sandbox
that blanks the live Discord/Ollama creds in .env, so advertising them anywhere the brain or
executor reads is a documented incident class. This asserts that the single-sourced FULL_SUITE
command is pytest, that generated AI-nav artifacts never advertise unittest, that the executor
playbook prompt strings never do, and that no test file carries a ``unittest`` runner block.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT, REPO_ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import repo_map  # noqa: E402  (tools/ injected above)
import repo_map_render  # noqa: E402
from agents import playbook  # noqa: E402


def test_full_suite_is_pytest_only():
    assert repo_map_render.FULL_SUITE.startswith("python -m pytest")
    assert "unittest" not in repo_map_render.FULL_SUITE


def test_generated_agents_md_has_no_unittest():
    root_md = repo_map_render.render_root_agents_md(repo_map.build_map())
    assert "unittest" not in root_md
    assert repo_map_render.FULL_SUITE in root_md


def test_playbook_prompts_never_advertise_unittest():
    # buildCharter/buildPlaybook are injected verbatim into every executor run -- they must
    # never tell the executor to run unittest (only the classification keyword list may name it).
    for profile in playbook.PROFILES:
        charter = playbook.buildCharter(profile)
        book = playbook.buildPlaybook(profile)
        assert "unittest" not in charter, f"{profile} charter advertises unittest"
        assert "unittest" not in book, f"{profile} playbook advertises unittest"


def test_playbook_full_suite_is_pytest():
    assert playbook.FULL_SUITE.startswith("python -m pytest")


def test_no_test_file_has_unittest_main_block():
    # Build the needle from parts so THIS guard file is not itself an offender.
    needle = "unittest" + ".main("
    offenders = [
        str(p.relative_to(REPO_ROOT)).replace("\\", "/")
        for p in sorted((REPO_ROOT / "tests").rglob("*.py"))
        if "__pycache__" not in p.parts
        and needle in p.read_text(encoding="utf-8", errors="ignore")
    ]
    assert offenders == [], f"test files carry a {needle}) runner block: {offenders}"
