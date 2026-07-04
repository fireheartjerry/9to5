"""Tests for second-opinion review mixin helpers."""

from __future__ import annotations

import threading

from platform_core.orchestration.control_review_mixin import OrchestratorControlReviewMixin


class _Host(OrchestratorControlReviewMixin):
    def __init__(self) -> None:
        # Mirrors the eager init Orchestrator.__init__ performs (see orchestrator.py) --
        # _reviewHashLock/_reviewHashes are plain attribute reads now, not lazy check-then-set.
        self._review_hash_lock = threading.Lock()
        self._review_hashes: dict = {}


def test_worth_gpt_review_dedupes_per_subtask(monkeypatch):
    monkeypatch.setattr("config.GEMINI_MIN_OUTPUT_CHARS", 5)
    host = _Host()
    text = "long enough output for review"

    assert host._worthGptReview(text, "st-1") is True
    assert host._worthGptReview(text, "st-1") is False
    assert host._worthGptReview(text, "st-2") is True
