"""Explore-domain conftest: re-exposes the shared introspect fixture project.

The canonical ``fixture_project`` fixture lives in ``tests/introspect/conftest.py``
(built by Task 1 of the any-project-capabilities plan). Importing the fixture
function here re-registers it for the explore test domain.
"""
from __future__ import annotations

from tests.introspect.conftest import fixture_project  # noqa: F401

__all__ = ["fixture_project"]
