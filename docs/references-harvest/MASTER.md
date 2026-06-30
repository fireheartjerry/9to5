# References Harvest — MASTER Index

**Date:** 2026-06-30 · **Phase deliverable:** catalog only (no 9to5 code changed).
**Inputs:** 23 cloned repos in `references/` (~21k Python, ~50k+ TS).
**Method:** 1 ground-truth agent mapped 9to5 → 23 parallel agents mined one repo
each (dual lens: *9to5-fit* + *standout*) → 9 parallel theme agents cross-cut the
best technique per domain → this synthesis. Spec:
`docs/superpowers/specs/2026-06-30-references-harvest-design.md`.

> Every ranked claim below traces to a per-repo digest (`<repo>.md`) and/or a
> theme doc (`themes/<theme>.md`), which cite exact source files. Cataloging ideas
> is license-safe; **porting code requires honoring the license** — see the ledger.

---

## 1. Headline: the 9 highest-conviction steals

The cross-cut agents independently converged on one top pick per theme. Sorted by
my recommended adoption order (impact × low effort × cross-repo corroboration).

| # | Steal | Best source(s) | Fills 9to5 gap | Effort | Theme doc |
|---|---|---|---|---|---|
| 1 | **Step-level pending-writes journal + resume-from-last-step** — persist each completed executor step to `experience.db`, replay-skip on resume instead of restarting the subtask | langgraph (`put_writes`) · swarmclaw (sqlite saver) · ms-agent-framework (superstep checkpoint) | #3 mid-subtask durability | port-code | [long-horizon-durability](themes/long-horizon-durability.md) |
| 2 | **Dual-ledger planner** — outer Task Ledger (facts+plan) + tiny per-step Progress Ledger JSON; stall-counter → root-cause replan. Many small reliable calls vs one brittle big one | autogen (Magentic-One) · ms-agent-framework | #1 brittle 7B planner | port-code | [orchestration-planning](themes/orchestration-planning.md) |
| 3 | **Execution-grounded independent verifier + Evidence Receipt** — separate read-only agent re-runs tests/build/diff, judges each criterion by evidence; green verdict from re-derivable FACTS only (diff sha, exit codes), LLM opinion non-binding | eliza (CompletionEnvelope + independent-verifier) · loki-mode (proof-generator) | #2 shallow/gameable verify | port-code | [verification-self-correction](themes/verification-self-correction.md) |
| 4 | **`@exp_cache` solution-content RAG over an ANN index** — store the real diff/answer/post-mortem, serve from a persistent index, retire the O(n) cosine scan over metadata | metagpt (exp_pool) · autogen (ChromaDB StringSimilarityMap) | #4 codebase/solution RAG | port-code | [memory-knowledge](themes/memory-knowledge.md) |
| 5 | **Worktree-per-subtask isolation + file-disjointness parallel-safety** — each worker in its own git worktree; two subtasks run concurrently only if file-sets disjoint & no dep; atomic CAS claim | hermes (`BaseEnvironment`) · claude-code (`EnterWorktree`, already drivable) · guild (`bounties.go`/`accept.go`) | #6 sandbox + #7 topology | port-code | [tool-use-env](themes/tool-use-env.md) |
| 6 | **Hierarchical context compaction + offload** — at token-trigger, summarize old half into structured `summary`, offload raw to disk w/ breadcrumb; replaces blind `[:1500]` truncation | agentscope (`_compress_context_impl`) · openclaw (`MUST PRESERVE` contract, tool-pair-safe) · eliza (`model-input-budget`) | #8 long-horizon context | port-code | [prompt-context-engineering](themes/prompt-context-engineering.md) |
| 7 | **JSON span-tree trajectory recorder w/ token+USD cost + parent→child spawn linking** — one file-based artifact = span tree + cost series + replay source; honest `0` cost for local Ollama | eliza (`trajectory-recorder`) · pydantic-ai (`SpanQuery`/`SpanTree` DSL) · swarmclaw (cost budgets+alerts) | #5 tracing/cost/replay | port-code | [observability](themes/observability.md) |
| 8 | **Semantic action-risk authorization gate** — classify each step `read/dry-run/mutating/paid/destructive`; auto-run reads, budget-meter mutating, always escalate destructive/unknown to Discord gate | eliza (`spend-allowance::decideSpendAuthorization`) | #6/2.8 path-regex→semantic safety | port-code | [human-loop-control-safety](themes/human-loop-control-safety.md) |
| 9 | **`ValidationError → RetryPrompt` structured self-correction** — feed exact schema/field errors back to the model on bad JSON instead of blind re-prompt + fallback scaffolding; + `json_repair` salvage | pydantic-ai · dify (`json_repair`) | cross-cuts #1/#2 (7B JSON tax) | idea→port | [orchestration-planning](themes/orchestration-planning.md) / [verification](themes/verification-self-correction.md) |

**Convergence signal:** step-level WAL journaling (#1), the dual-ledger planner
(#2), and execution-grounded verification (#3) each appear as a top/rank-5 steal
in **3+ independent repos** — the strongest evidence they are real, not novelty.

---

## 2. Standout / future tier (not immediate-fit, high inspiration)

| Technique | Source | Why notable | Theme |
|---|---|---|---|
| **Held-out spec evals / anti-reward-hacking** — hide 25% of acceptance checks from the build loop; empty-diff/red-tests can't "complete" | loki-mode | Directly counters the same-brain-writes-work-and-check risk | verification |
| **Counter-evidence override council (fail-closed) + memory-injection sanitizer** | loki-mode | Patches a real prompt-injection hole 9to5 has today | human-loop-safety |
| **Git-native run-ledger / commit-as-step-journal** — `<agent>: <action> <entity>` commit per step; git history = durable replayable journal | gnap · loom · claude-code (file-history) | Zero-infra path to gap #3 | durability |
| **RRF hybrid BM25+vector retrieval, int8 in-memory index** | guild · swarmclaw (MMR) | Beats pure cosine recall; cheap | memory |
| **Record/replay gateway** — deterministic replay of a failed attempt | bernstein | Debug failed runs without re-spending tokens | observability |
| **OTel `gen_ai.*` span instrumentation** | ms-agent-framework · autogen · agentscope · pydantic-ai | Industry-standard trace schema if 9to5 ever externalizes | observability |
| **Shared blackboard / pub-sub message pool** | metagpt (message pool) · bernstein (whiteboard) · agentscope (leader/worker bus) | The layer above worktree isolation for real multi-agent | topology |
| **Workforce coordinator/worker w/ per-agent scoped toolkits** | owl · autogen | Blueprint past star-only topology | topology |
| **Autonomy supervisor (auto block/replan/compact/budget_trim) + approval-gated guardian rollback** | swarmclaw | Closed-loop self-governance | human-loop-safety |
| **Claude Code features 9to5 can just turn ON** — deferred-tool search, SDK NDJSON `can_use_tool` per-tool approval, file-history snapshot/rewind, coordinator mode, persistent agent memory | claude-code | Config, not code — cheapest wins | tool-use / safety |
| **Reflection / episodic→semantic consolidation** — importance-triggered "questions→evidence→cited higher-level thoughts" | generative-agents · loki-mode | Missing hierarchical-memory primitive | memory |
| **Two-doc spec template (PRODUCT.md + TECH.md) w/ file:line anchors; self-improving skills via cron** | warp | Reviewable planning + verification rubric in one | orchestration |

---

## 3. License ledger (READ before porting any code)

| License | Repos | Porting rule |
|---|---|---|
| **MIT** | autogen, crewai, eliza, hermes, langgraph, metagpt, ms-agent-framework, openclaw, openhands, pydantic-ai, swarmclaw, agx, gnap, guild (Apache-2.0/Go) | Port freely w/ attribution + license notice |
| **Apache-2.0** | agentscope, bernstein, generative-agents, owl, guild | Port freely w/ attribution + NOTICE |
| **Modified Apache-2.0** | dify | Port w/ care; check the added clauses |
| **BUSL-1.1** (source-available) | loki-mode | **Ideas only** — do not vendor code |
| **Proprietary / leaked** | claude-code, loom | **Ideas only** — no verbatim copying |
| **AGPL** (warpui crates MIT) | warp | Patterns freely reusable; **no file copying** (except warpui) |

Most of the top-9 steals (#1–#7) come from MIT/Apache repos → portable. #3's loki
half and #6/#7's claude-code half are idea-only — but each has an MIT/Apache twin
(eliza, hermes, agentscope) you can port from instead.

---

## 4. Per-repo digests (23)

High-value-first. Each links to its full digest with techniques table + license.

**Tier A — twins / framework goldmines:** [bernstein](bernstein.md) (deterministic
coding-orchestrator, fills all 8 gaps) · [autogen](autogen.md) · [ms-agent-framework](ms-agent-framework.md)
· [agentscope](agentscope.md) · [eliza](eliza.md) · [langgraph](langgraph.md) ·
[metagpt](metagpt.md) · [swarmclaw](swarmclaw.md) · [pydantic-ai](pydantic-ai.md)

**Tier B — strong single-domain steals:** [openhands](openhands.md) (sandbox/event-stream)
· [hermes](hermes.md) (env backends) · [openclaw](openclaw.md) (compaction/sandbox)
· [crewai](crewai.md) (guardrails/flows) · [dify](dify.md) (planner/RAG) ·
[loki-mode](loki-mode.md) (evidence/anti-hacking) · [guild](guild.md) (parallel-safety/RRF)
· [agx](agx.md) (typed-DAG/checkpoints) · [generative-agents](generative-agents.md) (retrieval/reflection)
· [claude-code](claude-code.md) (executor features 9to5 underuses)

**Tier C — patterns / ideas:** [warp](warp.md) (agent-ops corpus) · [owl](owl.md)
(Workforce topology) · [loom](loom.md) (auto-commit journal) · [gnap](gnap.md)
(git-native protocol)

## 5. Theme cross-cuts (9)

[orchestration-planning](themes/orchestration-planning.md) ·
[long-horizon-durability](themes/long-horizon-durability.md) ·
[memory-knowledge](themes/memory-knowledge.md) ·
[agent-comms-topology](themes/agent-comms-topology.md) ·
[verification-self-correction](themes/verification-self-correction.md) ·
[tool-use-env](themes/tool-use-env.md) ·
[observability](themes/observability.md) ·
[human-loop-control-safety](themes/human-loop-control-safety.md) ·
[prompt-context-engineering](themes/prompt-context-engineering.md)

Ground truth: [_9to5-brief.md](_9to5-brief.md) (9to5 capability map + 8 ranked gaps).

---

## 6. Suggested next phase (NOT done here — catalog only)

If/when you want integration specs, the natural first bundle is a **"durable
execution" epic** that stacks steals #1 (step journal) + #5 (worktree isolation) +
#7 (trajectory trace): they share the same seam (the executor stream tap +
`experience.db` + git), are all MIT/already-owned, and together close gaps #3/#6/#7/#5.
Steals #2/#3/#9 form a second **"trustworthy 7B loop" epic** (planner + verifier +
JSON self-correction). Each steal already names its source file; brainstorming →
writing-plans per epic when you green-light it.
