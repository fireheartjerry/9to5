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
| Current run state | task JSON / canonical state store / SQLite if introduced |
| Control commands | ControlBus |
| Persistent notes/context | Obsidian + disk fallback |
| Execution transcript | run logs / task notes / trace records |
| Verification status | verifier result object |
| Human control | Discord/web UI commands |
| File safety boundaries | Universe + self-modification guard |
| Coordination artifacts (Epic 5) | Blackboard — facts/results/proposals/votes (NOT status; task JSON still owns status/claim) |
| Dashboard display | derived view only |

Discord and web dashboards are windows into state, not state machines.

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

Verifier executes a brain-authored `{cmd, expect}`.

Supported expectation modes:

```txt
exit_zero
stdout_contains:<text>
stdout_regex:<regex>
stdout_contains_all:<t1>|||<t2>|||...   # all listed texts must be present
stdout_regex_all:<p1>|||<p2>|||...      # all listed patterns must match
```

A subtask is done only if verification passes.

If verification fails:

1. Capture command, stdout, stderr, exit code.
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

## Universe-constrained execution

The universe is about surgical precision, not permission.

Fields:

- `description`: scope of task
- `allowed_paths`: expected focus area; precision hint, not hard allowlist
- `allowed_to_expand_to`: related code/dependencies that may be touched if needed
- `hard_boundaries`: actual forbidden paths

Hard boundaries should include secrets, VCS internals, venvs, generated/runtime state unless explicitly authorized, and other dangerous paths.

## Workflow registry

`workflows/registry.py` loads `WorkflowDefinition` JSON files from `workflows/definitions/` and
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
`False`). The `society/` package is a peer of `agents/`/`workflows/`:

- **`society/coordinator.py` — `Coordinator`**: deterministic Python (NOT a new LLM). Posts
  Task-Ledger facts, selects a file-disjoint batch (Epic-1 CAS seam), spawns one `WorkerAgent`
  per claim, collects results, detects contested subtasks, and enforces a per-run USD budget
  governor (`SOCIETY_TOKEN_BUDGET_USD`).
- **`society/worker.py` — `WorkerAgent`**: role-scoped wrapper over `agents/executor.py::runClaude`.
  Performs the atomic CAS claim against **task JSON** (single source of truth for status/claim),
  builds a narrowed `InvocationSpec`, runs in its work_dir, posts a `result` to the blackboard.
- **`society/blackboard.py` — `Blackboard`**: append-only per-run JSONL coordination surface
  (threadlock + best-effort cross-process file lock, malformed-line tolerant). Holds ONLY
  coordination artifacts; every append mirrors to `event_bus` for live surfaces.
- **`society/roles.py`**, **`society/inbox.py`**, **`society/debate.py`**: role registry +
  capability router, addressing/cursor helpers, and bounded structured debate
  (`selectNextSpeaker` + arbiter via `agents/second_brain.py::consult`, round-cap + diff-hash
  oscillation guard). Debate verdicts are **advisory**; the verifier still gates.

**LOCKED concurrency boundary:** threads + per-worker git worktree filesystem isolation
(mirrors `run_loop_mixin._handleParallelBatch`), NOT process-per-worker. Run-loop wiring lives
in `society/society_batch.py` (extracted to keep `run_loop_mixin.py` ≤450); the mixin's
`_societyGate`/`_handleSocietyBatch` delegate to it. With the flag **off**, the gate is closed
and the star/parallel path is byte-identical to today.

**Epic-1 co-design (Durable Execution — worktrees + file-disjointness):** Epic 5 ships and is
fully testable without Epic 1 via named seams with standalone fallbacks — `selectDisjointBatch`
defaults to deps-only batching (`file_sets_fn=None`), workers default to the shared tree
(advisory mode, serial), `BlackboardEntry.span_id` stays `None`, and `_remediationUnsafe`
already encodes the worktree-isolation flip (peer-safe once each worker edits its own tree).

## Module layout (post-modularization)

As of 2026-06-27, the codebase uses sub-module extraction to keep every file ≤450 lines
and every function ≤70 lines. Key patterns:

### Mixin decomposition — `orchestrator.py`
The `Orchestrator` class is assembled from 7 focused mixin files:

| Mixin | Responsibility |
|---|---|
| `orchestrator_llm_mixin.py` | LLM/Ollama chat, eval, model selection |
| `orchestrator_plan_mixin.py` | Subtask planning, spec authoring, backfill |
| `orchestrator_control_mixin.py` | Gate handling, ControlBus, Discord commands |
| `orchestrator_execute_mixin.py` | Attempt loop, SIE, replan, subtask enrichment |
| `orchestrator_review_mixin.py` | Adversary review, Gemini session, PR gate, git helpers |
| `orchestrator_run_loop_mixin.py` | Execution loop, backfill drain, livelock, parallel batch |
| `orchestrator_run_phase_mixin.py` | Run lifecycle: preamble, phases, teardown, crash/abort |

Helper modules re-exported into `orchestrator.py` namespace:
`orchestrator_brain_io.py`, `orchestrator_knowledge.py`, `orchestrator_time.py`

### Sub-module extraction with re-export facade

| Facade | Sub-modules |
|---|---|
| `config.py` | `config_paths.py`, `config_discord.py`, `config_llm.py` |
| `knowledge.py` | `knowledge_scraper.py`, `knowledge_builder.py`, `knowledge_compress.py` |
| `memory/experience.py` | `experience_schema.py`, `experience_runs.py`, `experience_subtasks.py`, `experience_policy.py`, `experience_adapters.py`, `experience_solutions.py` |
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
