# 9TO5 — Capabilities

> Auto-documented from `CLAUDE.md` and `README.md`. Describes 9to5's
> architecture, the Claude Code primitives it weaponizes, its control surfaces,
> the verification gate, and current capabilities.

## What 9to5 is
A personal **autonomous AI orchestrator** that runs long-horizon engineering
tasks (≈9am–5pm) at **zero marginal API cost**. It never calls an AI API.

- **Brain** — local Ollama `qwen2.5:7b`. Reads task-state JSON + Obsidian
  context and **authors every prompt** sent downstream; does initial planning
  and replans after each subtask.
- **Hands** — the Claude Code CLI (`claude --print --dangerously-skip-permissions`),
  one fresh subprocess per step. **Receives** brain-authored prompts and does the
  actual work (code, file edits, bash, git). **Never decides anything.**
- **Memory** — Obsidian vault via Local REST API, with automatic disk-write fallback.
- **Notifications** — Discord embeds + a `!status` / `!plan` / `!log` command bot.

Python is pure plumbing: Ollama → prompt → Claude Code CLI → output → Obsidian →
feed back to Ollama → repeat.

## Architecture — the 4 layers (only Layer 3 is built, Phase 1)
- **Layer 1 Browser** — CDP driving claude.ai / chatgpt.com (Phase 2).
- **Layer 2 Native** — UIA/pywinauto driving desktop apps (Phase 3).
- **Layer 3 Terminal/CLI** — *PRIMARY, built now*: Claude Code CLI, gh, git.
- **Layer 4 Local model** — Ollama `qwen2.5:7b` as the brain.

## Agent roster
- **Orchestrator** — Ollama; authors prompts, plans, replans. (`orchestrator.py`)
- **Executor** — Claude Code CLI subprocess. (`agents/executor.py`)
- **Architect** — Claude Code CLI with a locked system prompt prepended; output
  saved as `architect.md`. (`agents/architect.py`)
- **Adversary** — **STUB in Phase 1**: logs the trigger reason, returns
  `approved`. Phase 2 → GPT-5.5 via chatgpt.com CDP. (`agents/adversary.py`)
- **Replanner** — Ollama, after every subtask; may mutate the subtask list.
  (`agents/replanner.py`)

## The six Claude Code primitives 9to5 weaponizes
9to5 drives the Claude Code CLI through these primitives, each authored by the
Ollama brain per step:

1. **Headless execution** — `claude --print --dangerously-skip-permissions`,
   one fresh subprocess per step, fully non-interactive.
2. **Brain-authored prompts** — every prompt fired at Claude is composed by the
   local model from task state + Obsidian context; the Executor never decides.
3. **Locked system-prompt prepend** — the Architect runs with a fixed system
   prompt prepended, producing `architect.md`.
4. **Subtask execution with verify-and-retry** — per subtask, the brain emits a
   `verify {cmd, expect}` contract that gates completion (see below).
5. **Tooling access** — git, `gh`, and bash inside the Claude Code subprocess
   for code, file edits, commits, and PR creation.
6. **Replan feedback loop** — Claude output is saved to Obsidian and fed back to
   Ollama, which may mutate the remaining subtask list after each step.

## Core loop
0. Human types goal + time horizon.
0.5 **Elaborator** (Ollama) expands the goal → human approves/edits (last human input).
1. **Architect** — Ollama authors an architecture prompt → Claude writes `architect.md`.
2. **Planning** — Ollama turns spec + `architect.md` into a JSON subtask list.
3. **Execution** — per subtask: Ollama authors the Claude prompt → fire subprocess →
   **run the brain-authored verify cmd → retry-on-fail (≤3)** → save Obsidian note →
   adversary check → replan → update state. Control (abort/pause/skip/gate) is
   checked at every boundary.
4. **Complete** — create GitHub PR via `gh` (best effort) → Discord complete embed.

**Adversary trigger signals:** strings in Claude output ("I'm not sure",
"unclear", "multiple approaches", "could go either way"); ≥3 failed attempts on
one subtask; every 3rd subtask (heartbeat floor); right before PR creation.

## Control surfaces — the glass box
- **Terminal / CLI** — `main.py` flags: `--mode watch|gated`, `--work-dir`,
  `--web-port`, `--no-web`, `--no-pr`, `--auto-approve`. Backed by **ControlBus**
  (`control.py`), one JSON per task under `state/control/`, shared by the run,
  the command bot, and the web dashboard.
  - **Control modes:** `watch` (autonomous + abort, default) or `gated`
    (approval gates at the `plan` and `pre_pr` boundaries).
- **Discord** — a **live dashboard** (`notifications/dashboard.py`): ONE embed
  created at run start and PATCH-edited every step (status, subtask X/Y, attempt,
  last verify ✓/✗, elapsed/ETA, recent events). Plus **milestone embeds**
  (`notifications/discord_bot.py`): planning_start, architect_done,
  adversary_triggered, subtask_failed, complete, aborted. The run **polls the
  channel itself** between steps, so `!status !plan !log !abort !pause !resume
  !approve !reject !skip <id> !add <title> !retry` work with no extra process.
  An optional richer **gateway command bot** (`notifications/command_bot.py`,
  `python -m notifications.command_bot`) provides the same `!` commands.
- **Web dashboard** — `notifications/webdash.py`: stdlib HTTP server on
  `127.0.0.1:8787` — live view + Abort / Pause / Resume / Approve / Reject / Skip
  buttons.

## Verification gate
`agents/verifier.py` — the brain authors a `verify` `{cmd, expect}` per subtask,
where `expect` ∈ `exit_zero | stdout_contains:<t> | stdout_regex:<re>`. After the
executor runs, the cmd runs in the work dir; a subtask is `done` **only if it
passes**, otherwise the executor prompt is re-authored with the failure output
and retried up to `MAX_SUBTASK_ATTEMPTS` (3).

## Current capabilities / what is stubbed
Phase 1 (Layer 3 only).
- **LIVE:** verification gate + retry, live Discord dashboard, web dashboard,
  gateway command bot, watch/gated control modes, plan editing.
- **STUBBED:** the **Adversary** auto-approves (Phase 2 → GPT-5.5 via
  chatgpt.com CDP). Layers 1 (Browser) and 2 (Native) are not built.
- Everything reads config from `C:\supercritical\.env` — never hardcode secrets.

## Conventions
`ALL_CAPS` module constants, `snake_case` variables, `camelCase` functions,
`pathlib.Path` everywhere (never `os.path`).
