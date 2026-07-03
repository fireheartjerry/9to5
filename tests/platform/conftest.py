"""Shared session-scoped fixtures for tests/platform/.

repo_map.build_map() does a full-repo rglob + AST-parse over every first-party module. Several
tests in this directory only READ the result (filter/inspect it, never mutate it) -- computing
it once per pytest session (once per xdist worker under --dist loadscope) instead of once per
test collapses that redundant full-repo scan without changing what any test verifies.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_TOOLS_DIR = str(REPO_ROOT / "tools")
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

try:
    import repo_map  # noqa: E402  (path injected above)
except Exception:  # noqa: BLE001 -- old/partial checkout: dependent tests skip via the fixture
    repo_map = None


@pytest.fixture(scope="session")
def repo_build_map():
    """The real repo_map.build_map() result, computed once per test session (per xdist worker)
    and shared READ-ONLY across every test that requests it. No consumer in this suite mutates
    the returned dict (audited: filters/iterates only) -- if a future test needs to modify it,
    deep-copy first rather than sharing this fixture."""
    if repo_map is None:
        pytest.skip("tools/repo_map.py not importable")
    return repo_map.build_map()
