# Custom Skills and Hooks

Recommendations for custom hooks, scripts, and skills that make 9TO5 safer and faster for LLM iteration.

These are not all mandatory on day one. Add them incrementally when useful. Because apparently asking every subprocess to remember every invariant forever is not a stable engineering strategy.

> **Hook registration is live and CI-guarded.** The Claude executor passes
> `--settings <repo>/.claude/settings.json`, whose `hooks.PreToolUse` block registers
> `block_destructive` and `self_modification_guard` (Bash) and `self_modification_guard`
> (Edit/Write/MultiEdit), plus `PostToolUse` telemetry. A prior commit had stripped this to
> `"hooks": {}`, silently disabling every guard; `tests/test_hooks_registration.py` now asserts
> that the registrations in `settings.json` and the handlers in `agents/hooks.py` stay in parity,
> so a future strip fails CI. Blocking guards fail **closed**: if a guard sub-module can't be
> imported, the dispatch exits non-zero (blocks the tool call) rather than allowing it.

## Recommended hooks

### 1. Pre-edit hard-boundary guard

Purpose:

- block edits to secrets, `.env`, `.git/`, virtualenvs, caches, and runtime state unless explicitly authorized
- enforce `meta.universe.hard_boundaries`

Status:

- already conceptually part of self-modification guard
- should remain strict

Should block:

```txt
.env
.git/
venv/
.venv/
__pycache__/
state/tasks/ unless explicitly authorized
state/control/ unless explicitly authorized
logs/
cache/
runs/
```

### 2. Documentation drift check

Purpose:

- detect when code changes likely require Markdown updates

Trigger on edits to:

```txt
agents/
orchestrator.py
main.py
platform_core/runtime/control.py
state/
memory/
notifications/
config.py
tests/
```

Expected behavior:

- warn if no relevant docs changed
- do not always block
- block only for high-risk docs-required changes if configured

Suggested implementation:

```txt
scripts/check_docs_drift.py
```

It can map changed files to required docs using `docs/DOC_MAINTENANCE.md`.

### 3. Focused test suggestion hook

Purpose:

- after edits, suggest the narrowest relevant test command

Suggested script:

```txt
scripts/suggest_tests.py
```

Examples:

Note: this already exists as `python tools/affected_tests.py <files>` (and
`python tools/dev.py check <file>`). Tests are flat under `tests/test_*.py`:

| Changed file | Suggested command |
|---|---|
| `agents/verifier.py` | `python -m pytest tests/test_verify_multi_requirement.py tests/test_verify_shell_safety.py -q` |
| `platform_core/runtime/control.py` | `python -m pytest tests/test_control_concurrency.py -q` |
| `notifications/dashboard.py` | `python -m pytest tests/test_dashboard.py -q` |
| `memory/obsidian.py` | `python -m pytest tests/test_memory_subtask_manager.py -q` |

### 4. Repo health command

Purpose:

- give fresh Terminal A / Executor subprocesses a compact repo status

Suggested command:

```bash
python scripts/repo_health.py
```

Should print:

- Python version
- current branch/dirty status if safe
- test count if discoverable
- known failing tests
- important config files
- recent trace count
- optional services available/unavailable
- suggested next commands

### 5. JSON/schema validation hook

Purpose:

- validate task JSON, control JSON, config YAML/JSON, and golden trace fixtures

Suggested command:

```bash
python scripts/validate_schemas.py
```

Use when editing:

- `state/`
- `config/`
- `tests/fixtures/traces/`
- ControlBus state shape

### 6. No-generated-edit guard

Purpose:

- warn if patch edits generated/runtime artifacts

Paths:

```txt
logs/
runs/
cache/
.tmp/
generated/
vault/
state/tasks/
state/control/
```

Should allow edits to fixtures/examples explicitly under `tests/fixtures/`.

## Recommended custom Claude slash commands

If Claude Code supports custom commands in your setup, consider adding:

### `/repo-health`

Runs:

```bash
python scripts/repo_health.py
```

### `/docs-check`

Runs:

```bash
python scripts/check_docs_drift.py
```

### `/test-suggest`

Runs:

```bash
python scripts/suggest_tests.py --changed
```

### `/trace-summary`

Summarizes latest run trace:

```bash
python scripts/trace_summary.py --latest
```

### `/danger`

Prints relevant danger map section for changed files.

## Recommended custom skills

Custom skills are useful only if they reduce repeated reasoning. Do not create ceremonial skills that nobody uses.

Implemented local skills:

| Skill | Purpose |
|---|---|
| `9to5-fast-fix` | Smallest safe edit + focused validation loop |
| `9to5-ci-debug` | CI lane triage, heartbeat checks, and slow-report workflow |
| `9to5-doc-sync` | Keep docs, repo-map, rules, and skills synchronized |
| `9to5-iteration-bench` | Run and interpret validated iteration-speed benchmarks |

Recommended:

### 1. 9TO5 Docs Maintainer

Reads changed files, updates appropriate docs, checks contradictions.

Inputs:

- changed file list
- short behavior summary
- docs map

Outputs:

- docs updated
- docs checked but unchanged
- potential stale docs

### 2. 9TO5 Test Selector

Maps changed files to focused test commands.

Inputs:

- changed file list
- test tree

Outputs:

- Tier 0/1/2 recommended commands
- live checks needed or not

### 3. 9TO5 Trace Analyst

Reads latest run logs/traces and explains:

- what happened
- where it failed
- which subsystem owns the failure
- next likely files to inspect

### 4. 9TO5 Danger Reviewer

Reviews patches touching high-risk files.

Checks:

- source-of-truth violations
- guard weakening
- lifecycle/status drift
- dashboard state mutation
- state schema changes without docs/tests
- learning subsystem bypasses

### 5. Nightclaw Surface Reviewer

For Discord/web dashboard changes.

Checks:

- embed size limits
- field clamping
- command routing
- ControlBus consistency
- dashboard derived-state rule
- owner/auth behavior

## What not to automate yet

Avoid building heavy hooks that slow every edit.

Do not add:

- expensive live Discord checks on every patch
- browser automation on every patch
- full test suite on every save
- automatic state migrations without review
- live learning/adapter promotion without eval gates

## Hook acceptance criteria

Implemented telemetry hooks must stay best-effort:

- malformed stdin exits 0
- logging failures exit 0
- safety guards still exit 2 only for intentional blocks
- status-line rendering works outside Claude Code
- metrics are written only under ignored `logs/claude_metrics/`

A hook is worth keeping if it:

- catches real mistakes
- produces short actionable output
- does not block low-risk edits unnecessarily
- can be bypassed explicitly when needed
- is documented in this file and `CLAUDE.md`

If a hook becomes noisy, it will be ignored. This is one of the few things humans and agents agree on.
