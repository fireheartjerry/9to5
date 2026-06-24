# 9TO5 — Orchestration Workflow Reference

> This document is the authoritative description of the 9TO5 orchestration loop.
> Every step, decision point, and retry boundary is covered here.
>
> **Scope:** Steps 0–7 of the core loop (goal input → elaboration → architecture →
> planning → execute/verify/retry → adversary review → replan → PR creation).
> Also covers: orchestration tool inventory, notification system architecture,
> error-handling resilience, and the full decision-point map.

---

## Architecture overview

```
Human goal
  │
  ▼
[Elaborator] ──── Ollama expands goal; human approves (last human touch)
  │
  ▼
[Architect] ───── Ollama authors architecture prompt → Claude writes architect.md
  │
  ▼
[Planner] ──────── Ollama turns spec + architect.md → JSON subtask list
  │
  ▼
[Core loop] ─────  for each subtask:
  │                  Ollama authors Claude prompt → subprocess → verify → retry
  │                  → Obsidian note → Adversary check → Replan → control check
  ▼
[PR] ────────────  gh pr create (best-effort) → Discord complete embed
```

---

## Step-by-step guide

### Step 0 — Goal input and mode selection

**What happens:** The user provides a natural-language goal and a time horizon
(e.g. `--hours 2`). CLI flags select the control mode.

**Control mode decision point:**

| Flag | Behaviour |
|------|-----------|
| `--mode watch` (default) | Fully autonomous; user can abort/pause from Discord or web at any time |
| `--mode gated` | Pauses at `plan` boundary and `pre_pr` boundary waiting for `!approve` / `!reject` |
| `--auto-approve` | Skips the elaboration review prompt; suitable for cron/headless runs |
| `--dry-run` | Simulates a full run offline (no Ollama / Claude / Discord / Obsidian) |

---

### Step 1 — Elaboration

**Agent:** `Elaborator` (`agents/elaborator.py`) — Ollama `qwen2.5:7b`

**What happens:** The raw goal is expanded into a structured spec: objective,
deliverables, acceptance criteria, constraints, assumptions, steps, and effort level.
The universe (scope: `allowed_paths`, `allowed_to_expand_to`, `hard_boundaries`) is
extracted here and saved to `meta.universe`.

**Decision point — human approval:**
- Unless `--auto-approve` is set, the elaborated spec is printed and the user must
  press Enter (accept) or edit inline. This is the **last human input** in a run.
- If the user rejects, the run stops cleanly.

---

### Step 2 — Architecture

**Agent:** `Architect` (`agents/architect.py`) — Ollama authors the prompt; Claude
Code CLI executes it and writes `vault/.../architect.md`.

**What happens:** Given the elaborated spec, a design document is produced covering
component boundaries, data flow, and implementation decisions.

**Output:** `architect.md` stored in the Obsidian vault (disk fallback:
`C:\9to5\vault\9to5\tasks\<task_id>_<date>\architect.md`).

---

### Step 3 — Planning

**Agent:** Orchestrator brain (Ollama) — `orchestrator.py :: _plan()`

**What happens:** Ollama receives the spec + `architect.md` and returns a JSON list
of subtasks. Each subtask has:

```
subtask_id   title   description   assigned_to   layer   depends_on
verify {cmd, expect}
```

**Decision point — gated mode:**
If `--mode gated`, the run pauses here. The user must `!approve` the plan (via
Discord command or web button) before execution begins. `!reject` aborts the run.

**Planner output is saved** to `state/tasks/<task_id>.json` under `plan.subtasks`.

---

### Step 4 — Execute / Verify / Retry loop

This is the core of the system. For each subtask (in dependency order):

#### 4a. Prompt authoring
Ollama authors a Claude Code invocation spec:
```
{prompt, claude_md_inject, skills_to_invoke, effort_level,
 pre_tool_hooks, post_tool_hooks}
```
The subtask description, context handoffs from prior subtasks, and the current
`architect.md` are all fed to the brain.

#### 4b. Execution
Claude Code CLI is launched as a subprocess:
```
claude --print --dangerously-skip-permissions [--system-prompt <inject>] <prompt>
```
`--work-dir` points to the task's isolated directory (or `PROJECT_ROOT` for
non-self-referential runs).

#### 4c. Verification gate
After the executor returns, the **Verifier** (`agents/verifier.py`) runs the verify command:
```
verify.cmd   (shell command)
verify.expect  ∈  exit_zero
               |  stdout_contains:<text>
               |  stdout_regex:<pattern>
               |  stdout_contains_all:<t1>|||<t2>|||...   (multi-requirement)
               |  stdout_regex_all:<p1>|||<p2>|||...      (multi-requirement)
```
**Decision point — pass / fail:**
- **Pass** → subtask is marked `done`; flow continues to step 4d.
- **Fail** → the failure output is appended to the next Ollama prompt and the
  subtask is retried (back to step 4a). Up to `MAX_SUBTASK_ATTEMPTS` (3) retries.
  After 3 failures the subtask is marked `failed` and the run logs the error.

#### 4d. Obsidian note
`memory/obsidian.py` writes a structured Markdown note to the vault:
- REST-first (`https://127.0.0.1:27124` with `Authorization: Bearer <key>`)
- Disk fallback: `vault/9to5/tasks/<task_id>_<date>/subtasks/st-00N.md`

#### 4e. Control check
`ControlBus` (`control.py`) is polled. Possible outcomes:

| Signal | Action |
|--------|--------|
| `abort` | Raise `AbortSignal`; run terminates immediately |
| `pause` | Block until `resume` signal; then continue |
| `skip <id>` | Mark subtask skipped; move to next |
| `add <title>` | Insert new subtask into the plan |
| `retry` | Re-run the current subtask from step 4a |

---

### Step 5 — Adversary review

**Agent:** `Adversary` (`agents/adversary.py`) — Ollama-backed critique; conservative
auto-approve fallback if Ollama is unavailable.

**Trigger conditions** (any one is sufficient):
- Executor output contains uncertainty markers: `"I'm not sure"`, `"unclear"`,
  `"multiple approaches"`, `"could go either way"`
- Subtask required ≥3 attempts
- Every 3rd subtask (heartbeat floor)
- Immediately before PR creation

**What the Adversary does:**
1. Receives the executor output + trigger reason
2. Returns a structured verdict: `approved` | `challenged`
3. If `challenged`: concerns are logged, a milestone embed is posted to Discord,
   and (in remediation mode) the executor is re-run with the concerns injected

**Decision point — verdict:**

| Verdict | Action |
|---------|--------|
| `approved` | Continue to step 6 |
| `challenged` | Concerns logged; remediation attempt; PR hold flag set |

---

### Step 6 — Replan

**Agent:** `Replanner` (`agents/replanner.py`) — Ollama

**What happens:** After every subtask, the Replanner examines the executor output
and current subtask list. It may:
- Add new subtasks (gaps discovered during execution)
- Remove subtasks (made redundant by earlier work)
- Reorder subtasks (dependency update)
- Leave the plan unchanged (most common)

Changes are applied atomically via `control.py :: applyPlanOps()` and logged to
`vault/.../replan-log.md`.

---

### Step 7 — PR creation

**What happens:** After all subtasks reach terminal state (`done` / `skipped`),
the orchestrator calls:
```
gh pr create --title "..." --body "..." --base <main_branch>
```
This is best-effort: if it fails (no remote, no GitHub auth), the run still
completes successfully.

**Decision point — gated mode:**
If `--mode gated`, the run pauses here waiting for `!approve` before calling `gh`.

**Milestone embed** is posted to Discord on completion with:
subtasks done/total, success rate %, elapsed time, replan count, adversary count, PR URL.

---

## Decision-point summary

| Boundary | Decision | Who decides |
|----------|----------|-------------|
| After elaboration | Accept / reject spec | Human (or `--auto-approve`) |
| After planning | Approve / reject plan | Human (gated) or auto (watch) |
| After each subtask verify | Pass / fail / retry | Verify command exit code |
| Each adversary trigger | Approve / challenge | Adversary (Ollama) |
| Before PR | Approve / reject PR | Human (gated) or auto (watch) |
| Any time | Abort / pause / skip | Human via Discord / web / `!` commands |

---

## Verification `expect` types

| Type | Passes when |
|------|-------------|
| `exit_zero` | Command exits with code 0 |
| `stdout_contains:<text>` | stdout includes the literal text |
| `stdout_regex:<pattern>` | stdout matches the regex pattern |
| `stdout_contains_all:<t1>|||<t2>` | stdout includes **all** listed texts |
| `stdout_regex_all:<p1>|||<p2>` | stdout matches **all** listed patterns |

Multi-requirement types (`_all`) assert every deliverable of a multi-goal subtask
in a single verify command. Introduced in `fix/multi-requirement-verify`.

---

## Error handling and resilience

| Failure mode | Behaviour |
|-------------|-----------|
| Ollama unavailable | Brain calls raise; run aborts with clear error |
| Claude Code CLI crash | Subprocess exit ≠0; treated as verify fail; retry |
| Obsidian REST 401/timeout | Falls back to disk write under `vault/9to5/` |
| Discord API error | Logged; run continues (notifications are best-effort) |
| Subtask max attempts reached | Subtask marked `failed`; Replanner may add a fix subtask |
| Adversary Ollama unavailable | Conservative auto-approve; logged as stub review |
| `gh pr create` failure | Logged; run still marked `complete` |

---

## File layout (quick reference)

| File | Role |
|------|------|
| `main.py` | Entry point — goal input, elaboration approval, subprocess launch |
| `orchestrator.py` | Brain loop — plan → spec → execute → verify → replan → PR |
| `config.py` | Env vars, constants, logging, UTF-8 stdio |
| `control.py` | `ControlBus` — file-backed cross-process abort/pause/gate/ops |
| `agents/elaborator.py` | Ollama goal expansion |
| `agents/architect.py` | Ollama-authored architecture doc via Claude Code |
| `agents/executor.py` | Claude Code CLI subprocess wrapper |
| `agents/verifier.py` | Verify command runner — `exit_zero` / contains / regex |
| `agents/adversary.py` | Ollama critique — approved / challenged verdict |
| `agents/replanner.py` | Post-subtask plan mutation |
| `state/task.py` | Lean task-state model + JSON persistence |
| `memory/obsidian.py` | REST-first, disk-fallback note writer/reader |
| `notifications/dashboard.py` | Live self-updating Discord dashboard embed |
| `notifications/webdash.py` | stdlib web dashboard — view + control buttons |
| `notifications/command_bot.py` | discord.py gateway bot — `!` commands |

---

## Orchestration tools

These are the scripts and helper modules that implement the orchestration loop.
Each maps to a discrete responsibility; they are the "how" behind every step above.

| Tool | Step(s) | Role |
|------|---------|------|
| `agents/elaborator.py` | 1 | Ollama goal expansion; extracts universe scope |
| `agents/architect.py` | 2 | Prompts Claude Code to write `architect.md` |
| `orchestrator.py :: _plan()` | 3 | Turns spec + architect doc into JSON subtask list |
| `agents/executor.py` | 4b | Launches Claude Code CLI subprocess with injected prompt |
| `agents/verifier.py` | 4c | Runs verify command; maps result to pass/fail/retry |
| `agents/adversary.py` | 5 | Ollama-backed critique; returns `approved`/`challenged` |
| `agents/replanner.py` | 6 | Post-subtask plan mutation via `applyPlanOps()` |
| `control.py` | 4e, 3, 7 | `ControlBus` — file-backed abort/pause/gate/plan-ops |
| `state/task.py` | all | Lean task-state model + JSON persistence |
| `memory/obsidian.py` | 4d | REST-first, disk-fallback Obsidian note writer |

**Decision point — which tool runs when a subtask fails:**
`verifier.py` increments the attempt counter. If `attempt < MAX_SUBTASK_ATTEMPTS`,
`orchestrator.py` re-invokes `elaborator`-authored context → `executor.py` again.
If `attempt == MAX_SUBTASK_ATTEMPTS`, the subtask is marked `failed` and
`replanner.py` is consulted to optionally add a remediation subtask.

---

## Notification system

9TO5 uses three complementary notification surfaces, all non-blocking (failures are
logged but never halt the run).

### Live Discord dashboard (`notifications/dashboard.py`)
- **One embed, continuously patched.** Created at run start; updated after every
  step with: status, `subtask X/Y`, attempt number, last verify ✓/✗, elapsed /
  ETA, and a rolling recent-events list.
- **Decision point — update frequency:** Updated after every step boundary
  (4a prompt authored, 4b execution done, 4c verify result, 4e control check).
  This is the primary "while away" surface.

### Milestone embeds (`notifications/discord_bot.py`)
Discrete embeds posted at key transitions:

| Event | Embed |
|-------|-------|
| `planning_start` | Goal + subtask count |
| `architect_done` | architect.md summary |
| `adversary_triggered` | Trigger reason + verdict |
| `subtask_failed` | Subtask title + failure output |
| `complete` | Done/total, success %, elapsed, PR URL |
| `aborted` | Reason + last completed subtask |

### Web dashboard (`notifications/webdash.py`)
- stdlib HTTP server on `127.0.0.1:8787` — live status view.
- Buttons: **Abort / Pause / Resume / Approve / Reject / Skip** — all write to
  `ControlBus` so they take effect at the next step boundary.
- **Decision point — control flow:** Any button press writes a signal to
  `state/control/<task_id>.json`; `ControlBus.check()` reads it at step 4e and
  at every gate boundary (steps 3 and 7 in gated mode).

### Discord command polling
The main `orchestrator.py` process polls the configured Discord channel between
steps (REST GET, no gateway bot required). Commands `!abort !pause !resume
!approve !reject !skip <id> !add <title> !retry` are handled inline.
The optional `notifications/command_bot.py` gateway bot provides the same
interface with lower latency.

---

## Conventions

- `ALL_CAPS` — module-level constants
- `snake_case` — variables
- `camelCase` — functions
- `pathlib.Path` everywhere — never `os.path`
- Install root: `C:\9to5` (never move)
- Secrets in `.env` — never hardcode
