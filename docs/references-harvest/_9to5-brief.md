# 9TO5 Capability Brief

> Map of what 9TO5 does today vs. where it is thin, so other agents can judge whether an
> external technique fills a *real* gap. All paths verified against the working tree.

## 1. System overview

9TO5 is a personal autonomous "send one sentence at 9am, get a finished job at 5pm"
orchestration system built on a **strict-protocol / replaceable-intelligence** split
(`docs/ARCHITECTURE.md`). A **local Ollama brain** (the *Orchestrator*, default
`qwen2.5-coder:7b`, `config.py`) plans, authors prompts, replans, and owns all decisions
but never writes code; it drives a **Claude Code CLI subprocess** (the *Executor* / "hands",
`agents/executor.py`) that does every edit/test/git action; a deterministic **Verifier**
(`agents/verifier.py`) gates each subtask on a brain-authored `{cmd, expect}` check; an
**Adversary** (`agents/adversary.py`, Ollama or Gemini) critiques; a **Replanner** mutates
the remaining queue. Python plumbing under `platform_core/` wires the lifecycle
(Goal → ElaboratedGoal → Architect doc → subtasks → ExecutionStep → Verify → Review →
Replan → PR), persists canonical run state as task JSON (`state/task_schema.py`), and
exposes everything through **Nightclaw** — the Discord bot + Bloomberg-style web dashboard
surface (`notifications/`), all fed by one process-global event bus
(`notifications/event_bus.py`). The product promise rests on `platform_core/runtime/`:
file-backed cross-process control (`control.py`) and crash/deadline auto-recovery
(`resilience.py`).

---

## 2. Per-domain capability map

### 2.1 Orchestration / planning
**Today.** A fixed linear pipeline: `agents/elaborator.py` → `agents/architect.py`
(Claude writes a design doc) → planner. Planning is a **single Ollama JSON call plus one
self-critique pass**: `OrchestratorPlanMixin.authorSubtaskPlan` then `critiqueSubtaskPlan`
(`platform_core/orchestration/plan_mixin.py`), governed by `ORCHESTRATOR_CONSTITUTION`
(same file) which makes the brain emit a per-subtask **invocation spec** weaponizing Claude
Code's seven primitives. Phases are sequenced in
`run_phase_mixin.py::_freshRunPhase` (architect retried at higher effort if weak), executed
by `run_loop_mixin.py::runExecutionLoop`. Replanning is per-subtask add/remove mutation
(`_applyReplan`) plus horizon-fill backfill for self-improvement runs (`_backfill`,
`_continueAfterDrain`). Discovery pre-flight exists (`agents/discovery`, `_runDiscoveryPhase`).
Dependencies live in the schema (`depends_on`) and are honored by `state.nextActionable`.

**Thin / gap.** Planning is shallow and brittle: one-shot LLM decomposition (1–4 subtasks,
`MAX_SUBTASKS`), no tree-search / HTN / look-ahead / cost-budgeted planning. The whole layer
is bottlenecked on a 7B brain whose JSON is unreliable — the code is saturated with fallback
scaffolding (e.g. planner-returns-empty fallback that re-derives per-requirement subtasks in
`authorSubtaskPlan`; "brain authored no batch" open-ended fallback in `_backfill`). The
planner does not really author `depends_on` graphs; replan is greedy title-dedup add/remove,
not a re-derivation of the task graph. No notion of subtask cost/risk in scheduling.

### 2.2 Long-horizon durability (checkpoint / resume / step-state)
**Today.** `platform_core/runtime/resilience.py::run_with_recovery` wraps the run:
crash → reload persisted state (committed progress is source of truth) → exponential backoff
resume, with a **progress-aware, horizon-scaled restart budget** (≈1 retry/15min), deadline
awareness (`deadline_passed`/`remaining_seconds`), orphan resume (`pick_resume_task`), and
stall detection (`is_stalled`). State is checkpointed at **subtask granularity** — every
`TaskState` mutation calls `save()` (`state/task_schema.py`). Resume un-strands `in_progress`
subtasks back to `pending` and rebuilds the architect doc from Obsidian
(`run_phase_mixin.py::_resumeSetup`). Within a subtask, Claude sessions are carried across
retries via `--resume <session_id>` (`agents/executor.py`, dropped on error). A livelock
guard aborts after 40 no-progress iterations (`run_loop_mixin.py::_livelockGuard`).

**Thin / gap.** **No mid-subtask checkpoint.** A crash or kill mid-attempt loses the entire
attempt; resume restarts that subtask from scratch (status flips `in_progress`→`pending`).
There is no durable step-level journal of what the executor actually did — only the final
Obsidian note + the `experience.db` row. `--resume` is best-effort and discarded on any error
(`execute_mixin.py` carries `resume_session` only when `not is_error`). Self-edits to loop
code are deliberately inert until a fresh process (bytecode pinned, comment in
`run_with_recovery`). No transactional/WAL execution log to replay a partially-completed
subtask.

### 2.3 Memory / knowledge
**Today.** Three stores. (1) **Experience Ledger** — SQLite `state/experience.db`
(`memory/experience*.py`, schema in `experience_schema.py`: runs, subtasks, embeddings,
failure_modes, lessons, pr_outcomes, solutions). (2) **Retrieval-augmented brain**
(`memory/retrieval.py`): local `nomic-embed-text` embeddings, cosine top-k over *passing*
subtasks, rendered into a tiny `lessons_block` prepended to brain prompts. (3) **Obsidian**
(`memory/obsidian.py`): notes + disk fallback, the persistent context store; plus
`writeClaudioMd` living per-subtask CLAUDE.md. **Claude-capabilities knowledge**
(`knowledge.py` facade → `platform_core/knowledge_base/`) scrapes/compresses Claude Code docs
and injects a `CLAUDE CODE CAPABILITIES` block into *every* brain call. Also
`memory/conviction_ledger.py`, `learning/knowledge_graph.py`, `learning/solution_cache.py`,
`memory/user_prefs.py`.

**Thin / gap.** Retrieval is an **O(n) full scan**: `top_k_similar` iterates *every* embedded
row and cosines in Python (`memory/retrieval.py`) — no ANN index, won't scale. Only
verify-passing rows are retrievable and the `lessons_block` carries *metadata only* (effort,
model, attempt count) — **not the actual solution content**. There is **no persistent RAG
index over the codebase itself**; repo understanding is re-discovered fresh each run by the
architect/discovery phase and then hard-truncated into prompts. No semantic chunking, no
cross-run code memory beyond titles.

### 2.4 Agent-comms / topology
**Today.** Star topology: every agent (elaborator, architect, planner, executor, verifier,
adversary, replanner — `docs/ARCHITECTURE.md` roster) communicates only through the
orchestrator and the task-JSON state; there is no peer-to-peer channel. Optional intra-subtask
fan-out exists via the **workflow registry** (`workflows/registry.py`, definitions in
`workflows/definitions/`): the brain can set `use_workflow` + a `workflow_definition` of
phases with `parallel` agents (e.g. the parallel `code_review` workflow). Subtask-level
parallelism via `ThreadPoolExecutor` (`run_loop_mixin.py::_handleParallelBatch`). A Gemini
**second brain** (`agents/second_brain.py`, `agents/gemini_driver.py`) provides an independent
review opinion. Cast personas (`notifications/cast.py`) are cosmetic voices.

**Thin / gap.** No blackboard / shared scratchpad between concurrent workers — they edit one
shared git tree, and adversary remediation is *disabled* under parallelism because a
snapshot/restore would clobber peers (`execute_mixin.py::_remediationTreeShared`). The
multi-agent "workflow" is delegated wholesale to Claude Code's own subagent mechanism, opaque
to 9TO5. No dynamic agent spawning, role negotiation, debate, or message-passing beyond a
single advisory adversary verdict.

### 2.5 Verification / self-correction
**Today.** Deterministic gate (`agents/verifier.py` + `verifier_runner.py`): `expect` ∈
{`exit_zero`, `stdout_contains`, `stdout_regex`, `stdout_contains_all`, `stdout_regex_all`},
run via cmd.exe with process-tree-kill on timeout. For enumerated multi-deliverable goals the
brain (or a fallback) **synthesizes a compound content-scan verify** that word-tokenizes a
target file and asserts ≥1 marker per requirement (`buildContentScanVerify`,
`buildRequirementsVerify`), marked `strict` so the repair fallback can't rescue partial work.
Self-correction: bounded retry loop with failure-feedback re-prompting
(`execute_mixin.py::_runAttemptLoop`, `MAX_SUBTASK_ATTEMPTS`); brittle-verify repair
(`_repairVerify`); a self-ref quality gate; **bounded adversary remediation** with git
snapshot/restore so a fix can only keep-or-improve (`_remediate`); clarifier auto-answering so
the brain resolves executor questions without a human (`llm_mixin.py::_resolveClarifications`);
a pre-PR adversary + test-suite gate (`run_phase_mixin.py::_resolvePrePrGate`).

**Thin / gap.** Verification is **shallow** — it proves a command exits 0 or that
strings/tokens are *present in source*, not that behavior is *correct*. `buildContentScanVerify`
asserts markers exist, which a sufficiently verbose wrong implementation can satisfy. No
test-generation, no property-based/semantic checks, no spec-vs-diff review, no regression
detection beyond the pre-PR suite. The adversary is advisory (blocking only in some modes) and
remediation is a single bounded attempt, skipped entirely under parallelism. Much of the
machinery exists to paper over the weak brain authoring bad verifies.

### 2.6 Tool-use / environment
**Today.** All real tool use happens **inside the Claude subprocess**; the brain controls it
indirectly through the invocation spec (`agents/executor.py`): living CLAUDE.md inject, named
skills, a read-only subagent, effort→`--effort`, deterministic hooks via
`.claude/settings.json`, and per-effort model routing (`config.MODEL_BY_EFFORT`, low→haiku /
default·high→sonnet / xhigh·ultracode→opus) with `--fallback-model`. Surfaces are pluggable:
terminal (live, L3), browser (`agents/browser_executor.py`, gated `BROWSER_LAYER_ENABLED`),
native/UIA (`agents/native_executor.py`, future). Guard hooks
(`agents/hooks.py` → `hooks_selfmod`/`hooks_destructive`) can hard-block a tool call
(PreToolUse exit-2), and self-ref runs pass `--disallowedTools Edit/Write` for
`CORE_PROTECTED_FILES`.

**Thin / gap.** 9TO5 has **no tool-orchestration layer of its own** — no MCP surface, no
per-tool policy/learning; it cannot see or constrain individual tool calls except via the
coarse hook guards. The executor runs `--dangerously-skip-permissions` directly on the real
project tree (no container/sandbox, no per-subtask capability scoping). Browser/native layers
are partial/gated. Tool *selection* is entirely Claude's; 9TO5 learns surfaces only at a
coarse `surfaces_used(spec)` level.

### 2.7 Observability
**Today.** One process-global nervous system: `notifications/event_bus.py` (`LiveEventBus`
ring buffers + SSE fan-out), `notifications/subprocess_feed.py` (taps Claude stdout JSONL into
tool events + 30s heartbeat), `notifications/webdash.py`/`webdash_page.py` (live terminal-style
page, `/api/events` SSE, `/api/state`), `notifications/tunnel.py` (supervised public tunnel).
Plus Discord dashboards/embeds, narrative surfaces (`run_arc.py`, `narration.py`,
`health_aura.py`, `reflection_post.py`, codenames), per-run comparative intelligence
(`memory.experience.compare_run`), hook-driven telemetry (`tools/claude_metrics.py`), and the
`experience.db` ledger. `agents/trace_replay*.py` exists for replay.

**Thin / gap.** Observability is **presentation-heavy** (Discord theater, personas, replay
GIFs) but lacks a structured **distributed trace / span tree** across a run. Per-step token/cost
accounting is best-effort (`cost_usd` captured opportunistically), not a consistent metric
series; no threshold alerting (cost/error-rate); logs are explicitly forbidden as a source of
truth. Step-level replay-debugging of a *failed* attempt is limited.

### 2.8 Human-loop / control-safety
**Today.** `platform_core/runtime/control.py::ControlBus` — file-backed, atomic, three-process
(run + Discord bot + web), carrying abort / pause / `kill_subprocess` / `force_replan` / gate
decisions / queued plan-ops, with cross-process + in-process locking and corrupt-bus rebuild.
Two control modes (gated vs autonomous); approval **gates** at `plan` and `pre_pr` with
deadline timeout (`run_phase_mixin.py`). Discord commands drain into ops
(`control_mixin.py::_applyOps`: skip/add/retry/edit) plus operator **intents** and injected
context folded into the next spec (`plan_mixin.py::_foldOperatorContext`, `state.activeIntents`).
Per-subtask feedback embeds (Subsystem C). Safety: **universe** scoping
(`allowed_paths`/`hard_boundaries`) + `self_modification_guard` + destructive-pattern scan +
`CORE_PROTECTED_FILES` disallow.

**Thin / gap.** Safety is **path/regex-based**, not semantic — no review of *what an action
does*, no per-subtask capability sandbox (executor runs skip-permissions). Human-loop is coarse:
approve/reject/skip whole gates or subtasks, no inline per-step approval; by design the system
*removes* the human (brain auto-answers clarifications) rather than escalating. Rollback exists
only as the git snapshot inside adversary remediation; there is no run-wide undo. Action audit
is at hook granularity only.

### 2.9 Prompt / context-engineering
**Today.** Every brain call is augmented with the live `CLAUDE CODE CAPABILITIES` block
(`knowledge.py::injectCapabilities`) and runs at a **fixed** `num_ctx` with the user payload
trimmed to fit (`llm_mixin.py::_ollamaChat` + `_fitUserToCtx`) — a deliberate fix for an
Ollama reload storm. The brain authors a structured invocation spec; the executor gets a living
per-subtask CLAUDE.md (`memory.obsidian.writeClaudioMd`) plus a role-scoped **playbook/charter**
via `--append-system-prompt` (`agents/playbook.py`). SIE folds learned context into authoring:
policy hint, retrieved lessons, post-mortem guidance, knowledge-graph context, confidence nudge,
warm-start (`plan_mixin.py::_sieAuthoringContext`). A prompt registry supports champion/challenger
constitutions (`learning/prompts.py`); loose JSON extraction salvages malformed brain output
(`brain_io._chatJson`).

**Thin / gap.** Context engineering is mostly **truncation** to fit the 7B (`architect_doc[:1500]`,
`[:4000]`, tiny `RETRIEVAL_MAX_TOKENS`). No hierarchical summarization / compaction of
accumulating long-run history; the executor's context is just the regenerated CLAUDE.md.
Retrieval injection is metadata, not solution content. The brain's small, unreliable context
window is the structural ceiling on everything above it.

---

## 3. What would most help 9TO5 — top 8 capability gaps (ranked)

1. **Robust structured planning/decomposition** to replace the brittle one-shot 7B JSON planner — iterative or search-based decomposition (HTN / plan-and-solve / decomposition-with-verification) that produces reliable task graphs with dependencies instead of the current fallback-saturated single call.
2. **Deeper semantic verification** beyond exit-code/substring/token-presence checks — auto-generated tests, property/behavioral assertions, and spec-vs-diff LLM-judge rubrics, since today's verifies certify that markers exist, not that the work is correct.
3. **Mid-subtask checkpoint & step-level resume durability** — a transactional execution journal so a crash or kill mid-attempt resumes from the last completed step instead of re-running the whole subtask from scratch.
4. **Persistent, scalable codebase RAG** — an ANN-indexed semantic index over code *and* solution content (not an O(n) cosine scan of passing-subtask metadata) so repo knowledge persists across runs rather than being re-discovered and truncated each time.
5. **Structured step/tool-level tracing with cost-aware metrics** — a span tree and consistent per-step token/cost accounting with threshold alerting and failed-attempt replay, replacing the presentation-heavy but trace-poor observability stack.
6. **Sandboxed / isolated executor environment** — container or per-run worktree isolation with semantic capability scoping, instead of running `--dangerously-skip-permissions` on the real tree behind only path/regex guards.
7. **Richer multi-agent topology** — a shared blackboard/scratchpad and coordinated parallel workers (or structured debate) so concurrent subtasks stop clobbering one shared git tree and adversary remediation need not be disabled under parallelism.
8. **Long-horizon context compaction** — hierarchical summarization/rolling memory of run history and injection of actual solution content, lifting the structural ceiling imposed by the local 7B brain's small, hard-truncated context window.
