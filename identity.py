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
