# test-coverage-triage

Find what isn't tested before production finds it. Prioritize by risk, not line count.

## What it does

Given a module or set of changed files, this skill maps all execution paths (happy, edge, error),
cross-references existing tests, and produces a prioritized list of gaps — HIGH/MED/LOW — with
concrete test names and the reason each matters. Highest blast-radius gaps come first.

## How to invoke

```
/test-coverage-triage
find coverage gaps
what should I test next
```

Triggers: before a PR on core logic, after a bug escaped tests, when adding a new module.

## Output format

```
COVERAGE TRIAGE REPORT
======================
Scope: <files>

HIGH-risk gaps (write these first):
  [ ] test_<module>_<function>_<path> — <why it matters>

MED-risk gaps:
  [ ] test_<module>_<function>_<path>

LOW-risk gaps (optional):
  [ ] ...

Already covered:
  - <function>: happy path, error path
```

## Example

```
COVERAGE TRIAGE REPORT
Scope: agents/verifier.py

HIGH-risk gaps:
  [ ] test_verifier_verify_step_exit_nonzero_marks_fail
        — gate before retry; wrong result = infinite retry loop
  [ ] test_verifier_verify_step_missing_key_raises
        — KeyError propagates uncaught to orchestrator

MED-risk gaps:
  [ ] test_verifier_verify_step_empty_stdout_exit_zero_passes
        — regression: was previously treated as failure

Already covered:
  - verify_step: happy path (exit 0, stdout present)
```

## File placement rule

Tests must be flat files: `tests/test_<module_name>.py`.

**Never** create `tests/<package>/` subdirectories — they shadow the real package during
`unittest discover` and break every import in the suite.

## Rules

- 100% line coverage with no assertion = theater. Coverage by assertion, not by line.
- PARTIAL coverage is often more dangerous than MISSING — it gives false confidence.
- Do not write LOW-risk tests while HIGH-risk gaps remain.
- Run `pytest tests/test_<module>.py -v` after writing; confirm green before claiming improved.

## See also

- [`../test_coverage_triage.md`](../test_coverage_triage.md) — full LLM-facing protocol
- `../skill_gap_analysis/README.md` — use before writing tests if the testing API is unfamiliar
