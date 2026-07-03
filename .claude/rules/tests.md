# 9TO5 Test Rules

- Prefer `python tools/dev.py check <file>` for focused edits.
- Use `python tools/dev.py fast` before handing off broad Python changes.
- `tests/` is organized by domain, not flat: `tests/evolution/`, `tests/execution/`,
  `tests/orchestration/`, `tests/control/`, `tests/notifications/`, `tests/workflows/`,
  `tests/platform/` hold fast-lane tests; `tests/conftest.py`, `tests/factories.py`, and
  `tests/progress_reporter.py` stay at the `tests/` root.
- Slow is directory-based: anything under `tests/slow/` is auto-marked `@pytest.mark.slow`.
  To make a test slow, put it in `tests/slow/` — there is no filename-substring mechanism.
- Slow/full runs should keep pytest progress enabled with `NINE_TO_FIVE_TEST_PROGRESS=1`.
- For slow profiling, use `python tools/dev.py slow-report`; it writes `logs/slow-test-report.md`.
- Keep exhaustive fuzz/e2e work in nightly or manual lanes unless the changed code needs that boundary.
