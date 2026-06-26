# Add Browser Executor Capability

Use when adding Playwright/CDP/browser automation.

## Read first

- `CLAUDE.md`
- `docs/ARCHITECTURE.md`
- `docs/DANGER_MAP.md`
- `docs/TESTING.md`

## Likely files

- browser driver/executor files if present
- integration tests with fake browser backend
- `docs/ARCHITECTURE.md`
- `LLM_MAP.md`

## Rules

- Browser executor is an interchangeable capability, not the orchestrator.
- Keep live browser tests separate from fast tests.
- Attach screenshots/artifacts when useful.
- Do not depend on brittle UI flows for core tight loops unless explicitly required.

## Verification

Run fake browser tests. Run live browser check only when needed and report if skipped.
