"""Fail-closed normalization for planner-authored concurrency metadata."""
from __future__ import annotations

from pathlib import PurePosixPath
from typing import Mapping, Required, Sequence, TypedDict, TypeGuard


class PlannedSubtask(TypedDict, total=False):
    title: Required[str]
    description: Required[str]
    layer: Required[int]
    effort_level: Required[str]
    verify: Required[dict[str, object]]
    depends_on: list[int]
    files_touched: list[str]
    parallel_safe: bool


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _path(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip() or any(char in value for char in "*?["):
        return None
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or path == PurePosixPath("."):
        return None
    return path.as_posix()


def normalizePlanConcurrency(plan: Sequence[Mapping[str, object]]) -> list[dict]:
    """Copy plan metadata, retaining concurrency only when every proof is valid.

    A bad dependency declaration makes the whole plan serial: this is safer than
    guessing a graph and preserves existing ordered-plan behavior.
    """
    normalized: list[dict] = []
    invalid_dependencies = False
    for index, raw in enumerate(plan):
        item = dict(raw)
        raw_deps = raw.get("depends_on", [])
        deps: list[int] = []
        if not isinstance(raw_deps, list) or not all(_is_int(dep) and 0 <= dep < index for dep in raw_deps):
            invalid_dependencies = True
        else:
            deps = list(dict.fromkeys(raw_deps))
        raw_files = raw.get("files_touched", [])
        files: list[str] = []
        files_valid = isinstance(raw_files, list)
        if files_valid:
            for candidate in raw_files:
                clean = _path(candidate)
                if clean is None:
                    files_valid = False
                    break
                if clean not in files:
                    files.append(clean)
        item["depends_on"] = deps
        item["files_touched"] = files if files_valid else []
        item["parallel_safe"] = bool(raw.get("parallel_safe") is True and files_valid and files)
        normalized.append(item)
    if invalid_dependencies:
        for item in normalized:
            item["depends_on"] = []
            item["parallel_safe"] = False
    return normalized
