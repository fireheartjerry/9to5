# Trace Replay Subagent

**Module:** `agents/trace_replay.py`  
**CLI script:** `agents/trace_replay_cli.py`  
**Companion docs:** `docs/trace_replay.md`, `.claude/skills/trace_replay.md`

---

## What it does

`agents/trace_replay.py` is the orchestration-level wrapper around the `agents/trace_replay_cli.py`
CLI script. It provides Python functions for the 9TO5 orchestrator to dispatch trace-replay
diagnostics as a structured subagent step — with pre-built invocation specs, JSON output
parsing, and a fast-path skip when no archived runs exist.

Use this module when you want to programmatically trigger trace replay inside the
orchestration pipeline rather than invoking the CLI by hand.

Key optimizations vs bare CLI invocation:

- JSON output mode (`--format json --no-color`): skips ANSI rendering; structured result
  is O(1) to parse.
- Calibration capped at 20 recent runs instead of 100.
- Existence pre-check via `tracing.recentRunIds()`: no replay attempted when no traces
  exist.

---

## Public API

### `DEFAULT_INVOCATION_SPEC`

A ready-to-use invocation spec dict that follows the executor.py conventions. The orchestrator
can dispatch this verbatim when no run-specific overrides are needed.

```python
from agents.trace_replay import DEFAULT_INVOCATION_SPEC

# Dispatch the subagent with baseline settings
orchestrator.dispatch(DEFAULT_INVOCATION_SPEC)
```

Keys:

| Key | Value |
|-----|-------|
| `claude_md_inject` | Context injected into the Claude session |
| `skills_to_invoke` | `[]` — no additional skills needed |
| `effort_level` | `"default"` |
| `subagent` | `None` |
| `prompt` | Instruction to run `trace_replay_cli.py --format json --no-color` |
| `pre_tool_hooks` | `[]` |
| `post_tool_hooks` | `["write_obsidian"]` — result is persisted to Obsidian |

---

### `buildSpec(run_id, limit, calibrate_limit) -> dict`

Returns an invocation spec dict tuned for a specific run.

```python
from agents.trace_replay import buildSpec

# Replay the most recent run
spec = buildSpec()

# Replay a specific run
spec = buildSpec(run_id="run_20260624_103000")

# Limit scan to last 10 runs when no run_id is given
spec = buildSpec(limit=10)

# Cap calibration to 5 runs for speed
spec = buildSpec(calibrate_limit=5)
```

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `run_id` | `None` | Target run ID. `None` → most recent run. |
| `limit` | `5` | Max recent runs to surface as alternatives when no `run_id` is given. |
| `calibrate_limit` | `20` | Max runs used to calibrate the high-activity threshold. |

The returned spec includes a `_meta` key with `run_id`, `limit`, `calibrate_limit`,
`output_format`, and `color` for downstream tooling.

---

### `runWorkflow(run_id, limit, calibrate_limit) -> dict`

Execute the trace-replay script directly and return parsed results.

```python
from agents.trace_replay import runWorkflow

result = runWorkflow()
if result["ok"]:
    print(f"divergence_count={result['divergence_count']}")
    print(f"high_activity_count={result['high_activity_count']}")
    for d in result["divergences"]:
        print(f"  {d['offset']}  {d['event']}  [{d['kind']}]")
else:
    print(f"error: {result['error']}")
```

**Return value schema:**

| Key | Type | Description |
|-----|------|-------------|
| `ok` | `bool` | `True` when the in-process replay completed. |
| `run_id` | `str \| None` | Resolved run ID that was replayed. |
| `divergence_count` | `int` | Number of FAIL/REPLAN/CHALLENGE events found. |
| `high_activity_count` | `int` | Number of subtasks flagged as high-activity. |
| `parallel_moments` | `int` | Number of concurrent execution moments detected. |
| `total_events` | `int` | Total events in the replayed trace. |
| `divergences` | `list[dict]` | Structured list of divergence events (see below). |
| `raw` | `str` | JSON-serialized replay report. |
| `error` | `str \| None` | Error message on failure; `None` on success. |

**`divergences` entry schema:**

| Key | Type | Description |
|-----|------|-------------|
| `offset` | `str` | Time offset string, e.g. `"T+2.41s"`. |
| `event` | `str` | Event type, e.g. `"executor_failed"`. |
| `subtask` | `str` | Subtask ID, e.g. `"st-003"`. |
| `kind` | `str` | Event kind: `"FAIL"`, `"REPLAN"`, or `"CHALLENGE"`. |
| `fields` | `str` | Formatted key=value fields from the event. |
| `ts` | `float` | Unix timestamp. |

**Error values:**

| `error` value | Meaning |
|---------------|---------|
| `None` | Success. |
| `"no_traces"` | No archived run traces found; replay skipped. |
| `"timeout"` | Subprocess exceeded 60 s time limit. |
| `"json_parse_error"` | Subprocess output could not be parsed as JSON. |
| `"exit N: <stderr>"` | Subprocess exited with non-zero code. |

---

### `buildStepSpec(run_id, limit, calibrate_limit) -> dict`

Like `buildSpec()`, but the `claude_md_inject` context marks this as **step-by-step
decision-point mode**. Downstream tooling surfaces `context_before` / `context_after`
windows around each divergence.

```python
from agents.trace_replay import buildStepSpec

spec = buildStepSpec(run_id="run_20260624_103000")
# spec["_meta"]["mode"] == "step"
```

---

### `getDecisionPoints(run_id, limit, calibrate_limit) -> dict`

Run trace-replay and return structured decision points (divergences repackaged for
step-by-step debugging). Delegates the replay to `runWorkflow()`.

```python
from agents.trace_replay import getDecisionPoints

result = getDecisionPoints()
for dp in result["decision_points"]:
    print(f"  {dp['offset']}  {dp['kind']}  {dp['event']}  subtask={dp['subtask']}")
```

**Return value schema:**

| Key | Type | Description |
|-----|------|-------------|
| `ok` | `bool` | `True` when replay succeeded. |
| `run_id` | `str \| None` | Resolved run ID. |
| `decision_points` | `list[dict]` | Divergence entries (same schema as `divergences`). |
| `total_events` | `int` | Total events in the replayed trace. |
| `error` | `str \| None` | Error message on failure; `None` on success. |

---

## Invocation spec format

All spec dicts follow the executor.py invocation spec convention. Required keys:

```python
spec = {
    "claude_md_inject": str,       # Context injected into the Claude Code session
    "skills_to_invoke": list,      # Skills to load (usually [])
    "effort_level": str,           # "default" | "high" | "low"
    "subagent": None | str,        # Nested subagent override (usually None)
    "prompt": str,                 # The task prompt
    "pre_tool_hooks": list,        # Hooks before tool calls
    "post_tool_hooks": list,       # Hooks after tool calls (["write_obsidian"] typical)
}
```

---

## Quick start

### 1. Replay most recent run from Python

```python
from agents.trace_replay import runWorkflow

result = runWorkflow()
print(result["divergence_count"], "divergences found")
```

### 2. Replay a specific run

```python
from agents.trace_replay import runWorkflow

result = runWorkflow(run_id="run_20260624_103000")
for d in result["divergences"]:
    print(d["offset"], d["kind"], d["event"])
```

### 3. Dispatch as an orchestrator subagent step

```python
from agents.trace_replay import buildSpec

spec = buildSpec(run_id="run_20260624_103000")
orchestrator.dispatch(spec)
```

### 4. Get decision points for step-by-step review

```python
from agents.trace_replay import getDecisionPoints

result = getDecisionPoints()
for dp in result["decision_points"]:
    print(dp["offset"], dp["subtask"], dp["event"])
```

### 5. Use the CLI directly (no Python)

```sh
# Human-readable text report
python agents/trace_replay_cli.py --run-id run_20260624_103000

# Machine-readable JSON (same as runWorkflow output)
python agents/trace_replay_cli.py --run-id run_20260624_103000 --format json --no-color

# Validate tool logic without a trace
python agents/trace_replay_cli.py --self-test
```

---

## Examples

### Example 1 — Check for divergences after a run

```python
from agents.trace_replay import runWorkflow

result = runWorkflow()
if not result["ok"]:
    print(f"Replay failed: {result['error']}")
elif result["divergence_count"] == 0:
    print("No divergences — clean run.")
else:
    print(f"{result['divergence_count']} divergence(s):")
    for d in result["divergences"]:
        print(f"  {d['offset']}  [{d['kind']}]  {d['event']}  subtask={d['subtask']}")
```

### Example 2 — Build a spec, inspect it, then dispatch

```python
from agents.trace_replay import buildSpec

spec = buildSpec(run_id="run_20260624_103000", calibrate_limit=10)
print("prompt:", spec["prompt"])
print("meta:", spec["_meta"])

# When satisfied, dispatch via orchestrator:
orchestrator.dispatch(spec)
```

### Example 3 — Step-by-step decision replay

```python
from agents.trace_replay import getDecisionPoints

result = getDecisionPoints(limit=3)
print(f"Replayed run: {result['run_id']}  ({result['total_events']} events)")
for i, dp in enumerate(result["decision_points"], 1):
    print(f"  [{i}] {dp['offset']}  {dp['kind']}  {dp['event']}")
```

### Example 4 — JSON output via CLI (CI integration)

```sh
python agents/trace_replay_cli.py --run-id run_abc123 --format json --no-color
```

Output:

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
    }
  ],
  "high_activity_subtasks": { "st-003": 14 }
}
```

---

## Rules

- Always check `result["ok"]` before reading `divergence_count` or `divergences`.
- When `error == "no_traces"`, no replay was attempted — the result is valid but empty.
- Use `buildSpec()` / `buildStepSpec()` when you need an invocation spec dict for the
  orchestrator; use `runWorkflow()` / `getDecisionPoints()` when you want results directly.
- The `post_tool_hooks: ["write_obsidian"]` default persists replay results to Obsidian.
  Remove it if you are running in a context without an Obsidian server.
- Prefer `--format json --no-color` in CI pipelines; the text format is for human review only.

---

## See also

- `docs/trace_replay.md` — full CLI reference and six-phase protocol
- `.claude/skills/trace_replay.md` — LLM-facing skill (invoked via `/trace-replay`)
- `.claude/skills/trace_replay/README.md` — quick reference card
- `agents/trace_replay_cli.py` — the underlying CLI script
- `docs/TESTING.md` — how to run the narrowest useful test after a patch
