---
name: test-coverage-triage
description: >
  Identify and prioritize test coverage gaps in a Python project. Given a module or
  feature, determine which code paths lack tests, classify gaps by risk, and produce
  a concrete list of tests to write — ordered by highest blast radius first.
  Use before a PR, after a refactor, or when a bug escaped existing tests.
---

## Purpose

Find what isn't tested before production finds it. Prioritize by risk, not by line count.

## When to invoke

- Before merging a PR touching core logic
- After a bug escaped existing tests ("how did this slip through?")
- Explicitly: `/test-coverage-triage`, "find coverage gaps", "what should I test next"
- When adding a new module and unsure where to start testing

## Protocol

### Phase 1 — Identify scope

Determine which modules/files are in scope. Default to the files changed in the current task. If broader, list them explicitly.

### Phase 2 — Map code paths

For each in-scope file:

1. List all public functions/methods.
2. For each function, identify distinct execution paths:
   - Happy path (normal input, expected output)
   - Edge cases (empty, zero, None, boundary values)
   - Error paths (exceptions, invalid input, missing deps)
   - Async/concurrent paths if applicable

Use this template per function:
```
fn: <function_name>
  paths:
    - happy: <description>
    - edge:  <description>
    - error: <description>
```

### Phase 3 — Cross-reference existing tests

Search `tests/` for each function name. For each test found, note which path it covers.

Grep pattern: `grep -r "function_name" tests/`

Mark paths as:
- `COVERED` — test exists and exercises this path
- `PARTIAL` — test exists but doesn't assert the critical postcondition
- `MISSING` — no test

### Phase 4 — Classify gaps by risk

Assign each MISSING or PARTIAL path a risk level:

| Risk | Criteria |
|------|---------|
| HIGH | Core business logic; mutation of persistent state; auth/permissions; error recovery |
| MED  | Data transformation; serialization; secondary flows |
| LOW  | Pure formatting; logging; display-only behavior |

### Phase 5 — Produce triage report

```
COVERAGE TRIAGE REPORT
======================
Scope: <files>
Date:  <session>

HIGH-risk gaps (write these first):
  [ ] test_<module>_<function>_<path> — <why it matters>
  ...

MED-risk gaps:
  [ ] test_<module>_<function>_<path> — <why it matters>
  ...

LOW-risk gaps (optional):
  [ ] ...

Already covered (no action needed):
  - <function>: happy path, error path
  ...

Suggested test file: tests/test_<module>.py
```

### Phase 6 — Write the highest-risk tests first

Do not write LOW-risk tests while HIGH-risk gaps remain. One solid high-risk test beats five trivial ones.

Each test must:
- Have a descriptive name: `test_<fn>_<condition>_<expected_outcome>`
- Assert the postcondition, not the implementation internals
- Be deterministic (no time, random, or network dependencies without mocking)
- Live in `tests/test_<module_name>.py` (flat file, never `tests/<module>/`)

## Examples

### Example A — verifier.py has no error-path tests

```
COVERAGE TRIAGE REPORT
Scope: agents/verifier.py

HIGH-risk gaps:
  [ ] test_verifier_verify_step_exit_nonzero_marks_fail
        — verifier is the gate before retry; wrong result = infinite retry loop
  [ ] test_verifier_verify_step_missing_expected_key_raises
        — missing key in result dict causes KeyError uncaught in orchestrator

MED-risk gaps:
  [ ] test_verifier_verify_step_empty_stdout_with_exit_zero_passes
        — regression: was previously treated as failure (see trace replay)

Already covered:
  - verify_step: happy path (exit 0, stdout present)
```

### Example B — new Discord cog, no tests at all

```
COVERAGE TRIAGE REPORT
Scope: notifications/discord_bot.py (new cog)

HIGH-risk gaps:
  [ ] test_discord_bot_on_message_ignores_bots
        — bot-loop prevention; missing = infinite message chain
  [ ] test_discord_bot_command_dispatch_unknown_command_sends_error
        — unhandled command = silent failure visible to user

MED-risk gaps:
  [ ] test_discord_bot_format_run_summary_truncates_long_text
        — Discord 2000-char limit; over-limit = API error
```

## Rules

- Never assess coverage by line % alone. 100% line coverage with no assertion = theater.
- PARTIAL coverage is often more dangerous than MISSING — it gives false confidence.
- File placement rule: `tests/test_<module>.py` flat. Never `tests/<package>/`.
- After writing tests, run `python -m pytest tests/test_<module>.py -v` before claiming coverage improved.
- Use `pytest` not `unittest discover` locally (conftest sandbox isolation).
