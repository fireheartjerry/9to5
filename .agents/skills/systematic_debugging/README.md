# systematic-debugging

Hypothesis-driven bug diagnosis. One variable at a time. Root cause before patch.

## What it does

When a bug survives one fix attempt, this skill replaces guessing with a structured protocol:
undo the failed patch, reproduce minimally, bisect the causal chain, test one hypothesis at a
time, confirm root cause in one sentence, then patch minimally. Includes a post-mortem template
for non-obvious bugs.

## How to invoke

```
/systematic-debugging
debug this properly
why is this failing
```

CLAUDE.md rule: **when a bug survives one fix attempt, switch to this skill instead of guessing.**

## Protocol summary

```
Phase 0: Undo failed patch. State known/unknown/assumed.
Phase 1: Reproduce minimally. Confirm determinism. State exact failure.
Phase 2: Map causal chain: input → [A] → [B] → [C] → output
Phase 3: Form falsifiable hypothesis per component.
Phase 4: Instrument (log actual values). Don't assume.
Phase 5: Confirm root cause: "<component> does <X> because <Y> when <Z>."
Phase 6: Patch minimally. Remove instrumentation. Re-run full suite.
Phase 7: Post-mortem if non-obvious.
```

## Common traps

| Trap | Antidote |
|------|---------|
| Fixing symptoms | Write root cause sentence before patching |
| Multiple changes at once | One change = one hypothesis test |
| Trusting error location | Error fires at detection, not at cause |
| Assuming async is fine | Verify results are awaited; check event loops |
| Blaming the framework | Your usage is far more likely wrong |

## Example

```
Bug: KeyError 'result' on second retry in orchestrator

Known:   first attempt succeeds; error on retry path
Assumed: retry dict same shape as first attempt dict (UNVERIFIED)

Causal chain: plan → executor → [result_dict] → verifier → replan → [retry_dict] → executor

H1: retry_dict missing 'result' key (shape differs from first attempt)
Test: log retry_dict.keys() at entry point
Result: keys = ['step_id', 'error'] — 'result' absent → H1 confirmed

Root cause: replan() builds retry dict from error record; omits 'result'.
            executor assumes key always present.

Patch: executor.py — dict.get('result', None) + None handling
```

## Integration with other skills

- Have logs from prior run? → `trace-replay` first, then Phase 3 of this skill.
- Bug escaped tests? → `test-coverage-triage` after fixing to add regression test.
- Uncertain about a component's API? → `skill-gap-analysis` before Phase 3.

## See also

- [`../systematic_debugging.md`](../systematic_debugging.md) — full LLM-facing protocol
- `../trace_replay/README.md` — use instead of Phase 1 when live repro is impossible
