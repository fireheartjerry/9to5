"""Shared fixture project for introspect (and downstream refactor/explore) tests.

Builds the fixture tree locked in
docs/superpowers/plans/2026-07-04-any-project-capabilities.md "Shared test fixture":
a small mixed Python/JS project with a facade, a deliberate import cycle, a
module-level subprocess side effect, and a conventional test file. Excluded
directories (.git, __pycache__) are also created so scanner-exclusion tests
are meaningful rather than vacuous.
"""
from __future__ import annotations

import pytest

PYPROJECT_TOML = """\
[tool.pytest.ini_options]
testpaths = ["tests"]
"""

PKG_INIT = '''"""Fixture facade: re-exports pkg.core."""
from pkg.core import coreFunc

__all__ = ["coreFunc"]
'''

PKG_CORE = '''"""Fixture core module."""
from pkg.util import helper


def coreFunc():
    return helper()
'''

PKG_UTIL = '''"""Fixture util module with a module-level subprocess call."""
import subprocess

subprocess.run(["echo", "fixture"], capture_output=True)


def helper():
    return 1
'''

APP_JS = """\
import {x} from './lib.js';
console.log(x);
"""

LIB_JS = """\
export const x = 1;
"""

TEST_CORE = """\
def test_core():
    from pkg.core import coreFunc
    assert callable(coreFunc)
"""


@pytest.fixture
def fixture_project(tmp_path):
    """Build the shared fixture project tree and return its root path."""
    proj = tmp_path / "proj"
    pkg = proj / "pkg"
    pkg.mkdir(parents=True)
    (proj / "pyproject.toml").write_text(PYPROJECT_TOML, encoding="utf-8")
    (pkg / "__init__.py").write_text(PKG_INIT, encoding="utf-8")
    (pkg / "core.py").write_text(PKG_CORE, encoding="utf-8")
    (pkg / "util.py").write_text(PKG_UTIL, encoding="utf-8")
    (pkg / "cycle_a.py").write_text("import pkg.cycle_b\n", encoding="utf-8")
    (pkg / "cycle_b.py").write_text("import pkg.cycle_a\n", encoding="utf-8")
    (proj / "app.js").write_text(APP_JS, encoding="utf-8")
    (proj / "lib.js").write_text(LIB_JS, encoding="utf-8")
    tests_dir = proj / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_core.py").write_text(TEST_CORE, encoding="utf-8")
    # Excluded dirs: present so exclusion assertions actually exercise the filter.
    git_dir = proj / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    pycache = pkg / "__pycache__"
    pycache.mkdir()
    (pycache / "core.cpython-312.pyc").write_bytes(b"\x00")
    return proj
