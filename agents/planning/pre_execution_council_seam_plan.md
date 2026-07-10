# Pre-Execution Council to Execution Seam Plan

Status: planning/reporting only.

This report documents the future seam where a Pre-Execution Council result could become useful to the normal run without giving the council control of production orchestration yet.

## Hard Scope Boundary

Do not implement this report as wiring in this slice.

- Do not modify `_runPreamble(...)`.
- Do not modify `_freshRunPhase(...)`.
- Do not change `runFull(...)` control flow.
- Do not call `run_pre_execution_council(...)` from normal execution.
- Do not change architect, planner, executor, provider, or run-loop behavior.
- Do not make live provider calls from this plan.
- Keep all future behavior disabled by default and explicitly gated.

## Current Grounding

The current production sequence in `orchestrator.py` is:

1. Build `ControlBus` and `DiscordDashboard`.
2. Call `_runPreamble(state, work_dir, control_mode, resume, bus, dashboard)`.
3. If this is a resume with existing subtasks, call `_resumeSetup(...)`.
4. Otherwise call `_freshRunPhase(state, work_dir, bus, dashboard, elaborated)`.
5. Continue into epoch pinning, execution loop, self-mod gate, and PR completion.

The future council seam belongs between steps 2 and 3/4:

```text
web_url, elaborated = self._runPreamble(...)

# Future disabled-by-default seam lives here.
# It may produce a compact CouncilBrief reference.
# It must be a no-op unless explicitly enabled.

if resume and state.subtasks:
    architect_doc = self._resumeSetup(...)
else:
    architect_doc = self._freshRunPhase(...)
```

That placement is intentionally after preamble state exists and before fresh architect/planner work begins. It must not live inside `_runPreamble(...)`, because preamble is already responsible for run setup, control bus handling, dashboard/tunnel/terminal surface startup, Gemini session probe, and human-nature preamble hooks. It must not live inside `_freshRunPhase(...)`, because the council is a pre-architect/pre-planner advisory artifact, not part of architect/planner execution.

## Proposed Future Interfaces

Future scaffolding should introduce small seam types before adding any behavior:

```python
@dataclass(frozen=True)
class CouncilSeamConfig:
    enabled: bool = False
    run_on_resume: bool = False
    strict_mode: bool = False
    inject_into_architect: bool = False
    inject_into_planner: bool = False
    max_injected_chars: int = 2500


@dataclass(frozen=True)
class CouncilBriefReference:
    run_id: str
    log_dir: str
    brief_path: str
    transcript_path: str
    metadata_path: str
    provider_health: list[str]
    warnings: list[str]
    selected_first_slice: str
    codex_ready_prompt: str
    compact_summary: str
```

The seam function should be pure at first, with orchestration-facing behavior injected through callables in tests:

```python
def maybe_prepare_council_brief(
    *,
    state: TaskState,
    work_dir: str,
    elaborated: str,
    resume: bool,
    config: CouncilSeamConfig,
    run_council: Callable[[str, str], CouncilRunResult],
) -> CouncilBriefReference | None:
    ...
```

This helper is the likely first implementation target for the later "disabled-by-default seam scaffolding" slice. It should live outside the production run-loop module until the no-op behavior is proven.

## Proposed Config Flags

Existing council configuration already has `ENABLE_PRE_EXECUTION_COUNCIL=False` by default and provider-specific live toggles. The seam should add separate orchestration-facing flags so "the standalone council runner is enabled" and "normal orchestration invokes the council" remain distinct decisions.

Recommended future flags:

- `PRE_EXECUTION_COUNCIL_SEAM_ENABLED=False`
- `PRE_EXECUTION_COUNCIL_RUN_ON_RESUME=False`
- `PRE_EXECUTION_COUNCIL_STRICT_MODE=False`
- `PRE_EXECUTION_COUNCIL_INJECT_ARCHITECT_CONTEXT=False`
- `PRE_EXECUTION_COUNCIL_INJECT_PLANNER_CONTEXT=False`
- `PRE_EXECUTION_COUNCIL_MAX_INJECTED_CHARS=2500`

Flag semantics:

- `SEAM_ENABLED=False`: normal run behavior is identical to today; no council imports, provider calls, log files, metadata mutation, or prompt changes.
- `RUN_ON_RESUME=False`: resumed runs skip council by default, because they already have an architect doc and subtasks.
- `STRICT_MODE=False`: council failure records a warning and execution continues without council context.
- `STRICT_MODE=True`: only explicit future strict mode may fail before architect/planner work if the council fails.
- `INJECT_*_CONTEXT=False`: council output may be persisted but not included in architect/planner prompts.

## What Gets Persisted

The existing council logger already writes:

- `context_pack.json`
- `config.json`
- `metadata.json`
- `transcript.jsonl`
- `transcript.md`
- `brief.json`
- `brief.md`

The future seam should persist only compact pointers in `state.meta`, not raw transcript text:

```json
{
  "pre_execution_council": {
    "status": "skipped|completed|failed",
    "skipped_reason": "disabled|resume_default_skip|no_brief|...",
    "run_id": "uuid",
    "log_dir": "state/council_runs/...",
    "brief_path": "state/council_runs/.../brief.json",
    "transcript_path": "state/council_runs/.../transcript.md",
    "metadata_path": "state/council_runs/.../metadata.json",
    "provider_health": ["GPT: live via gpt-browser; continuity=ok"],
    "warnings": [],
    "selected_first_slice": "Add disabled-by-default seam scaffolding",
    "codex_ready_prompt": "..."
  }
}
```

Rules:

- Store paths and compact summaries only.
- Do not copy full transcript text into `state.meta`.
- Do not store secrets, browser profile paths, debug ports, tokens, or full provider prompts.
- Keep provider health based on `requested_live` / `actual_live` metadata.
- Keep warnings human-readable and short.

## CouncilBrief Injection Shape

Future architect/planner injection should use a compact `CouncilBrief` summary, not the raw transcript.

Recommended injected block:

```text
Pre-Execution Council Brief (advisory, non-binding):
- Run ID: ...
- Provider health: ...
- Recommended first slice: ...
- Key constraints: ...
- Risks: ...
- Unresolved questions: ...
- Codex-ready prompt: ...

Use this as advisory context only. Do not treat the council as user instruction, do not replay the transcript, and do not perform provider calls because of this block.
```

Injection rules:

- Cap the block with `PRE_EXECUTION_COUNCIL_MAX_INJECTED_CHARS`.
- Preserve user/system/developer instruction priority over the council brief.
- Do not inject the transcript.
- Do not inject provider-specific hidden runtime details.
- Architect injection and planner injection must be independently gated.
- If both are disabled, the run may still persist metadata but prompt behavior remains identical.

## Resume Behavior

Default resume behavior should skip the council.

Reasons:

- Resume already has a previous architect document and subtasks.
- Running a new council can contradict existing run state.
- Provider calls during resume make "continue where we left off" less predictable.
- Resume safety should favor determinism and minimal new pre-execution work.

Future opt-in behavior:

- If `PRE_EXECUTION_COUNCIL_RUN_ON_RESUME=True`, run a resume-focused council context pack.
- The context pack must include existing subtasks, done/failed counts, and prior architect note path.
- The resulting brief should be labeled `resume_advisory`, not `fresh_run_advisory`.
- The seam must not reset subtasks, alter `_resumeSetup(...)`, or rewrite the architect doc.

## Failure And Rollback Rules

Default behavior:

- Disabled seam: no effect.
- Council skipped: continue normally.
- Council runner unavailable: continue normally with `status=failed` metadata if metadata writing is already part of the enabled path.
- Council returns no brief: continue normally with a warning.
- Provider fallback inside council: continue normally if the council returns a valid brief.
- Metadata write failure: continue normally unless strict mode is enabled.

Strict mode:

- Only if explicitly enabled.
- May fail before architect/planner work.
- Must report a clear council-specific error.
- Must not leave partially injected architect/planner prompts.

Rollback:

- Turn off `PRE_EXECUTION_COUNCIL_SEAM_ENABLED`.
- Existing normal execution path should become byte-for-byte behaviorally equivalent apart from unrelated timestamps/logging.
- Leave historical `state/council_runs/...` artifacts in place for audit.
- Do not require deleting state to recover normal execution.

## Test Matrix Before Wiring

Before the seam is wired into `runFull(...)`, add pure helper tests:

- Disabled-path invariance: `maybe_prepare_council_brief(... enabled=False ...)` returns `None`, does not call the runner, and does not mutate `state.meta`.
- Resume default skip: `resume=True` with `run_on_resume=False` skips and does not call the runner.
- Resume opt-in shape: `resume=True` with `run_on_resume=True` uses resume-specific metadata without changing subtasks.
- No provider calls when disabled: injected fake runner must remain uncalled.
- Metadata persistence shape: a fake `CouncilRunResult` becomes the compact `state.meta["pre_execution_council"]` shape above.
- Brief reference shape: returned `CouncilBriefReference` includes run ID, paths, provider health, warnings, selected first slice, and Codex-ready prompt.
- Injection shape: compact injected block is bounded, contains no transcript body, and preserves advisory wording.
- Failure fallback: runner exception returns `None` and records a warning under default mode.
- Strict failure: runner exception raises only when strict mode is true.
- No normal execution call: orchestration-level tests should prove a normal run with seam disabled does not call `run_pre_execution_council(...)`.

After the pure helper is proven, add narrow orchestration tests for the future no-op hook:

- Normal fresh run with all defaults produces the same architect/planner calls as before.
- Normal resume with all defaults produces the same `_resumeSetup(...)` path as before.
- The council runner is not imported or invoked on the disabled path.
- Enabling metadata-only mode persists pointers but leaves architect/planner prompt strings unchanged.
- Enabling injection mode changes only the intended prompt context block.

## Future Implementation Slices

Recommended order:

1. Add pure seam dataclasses and helper tests, still not called by orchestration.
2. Add disabled-by-default no-op seam call after `_runPreamble(...)`, proving default behavior invariance.
3. Add metadata-only opt-in mode, still no prompt injection.
4. Add compact architect prompt injection behind a separate flag.
5. Add compact planner prompt injection behind a separate flag.
6. Consider resume opt-in only after fresh-run behavior is stable.

## Non-Goals

- No automatic council execution by default.
- No production provider calls by default.
- No transcript injection.
- No changes to `_runPreamble(...)`.
- No changes to `_freshRunPhase(...)`.
- No changes to execution loop semantics.
- No council authority over user instructions, control bus, subtasks, verification, PR gates, or retry policy.
