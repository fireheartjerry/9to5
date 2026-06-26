# Add Memory Backend

Use when adding or changing memory storage.

## Read first

- `CLAUDE.md`
- `docs/MEMORY.md`
- `docs/STATE.md`
- `docs/DANGER_MAP.md`

## Likely files

- `memory/`
- memory tests
- `docs/MEMORY.md`
- `LLM_MAP.md` if ownership changes

## Rules

- Memory stores context, not canonical run state.
- Preserve disk fallback for Obsidian.
- Normal tests should not require live Obsidian.
- Use fake backend for integration tests.

## Verification

Run memory tests, including failure/fallback path.
