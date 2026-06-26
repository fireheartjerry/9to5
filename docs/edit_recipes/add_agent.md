# Add Agent

Use when adding a new agent role.

## Read first

- `CLAUDE.md`
- `LLM_MAP.md`
- `docs/ARCHITECTURE.md`
- `docs/DANGER_MAP.md`

## Likely files

- `agents/<new_agent>.py`
- `agents/__init__.py`
- `orchestrator.py` or `main.py` if wired into lifecycle
- tests for the agent
- `docs/ARCHITECTURE.md`
- `LLM_MAP.md`

## Rules

- Define clear input/output contracts.
- Do not let the agent mutate canonical state unless explicitly responsible.
- Add fake backend/test doubles if the agent calls external systems.
- Avoid making the new agent part of the live loop until it has a testable boundary.

## Verification

Run focused agent tests, then relevant integration fake-run tests.
