# Modify Lifecycle State

Use when adding, removing, or renaming run/subtask statuses.

## Read first

- `CLAUDE.md`
- `docs/ARCHITECTURE.md`
- `docs/STATE.md`
- `docs/NIGHTCLAW.md`
- `docs/DANGER_MAP.md`

## Likely files

- `lifecycle.py` — **the canonical `RunStatus`/`SubtaskStatus` source; edit here FIRST**
- `tests/test_lifecycle.py` — update the enum/terminal/normalize tests
- `state/task.py` (esp. `_TERMINAL`)
- `main.py`
- `orchestrator.py`
- `control.py`
- dashboard consumers
- `docs/STATE.md`
- `docs/ARCHITECTURE.md`
- `LLM_MAP.md`

## Rules

- Use one canonical vocabulary (`lifecycle.py`); the enum value must equal the on-disk string.
- Update every consumer.
- Add migration/backward compatibility notes if old task files may exist.
- Do not rename statuses casually.

## Verification

Run state tests, lifecycle tests, dashboard display tests, and integration fake-run.
