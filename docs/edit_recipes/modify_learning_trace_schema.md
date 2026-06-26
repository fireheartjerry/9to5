# Modify Learning Trace Schema

Use when changing learning traces, failure taxonomy, adapter promotion, eval generation, or self-improvement records.

## Read first

- `CLAUDE.md`
- `docs/ARCHITECTURE.md`
- `docs/DANGER_MAP.md`
- `docs/CUSTOM_SKILLS_AND_HOOKS.md`

## Likely files

- learning modules if present
- trace schema/tests
- golden trace fixtures
- `docs/ARCHITECTURE.md`
- `docs/DANGER_MAP.md`
- `docs/TESTING.md`

## Rules

- Learning consumes traces and proposes improvements.
- Learning must not bypass verifier, adversary, guards, or configured human gates.
- Adapter promotion requires eval gates.
- Trace schema changes require fixture updates.

## Verification

Run learning tests, trace schema validation, and fixture tests.
