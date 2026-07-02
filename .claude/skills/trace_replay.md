---
name: trace-replay
description: >
  Replay a recorded execution trace (logs, JSON events, stdout lines) to reproduce
  and diagnose a bug without re-running live infrastructure. Extracts the causal chain
  from trace data, identifies the divergence point, and proposes the minimal patch.
  Use when a bug was observed in a prior run and you have logs/traces but can't trigger
  it live (flaky, slow, side-effectful, or prod-only).
---

## Purpose

Turn a dead log into a live debugging session. Extract cause from effect without re-running.

## When to invoke

- Bug reproduced in CI/prod but not locally reproducible
- You have a log file, JSON trace, or stdout dump from a failed run
- Explicitly invoked: `/trace-replay`, "replay this trace", "analyze this log"
- A flaky test left a pytest/unittest output but won't repro on demand

## 9TO5 built-in tool

`agents/trace_replay_cli.py` automates Phases 1–5 for any 9TO5 run trace stored under
`logs/runs/`:

```sh
# replay the most recent run
python agents/trace_replay_cli.py

# replay a specific run
python agents/trace_replay_cli.py --run-id <RUN_ID>

# show calibrated high-activity threshold and exit
python agents/trace_replay_cli.py --calibrate

# validate internal logic against synthetic fixtures
python agents/trace_replay_cli.py --self-test

# limit how many recent runs are considered when no --run-id is given
python agents/trace_replay_cli.py --limit 10
```

| Flag | Default | Description |
|------|---------|-------------|
| `--run-id RUN_ID` | most recent run | Specific run to replay |
| `--limit N` | 5 | Max recent runs to scan when `--run-id` is omitted |
| `--calibrate` | off | Print derived threshold and exit without replaying |
| `--self-test` | off | Run synthetic fixture tests and exit (no trace needed) |

### Event classification

Each event in the JSONL log is classified into one of five kinds:

| Kind | Event patterns | Role |
|------|---------------|------|
| `FAIL` | `verification_failed`, `executor_failed`, `step_failed`, `run_failed`, `subtask_failed` | Divergence signal |
| `REPLAN` | `replan`, `replan_split`, `replanned`, `replan_triggered` | Divergence signal |
| `CHALLENGE` | `adversary_challenged`, `adversary_challenge` | Divergence signal |
| `PASS` | `verification_passed`, `verify_passed`, `run_completed` | Happy path |
| `INFO` | everything else | Informational |

`FAIL`, `REPLAN`, and `CHALLENGE` events are **divergence signals** — they appear in the
DIVERGENCE POINTS section of the replay report.

### High-activity threshold calibration

The threshold for flagging high-activity subtasks (possible retry storms) is derived
empirically at startup: **90th percentile of per-subtask event counts + 1**, computed
across all available run traces. Falls back to 10 when no prior traces exist. Use
`--calibrate` to inspect the derived value before replaying.

## Protocol

### Phase 1 — Acquire the trace

Identify what you have:

| Trace type | Example source |
|------------|----------------|
| Structured JSON events | `state/runs/*.json`, orchestrator step logs |
| Python tracebacks | `logs/*.log`, test stderr |
| Discord/webhook payloads | bot event logs |
| HTTP request/response | proxy captures, `requests` debug logs |
| Custom 9TO5 step logs | `ExecutionStep` records in run state |

Read the trace file. Do not summarize it — read the raw content first.

### Phase 2 — Build the event timeline

Extract events in order. For each event record:

```
T+<offset>  [MODULE]  <event type>  <key fields>
```

Example:
```
T+0.00s     [orchestrator]  plan_start        goal="fix auth bug"
T+0.12s     [executor]      step_dispatched   step_id=3, prompt_len=1204
T+1.83s     [executor]      step_result       exit_code=1, stderr="ModuleNotFoundError"
T+1.84s     [verifier]      verify_fail       reason="import error"
T+1.85s     [orchestrator]  replan            attempt=2
```

### Phase 3 — Identify the divergence point

The divergence point is the earliest event where actual behavior deviates from expected.

Signals:
- First non-zero exit code
- First exception/traceback line
- First assertion failure
- First "unexpected" log message (status != expected)
- A missing event that should have appeared

Mark the divergence point explicitly:
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
4. Repeat until you hit an originating action (a human decision, config value, or code path).

```
Root cause chain:
  [3] executor step_result → ModuleNotFoundError 'foo'
  [2] executor step_dispatched → imports foo in generated code
  [1] architect → spec included foo without checking requirements.txt
  ROOT: foo not in requirements.txt; architect assumed it was installed
```

### Phase 5 — Propose minimal patch

State:
- **File to change** (exact path)
- **Line range** (if determinable from trace)
- **Change** (add import guard / add to requirements / fix logic)
- **Verification command** (how to confirm fix without live re-run if possible)

### Phase 6 — Produce replay report

```
TRACE REPLAY REPORT
===================
Trace source: <file path or description>
Total events: <N>
Divergence:   T+<offset> in <module> — <short description>

Root cause chain:
  <backward chain, numbered>

Minimal patch:
  File: <path>
  Change: <description>

Verify with: <command>
```

## Examples

### Example A — Python ModuleNotFoundError from CI log

Trace excerpt:
```
[executor] dispatching step: install deps
[executor] pip install -r requirements.txt → exit 0
[executor] dispatching step: run tests
[executor] python -m pytest tests/ → exit 1
  ImportError: cannot import name 'AsyncClient' from 'httpx' (0.18.2)
```

Replay report:
```
Divergence: pytest import failure — httpx 0.18.2 lacks AsyncClient (added in 0.20)
Root cause: requirements.txt pins httpx==0.18.2; test code uses httpx.AsyncClient
Patch: requirements.txt — change httpx==0.18.2 to httpx>=0.20.0
Verify: pip install httpx>=0.20 && python -c "from httpx import AsyncClient"
```

### Example B — 9TO5 verifier spurious failure

Trace excerpt (JSON):
```json
{"event":"verify_start","step_id":5,"expected":"exit_zero"}
{"event":"step_stdout","data":""}
{"event":"verify_fail","reason":"empty stdout treated as failure"}
```

Replay report:
```
Divergence: verify_fail — verifier treats empty stdout as failure
Root cause: verifier logic: `if not stdout: mark_fail()` — wrong for scripts that
            produce no output on success
Patch: agents/verifier.py — change empty-stdout check to use exit_code only
Verify: re-run step with no-output script and confirm exit 0 → verify_pass
```

## Rules

- Read the full trace before concluding. The first visible error is rarely the root cause.
- Timestamps matter. A warning before an error is often the cause.
- If the trace is truncated, note the truncation point and limit confidence accordingly.
- Do not patch the symptoms. Patch the earliest link in the root cause chain.
