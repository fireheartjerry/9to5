# Add Native Executor Capability

Use when adding UIA/pywinauto/native desktop automation.

## Read first

- `CLAUDE.md`
- `docs/ARCHITECTURE.md`
- `docs/DANGER_MAP.md`
- `docs/TESTING.md`

## Likely files

- native driver/executor files if present
- integration tests with fake native backend
- `docs/ARCHITECTURE.md`
- `LLM_MAP.md`

## Rules

- Native executor is replaceable capability, not canonical state.
- Keep native UI tests separate from fast tests.
- Avoid hidden global desktop state where possible.
- Log enough context to debug failures.

## Verification

Run fake native tests. Run live native check only when needed and report if skipped.
