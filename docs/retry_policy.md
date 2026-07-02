# Retry policy

`platform_core/runtime/retry_policy.py` (`RetryPolicy`) was deleted along with
the rest of the unused retry stack — nothing in production imported it. The
live recovery mechanism is
`platform_core.runtime.resilience.run_with_recovery(run_fn, state)` (run-level
auto-resume with exponential backoff) plus `MAX_SUBTASK_ATTEMPTS` for
per-subtask retry budgets. See `docs/error_handling.md`.
