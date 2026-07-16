"""Regression coverage for compact navigation, coverage selection, FTS hydration, and council fan-out."""
from __future__ import annotations

import threading

from agents.planning.council_context import CouncilContextPack
from agents.planning.pre_execution_council import CouncilConfig, CouncilRunner
from memory import experience
from memory.ledger import content
from platform_core.orchestration.llm_navigation import build_context_packet, build_projection
from tools.test_brain_optimizer import optimize_weighted_coverage


def test_navigation_preserves_direct_hit_through_budget():
    projection = build_projection({"modules": {"a.core": {"path": "a/core.py", "exports": [], "depends_on": ["b"], "callers": []}, "b": {"path": "b.py", "exports": [], "depends_on": ["a.core"], "callers": []}}})
    packet = build_context_packet(projection, "core", budget_chars=1)
    assert "a.core" in packet["direct_modules"]
    assert any(row["module"] == "a.core" for row in packet["modules"])


def test_weighted_coverage_exact_prefers_shared_value():
    chosen = optimize_weighted_coverage([], {"a": {"x"}, "b": {"y"}, "both": {"x", "y"}},
                                        {"x": 2.0, "y": 2.0}, {}, 5.0)
    assert chosen == ["both"]


def test_fts_and_batch_content(tmp_path):
    db = tmp_path / "experience.db"
    experience._reset_schema_cache()
    experience.init(db)
    assert content.recordSolutionContent("r", "s", solution_content="fast retrieval graph", post_mortem="", importance=1, model_id=None, db_path=db)
    assert content.lexicalSearch("retrieval", db_path=db)[0]["st_id"] == "s"
    assert content.fetchSolutionContents([("r", "s")], db_path=db)[("r", "s")]["solution_content"] == "fast retrieval graph"
    experience._reset_schema_cache()


class _ParallelProbe:
    def __init__(self):
        self._lock = threading.Lock()
        self._release = threading.Event()
        self._active = 0
        self.observed_overlap = False

    def rendezvous(self):
        with self._lock:
            self._active += 1
            if self._active >= 2:
                self.observed_overlap = True
                self._release.set()
        self._release.wait(timeout=2)
        with self._lock:
            self._active -= 1


class _Seat:
    def __init__(self, name, probe=None):
        self.name = name
        self._probe = probe

    def ask(self, prompt, context):
        if self._probe is not None:
            self._probe.rendezvous()
        return "[PLAN] independent"


def test_parallel_memos_record_in_stable_order():
    runner = CouncilRunner(CouncilConfig(enabled=True, conversation_policy="selector", parallel_memos_enabled=True, max_parallel_seats=2, logging_enabled=False))
    probe = _ParallelProbe()
    seats = [_Seat("A", probe), _Seat("B", probe)]
    messages, compact = [], {k: [] for k in ("claims", "risks", "questions", "data", "constraints", "plans", "disagreements", "actions", "synthesis")}
    nxt = runner._run_parallel_memos("r", CouncilContextPack.for_task("plan"), seats, {"A": [], "B": []}, messages, compact, [], None, 1)
    assert nxt == 3 and [m.speaker for m in messages] == ["A", "B"]
    assert probe.observed_overlap
