# State and Control

State schema and source-of-truth rules for 9TO5.

## Source-of-truth rules

| Concern | Canonical source |
|---|---|
| Current run/task state | `state/tasks/<task_id>.json` or canonical state store |
| Control commands | `ControlBus` over SQLite `state/control.db` |
| Persistent notes/context | Obsidian + disk fallback |
| Execution transcript | logs / task notes / traces |
| Verification status | verifier result object |
| Dashboard display | derived view only |

Do not make Discord, web dashboard, or generated embeds canonical state.

## Single-writer rule (task JSON)

**Only the orchestrator run process writes `state/tasks/<task_id>.json`.** Every other
process (gateway bot, launcher, web dashboard, cogs) expresses intent through the
ControlBus (`requestAbort`, `pushOp`) and the run loop drains + applies it. Concretely:

- `!mode` queues a `set_mode` plan op; the run applies it at the next drain tick (~seconds).
- The launcher's stale cleanup (`work_launcher._reapStale`) calls `bus.requestAbort()` +
  `pushOp({"op": "mark_stale", ...})` and then `state/task_io.py:reapDeadRun(task_id)` —
  the **only** sanctioned out-of-process task-JSON write, and it refuses unless
  `heartbeat.isRunAlive(task_id)` is False and the task is still non-terminal.
- In-run daemon threads that touch shared `TaskState` (tunnel supervisor, dashboard)
  must hold the orchestrator's `_state_lock` (`TunnelManager(state=..., state_lock=...)`,
  `dashboard.start(..., state_lock=...)`).

There is no `state_epoch` field anymore — it was a write-side stamp with zero readers.

## Liveness (heartbeats)

`platform_core/runtime/heartbeat.py` is the ONE liveness primitive (no mtime heuristics):

- The run loop writes `state/heartbeats/<task_id>.json` (~every 10s, throttled `beat`).
- The gateway bot writes `state/heartbeats/gateway-bot.json` from its presence loop.
- `isRunAlive(task_id, grace_s=45)` = heartbeat fresh OR recorded pid alive (falls back
  to the task JSON's `meta.run_pid`); `isBotAlive(grace_s=90)` is the bot-side twin.
- Unprovable liveness (psutil missing but a pid recorded) counts as ALIVE — never
  false-abort a run you cannot prove dead.

## Launch handshake

`/work` launches carry `--launch-id <token>`; the spawned `main.py` writes
`state/launch/<token>.json` (`{task_id, pid, at}`) at startup and the launcher confirms
by reading it (`work_launcher.waitForLaunch`) — never by polling for the newest state
file. The check-active → spawn → confirm window is serialized by an in-process lock plus
the O_EXCL sidecar `state/launch/launching.lock`.

## IPC files

Cross-process bridge files (Live Terminal nav/mirror) live under `state/ipc/`, OUTSIDE
the task store, so `task_io.iterStored` scans can never misparse them. `iterStored`
additionally requires task shape (`task_id` + dict `meta`) and counts+logs skipped files.

## Task state location

```txt
state/tasks/<task_id>.json
```

`task_id` should be `uuid4`.

## Lean task JSON

Long content belongs in Obsidian, not bloated task JSON.

Suggested structure:

```yaml
meta:
  goal_raw:
  goal_elaborated:
  time_horizon_hours:
  started_at:
  deadline_at:
  status:
  blocked_reason:
  codename:        # run identity, e.g. IRON_PHOENIX (platform_core/ops/codenames.py); shown on every surface
  tunnel_url:      # last validated public tunnel URL (TunnelManager); resume reuses it if still live
  arc: []          # run narrative arc beats [{text, at}] (notifications/run_arc.py)
  health_score:    # last composite Health Aura 0-100 (notifications/health_aura.py)
  universe:
    description:
    allowed_paths:
    allowed_to_expand_to:
    hard_boundaries:

plan:
  architect_design_doc:
  subtasks: []

adversary_reviews: []
notifications: []
context_handoffs: []

obsidian:
  vault_root:
  vault_task_dir:
  index_note:
```

## Subtask fields

Each subtask should include:

```yaml
subtask_id:
title:
description:
assigned_to:
layer:
status:
depends_on:
started_at:
completed_at:
output_ref:
github_pr:
session:
```

## Lifecycle/status vocabulary

**Canonical source: `lifecycle.py`** (`RunStatus` / `SubtaskStatus` enums). The enum
VALUES are the actual on-disk strings, so `meta["status"] == "done"` keeps working.
Use the enums in new code; do not invent new status strings here.

Run statuses (as actually persisted in `meta["status"]`):

```txt
created  architecting  planning  executing  done  partial  blocked  failed  aborted  crashed
```

`crashed` is persisted but **resumable** — recovery depends on it NOT being treated
as terminal. The terminal set (`lifecycle.TERMINAL_RUN_STATUSES`, mirroring
`state/task.py:_TERMINAL`) is `done, aborted, partial, blocked, failed` plus the
legacy spelling `complete`.

Subtask statuses (`state/task.py` addSubtask/updateSubtask):

```txt
pending  in_progress  done  blocked  failed  removed
```

Synonyms (`completed` / `complete` / `success` / `ok` / `passed` / `finished`) all mean
`done`; fold them with `lifecycle.normalizeRunStatus()` at read boundaries (dashboards,
reports) rather than introducing a new value. Do not rename status values without
updating `lifecycle.py`, its tests, and dashboard consumers.

## ControlBus

`ControlBus` (`platform_core/runtime/control.py`) is a thin facade over the transactional
SQLite store `platform_core/runtime/control_store.py`:

```txt
state/control.db        (WAL, busy_timeout=30s; tables: flags, decisions, ops, ledger)
```

Every mutation is one `BEGIN IMMEDIATE` transaction on a per-call connection — SQLite is
the cross-process serializer (no sidecar locks, no atomic-replace retries). The legacy
`state/control/<task_id>.json` mailboxes are retired: the first time a `control.db` is
created, any remaining files are imported one-shot and renamed `*.json.migrated`.

Ingestion authority: the **gateway bot owns Discord ingestion**; the in-run REST poller
(`control_mixin._translateDiscord`) engages only while `heartbeat.isBotAlive()` is False
(logged once per transition). Every ingested `!` command carries its Discord message id
into `pushOp(op, source_msg_id=...)` — `UNIQUE(task_id, source_msg_id)` makes the same
message ingested twice ONE op, while two identical user messages (two ids) are two ops
(so `!retry` twice retries twice; the old whole-op identity dedup is gone).

The autonomy spend ledger is a `ledger` table (`attempt_id UNIQUE`, `spent = SUM(usd)`):
idempotent per attempt and structurally impossible to zero by a corrupt-rebuild.

Gate waits go through `bus.waitDecision(gate, timeout, poll)` — one shared wait with
abort / timeout / deadline-escape / night-mode escapes instead of per-caller sleep loops.

It is shared by:

- active run
- command bot
- web dashboard

It handles:

- abort
- pause
- resume
- approve
- reject
- skip
- retry
- plan operations
- `kill_subprocess` / `force_replan` boolean signals (Spec B granular controls)
- Spec B queued ops: `intent`, `intent_clear`, `inject_context`, `set_effort`,
  `set_run_effort`, `extend_deadline` (drained by `control_mixin._applyOps`)

## Intelligence & Control fields (Spec B)

Additive `meta` fields (`state/task_schema.py`):

- `user_intents`: append-only list of `{text, at, added_at_completed}`. `activeIntents()`
  returns intents added < 2 subtask-completions ago (they expire after 2 completions).
- `instinct_flags`: list of `{text, at}` — Nightclaw instinct fires at most once per run.
- `injected_context`: queued one-shot CLAUDE.md context, consumed by the next attempt
  (`takeInjectedContext()` clears it).
- `run_effort_override` / per-subtask `effort_override`: live effort overrides folded into
  the invocation spec by `plan_mixin._foldOperatorContext`.

Cross-session operator preferences live OUTSIDE task state in `memory/user_prefs.py`
(`<state_dir>/../user_prefs.json`), set via `!prefer` / `!brief set` / `!prefs`.

New `!` command surface (registry in `notifications/commands.py`, help in
`branding._CATEGORIES`): `intent`, `prefer`, `prefs`, `effort`, `mode`, `replan`,
`deadline`, `kill`, `inject`, `set-effort`. Ollama-backed info commands
(`brief`/`why`/`explain`/`wisdom`/`growth`) are gateway-only (`bot/cogs/log_cog.py`) so a
slow brain call never blocks the run loop.

## Control modes

`watch`:

- autonomous
- abort/pause/resume still possible

`gated`:

- approval gates at configured boundaries
- known boundaries include `plan` and `pre_pr`

## State schema change rules

When changing state schema:

1. Update tests.
2. Update this doc.
3. Update `LLM_MAP.md` if ownership changes.
4. Update dashboard consumers if displayed state changes.
5. Add backward compatibility or migration notes if old task files may exist.
6. Avoid changing status strings casually.

## Layer-1 / Layer-2 derived artifacts (Epic 3)

- `state/exp_index/` — ChromaDB ANN index (derived cache over `state/experience.db`; the
  embedding BLOB column stays source of truth; rebuild via `retrieval.backfill_embeddings`).
  Collection name pins `EMBED_MODEL`+dim so an embedder swap starts a fresh space.
- `state/compaction/ctx-*.txt` — raw context offloaded by the compaction layer; the brain
  payload carries a `[raw context offloaded to <path>]` breadcrumb. Safe to prune.
- New tables in `state/experience.db`: `exp_content` (solution_content/post_mortem/importance)
  and `subtasks.importance` (denormalized salience). All additive via CREATE-IF-NOT-EXISTS.
- Optional dependency: `chromadb` (Phase 2). Absent wheel -> `NullIndex` fail-open to the O(n)
  cosine scan; never required for a run.

## Universe state

Universe lives under:

```txt
meta.universe
```

Fields:

- `description`
- `allowed_paths`
- `allowed_to_expand_to`
- `hard_boundaries`

`allowed_paths` are precision hints.

`hard_boundaries` are hard stops.

## State edit danger

Do not edit live task/control files as implementation.

Only touch runtime state if:

- task explicitly asks for migration/repair
- test fixture is being updated
- docs/examples are being updated
- fake state fixture is being created
