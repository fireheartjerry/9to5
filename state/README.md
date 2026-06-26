# `state/` — the canonical run state (source of truth)

The authoritative store for a run's lifecycle. Everything else (dashboards, Discord, logs) is a
view derived from here. Index: `state/AGENTS.md`. Schema detail: `docs/STATE.md`.

## What lives here
- **`task.py`** — `TaskState`: `meta` (goal, universe, status, timestamps), `plan.subtasks[]`,
  adversary reviews, notifications, Obsidian refs. Atomic writes (temp + replace). `setStatus`,
  `addSubtask`/`updateSubtask`, `nowIso`, `_TERMINAL`.
- **`tasks/<task_id>.json`** — one lean file per run (`task_id` = uuid4). Long content lives in Obsidian.

## Canonical vocabulary
Status values come from **`lifecycle.py`** (`RunStatus`/`SubtaskStatus`); `_TERMINAL` mirrors
`lifecycle.TERMINAL_RUN_STATUSES`. Do not invent status strings here — edit `lifecycle.py` first.

## Must NOT
- Be treated as editable implementation: don't hand-edit live `tasks/*.json` except for an
  explicit migration/repair/fixture task. The self-modification guard treats `state/tasks/` and
  `state/control/` as hard boundaries.
- Drift from `docs/STATE.md` — update it (and tests + dashboard consumers) on any schema change.

## Tests
`tests/test_task_*.py`, `tests/test_lifecycle.py`, `tests/test_*control*.py`.
