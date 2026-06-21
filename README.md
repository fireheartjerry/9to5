# 9TO5

A personal **autonomous AI orchestrator** that runs long-horizon engineering
tasks at **zero marginal API cost** by using a local model as its brain and the
Claude Code CLI as its hands.

- **Brain** — Ollama `qwen2.5:7b` (local). Authors every prompt, plans, replans.
- **Hands** — Claude Code CLI (`claude --print --dangerously-skip-permissions`),
  one fresh subprocess per step. Never decides anything.
- **Memory** — Obsidian vault (Local REST API, with disk-write fallback).
- **Notifications** — Discord embeds + a `!status` / `!plan` / `!log` command bot.

Python is plumbing: Ollama → prompt → Claude Code CLI → output → Obsidian →
Ollama → repeat.

## Phase 1 scope
Layer 3 (Terminal/CLI) only. The **Adversary is stubbed** (auto-approves).
Browser (Layer 1) and Native (Layer 2) come later.

## Setup
```powershell
# Python deps (venv already created at .\venv)
venv\Scripts\python -m pip install -r requirements.txt

# Required, running locally:
#   - Ollama serving qwen2.5:7b   (ollama serve; ollama pull qwen2.5:7b)
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

# Useful flags:
#   --mode watch|gated   watch = autonomous + abort (default); gated = approval gates
#   --work-dir C:\path   working dir for Claude Code CLI (default PROJECT_ROOT)
#   --web-port 8787      local web dashboard port    --no-web  disable it
#   --no-pr              skip the GitHub PR step

# While a run is live you get a glass box:
#   - Discord: one self-updating dashboard embed + milestone embeds
#   - Web:     http://127.0.0.1:8787/  (Abort/Pause/Resume/Approve/Reject/Skip)
#   - The run polls the channel itself, so these commands work with no extra process:
#       !status !plan !log !abort !pause !resume !approve !reject !skip <id> !add <title> !retry

# Optional richer gateway bot (separate, long-lived process):
venv\Scripts\python -m notifications.command_bot
```

**Verification gate:** the brain authors a `verify` `{cmd, expect}` per subtask;
a subtask is only `done` when its command passes (`exit_zero` /
`stdout_contains:` / `stdout_regex:`), otherwise the executor is re-prompted with
the failure and retried up to 3×.

## Layout
| Path | Role |
|------|------|
| `main.py` | entrypoint: goal input, elaboration approval, launch |
| `orchestrator.py` | brain (Ollama) + core loop (architect→plan→verify→exec→PR) |
| `config.py` | env/config + logging + UTF-8 stdio |
| `control.py` | `ControlBus` — file-backed cross-process control (abort/pause/gates/ops) |
| `agents/` | elaborator, architect, executor, adversary (stub), replanner, **verifier** |
| `state/task.py` | lean task-state model + JSON persistence |
| `memory/obsidian.py` | REST-first, disk-fallback note writer/reader |
| `notifications/discord_bot.py` | REST embeds + message create/edit/poll helpers |
| `notifications/dashboard.py` | live self-updating Discord dashboard embed |
| `notifications/webdash.py` | stdlib web dashboard (view + control buttons) |
| `notifications/command_bot.py` | discord.py gateway bot (rich `!` commands) |

See `CLAUDE.md` for the full mental model handed to spawned Claude sessions.

## Conventions
`ALL_CAPS` constants, `snake_case` variables, `camelCase` functions,
`pathlib.Path` everywhere.
