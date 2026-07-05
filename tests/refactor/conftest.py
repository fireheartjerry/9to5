"""Re-expose the shared introspect fixture project for tests/refactor.

The canonical ``fixture_project`` fixture (mixed Python/JS tree with a facade, a
deliberate import cycle, and a conventional test file) lives in
``tests/introspect/conftest.py``; the star import registers it here so refactor
tests reuse the exact same tree the plan locks.
"""
from __future__ import annotations

from tests.introspect.conftest import *  # noqa: F401,F403
