"""Tests for introspect.generic_import_scan: regex JS/TS import edges."""
from __future__ import annotations


def test_generic_scan_js(fixture_project):
    from developer_tools.introspection.generic_import_scan import analyzeGeneric

    mods = analyzeGeneric(fixture_project, ["app.js", "lib.js"])
    assert "lib.js" in mods["app.js"].imports


def test_generic_scan_require_and_extensionless(fixture_project):
    from developer_tools.introspection.generic_import_scan import analyzeGeneric

    (fixture_project / "cli.js").write_text(
        "const lib = require('./lib');\n", encoding="utf-8"
    )
    mods = analyzeGeneric(fixture_project, ["cli.js", "lib.js"])
    assert "lib.js" in mods["cli.js"].imports       # './lib' resolved via +.js


def test_generic_scan_ignores_out_of_set_and_bare(fixture_project):
    from developer_tools.introspection.generic_import_scan import analyzeGeneric

    (fixture_project / "vendor.js").write_text(
        "import React from 'react';\nimport {y} from './missing.js';\n",
        encoding="utf-8",
    )
    mods = analyzeGeneric(fixture_project, ["vendor.js", "lib.js"])
    assert mods["vendor.js"].imports == ()          # bare specifier + out-of-set both dropped


def test_generic_scan_subdir_relative(fixture_project):
    from developer_tools.introspection.generic_import_scan import analyzeGeneric

    sub = fixture_project / "src"
    sub.mkdir()
    (sub / "a.js").write_text("import {x} from '../lib.js';\n", encoding="utf-8")
    mods = analyzeGeneric(fixture_project, ["src/a.js", "lib.js"])
    assert "lib.js" in mods["src/a.js"].imports
