# `memory/` — durable context, not run state

Persistent human-readable context + the structured experience ledger. Index: `memory/AGENTS.md`.

## What lives here
- **`obsidian.py`** — notes via the Local REST API (`https://127.0.0.1:27124`, `verify=False`),
  with an automatic **disk-write fallback** under `vault/9to5/`. See `docs/MEMORY.md`.
- **`experience.py`** — the SQLite experience ledger (`state/experience.db`): runs/subtasks/
  eval rows, embeddings, gold examples. Best-effort — never raises into a run.

## Must NOT
- Become canonical **run** state — that is `state/task.py`. Memory is durable context/lessons.
- Lose the Obsidian disk-fallback: writes must survive a closed/locked vault (401) or REST outage.

## Tests
`tests/test_obsidian*.py`, `tests/test_experience_ledger.py`, `tests/test_memory_subtask_manager.py`, …
