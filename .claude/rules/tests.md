# 9TO5 Test Rules

- Prefer `python tools/dev.py check <file>` for focused edits.
- Use `python tools/dev.py fast` before handing off broad Python changes.
- Slow/full runs should keep pytest progress enabled with `NINE_TO_FIVE_TEST_PROGRESS=1`.
- For slow profiling, use `python tools/dev.py slow-report`; it writes `logs/slow-test-report.md`.
- Keep exhaustive fuzz/e2e work in nightly or manual lanes unless the changed code needs that boundary.
