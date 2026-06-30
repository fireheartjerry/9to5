# Epic 3 — Memory & Context (Design Spec)

**Date:** 2026-06-30 · **Status:** design only (no 9to5 source changed by this doc).
**Harvest source:** `docs/references-harvest/MASTER.md` steals #4 and #6 + fast-follows.
**Themes:** `themes/memory-knowledge.md`, `themes/prompt-context-engineering.md`.
**Ground truth:** `_9to5-brief.md` §2.3 (gap #4), §2.9 (gap #8).

---

## 1. Goal

Lift the 7B brain's structural ceiling by giving retrieval *real solution content served
from a persistent ANN index* and replacing blind `[:N]` truncation with *hierarchical
compaction that trims the payload to the fixed context window* — closing brief gap **#4**
(persistent, scalable codebase/solution RAG) and gap **#8** (long-horizon context
compaction).

---

## 2. Non-Goals

- **NOT resizing `num_ctx`.** `config.OLLAMA_NUM_CTX` (8192) and `OLLAMA_KEEP_ALIVE` ("30m")
  stay constant. The fixed window was the deliberate fix for the Ollama reload/empty-completion
  storm (`platform_core/app_config/llm.py:78-90`, `_9to5-brief.md` §2.9). Compaction trims the
  **payload** to fit the window; it never grows or per-call-sizes the window. Any internal
  summarizer call this epic adds is itself an ordinary fixed-window brain call.
- **NOT replacing Obsidian as the persistent store.** `memory/obsidian.py` remains the durable
  note store and the per-subtask living `CLAUDE.md` writer. The ANN index is a *derived,
  rebuildable cache* over `state/experience.db`; offloaded raw context is breadcrumbed to disk,
  not promoted into Obsidian.
- **NOT a new vector DB service.** No server process; everything stays file-backed and local,
  reusing local `nomic-embed-text` embeddings.
- **NOT changing model/effort routing**, the verifier contract, or any public facade signature.

---

## 3. Architecture

Three independently shippable units, each fail-open to today's behavior. All new public
functions are `camelCase`, vars `snake_case`, consts `ALL_CAPS`, every new module carries the
`@AI-MAP v1` header.

### 3a. Solution-content store + ANN index (steal #4)

**Problem in code.** `memory/retrieval.py::top_k_similar` calls
`experience.embedded_subtasks()` (`memory/experience_subtasks.py:152` — a `SELECT *` over every
embedded, verify-passing row) and cosines each in pure Python — an **O(n) full scan, no index**.
`render_lessons` (`memory/retrieval.py:184`) emits **metadata only** (`title`, `effort`,
`model`, `"needed N tries"`) — never the diff/answer/post-mortem. The `subtasks` row
(`memory/experience_schema.py:46`) stores `invocation_spec_json` (the *request*) but not the
*resulting solution content*.

**Design.**

1. **Widen the stored payload (write side).** Add a content table rather than bloating the hot
   `subtasks` row:
   - In `memory/experience_schema.py::_SCHEMA`, append one `CREATE TABLE IF NOT EXISTS
     exp_content (run_id TEXT, st_id TEXT, solution_content TEXT, post_mortem TEXT,
     importance REAL, model_id TEXT, created_at TEXT, UNIQUE(run_id, st_id))`. New tables are
     additive (the module already relies on `CREATE TABLE IF NOT EXISTS` running on first
     connect, `experience_schema.py:251`), so no migration machinery is needed; an old db file
     gains the table on next open.
   - Add `importance REAL` to the `subtasks` table via the existing `_MIGRATIONS` dict
     (`experience_schema.py:215`) so the rerank in 3b has a salience column even for rows that
     predate `exp_content`.
   - New module **`memory/experience_content.py`** (sibling of `experience_subtasks.py`, owns
     the `exp_content` table): `recordSolutionContent(run_id, st_id, *, solution_content,
     post_mortem, importance, model_id, db_path=None)` and `fetchSolutionContent(run_id, st_id,
     db_path=None)`. Same `_WRITE_LOCK` + `_connect` pattern as `experience_solutions.py`.
   - The content source is the executor result already in hand at record time
     (`memory/experience_subtasks.py::_subtask_params` reads `st["session"]`); the recording
     site is the same place `sync_subtask` is called. Solution content = the final diff/answer
     summary; `post_mortem` reuses the executor learning summary already requested via
     `reflection.REQUEST` (`plan_mixin.py:327`, stored today in the `reflections` table).

2. **ANN index (read side).** New module **`memory/exp_index.py`** defining a tiny interface so
   the dependency is swappable and the O(n) scan becomes the *fallback*, not the default:
   ```
   class AnnIndex(Protocol):
       def addPair(self, uid: str, vec: list[float], payload: dict) -> None: ...
       def query(self, vec: list[float], k: int, threshold: float) -> list[dict]: ...   # [{uid, score, payload}]
       def persist(self) -> None: ...
   ```
   - **Primary backend `ChromaIndex`** — a ~120-line port of AutoGen's drop-in
     (`references/autogen/python/packages/autogen-ext/src/autogen_ext/experimental/task_centric_memory/_string_similarity_map.py`):
     a disk-persistent `chromadb` collection under `state/exp_index/`, `get_or_create=True`,
     `anonymized_telemetry=False`. **Crucially we pass our own `nomic-embed-text` vectors**
     (`collection.add(embeddings=[vec], ids=[uid], metadatas=[payload])`) instead of Chroma's
     default Sentence-Transformers embedder, so the index lives in the *same* embedding space as
     `retrieval.embed` and reuses its negative-cache seam (`retrieval.py:73`). The collection name
     is suffixed with `EMBED_MODEL` + dim (guild-style `model_id` pin) so a future embedder swap
     can't silently mix vector spaces.
   - **Fallback `NullIndex`** — returned by `getIndex()` whenever `ANN_INDEX_ENABLED` is false or
     `import chromadb` fails; its `query` returns `[]`, which makes `retrieve_content` fall back
     to the existing `top_k_similar` scan. This keeps the new dependency strictly optional.
   - `getIndex()` is a cached singleton (one index per process, like the experience conn pool).

3. **Wire retrieve→inject (`memory/retrieval.py`, signatures preserved).**
   - Keep `top_k_similar` exactly as the fail-open fallback.
   - Add `retrieve_content(goal, title, *, k=None, db_path=None) -> list[dict]`: embed the query
     (existing `embed`), `getIndex().query(vec, k, RETRIEVAL_MIN_SCORE)`; on empty result fall
     back to `top_k_similar`; join each hit to its `exp_content` row.
   - Add `render_solutions(neighbors, max_tokens=None)`: emit the **actual** solution content
     (sanitized — see §6), budgeted by a new `RETRIEVAL_CONTENT_MAX_TOKENS`, with the existing
     `_approx_tokens` budget loop. `render_lessons` stays for metadata-only callers.
   - `lessons_block` (the one helper `plan_mixin` calls at `plan_mixin.py:142` and
     `_sieAuthoringContext` at `plan_mixin.py:357`) gains an internal preference for
     `retrieve_content` + `render_solutions`, degrading to `retrieve` + `render_lessons`. **Its
     signature and the two call sites do not change** — the upgrade is transparent.
   - Index population: `embed_and_store` (`retrieval.py:135`) and `backfill_embeddings`
     (`retrieval.py:218`) additionally `getIndex().addPair(...)`. First-run migration of an
     existing `experience.db`: `backfill_embeddings` already walks every passing row; it now also
     seeds the index, so the index self-heals from the BLOB column (the BLOB stays source of
     truth; the index is a derived cache).

### 3b. Recency + Importance + Relevance re-rank (+ optional reflection consolidation)

**Re-rank** — new module **`memory/retrieval_rank.py`**, a port of generative-agents
`new_retrieve` (`references/generative-agents/reverie/backend_server/persona/cognitive_modules/retrieve.py:199`):
`rerank(candidates, *, now) -> list[dict]` computing, per candidate, three min-max-normalized
signals and a weighted sum:
- **recency** = exp-decay over `created_at` age (`RETRIEVAL_RECENCY_HALFLIFE_DAYS`);
- **importance** = the stored `importance` column (write-time salience: derived from
  `attempt_count`, adversary verdict, cost — a noisy first-pass subtask that *eventually*
  passed is a higher-stakes lesson);
- **relevance** = the cosine/ANN score already on the candidate.

Weights are config consts `RETRIEVAL_W_RECENCY` / `_W_IMPORTANCE` / `_W_RELEVANCE` (gen-agents
ships `[0.5, 3, 2]` for relevance-heavy ranking; we start there). `retrieve_content` calls
`rerank` before truncating to `k`. Pure function, unit-testable with synthetic timestamps, no
embedder or DB needed. Fail-open: any error returns candidates in their incoming cosine order.

**Reflection consolidation (optional, default OFF)** — new module
**`memory/reflection_consolidate.py`**, a port of generative-agents `reflect.py`:
`maybeConsolidate(*, db_path=None)` fires when accumulated `importance` of new rows crosses a
budget (importance-accumulator trigger), generates focal questions → retrieves evidence →
writes a few abstracted, **source-cited** principles into the existing `reflections` table
(`experience_schema.py:166`, already has `approach`/`reusable_recipe`/`confidence`/`trusted`).
Runs **off the hot path** inside the existing SIE post-run maintenance thread
(`SIE_AUTO_MAINTENANCE`), gated by `REFLECTION_CONSOLIDATE_ENABLED=false`. This is the "metadata
→ durable cited principle" consolidation 9to5 lacks; shipped last and flag-dark so it never
blocks the core steal.

### 3c. Hierarchical context compaction + offload (steal #6)

**Problem in code.** Every brain call ends in `brain_io._fitUserToCtx` (`brain_io.py:23`), which
**blind-slices** an over-long payload (`head = 2/3`, `tail = 1/3`, a "context trimmed" marker
between). Long-run history is hard-sliced upstream too: `architect_doc[:1500]`
(`plan_mixin.py:279`), `[:4000]` (`plan_mixin.py:141`), `RETRIEVAL_MAX_TOKENS=350`. Nothing
*condenses*; old context is dropped, not summarized.

**Design** — new module **`platform_core/orchestration/compaction.py`** (pure-Python, no
framework dep), three ported pieces:

1. **`shouldCompact(system, user, num_ctx, headroom) -> bool`** — eliza model-input-budget
   trigger (`references/eliza/packages/core/src/runtime/model-input-budget.ts`): estimate tokens
   for `system + user`, compare against `COMPACTION_TRIGGER_RATIO * num_ctx` with a reserve of
   `max(COMPACTION_RESERVE_FLOOR, num_ctx * reserve)`. Window-aware, regression-safe.

2. **`compactPayload(system, user, num_ctx, headroom, *, summarize, offload_dir) -> str`** —
   agentscope `_compress_context_impl` spine
   (`references/agentscope/src/agentscope/agent/_agent.py:312`, methods `_compress_context_impl`
   / `_split_context_for_compression`):
   - split `user` into **compress-half vs reserve-half** by `COMPACTION_RESERVE_RATIO`
     (newest text reserved verbatim, oldest condensed);
   - summarize the compress-half via the injected `summarize` callable into a **structured
     MUST-PRESERVE summary** (3); 
   - **offload** the raw compress-half to `offload_dir` (under `state/`) with a re-readable
     breadcrumb line appended to the payload (`"[raw context offloaded to <path>]"`);
   - **drop-oldest fallback**: if the summary itself would overflow, or `summarize` returns empty
     / raises, return `_fitUserToCtx(system, user, num_ctx, headroom)` — i.e. **today's exact
     truncation**. Compaction is strictly an *improvement layer* over the existing safety net.

3. **`MUST_PRESERVE_CONTRACT`** const + summary prompt — openclaw rubric
   (`references/openclaw/src/agents/compaction.ts`, `compaction-planning.ts`): the summary must
   retain active goal + status, batch progress, last request, decisions + rationale, TODOs, and
   **exact file paths / function names / error strings**. (9to5 brain calls are JSON-shaped
   single-shot rather than a tool transcript, so the openclaw tool-pair-split invariant is noted
   for the future executor-history compactor but not required for the brain-payload path here.)

**Integration (num_ctx stays fixed).** `_ollamaChat` (`llm_mixin.py:99-100`) keeps
`num_ctx = config.OLLAMA_NUM_CTX` and the existing `keep_alive`. The single change is at the fit
seam: replace the bare `_fitUserToCtx` call with
```
user = compaction.fitOrCompact(system, user, num_ctx, OLLAMA_GEN_HEADROOM, summarize=self._summarizeForCompaction)
```
where `fitOrCompact` returns `user` unchanged when small, calls `compactPayload` when
`shouldCompact` and `COMPACTION_ENABLED`, and otherwise/on-failure returns `_fitUserToCtx(...)`.
`_summarizeForCompaction` is a thin orchestrator method that calls the **same** Ollama model at
the **same** fixed `num_ctx` on a bounded slice — it never re-enters compaction (no recursion)
and never resizes the window. A **circuit breaker** (claude-code autoCompact pattern,
`COMPACTION_MAX_PASSES`, stop after N consecutive summary failures) prevents a doomed
summarize-retry loop. Default `COMPACTION_ENABLED=false` for the first ship so the summarizer's
extra latency/cost is opt-in until measured.

A complementary **run-history compactor** (same module) maintains one structured rolling summary
of completed subtasks for long self-improvement runs, replacing ad-hoc inclusion of prior
outputs in `claude_md_inject`; raw detail offloads to disk with a breadcrumb. This is the
genuine long-horizon win and reuses `compactPayload`.

---

## 4. Data flow (authoring one brain prompt)

```
authorInvocationSpec / authorSubtaskPlan (plan_mixin.py)
  └─ _sieAuthoringContext / lessons_block            # 3a/3b
       ├─ retrieval.embed(query)                      # local nomic-embed-text (negative-cached)
       ├─ exp_index.getIndex().query(vec, k, floor)   # ANN lookup  (fallback: top_k_similar O(n) scan)
       ├─ join hits → exp_content rows (solution_content + post_mortem)
       ├─ retrieval_rank.rerank(candidates, now)      # recency + importance + relevance
       └─ render_solutions(...)  → CONTENT block, budgeted by RETRIEVAL_CONTENT_MAX_TOKENS
  └─ build system + user payload
  └─ _ollamaChat(system, user)                        # 3c
       ├─ num_ctx = config.OLLAMA_NUM_CTX             # FIXED — never resized
       ├─ user = compaction.fitOrCompact(...)         # condense old half + offload raw; else _fitUserToCtx
       └─ ollama.chat(options={num_ctx}, keep_alive)  # unchanged transport
```

Write-back after verify: `sync_subtask` → `experience_content.recordSolutionContent(...)` +
`embed_and_store` (now also `index.addPair`). Off hot path: `maybeConsolidate()` (optional).

---

## 5. Exact file structure

**New files** (each ≤300 lines target, functions ≤25/70):

| File | Responsibility |
|---|---|
| `memory/exp_index.py` | `AnnIndex` protocol, `ChromaIndex` (AutoGen SSM port, nomic vectors), `NullIndex` fallback, cached `getIndex()`. |
| `memory/experience_content.py` | Owns the `exp_content` table: `recordSolutionContent`, `fetchSolutionContent`. |
| `memory/retrieval_rank.py` | `rerank()` — recency+importance+relevance weighted score (gen-agents port). Pure fns. |
| `memory/reflection_consolidate.py` | `maybeConsolidate()` — importance-triggered cited-principle consolidation (gen-agents `reflect.py`, default OFF). |
| `platform_core/orchestration/compaction.py` | `shouldCompact`, `compactPayload`, `fitOrCompact`, `MUST_PRESERVE_CONTRACT`, offload breadcrumb (agentscope + openclaw + eliza ports). |

**Modified files** (narrow, ownership-preserving):

| File | Change |
|---|---|
| `memory/experience_schema.py` | Append `exp_content` CREATE-TABLE to `_SCHEMA`; add `importance` to `subtasks` via `_MIGRATIONS`. |
| `memory/retrieval.py` | Add `retrieve_content`, `render_solutions`; `lessons_block` prefers content+index, falls back to `top_k_similar`/`render_lessons`; `embed_and_store`/`backfill_embeddings` also seed the index. Public names preserved. |
| `memory/experience_subtasks.py` | At the sync/record site, also call `experience_content.recordSolutionContent`. |
| `platform_core/orchestration/brain_io.py` | Keep `_fitUserToCtx` as-is (it is the fallback); compaction imports it. |
| `platform_core/orchestration/llm_mixin.py` | Swap `_fitUserToCtx(...)` for `compaction.fitOrCompact(...)`; add `_summarizeForCompaction` (fixed-window, non-recursive) + circuit-breaker state. |
| `platform_core/orchestration/plan_mixin.py` | No signature change — benefits via `lessons_block` upgrade. |
| `platform_core/app_config/llm.py` | New consts (below). |

**New config consts** (`platform_core/app_config/llm.py`, `_env*` helpers, ALL_CAPS):
`ANN_INDEX_ENABLED=false`, `ANN_INDEX_BACKEND="chroma"`, `ANN_INDEX_DIR="state/exp_index"`,
`RETRIEVAL_CONTENT_MAX_TOKENS=700`, `RETRIEVAL_W_RECENCY=0.5`, `RETRIEVAL_W_IMPORTANCE=3.0`,
`RETRIEVAL_W_RELEVANCE=2.0`, `RETRIEVAL_RECENCY_HALFLIFE_DAYS=14`, `COMPACTION_ENABLED=false`,
`COMPACTION_TRIGGER_RATIO=0.85`, `COMPACTION_RESERVE_RATIO=0.4`, `COMPACTION_RESERVE_FLOOR=1024`,
`COMPACTION_MAX_PASSES=3`, `COMPACTION_OFFLOAD_DIR="state/compaction"`,
`REFLECTION_CONSOLIDATE_ENABLED=false`. Every new feature ships **dark** (default off) so the
merge is a no-op until explicitly enabled.

**Docs:** regenerate `AGENTS.md` via `python tools/repo_map.py` after the new modules; add a row
to `docs/MEMORY.md` / `docs/STATE.md` describing the index + offload artifacts under `state/`.

---

## 6. Error handling (everything fails open to today's behavior)

- **Embedder down** → existing `retrieval.embed` negative cache returns `None` → no retrieval
  today, unchanged.
- **ANN absent / `import chromadb` fails / `ANN_INDEX_ENABLED=false`** → `getIndex()` returns
  `NullIndex` → `retrieve_content` falls back to `top_k_similar` (the O(n) scan still works).
- **Index corrupt** → query raises, caught, fall back to scan; `backfill_embeddings` rebuilds the
  index from the BLOB column (source of truth) on the next maintenance pass.
- **No `exp_content` row** (legacy rows) → `render_solutions` degrades to `render_lessons`
  (metadata).
- **Rerank error** → return candidates in incoming cosine order.
- **Compaction**: summarizer empty/raises, or summary would overflow, or circuit breaker tripped
  → `_fitUserToCtx` truncation (today's exact path). `shouldCompact`/`compactPayload` are wrapped
  so a bug there can never block a brain call.
- **Prompt-injection hardening**: `render_solutions` sanitizes each retrieved field to one inline
  line (strip control chars, collapse newlines, defang leading `#`/fences — loki-mode
  `_sanitize_field` pattern) since solution content is now injected verbatim into brain prompts.
- All new writes are best-effort under `try/except` + `LOG.debug`, matching the existing
  `record_subtask` / `lessons_block` convention.

---

## 7. Testing strategy (pytest; run `python tools/dev.py check <file>` per edit)

- **ANN index** (`tests/test_exp_index.py`): use a tmp `ANN_INDEX_DIR`; monkeypatch
  `retrieval._embed_call` to return deterministic vectors (existing seam at `retrieval.py:57`);
  assert add→query round-trips by cosine order. Add a `FakeIndex` for unit tests so `chromadb`
  is **not a hard test dependency**; one `@pytest.mark.skipif(chromadb missing)` test exercises
  the real `ChromaIndex`. Assert `NullIndex` path when the import is forced to fail.
- **Solution content** (`tests/test_experience_content.py`): record + fetch round-trip against a
  tmp `db_path`; assert `lessons_block` now contains the stored solution text, not just `effort=`.
- **Rerank** (`tests/test_retrieval_rank.py`): pure-function tests with synthetic candidates +
  timestamps; assert recent/high-importance rows out-rank an older nearest-cosine row.
- **Compaction** (`tests/test_compaction.py`): `shouldCompact` threshold math; `compactPayload`
  with a stub `summarize` (asserts MUST-PRESERVE identifiers — file paths, fn names — survive);
  offload breadcrumb file written under tmp dir; drop-oldest fallback when summarize raises;
  **assert the `ollama.chat` options always carry `config.OLLAMA_NUM_CTX` unchanged** (guards the
  reload-storm regression).
- **Migration** (`tests/test_experience_schema_migration.py`): open a pre-existing db lacking the
  new table/column, assert it is added idempotently and old reads still work.
- Gate with `python tools/dev.py fast`; `python tools/size_audit.py` (zero `must_split`);
  `python tools/repo_map.py` after module adds.

---

## 8. Risks & sequencing

**Risks**
- *Index migration of existing `experience.db`* — Mitigated: index is a **derived cache**, BLOB
  column stays source of truth, `backfill_embeddings` seeds/rebuilds it; first enable triggers one
  backfill pass off the hot path.
- *Embedding dim / mixed spaces* — `nomic-embed-text` is 768-dim; pin `EMBED_MODEL`+dim into the
  Chroma collection name (guild `model_id` pattern) so a swapped embedder starts a fresh
  collection instead of silently corrupting cosine space.
- *ANN dependency choice* (**open question, §final**) — `chromadb` is the cleanest drop-in but a
  heavier wheel; `sqlite-vss` keeps everything in the existing sqlite file but has shaky Windows
  wheels; `hnswlib` is light/pure but needs our own id↔payload map. The `AnnIndex` interface makes
  this swappable, but the first backend must be chosen.
- *Compaction reintroducing latency/cost* — gated behind `COMPACTION_ENABLED=false` + circuit
  breaker; summary calls reuse the fixed window so they cannot trigger the reload storm.
- *Injection surface* — solution content is now injected verbatim → §6 sanitization is mandatory.

**Sequencing** (each phase independently mergeable, all dark by default)
1. **Content store + content injection** — `exp_content` table, `experience_content.py`,
   `render_solutions`, write-back. Immediate value, **no new dependency** (still over the O(n)
   scan). 
2. **ANN index** — `exp_index.py`, wire `retrieve_content` with fail-open to scan. *Requires the
   dependency decision.*
3. **Recency+importance+relevance rerank** — `retrieval_rank.py`.
4. **Compaction layer** — `compaction.py` + `_ollamaChat` seam swap + run-history compactor.
5. **Reflection consolidation (optional)** — `reflection_consolidate.py`, off by default.

---

## 9. Success criteria

- `lessons_block` injected into the brain carries **actual solution content** (diff/answer/
  post-mortem), proven by a test asserting stored content appears — not just `effort=/model=`.
- With `ANN_INDEX_ENABLED=true`, retrieval is an **index lookup**, not a full-table scan; the
  fail-open fallback to `top_k_similar` is covered by tests.
- Retrieved lessons are reranked by **recency + importance + relevance**; a recent high-stakes
  lesson out-ranks an older nearest-cosine match (test-proven).
- An oversized brain payload is **condensed with a MUST-PRESERVE summary + raw offload**, not
  blind-sliced, while `num_ctx` is asserted constant at `config.OLLAMA_NUM_CTX` across the call.
- All retrieval/compaction paths **fail open** to today's truncation/metadata behavior.
- `python tools/dev.py fast` green; `tools/size_audit.py` zero `must_split`; `AGENTS.md`
  regenerated; every feature ships behind a default-off flag.
```
