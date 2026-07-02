# State and Control

State schema and source-of-truth rules for 9TO5.

## Source-of-truth rules

| Concern | Canonical source |
|---|---|
| Current run/task state | `state/tasks/<task_id>.json` or canonical state store |
| Control commands | `ControlBus` under `state/control/` |
| Persistent notes/context | Obsidian + disk fallback |
| Execution transcript | logs / task notes / traces |
| Verification status | verifier result object |
| Dashboard display | derived view only |

Do not make Discord, web dashboard, or generated embeds canonical state.

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

`ControlBus` lives in:

```txt
platform_core/runtime/control.py
```

It stores one JSON per task under:

```txt
state/control/
```

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

## Retention sweep (per-run artifact GC)

`platform_core/ops/retention.py` runs a best-effort sweep at run teardown (gated by
`RETENTION_ENABLED`, default true; fail-open — never blocks or breaks a run):

- `state/blackboard/*.jsonl` and `state/compaction/ctx-*.txt` — keep the newest
  `RETENTION_KEEP_RECENT` (default 10) plus anything younger than `RETENTION_MAX_AGE_DAYS`
  (default 14); prune the rest. These were previously unbounded (one file per run).
- Terminal-status task JSON older than `RETENTION_ARCHIVE_AGE_DAYS` (default 30) is **moved**
  into `state/archive/` — never deleted (the wipe-safety constraint). A live or unreadable
  run is never archived (`_isTerminalTaskFile` fails closed).
- The sweep never touches `.py` files under any circumstance.

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
