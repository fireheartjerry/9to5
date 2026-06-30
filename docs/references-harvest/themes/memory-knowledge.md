# Theme: Memory & Knowledge (RAG, ANN indexing, retrieval scoring, reflection/consolidation, knowledge graphs, codebase memory, solution-content storage)

Cross-repo synthesis for the 9TO5 agent-tech harvest. READ-ONLY. Sources: all 23 per-repo
digests in `docs/references-harvest/*.md`, with code spot-checks in `references/<repo>`.

## 1. Theme intro + how 9TO5 handles this today

Memory/knowledge is the layer that lets an agent *not relearn the same thing every run*: a
store of past work, an index that finds the relevant slice fast, a scoring function that
ranks it, and a consolidation step that distills raw experience into durable lessons. It is
the difference between an agent that gets smarter across runs and one that re-discovers the
repo from scratch each morning.

**How 9TO5 does it today.** Three stores: (1) an **Experience Ledger** — SQLite
`state/experience.db` (`memory/experience*.py`) with runs/subtasks/embeddings/lessons/
pr_outcomes/solutions tables; (2) a **retrieval-augmented brain** (`memory/retrieval.py`):
local `nomic-embed-text` embeddings, a cosine `top_k_similar` over *verify-passing* subtasks,
rendered into a tiny `lessons_block` prepended to brain prompts; (3) **Obsidian**
(`memory/obsidian.py`) as the durable note store + per-subtask living `CLAUDE.md`. Plus
`knowledge.py` (Claude-capabilities scrape), `learning/knowledge_graph.py`,
`learning/solution_cache.py`, `memory/conviction_ledger.py`, `memory/user_prefs.py`.

**Where it is weak (brief gap #4, confirmed in code).** `memory/retrieval.py::top_k_similar`
iterates **every** embedded row and cosines in pure Python — an O(n) full scan with **no ANN
index**; it won't scale past a few thousand rows. Only verify-passing rows are retrievable.
Critically, `render_lessons` emits **metadata only** — `title`, `effort`, `model`,
`attempt_count` ("needed 3 tries -- be careful") — and **never the actual solution content**
(the diff, the answer, the post-mortem). There is **no persistent RAG over the codebase
itself**: repo understanding is re-discovered fresh by the architect/discovery phase each run
and hard-truncated into prompts. No reflection/consolidation pass turns the pile of raw
subtask rows into a few generalized principles; the knowledge graph and solution cache are
under-exploited. Net: 9TO5 has the *plumbing* (local embeddings, a SQLite blob column, cosine,
top-k, an Obsidian store) but is missing the four things that make memory pay off — an ANN
index, **solution-content** storage, salience-aware ranking, and a consolidation loop.

## 2. Ranked technique table (best across all repos; near-duplicates merged)

Rank 5 = highest value-for-fit for 9TO5's memory/knowledge gap. Effort: idea-only / port-code / heavy.

| # | technique | source repo | what it does | 9to5-fit | steal-effort | rank |
|---|---|---|---|---|---|---|
| 1 | **`@exp_cache` experience pool** | metagpt | Transparent decorator: semantic-query a pool of prior **request→response solution content**, return a scored "perfect" past solution or run the fn then score + persist it. Backed by a real RAG engine. (`exp_pool/decorator.py`, `manager.py`, `scorers`/`perfect_judges`) | Fixes BOTH halves of gap #4 at once — stores *actual solution content* (not metadata) AND retrieves via ANN; wraps existing call sites with one decorator | port-code | 5 |
| 2 | **Recency + Importance + Relevance retrieval score** | generative-agents | Rank memory by weighted sum of 3 min-max-normalized signals: exp-decay recency, LLM-assigned importance (poignancy 1–10), cosine relevance. Weights are tunable `scratch.*_w`. (`retrieve.py::new_retrieve`) | Drop-in replacement for bare cosine in `top_k_similar`; surfaces *recent + high-stakes* lessons, not just nearest-cosine. Pair with a write-time importance score per row | idea-only | 5 |
| 3 | **Reflection: synthesize higher-level insights w/ provenance** | generative-agents | When accumulated importance crosses a budget, generate focal questions → retrieve evidence → write abstracted "thought" nodes that cite their source node ids (`filling`/`depth` = a traceable tree). (`reflect.py`) | The missing consolidation primitive: compress many raw subtask rows into a few durable, *cited* principles. Directly attacks "metadata-only lessons" + long-horizon compaction; gives an auditable lesson→evidence graph | port-code | 5 |
| 4 | **ChromaDB persistent ANN string-similarity map** | autogen | ~120-line disk-backed `chromadb` store mapping embedded input→output pairs; `get_related_string_pairs(query, n, threshold)` with a distance threshold. (`task_centric_memory/_string_similarity_map.py`) | The smallest, cleanest drop-in replacement for the O(n) Python cosine scan — a persistent ANN index that scales, and a reference shape for a codebase index | port-code | 5 |
| 5 | **RRF hybrid retrieval (BM25 + vector)** | guild | Fuse a BM25/FTS5 lexical arm and an int8 vector arm by Reciprocal Rank Fusion (rank-only, k=60, deterministic tiebreak); ADR shows weighted-linear fusion tested strictly worse. Coverage-gated graceful degrade to BM25-only. (`internal/lore/embed/rrf.go`, `appraise_rrf.go`) | "How did we solve X" needs both exact-term (error strings, file paths, SHAs) and semantic neighbors; pure cosine misses lexical. Best-in-class fusion recipe | port-code | 5 |
| 6 | **int8 in-memory vector index w/ epoch reload** | guild | Parallel `[]int8`/id slices, int8×int8 dot scan (~0.5ms @ 10k×384), `byEntry` map for O(1) splice, one indexed epoch read at query top; cross-process writers splice without full reload. (`internal/lore/embed/index.go`) | A real persistent index with cheap cross-process freshness — beats the O(n) scan while staying dependency-light (no external vector DB) | port-code | 5 |
| 7 | **Task-centric memory: failure→advice→validated-insight loop** | autogen | Memory controller stores task→insight memos; a background loop tests the agent, diagnoses failures, drafts teacher-style advice, re-tests, and **only persists advice that demonstrably fixes the task**. Retrieval generalizes the task → ANN search → **LLM validates each candidate insight before injection**. (`task_centric_memory/memory_controller.py`, `_prompter.py`) | Stores *actionable insight content*, learns from failures (9TO5 only learns from wins today), and gates retrieval with an LLM relevance filter to cut junk lessons | heavy | 5 |
| 8 | **Pluggable ANN RAG backend registry/factory** | crewai / dify / agentscope | One provider-keyed factory returns a `BaseClient`; real ANN DBs (Qdrant/Chroma/FAISS, ~30 backends in dify) behind a uniform interface, swap by config, keep the local-embeddings seam. (`crewai/rag/factory.py`; `dify/.../vdb/vector_factory.py`; `agentscope/rag/_vdb/_qdrant.py`) | The clean abstraction to replace the O(n) scan without hard-wiring one vendor; `metadata_filter` gives per-run / per-repo scoping. agentscope's Qdrant `KnowledgeBase` is the most 9TO5-shaped | port-code | 4 |
| 9 | **Long-term Store: namespaces + vector IndexConfig + TTL** | langgraph | Cross-thread KV memory: hierarchical `namespace` tuples, `IndexConfig`(`dims`,`embed`,`fields`) for semantic `SearchOp`, filter operators (`$gt`,`$ne`), TTL, pagination; ANN-backed in the pg adapter. (`checkpoint/.../store/base/`) | The reference design for content-bearing, namespaced, ANN-searchable memory that's cleanly separated from short-term run state — stores solution content under `/repo/<x>/...` | port-code | 4 |
| 10 | **Composite recall scoring (sem + recency-decay + importance)** | crewai | Final rank = `w_sem*sim + w_rec*0.5^(age/half_life) + w_imp*importance`, per-reason attribution, weights+half-life configurable. (`memory/types.py::compute_composite_score`) | Same idea as #2 in production-grade Python; small, high-ROI upgrade to `top_k_similar` so stale/low-value lessons sink | port-code | 4 |
| 11 | **MMR retrieval diversification** | swarmclaw | Maximal Marginal Relevance over candidates balancing salience vs novelty, with **embedding similarity + Jaccard text fallback** when vectors are absent. (`src/lib/server/mmr.ts`) | A drop-in re-ranker so the lessons block isn't 5 near-duplicate neighbors; the no-embedding fallback keeps it usable when the embedder is cold | port-code | 4 |
| 12 | **Typed memory extract/inject (solution content, deduped)** | agx | After a task, one LLM call distills 0–3 typed `decision/pattern/gotcha` memories (strict JSON, fail-open); at task start a budgeted, per-project "Past learnings" block of actual sentences is injected; `UNIQUE(task_id,type,content_hash)` dedups across reruns. (`lib/memory/{extract,inject}.js`) | Exactly the "inject solution content, not metadata" fix in a small, SQLite-native shape that matches 9TO5's existing experience.db | port-code | 4 |
| 13 | **Episodic→semantic consolidation pipeline** | loki-mode | Cluster episode traces (similarity + task-type), extract a common pattern AND anti-patterns per cluster, merge into existing semantic patterns, build zettelkasten cross-links. (`memory/consolidation.py`) | The generalization step 9TO5 lacks — turns `experience.db` rows into reusable patterns + anti-patterns; complements #3 | port-code | 4 |
| 14 | **Trajectory feedback (codified context)** | eliza | Query a past-trajectory DB for relevant prior decisions/**failure modes** and pre-load them into the spawn prompt (timeout-guarded). | Closes the loop 9TO5's lessons_block only half-does: inject failure modes & decisions, not just passing-subtask metadata | port-code | 4 |
| 15 | **Three-surface write model by lifetime** | guild | journal (dies with task) / lore (cross-task durable) / brief (next-session handoff), with an explicit "who else needs this?" routing test. (`internal/mcp/instructions.md`) | A clean taxonomy 9TO5's Obsidian + experience.db + CLAUDE.md split lacks; lifetime-scoped routing prevents memory bloat | idea-only | 4 |
| 16 | **Git-aware staleness / echoes lifecycle** | guild | Per-kind `valid_days` auto-stale **plus** flag an entry when its `file_path` was modified in git *after* the entry was written; stale entries surface as "fading echoes". (`internal/lore/echoes.go`) | A code-memory invalidation signal 9TO5 has no analog for — keeps a codebase RAG corpus from serving notes about code that has since changed | port-code | 4 |
| 17 | **Importance-accumulator reflection trigger** | generative-agents | Fire consolidation when summed importance of new memories crosses a budget, then reset — self-pacing, not fixed-schedule. (`reflect.py`, `scratch.importance_trigger_max`) | Decides *when* to run #3/#13 by accumulated salience rather than run count | idea-only | 4 |
| 18 | **Filesystem MEMORY.md long-term memory + autoDream consolidation** | agentscope / claude-code | Typed markdown memory store with a bounded `MEMORY.md` index injected into the system prompt; a background forked subagent consolidates recent transcripts into topic files (orient→gather→consolidate→prune). (`agentscope middleware/_longterm_memory/`; `claude-code services/autoDream/`) | Directly compatible with 9TO5's Obsidian store; adds a typed self-curating index + nightly consolidation job | idea-only | 3 |
| 19 | **Parent-child (small-to-big) + QA indexing + weighted hybrid rerank** | dify | Index small child chunks for match precision, return the larger parent (function/file) for context; alt-index Q&A pairs; fuse cosine + BM25 with tunable weights (no rerank model). (`core/rag/index_processor/`, `rerank/weight_rerank.py`) | The codebase-RAG chunking strategy: match on a tight snippet, hand the executor the enclosing function — and cheap local hybrid rerank | port-code | 3 |
| 20 | **Pre-resolved `file:line` anchors persisted into the spec** | warp | The tech spec lists exact code locations a change touches (`app/src/.../util.rs:24-145`) *before* code is written. (`specs/APP-*/TECH.md`) | Persist resolved anchors into state so repo knowledge isn't re-discovered every run — a lightweight codebase-memory win without a full index | port-code | 3 |
| 21 | **Cross-task KB: tag-indexed publish/subscribe over memory** | bernstein | Explicit `publish(tag,key,value,scope)` / `subscribe(tag,scope)` over SQLite memory; facts carry a lineage triple (producer_task_id, ts_ns, content_hash); run vs project scope. (`core/memory/cross_task_kb.py`) | Persistent, attributable cross-run fact channel storing real content, keyed by tag — beats metadata-only lessons | port-code | 3 |
| 22 | **Hybrid trust-weighted retrieval (FTS5 → Jaccard → trust)** | hermes | FTS5 candidates → Jaccard rerank → trust-weighted scoring with per-fact helpful/trust counts + temporal decay; optional HRR vectors for ANN-free semantic match with numpy-optional fallback. (`plugins/memory/holographic/`) | A feedback-weighted hybrid retriever richer than top-k cosine; trust counts let 9TO5 down-weight lessons that didn't pan out | idea-only | 3 |
| 23 | **FTS5 keyword recall over solution/code content** | loom / hermes | SQLite FTS5 over message/title/code with INSERT/UPDATE/DELETE triggers keeping the index live, BM25 + recency tiebreak, `tokenchars` for paths/SHAs; hermes adds lineage-dedup + source-demotion ranking. (`loom specs/search-system.md`; `hermes tools/session_search_tool.py`) | The cheap lexical half of a hybrid index (#5), indexing *content*; zero LLM cost; pairs with embeddings | port-code | 3 |
| 24 | **Agentic vs static RAG injection mode** | agentscope | Either expose a `search_knowledge` *tool* (LLM decides when to retrieve) or auto-inject top-k on turn 0 as a hint block. (`middleware/_rag.py`) | Lets the brain pull solution *content* on demand instead of always-prepending a fixed lessons block | port-code | 3 |
| 25 | **Near-dup detection on write (Jaccard/trigram)** | guild | Broad SQL OR candidate fetch within 14d, then Jaccard on title tokens (≥0.40) OR summary trigrams (≥0.20) to surface duplicates so agents update instead of re-inscribe. (`internal/lore/dedupe.go`) | "Appraise before research" — cheap lexical dedup at write time, no embedder needed; keeps the corpus lean | port-code | 3 |
| 26 | **Vector versioning by `model_id`** | guild | Index refuses to load vectors whose `model_id` != canonical; embedder identity pinned via `.model-version`; stale-model rows skipped, not trusted. | Safe embedder upgrades (e.g. swapping `nomic-embed-text`) without silent mixed-vector-space corruption | idea-only | 3 |
| 27 | **Memory-as-untrusted-input sanitization** | loki-mode | Collapse every stored memory field to one inline line before it enters a prompt: strip control chars, defang leading markdown/`###`/fences, per-field char cap. (`memory/rag_injector.py::_sanitize_field`) | 9TO5 injects retrieved lessons + Obsidian context into brain prompts with **no injection defense** — a real, cheap hardening | port-code | 3 |
| 28 | **Dream-cycle / offline consolidation + temporal-decay tiering** | swarmclaw | Idle/scheduled background cycles consolidate working memory into durable abstractions; three tiers (working/durable/archive) with exp half-life decay on search scores, evergreen exemption, supersede-hiding. (`memory/{dream-cycles,memory-tiers,temporal-decay}.ts`) | Recency-weighted recall + tiering 9TO5's flat ledger lacks; another reference for the consolidation job | heavy | 3 |
| 29 | **Vectorized cosine (numpy matrix mul)** | loki-mode | Stack all embeddings into one matrix, single `np.dot` for all cosines, atomic `.npz` persist. (`memory/vector_index.py`) | A *stepping-stone*: beats 9TO5's per-row Python loop immediately, but still O(n) brute force — not the ANN answer gap #4 ultimately wants (use #4/#6/#8) | port-code | 2 |
| 30 | **Workspace archive (git-delta + tar.gz) as cross-run code memory** | openhands | Before sandbox teardown, capture a compact git-delta patch + self-contained tarball + manifest to object storage so the *actual diffs/files* survive. (`sandbox/workspace_archive.py`) | Persists real solution artifacts (not summaries) for cross-run code memory; feeds a content index | port-code | 2 |

**Dedup notes.** Recency/importance/relevance scoring appears in generative-agents (#2, the
origin, idea-only) and crewai (#10, production Python) and swarmclaw (#11 adds MMR+decay) — **gen-agents
is the cleanest formulation, crewai the most copy-pasteable.** ANN/vector-store appears in
autogen Chroma (#4, smallest), guild int8+RRF (#5/#6, no external dep, best hybrid), and the
factory abstractions (#8) — **autogen #4 for the fastest win, guild #5+#6 for the best
self-contained design, the factory for the long-term seam.** Solution-content storage is the
through-line of metagpt exp_cache (#1), autogen task-centric (#7), agx extract/inject (#12),
eliza trajectory-feedback (#14), bernstein cross-task KB (#21) — **metagpt #1 is the most
complete because it scores and judges before reuse.** Consolidation/reflection spans gen-agents
(#3, with provenance), loki (#13), swarmclaw/claude-code/agentscope (#18/#28) — **gen-agents #3
is the canonical primitive and adds an auditable evidence graph.**

## 3. If 9TO5 adopts ONE thing for this theme

**Adopt MetaGPT's `@exp_cache` experience-pool pattern — store and retrieve actual
request→response *solution content*, served from a persistent ANN index — replacing the
metadata-only `lessons_block` over an O(n) cosine scan.** Source: `references/metagpt/metagpt/
exp_pool/decorator.py` + `manager.py` (+ `scorers`/`perfect_judges`), backed by a RAG engine in
the shape of `metagpt/rag/engines/simple.py`; for the index itself, the smallest drop-in is
AutoGen's ~120-line ChromaDB `StringSimilarityMap`
(`task_centric_memory/_string_similarity_map.py`). This is the single highest-leverage steal
because it fixes **both halves of brief gap #4 at once**: it persists the real diff/answer/
post-mortem (not just `effort`/`model`/`attempt_count` as `memory/retrieval.py::render_lessons`
does today) and it serves them from a scalable ANN index instead of iterating every embedded
row in Python. 9TO5 already has the hard parts — local `nomic-embed-text` embeddings, a SQLite
`embeddings` BLOB column, cosine, and top-k — so the change is mostly swapping the scan for an
indexed lookup and widening the stored payload to include solution content, then wrapping the
existing retrieve→inject call sites with one transparent decorator. As a fast follow-up,
re-rank results with generative-agents' cheap **recency+importance+relevance** score
(`retrieve.py::new_retrieve`) so the brain sees *recent, high-stakes, content-bearing* lessons
rather than nearest-cosine metadata — and schedule a periodic generative-agents-style
**reflection** pass (`reflect.py`) to consolidate the growing pool into a few cited, durable
principles.
