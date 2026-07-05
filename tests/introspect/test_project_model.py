"""Tests for introspect.project_model: JSON round-trip + dataclass defaults."""
from __future__ import annotations

from introspect.project_model import (
    BoundaryMap,
    DetectedCommand,
    ModuleInfo,
    ProjectModel,
)


def _sampleModel() -> ProjectModel:
    mod = ModuleInfo(
        path="pkg/core.py",
        lang="python",
        loc=12,
        exports=("coreFunc",),
        imports=("pkg/util.py",),
        lazy_imports=("pkg/late.py",),
        side_effects=("subprocess",),
    )
    return ProjectModel(
        root="C:/tmp/proj",
        languages=("python", "javascript"),
        modules=(mod,),
        import_edges=(("pkg/core.py", "pkg/util.py"),),
        commands=(
            DetectedCommand(kind="test", cmd="python -m pytest", source="pyproject.toml"),
        ),
        boundaries=BoundaryMap(
            packages=("pkg",),
            facades=("pkg/__init__.py",),
            entrypoints=("main.py",),
            config_files=("pyproject.toml",),
        ),
    )


def test_json_round_trip():
    model = _sampleModel()
    assert ProjectModel.fromJson(model.toJson()) == model


def test_defaults():
    model = _sampleModel()
    assert model.truncated is False
    assert model.git_head == ""
    mod = ModuleInfo(path="a.py", lang="python", loc=0)
    assert mod.exports == ()
    assert mod.imports == ()
    assert mod.lazy_imports == ()
    assert mod.side_effects == ()
    assert BoundaryMap() == BoundaryMap((), (), (), ())


def test_round_trip_preserves_flags():
    base = _sampleModel()
    model = ProjectModel(
        root=base.root,
        languages=base.languages,
        modules=base.modules,
        import_edges=base.import_edges,
        commands=base.commands,
        boundaries=base.boundaries,
        truncated=True,
        git_head="abc123",
    )
    back = ProjectModel.fromJson(model.toJson())
    assert back.truncated is True
    assert back.git_head == "abc123"
    assert back == model
