---
name: systematic-debugging
description: >
  Structured bug diagnosis protocol. When a bug survives one fix attempt, switch to
  this instead of guessing. Forces hypothesis-driven investigation: one variable at a
  time, falsifiable claims, smallest reproducible case, root cause before patch.
  Use when: first fix failed, bug is intermittent, error message is misleading,
  or you don't understand why something works differently than expected.
---

## Core principle

A bug is a falsifiable claim about system behavior. Test one hypothesis at a time.
Never patch what you don't understand.

## When to invoke

- First fix attempt failed or made things worse
- Bug is intermittent / flaky
- Error message points at symptoms, not cause
- "It should work but it doesn't" — no clear mental model
- Explicitly: `/systematic-debugging`, "debug this properly", "why is this failing"

## Protocol

### Phase 0 — Stop guessing

If you've already tried a fix that didn't work: **undo it** before continuing. A failed
patch in the codebase contaminates subsequent investigation.

State what you know and don't know:
```
Known:    <observable facts from error output, logs, test results>
Unknown:  <what you're not sure about>
Assumed:  <things you believe but haven't verified>
```

### Phase 1 — Reproduce minimally

The smaller the reproduction case, the faster the diagnosis.

1. Identify the **smallest input** that triggers the bug.
2. Confirm the bug is **deterministic** (or characterize its non-determinism).
3. State the exact failure: `expected <X>, got <Y>`.

If you can't reproduce it at all: use `trace-replay` skill instead.

Minimal repro template:
```python
# Minimal repro for: <bug description>
# Expected: <X>
# Actual:   <Y>

<minimal setup code>
result = <the call that fails>
assert result == <expected>  # fails here
```

### Phase 2 — Bisect the causal chain

List every component the code path passes through (in order):

```
input → [A] → [B] → [C] → output
```

For each component, ask: "Could this component be the cause?"
Eliminate components where you can verify correct output.

The bug lives at the first component where output diverges from expected.

### Phase 3 — Form falsifiable hypotheses

For each remaining candidate component, write a hypothesis:

```
H1: [Component B] transforms X incorrectly when input is empty string.
    Test: call B directly with empty string, observe output.
    Falsified if: B returns the correct value.
    Confirmed if: B returns the wrong value.
```

Only one hypothesis active at a time. Test it. Move on.

### Phase 4 — Instrument, don't assume

Add the minimum logging/print needed to observe the variable in question.
Read the actual value. Do not trust what you think it should be.

```python
# Temporary instrumentation (remove after bug found)
print(f"DEBUG B input:  {repr(input_val)}")
print(f"DEBUG B output: {repr(output_val)}")
```

Key instrumentation targets:
- Function inputs (are they what you think?)
- Intermediate values at component boundaries
- Exception `__cause__` and `__context__` (not just the message)
- Async task results (are they awaited correctly?)

### Phase 5 — Confirm the root cause

Before patching, state the root cause in one sentence:

```
ROOT CAUSE: <component> <does wrong thing> because <specific reason> when <condition>.
```

If you can't write this sentence, you haven't found the root cause yet.

Validate: can you predict the bug behavior from the root cause alone? If not, dig deeper.

### Phase 6 — Patch minimally

Patch only the root cause. Do not "improve" adjacent code.

After patching:
1. Re-run the minimal reproduction — confirm it passes.
2. Run the focused module test suite.
3. Run the full suite.
4. Remove all instrumentation (print/debug statements).

### Phase 7 — Post-mortem (brief)

For bugs that took more than one attempt or were non-obvious:

```
BUG POST-MORTEM
===============
Root cause:     <one sentence>
Misleading clue: <what sent you in the wrong direction initially>
Detection gap:  <what test would have caught this earlier>
Fix:            <file:line — what changed>
```

## Common traps

| Trap | Antidote |
|------|---------|
| Fixing symptoms not cause | Write root cause sentence before patching |
| Testing the fix, not the behavior | Assert the postcondition, not that the line changed |
| Trusting the error message location | Error fires at detection, not at cause |
| Patching without reproducing first | Always reproduce → confirm → patch → reconfirm |
| Multiple changes at once | One change at a time; each is a hypothesis test |
| Assuming async is fine | Always verify async results are awaited; check event loops |
| Blaming the framework | Framework bugs are rare. Your usage of it is common. Verify assumptions first. |

## Example walkthrough

**Bug:** `orchestrator.py` crashes with `KeyError: 'result'` on second retry.

```
Known:   KeyError on key 'result' in retry path; first attempt succeeds
Unknown: what populates 'result' in the retry dict
Assumed: retry dict has same shape as first attempt dict (UNVERIFIED)

Causal chain:
  plan → executor → [result_dict] → verifier → replan → [retry_dict] → executor

H1: retry_dict is missing 'result' key — differs from first-attempt dict shape.
Test: log retry_dict keys at retry entry point.
Result: retry_dict has keys ['step_id', 'error'] — no 'result' key (confirmed H1)

Root cause: replan() constructs retry dict from error record, which omits 'result'.
            executor assumes 'result' always present — no default.
Patch: executor.py — use dict.get('result', None) and handle None case.
```

## Integration with other skills

- If you have logs from a prior run: use `trace-replay` first to get the causal chain, then use this protocol from Phase 3.
- If the bug escaped tests: after fixing, use `test-coverage-triage` to identify which test would have caught it.
- If multiple components are uncertain: use `skill-gap-analysis` to identify where you need to read docs before Phase 3.
