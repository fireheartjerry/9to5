# 9TO5 Architecture

9TO5 is a personal autonomous AI orchestration system for long-horizon work sessions.

It decomposes a human goal, executes work through Claude Code subprocesses, verifies outputs, runs adversarial critique, replans when needed, and reports through Discord/web dashboards.

## Core principle

```txt
strict protocol, replaceable intelligence
```

The lifecycle, schemas, guards, state machine, verification rules, and state ownership should be deterministic and boring.

Models, Claude Code, browser models, VLMs, reviewers, and executors should be replaceable intelligence modules plugged into that protocol.

## Current mental model

### Orchestrator brain

- Local Ollama model. Brain default `OLLAMA_MODEL = qwen2.5-coder:7b` (config.py);
  vision `VLM_MODEL = qwen2.5vl:7b`, embeddings `EMBED_MODEL = nomic-embed-text`.
- Reads task state JSON and Obsidian context.
- Authors prompts.
- Plans and replans.
- Owns decisions.

### Executor hands

- Claude Code CLI subprocess.
- Executes code edits, file edits, bash, git, and local tool work.
- Does not own orchestration state.

### Python plumbing

Python wires:

```txt
Ollama prompt/decision
-> Claude Code subprocess
-> output capture
-> verification
-> state/memory update
-> adversarial review
-> replanning
-> dashboard/control update
```

## Layers

Only Layer 3 is built as the primary phase.

| Layer | Status | Role |
|---|---|---|
| Layer 1 Browser | future/partial | CDP/Playwright generic browser surface (gated by `BROWSER_LAYER_ENABLED`) |
| Layer 2 Native | future/partial | UIA/pywinauto driving desktop apps |
| Layer 3 Terminal/CLI | live | Claude Code CLI, gh, git |
| Layer 4 Local model | live | Ollama brain |

## Agent roster

| Agent | Owner/model | Main files | Responsibility |
|---|---|---|---|
| Orchestrator | Ollama | `orchestrator.py` | Plans, authors prompts, coordinates loop |
| Elaborator | Ollama | `agents/elaborator.py` | Expands human goal into approved objective |
| Architect | Claude Code CLI | `agents/architect.py` | Produces `architect.md` design doc |
| Executor | Claude Code CLI | `agents/executor.py` | Runs actual code/file/bash/git work |
| Verifier | deterministic + authored commands | `agents/verifier.py` | Runs verification command and parses expectation |
| Adversary | Ollama-backed critique | `agents/adversary.py` | Reviews executor output and raises concerns |
| Replanner | Ollama | `agents/replanner.py` | Mutates remaining subtasks after each subtask |

## Core run lifecycle

```txt
Goal
-> ElaboratedGoal
-> Architect design doc
-> TaskGraph
-> Subtask
-> ExecutionStep
-> StepResult
-> VerificationResult
-> ReviewResult
-> ReplanDecision
-> FinalRunReport
```

Everything else should attach to this spine.

Dashboards, Obsidian, ControlBus, learning traces, and Discord events should observe or derive from this lifecycle. They should not invent parallel lifecycle models.

## Core loop

1. Human provides goal + time horizon.
2. Elaborator expands the goal.
3. Human approves/edits. This is normally the last human input.
4. Architect creates design doc.
5. Orchestrator plans a JSON subtask list.
6. For each subtask:
   - Orchestrator authors Claude prompt.
   - Executor runs Claude Code subprocess.
   - Verifier runs brain-authored verify command.
   - If verification fails, retry with failure context up to max attempts.
   - Save Obsidian note.
   - Run adversary when triggered.
   - Replan if needed.
   - Update state and dashboards.
   - Check ControlBus boundaries.
7. On complete:
   - create GitHub PR via `gh` best effort
   - send Discord complete embed

## Source-of-truth ownership

| Concern | Source of truth |
|---|---|
| Current run state | task JSON `state/tasks/<task_id>.json` — **single writer: the run process** (see `docs/STATE.md`) |
| Control commands | ControlBus over SQLite `state/control.db` (`platform_core/runtime/control_store.py`) |
| Process liveness | heartbeat files `state/heartbeats/` (`platform_core/runtime/heartbeat.py`) |
| Persistent notes/context | Obsidian + disk fallback |
| Execution transcript | run logs / task notes / append-only trajectory JSONL (`state/trajectories/<run_id>.jsonl`) |
| Verification status | typed `Receipt` (`agents/verification.py`) |
| Human control | Discord/web UI commands ingested into the ControlBus |
| File safety boundaries | Universe + self-modification guard |
| Coordination artifacts (Epic 5) | Blackboard — facts/results/proposals/votes (NOT status; task JSON still owns status/claim) |
| Degradation picture | `platform_core/core/best_effort.py` registry (surfaced in doctor, webdash, final embed) |
| Dashboard display | derived view only |

Discord and web dashboards are windows into state, not state machines.

## Control plane (2026-07 rewrite)

`docs/STATE.md` is canonical; the shape:

- **ControlBus = SQLite.** `platform_core/runtime/control.py` is a thin facade over the
  transactional store `platform_core/runtime/control_store.py` (`state/control.db`, WAL;
  tables: `flags`, `decisions`, `ops`, `ledger`). Every mutation is one `BEGIN IMMEDIATE`
  transaction — SQLite is the cross-process serializer. `pushOp(op, source_msg_id=...)`
  dedups the same Discord message via `UNIQUE(task_id, source_msg_id)`; the autonomy spend
  ledger is idempotent per `attempt_id`. Gate waits go through `bus.waitDecision(...)`.
- **One Discord ingestion authority.** The gateway bot owns `!`-command ingestion; the
  in-run REST poller engages only while `heartbeat.isBotAlive()` is False.
- **Liveness = heartbeats.** The run loop and the bot write `state/heartbeats/*.json`;
  `isRunAlive`/`isBotAlive` (heartbeat fresh OR pid alive) are the only liveness checks —
  no mtime heuristics. Unprovable liveness counts as alive.
- **Single-writer task JSON.** Only the run process writes its task JSON; the launcher's
  stale cleanup goes through `state/task_io.py:reapDeadRun`, which refuses unless the run
  is provably dead. Launches carry `--launch-id`; the spawned run confirms via
  `state/launch/<token>.json`. Terminal IPC bridge files live in `state/ipc/`.
- **Abort survives crashes.** Crash recovery (`platform_core/runtime/resilience.py`)
  checks `bus.isAbort()` before resuming — an aborted run stays aborted.

## Surface layer (Observability & Surfaces)

All live surfaces are fed by one process-global nervous system; nothing bypasses it.

- **`notifications/event_bus.py` — `LiveEventBus`** (singleton via `get_bus()`): ring buffers for
  raw stdout (10k), structured events (2k), and per-subtask raw (1k). Fans every `Event`
  (`tool_use`/`raw`/`heartbeat`/`phase`/`moment`/`narration`/`health`/...) out to web SSE
  subscribers; producers never block on a slow tab.
- **`notifications/subprocess_feed.py` — `SubprocessFeed`**: created per Claude attempt in
  `execute_mixin`; taps stdout line-by-line (opt-in streaming path in `agents/executor_stream.py`,
  threaded through `runClaude(feed=...)`), parses Claude JSONL into tool events, and emits a 30s heartbeat.
- **`notifications/tunnel.py` + `tunnel_providers.py` — `TunnelManager`**: supervised public tunnel
  (cloudflared → ngrok → bore → localtunnel) with watchdog, HTTP probe, backoff restart, provider
  demotion, validate-before-announce, and resume reuse of a live `meta["tunnel_url"]`.
- **`notifications/webdash.py` (+ `webdash_page.py`)**: Bloomberg-terminal page; `/api/events` SSE,
  `/api/raw` per-subtask stdout, `/api/state` snapshot (health aura, codename, arc, wisdom trail,
  comparative, intelligence curve). Control token CSRF guard preserved. The page itself is split
  across `webdash_page.py` (facade, exports `PAGE`), `webdash_styles.py` (`STYLES`),
  `webdash_markup.py` (`MARKUP`), and `webdash_script.py` (`SCRIPT`) — a11y landmarks/focus/aria,
  confirm-modal + toast + connection-status feedback, motion, a responsive breakpoint, and an SVG
  intelligence-curve chart, all zero-dependency (stdlib `http.server` only, no CDN/build step).
- **Voice/story (best-effort, wired additively into the orchestration mixins):**
  `run_arc.py` (narrative beats), `narration.py` (rate-limited proactive narration + Moments +
  attention-mode), `reflection_post.py` (end-of-run self-reflection), `health_aura.py`
  (composite 0–100 score), `platform_core/ops/codenames.py` (run identity).
- **Discord on-demand surfaces** (`notifications/commands.py`): `!logs` / `!stdout` / `!arc` /
  `!history` read from the bus and persist as normal channel messages.
- **Comparative intelligence**: `memory/experience.compare_run(task_id)` deltas vs rolling averages.

## Verification gate

Verifier executes a brain-authored `{cmd, expect}` (optionally `targets`) through the
typed **Receipt pipeline** (`agents/verification.py`): `runReceipt` produces one frozen
`Receipt` with a `Verdict` (`PASS`/`FAIL`/`ERROR`/`SKIPPED`), the exec'd arg vector, rc,
matched/missing needles, diff-grounded files, duration, and failure feedback.
`verdictFor(rc, output, expect)` is a **pure function** — no cmd-shape special cases.

Supported expectation modes (evaluated STRICTLY; a verify without an `expect` is
rejected by the sanitizer):

```txt
exit_zero
stdout_contains:<text>              # text in stdout AND rc==0
stdout_regex:<regex>                # regex matches stdout AND rc==0
stdout_contains_all:<t1>||<t2>||... # EVERY ||-separated text present (AND rc==0)
stdout_regex_all:<p1>||<p2>||...    # EVERY ||-separated pattern matches (AND rc==0)
```

Strictness rules (R10 — these overrides are dead on purpose):

- **No test-runner FAIL→PASS override.** A green suite with a wrong stdout needle FAILS.
- **No token-scan of executor output.** Only the verify command's own rc/stdout decide.
- `verify.targets` (file paths) are **diff-grounded**: the receipt records whether the
  declared files actually changed (`agents/verification_diff.py`).
- Receipt `annotations` (envelope self-report, independent verifier, adversary verdict)
  are non-binding and NEVER override the verdict.

A subtask is done only if verification passes.

If verification fails:

1. Capture command, stdout, stderr, exit code (all carried on the Receipt).
2. Feed failure context into a retry prompt.
3. Retry up to `MAX_SUBTASK_ATTEMPTS`.
4. Trigger adversary or replanner if repeated failure occurs.

## Adversary triggers

Trigger adversary review on:

- uncertainty strings in Claude output
- repeated failed attempts
- every 3rd subtask as heartbeat floor
- pre-PR boundary

Adversary verdicts are advisory unless the current run mode treats them as blocking.

Verdict parsing fails CLOSED (`agents/adversary_review.py`): a garbled or
off-contract adversary response is treated as **CHALLENGED**, never as a silent
approve — a real challenge expressed off-contract must not neuter the PR-hold.

## Universe-constrained execution

The universe is about surgical precision, not permission.

Fields:

- `description`: scope of task
- `allowed_paths`: expected focus area; precision hint, not hard allowlist
- `allowed_to_expand_to`: related code/dependencies that may be touched if needed
- `hard_boundaries`: actual forbidden paths

Hard boundaries should include secrets, VCS internals, venvs, generated/runtime state unless explicitly authorized, and other dangerous paths.

## Workflow registry

`platform_core/orchestration/workflows/registry.py` loads `WorkflowDefinition` JSON files from `platform_core/orchestration/workflows/definitions/` and
exposes them as a dict keyed by workflow name. The orchestrator sets `InvocationSpec.use_workflow`
and `workflow_definition` to run a multi-phase agent workflow instead of a single prompt.

Built-in templates: `bug_investigation`, `code_review`, `feature_implementation`.

### code_review workflow — optimized parallel design (st-046)

The `code_review` workflow was restructured to reduce wall-clock review time by ≥20% through
parallel phase design:

**Phase 1 — Design pre-flight (sequential, 1 agent)**
Examines architectural concerns (module boundaries, interface drift, scalability) before
line-level review begins. This avoids re-discovering scope redundantly across all agents.

**Phase 2 — Parallel line-level review + test coverage (4 agents, parallel)**
- `correctness` (effort: high) — off-by-one, null dereferences, API contract violations
- `security` (effort: high) — injection, insecure deserialization, missing input validation
- `simplification` (effort: default) — dead code, duplicated logic, unnecessary abstractions
- `test-coverage` (effort: default) — missing test cases for changed code paths

`test-coverage` has no dependency on Phase 1 output, so it runs in Phase 2 at zero
sequencing cost. Wall-clock: `2T` vs `5T` sequential baseline → **≥50% reduction**.

**Synthesis** merges all five dimensions into a single severity-ranked finding list.

See `docs/workflow.md` § *Workflow registry* for the full schema and template descriptions.

---

## Learning subsystem boundary

Learning should consume traces and propose improvements.

It should not bypass:

- verifier
- adversary
- guard hooks
- universe hard boundaries
- human gates where configured
- test requirements
- source-of-truth ownership

Recommended role:

- trace recorder
- failure taxonomy
- playbook miner
- eval generator
- prompt/router optimizer
- small LoRA/adapter experiment harness

## Workforce topology (Epic 5 — agent society, OFF by default)

The default topology is a star: one Ollama brain plans, one Claude executor acts. Epic 5 adds
an optional 9to5-owned **multi-agent workforce** behind `config.SOCIETY_ENABLED` (default
`False`). The `platform_core/orchestration/society/` package belongs with the workflow registry:

- **`platform_core/orchestration/society/coordinator.py` — `Coordinator`**: deterministic Python (NOT a new LLM). Posts
  Task-Ledger facts, selects a file-disjoint batch (Epic-1 CAS seam), spawns one `WorkerAgent`
  per claim, collects results, detects contested subtasks, and enforces a per-run USD budget
  governor (`SOCIETY_TOKEN_BUDGET_USD`).
- **`platform_core/orchestration/society/worker.py` — `WorkerAgent`**: role-scoped wrapper over `agents/executor.py::runClaude`.
  Performs the atomic CAS claim against **task JSON** (single source of truth for status/claim),
  builds a narrowed `InvocationSpec`, runs in its work_dir, posts a `result` to the blackboard.
- **`platform_core/orchestration/society/blackboard.py` — `Blackboard`**: append-only per-run JSONL coordination surface
  (threadlock + best-effort cross-process file lock, malformed-line tolerant). Holds ONLY
  coordination artifacts; every append mirrors to `event_bus` for live surfaces.
- **`platform_core/orchestration/society/roles.py`**: role registry + capability router.
  (`platform_core/orchestration/society/inbox.py` and `platform_core/orchestration/society/debate.py` were deleted 2026-07-01 — unwired halves
  with zero production callers.)

**Budget gate is WIRED:** `Coordinator._handleSocietyBatch` consults `budgetExceeded()`
before EVERY worker spawn (hard pre-spawn gate against `SOCIETY_TOKEN_BUDGET_USD`), and
`platform_core/orchestration/society/society_batch.py` seeds `coord.spent_usd` from prior blackboard `budget`/cost
entries so the budget is run-wide, not per-batch.

**LOCKED concurrency boundary:** threads + per-worker git worktree filesystem isolation
(mirrors `run_loop_mixin._handleParallelBatch`), NOT process-per-worker. Run-loop wiring lives
in `platform_core/orchestration/society/society_batch.py` (extracted to keep `run_loop_mixin.py` ≤450); the mixin's
`_societyGate`/`_handleSocietyBatch` delegate to it. With the flag **off**, the gate is closed
and the star/parallel path is byte-identical to today.

**Epic-1 co-design (Durable Execution — worktrees + file-disjointness):** Epic 5 ships and is
fully testable without Epic 1 via named seams with standalone fallbacks — `selectDisjointBatch`
defaults to deps-only batching (`file_sets_fn=None`), workers default to the shared tree
(advisory mode, serial), `BlackboardEntry.span_id` stays `None`, and `_remediationUnsafe`
already encodes the worktree-isolation flip (peer-safe once each worker edits its own tree).

## Any-project capabilities (`developer_tools/`)

Three stdlib-only leaf packages give 9TO5 typed understanding of ANY project root, not just
this repo. Dependency direction is one-way: `explore` → `introspect` ← `refactor` (both
consumers import `introspect`; nothing imports back). Orchestration touches them only through
lazy, fail-open imports — with the flags off, planning and fork behavior are byte-identical.

- **`developer_tools/introspection/`** — `extractProject(root)` builds a frozen `ProjectModel` (languages,
  modules, import edges, detected test/build/lint commands proved by config files, boundary
  map) for any directory; `contextForPrompt(model, budget_chars=...)` renders a budgeted
  digest. Wiring: `plan_mixin` injects that digest into the plan prompt when
  `PROJECT_INTROSPECTION_ENABLED` (default ON) is set, capped by
  `PROJECT_INTROSPECTION_MAX_FILES` (default 4000). Fail-open: introspection errors never
  block planning.
- **`developer_tools/refactoring/`** — refactoring safety as a library: import-cycle detection
  (`findCycles`/`wouldCreateCycle`), pre-apply impact prediction (`predictImpact` →
  `ImpactReport` with orphaned usages, new cycles, affected tests), and
  `RefactorTransaction` — atomic multi-file apply with byte snapshots + on-disk crash
  journal (`recoverJournal`), py_compile gate, only-NEW-cycles gate, and an optional
  shell-free gate command. CLI: `python -m developer_tools.refactoring check <root>` (exit 1 on cycles).
  Path guard: edits escaping the root or touching `FORBIDDEN_SEGMENTS` (`.git`, `.env`,
  venvs, `node_modules`, `__pycache__`) are rejected with an explicit reason.
  Recipe: `docs/edit_recipes/refactor_multi_file.md`.
- **`developer_tools/exploration/`** — solution-space exploration over an introspected project:
  `generateApproaches` (archetype-grounded candidates, optional brain) →
  `scoreApproaches` (fit/risk/effort/testability trade-offs) → `selectOrSynthesize`;
  one-call facade `exploreSolutionSpace(goal, root_or_model)`. Wiring: when
  `EXPLORE_APPROACHES_ENABLED` (default OFF) is set, `fork_policy` seeds Epic-6 fork
  angles from ranked approach summaries (`EXPLORE_APPROACHES_N`, default 3); any failure
  falls back to the static angle list.

Proof-of-concept driver: `scripts/poc_any_project.py` (self-scan + external-repo scan).

## Platform kernel (2026-07 rewrite)

- **IO kernel** — `platform_core/core/{fsio,jsonl_io,clock,git_io}.py` are the single
  homes for atomic file IO, JSONL append/read, time, and git subprocess calls; do not
  hand-roll copies. The run trajectory is true append-only JSONL
  (`platform_core/runtime/trajectory.py` → `state/trajectories/<run_id>.jsonl`).
- **Degradation registry** — `platform_core/core/best_effort.py` (`best_effort()`,
  `recordDegradation`): swallowed best-effort failures are counted, deduped, and
  surfaced in `doctor`, the web dashboard, and one aggregated line on the final
  Discord embed. The bare-swallow count is ratcheted down by
  `python tools/dev.py swallow-ratchet` (`tools/swallow_baseline.json`).
- **Config v2** — `config.py` is a PEP 562 facade over the typed frozen registry
  `platform_core/app_config/settings.py` (layers: coded defaults < `.env` <
  `state/sie_overrides.json` as a first-class, whitelisted+bounds-checked layer).
  `platform_core/app_config/_env.py` is THE one place that touches `.env`
  (`loadEnvOnce`) and computes `PROJECT_ROOT` from repo markers (`.git`/`pyproject`),
  never from cwd. Run-scoped flags (`NIGHT_MODE`, `WEB_DASHBOARD`, ...) live on
  `settings.runFlags()` — main.py mutates that object, never module globals.
  Logging: `NINE_TO_FIVE_LOG_LEVEL` env knob + rotating file handler.
- **LLM seam** — `llm_io.chat(system, user, *, act=...)` is the single blessed LLM
  call; every call carries a structured `act` tag and simulator doubles dispatch on
  `act`, never on prompt wording. `parseJsonLoose` is the one JSON-recovery ladder.
- **Operator control** — `!kill` / `!abort` land within ~one `CANCEL_POLL_SECONDS`
  poll (default 2s): a cancel watcher tree-kills the in-flight Claude subprocess
  (`taskkill /T`), the result carries `subtype="operator_killed"` (distinct from
  `timeout`), and the attempt slot is NOT burned. Guard hooks
  (`block_destructive`, `self_modification_guard`) are registered in
  `.claude/settings.json`, composed per-run via `composeRunSettings()`, and fail
  CLOSED (a crashing guard hook blocks the action).
- **Hook environment** — the executor pins hook context via env vars, one channel per
  concern, all optional/degrade-safe: `NINE_TO_FIVE_HOOK_CTX` (JSON: guard alert +
  log paths, read by `hooks_destructive.readHookCtx()`), `NINE_TO_FIVE_TASK_FILE` /
  `NINE_TO_FIVE_TASK_ID` (pin `_resolveState()` to the run's own task instead of
  guessing via `loadLatest()`), and `NINE_TO_FIVE_SUBTASK_ID` (tell `write_obsidian`
  which subtask note to append to, overriding the in-progress-subtask scan).

## Deleted subsystems (2026-07-01 first-principles rewrite)

Zero-production-caller subsystems were removed (~-22k LOC): `monitoring/`, `scheduling/`,
`notifications/bus.py` + `predictive.py`,
`agents/orchestration_pipeline*`, `learning/{rollout,counterfactual,adapter_ops,reward}.py`,
`memory/{subtask_manager,reflection_consolidate}.py`, the retry stack
(`error_handling`/`retry_policy`/`enhanced_error_handling` — recovery is
`platform_core/runtime/resilience.py`), and
`llm_epic_flags.py`. Portfolio: `docs/superpowers/specs/2026-07-01-first-principles-rewrite-design.md`.

## Module layout (post-modularization)

The codebase uses sub-module extraction to keep every file ≤450 lines
and every function ≤70 lines. Key patterns:

### Mixin decomposition — `orchestrator.py`
The `Orchestrator` class is assembled from 8 focused mixins in
`platform_core/orchestration/`:

| Mixin | Responsibility |
|---|---|
| `llm_mixin.py` | LLM/Ollama chat, eval, model selection |
| `plan_mixin.py` | Subtask planning, spec authoring, backfill |
| `control_mixin.py` | Gate handling, ControlBus, Discord commands |
| `execute_mixin.py` | Attempt loop, SIE, replan, subtask enrichment |
| `review_mixin.py` | Adversary review, Gemini session, PR gate, git helpers |
| `run_loop_mixin.py` | Execution loop, backfill drain, livelock, parallel batch |
| `run_phase_mixin.py` | Run lifecycle: preamble, phases, teardown, crash/abort |
| `safety_mixin.py` | Semantic action-risk authorization (Epic 4) |

Helper modules re-exported into the `orchestrator.py` namespace include
`brain_io.py`, `knowledge_refresh.py`, and `time_utils.py` (same package).

### Vertical domain layout

- `developer_tools/` groups the introspection, exploration, and refactoring packages.
- `platform_core/orchestration/` owns the workforce (`society/`) and declarative workflow registry (`workflows/`); `platform_core/simulator/testing/` owns virtual-operator helpers.
- `human_nature/faculties/` groups its implementation by affect, governance, identity, signals, and runtime. `human_nature/__init__.py` maintains historical module imports as compatibility aliases.

### Sub-module extraction with re-export facade

| Facade | Sub-modules |
|---|---|
| `config.py` | `platform_core/app_config/{settings,_env,paths,discord,llm}.py` |
| `knowledge.py` | `platform_core/knowledge_base/{scraper,builder,compress}.py` |
| `memory/experience.py` | `experience_{schema,runs,subtasks,policy,adapters,solutions,evolution,pr,journal}.py` |
| `notifications/discord_bot.py` | `discord_client.py`, `discord_embeds.py`, `discord_channels.py` |
| `notifications/views.py` | `views_control.py`, `views_run.py`, `views_subtask.py` |
| `notifications/visuals.py` | `visuals_components.py`, `visuals_cards.py` |
| `agents/executor.py` | `executor_session.py`, `executor_env.py`, `executor_stream.py` |
| `agents/hooks.py` | `hooks_selfmod.py`, `hooks_obsidian.py`, `hooks_destructive.py` |
| `agents/verifier.py` | `verifier_sanitize.py`, `verifier_runner.py` |
| `agents/adversary.py` | `adversary_review.py`, `adversary_browser.py` |
| `state/task.py` | `task_schema.py`, `task_io.py` |
| `tools/dev.py` | `dev_checks.py`, `dev_reports.py` |
| `tools/repo_map.py` | `repo_map_render.py`, `repo_map_outputs.py` |

Run `python tools/size_audit.py` to verify thresholds are met.

## Design smell checklist

Be suspicious of:

- multiple status vocabularies
- dashboard becoming state source
- unstructured cross-module dicts
- side-effect-heavy functions
- dynamic imports without a central registry
- self-improvement mutating live behavior without eval gates
- generated artifacts patched as source
- test commands known only by tribal memory, a frankly ridiculous species tradition
