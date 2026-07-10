"""Tests for introspect.project_boundaries: packages, facades, entrypoints, config."""
from __future__ import annotations


def _scan(root):
    from developer_tools.introspection.project_scanner import scanProject

    return scanProject(root, max_files=100)


def test_boundaries_on_fixture(fixture_project):
    from developer_tools.introspection.project_boundaries import detectBoundaries

    bounds = detectBoundaries(fixture_project, _scan(fixture_project))
    assert bounds.packages == ("pkg",)
    assert "pkg/__init__.py" in bounds.facades       # imports + __all__ + docstring only
    assert "pyproject.toml" in bounds.config_files


def test_non_facade_module_excluded(fixture_project):
    from developer_tools.introspection.project_boundaries import detectBoundaries

    bounds = detectBoundaries(fixture_project, _scan(fixture_project))
    assert "pkg/core.py" not in bounds.facades       # defines a function -> not a facade


def test_future_only_module_is_not_facade(fixture_project):
    from developer_tools.introspection.project_boundaries import detectBoundaries

    (fixture_project / "pkg" / "future_only.py").write_text(
        '"""Docstring plus a future import only -- NOT a re-export facade."""\n'
        "from __future__ import annotations\n",
        encoding="utf-8",
    )
    bounds = detectBoundaries(fixture_project, _scan(fixture_project))
    assert "pkg/future_only.py" not in bounds.facades
    assert "pkg/__init__.py" in bounds.facades       # real facade still detected


def test_entrypoints_detected(fixture_project):
    from developer_tools.introspection.project_boundaries import detectBoundaries

    (fixture_project / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (fixture_project / "pkg" / "__main__.py").write_text("print('m')\n", encoding="utf-8")
    bounds = detectBoundaries(fixture_project, _scan(fixture_project))
    assert "main.py" in bounds.entrypoints
    assert "pkg/__main__.py" in bounds.entrypoints
