# 9TO5

A personal **autonomous AI orchestrator** that runs long-horizon engineering
tasks at **zero marginal API cost** by using a local model as its brain and the
Claude Code CLI as its hands.

- **Brain** — Ollama `qwen2.5-coder:7b` (local). Authors every prompt, plans, replans.
- **Hands** — Claude Code CLI (`claude --print --dangerously-skip-permissions`),
  one fresh subprocess per step. Never decides anything.
- **Memory** — Obsidian vault (Local REST API, with disk-write fallback).
- **Notifications** — Discord embeds + a `!status` / `!plan` / `!log` command bot.

Python is plumbing: Ollama → prompt → Claude Code CLI → output → Obsidian →
Ollama → repeat.

## Phase 1 scope
Layer 3 (Terminal/CLI) only. The **Adversary** runs a real Ollama-backed critique
(verdict + concerns, conservative auto-approve fallback). Browser (Layer 1) and
Native (Layer 2) come later.

## Setup
```powershell
# Python deps (venv already created at .\venv)
venv\Scripts\python -m pip install -r requirements.txt

# Required, running locally:
#   - Ollama serving qwen2.5-coder:7b   (ollama serve; ollama pull qwen2.5-coder:7b)
#   - Claude Code CLI on PATH     (claude --version)
#   - Obsidian + Local REST API   (open the `9to5` vault for REST;
#                                   otherwise notes fall back to disk)
# Secrets come from .\.env (DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID,
# OBSIDIAN_API_KEY, OBSIDIAN_PORT, OBSIDIAN_HTTPS, OBSIDIAN_VAULT_PATH,
# PROJECT_ROOT, LOG_PATH).
```

## Run
```powershell
# Interactive (you approve the elaboration, then walk away):
venv\Scripts\python main.py --goal "Build X at C:\path\to\file.py" --hours 1

# Fully non-interactive (walk away — watch + control from Discord/web):
venv\Scripts\python main.py --goal "..." --hours 1 --auto-approve

# Chat-style one-liner (implies --auto-approve; flags still pass through):
venv\Scripts\python main.py @9to5 make the test suite green --hours 2

# Useful flags:
#   --mode watch|gated   watch = autonomous + abort (default); gated = approval gates
#   --work-dir C:\path   working dir for Claude Code CLI (default PROJECT_ROOT)
#   --web-port 8787      local web dashboard port    --no-web  disable it
#   --no-pr              skip the GitHub PR step
#   --dry-run            simulate a FULL run offline (no Ollama/Claude/Discord/Obsidian)

# While a run is live you get a glass box:
#   - Discord: one self-updating dashboard embed + milestone embeds
#   - Web:     http://127.0.0.1:8787/  (Abort/Pause/Resume/Approve/Reject/Skip)
#   - The run polls the channel itself, so these commands work with no extra process:
#       !status !plan !log !abort !pause !resume !approve !reject !skip <id> !add <title> !retry

# Optional richer gateway bot (separate, long-lived process):
venv\Scripts\python -m notifications.command_bot
```

**Verification gate:** the brain authors a `verify` `{cmd, expect}` per subtask;
a subtask is only `done` when its command passes (`exit_zero` / `stdout_contains:` /
`stdout_regex:`, plus the compound `stdout_contains_all:` / `stdout_regex_all:` with
`||`-separated needles that assert every deliverable of a multi-requirement goal —
all stdout modes ALSO require exit 0, and there is no test-runner special case),
otherwise the executor is re-prompted with the failure and retried up to 3×.

## Tests
```powershell
# full suite -- pytest ONLY (the conftest sandbox that blanks live creds is pytest-only)
venv\Scripts\python -m pytest -n auto -q
```
The command is single-sourced as `FULL_SUITE` in `tools/repo_map_render.py`.
GitHub Actions runs path-aware lanes (`.github/workflows/tests.yml`): fast lane on
push (py3.12); fast (py3.11+3.12) + slow + smoke on PRs; `compileall -q tests` first.

## Layout
| Path | Role |
|------|------|
| `main.py` | entrypoint: goal input, elaboration approval, launch |
| `orchestrator.py` | brain (Ollama) + core loop (architect→plan→verify→exec→PR) |
| `config.py` | env/config + logging + UTF-8 stdio |
| `platform_core/runtime/control.py` | `ControlBus` — SQLite-backed (`state/control.db`) cross-process control (abort/pause/gates/ops) |
| `platform_core/orchestration/{society,workflows}/` | workforce coordination and shipped workflow definitions |
| `platform_core/simulator/testing/` | virtual-operator and end-to-end simulation helpers |
| `agents/` | elaborator, architect, executor, adversary, replanner, **verifier**, clarifier, playbook |
| `developer_tools/` | any-project introspection, solution-space exploration, and safe refactoring |
| `human_nature/faculties/` | affect, governance, identity, signals, and live psyche runtime |
| `state/task.py` | lean task-state model + JSON persistence |
| `memory/obsidian.py` | REST-first, disk-fallback note writer/reader |
| `notifications/discord_bot.py` | REST embeds + message create/edit/poll helpers |
| `notifications/dashboard.py` | live self-updating Discord dashboard embed |
| `notifications/webdash.py` | stdlib web dashboard (view + control buttons) |
| `notifications/command_bot.py` | discord.py gateway bot (rich `!` commands) |

See `CLAUDE.md` for the full mental model handed to spawned Claude sessions.

## Discord notifications

9to5 maintains a **live dashboard embed** (single message, PATCH-edited every
step) plus **milestone embeds** for key events.

### Live dashboard embed fields

| Field | Content |
|-------|---------|
| Status | Current task status (e.g. `executing`) |
| Mode | `watch` or `gated` |
| Progress | `▰▰▰▱▱▱▱▱▱▱▱▱▱▱▱▱ 20% (2/10)` — 16-cell bar |
| Subtasks | `✅ N  ⚡ N  ⬜ N  ❌ N  ·  XX% pass` |
| Current | Active subtask ID + title; appends `(attempt N)` on retries |
| Model | Model in use |
| Mode | Control mode |
| Elapsed | Wall-clock time since run start |
| ETA | Remaining-time estimate based on pace so far; `—` until ≥1 subtask done |
| Replans | Total replanner invocations |
| Adversary | Total adversary triggers |
| Effort | Visual effort-level bar |
| Last verify | Most recent verification result |
| Recent events | Up to 10 timestamped events (HH:MM format) |

### Control-panel buttons

Two rows attached to the dashboard embed:

- **Row 1 — flow** (secondary/success): ⏸️ Pause · ▶️ Resume · ✅ Approve
- **Row 2 — destructive** (secondary/danger): ⚔️ Reject · ⏭️ Skip · 🛑 Abort

### Milestone embeds

| Trigger | Embed |
|---------|-------|
| Task complete | Shows subtasks done/total, success rate %, elapsed, replans, adversary count, PR link |
| Subtask failed | Shows subtask ID, attempts, exit code, verify command, stdout/stderr tail |
| Gate needed | Prompts `!approve` / `!reject` |
| Blocked | Shows reason + Claude Code's question (separated by `━━━ Claude Code asks ━━━`) |
| Adversary triggered | Shows verdict + concerns |

### Status embed (!/status command)

Fields: Status, Mode, Subtasks, Current, Working dir, ⏰ Deadline (shown only when set).

## Conventions
`ALL_CAPS` constants, `snake_case` variables, `camelCase` functions,
`pathlib.Path` everywhere.
