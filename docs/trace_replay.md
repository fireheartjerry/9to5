# Trace Replay

**Location:** `.claude/skills/trace_replay.md`  
**Companion README:** `.claude/skills/trace_replay/README.md`  
**CLI tool:** `agents/trace-replay.py`

---

## What it does

The `trace-replay` subagent loads archived 9TO5 execution traces (JSONL event logs) and
replays them step-by-step to surface divergence points — the exact moment where the
orchestrator deviated from the expected happy path.

It classifies each event as `FAIL`, `REPLAN`, `CHALLENGE`, `PASS`, or `INFO`, identifies
the earliest DIVERGENCE, flags high-activity subtasks (possible retry storms), detects
concurrent parallel execution moments, and emits a structured replay report.

**Core insight:** a recorded trace encodes the full causal chain. Reading it backward from
the first divergence is faster and more precise than guessing or re-running live.

---

## When to invoke

| Trigger | Example |
|---------|---------|
| Bug reproduced in CI/prod but not locally reproducible | flaky test left a trace but won't repro on demand |
| 9TO5 run failed and you have `logs/runs/<run_id>.jsonl` | orchestrator aborted at an unknown step |
| Explicit invocation | `/trace-replay`, "replay this trace", "analyze this log" |
| Verifier spuriously failed on a prior run | empty stdout marked as failure |
| Multi-subtask run had unexpected replanning | want to know which subtask triggered the replan |

---

## CLI reference

All flags for `agents/trace-replay.py`:

```sh
# replay the most recent run (auto-detected)
python agents/trace-replay.py

# replay a specific run by ID
python agents/trace-replay.py --run-id <RUN_ID>

# limit how many recent runs are scanned when --run-id is omitted
python agents/trace-replay.py --limit 10

# print calibrated high-activity threshold and exit without replaying
python agents/trace-replay.py --calibrate

# validate internal logic against synthetic fixtures (no trace needed)
python agents/trace-replay.py --self-test

# print ASCII bar chart of per-subtask event distribution
python agents/trace-replay.py --chart

# emit machine-readable JSON report (suitable for CI pipelines)
python agents/trace-replay.py --format json

# disable ANSI colour output
python agents/trace-replay.py --no-color

# combine flags
python agents/trace-replay.py --run-id run_abc123 --chart --format json
```

| Flag | Default | Description |
|------|---------|-------------|
| `--run-id RUN_ID` | most recent run | Specific run to replay |
| `--limit N` | 5 | Max recent runs to scan when `--run-id` is omitted |
| `--calibrate` | off | Print derived threshold and exit without replaying |
| `--self-test` | off | Run synthetic fixture tests and exit (no trace needed) |
| `--chart` | off | Print ASCII bar chart of per-subtask event counts |
| `--format text\|json` | text | Output format: human-readable or machine-readable JSON |
| `--no-color` | off | Disable ANSI color even on a capable terminal |

---

## Event kinds

Each event in a 9TO5 JSONL trace is classified into one of five kinds:

| Kind | Event patterns | Divergence signal? |
|------|---------------|-------------------|
| `FAIL` | `verification_failed`, `verify_fail`, `verify_failed`, `executor_failed`, `step_failed`, `run_failed`, `subtask_failed` | **Yes** |
| `REPLAN` | `replan`, `replan_split`, `replanned`, `replan_triggered` | **Yes** |
| `CHALLENGE` | `adversary_challenged`, `adversary_challenge` | **Yes** |
| `PASS` | `verification_passed`, `verify_pass`, `verify_passed`, `run_completed` | No |
| `INFO` | everything else | No |

`FAIL`, `REPLAN`, and `CHALLENGE` are **divergence signals** — they populate the
DIVERGENCE POINTS section of the replay report.

---

## High-activity threshold

The threshold for flagging high-activity subtasks is **not hardcoded**. At startup the tool
derives it empirically: **90th percentile of per-subtask event counts + 1**, computed across
all available run traces. Falls back to 10 when no prior traces exist.

Use `--calibrate` to inspect the derived value before replaying. A subtask with more events
than the threshold is flagged as a possible retry storm.

---

## Protocol

### Phase 1 — Acquire the trace

Identify what you have and where it lives:

| Trace type | Typical location |
|------------|-----------------|
| 9TO5 JSONL event log | `logs/runs/<run_id>.jsonl` |
| Python tracebacks | `logs/*.log`, test stderr |
| Discord/webhook payloads | bot event logs |
| HTTP request/response | proxy captures, `requests` debug logs |
| 9TO5 ExecutionStep records | run state JSON in `state/` |

Read the raw content in full. Do not summarize before reading.

For 9TO5 runs, list available traces and replay the most recent:

```sh
python agents/trace-replay.py --limit 5
```

### Phase 2 — Build the event timeline

Extract events in chronological order. For each event record, emit:

```
T+<offset>  [MODULE]  <event type>  <key fields>
```

Example:

```
T+0.00s   [orchestrator]  plan_start        goal="fix auth bug"
T+0.12s   [executor]      step_dispatched   step_id=3  prompt_len=1204
T+1.83s   [executor]      step_result       exit_code=1  stderr="ModuleNotFoundError"
T+1.84s   [verifier]      verify_fail       reason="import error"
T+1.85s   [orchestrator]  replan            attempt=2
```

### Phase 3 — Identify the divergence point

The DIVERGENCE point is the earliest event where actual behaviour first deviates from expected.

Signals to look for:
- First non-zero exit code
- First exception or traceback line
- First assertion failure
- First "unexpected" status (e.g. `verify_fail` where `verify_pass` was expected)
- A missing event that should have appeared (e.g. no `run_completed` after a long idle period)

Mark the DIVERGENCE explicitly:

```
DIVERGENCE at T+1.83s: executor step_result exit_code=1
  Expected: exit_code=0
  Actual:   exit_code=1, stderr="ModuleNotFoundError: No module named 'foo'"
```

### Phase 4 — Trace backward to root cause

From the divergence point, walk backward through the timeline:

1. What was the input to the failing step?
2. What state existed at that point (prior events)?
3. Which earlier step produced that state?
4. Repeat until you reach an originating action — a human decision, config value, or code path.

Document the root cause chain:

```
Root cause chain:
  [3] executor step_result → ModuleNotFoundError 'foo'
  [2] executor step_dispatched → imports foo in generated code
  [1] architect → spec included foo without checking requirements.txt
  ROOT: foo not in requirements.txt; architect assumed it was installed
```

### Phase 5 — Propose minimal patch

State precisely:
- **File to change** — exact path
- **Line range** — if determinable from the trace
- **Change** — what to add, remove, or modify
- **Verification command** — how to confirm the fix without a live re-run if possible

### Phase 6 — Produce replay report

```
TRACE REPLAY REPORT
===================
Trace source: <file path or description>
Total events: <N>
Divergence:   T+<offset> in <module> — <short description>

Root cause chain:
  [N] <module> <event> — <description>
  ...
  ROOT: <originating cause>

Minimal patch:
  File: <path>
  Change: <description>

Verify with: <command>
```

---

## Examples

### Example 1 — Python ModuleNotFoundError from CI log

**Trace excerpt:**

```
[executor] dispatching step: install deps
[executor] pip install -r requirements.txt → exit 0
[executor] dispatching step: run tests
[executor] python -m pytest tests/ → exit 1
  ImportError: cannot import name 'AsyncClient' from 'httpx' (0.18.2)
```

**Replay:**

```
TRACE REPLAY REPORT
Trace source: logs/run_2026-06-24.log
Total events: 8
DIVERGENCE: T+1.83s executor step_result exit_code=1
  ImportError: cannot import name 'AsyncClient' from 'httpx' (0.18.2)

Root cause chain:
  [3] executor: step fails on import
  [2] executor: code generated using httpx.AsyncClient
  [1] requirements.txt: httpx==0.18.2 (AsyncClient added in 0.20)
  ROOT: version pin too old for generated code pattern

Minimal patch:
  File: requirements.txt
  Change: httpx==0.18.2 → httpx>=0.20.0

Verify with: pip install "httpx>=0.20" && python -c "from httpx import AsyncClient"
```

### Example 2 — 9TO5 verifier spurious FAIL

**Trace excerpt (JSONL):**

```json
{"ts": "2026-06-01T10:00:00Z", "event": "verify_start",  "step_id": 5, "expected": "exit_zero"}
{"ts": "2026-06-01T10:00:01Z", "event": "step_stdout",   "data": ""}
{"ts": "2026-06-01T10:00:01Z", "event": "verify_fail",   "reason": "empty stdout treated as failure"}
```

**Replay using CLI:**

```sh
python agents/trace-replay.py --run-id run_20260601_100000
```

**Output (abridged):**

```
TRACE REPLAY  run_id=run_20260601_100000  events=3  threshold=10
========================================================================
T+0.00s   [INFO     ]  st-005  verify_start   expected='exit_zero'
T+1.00s   [INFO     ]  st-005  step_stdout    data=''
T+1.00s   [FAIL     ]  st-005  verify_fail    reason='empty stdout treated as failure'

DIVERGENCE POINTS (chronological)
  T+1.00s  [FAIL     ]  st-005  verify_fail
  -> reason='empty stdout treated as failure'

Root cause: verifier logic treats empty stdout as failure regardless of exit code.
Patch: agents/verifier.py — change empty-stdout check to use exit_code only.
Verify: re-run step with no-output script; confirm exit 0 → verify_pass.
```

### Example 3 — JSON output for CI pipeline integration

```sh
python agents/trace-replay.py --run-id run_abc123 --format json
```

**Output:**

```json
{
  "run_id": "run_abc123",
  "total_events": 12,
  "divergence_count": 2,
  "high_activity_count": 1,
  "parallel_moments": 0,
  "divergences": [
    {
      "offset": "T+2.41s",
      "event": "executor_failed",
      "subtask": "st-003",
      "kind": "FAIL",
      "fields": "exit_code='1'  stderr='SyntaxError'",
      "ts": 1748771202.41
    },
    {
      "offset": "T+3.10s",
      "event": "replan_triggered",
      "subtask": "st-003",
      "kind": "REPLAN",
      "fields": "attempt='2'",
      "ts": 1748771203.10
    }
  ],
  "high_activity_subtasks": {
    "st-003": 14
  }
}
```

### Example 4 — Self-test (no trace required)

Use `--self-test` to verify the tool's internal logic is intact without needing any archived trace:

```sh
python agents/trace-replay.py --self-test
```

Expected output:

```
[trace-replay] All self-tests passed.
```

The self-test validates:
- Event classification (`FAIL`, `REPLAN`, `CHALLENGE`, `PASS`, `INFO`)
- High-activity detection at a given threshold
- Threshold calibration from a synthetic corpus (90th percentile + 1, floored at 10)
- DIVERGENCE count from the full `_replayEvents` pipeline
- JSON output mode correctness
- Parallel execution detection

### Example 5 — ASCII bar chart

```sh
python agents/trace-replay.py --chart
```

Appends to the text report:

```
EVENT DISTRIBUTION PER SUBTASK
────────────────────────────────────────────────────────
  st-003            [██████████████████████░░░░░░░░]    14  ← HIGH
  st-001            [████████░░░░░░░░░░░░░░░░░░░░░░]     5
  st-002            [████░░░░░░░░░░░░░░░░░░░░░░░░░░]     3
```

---

## Rules

- Read the full trace before concluding. The first visible error is rarely the root cause.
- Timestamps matter. A warning emitted before an error is often the cause of that error.
- If the trace is truncated, note the truncation point and limit confidence accordingly.
- Do not patch symptoms. Patch the earliest link in the root cause chain.
- If a run has zero events, run `--self-test` first to verify the tool is working before
  assuming the run produced no data.
- Use `--calibrate` to inspect the derived threshold before interpreting high-activity flags.
- Prefer `--format json` for programmatic consumers (CI pipelines, dashboards, downstream scripts).
- `--no-color` is useful when piping output or running in environments without ANSI support.

---

## New Features

### Decision-point extraction — `_extractDecisionPoints`

**Location:** `agents/trace-replay.py`

`_extractDecisionPoints(events, context_window=2)` scans a pre-loaded event list and
returns one structured record per divergence event (`FAIL`, `REPLAN`, `CHALLENGE`),
enriched with the surrounding context window.

**Return shape (one entry per divergence):**

| Field | Type | Description |
|-------|------|-------------|
| `index` | int | Position of the event in the original list |
| `event` | str | Raw event type string (e.g. `verify_fail`) |
| `subtask` | str | Subtask ID (`subtask_id` field, or `"-"` if absent) |
| `kind` | str | Classified kind: `FAIL`, `REPLAN`, or `CHALLENGE` |
| `ts` | float | Unix timestamp |
| `offset` | str | Human offset from first event (e.g. `T+1.83s`) |
| `fields` | str | Key fields summary string |
| `context_before` | list | Up to `context_window` events immediately before |
| `context_after` | list | Up to `context_window` events immediately after |

`context_before` / `context_after` entries each carry `event`, `subtask`, and `ts`.

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `events` | — | Raw event list (dicts) loaded from a JSONL trace |
| `context_window` | `2` | Events before/after each divergence to include |

**Example (direct call):**

```python
# Load events manually, then call the private function
spec = importlib.util.spec_from_file_location("tr", "agents/trace-replay.py")
tr = importlib.util.module_from_spec(spec); spec.loader.exec_module(tr)

events = [...]  # from a JSONL trace
points = tr._extractDecisionPoints(events, context_window=3)
```

For everyday use, prefer `getDecisionPoints()` (see below) — it handles subprocess
management and returns the same shape without manual JSONL loading.

---

### Step-by-step replay spec — `buildStepSpec`

**Location:** `agents/trace_replay.py`

`buildStepSpec(run_id, limit, calibrate_limit)` is a variant of `buildSpec()` that
returns an invocation spec marked as **step mode**. Downstream orchestrator tooling
that checks `_meta["mode"]` can use this to surface per-decision `context_before` /
`context_after` windows instead of the flat divergence list.

```python
from agents.trace_replay import buildStepSpec

spec = buildStepSpec(run_id="run_abc123")
# spec["_meta"]["mode"] == "step"
# spec["claude_md_inject"] instructs the subagent to surface decision_points
```

Differences from `buildSpec()`:

- `claude_md_inject` instructs the executor to surface each entry in `decision_points`
  (with `context_before` / `context_after`) rather than the flat divergence summary.
- `_meta["mode"]` is set to `"step"` (absent in `buildSpec`).

All other keys — `skills_to_invoke`, `effort_level`, `subagent`, `prompt`,
`pre_tool_hooks`, `post_tool_hooks` — are identical.

---

### High-level decision-point API — `getDecisionPoints`

**Location:** `agents/trace_replay.py`

`getDecisionPoints(run_id, limit, calibrate_limit)` runs trace-replay via
`runWorkflow()` and repackages the result as a decision-points dict, ready for
step-by-step debugging loops or downstream orchestrator consumers.

**Signature:**

```python
def getDecisionPoints(
    run_id: str | None = None,
    limit: int = 5,
    calibrate_limit: int = 20,
) -> dict: ...
```

**Return shape:**

```python
{
    "ok": True,                  # bool: False on subprocess failure
    "run_id": "run_abc123",      # resolved run ID that was replayed
    "decision_points": [...],    # list of divergence dicts (FAIL/REPLAN/CHALLENGE)
    "total_events": 42,          # total event count in the trace
    "error": None,               # str | None: set on failure
}
```

Each `decision_points` entry includes `index`, `event`, `subtask`, `kind`, `ts`,
`offset`, `fields`, `context_before`, and `context_after`.

**Example:**

```python
from agents.trace_replay import getDecisionPoints

result = getDecisionPoints()          # most recent run
if result["ok"]:
    for dp in result["decision_points"]:
        print(f"{dp['offset']}  [{dp['kind']}]  {dp['event']}  {dp['subtask']}")
        for ev in dp["context_before"]:
            print(f"  <- {ev['event']}")
        for ev in dp["context_after"]:
            print(f"  -> {ev['event']}")
```

**`getDecisionPoints` vs `runWorkflow`:**

| | `runWorkflow()` | `getDecisionPoints()` |
|--|---|---|
| Primary output key | `divergences` | `decision_points` (same data, renamed) |
| Extra fields | `divergence_count`, `high_activity_count`, `parallel_moments`, `raw` | — |
| Use case | CI pipelines, dashboards | Step-by-step debugging, orchestrator step loops |

---

## See also

- `.claude/skills/trace_replay.md` — LLM-facing protocol (phases 1–6, full prompt)
- `.claude/skills/trace_replay/README.md` — quick reference card
- `.claude/skills/systematic_debugging/README.md` — use after replay identifies the candidate component
- `docs/TESTING.md` — how to run the narrowest useful test after a patch
