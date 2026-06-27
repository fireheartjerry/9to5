# 9TO5 CI Debug

Use this skill when CI is slow, failed, or ambiguous.

1. Identify the lane: fast, slow, smoke/e2e, workflow-only, docs-only, or nightly.
2. Reproduce locally with `python tools/dev.py ci-local` when possible.
3. For slow tests, run `python tools/dev.py slow-report` and inspect top durations.
4. Check for heartbeat output before assuming a run is hung.
5. Fix the narrow failure first, then rerun the smallest lane that proves it.
