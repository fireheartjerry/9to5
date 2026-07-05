# Testing and Verification

Canonical testing strategy for 9TO5.

Claude Code sessions should run the narrowest useful test first. Do not jump to expensive, live, browser, Discord, or native checks unless the change requires them. Shocking concept: less theater, more signal.

## Test tiers

### Tier 0: sanity checks

Target runtime: under 5 seconds.

Use for syntax/import/config sanity.

Examples:

```bash
python -m compileall -q tests               # tests must parse (CI runs this before pytest)
python -m compileall .                      # syntax/parse check
python -m pytest -m "not slow" -q           # fast lane (excludes slow/integration)
```

Canonical commands in THIS repo (there is no `scripts/check.py`): the fast inner
loop is `python tools/dev.py check <file>` (lint + typecheck + affected tests +
repo-map drift for one file). Tests live under domain subdirectories, not flat:
`tests/evolution/`, `tests/execution/`, `tests/orchestration/`, `tests/control/`,
`tests/notifications/`, `tests/workflows/`, `tests/platform/`, `tests/introspect/`,
`tests/refactor/`, `tests/explore/` hold the fast-lane
tests by domain, and `tests/slow/` holds heavyweight subprocess/e2e/integration/fuzz/
simulation tests (see "Slow lane is directory-based" below). `tests/conftest.py`,
`tests/factories.py`, and `tests/progress_reporter.py` stay at the `tests/` root.
`tools/repo_map.py::find_tests` and `tools/affected_tests.py` resolve tests
recursively, so module→test mapping works across all subdirectories.

Test files never carry `@AI-MAP` headers: `tools/repo_map.py` neither indexes nor
header-splices `tests/` (a bad splice there corrupted the suite — 2026-07 incident).

### Tier 1: focused module tests

Target runtime: under 15 seconds.

Use after changing one module.

Examples:

```bash
python -m pytest tests/execution/test_verifier.py -q
python -m pytest tests/control/test_control_concurrency.py -q
python -m pytest tests/notifications/test_dashboard.py -q
python tools/affected_tests.py $(git diff --name-only)   # auto-pick tests for changed files
```

#### PR feedback learning loop

```bash
# Core PR capture + ledger write (mocked gh CLI)
python -m pytest tests/slow/test_learning_loop.py -v

# experience_pr SQLite round-trip (record/fetch/upsert/filter)
python -m pytest tests/evolution/test_experience_pr.py -v

# SIE pr_consolidate: failure-mode + lesson emission
python -m pytest tests/evolution/test_sie.py -v

# Adaptive curriculum trigger (>=5 new feedback records)
python -m pytest tests/evolution/test_curriculum.py -v

# Discord feedback embed + FeedbackView buttons
python -m pytest tests/notifications/test_feedback_flow.py -v

# Run all PR-feedback focused tests together
python -m pytest tests/slow/test_learning_loop.py tests/evolution/test_experience_pr.py \
    tests/evolution/test_sie.py tests/evolution/test_curriculum.py \
    tests/notifications/test_feedback_flow.py -v
```

These tests use temp SQLite databases and a mocked `gh` CLI — no live GitHub access required.

### Tier 2: integration fake-run tests

Target runtime: under 60 seconds.

Use after changing lifecycle, execution, ControlBus, state, verifier, replanner, dashboards, or agent interfaces.

**Slow lane is directory-based, not filename-based.** `tests/conftest.py::pytest_collection_modifyitems`
auto-marks every test collected from under `tests/slow/` with `@pytest.mark.slow` plus a
300s timeout. There is no filename-substring matching anymore (the old `_SLOW_PATTERNS`
mechanism is gone). **To make a test slow, put it in `tests/slow/`** — marking a test
`@pytest.mark.slow` by hand outside that directory has no special CI effect beyond the
marker itself.

Examples:

```bash
python -m pytest tests/slow/test_integration_loop.py -q
python -m pytest tests/notifications/ -q
python -m pytest tests/control/test_webdash_control.py -q
```

**Epic-flag isolation:** use the `pin_flags` factory fixture (`tests/conftest.py`) instead of
hand-rolling `monkeypatch.setattr(config, "FLAG", value, raising=False)` per flag — e.g.
`pin_flags(SOCIETY_ENABLED=True, WORKTREE_ISOLATION_ENABLED=True)`. It isolates a test from the
live `.env` the same way, just without the boilerplate.

**Combined-flags smoke test:** `tests/slow/test_epic_flags_combined.py` turns SEVERAL epic flags on
TOGETHER (Society, Worktree Isolation, Solution Fork, Semantic Safety, Cost Budget, Compaction,
Execution Fabric) against a real `BuilderBrain` run — every other epic test exercises flags in
isolation, never in combination, so this is the only place cross-epic interaction bugs surface.
Run it after changing any epic-flagged code path:

```bash
python -m pytest tests/slow/test_epic_flags_combined.py -q
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
python tools/dev.py swallow-ratchet              # bare except-swallow count vs baseline (only goes DOWN)
```

> The suite is **pytest-only**. Never run bare `unittest`: the per-test sandbox (offline
> Discord/Ollama/browser/tunnel) lives in `tests/conftest.py`, which `unittest` does not load — so
> bare `unittest` can fire real side effects from a live local `.env`. This footgun is
> enforced: `python tools/dev.py ci-local` includes a **no-unittest-main gate** (no test
> file may carry a `unittest.main()` runner block), plus `compileall -q tests` and the
> **swallow-ratchet** gate (`tools/swallow_baseline.json` — bare `except Exception: pass`
> count may only decrease; lower it with `--update`).

**Hermetic install root.** The root `conftest.py` pins `INSTALL_ROOT` to the current
checkout for every pytest process (before any `import config`). Without it,
`loadEnvOnce()` loads the shared install's `C:\9to5\.env` — live production credentials
and feature flags — into local test runs while CI runs with stock defaults, which is how
"green locally, red on CI" divergence used to happen. Non-pytest harnesses stay hermetic
by their own means: `testing/e2e.py` forces sim-safe knobs (`_FORCED`, incl.
`GEMINI_ENABLED=False`, `DUAL_LEDGER_PLANNER_ENABLED=False`) and `main.py --dry-run`
uses the simulation doubles.

#### CI lanes (`.github/workflows/tests.yml`)

| Trigger | Jobs |
|---|---|
| Docs-only | repo-map drift check only |
| Workflow-only | workflow validation + workflow registry tests |
| Tooling-only | repo-map/tooling/dev-command tests |
| PR with core changes | `classify` job runs `tools/ci_affected.py`; fast lane (py3.12) runs **affected tests only** when safe, else falls back to the full `-m "not slow"` fast lane — no slow lane, no smokes |
| Push to `main` with core changes | fast lane (py3.12, full `-m "not slow"`), slow lane, dry-run smoke, E2E smoke — all run **in parallel**, none gated on `fast` |
| Nightly/manual | `exhaustive` (full slow lane, `NINE_TO_FIVE_FUZZ_SEEDS=150`) + `nightly-fast-py311` (fast lane on Python 3.11) + smoke commands |

**PR lane is affected-tests-only, fail-closed.** The `classify` job (`tools/ci_affected.py`)
maps the PR's changed files to the tests that cover them and runs only those, WITHOUT the
`-m "not slow"` filter — so a slow test covering changed code still runs on its own PR. It
falls back to the full fast lane (`-m "not slow" -n auto --dist loadscope`) whenever ANY of
these hold:

- more than 25 changed files
- any non-`.py` file changed
- any deleted or renamed file
- a sensitive file changed: `tests/conftest.py`, any `*/conftest.py` at any depth,
  `pytest.ini`, `config.py`, `tests/factories.py`, `tests/progress_reporter.py`,
  `tools/repo_map.py`, `tools/affected_tests.py`, `tools/ci_affected.py`,
  `.github/workflows/*`, or `requirements*`
- any changed non-test `.py` file that maps to zero tests

Classification of the docs/workflow/tooling/core split **also fails closed** independently:
a change set that mixes "excluded" categories (e.g. docs + tools) or whose diff base is
unverifiable (force-push) runs the full core lanes rather than silently skipping everything.
Every job carries a `timeout-minutes` cap.

**PR fast lane is Python 3.12 only.** The 3.11 compatibility leg was dropped from PRs and
moved to nightly as `nightly-fast-py311`.

The fast job runs `python -m compileall -q tests` BEFORE pytest so corrupt test
files fail in seconds, not at collection.

`concurrency: cancel-in-progress` applies to PR runs only — a push to `main` no longer
cancels the in-flight nightly exhaustive run. Installs use `uv`. Dev/test deps
(`pytest`, `pytest-xdist`, `pytest-timeout`, `pyyaml`) live in `requirements-dev.txt`.

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

#### Nightclaw offline replay (substitutes a second live gateway)

Only one `DISCORD_BOT_TOKEN` exists, so a second live bot cannot be started to exercise the
`!` control surface. `platform_core/simulator/bot_replay.py` is the safe offline substitute:
it feeds synthetic gateway messages through the pure command spine
(`notifications/commands.py`) against an in-memory `ControlBus`, mirroring BOTH real consumers
of a Discord message (the gateway `on_message` path and the in-run REST poller). The token is
blank so the REST chokepoint (`notifications/discord_client._request`) short-circuits to a
no-op — nothing touches the network. Use it instead of spinning up a second gateway.

```bash
python -m pytest tests/notifications/test_bot_replay.py -q
```

The matrix covers: every registered `!` command, malformed/unicode-garbage args, unauthorized
and bot-author senders, duplicate/dedup, cursor-based stale replay, pause/resume/abort races,
oversized reply/embed clamping, dual-consumer double-apply, the REST 429→401 breaker/latch, and
the watchdog stale path.

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
Command: pytest tests/execution/test_verifier.py -q
Exit code: 1
Suggested files:
- agents/verifier.py
- tests/execution/test_verifier.py
```

## Final verification reporting

Always report:

- exact commands run
- pass/fail result
- skipped tests and why
- live checks skipped and why
- remaining risk
