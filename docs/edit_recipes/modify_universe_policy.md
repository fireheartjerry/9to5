# Modify Universe Policy

Use when changing allowed paths, expansion behavior, hard boundaries, or self-modification guard rules.

## Read first

- `CLAUDE.md`
- `docs/ARCHITECTURE.md`
- `docs/DANGER_MAP.md`
- `docs/STATE.md`

## Likely files

- guard/path policy code
- elaborator/orchestrator universe extraction
- tests for hard-boundary blocking
- `docs/DANGER_MAP.md`
- `docs/STATE.md`
- `docs/ARCHITECTURE.md`

## Rules

- `allowed_paths` are precision hints, not hard allowlists.
- `hard_boundaries` are actual forbidden paths.
- Never weaken protection for secrets, VCS internals, virtualenvs, or runtime state accidentally.
- Add tests for both allowed expansion and blocked hard-boundary edit.

## Verification

Run hard-boundary guard tests and universe extraction tests.
