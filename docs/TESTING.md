# Testing and Verification

Canonical testing strategy for 9TO5.

Claude Code sessions should run the narrowest useful test first. Do not jump to expensive, live, browser, Discord, or native checks unless the change requires them. Shocking concept: less theater, more signal.

## Test tiers

### Tier 0: sanity checks

Target runtime: under 5 seconds.

Use for syntax/import/config sanity.

Examples:

```bash
python -m compileall .                      # syntax/parse check
python -m pytest -m "not slow" -q           # fast lane (excludes slow/integration)
```

Canonical commands in THIS repo (there is no `scripts/check.py`): the fast inner
loop is `python tools/dev.py check <file>` (lint + typecheck + affected tests +
repo-map drift for one file). Tests live FLAT under `tests/test_*.py` — there are
no `tests/verification/`, `tests/control/`, or `tests/integration/` subdirs.

### Tier 1: focused module tests

Target runtime: under 15 seconds.

Use after changing one module.

Examples:

```bash
python -m pytest tests/test_verify_multi_requirement.py -q
python -m pytest tests/test_control_concurrency.py -q
python -m pytest tests/test_dashboard.py -q
python tools/affected_tests.py $(git diff --name-only)   # auto-pick tests for changed files
```

### Tier 2: integration fake-run tests

Target runtime: under 60 seconds.

Use after changing lifecycle, execution, ControlBus, state, verifier, replanner, dashboards, or agent interfaces.

Examples:

```bash
python -m pytest tests/test_integration_loop.py -q
python -m pytest tests/test_notification_integration.py -q
python -m pytest tests/test_webdash_control.py -q
```

### Tier 3: full suite

Use after focused tests pass or before merging large changes.

```bash
python -m pytest -n auto --dist loadscope -q   # full suite, parallel (CI form)
python tools/dev.py fast                         # fast lane only, parallel
python -m pytest --lf -q                         # re-run only last-failed
python tools/dev.py ci-local                     # local CI-shaped gate
python tools/dev.py slow-report                  # slow lane + heartbeat + duration report
python tools/dev.py context-check                # Claude-facing context budget warning
python tools/dev.py iteration-health             # recent LLM/test-loop health summary
python tools/dev.py bench-iteration --dry-run    # list validated iteration benchmark tasks
python tools/dev.py size-audit                   # file/function line-count budget audit
```

> Run tests via **pytest**, not bare `unittest`: the per-test sandbox (offline Discord/Ollama/
> browser) lives in `tests/conftest.py`, which `unittest` does not load — so bare `unittest` can
> fire real side effects from a live local `.env`.

#### CI lanes (`.github/workflows/tests.yml`)

| Trigger | Jobs |
|---|---|
| Docs-only | repo-map drift check only |
| Workflow-only | workflow validation + workflow registry tests |
| Tooling-only | repo-map/tooling tests |
| Push to `main` with core changes | fast lane, py3.12 |
| PR with core changes | fast lane py3.11+3.12, slow lane py3.12, dry-run smoke, E2E smoke |
| Nightly/manual | exhaustive slow lane + smoke commands |

`concurrency: cancel-in-progress` kills superseded runs; installs use `uv`. Dev/test deps
(`pytest`, `pytest-xdist`, `pytest-timeout`) live in `requirements-dev.txt`.

Long CI pytest jobs enable the first-party heartbeat reporter by default:

```txt
[pytest-progress] elapsed=90s completed=412/2793 failed=0 skipped=1 active=gw0 tests/test_x.py::test_y
```

Controls:

- `NINE_TO_FIVE_TEST_HEARTBEAT_SECONDS=30` changes the interval.
- `NINE_TO_FIVE_TEST_PROGRESS=0` disables heartbeat output.
- Focused local test files stay quiet unless progress is explicitly enabled.

### Tier 4: live/manual/browser/native checks

Only run when required.

Examples:

- Discord live bot checks
- web dashboard click flow
- Playwright/CDP generic browser execution (the `BROWSER_LAYER_ENABLED` surface)
- real Gemini API call (second brain; gated by `NINE_TO_FIVE_ALLOW_REAL_API`)
- UIA/pywinauto native execution
- real Claude Code subprocess smoke
- real Obsidian REST API write

## Preferred test-selection flow

1. Identify changed module.
2. Run focused test for that module.
3. If lifecycle/control/state is affected, run related integration test.
4. If docs/test commands changed, validate docs or command output.
5. Run full suite only after focused tests pass.
6. Report skipped checks honestly.

## Required scenarios to add/maintain

These scenario tests should exist or be introduced over time:

- `test_run_completes_simple_patch`
- `test_failed_verify_retries_with_context`
- `test_adversary_blocks_unverified_success`
- `test_replanner_splits_failed_subtask`
- `test_universe_blocks_forbidden_file_edit`
- `test_discord_state_matches_run_state`
- `test_web_control_pause_resume`
- `test_self_modification_guard_blocks_secrets`
- `test_browser_executor_attaches_artifacts`
- `test_gemini_driver_degrades_to_ollama_when_unavailable`
- `test_learning_consumes_trace_without_mutating_live_run`
- `test_control_bus_pause_resume_cancel`

## Fake backend strategy

Prefer fake backends for integration tests:

- `FakeClaudeExecutor`
- `FakeOllamaBrain`
- `FakeDiscordClient`
- `FakeControlBus`
- `FakeObsidianStore`
- `FakeBrowserExecutor`
- `FakeNativeExecutor`
- `FakeGeminiSession`

Normal fast tests should not require:

- live Discord
- browser sessions
- native UI automation
- real Claude Code CLI
- real Obsidian REST API
- external network access

## Golden trace fixtures

Maintain fixtures under:

```txt
tests/fixtures/traces/
```

Recommended fixtures:

- `simple_success.json`
- `verifier_failure_then_retry.json`
- `adversary_rejects_fake_success.json`
- `universe_boundary_violation.json`
- `paused_then_resumed.json`
- `browser_ui_repair.json`
- `self_modification_guard_blocks_secret.json`
- `replanner_splits_failed_subtask.json`
- `discord_state_matches_run_state.json`

Golden traces should make behavior concrete across refactors.

## Failure message quality

Failures should point the next LLM edit to the cause.

Bad:

```txt
Verification failed.
```

Good:

```txt
Verification failed for step step_042.
Expected: stdout contains "3 passed"
Command: pytest tests/test_verify_multi_requirement.py -q
Exit code: 1
Suggested files:
- agents/verifier.py
- tests/test_verify_multi_requirement.py
```

## Final verification reporting

Always report:

- exact commands run
- pass/fail result
- skipped tests and why
- live checks skipped and why
- remaining risk
