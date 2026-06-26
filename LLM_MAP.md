# 9TO5 LLM Map

Repo navigation guide for Terminal A sessions and 9TO5-spawned Executor subprocesses.

This file answers: where does the relevant code probably live?

For behavioral rules, read `CLAUDE.md`.
For system design, read `docs/ARCHITECTURE.md`.
For dangerous files and invariants, read `docs/DANGER_MAP.md`.
For doc-sync rules, read `docs/DOC_MAINTENANCE.md`.

## Core vocabulary

- **Terminal A**: human-operated Claude Code terminal used to develop 9TO5.
- **9TO5 Executor**: Claude Code subprocess spawned by 9TO5.
- **Orchestrator**: local Ollama brain that plans, authors prompts, and replans.
- **Nightclaw**: Discord bot / orchestrator-facing bot surface.
- **Run**: full work session.
- **Subtask**: meaningful unit of work inside a run.
- **ExecutionStep**: one concrete action.
- **Verification**: proof that work succeeded.

## Current top-level structure

```txt
main.py
orchestrator.py
config.py
control.py
contracts.py        # cross-module payload shapes (TypedDicts)
protocols.py        # replaceable-intelligence seams (Executor/Verifier/Reviewer/Brain)
lifecycle.py        # canonical RunStatus/SubtaskStatus vocabulary
resilience.py  selfmod.py  knowledge.py  llm_io.py
identity.py  provenance.py  epoch.py      # guard primitives (role/provenance/epoch)
requirements.txt
CLAUDE.md
README.md

agents/         # executor, architect, adversary, replanner, verifier, drivers
learning/       # SIE subsystem (32 modules) — traces, retrieval, policy, finetune, rollout
memory/         # obsidian + experience DB
state/
notifications/  # Discord/web dashboards, command bot, cogs
tools/          # AI-nav layer: repo_map.py, dev.py, affected_tests.py, codemod.py
docs/
tests/
```

## Module ownership map

| Area | Likely files | Responsibility |
|---|---|---|
| Entry point / run loop | `main.py` | Starts runs, wires orchestrator, control, dashboards, and execution loop |
| Brain/planning | `orchestrator.py`, `agents/elaborator.py`, `agents/replanner.py` | Goal elaboration, planning, replanning, prompt authorship |
| Execution | `agents/executor.py` | Claude Code subprocess execution |
| Architecture drafting | `agents/architect.py` | Generates architecture/design notes |
| Adversarial review | `agents/adversary.py` | Critique/review verdicts |
| Verification | `agents/verifier.py` | Runs verify commands and decides pass/fail |
| Run control | `control.py` | ControlBus, pause/resume/abort/approval/plan ops |
| Task state | `state/task.py`, `state/tasks/` | Task JSON structure and persistence |
| Memory | `memory/obsidian.py` | Obsidian REST API + disk fallback |
| Discord dashboard | `notifications/dashboard.py`, `notifications/discord_bot.py` | Live embed and milestone embeds |
| Web dashboard | `notifications/webdash.py` | Local web UI and controls |
| Gateway bot | `notifications/command_bot.py`, `notifications/bot/` | Discord gateway command bot / cogs |
| Nightclaw surfaces | `notifications/*`, especially `bot/`, `ask.py`, `cast.py`, `engagement.py`, `ops.py` | Bot, cogs, dashboards, engagement, UI |
| Learning / SIE | `learning/` (32 modules: `trace*`, `policy.py`, `finetune.py`, `promotion.py`, `rollout.py`, …) | Consumes traces, proposes improvements — **downstream only**, never mutates a live run |
| Guards / boundaries | `agents/hooks.py`, `identity.py`, `provenance.py`, `epoch.py` | The only hard stops (self-modification guard) |
| Contracts / seams / status | `contracts.py`, `protocols.py`, `lifecycle.py` | Cross-module shapes, replaceable-intelligence Protocols, canonical status vocab |
| Resilience / self-mod | `resilience.py`, `selfmod.py` | Crash recovery + self-modification baseline |
| Dev / AI-nav tooling | `tools/repo_map.py`, `tools/dev.py`, `tools/affected_tests.py`, `tools/codemod.py` | `@AI-MAP` headers, `.repo-map.json`, `AGENTS.md`, fast check loop |
| Config | `config.py`, `.env` | Runtime configuration |
| Docs | `CLAUDE.md`, `LLM_MAP.md`, `docs/` | Operating and architectural context for future agents |

## When changing code, read these docs first

| Change area | Read |
|---|---|
| Any edit | `CLAUDE.md` |
| Finding files / ownership | `LLM_MAP.md` |
| Orchestration / agents / lifecycle | `docs/ARCHITECTURE.md` |
| Risky files / boundaries | `docs/DANGER_MAP.md` |
| Tests / CI / verification commands | `docs/TESTING.md` |
| Discord / dashboard / Nightclaw | `docs/NIGHTCLAW.md` |
| State / task JSON / ControlBus | `docs/STATE.md` |
| Obsidian / memory / context | `docs/MEMORY.md` |
| Docs consistency | `docs/DOC_MAINTENANCE.md` |
| Hooks / skills | `docs/CUSTOM_SKILLS_AND_HOOKS.md` |
| Repeated workflow | `docs/edit_recipes/` |

## Common edit locations

### Add or modify a verification mode

Likely files:

- `agents/verifier.py`
- tests for verifier behavior
- `docs/TESTING.md`
- `docs/edit_recipes/add_verification_mode.md`

Do not touch:

- dashboard code unless display changes
- ControlBus unless control behavior changes
- lifecycle statuses unless pass/fail state changes

### Add a dashboard metric

Likely files:

- `notifications/metrics.py`
- `notifications/dashboard.py`
- `notifications/discord_bot.py`
- relevant dashboard tests
- `docs/NIGHTCLAW.md`

Do not mutate canonical task state just to display a metric.

### Add a Discord/Nightclaw command

Likely files:

- `notifications/commands.py`
- `notifications/command_bot.py`
- `notifications/bot/cogs/*`
- `control.py` if command changes ControlBus behavior
- `docs/NIGHTCLAW.md`
- `docs/STATE.md` if control state changes

### Change task state schema

Likely files:

- `state/task.py`
- `control.py` if control state is involved
- `main.py` if lifecycle assumptions change
- `docs/STATE.md`
- `docs/ARCHITECTURE.md`
- migration/backward compatibility tests

### Change Obsidian/memory behavior

Likely files:

- `memory/obsidian.py`
- `docs/MEMORY.md`
- memory tests

Preserve disk-write fallback.

### Change self-improvement / learning

Likely files:

- learning modules if present
- `docs/ARCHITECTURE.md`
- `docs/DANGER_MAP.md`
- `docs/CUSTOM_SKILLS_AND_HOOKS.md`

Learning may consume traces and propose improvements, but should not bypass verifier/adversary/guards.

## Preferred future structure

When refactoring for LLM-native editability, prefer clear ownership:

```txt
orchestration/
  task_graph.py
  lifecycle.py
  replanner.py

execution/
  claude_code_runner.py
  subprocess_step.py
  execution_result.py

verification/
  verify_spec.py
  verify_runner.py
  expectation_matcher.py

control/
  control_bus.py
  commands.py
  state_store.py

dashboard/
  discord_embed.py
  web_server.py
  metrics.py

memory/
  obsidian_store.py
  experience_db.py

learning/
  trace_mining.py
  eval_generation.py
  adapter_experiments.py

guards/
  universe.py
  path_policy.py

drivers/
  browser_executor.py
  native_executor.py
  chatgpt_driver.py
  vlm_healer.py
```

Do not force this structure in one giant patch. Use it as the target direction when refactors are justified.

## Golden rule

A future Terminal A or 9TO5 Executor should be able to answer quickly:

- Where is the relevant code?
- Which docs explain it?
- What state is canonical?
- What tests should be run?
- What boundaries must not be crossed?
