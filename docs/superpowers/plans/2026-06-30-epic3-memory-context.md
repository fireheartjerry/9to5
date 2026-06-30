# Epic 3 — Memory & Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give 9to5 retrieval *real solution content* served from a swappable ANN index (ChromaDB fed 9to5's own `nomic-embed-text` vectors), rerank by recency+importance+relevance, and replace blind `[:N]` truncation with hierarchical compaction that trims the *payload* to the **fixed** Ollama window — closing brief gaps #4 (solution RAG) and #8 (long-horizon context).

**Architecture:** Five independently-shippable, default-OFF units, each fail-open to today's behavior: (3a-i) `exp_content` content store with no new dependency; (3a-ii) an `AnnIndex` Protocol with a `NullIndex` fail-open fallback to today's O(n) cosine scan; (3a-iii) a `ChromaIndex` backend fed our own 768-dim vectors; (3b) a pure-function recency/importance/relevance rerank; (3c) a compaction layer that condenses the oldest half of an over-long payload and offloads the raw to disk. **`num_ctx` is NEVER resized** — it stays pinned at `config.OLLAMA_NUM_CTX`; compaction trims the payload to fit the window (preserving the documented Ollama reload-storm fix). Every summarizer call is itself an ordinary fixed-window brain call.

**Tech Stack:** Python 3, stdlib `sqlite3` (WAL pool already in `memory/experience_schema.py`), local Ollama `nomic-embed-text` embeddings (`memory/retrieval.py::embed`), optional `chromadb` (added only in Phase 2, behind a fail-open import guard), `pytest`. Conventions: `camelCase` functions, `snake_case` vars, `ALL_CAPS` consts, `@AI-MAP v1` headers, files ≤450 lines / functions ≤70 lines (`python tools/size_audit.py`).

---

## Ground-truth anchors (read before starting)

| Concern | Exact location |
|---|---|
| O(n) cosine scan (fallback) | `memory/retrieval.py:147` `top_k_similar`; pool query `memory/experience_subtasks.py:152` `embedded_subtasks` |
| Metadata-only render | `memory/retrieval.py:184` `render_lessons` |
| One-call helper used by the brain | `memory/retrieval.py:240` `lessons_block`; call sites `platform_core/orchestration/plan_mixin.py:142` and `:357` (`_sieAuthoringContext`) |
| Embed seam (mock target) | `memory/retrieval.py:57` `_embed_call`; public `embed` at `:73` |
| Index seed points | `memory/retrieval.py:135` `embed_and_store`, `:218` `backfill_embeddings` |
| Schema + migrations | `memory/experience_schema.py:30` `_SCHEMA`, `:215` `_MIGRATIONS`, `:204` `_ensureColumns` |
| Write convention (lock+connect) | `memory/experience_solutions.py:25` (`_WRITE_LOCK, _connect`) ; `set_subtask_embedding` at `memory/experience_subtasks.py:139` |
| Subtask record/sync site | `memory/experience_subtasks.py:62` `record_subtask`, `:117` `sync_subtask`; invoked from `state/task_schema.py:181` |
| Blind truncation (the fallback we keep) | `platform_core/orchestration/brain_io.py:23` `_fitUserToCtx` |
| Fixed-window fit seam | `platform_core/orchestration/llm_mixin.py:99-100` (`num_ctx = config.OLLAMA_NUM_CTX`, then `_fitUserToCtx`) |
| Config home (auto re-exported by `config.py:55`) | `platform_core/app_config/llm.py` — `_envBool/_envInt/_envFloat` helpers at lines 26/33/44 |

**Modularity note:** `memory/retrieval.py` is 252 lines and `platform_core/orchestration/plan_mixin.py` is 416 lines today. The new public functions added to `retrieval.py` (Tasks 4/9/12) keep it under 450; do NOT add net new logic to `plan_mixin.py` (its upgrade is transparent via `lessons_block`).

---

## Task 1: `exp_content` table + `importance` migration column

**Files:**
- Modify: `memory/experience_schema.py:30-201` (`_SCHEMA`) and `:215-220` (`_MIGRATIONS`)
- Test: `tests/test_experience_schema_migration.py`

- [ ] **Step 1: Write the failing test**

```python
"""Migration test: a pre-existing ledger gains exp_content + subtasks.importance idempotently."""
import sqlite3
from pathlib import Path

import pytest

import config
from memory import experience, experience_schema


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    db = tmp_path / "experience.db"
    monkeypatch.setattr(config, "EXPERIENCE_DB_PATH", db, raising=False)
    experience._reset_schema_cache()
    yield db
    experience._reset_schema_cache()


def test_exp_content_table_and_importance_column_created(fresh_db):
    experience.init(db_path=fresh_db)
    with experience._connect(fresh_db) as conn:
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "exp_content" in tables
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(subtasks)")}
        assert "importance" in cols
        ccols = {r["name"] for r in conn.execute("PRAGMA table_info(exp_content)")}
        assert {"run_id", "st_id", "solution_content", "post_mortem",
                "importance", "model_id", "created_at"} <= ccols


def test_migration_is_idempotent_on_legacy_db(fresh_db):
    # Simulate an OLD ledger: subtasks table WITHOUT importance, no exp_content.
    conn = sqlite3.connect(fresh_db)
    conn.execute("CREATE TABLE subtasks (id INTEGER PRIMARY KEY, run_id TEXT, st_id TEXT)")
    conn.execute("INSERT INTO subtasks (run_id, st_id) VALUES ('r0','st-0')")
    conn.commit()
    conn.close()
    experience._reset_schema_cache()
    experience.init(db_path=fresh_db)           # ensure-schema must ALTER in place
    experience.init(db_path=fresh_db)           # second pass must not raise
    with experience._connect(fresh_db) as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(subtasks)")}
        assert "importance" in cols
        row = conn.execute("SELECT st_id FROM subtasks WHERE run_id='r0'").fetchone()
        assert row["st_id"] == "st-0"           # old reads still work
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_experience_schema_migration.py -v`
Expected: FAIL — `assert "exp_content" in tables` (table not yet defined).

- [ ] **Step 3: Write minimal implementation**

In `memory/experience_schema.py`, append a new CREATE-TABLE to the `_SCHEMA` tuple immediately AFTER the `pr_outcomes` block (after line 194, before the `CREATE INDEX` lines at `:195`):

```python
    """CREATE TABLE IF NOT EXISTS exp_content (
        run_id           TEXT,
        st_id            TEXT,
        solution_content TEXT,
        post_mortem      TEXT,
        importance       REAL,
        model_id         TEXT,
        created_at       TEXT,
        UNIQUE(run_id, st_id)
    )""",
```

Then extend `_MIGRATIONS` (`:215`) so legacy `subtasks` rows gain the salience column:

```python
_MIGRATIONS: dict[str, dict[str, str]] = {
    "subtasks": {"adversary_stub": "INTEGER", "provenance": "TEXT", "importance": "REAL"},
    "prompt_variants": {"provenance": "TEXT"},
    "reflections": {"provenance": "TEXT"},
    "solution_cache": {"provenance": "TEXT"},
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_experience_schema_migration.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add memory/experience_schema.py tests/test_experience_schema_migration.py
git commit -m "feat(memory): add exp_content table + subtasks.importance migration"
```

---

## Task 2: `memory/experience_content.py` — content store + importance

**Files:**
- Create: `memory/experience_content.py`
- Test: `tests/test_experience_content.py`

- [ ] **Step 1: Write the failing test**

```python
"""exp_content round-trip + importance scoring (tmp db, no embedder/Ollama needed)."""
import pytest

import config
from memory import experience, experience_content


@pytest.fixture()
def db(tmp_path, monkeypatch):
    p = tmp_path / "experience.db"
    monkeypatch.setattr(config, "EXPERIENCE_DB_PATH", p, raising=False)
    experience._reset_schema_cache()
    experience.init(db_path=p)
    yield p
    experience._reset_schema_cache()


def test_record_then_fetch_roundtrip(db):
    ok = experience_content.recordSolutionContent(
        "r1", "st-1", solution_content="diff: added retry to fetch()",
        post_mortem="timeout needed backoff", importance=2.5,
        model_id="claude-sonnet-4-6", db_path=db)
    assert ok is True
    row = experience_content.fetchSolutionContent("r1", "st-1", db_path=db)
    assert row["solution_content"] == "diff: added retry to fetch()"
    assert row["post_mortem"] == "timeout needed backoff"
    assert abs(row["importance"] - 2.5) < 1e-6


def test_fetch_missing_returns_none(db):
    assert experience_content.fetchSolutionContent("r1", "nope", db_path=db) is None


def test_record_upserts_on_conflict(db):
    experience_content.recordSolutionContent("r1", "st-1", solution_content="v1",
                                             post_mortem="", importance=1.0,
                                             model_id="m", db_path=db)
    experience_content.recordSolutionContent("r1", "st-1", solution_content="v2",
                                             post_mortem="", importance=1.0,
                                             model_id="m", db_path=db)
    assert experience_content.fetchSolutionContent("r1", "st-1", db_path=db)["solution_content"] == "v2"


def test_compute_importance_rewards_hard_won_contested_costly():
    base = experience_content.computeImportance(attempt_count=1, adversary_verdict="pass", cost_usd=0.0)
    harder = experience_content.computeImportance(attempt_count=3, adversary_verdict="challenged", cost_usd=2.0)
    assert harder > base
    assert experience_content.computeImportance(attempt_count=None) >= 1.0  # tolerant of nulls


def test_record_from_subtask_extracts_and_scores(db):
    st = {"subtask_id": "st-9", "title": "fix flaky test", "description": "make it deterministic",
          "_adversary_verdict": "challenged",
          "session": {"result_text": "rewrote sleep() as event wait", "model": "claude-opus-4-8",
                      "attempts": 2, "cost_usd": 1.5, "learning_summary": "avoid wall-clock sleeps"}}
    assert experience_content.recordFromSubtask("r2", st, db_path=db) is True
    row = experience_content.fetchSolutionContent("r2", "st-9", db_path=db)
    assert "event wait" in row["solution_content"]
    assert row["model_id"] == "claude-opus-4-8"
    assert row["importance"] > 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_experience_content.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'memory.experience_content'`.

- [ ] **Step 3: Write minimal implementation**

Create `memory/experience_content.py`:

```python
"""Experience Ledger -- solution-content store (owns the ``exp_content`` table).

Stores the REAL diff/answer/post-mortem per passed subtask plus a write-time
``importance`` salience, sibling to ``experience_subtasks`` (which owns ``subtasks``).
Same best-effort ``_WRITE_LOCK`` + ``_connect`` convention as ``experience_solutions``.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  computeImportance(*, attempt_count=None, adversary_verdict=None, cost_usd=None) -> float  -- Write-time salience.
  recordSolutionContent(run_id, st_id, *, solution_content, post_mortem, importance, model_id, db_path=None) -> bool
  recordFromSubtask(run_id, st, db_path=None) -> bool  -- Extract content+importance from a synced subtask dict and store it.
  fetchSolutionContent(run_id, st_id, db_path=None) -> Optional[dict]
DEPENDS-ON: memory.experience_schema
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/test_experience_content.py
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from memory.experience_schema import LOG, _WRITE_LOCK, _connect, _nowIso

_CONTESTED = {"challenged", "fail", "failed", "blocked", "reject", "rejected"}


def computeImportance(*, attempt_count: Any = None, adversary_verdict: Any = None,
                      cost_usd: Any = None) -> float:
    """Write-time salience: a noisy first-pass subtask that EVENTUALLY passed, or a
    contested/expensive one, is a higher-stakes lesson. Tolerant of nulls/garbage."""
    score = 1.0
    try:
        attempts = int(float(attempt_count)) if attempt_count is not None else 1
    except (TypeError, ValueError):
        attempts = 1
    if attempts > 1:
        score += min(attempts - 1, 3) * 0.5
    if isinstance(adversary_verdict, str) and adversary_verdict.strip().lower() in _CONTESTED:
        score += 1.0
    try:
        cost = float(cost_usd) if cost_usd is not None else 0.0
    except (TypeError, ValueError):
        cost = 0.0
    if cost > 0:
        score += min(cost, 5.0) * 0.2
    return round(score, 4)


def _extractFields(st: dict[str, Any]) -> tuple[str, str, Optional[str]]:
    """Pull (solution_content, post_mortem, model_id) from a synced subtask dict.
    Best-effort across known result shapes; degrades to title/description."""
    session = st.get("session") or {}
    solution = (session.get("result_text") or session.get("output") or session.get("summary")
                or st.get("_solution_content") or st.get("description") or "")
    post_mortem = (session.get("learning_summary") or st.get("_reflection")
                   or st.get("_post_mortem") or "")
    return str(solution), str(post_mortem), session.get("model")


def recordSolutionContent(run_id: str, st_id: str, *, solution_content: str,
                          post_mortem: str, importance: float, model_id: Optional[str],
                          db_path: Optional[Path] = None) -> bool:
    """Upsert one ``exp_content`` row keyed by ``(run_id, st_id)``. Best-effort."""
    if not (run_id or "").strip() or not (st_id or "").strip():
        return False
    try:
        with _WRITE_LOCK, _connect(db_path) as conn:
            conn.execute(
                """INSERT INTO exp_content
                   (run_id, st_id, solution_content, post_mortem, importance, model_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(run_id, st_id) DO UPDATE SET
                     solution_content=excluded.solution_content,
                     post_mortem=excluded.post_mortem,
                     importance=excluded.importance,
                     model_id=excluded.model_id""",
                (run_id, st_id, solution_content, post_mortem, float(importance),
                 model_id, _nowIso()))
        return True
    except Exception as e:  # noqa: BLE001 -- learning never blocks a run
        LOG.debug("recordSolutionContent failed (ignored): %s", e)
        return False


def recordFromSubtask(run_id: str, st: dict[str, Any], db_path: Optional[Path] = None) -> bool:
    """Convenience: extract content + compute importance from ``st`` then store. Best-effort."""
    if not isinstance(st, dict) or not (st.get("subtask_id") or "").strip():
        return False
    solution, post_mortem, model_id = _extractFields(st)
    if not solution.strip():
        return False
    session = st.get("session") or {}
    vres = st.get("verify_result") or {}
    importance = computeImportance(
        attempt_count=session.get("attempts") or vres.get("attempt_count"),
        adversary_verdict=st.get("_adversary_verdict"),
        cost_usd=session.get("cost_usd"))
    return recordSolutionContent(run_id, st["subtask_id"], solution_content=solution,
                                 post_mortem=post_mortem, importance=importance,
                                 model_id=model_id, db_path=db_path)


def fetchSolutionContent(run_id: str, st_id: str,
                         db_path: Optional[Path] = None) -> Optional[dict[str, Any]]:
    """The stored content row for ``(run_id, st_id)``, or None. Best-effort (None on error)."""
    try:
        with _connect(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM exp_content WHERE run_id=? AND st_id=?",
                (run_id, st_id)).fetchone()
            return dict(row) if row else None
    except Exception as e:  # noqa: BLE001
        LOG.debug("fetchSolutionContent failed (ignored): %s", e)
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_experience_content.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add memory/experience_content.py tests/test_experience_content.py
git commit -m "feat(memory): exp_content store + write-time importance scoring"
```

---

## Task 3: Wire content write-back into `sync_subtask`

**Files:**
- Modify: `memory/experience_subtasks.py:117-136` (`sync_subtask`); add `set_subtask_importance` near `:139`
- Modify: `memory/experience.py:62-69` + `:140-146` (re-export the new symbol)
- Test: `tests/test_experience_content_sync.py`

- [ ] **Step 1: Write the failing test**

```python
"""sync_subtask must ALSO persist solution content + denormalize importance onto subtasks."""
import pytest

import config
from memory import experience, experience_content


@pytest.fixture()
def db(tmp_path, monkeypatch):
    p = tmp_path / "experience.db"
    monkeypatch.setattr(config, "EXPERIENCE_DB_PATH", p, raising=False)
    monkeypatch.setattr(config, "EXPERIENCE_LEDGER_ENABLED", True, raising=False)
    experience._reset_schema_cache()
    experience.init(db_path=p)
    yield p
    experience._reset_schema_cache()


def _state(st):
    return {"task_id": "r1", "plan": {"subtasks": [st]}, "adversary_reviews": []}


def test_sync_subtask_writes_exp_content(db):
    st = {"subtask_id": "st-1", "title": "add cache", "description": "memoize lookups",
          "status": "done", "verify_result": {"passed": True},
          "session": {"attempts": 1, "model": "m", "result_text": "added lru_cache to lookup()"}}
    assert experience.sync_subtask(_state(st), st, db_path=db) is True
    row = experience_content.fetchSolutionContent("r1", "st-1", db_path=db)
    assert row is not None and "lru_cache" in row["solution_content"]


def test_sync_subtask_denormalizes_importance_onto_subtasks(db):
    st = {"subtask_id": "st-2", "title": "hard one", "description": "tricky",
          "status": "done", "verify_result": {"passed": True},
          "session": {"attempts": 3, "model": "m", "result_text": "fixed after 3 tries"}}
    experience.sync_subtask(_state(st), st, db_path=db)
    with experience._connect(db) as conn:
        imp = conn.execute("SELECT importance FROM subtasks WHERE st_id='st-2'").fetchone()["importance"]
    assert imp is not None and imp > 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_experience_content_sync.py -v`
Expected: FAIL — `row is None` (sync_subtask does not yet write exp_content).

- [ ] **Step 3: Write minimal implementation**

In `memory/experience_subtasks.py`, add `set_subtask_importance` directly after `set_subtask_embedding` (after line 149):

```python
def set_subtask_importance(run_id: str, st_id: str, importance: float,
                           db_path: Optional[Path] = None) -> bool:
    """Denormalize write-time salience onto the subtask row (so rerank has it even for
    rows that predate exp_content). Best-effort; mirrors set_subtask_embedding."""
    try:
        with _WRITE_LOCK, _connect(db_path) as conn:
            conn.execute("UPDATE subtasks SET importance=? WHERE run_id=? AND st_id=?",
                         (float(importance), run_id, st_id))
        return True
    except Exception as e:  # noqa: BLE001
        LOG.debug("set_subtask_importance failed (ignored): %s", e)
        return False
```

Replace the tail of `sync_subtask` (current `:136` `return record_subtask(...)`) with:

```python
    ok = record_subtask(state_data.get("task_id"), enriched, db_path=db_path)
    # Layer-1 widen: persist the REAL solution content + denormalize importance. Best-effort:
    # a content-store failure must NEVER change the subtask-record result.
    try:
        from memory import experience_content
        run_id = state_data.get("task_id")
        if experience_content.recordFromSubtask(run_id, enriched, db_path=db_path):
            session = enriched.get("session") or {}
            vres = enriched.get("verify_result") or {}
            importance = experience_content.computeImportance(
                attempt_count=session.get("attempts") or vres.get("attempt_count"),
                adversary_verdict=enriched.get("_adversary_verdict"),
                cost_usd=session.get("cost_usd"))
            set_subtask_importance(run_id, enriched["subtask_id"], importance, db_path=db_path)
    except Exception as e:  # noqa: BLE001
        LOG.debug("sync_subtask content write-back skipped (ignored): %s", e)
    return ok
```

In `memory/experience.py`, add `set_subtask_importance` to the subtasks import block (`:62`) and to `__all__` (`:140`):

```python
from memory.experience_subtasks import (
    record_subtask,
    sync_subtask,
    set_subtask_embedding,
    set_subtask_importance,
    embedded_subtasks,
    fetch_subtasks,
    _subtask_params,
)
```
and add `"set_subtask_importance",` to `__all__` right after `"set_subtask_embedding",`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_experience_content_sync.py tests/test_experience_ledger.py -v`
Expected: PASS (new tests + the existing ledger suite still green).

- [ ] **Step 5: Commit**

```bash
git add memory/experience_subtasks.py memory/experience.py tests/test_experience_content_sync.py
git commit -m "feat(memory): sync_subtask writes solution content + denormalizes importance"
```

---

## Task 4: `retrieve_content` + `render_solutions` (content injection, NO new dependency)

**Files:**
- Modify: `memory/retrieval.py` — add `_sanitizeField`, `retrieve_content`, `render_solutions`; upgrade `lessons_block` (`:240`); top import for `experience_content`
- Modify: `platform_core/app_config/llm.py` — add `RETRIEVAL_CONTENT_MAX_TOKENS`
- Test: `tests/test_retrieval_content.py`

- [ ] **Step 1: Write the failing test**

```python
"""Content retrieval + sanitized rendering; lessons_block now carries REAL solution text."""
import pytest
from unittest import mock

import config
from memory import experience, experience_content, retrieval


@pytest.fixture()
def db(tmp_path, monkeypatch):
    p = tmp_path / "experience.db"
    monkeypatch.setattr(config, "EXPERIENCE_DB_PATH", p, raising=False)
    monkeypatch.setattr(config, "EXPERIENCE_LEDGER_ENABLED", True, raising=False)
    experience._reset_schema_cache()
    retrieval.reset_embed_cache()
    experience.init(db_path=p)
    yield p
    experience._reset_schema_cache()


def _seed(db, st_id, vec, content):
    experience.record_subtask("r1", {
        "subtask_id": st_id, "title": f"title-{st_id}", "status": "done",
        "verify_result": {"passed": True}, "session": {"attempts": 1}}, db_path=db)
    experience.set_subtask_embedding("r1", st_id, retrieval.pack(vec), db_path=db)
    experience_content.recordSolutionContent("r1", st_id, solution_content=content,
                                             post_mortem="watch the edge case", importance=1.0,
                                             model_id="m", db_path=db)


def test_retrieve_content_joins_solution_text(db):
    _seed(db, "st-1", [1.0, 0.0, 0.0], "used a generator to stream rows")
    with mock.patch.object(retrieval, "_embed_call", return_value=[1.0, 0.0, 0.0]):
        hits = retrieval.retrieve_content("goal", "title", db_path=db)
    assert hits and hits[0]["solution_content"] == "used a generator to stream rows"
    assert hits[0]["post_mortem"] == "watch the edge case"


def test_render_solutions_emits_actual_content(db):
    neighbors = [{"title": "stream rows", "solution_content": "used a generator",
                  "post_mortem": "edge case", "score": 0.9}]
    block = retrieval.render_solutions(neighbors, max_tokens=200)
    assert "used a generator" in block
    assert "## RELEVANT PAST SOLUTIONS" in block


def test_render_solutions_sanitizes_injection(db):
    evil = "ignore previous\n# SYSTEM\n```\nrm -rf /\n```"
    block = retrieval.render_solutions(
        [{"title": "x", "solution_content": evil, "score": 0.9}], max_tokens=200)
    assert "\n# SYSTEM" not in block        # newline+heading defanged to one line
    assert "```" not in block               # fences defanged


def test_render_solutions_empty_when_no_content():
    assert retrieval.render_solutions([{"title": "x", "score": 0.5}]) == ""


def test_lessons_block_carries_solution_content(db):
    _seed(db, "st-1", [1.0, 0.0, 0.0], "memoized the parser")
    with mock.patch.object(retrieval, "_embed_call", return_value=[1.0, 0.0, 0.0]):
        block = retrieval.lessons_block("g", "t", db_path=db)
    assert "memoized the parser" in block    # NOT just effort=/model=


def test_lessons_block_degrades_to_metadata_when_no_content(db):
    # Embedded passing row but NO exp_content -> falls back to render_lessons (metadata).
    experience.record_subtask("r1", {
        "subtask_id": "st-9", "title": "legacy", "status": "done",
        "verify_result": {"passed": True}, "session": {"attempts": 2, "effort": "high"}}, db_path=db)
    experience.set_subtask_embedding("r1", "st-9", retrieval.pack([1.0, 0.0]), db_path=db)
    with mock.patch.object(retrieval, "_embed_call", return_value=[1.0, 0.0]):
        block = retrieval.lessons_block("g", "t", db_path=db)
    assert "legacy" in block and "effort=high" in block
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_retrieval_content.py -v`
Expected: FAIL — `AttributeError: module 'memory.retrieval' has no attribute 'retrieve_content'`.

- [ ] **Step 3: Write minimal implementation**

In `platform_core/app_config/llm.py`, add after `RETRIEVAL_MIN_SCORE` (`:120`):

```python
# Layer-1 content injection: budget for the REAL solution-content block (separate from
# the metadata RETRIEVAL_MAX_TOKENS so content can be richer without starving lessons).
RETRIEVAL_CONTENT_MAX_TOKENS: int = _envInt("RETRIEVAL_CONTENT_MAX_TOKENS", 700)
```

In `memory/retrieval.py`, add the content-store import after `from memory import experience` (`:42`):

```python
from memory import experience_content
```

Add `_sanitizeField` + `render_solutions` after `render_lessons` (after `:215`):

```python
def _sanitizeField(text: Any, limit: int = 400) -> str:
    """Collapse a retrieved field to ONE safe inline line before it is injected verbatim
    into a brain prompt: strip control chars, collapse all whitespace/newlines, defang a
    leading markdown heading and any code fences (prompt-injection hardening, see spec 6)."""
    if not text:
        return ""
    s = "".join(ch for ch in str(text) if ch >= " " or ch in "\t\n")
    s = " ".join(s.split())            # all runs of whitespace (incl newlines) -> single space
    s = s.lstrip("#").lstrip()         # defang leading heading
    s = s.replace("```", "'''")        # defang fences
    return s[:limit]


def render_solutions(neighbors: list[dict[str, Any]],
                     max_tokens: Optional[int] = None) -> str:
    """Render neighbors into a compact block of ACTUAL solution content (sanitized),
    budgeted by RETRIEVAL_CONTENT_MAX_TOKENS. Returns "" when no neighbor carries content
    (the caller then degrades to render_lessons)."""
    budget = max_tokens or config.RETRIEVAL_CONTENT_MAX_TOKENS
    if not neighbors:
        return ""
    header = "## RELEVANT PAST SOLUTIONS (content from similar PASSED subtasks)\n"
    lines: list[str] = []
    for n in neighbors:
        content = _sanitizeField(n.get("solution_content"))
        if not content:
            continue
        title = _sanitizeField(n.get("title") or "untitled", 80)
        line = f'- "{title}": {content}'
        lesson = _sanitizeField(n.get("post_mortem"), 200)
        if lesson:
            line += f" [lesson: {lesson}]"
        candidate = header + "\n".join(lines + [line])
        if _approx_tokens(candidate) > budget:
            break
        lines.append(line)
    if not lines:
        return ""
    return header + "\n".join(lines) + "\n"
```

Add `retrieve_content` after `retrieve` (after `:174`):

```python
def retrieve_content(goal: str, title: str = "", *, k: Optional[int] = None,
                     db_path: Optional[Path] = None) -> list[dict[str, Any]]:
    """Embed the query, find the top-K similar past successes (O(n) scan for now; Phase 2
    adds the ANN lookup in front of this), and JOIN each hit to its exp_content row so the
    caller can render REAL solution content. Best-effort: empty list on any failure."""
    qvec = embed(signature_text(goal, title))
    if not qvec:
        return []
    neighbors = top_k_similar(qvec, k or config.RETRIEVAL_K, db_path=db_path)
    for n in neighbors:
        row = experience_content.fetchSolutionContent(
            n.get("run_id"), n.get("st_id"), db_path=db_path)
        if row:
            n["solution_content"] = row.get("solution_content")
            n["post_mortem"] = row.get("post_mortem")
            n["created_at"] = row.get("created_at")
            if row.get("importance") is not None:
                n["importance"] = row.get("importance")
    return neighbors
```

Upgrade `lessons_block` (`:240`) to prefer content and degrade transparently — **signature unchanged**:

```python
def lessons_block(goal: str, title: str = "", *, db_path: Optional[Path] = None) -> str:
    """Orchestrator-facing one-call helper: retrieve + render, fully best-effort.

    Prefers REAL solution content (retrieve_content + render_solutions); degrades to the
    metadata block (render_lessons) when no neighbor carries content. Returns "" when
    retrieval is unavailable, so a caller can unconditionally prepend the result."""
    try:
        neighbors = retrieve_content(goal, title, db_path=db_path)
        block = render_solutions(neighbors)
        if not block:
            block = render_lessons(neighbors)
        return (block + "\n") if block else ""
    except Exception as e:  # noqa: BLE001 -- learning must never break authoring
        LOG.debug("lessons_block failed (ignored): %s", e)
        return ""
```

Update the `@AI-MAP` `EXPORTS:` header block of `retrieval.py` to list `retrieve_content` and `render_solutions` (it is regenerated by `repo_map.py` in Task 16's verification, but add a one-line stub now so the header is not stale):

```python
  retrieve_content(goal, title='', *, k=None, db_path=None) -> list[dict]  -- Top-K similar successes joined to their exp_content solution rows.
  render_solutions(neighbors, max_tokens=None) -> str  -- Render ACTUAL sanitized solution content, budgeted by RETRIEVAL_CONTENT_MAX_TOKENS.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_retrieval_content.py tests/test_retrieval.py -v`
Expected: PASS (new content tests + the existing retrieval suite still green — `lessons_block` best-effort empty path is preserved).

- [ ] **Step 5: Commit**

```bash
git add memory/retrieval.py platform_core/app_config/llm.py tests/test_retrieval_content.py
git commit -m "feat(memory): inject real solution content via retrieve_content/render_solutions"
```

---

## Task 5: ANN config consts + `AnnIndex` Protocol + `NullIndex` (fail-open, NO chromadb)

**Files:**
- Modify: `platform_core/app_config/llm.py` — add ANN consts
- Create: `memory/exp_index.py` (Protocol + `NullIndex` + cached `getIndex`/`resetIndex`; `ChromaIndex` added in Task 6)
- Test: `tests/test_exp_index.py`

- [ ] **Step 1: Write the failing test**

```python
"""AnnIndex contract: NullIndex fail-open + getIndex singleton honoring ANN_INDEX_ENABLED."""
import pytest

import config
from memory import exp_index


@pytest.fixture(autouse=True)
def _reset():
    exp_index.resetIndex()
    yield
    exp_index.resetIndex()


def test_nullindex_query_is_empty_and_addpair_is_noop():
    idx = exp_index.NullIndex()
    idx.addPair("u1", [1.0, 0.0], {"st_id": "st-1"})
    idx.persist()
    assert idx.query([1.0, 0.0], 5, 0.0) == []


def test_getindex_returns_null_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "ANN_INDEX_ENABLED", False, raising=False)
    assert isinstance(exp_index.getIndex(), exp_index.NullIndex)


def test_getindex_is_cached_singleton(monkeypatch):
    monkeypatch.setattr(config, "ANN_INDEX_ENABLED", False, raising=False)
    assert exp_index.getIndex() is exp_index.getIndex()


def test_getindex_falls_open_to_null_when_backend_import_fails(monkeypatch):
    monkeypatch.setattr(config, "ANN_INDEX_ENABLED", True, raising=False)
    monkeypatch.setattr(exp_index, "_buildBackend", lambda: (_ for _ in ()).throw(ImportError("no chromadb")))
    assert isinstance(exp_index.getIndex(), exp_index.NullIndex)


def test_fakeindex_satisfies_protocol_and_ranks_by_cosine():
    # An in-memory test double proves the Protocol is usable WITHOUT chromadb as a test dep.
    fake = _FakeIndex()
    fake.addPair("a", [1.0, 0.0, 0.0], {"st_id": "a"})
    fake.addPair("b", [0.0, 1.0, 0.0], {"st_id": "b"})
    hits = fake.query([1.0, 0.0, 0.0], 2, 0.0)
    assert [h["uid"] for h in hits] == ["a", "b"]
    assert isinstance(fake, exp_index.AnnIndex)   # runtime_checkable Protocol


class _FakeIndex:
    def __init__(self):
        self._rows = []

    def addPair(self, uid, vec, payload):
        self._rows.append((uid, list(vec), dict(payload)))

    def query(self, vec, k, threshold):
        import math
        def cos(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a)); nb = math.sqrt(sum(y * y for y in b))
            return dot / (na * nb) if na and nb else 0.0
        scored = [{"uid": u, "score": cos(vec, v), "payload": p} for u, v, p in self._rows]
        scored = [s for s in scored if s["score"] >= threshold]
        scored.sort(key=lambda s: s["score"], reverse=True)
        return scored[:k]

    def persist(self):
        pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_exp_index.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'memory.exp_index'`.

- [ ] **Step 3: Write minimal implementation**

In `platform_core/app_config/llm.py`, add after `RETRIEVAL_CONTENT_MAX_TOKENS` (added in Task 4):

```python
# Layer-1 ANN index (drop-in over the O(n) cosine scan; fail-open to the scan).
ANN_INDEX_ENABLED: bool = _envBool("ANN_INDEX_ENABLED", False)
ANN_INDEX_BACKEND: str = os.getenv("ANN_INDEX_BACKEND", "chroma")
ANN_INDEX_DIR: str = os.getenv("ANN_INDEX_DIR", "state/exp_index")
# Pin the embedding dim into the collection name so a swapped embedder can't silently mix
# vector spaces (nomic-embed-text is 768-dim). See spec 8 "Embedding dim / mixed spaces".
ANN_EMBED_DIM: int = _envInt("ANN_EMBED_DIM", 768)
```

Create `memory/exp_index.py`:

```python
"""Swappable ANN index for Layer-1 retrieval (fail-open to the O(n) cosine scan).

``AnnIndex`` is a tiny Protocol; ``NullIndex`` is the always-available fallback whose
``query`` returns ``[]`` (so retrieval falls back to ``top_k_similar``). ``ChromaIndex``
(a disk-persistent chromadb collection fed 9to5's OWN nomic-embed-text vectors) is the
optional primary backend. ``getIndex()`` is a cached process singleton.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  AnnIndex  -- runtime_checkable Protocol: addPair / query / persist.
  NullIndex  -- fail-open fallback (query -> []).
  getIndex() -> AnnIndex  -- cached singleton; NullIndex when disabled or backend import fails.
  resetIndex() -> None  -- drop the singleton (tests / after a known rebuild).
DEPENDS-ON: config
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/test_exp_index.py
"""
from __future__ import annotations

import re
from typing import Any, Optional, Protocol, runtime_checkable

import config

LOG = config.getLogger("sie.exp_index")


@runtime_checkable
class AnnIndex(Protocol):
    def addPair(self, uid: str, vec: list[float], payload: dict) -> None: ...
    def query(self, vec: list[float], k: int, threshold: float) -> list[dict]: ...
    def persist(self) -> None: ...


class NullIndex:
    """The fail-open fallback: never stores, always returns no hits."""

    def addPair(self, uid: str, vec: list[float], payload: dict) -> None:
        return None

    def query(self, vec: list[float], k: int, threshold: float) -> list[dict]:
        return []

    def persist(self) -> None:
        return None


def _collectionName() -> str:
    """Embedder-pinned collection name so a model/dim swap starts a fresh space."""
    raw = f"exp_{config.EMBED_MODEL}_{int(config.ANN_EMBED_DIM)}"
    return re.sub(r"[^A-Za-z0-9_.-]", "-", raw)[:60]


def _buildBackend() -> "AnnIndex":
    """Construct the configured primary backend. Raises if its dependency is absent (the
    caller catches and falls open to NullIndex). ChromaIndex is added in the next task."""
    raise ImportError("no ANN backend built yet")


_INDEX_SINGLETON: Optional["AnnIndex"] = None


def getIndex() -> "AnnIndex":
    """Cached singleton. Returns NullIndex when ANN_INDEX_ENABLED is false or the backend
    import fails -- keeping chromadb strictly optional and retrieval always working."""
    global _INDEX_SINGLETON
    if _INDEX_SINGLETON is not None:
        return _INDEX_SINGLETON
    if not getattr(config, "ANN_INDEX_ENABLED", False):
        _INDEX_SINGLETON = NullIndex()
        return _INDEX_SINGLETON
    try:
        _INDEX_SINGLETON = _buildBackend()
    except Exception as e:  # noqa: BLE001 -- absent/broken dep -> fail open to the scan
        LOG.info("ANN backend unavailable, using O(n) scan fallback: %s", e)
        _INDEX_SINGLETON = NullIndex()
    return _INDEX_SINGLETON


def resetIndex() -> None:
    """Drop the cached singleton (tests, or after a known backfill rebuild)."""
    global _INDEX_SINGLETON
    _INDEX_SINGLETON = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_exp_index.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add memory/exp_index.py platform_core/app_config/llm.py tests/test_exp_index.py
git commit -m "feat(memory): AnnIndex Protocol + NullIndex fail-open singleton"
```

---

## Task 6: `ChromaIndex` backend (our own nomic vectors, disk-persistent)

**Files:**
- Modify: `memory/exp_index.py` — add `ChromaIndex` + wire `_buildBackend`
- Test: `tests/test_exp_index_chroma.py` (skipped when chromadb absent)

- [ ] **Step 1: Write the failing test**

```python
"""Real ChromaIndex round-trip (skipped unless chromadb is installed)."""
import pytest

import config
from memory import exp_index

chromadb = pytest.importorskip("chromadb")


@pytest.fixture(autouse=True)
def _reset():
    exp_index.resetIndex()
    yield
    exp_index.resetIndex()


def test_chromaindex_add_query_roundtrip_by_cosine(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ANN_INDEX_DIR", str(tmp_path / "idx"), raising=False)
    monkeypatch.setattr(config, "ANN_EMBED_DIM", 3, raising=False)
    idx = exp_index.ChromaIndex(str(tmp_path / "idx"))
    idx.addPair("a", [1.0, 0.0, 0.0], {"st_id": "a", "run_id": "r1"})
    idx.addPair("b", [0.0, 1.0, 0.0], {"st_id": "b", "run_id": "r1"})
    idx.persist()
    hits = idx.query([1.0, 0.0, 0.0], 2, 0.0)
    assert hits[0]["uid"] == "a"
    assert hits[0]["payload"]["st_id"] == "a"
    assert hits[0]["score"] >= hits[1]["score"]


def test_getindex_returns_chroma_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ANN_INDEX_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "ANN_INDEX_DIR", str(tmp_path / "idx2"), raising=False)
    monkeypatch.setattr(config, "ANN_EMBED_DIM", 3, raising=False)
    assert isinstance(exp_index.getIndex(), exp_index.ChromaIndex)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_exp_index_chroma.py -v`
Expected: FAIL if chromadb installed (`AttributeError: ... has no attribute 'ChromaIndex'`); SKIPPED if not installed (still valid — the contract is covered by the `_FakeIndex` in Task 5).

- [ ] **Step 3: Write minimal implementation**

In `memory/exp_index.py`, insert `ChromaIndex` after `NullIndex` and replace `_buildBackend`:

```python
class ChromaIndex:
    """Disk-persistent chromadb collection fed 9to5's OWN nomic-embed-text vectors.

    We pass embeddings explicitly (NOT chroma's default Sentence-Transformers embedder)
    so the index lives in the SAME space as retrieval.embed and reuses its negative cache.
    Cosine distance is configured; score = 1 - distance. ~AutoGen StringSimilarityMap port
    (MIT). Best-effort: any backend error is swallowed so retrieval falls back to the scan."""

    def __init__(self, persist_dir: str) -> None:
        import chromadb
        from pathlib import Path
        Path(persist_dir).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=persist_dir,
            settings=chromadb.config.Settings(anonymized_telemetry=False, allow_reset=True))
        self._col = self._client.get_or_create_collection(
            name=_collectionName(), metadata={"hnsw:space": "cosine"})

    def addPair(self, uid: str, vec: list[float], payload: dict) -> None:
        try:
            meta = {k: v for k, v in (payload or {}).items()
                    if isinstance(v, (str, int, float, bool)) and v is not None}
            self._col.upsert(ids=[uid], embeddings=[list(vec)], metadatas=[meta or {"_": ""}])
        except Exception as e:  # noqa: BLE001
            LOG.debug("ChromaIndex.addPair failed (ignored): %s", e)

    def query(self, vec: list[float], k: int, threshold: float) -> list[dict]:
        try:
            res = self._col.query(query_embeddings=[list(vec)], n_results=max(1, int(k)),
                                  include=["distances", "metadatas"])
        except Exception as e:  # noqa: BLE001
            LOG.debug("ChromaIndex.query failed (ignored): %s", e)
            return []
        ids = (res.get("ids") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        out: list[dict] = []
        for uid, dist, meta in zip(ids, dists, metas):
            score = 1.0 - float(dist)        # cosine distance -> similarity
            if score < threshold:
                continue
            out.append({"uid": uid, "score": score, "payload": dict(meta or {})})
        return out

    def persist(self) -> None:
        return None                          # PersistentClient writes through automatically


def _buildBackend() -> "AnnIndex":
    """Construct the configured primary backend. Raises if its dependency is absent."""
    backend = getattr(config, "ANN_INDEX_BACKEND", "chroma")
    if backend == "chroma":
        return ChromaIndex(config.ANN_INDEX_DIR)
    raise ValueError(f"unknown ANN_INDEX_BACKEND: {backend!r}")
```

Add `chromadb` to the project's optional/dev dependencies (do NOT pin into the core runtime requirements — it stays optional). Append to `requirements-dev.txt` if present, else note in `docs/STATE.md` (Task 17). The import guard in `getIndex` means a missing wheel never breaks a run.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_exp_index_chroma.py -v`
Expected: PASS if chromadb installed; SKIPPED otherwise (both acceptable).

- [ ] **Step 5: Commit**

```bash
git add memory/exp_index.py tests/test_exp_index_chroma.py
git commit -m "feat(memory): ChromaIndex backend over 9to5 nomic vectors"
```

---

## Task 7: Wire `retrieve_content` to the index + seed on `embed_and_store`/`backfill_embeddings`

**Files:**
- Modify: `memory/retrieval.py` — `retrieve_content` tries `getIndex().query` first; `embed_and_store` (`:135`) + `backfill_embeddings` (`:218`) also `addPair`
- Test: `tests/test_retrieval_index_wire.py`

- [ ] **Step 1: Write the failing test**

```python
"""retrieve_content prefers the ANN index, falls back to scan; seeders populate the index."""
import pytest
from unittest import mock

import config
from memory import exp_index, experience, experience_content, retrieval


@pytest.fixture()
def db(tmp_path, monkeypatch):
    p = tmp_path / "experience.db"
    monkeypatch.setattr(config, "EXPERIENCE_DB_PATH", p, raising=False)
    monkeypatch.setattr(config, "EXPERIENCE_LEDGER_ENABLED", True, raising=False)
    experience._reset_schema_cache()
    retrieval.reset_embed_cache()
    exp_index.resetIndex()
    experience.init(db_path=p)
    yield p
    experience._reset_schema_cache()
    exp_index.resetIndex()


class _FakeIndex:
    def __init__(self): self.rows = []
    def addPair(self, uid, vec, payload): self.rows.append((uid, list(vec), dict(payload)))
    def query(self, vec, k, threshold):
        import math
        def cos(a, b):
            d = sum(x*y for x, y in zip(a, b))
            na = math.sqrt(sum(x*x for x in a)); nb = math.sqrt(sum(y*y for y in b))
            return d/(na*nb) if na and nb else 0.0
        s = [{"uid": u, "score": cos(vec, v), "payload": p} for u, v, p in self.rows]
        s = [x for x in s if x["score"] >= threshold]
        s.sort(key=lambda x: x["score"], reverse=True)
        return s[:k]
    def persist(self): pass


def test_retrieve_content_uses_index_when_it_returns_hits(db, monkeypatch):
    fake = _FakeIndex()
    fake.addPair("r1::st-1", [1.0, 0.0, 0.0], {"run_id": "r1", "st_id": "st-1", "title": "x"})
    experience_content.recordSolutionContent("r1", "st-1", solution_content="indexed answer",
                                             post_mortem="", importance=1.0, model_id="m", db_path=db)
    monkeypatch.setattr(exp_index, "getIndex", lambda: fake)
    with mock.patch.object(retrieval, "_embed_call", return_value=[1.0, 0.0, 0.0]):
        hits = retrieval.retrieve_content("g", "t", db_path=db)
    assert hits and hits[0]["solution_content"] == "indexed answer"


def test_retrieve_content_falls_back_to_scan_on_empty_index(db, monkeypatch):
    experience.record_subtask("r1", {"subtask_id": "st-2", "title": "scan", "status": "done",
                                     "verify_result": {"passed": True}, "session": {"attempts": 1}}, db_path=db)
    experience.set_subtask_embedding("r1", "st-2", retrieval.pack([1.0, 0.0]), db_path=db)
    experience_content.recordSolutionContent("r1", "st-2", solution_content="scanned answer",
                                             post_mortem="", importance=1.0, model_id="m", db_path=db)
    monkeypatch.setattr(exp_index, "getIndex", lambda: exp_index.NullIndex())
    with mock.patch.object(retrieval, "_embed_call", return_value=[1.0, 0.0]):
        hits = retrieval.retrieve_content("g", "t", db_path=db)
    assert hits and hits[0]["solution_content"] == "scanned answer"


def test_embed_and_store_seeds_index(db, monkeypatch):
    fake = _FakeIndex()
    monkeypatch.setattr(exp_index, "getIndex", lambda: fake)
    experience.record_subtask("r1", {"subtask_id": "st-3", "title": "seed", "status": "done",
                                     "verify_result": {"passed": True}, "session": {"attempts": 1}}, db_path=db)
    with mock.patch.object(retrieval, "_embed_call", return_value=[0.3, 0.4, 0.5]):
        assert retrieval.embed_and_store("r1", "st-3", "goal", "seed", db_path=db) is True
    assert any(uid == "r1::st-3" for uid, _, _ in fake.rows)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_retrieval_index_wire.py -v`
Expected: FAIL — `test_retrieve_content_uses_index_when_it_returns_hits` (index branch not wired yet).

- [ ] **Step 3: Write minimal implementation**

In `memory/retrieval.py`, add the import alongside the others (after `from memory import experience_content`):

```python
from memory import exp_index
```

Add a `uid` helper near `signature_text` (after `:132`):

```python
def _uid(run_id: str, st_id: str) -> str:
    """Stable index id for a subtask (collision-free across runs)."""
    return f"{run_id}::{st_id}"
```

Replace the body of `retrieve_content` (Task 4) so the index is tried first, scan is the fallback:

```python
def retrieve_content(goal: str, title: str = "", *, k: Optional[int] = None,
                     db_path: Optional[Path] = None) -> list[dict[str, Any]]:
    """Embed the query, look up the ANN index (fallback: O(n) scan), and JOIN each hit to
    its exp_content row. Best-effort: empty list on any failure."""
    qvec = embed(signature_text(goal, title))
    if not qvec:
        return []
    k = k or config.RETRIEVAL_K
    floor = float(getattr(config, "RETRIEVAL_MIN_SCORE", 0.0) or 0.0)
    neighbors: list[dict[str, Any]] = []
    try:
        hits = exp_index.getIndex().query(qvec, k, floor)
    except Exception:  # noqa: BLE001 -- a broken index never blocks retrieval
        hits = []
    if hits:
        for h in hits:
            payload = dict(h.get("payload") or {})
            payload["score"] = h.get("score")
            payload.setdefault("uid", h.get("uid"))
            neighbors.append(payload)
    else:
        neighbors = top_k_similar(qvec, k, db_path=db_path)
    for n in neighbors:
        row = experience_content.fetchSolutionContent(
            n.get("run_id"), n.get("st_id"), db_path=db_path)
        if row:
            n["solution_content"] = row.get("solution_content")
            n["post_mortem"] = row.get("post_mortem")
            n["created_at"] = row.get("created_at")
            if row.get("importance") is not None:
                n["importance"] = row.get("importance")
    return neighbors
```

Seed the index in `embed_and_store` (`:135`) — replace its body:

```python
def embed_and_store(run_id: str, st_id: str, goal: str, title: str = "",
                    db_path: Optional[Path] = None) -> bool:
    """Compute + persist a subtask's embedding AND seed the ANN index (derived cache; the
    BLOB column stays source of truth). Best-effort."""
    vec = embed(signature_text(goal, title))
    if not vec:
        return False
    ok = experience.set_subtask_embedding(run_id, st_id, pack(vec), db_path=db_path)
    try:
        exp_index.getIndex().addPair(_uid(run_id, st_id), vec,
                                     {"run_id": run_id, "st_id": st_id, "title": title})
    except Exception as e:  # noqa: BLE001
        LOG.debug("index seed skipped (ignored): %s", e)
    return ok
```

In `backfill_embeddings` (`:218`), after the existing `experience.set_subtask_embedding(...)` line (`:234`), also seed the index:

```python
        experience.set_subtask_embedding(row["run_id"], row["st_id"], pack(vec), db_path=db_path)
        try:
            exp_index.getIndex().addPair(
                _uid(row["run_id"], row["st_id"]), vec,
                {"run_id": row["run_id"], "st_id": row["st_id"], "title": row.get("title") or ""})
        except Exception as e:  # noqa: BLE001
            LOG.debug("backfill index seed skipped (ignored): %s", e)
        embedded += 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_retrieval_index_wire.py tests/test_retrieval.py tests/test_retrieval_content.py -v`
Expected: PASS (index wire + both existing retrieval suites still green).

- [ ] **Step 5: Commit**

```bash
git add memory/retrieval.py tests/test_retrieval_index_wire.py
git commit -m "feat(memory): retrieve via ANN index with O(n) scan fallback; seed on embed/backfill"
```

---

## Task 8: Rerank config consts + `memory/retrieval_rank.py` (pure functions)

**Files:**
- Modify: `platform_core/app_config/llm.py` — already added `RETRIEVAL_W_*` / `RETRIEVAL_RECENCY_HALFLIFE_DAYS`? No — add them here
- Create: `memory/retrieval_rank.py`
- Test: `tests/test_retrieval_rank.py`

- [ ] **Step 1: Write the failing test**

```python
"""rerank: recency + importance + relevance, pure functions, fail-open on bad input."""
from datetime import datetime, timedelta, timezone

import config
from memory import retrieval_rank


def _now():
    return datetime(2026, 6, 30, 12, 0, 0, tzinfo=timezone.utc)


def test_recent_high_importance_outranks_old_nearest_cosine():
    now = _now()
    old_best_cosine = {"st_id": "old", "score": 0.99, "importance": 1.0,
                       "created_at": (now - timedelta(days=120)).isoformat()}
    recent_important = {"st_id": "new", "score": 0.80, "importance": 4.0,
                        "created_at": (now - timedelta(days=1)).isoformat()}
    ranked = retrieval_rank.rerank([old_best_cosine, recent_important], now=now)
    assert ranked[0]["st_id"] == "new"
    assert "_rank_score" in ranked[0]


def test_rerank_is_stable_when_signals_tie():
    now = _now()
    a = {"st_id": "a", "score": 0.5, "importance": 1.0, "created_at": now.isoformat()}
    b = {"st_id": "b", "score": 0.5, "importance": 1.0, "created_at": now.isoformat()}
    ranked = retrieval_rank.rerank([a, b], now=now)
    assert {r["st_id"] for r in ranked} == {"a", "b"}


def test_rerank_failopen_returns_input_on_garbage():
    bad = [{"st_id": "x", "score": "not-a-number", "created_at": 12345, "importance": None}]
    out = retrieval_rank.rerank(bad, now=_now())
    assert out == bad or out[0]["st_id"] == "x"   # never raises


def test_rerank_empty_is_empty():
    assert retrieval_rank.rerank([], now=_now()) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_retrieval_rank.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'memory.retrieval_rank'`.

- [ ] **Step 3: Write minimal implementation**

In `platform_core/app_config/llm.py`, add after the ANN consts (Task 5):

```python
# Layer-1 rerank weights (gen-agents new_retrieve port: relevance-heavy [0.5, 3, 2]).
RETRIEVAL_W_RECENCY: float = _envFloat("RETRIEVAL_W_RECENCY", 0.5)
RETRIEVAL_W_IMPORTANCE: float = _envFloat("RETRIEVAL_W_IMPORTANCE", 3.0)
RETRIEVAL_W_RELEVANCE: float = _envFloat("RETRIEVAL_W_RELEVANCE", 2.0)
RETRIEVAL_RECENCY_HALFLIFE_DAYS: float = _envFloat("RETRIEVAL_RECENCY_HALFLIFE_DAYS", 14)
```

Create `memory/retrieval_rank.py`:

```python
"""Recency + Importance + Relevance rerank for Layer-1 retrieval (gen-agents port, Apache-2.0).

Pure functions, no embedder/DB needed. ``rerank`` computes three min-max-normalized signals
per candidate and a weighted sum, then sorts descending. Fail-open: any error returns the
candidates in their incoming order.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  rerank(candidates, *, now=None, w_recency=None, w_importance=None, w_relevance=None) -> list[dict]
DEPENDS-ON: config
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/test_retrieval_rank.py
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import config


def _parseTs(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:  # noqa: BLE001
        return None


def _recencyScore(created_at: Any, now: datetime, halflife_days: float) -> float:
    ts = _parseTs(created_at)
    if ts is None:
        return 0.0
    try:
        if ts.tzinfo is None and now.tzinfo is not None:
            ts = ts.replace(tzinfo=now.tzinfo)
        elif ts.tzinfo is not None and now.tzinfo is None:
            ts = ts.replace(tzinfo=None)
        age_days = max(0.0, (now - ts).total_seconds() / 86400.0)
    except Exception:  # noqa: BLE001
        return 0.0
    return 0.5 ** (age_days / max(halflife_days, 1e-4))


def _minmax(values: list[float]) -> list[float]:
    if not values:
        return values
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5 for _ in values]      # all-equal -> neutral, never divide-by-zero
    return [(v - lo) / (hi - lo) for v in values]


def _asFloat(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def rerank(candidates: list[dict[str, Any]], *, now: Optional[datetime] = None,
           w_recency: Optional[float] = None, w_importance: Optional[float] = None,
           w_relevance: Optional[float] = None) -> list[dict[str, Any]]:
    """Sort candidates by weighted (recency, importance, relevance). Fail-open: returns the
    input unchanged on any error."""
    if not candidates:
        return candidates
    try:
        now = now or datetime.now().astimezone()
        wr = config.RETRIEVAL_W_RECENCY if w_recency is None else w_recency
        wi = config.RETRIEVAL_W_IMPORTANCE if w_importance is None else w_importance
        wv = config.RETRIEVAL_W_RELEVANCE if w_relevance is None else w_relevance
        hl = config.RETRIEVAL_RECENCY_HALFLIFE_DAYS
        rec = [_recencyScore(c.get("created_at"), now, hl) for c in candidates]
        imp = [_asFloat(c.get("importance")) for c in candidates]
        rel = [_asFloat(c.get("score")) for c in candidates]
        rec_n, imp_n, rel_n = _minmax(rec), _minmax(imp), _minmax(rel)
        out: list[dict[str, Any]] = []
        for c, a, b, d in zip(candidates, rec_n, imp_n, rel_n):
            ranked = dict(c)
            ranked["_rank_score"] = wr * a + wi * b + wv * d
            out.append(ranked)
        out.sort(key=lambda r: r["_rank_score"], reverse=True)
        return out
    except Exception:  # noqa: BLE001
        return candidates
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_retrieval_rank.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add memory/retrieval_rank.py platform_core/app_config/llm.py tests/test_retrieval_rank.py
git commit -m "feat(memory): recency+importance+relevance rerank (pure functions)"
```

---

## Task 9: Apply `rerank` inside `retrieve_content`

**Files:**
- Modify: `memory/retrieval.py` — call `retrieval_rank.rerank` after the content join, before returning
- Test: `tests/test_retrieval_rerank_wire.py`

- [ ] **Step 1: Write the failing test**

```python
"""retrieve_content must rerank by recency+importance+relevance after joining content."""
import pytest
from unittest import mock
from datetime import datetime, timedelta, timezone

import config
from memory import exp_index, experience, experience_content, retrieval


@pytest.fixture()
def db(tmp_path, monkeypatch):
    p = tmp_path / "experience.db"
    monkeypatch.setattr(config, "EXPERIENCE_DB_PATH", p, raising=False)
    monkeypatch.setattr(config, "EXPERIENCE_LEDGER_ENABLED", True, raising=False)
    experience._reset_schema_cache()
    retrieval.reset_embed_cache()
    exp_index.resetIndex()
    experience.init(db_path=p)
    yield p
    experience._reset_schema_cache()
    exp_index.resetIndex()


def test_recent_important_row_floats_above_older_nearest_cosine(db, monkeypatch):
    now = datetime.now(timezone.utc)
    # OLD row: near-perfect cosine but stale + low importance.
    experience.record_subtask("r1", {"subtask_id": "old", "title": "old", "status": "done",
                                     "verify_result": {"passed": True}, "session": {"attempts": 1}}, db_path=db)
    experience.set_subtask_embedding("r1", "old", retrieval.pack([1.0, 0.0, 0.0]), db_path=db)
    experience_content.recordSolutionContent("r1", "old", solution_content="OLD answer",
                                             post_mortem="", importance=1.0, model_id="m", db_path=db)
    # NEW row: slightly worse cosine but recent + high importance.
    experience.record_subtask("r1", {"subtask_id": "new", "title": "new", "status": "done",
                                     "verify_result": {"passed": True}, "session": {"attempts": 1}}, db_path=db)
    experience.set_subtask_embedding("r1", "new", retrieval.pack([0.9, 0.1, 0.0]), db_path=db)
    experience_content.recordSolutionContent("r1", "new", solution_content="NEW answer",
                                             post_mortem="", importance=5.0, model_id="m", db_path=db)
    # Force created_at: old=120d ago, new=1d ago.
    with experience._connect(db) as conn:
        conn.execute("UPDATE exp_content SET created_at=? WHERE st_id='old'",
                     ((now - timedelta(days=120)).isoformat(),))
        conn.execute("UPDATE exp_content SET created_at=? WHERE st_id='new'",
                     ((now - timedelta(days=1)).isoformat(),))
    monkeypatch.setattr(exp_index, "getIndex", lambda: exp_index.NullIndex())  # use the scan path
    with mock.patch.object(retrieval, "_embed_call", return_value=[1.0, 0.0, 0.0]):
        hits = retrieval.retrieve_content("g", "t", db_path=db)
    assert hits[0]["solution_content"] == "NEW answer"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_retrieval_rerank_wire.py -v`
Expected: FAIL — `hits[0]` is `"OLD answer"` (still pure cosine order).

- [ ] **Step 3: Write minimal implementation**

In `memory/retrieval.py`, add the import (after `from memory import exp_index`):

```python
from memory import retrieval_rank
```

In `retrieve_content`, insert the rerank + final truncation immediately before `return neighbors`:

```python
    neighbors = retrieval_rank.rerank(neighbors)
    return neighbors[:k]
```

(The content-join loop already populated `created_at` / `importance` / `score`, which `rerank` consumes.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_retrieval_rerank_wire.py tests/test_retrieval_content.py tests/test_retrieval_index_wire.py -v`
Expected: PASS (rerank wire + both prior retrieval suites still green).

- [ ] **Step 5: Commit**

```bash
git add memory/retrieval.py tests/test_retrieval_rerank_wire.py
git commit -m "feat(memory): rerank retrieved content by recency+importance+relevance"
```

---

## Task 10: Compaction config consts + `shouldCompact` + `MUST_PRESERVE_CONTRACT`

**Files:**
- Modify: `platform_core/app_config/llm.py` — add `COMPACTION_*` consts
- Create: `platform_core/orchestration/compaction.py` (`_approxTokens`, `shouldCompact`, `MUST_PRESERVE_CONTRACT`)
- Test: `tests/test_compaction.py`

- [ ] **Step 1: Write the failing test**

```python
"""Compaction trigger math + MUST-PRESERVE contract presence."""
import config
from platform_core.orchestration import compaction


def test_should_compact_false_for_small_payload():
    assert compaction.shouldCompact("sys", "tiny user", num_ctx=8192, headroom=2048) is False


def test_should_compact_true_when_over_window_budget():
    big = "x" * (8192 * 4)      # ~8192 tokens of user alone, well past the trigger
    assert compaction.shouldCompact("sys", big, num_ctx=8192, headroom=2048) is True


def test_should_compact_is_window_aware():
    mid = "x" * (4096 * 4)
    # Same payload trips the trigger at a small window but not a large one.
    assert compaction.shouldCompact("s", mid, num_ctx=4096, headroom=512) is True
    assert compaction.shouldCompact("s", mid, num_ctx=32768, headroom=512) is False


def test_must_preserve_contract_lists_identifiers():
    c = compaction.MUST_PRESERVE_CONTRACT.lower()
    for token in ("file path", "function", "error", "goal", "todo"):
        assert token in c
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_compaction.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'platform_core.orchestration.compaction'`.

- [ ] **Step 3: Write minimal implementation**

In `platform_core/app_config/llm.py`, add after the rerank consts (Task 8):

```python
# Layer-2 hierarchical compaction (eliza model-input-budget + agentscope compress + openclaw
# rubric). Default OFF: the summarizer's extra latency/cost is opt-in until measured. num_ctx is
# NEVER resized -- compaction trims the PAYLOAD to fit the fixed OLLAMA_NUM_CTX window.
COMPACTION_ENABLED: bool = _envBool("COMPACTION_ENABLED", False)
COMPACTION_TRIGGER_RATIO: float = _envFloat("COMPACTION_TRIGGER_RATIO", 0.85)
COMPACTION_RESERVE_RATIO: float = _envFloat("COMPACTION_RESERVE_RATIO", 0.4)
COMPACTION_RESERVE_FLOOR: int = _envInt("COMPACTION_RESERVE_FLOOR", 1024)
COMPACTION_MAX_PASSES: int = _envInt("COMPACTION_MAX_PASSES", 3)
COMPACTION_OFFLOAD_DIR: str = os.getenv("COMPACTION_OFFLOAD_DIR", "state/compaction")
```

Create `platform_core/orchestration/compaction.py` (Tasks 10+11 fill it; this task adds the trigger + contract):

```python
"""Hierarchical context compaction for the fixed-window brain payload.

The Ollama window (config.OLLAMA_NUM_CTX) is NEVER resized -- that pinning is the documented
fix for the reload/empty-completion storm. This module CONDENSES an over-long user payload to
fit the fixed window: summarize the oldest half into a MUST-PRESERVE summary, offload the raw
to disk with a breadcrumb, and on ANY failure fall back to brain_io._fitUserToCtx (today's
exact blind truncation). Ports: eliza model-input-budget (trigger), agentscope
_compress_context_impl (split/compress), openclaw MUST-PRESERVE rubric.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  MUST_PRESERVE_CONTRACT  -- summary rubric const.
  shouldCompact(system, user, num_ctx, headroom) -> bool  -- window-aware token-budget trigger.
  compactPayload(system, user, num_ctx, headroom, *, summarize, offload_dir=None) -> str
  fitOrCompact(system, user, num_ctx, headroom, *, summarize=None) -> str  -- the llm_mixin seam.
DEPENDS-ON: config, platform_core.orchestration.brain_io
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/test_compaction.py
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Optional

import config

LOG = config.getLogger("orchestrator.compaction")

MUST_PRESERVE_CONTRACT: str = (
    "You are compacting earlier context for a fixed-window model. Produce a DENSE summary that "
    "MUST PRESERVE, verbatim where they appear: the active goal and its status; batch/subtask "
    "progress; the last request; every decision and its rationale; all open TODOs; and ALL exact "
    "file paths, function/class/constant names, commands, and error strings. Drop only redundant "
    "prose. Output the summary only -- no preamble."
)


def _approxTokens(text: str) -> int:
    """Cheap token estimate (~4 chars/token), matching brain_io's budgeting convention."""
    return max(1, len(text) // 4)


def shouldCompact(system: str, user: str, num_ctx: int, headroom: int) -> bool:
    """True when system+user is estimated to exceed the window budget (eliza model-input-budget).
    Window-aware: the budget scales with num_ctx, reserving room for the reply."""
    reserve = max(int(getattr(config, "COMPACTION_RESERVE_FLOOR", 1024)), int(headroom))
    budget = int(num_ctx * float(getattr(config, "COMPACTION_TRIGGER_RATIO", 0.85))) - reserve
    if budget <= 0:
        return True
    return (_approxTokens(system) + _approxTokens(user)) > budget
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_compaction.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/compaction.py platform_core/app_config/llm.py tests/test_compaction.py
git commit -m "feat(orchestration): compaction trigger + MUST-PRESERVE contract"
```

---

## Task 11: `compactPayload` + `fitOrCompact` (summarize, offload, drop-oldest fallback)

**Files:**
- Modify: `platform_core/orchestration/compaction.py` — add `_splitForCompression`, `_writeOffload`, `compactPayload`, `fitOrCompact`
- Test: `tests/test_compaction.py` (extend)

- [ ] **Step 1: Write the failing test (append to `tests/test_compaction.py`)**

```python
import re
from pathlib import Path

import pytest


def _identifier_summary(text):
    # A stub summarizer that preserves identifiers (paths, fn names) like the real contract.
    ids = re.findall(r"[\w/\\.]+\.py|\w+\(\)|Error\w*", text)
    return "SUMMARY keeps: " + " ".join(sorted(set(ids)))


def test_compact_payload_preserves_identifiers_and_offloads(tmp_path):
    raw_old = ("Earlier: edited memory/retrieval.py and called retrieve_content() ; hit "
               "TimeoutError once. " * 400)
    newest = "NEWEST: now finalize the patch in platform_core/orchestration/compaction.py"
    user = raw_old + newest
    out = compaction.compactPayload("sys", user, num_ctx=8192, headroom=2048,
                                    summarize=_identifier_summary, offload_dir=str(tmp_path))
    assert "memory/retrieval.py" in out                 # MUST-PRESERVE identifier survived
    assert "retrieve_content()" in out
    assert newest in out                                 # newest reserve-half kept verbatim
    assert "[raw context offloaded to" in out
    files = list(Path(tmp_path).glob("ctx-*.txt"))
    assert files and "TimeoutError" in files[0].read_text(encoding="utf-8")


def test_compact_payload_drops_to_truncation_when_summarize_raises(tmp_path):
    user = "x" * (8192 * 4)
    def boom(_): raise RuntimeError("summarizer down")
    out = compaction.compactPayload("sys", user, num_ctx=8192, headroom=2048,
                                    summarize=boom, offload_dir=str(tmp_path))
    assert "context trimmed to fit the model window" in out   # brain_io._fitUserToCtx marker


def test_compact_payload_drops_to_truncation_when_summary_empty(tmp_path):
    user = "x" * (8192 * 4)
    out = compaction.compactPayload("sys", user, num_ctx=8192, headroom=2048,
                                    summarize=lambda _: "", offload_dir=str(tmp_path))
    assert "context trimmed to fit the model window" in out


def test_fit_or_compact_is_noop_passthrough_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "COMPACTION_ENABLED", False, raising=False)
    out = compaction.fitOrCompact("sys", "small", num_ctx=8192, headroom=2048,
                                  summarize=lambda _: "S")
    assert out == "small"


def test_fit_or_compact_uses_truncation_when_no_summarizer(monkeypatch):
    monkeypatch.setattr(config, "COMPACTION_ENABLED", True, raising=False)
    big = "x" * (8192 * 4)
    out = compaction.fitOrCompact("sys", big, num_ctx=8192, headroom=2048, summarize=None)
    assert "context trimmed to fit the model window" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_compaction.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'compactPayload'`.

- [ ] **Step 3: Write minimal implementation (append to `compaction.py`)**

```python
def _splitForCompression(user: str) -> tuple[str, str]:
    """Split into (compress_half=oldest, reserve_half=newest). The newest
    COMPACTION_RESERVE_RATIO fraction is kept verbatim; the older remainder is condensed."""
    ratio = float(getattr(config, "COMPACTION_RESERVE_RATIO", 0.4))
    reserve_chars = int(len(user) * max(0.0, min(ratio, 0.9)))
    if reserve_chars <= 0:
        return user, ""
    return user[:-reserve_chars], user[-reserve_chars:]


def _writeOffload(raw: str, offload_dir: str) -> Optional[str]:
    """Persist the raw compress-half to disk; return its path (or None on failure)."""
    try:
        d = Path(offload_dir)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"ctx-{int(time.time() * 1000)}-{os.getpid()}.txt"
        path.write_text(raw, encoding="utf-8")
        return str(path)
    except Exception as e:  # noqa: BLE001
        LOG.debug("offload write skipped (ignored): %s", e)
        return None


def compactPayload(system: str, user: str, num_ctx: int, headroom: int, *,
                   summarize: Callable[[str], str], offload_dir: Optional[str] = None) -> str:
    """Condense the oldest half into a MUST-PRESERVE summary + offload the raw with a
    breadcrumb. Drop-oldest fallback: on empty/raising summarize, or if the result still
    overflows, return brain_io._fitUserToCtx (today's exact truncation)."""
    from platform_core.orchestration.brain_io import _fitUserToCtx
    try:
        compress_half, reserve_half = _splitForCompression(user)
        if not compress_half.strip():
            return _fitUserToCtx(system, user, num_ctx, headroom)
        try:
            summary = summarize(compress_half) or ""
        except Exception as e:  # noqa: BLE001 -- summarizer failure -> safety net
            LOG.debug("summarize raised, falling back to truncation: %s", e)
            return _fitUserToCtx(system, user, num_ctx, headroom)
        if not summary.strip():
            return _fitUserToCtx(system, user, num_ctx, headroom)
        path = _writeOffload(compress_half, offload_dir or config.COMPACTION_OFFLOAD_DIR)
        breadcrumb = f"\n[raw context offloaded to {path}]\n" if path else ""
        compacted = ("## CONDENSED EARLIER CONTEXT (MUST-PRESERVE summary)\n"
                     + summary.strip() + breadcrumb + "\n" + reserve_half)
        if shouldCompact(system, compacted, num_ctx, headroom):
            # Even the summary overflows -> fall back to truncation of the compacted text.
            return _fitUserToCtx(system, compacted, num_ctx, headroom)
        return compacted
    except Exception as e:  # noqa: BLE001 -- a bug here must never block a brain call
        LOG.debug("compactPayload failed, truncating: %s", e)
        return _fitUserToCtx(system, user, num_ctx, headroom)


def fitOrCompact(system: str, user: str, num_ctx: int, headroom: int, *,
                 summarize: Optional[Callable[[str], str]] = None) -> str:
    """The llm_mixin seam. Returns user bounded by _fitUserToCtx when small or when compaction
    is disabled/unavailable; compacts only when enabled AND over budget AND a summarizer is
    provided. Never raises into the brain call."""
    from platform_core.orchestration.brain_io import _fitUserToCtx
    try:
        if not getattr(config, "COMPACTION_ENABLED", False) or summarize is None:
            return _fitUserToCtx(system, user, num_ctx, headroom)
        if not shouldCompact(system, user, num_ctx, headroom):
            return _fitUserToCtx(system, user, num_ctx, headroom)
        return compactPayload(system, user, num_ctx, headroom, summarize=summarize)
    except Exception as e:  # noqa: BLE001
        LOG.debug("fitOrCompact failed, truncating: %s", e)
        return _fitUserToCtx(system, user, num_ctx, headroom)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_compaction.py -v`
Expected: PASS (all compaction tests).

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/compaction.py tests/test_compaction.py
git commit -m "feat(orchestration): compactPayload + fitOrCompact with offload + truncation fallback"
```

---

## Task 12: Wire `_ollamaChat` to `fitOrCompact` + `_summarizeForCompaction` (num_ctx STAYS FIXED)

**Files:**
- Modify: `platform_core/orchestration/llm_mixin.py:18` (import), `:99-100` (seam swap), add `_summarizeForCompaction` + circuit-breaker state
- Test: `tests/test_llm_compaction_numctx.py`

- [ ] **Step 1: Write the failing test**

```python
"""CRITICAL regression guard: num_ctx is config.OLLAMA_NUM_CTX on EVERY ollama.chat, even
when compaction + its summarizer fire. Protects the reload-storm fix."""
import pytest

import config
from platform_core.orchestration import llm_mixin
from platform_core.orchestration.llm_mixin import OrchestratorLlmMixin


class _RecordingOllama:
    def __init__(self):
        self.calls = []

    def chat(self, *, model, messages, **kwargs):
        self.calls.append(kwargs)
        return {"message": {"content": '{"ok": 1}'}}


class _Orch(OrchestratorLlmMixin):
    def __init__(self, ollama):
        self.ollama = ollama
        self._brain_tag_override = None
        self._compaction_fail_streak = 0


@pytest.fixture(autouse=True)
def _stub_caps(monkeypatch):
    # injectCapabilities reads the live knowledge base; stub to identity for hermeticity.
    monkeypatch.setattr(llm_mixin, "injectCapabilities", lambda s: s)


def test_numctx_fixed_on_every_call_even_with_compaction(monkeypatch):
    monkeypatch.setattr(config, "COMPACTION_ENABLED", True, raising=False)
    rec = _RecordingOllama()
    orch = _Orch(rec)
    huge_user = "x" * (config.OLLAMA_NUM_CTX * 5)        # forces compaction + a summarizer call
    resp = orch._ollamaChat("system prompt", huge_user, want_json=True)
    assert resp is not None
    assert rec.calls, "ollama.chat was never called"
    for kw in rec.calls:
        assert kw["options"]["num_ctx"] == config.OLLAMA_NUM_CTX   # NEVER per-prompt sized


def test_summarize_circuit_breaker_stops_after_max_passes(monkeypatch):
    monkeypatch.setattr(config, "COMPACTION_MAX_PASSES", 2, raising=False)

    class _Empty:
        def chat(self, *, model, messages, **kwargs):
            return {"message": {"content": ""}}      # always-empty summary -> failure

    orch = _Orch(_Empty())
    orch._compaction_fail_streak = config.COMPACTION_MAX_PASSES   # breaker already tripped
    assert orch._summarizeForCompaction("anything") == ""        # short-circuits, no call
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_llm_compaction_numctx.py -v`
Expected: FAIL — `AttributeError: ... has no attribute '_summarizeForCompaction'`.

- [ ] **Step 3: Write minimal implementation**

In `platform_core/orchestration/llm_mixin.py`, change the import line (`:18`):

```python
from platform_core.orchestration.brain_io import _chatJson, _chatText, _fitUserToCtx
from platform_core.orchestration import compaction
```

Replace the fit seam at `:100`:

```python
        num_ctx = config.OLLAMA_NUM_CTX
        user = compaction.fitOrCompact(system, user, num_ctx, config.OLLAMA_GEN_HEADROOM,
                                       summarize=self._summarizeForCompaction)
```

Add `_summarizeForCompaction` as a new method on `OrchestratorLlmMixin` (place it directly after `_ollamaChat`, before `_resolveClarifications`):

```python
    def _summarizeForCompaction(self, text: str) -> str:
        """Summarize the oldest payload half for compaction. CRITICAL: calls ollama.chat
        DIRECTLY at the SAME fixed num_ctx (never via _ollamaChat -> no recursion into
        fitOrCompact) and never resizes the window. A circuit breaker (COMPACTION_MAX_PASSES
        consecutive failures) stops a doomed summarize-retry loop; on trip it returns "" so
        compactPayload falls back to truncation."""
        if getattr(self, "_compaction_fail_streak", 0) >= config.COMPACTION_MAX_PASSES:
            return ""
        num_ctx = config.OLLAMA_NUM_CTX
        sys_prompt = compaction.MUST_PRESERVE_CONTRACT
        bounded = _fitUserToCtx(sys_prompt, text, num_ctx, config.OLLAMA_GEN_HEADROOM)
        try:
            from learning import finetune
            model = getattr(self, "_brain_tag_override", None) or finetune.active_brain_tag()
        except Exception:  # noqa: BLE001
            model = config.OLLAMA_MODEL
        try:
            resp = self.ollama.chat(
                model=model,
                messages=[{"role": "system", "content": sys_prompt},
                          {"role": "user", "content": bounded}],
                options={"num_ctx": num_ctx}, keep_alive=config.OLLAMA_KEEP_ALIVE)
            out = _chatText(resp).strip()
            if not out:
                self._compaction_fail_streak = getattr(self, "_compaction_fail_streak", 0) + 1
                return ""
            self._compaction_fail_streak = 0
            return out
        except Exception as e:  # noqa: BLE001
            LOG.debug("compaction summarize failed (ignored): %s", e)
            self._compaction_fail_streak = getattr(self, "_compaction_fail_streak", 0) + 1
            return ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_llm_compaction_numctx.py -v`
Expected: PASS (both tests; num_ctx fixed on every recorded call).

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/llm_mixin.py tests/test_llm_compaction_numctx.py
git commit -m "feat(orchestration): compaction at the fit seam; num_ctx stays pinned + circuit breaker"
```

---

## Task 13: Optional reflection consolidation (`memory/reflection_consolidate.py`, default OFF)

**Files:**
- Modify: `platform_core/app_config/llm.py` — add `REFLECTION_CONSOLIDATE_ENABLED`
- Create: `memory/reflection_consolidate.py`
- Test: `tests/test_reflection_consolidate.py`

- [ ] **Step 1: Write the failing test**

```python
"""Importance-triggered consolidation: OFF by default, writes cited principles when ON."""
import pytest

import config
from memory import experience, experience_content, reflection_consolidate


@pytest.fixture()
def db(tmp_path, monkeypatch):
    p = tmp_path / "experience.db"
    monkeypatch.setattr(config, "EXPERIENCE_DB_PATH", p, raising=False)
    monkeypatch.setattr(config, "EXPERIENCE_LEDGER_ENABLED", True, raising=False)
    experience._reset_schema_cache()
    experience.init(db_path=p)
    yield p
    experience._reset_schema_cache()


def test_disabled_by_default_is_noop(db, monkeypatch):
    monkeypatch.setattr(config, "REFLECTION_CONSOLIDATE_ENABLED", False, raising=False)
    out = reflection_consolidate.maybeConsolidate(db_path=db)
    assert out == {"consolidated": 0}
    assert experience.fetch_reflections(db_path=db) == []


def test_below_budget_does_not_fire(db, monkeypatch):
    monkeypatch.setattr(config, "REFLECTION_CONSOLIDATE_ENABLED", True, raising=False)
    experience_content.recordSolutionContent("r1", "st-1", solution_content="small",
                                             post_mortem="", importance=0.5, model_id="m", db_path=db)
    out = reflection_consolidate.maybeConsolidate(db_path=db, importance_budget=10.0)
    assert out == {"consolidated": 0}


def test_crossing_budget_writes_cited_principle(db, monkeypatch):
    monkeypatch.setattr(config, "REFLECTION_CONSOLIDATE_ENABLED", True, raising=False)
    for i in range(5):
        experience_content.recordSolutionContent(
            "r1", f"st-{i}", solution_content=f"used pattern P{i}",
            post_mortem=f"lesson {i}", importance=3.0, model_id="m", db_path=db)
    out = reflection_consolidate.maybeConsolidate(db_path=db, importance_budget=5.0)
    assert out["consolidated"] >= 1
    refl = experience.fetch_reflections(db_path=db)
    assert refl and refl[0]["role"] == "consolidator"
    assert "st-" in (refl[0]["reusable_recipe"] or "")   # source-cited
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_reflection_consolidate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'memory.reflection_consolidate'`.

- [ ] **Step 3: Write minimal implementation**

In `platform_core/app_config/llm.py`, add after the compaction consts (Task 10):

```python
# Optional episodic->semantic consolidation (gen-agents reflect.py). Default OFF, runs off the
# hot path inside SIE post-run maintenance; never blocks the core retrieval steal.
REFLECTION_CONSOLIDATE_ENABLED: bool = _envBool("REFLECTION_CONSOLIDATE_ENABLED", False)
```

Create `memory/reflection_consolidate.py`:

```python
"""Importance-triggered episodic->semantic consolidation (gen-agents reflect.py port, Apache-2.0).

When accumulated importance of recent exp_content rows crosses a budget, abstract them into a
few SOURCE-CITED principles written to the existing ``reflections`` table. Off the hot path,
gated by REFLECTION_CONSOLIDATE_ENABLED (default OFF). Best-effort: any error is swallowed.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  maybeConsolidate(*, db_path=None, importance_budget=None) -> dict  -- {"consolidated": int}
DEPENDS-ON: config, memory.experience_schema
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/test_reflection_consolidate.py
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import config
from memory.experience_schema import LOG, _connect

_DEFAULT_BUDGET = 12.0


def _recentContent(db_path: Optional[Path]) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM exp_content ORDER BY created_at DESC LIMIT 50")
        return [dict(r) for r in rows]


def maybeConsolidate(*, db_path: Optional[Path] = None,
                     importance_budget: Optional[float] = None) -> dict[str, int]:
    """Fire when accumulated importance crosses ``importance_budget``; write a cited principle
    per cluster into ``reflections``. No-op (and never raises) when disabled or below budget."""
    if not getattr(config, "REFLECTION_CONSOLIDATE_ENABLED", False):
        return {"consolidated": 0}
    budget = _DEFAULT_BUDGET if importance_budget is None else importance_budget
    try:
        from memory import experience_solutions
        rows = _recentContent(db_path)
        accumulated = sum(float(r.get("importance") or 0.0) for r in rows)
        if accumulated < budget or not rows:
            return {"consolidated": 0}
        # One abstracted, source-cited principle over the highest-importance evidence cluster.
        rows.sort(key=lambda r: float(r.get("importance") or 0.0), reverse=True)
        cluster = rows[:5]
        cited = ", ".join(f"{r.get('run_id')}::{r.get('st_id')}" for r in cluster)
        lessons = " | ".join((r.get("post_mortem") or r.get("solution_content") or "")[:120]
                             for r in cluster)
        run_id = cluster[0].get("run_id") or "consolidated"
        ok = experience_solutions.record_reflection(
            run_id=run_id, subtask_id="consolidated", role="consolidator",
            teacher="ollama", trusted=False, db_path=db_path,
            approach=lessons,
            reusable_recipe=f"Recurring principle from {cited}: {lessons}",
            confidence=0.5)
        return {"consolidated": 1 if ok else 0}
    except Exception as e:  # noqa: BLE001 -- consolidation never blocks
        LOG.debug("maybeConsolidate failed (ignored): %s", e)
        return {"consolidated": 0}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_reflection_consolidate.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add memory/reflection_consolidate.py platform_core/app_config/llm.py tests/test_reflection_consolidate.py
git commit -m "feat(memory): optional importance-triggered reflection consolidation (default OFF)"
```

---

## Task 14: Docs, repo-map, size audit, and full fast suite

**Files:**
- Modify: `AGENTS.md` (regenerated), `docs/MEMORY.md`, `docs/STATE.md`
- Verify: `tools/size_audit.py`, `tools/repo_map.py`, `tools/dev.py`

- [ ] **Step 1: Regenerate the navigation map**

Run: `python tools/repo_map.py`
Expected: `AGENTS.md` updated with rows for `memory/experience_content.py`, `memory/exp_index.py`, `memory/retrieval_rank.py`, `memory/reflection_consolidate.py`, `platform_core/orchestration/compaction.py`, and the new `retrieval.py` exports. No errors.

- [ ] **Step 2: Enforce modularity**

Run: `python tools/size_audit.py`
Expected: zero `must_split` violations. If `memory/retrieval.py` exceeds 450 lines, split the rendering helpers (`_sanitizeField`, `render_solutions`, `render_lessons`) into `memory/retrieval_render.py` and re-export from `retrieval.py` (preserve public names); re-run.

- [ ] **Step 3: Update human docs**

Add to `docs/STATE.md` a subsection describing the new `state/` artifacts:

```markdown
### Layer-1 / Layer-2 derived artifacts (Epic 3)
- `state/exp_index/` — ChromaDB ANN index (derived cache over `state/experience.db`; the
  embedding BLOB column stays source of truth; rebuild via `retrieval.backfill_embeddings`).
  Collection name pins `EMBED_MODEL`+dim so an embedder swap starts a fresh space.
- `state/compaction/ctx-*.txt` — raw context offloaded by the compaction layer; the brain
  payload carries a `[raw context offloaded to <path>]` breadcrumb. Safe to prune.
- New tables in `state/experience.db`: `exp_content` (solution_content/post_mortem/importance)
  and `subtasks.importance` (denormalized salience). All additive via CREATE-IF-NOT-EXISTS.
- Optional dependency: `chromadb` (Phase 2). Absent wheel -> `NullIndex` fail-open to the O(n)
  cosine scan; never required for a run.
```

Add to `docs/MEMORY.md` a one-line entry under the retrieval section noting that `lessons_block`
now injects real solution content (reranked recency+importance+relevance) and degrades to
metadata, all behind default-off flags (`ANN_INDEX_ENABLED`, `COMPACTION_ENABLED`,
`REFLECTION_CONSOLIDATE_ENABLED`).

- [ ] **Step 4: Run the focused + fast suites**

Run:
```bash
python tools/dev.py check memory/retrieval.py
python -m pytest tests/test_retrieval.py tests/test_retrieval_content.py tests/test_retrieval_index_wire.py tests/test_retrieval_rerank_wire.py tests/test_retrieval_rank.py tests/test_exp_index.py tests/test_experience_content.py tests/test_experience_content_sync.py tests/test_experience_schema_migration.py tests/test_compaction.py tests/test_llm_compaction_numctx.py tests/test_reflection_consolidate.py -v
python tools/dev.py fast
```
Expected: all green; `tools/dev.py fast` passes (no regressions in the existing ledger/retrieval/orchestrator suites).

- [ ] **Step 5: Commit**

```bash
git add AGENTS.md docs/STATE.md docs/MEMORY.md
git commit -m "docs(epic3): repo-map + state/memory notes for memory & context layer"
```

---

## Self-Review

**1. Spec coverage:**

| Spec section | Task |
|---|---|
| 3a-1 widen payload: `exp_content` table + `importance` migration | Task 1 |
| 3a-1 `experience_content.py` (`recordSolutionContent`/`fetchSolutionContent`) | Task 2 |
| 3a-1 content source at the sync/record site | Task 3 |
| 3a-2 `AnnIndex` Protocol + `NullIndex` + cached `getIndex` | Task 5 |
| 3a-2 `ChromaIndex` (our nomic vectors, collection name pins model+dim) | Task 6 |
| 3a-3 `retrieve_content` + `render_solutions`; `lessons_block` upgrade (signature preserved) | Tasks 4, 7 |
| 3a-3 index seeding in `embed_and_store` + `backfill_embeddings` | Task 7 |
| 3b rerank `retrieval_rank.py` (recency+importance+relevance) | Tasks 8, 9 |
| 3b reflection consolidation (optional, OFF) | Task 13 |
| 3c `shouldCompact` + `MUST_PRESERVE_CONTRACT` | Task 10 |
| 3c `compactPayload` + `fitOrCompact` + offload + drop-oldest fallback | Task 11 |
| 3c integration at `_ollamaChat`, fixed num_ctx, `_summarizeForCompaction`, circuit breaker | Task 12 |
| §5 config consts (all default-off/dark) | Tasks 4, 5, 8, 10, 13 |
| §6 fail-open + injection sanitization | Tasks 4 (`_sanitizeField`), 5/7 (NullIndex), 9/11/12 (fallbacks) |
| §7 tests incl. num_ctx-fixed assertion + migration test | Tasks 1, 12, all |
| §5 docs/repo-map/size-audit | Task 14 |

All spec requirements map to a task. The num_ctx-fixed regression assertion is Task 12 (`test_numctx_fixed_on_every_call_even_with_compaction`).

**2. Placeholder scan:** No `TODO`/`TBD`/"add error handling"/"similar to Task N" — every code step is complete. Fixed during review: Task 4 originally left `retrieve_content` without the index branch; that is intentional (Phase 1 has no dependency) and Task 7 rewrites the whole function body in full (not a diff), so the executor reading Task 7 alone still gets complete code.

**3. Type consistency check (fixed inline):**
- `getIndex()` / `resetIndex()` / `addPair` / `query(vec, k, threshold)` / `persist` — consistent across Tasks 5, 6, 7 and both `_FakeIndex` doubles.
- `query` returns `list[{uid, score, payload}]` everywhere; `retrieve_content` (Task 7) consumes exactly those keys.
- `recordSolutionContent(... importance=, model_id=)` and `fetchSolutionContent` returning a dict with `solution_content/post_mortem/importance/created_at` — consistent across Tasks 2, 3, 4, 7, 9, 13.
- `computeImportance(*, attempt_count, adversary_verdict, cost_usd)` — same kw-only signature in Tasks 2 and 3.
- `_uid(run_id, st_id)` → `"r1::st-1"` — matches the assertion in Task 7's `test_embed_and_store_seeds_index` and the cited id in Task 13.
- `fitOrCompact(system, user, num_ctx, headroom, *, summarize)` / `compactPayload(..., *, summarize, offload_dir)` / `shouldCompact(system, user, num_ctx, headroom)` — identical across Tasks 10, 11, 12.
- `_summarizeForCompaction(self, text)` and the `_compaction_fail_streak` attribute — consistent in Task 12 method + tests.
- Fallback marker string `"context trimmed to fit the model window"` matches `brain_io._fitUserToCtx:29` — used as the assertion target in Tasks 11/12.

No mismatches remain.
