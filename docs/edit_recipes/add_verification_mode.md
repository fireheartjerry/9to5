# Add Verification Mode

Use when adding or changing verifier expectation behavior.

## Read first

- `CLAUDE.md`
- `docs/TESTING.md`
- `docs/ARCHITECTURE.md`
- `docs/DANGER_MAP.md`

## Likely files

- `agents/verifier.py`
- verifier tests
- `docs/TESTING.md`
- `docs/ARCHITECTURE.md` if semantics change

## Do not touch

- dashboard code unless display changes
- ControlBus unless control state changes
- lifecycle statuses unless pass/fail semantics require it

## Required behavior

A subtask is done only if verification passes.

Failure output must preserve:

- command
- expectation
- stdout/stderr
- exit code
- likely next action where possible

## Verification

Run verifier unit tests and at least one failure-path test.
