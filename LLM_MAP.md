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
main.py             # public entrypoint
orchestrator.py     # public orchestrator facade
config.py           # public config facade
knowledge.py        # public Claude-knowledge facade
validate_workflows.py
selfmod.py  llm_io.py  nightclaw.py
requirements.txt
CLAUDE.md
README.md

agents/         # executor, architect, adversary, replanner, verifier, drivers
learning/       # SIE subsystem (32 modules) — traces, retrieval, policy, finetune, rollout
memory/         # obsidian + experience DB
state/
notifications/  # Discord/web dashboards, command bot, cogs
platform_core/  # internal platform plumbing: core, runtime, orchestration, ops, config internals
tools/          # AI-nav layer: repo_map.py, dev.py, affected_tests.py, codemod.py
docs/
tests/
```

## Module ownership map

| Area | Likely files | Responsibility |
|---|---|---|
| Entry point / run loop | `main.py` | Starts runs, wires orchestrator, control, dashboards, and execution loop |
| Brain/planning | `orchestrator.py`, `platform_core/orchestration/`, `agents/elaborator.py`, `agents/replanner.py` | Goal elaboration, planning, replanning, prompt authorship |
| Execution | `agents/executor.py` | Claude Code subprocess execution |
| Architecture drafting | `agents/architect.py` | Generates architecture/design notes |
| Adversarial review | `agents/adversary.py` | Critique/review verdicts |
| Verification | `agents/verifier.py` | Runs verify commands and decides pass/fail |
| Run control | `platform_core/runtime/control.py` | ControlBus, pause/resume/abort/approval/plan ops |
| Task state | `state/task.py`, `state/tasks/` | Task JSON structure and persistence |
| Memory | `memory/obsidian.py` | Obsidian REST API + disk fallback |
| Discord dashboard | `notifications/dashboard.py`, `notifications/discord_bot.py` | Live embed and milestone embeds |
| Web dashboard | `notifications/webdash.py`, `webdash_page.py`, `webdash_styles.py`, `webdash_markup.py`, `webdash_script.py` | Local web UI and controls (page split by content-type) |
| Gateway bot | `notifications/command_bot.py`, `notifications/bot/` | Discord gateway command bot / cogs |
| Nightclaw surfaces | `notifications/*`, especially `bot/`, `ask.py`, `cast.py`, `engagement.py`, `ops.py` | Bot, cogs, dashboards, engagement, UI |
| Learning / SIE | `learning/` (32 modules: `trace*`, `policy.py`, `finetune.py`, `promotion.py`, `rollout.py`, …) | Consumes traces, proposes improvements — **downstream only**, never mutates a live run |
| Guards / boundaries | `agents/hooks.py`, `platform_core/core/identity.py`, `platform_core/core/provenance.py`, `platform_core/core/epoch.py` | The only hard stops (self-modification guard) |
| Contracts / seams / status | `platform_core/core/contracts.py`, `platform_core/core/protocols.py`, `platform_core/core/lifecycle.py` | Cross-module shapes, replaceable-intelligence Protocols, canonical status vocab |
| Resilience / self-mod | `platform_core/runtime/resilience.py`, `selfmod.py` | Crash recovery + self-modification baseline |
| Dev / AI-nav tooling | `tools/repo_map.py`, `tools/dev.py`, `tools/affected_tests.py`, `tools/codemod.py` | `@AI-MAP` headers, `.repo-map.json`, `AGENTS.md`, fast check loop |
| Config | `config.py`, `platform_core/app_config/`, `.env` | Runtime configuration |
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
- `platform_core/runtime/control.py` if command changes ControlBus behavior
- `docs/NIGHTCLAW.md`
- `docs/STATE.md` if control state changes

### Change task state schema

Likely files:

- `state/task.py`
- `platform_core/runtime/control.py` if control state is involved
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

## Platform Core Guide

Use `platform_core/` for internal plumbing. Keep root files as public facades and entrypoints:

```txt
platform_core/
  app_config/       # config internals re-exported by config.py
  cli/              # CLI parsing helpers used by main.py
  core/             # contracts, identity, epoch, provenance, lifecycle, tracing, surfaces
  knowledge_base/   # knowledge scrape/build/compress internals re-exported by knowledge.py
  ops/              # doctor, health, staging validation, workflow validation, wipe
  orchestration/    # orchestrator mixins and helpers used by orchestrator.py
  runtime/          # ControlBus, retry/error handling, resilience
  simulator/        # dry-run simulation and simulation-safe parsing
```

Prefer editing the narrow implementation module under `platform_core/`, while preserving the root facade when callers already import it.

## Golden rule

A future Terminal A or 9TO5 Executor should be able to answer quickly:

- Where is the relevant code?
- Which docs explain it?
- What state is canonical?
- What tests should be run?
- What boundaries must not be crossed?
