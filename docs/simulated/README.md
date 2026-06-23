# Simulated Area - Unit Tests and Error Handling

The "simulated" area of 9to5 comprises `simulation.py` (dry-run doubles) and
`sim_error_handling.py` (shared error-handling utilities). Together they let
the full orchestration pipeline run in CI with no external services.

## Unit Testing

### Test files

| File | Scope |
|------|-------|
| `tests/test_simulator.py` | Error-handling paths in `sim_error_handling.py` and failure modes of simulation.py |
| `tests/test_simulation_units.py` | Happy-path unit tests for every public class/function |
| `tests/test_dry_run.py` | Integration: full `runFull` via simulation doubles |
| `tests/test_builder_sim.py` | Integration: builder doubles with real file artifacts |

### Running the tests

```bash
python -m pytest tests/test_simulator.py tests/test_simulation_units.py -v
```

### Coverage

`test_simulation_units.py` and `test_simulator.py` together cover all public
methods in `simulation.py`:

- `SimBrain.__init__`, `_plan`, `chat` - happy path + n_subtasks edge cases + non-dict messages
- `simRunClaude` - architect phase, subtask phase, missing IDs, None spec
- `SimObs.writeNote`, `appendNote`, `readNote`, `health` - write/append/read roundtrip
- `simReplan` / `simReview` - return shape, kwargs passthrough
- `BuilderBrain.__init__`, `_plan`, `chat` - verify cmd structure, non-dict messages
- `builderRunClaude` - file creation, nested dirs, write failure path
- `buildOrchestrator` / `buildBuilderOrchestrator` - Orchestrator construction

## Error Handling

### `sim_error_handling.py`

Three utilities centralise the recurring patterns in `simulation.py`:

#### `safeParseJson(text, fallback=None)`

Parses a JSON string; returns `fallback` (default `None`) on `JSONDecodeError`
or `TypeError`. Use for any brain-response parsing.

```python
data = safeParseJson(raw_response, fallback={})
```

#### `safeWritePath(path, content, encoding="utf-8")`

Writes `content` to `path`, creating parent directories as needed.
Returns `{"ok": True, "error": None}` on success or
`{"ok": False, "error": "<message>"}` on failure - never raises.

```python
rv = safeWritePath(target_path, source_code)
if not rv["ok"]:
    LOG.warning("could not write: %s", rv["error"])
```

#### `safeChatExtract(messages, role="user")`

Extracts the last message for `role` from a messages list. Skips non-dict
items silently; returns `""` on any error including `None` input.

```python
user_text = safeChatExtract(messages)   # last "user" message, or ""
```

### Integration with `simulation.py`

`sim_error_handling.py` provides the error-handling primitives that `simulation.py`
uses (or can adopt) for its three recurring patterns:

- **JSON parse errors**: `safeParseJson` for brain-response parsing
- **File write failures**: `safeWritePath` replaces bare `try/except` in `builderRunClaude`
- **Bad message lists**: `safeChatExtract` handles non-dict items and `None` inputs

### Backward compatibility

All changes are additive: existing callers see the same return types and
envelope keys as before. Error paths that previously raised exceptions now
return structured failure dicts instead.
