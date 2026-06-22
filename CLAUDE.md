# 9TO5 — context for any Claude Code session

You may have been spawned by 9TO5 as the **Executor** (the hands). Read
this so you understand the system you are part of.

## What 9TO5 is
A personal autonomous AI orchestrator that runs long-horizon tasks (≈9am–5pm) at
**zero marginal API cost**. It never calls an AI API. Its *brain* is a local
Ollama model; its *hands* are the Claude Code CLI, driven via subprocess.

## The mental model (two separate things)
1. **Orchestrator brain** = Ollama `qwen2.5:7b`, running locally. It reads task
   state JSON + Obsidian context and **authors every prompt** sent downstream. It
   also does initial planning and replans after each subtask.
2. **Executor hands** = Claude Code CLI subprocess. It **receives** Orchestrator-
   authored prompts and does the actual work (code, file edits, bash, git). It
   **never decides anything.**

Python is pure plumbing: call Ollama → get prompt → fire at Claude Code CLI →
capture output → save to Obsidian → feed back to Ollama → repeat.

## The 4 layers (only Layer 3 is built — Phase 1)
- **Layer 1 Browser** — CDP driving claude.ai / chatgpt.com (Phase 2).
- **Layer 2 Native** — UIA/pywinauto driving desktop apps (Phase 3).
- **Layer 3 Terminal/CLI** — *PRIMARY, built now*: Claude Code CLI, gh, git.
- **Layer 4 Local model** — Ollama `qwen2.5:7b` as the brain.

## Agent roster
- **Orchestrator** — Ollama; authors prompts, plans, replans. (`orchestrator.py`)
- **Executor** — Claude Code CLI subprocess. (`agents/executor.py`)
- **Architect** — Claude Code CLI with a locked system prompt prepended; output
  saved as `architect.md`. (`agents/architect.py`)
- **Adversary** — Phase 1 runs a **real Ollama-backed critique**: given the
  executor output + trigger reason it returns a verdict (`approved`/`challenged`)
  with concrete concerns; degrades to a conservative auto-approve if no brain is
  wired or the call fails. Phase 2 → GPT-5.5 via chatgpt.com CDP. (`agents/adversary.py`)
- **Replanner** — Ollama, after every subtask; may mutate the subtask list.
  (`agents/replanner.py`)

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

## Adversary trigger signals
Strings in Claude output: "I'm not sure", "unclear", "multiple approaches",
"could go either way"; ≥3 failed attempts on one subtask; every 3rd subtask
(heartbeat floor); right before PR creation.

## File structure
```
main.py  orchestrator.py  config.py  control.py  requirements.txt  CLAUDE.md  README.md
agents/  __init__.py elaborator.py architect.py executor.py adversary.py replanner.py verifier.py
state/   __init__.py task.py
memory/  __init__.py obsidian.py
notifications/ __init__.py discord_bot.py dashboard.py webdash.py command_bot.py
docs/superpowers/{specs,plans}/   # brainstorm spec + implementation plan
```

## Task-state JSON (lean — long content lives in Obsidian)
`state/tasks/<task_id>.json`. `task_id` = uuid4. `meta` {goal_raw,
goal_elaborated, time_horizon_hours, started_at, deadline_at, status,
blocked_reason}. `plan` {architect_design_doc, subtasks[]}. Plus
`adversary_reviews[]`, `notifications[]`, `context_handoffs[]`, `obsidian`
{vault_root, vault_task_dir, index_note}. Each subtask: {subtask_id, title,
description, assigned_to, layer, status, depends_on, started_at, completed_at,
output_ref, github_pr, session}.

## Obsidian vault structure
Notes written via Local REST API (`https://127.0.0.1:27124`, self-signed cert,
`verify=False`, `Authorization: Bearer <OBSIDIAN_API_KEY>`), **with automatic
disk-write fallback** under `C:\supercritical\vault\9to5\`.
```
vault/9to5/tasks/<task_id>_<date>/
  index.md  architect.md  replan-log.md
  subtasks/st-001.md  subtasks/st-001-rv.md
  handoffs/ho-001.md
vault/9to5/sessions/
```
> NOTE: the REST API on :27124 serves whichever vault is *open* in Obsidian. If a
> different vault is open, the 9to5 key is rejected (401) and the layer
> falls back to disk — notes still land in the correct folder. Open the
> `9to5` vault in Obsidian to use REST.

## Discord + live dashboards (the glass box)
- **Live Discord dashboard** (`notifications/dashboard.py`): ONE embed created at
  run start and PATCH-edited every step (status, subtask X/Y, attempt, last
  verify ✓/✗, elapsed/ETA, recent events). Primary "while away" surface.
- **Milestone embeds** (`notifications/discord_bot.py`): planning_start, architect_done,
  adversary_triggered, subtask_failed, complete, aborted.
- **Web dashboard** (`notifications/webdash.py`): stdlib HTTP server on
  `127.0.0.1:8787` — live view + Abort/Pause/Resume/Approve/Reject/Skip buttons.
- **Gateway command bot** (`notifications/command_bot.py`, run
  `python -m notifications.command_bot`): `!status !plan !log !abort !pause
  !resume !approve !reject !skip <id> !add <title> !retry`.
- The run **also polls the channel itself** (REST) between steps, so `!abort` etc.
  work from the single `main.py` process without the gateway bot running.

## Run control + verification
- **ControlBus** (`control.py`) — one JSON per task under `state/control/`, shared
  by the run, the command bot, and the web dashboard (abort/pause/decisions/plan-ops).
- **Control modes** (`--mode`): `watch` (autonomous + abort, default) or `gated`
  (approval gates at the `plan` and `pre_pr` boundaries — answer with `!approve`/
  `!reject` or the web buttons).
- **Verification gate** (`agents/verifier.py`) — the brain authors a `verify`
  `{cmd, expect}` per subtask (`expect` ∈ `exit_zero | stdout_contains:<t> |
  stdout_regex:<re>`). After the executor runs, the cmd runs in the work dir; a
  subtask is `done` only if it passes, else the executor prompt is re-authored
  with the failure output and retried up to `MAX_SUBTASK_ATTEMPTS` (3).

## Current phase / what is stubbed
Phase 1 (Layer 3 only). **LIVE:** verification gate + retry, live Discord
dashboard, web dashboard, gateway command bot, watch/gated control modes,
plan editing, **Ollama-backed Adversary critique** (advisory verdict +
concerns; conservative auto-approve fallback). Phase 2 swaps the Adversary's
brain for GPT-5.5 via chatgpt.com CDP. Layers 1/2 not built. Everything reads
config from `C:\supercritical\.env` — never hardcode secrets.

## Self-Improvement Philosophy

When 9to5 runs on itself, it operates with one principle: improve indiscriminately. No numerical targets. No fixed feature list. No "add 5 features" goals. Instead: hunt bugs, strengthen error handling, refactor weak areas, improve code quality, add missing tests, tighten the orchestration loop, improve Obsidian write reliability, make Discord embeds richer, improve Ollama prompt quality — whatever is most impactful at each moment based on what the codebase actually needs. Keep going instrumentally until the time horizon ends. The measure of success is not a checklist completed but a codebase that is meaningfully better than when the run started.

## Universe-constrained execution
The universe is about **surgical precision, not permission**. 9to5 may freely create or
modify whatever files a goal needs — it is never restricted to an allowlist of operations.
The universe simply keeps its edits **surgical and on-scope** so they don't sprawl goofily
into unrelated code. Every task carries a **universe** in `meta.universe` (extracted during
goal elaboration): `description`, `allowed_paths` (the area work is *expected* to focus on —
a precision hint, **not** a hard allowlist), `allowed_to_expand_to` (related code/deps it may
also touch), `hard_boundaries` (the **only** hard stop — files/dirs that must NEVER be touched:
secrets, VCS internals, virtualenvs, task state). The `self_modification_guard` PreToolUse hook
blocks edits **only** to `hard_boundaries` (read dynamically from task meta) — everything else is
fair game. 9to5 operates with full indiscriminate intensity, precise rather than caged.

## Conventions
`ALL_CAPS` module constants, `snake_case` variables, `camelCase` functions,
`pathlib.Path` everywhere (never `os.path`).
