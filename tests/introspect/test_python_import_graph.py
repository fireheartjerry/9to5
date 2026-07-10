"""Tests for introspect.python_import_graph: AST exports, edges, lazy split, side effects."""
from __future__ import annotations

FIXTURE_PY_FILES = [
    "pkg/__init__.py",
    "pkg/core.py",
    "pkg/util.py",
    "pkg/cycle_a.py",
    "pkg/cycle_b.py",
    "tests/test_core.py",
]


def test_python_graph_edges_and_lazy(fixture_project):
    from developer_tools.introspection.python_import_graph import analyzePython

    mods = analyzePython(fixture_project, FIXTURE_PY_FILES)
    core = mods["pkg/core.py"]
    assert "pkg/util.py" in core.imports            # top-level first-party import -> relpath
    assert "coreFunc" in core.exports
    util = mods["pkg/util.py"]
    assert "subprocess" in util.side_effects        # module-level subprocess.run call
    a = mods["pkg/cycle_a.py"]
    assert "pkg/cycle_b.py" in a.imports


def test_lazy_import_split(fixture_project):
    from developer_tools.introspection.python_import_graph import analyzePython

    mods = analyzePython(fixture_project, FIXTURE_PY_FILES)
    test_mod = mods["tests/test_core.py"]
    # `from pkg.core import coreFunc` lives INSIDE test_core() -> lazy, not load-time.
    assert "pkg/core.py" in test_mod.lazy_imports
    assert "pkg/core.py" not in test_mod.imports


def test_facade_honors_dunder_all(fixture_project):
    from developer_tools.introspection.python_import_graph import analyzePython

    mods = analyzePython(fixture_project, FIXTURE_PY_FILES)
    facade = mods["pkg/__init__.py"]
    assert facade.exports == ("coreFunc",)          # __all__ wins
    assert "pkg/core.py" in facade.imports


def test_stdlib_imports_not_first_party(fixture_project):
    from developer_tools.introspection.python_import_graph import analyzePython

    mods = analyzePython(fixture_project, FIXTURE_PY_FILES)
    util = mods["pkg/util.py"]
    assert all(i.endswith(".py") for i in util.imports)   # "subprocess" never resolved
    assert util.imports == ()


def test_open_tagged_only_for_write_modes(fixture_project):
    from developer_tools.introspection.python_import_graph import analyzePython

    cases = {
        "pkg/fx_read.py": 'open("x")\n',                          # default mode: read
        "pkg/fx_read2.py": 'open("x", "r")\n',
        "pkg/fx_read3.py": 'open("x", "rb")\n',
        "pkg/fx_write.py": 'open("x", "w")\n',
        "pkg/fx_append.py": 'open("x", "a")\n',
        "pkg/fx_excl.py": 'open("x", "xb")\n',
        "pkg/fx_plus.py": 'open("x", "r+")\n',
        "pkg/fx_kw.py": 'open("x", mode="w")\n',
        "pkg/fx_dyn.py": 'open("x", some_mode)\n',                # dynamic: not provable
    }
    for rel, src in cases.items():
        (fixture_project / rel).write_text(src, encoding="utf-8")
    mods = analyzePython(fixture_project, list(cases))
    for rel in ("pkg/fx_read.py", "pkg/fx_read2.py", "pkg/fx_read3.py", "pkg/fx_dyn.py"):
        assert "file-write" not in mods[rel].side_effects, rel
    for rel in ("pkg/fx_write.py", "pkg/fx_append.py", "pkg/fx_excl.py", "pkg/fx_plus.py",
                "pkg/fx_kw.py"):
        assert "file-write" in mods[rel].side_effects, rel


def test_syntax_error_yields_skeleton(fixture_project):
    from developer_tools.introspection.python_import_graph import analyzePython

    bad = fixture_project / "pkg" / "broken.py"
    bad.write_text("def x(:\n", encoding="utf-8")
    mods = analyzePython(fixture_project, ["pkg/broken.py"])
    info = mods["pkg/broken.py"]
    assert info.path == "pkg/broken.py"
    assert info.exports == () and info.imports == ()


def test_relative_import_resolution(fixture_project):
    from developer_tools.introspection.python_import_graph import analyzePython

    rel = fixture_project / "pkg" / "rel.py"
    rel.write_text("from . import util\nfrom .core import coreFunc\n", encoding="utf-8")
    mods = analyzePython(fixture_project, FIXTURE_PY_FILES + ["pkg/rel.py"])
    info = mods["pkg/rel.py"]
    assert "pkg/util.py" in info.imports
    assert "pkg/core.py" in info.imports
