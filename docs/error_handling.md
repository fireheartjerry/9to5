# Error handling

The former retry stack — `platform_core/runtime/error_handling.py`
(`retryTask`), `retry_policy.py` (`RetryPolicy`), and the
`enhanced_error_handling.py` re-export — was deleted: it had zero production
callers. Failure recovery in 9TO5 is owned by
`platform_core.runtime.resilience.run_with_recovery(run_fn, state)`, which
auto-resumes a crashed run from committed state with exponential backoff and a
bounded restart budget (`RUN_MAX_RESTARTS`). Per-subtask retries are governed
by `MAX_SUBTASK_ATTEMPTS` inside the orchestrator loop. See
`tests/test_resilience.py` for the behavioural contract.
