# trace-replay

Turn a dead log into a live debugging session. Diagnose bugs from recorded traces without re-running live infrastructure.

## What it does

Given a log file, JSON event stream, stdout dump, or test output from a prior run, this skill
extracts an event timeline, identifies the divergence point (where actual behavior first deviated
from expected), traces backward to the root cause, and proposes the minimal patch.

Use when a bug was observed in a prior run and you can't trigger it again (flaky, slow, prod-only,
or side-effectful).

## How to invoke

```
/trace-replay
replay this trace
analyze this log
```

Provide the trace file path or paste the relevant log excerpt.

For 9TO5 runs, use the built-in CLI tool directly:

```sh
# replay the most recent run
python agents/trace-replay.py

# replay a specific run by ID
python agents/trace-replay.py --run-id <RUN_ID>

# print calibrated high-activity threshold and exit
python agents/trace-replay.py --calibrate

# validate internal logic with synthetic fixtures (no trace needed)
python agents/trace-replay.py --self-test
```

## Trace types supported

| Type | Source |
|------|--------|
| Structured JSON events | `state/runs/*.json`, orchestrator step logs |
| Python tracebacks | `logs/*.log`, pytest stderr |
| Discord/webhook payloads | bot event logs |
| HTTP request/response | proxy captures |
| 9TO5 ExecutionStep records | run state JSON |

## Output format

```
TRACE REPLAY REPORT
===================
Trace source: <file path>
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

## Example

```
TRACE REPLAY REPORT
Trace source: logs/run_2026-06-24.log

Divergence: T+1.83s executor step_result exit_code=1
  ImportError: cannot import name 'AsyncClient' from 'httpx' (0.18.2)

Root cause chain:
  [3] executor: step fails on import
  [2] executor: code generated with httpx.AsyncClient
  [1] requirements.txt: httpx==0.18.2 (AsyncClient added in 0.20)
  ROOT: version pin too old for generated code pattern

Patch: requirements.txt — httpx==0.18.2 → httpx>=0.20.0
Verify: pip install "httpx>=0.20" && python -c "from httpx import AsyncClient"
```

## Event kinds

Each event in a 9TO5 JSONL trace is classified into one of five kinds:

| Kind | Meaning | Divergence signal? |
|------|---------|--------------------|
| `FAIL` | Verification or executor failure | Yes |
| `REPLAN` | Orchestrator replanned after failure | Yes |
| `CHALLENGE` | Adversary challenged the result | Yes |
| `PASS` | Successful verification or run completion | No |
| `INFO` | Informational event | No |

`FAIL`, `REPLAN`, and `CHALLENGE` events appear in the **DIVERGENCE POINTS** summary.
A subtask with more events than the calibrated threshold is flagged as high-activity
(possible retry storm).

## Rules

- Read the full trace before concluding. First visible error is rarely root cause.
- Timestamps matter. A warning before an error is often the cause.
- Do not patch symptoms. Patch the earliest link in the root cause chain.
- If the trace has zero events, run `python agents/trace-replay.py --self-test` to
  verify the tool itself is working correctly before assuming the run produced no data.

## See also

- [`../trace_replay.md`](../trace_replay.md) — full LLM-facing protocol
- `../systematic_debugging/README.md` — use after replay identifies the candidate component
