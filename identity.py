# identity.py
"""The SELF manifest -- 9to5's positive notion of identity.

Answers ONE question for any path: "whose is this, and in what role?" The manifest is a
*classifier*, not a guard -- roles drive handling, never the right to edit. Only the
``hard_boundary`` role forbids. See docs/superpowers/specs/2026-06-23-self-other-boundary-design.md.
"""
from __future__ import annotations

import os
from enum import Enum
from pathlib import Path

import config

PROJECT_ROOT: Path = Path(config.PROJECT_ROOT).resolve()


def _canonical(p: str | os.PathLike) -> str:
    """Fully canonical, comparison-ready absolute path: resolve symlinks/junctions/8.3,
    collapse '..', normalize Windows case. ``os.path.realpath`` is used deliberately --
    it canonicalizes more aggressively than ``Path.resolve()`` on Windows junctions."""
    raw = os.fspath(p)
    if not os.path.isabs(raw):
        raw = os.path.join(str(PROJECT_ROOT), raw)
    return os.path.normcase(os.path.realpath(raw))


def _isUnder(path_canon: str, root: Path) -> bool:
    """True iff ``path_canon`` is ``root`` or contained under it (canonical compare)."""
    root_canon = _canonical(root)
    return path_canon == root_canon or path_canon.startswith(root_canon + os.sep)


class Role(Enum):
    SELF_CODE = "self.code"               # own modules; freely editable; fingerprinted
    SELF_INSTRUCTIONS = "self.instructions"  # directives 9to5 OBEYS
    SELF_OBJECT_META = "self.object_meta"    # metadata 9to5 EDITS but must never OBEY
    SELF_LEARNED = "self.learned"            # task-produced memory; provenance-tagged
    SELF_LIVE_STATE = "self.live_state"      # hot cross-process channel
    SELF_FROZEN_STATE = "self.frozen_state"  # orchestrator owns in RAM; disk is a checkpoint
    HARD_BOUNDARY = "hard_boundary"          # the ONLY prohibition; narrow
    OTHER_CONTENT = "other.content"          # the work target


# Specific files override directory rules (checked first, most-specific wins).
# Keys are normcase'd (lowercase on Windows) to match the output of os.path.basename(_canonical(...)).
_FILE_ROLES: dict[str, Role] = {
    os.path.normcase("CLAUDE.md"): Role.SELF_OBJECT_META,
    os.path.normcase("README.md"): Role.SELF_OBJECT_META,
}

# Directory roots, checked in this order (first containment match wins). HARD_BOUNDARY
# and the more-specific state/knowledge roots precede the catch-all SELF_CODE root.
_DIR_ROLES: tuple[tuple[Role, Path], ...] = (
    (Role.HARD_BOUNDARY, PROJECT_ROOT / ".env"),
    (Role.HARD_BOUNDARY, PROJECT_ROOT / ".git"),
    (Role.HARD_BOUNDARY, PROJECT_ROOT / "venv"),
    (Role.SELF_FROZEN_STATE, PROJECT_ROOT / "state" / "tasks"),
    (Role.SELF_LIVE_STATE, PROJECT_ROOT / "state" / "control"),
    (Role.SELF_LEARNED, PROJECT_ROOT / "state" / "experience.db"),
    (Role.SELF_LEARNED, PROJECT_ROOT / "state" / "sie_overrides.json"),
    (Role.SELF_LEARNED, PROJECT_ROOT / "knowledge"),
    (Role.SELF_OBJECT_META, PROJECT_ROOT / "docs"),
    (Role.SELF_CODE, PROJECT_ROOT),   # catch-all for anything else inside the install tree
)

# Files the CLI's memory walk reads as instructions but that live OUTSIDE the tree.
_USER_GLOBAL_CLAUDE_MD = Path.home() / ".claude" / "CLAUDE.md"


def roleOf(path: str | os.PathLike) -> Role:
    """Classify ``path`` into exactly one Role. Canonical, containment-based."""
    canon = _canonical(path)
    if canon == _canonical(_USER_GLOBAL_CLAUDE_MD):
        return Role.SELF_INSTRUCTIONS
    base = os.path.basename(canon)
    # Specific-file override only applies inside the project tree.
    if base in _FILE_ROLES and _isUnder(canon, PROJECT_ROOT):
        return _FILE_ROLES[base]
    for role, root in _DIR_ROLES:
        if _isUnder(canon, root):
            return role
    return Role.OTHER_CONTENT


def isObeyable(path: str | os.PathLike) -> bool:
    """True only for directives 9to5 may treat as its OWN instructions."""
    return roleOf(path) == Role.SELF_INSTRUCTIONS


def isEditable(path: str | os.PathLike) -> bool:
    """Editing is unrestricted EXCEPT the narrow hard_boundary set."""
    return roleOf(path) != Role.HARD_BOUNDARY


def isCodeSelf(path: str | os.PathLike) -> bool:
    return roleOf(path) == Role.SELF_CODE


def selfCodeFiles() -> list[str]:
    """Every *.py under the project tree that classifies as SELF_CODE -- the set the
    epoch fingerprints. Excludes venv/.git (hard_boundary) and docs/state by role."""
    out: list[str] = []
    for p in PROJECT_ROOT.rglob("*.py"):
        if roleOf(p) == Role.SELF_CODE:
            out.append(_canonical(p))
    return sorted(out)
