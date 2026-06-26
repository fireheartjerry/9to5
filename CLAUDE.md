# 9TO5 CLAUDE.md

Behavioral and project-specific instructions for Claude Code sessions inside the 9TO5 repo.

These rules bias toward caution, surgical edits, and fast verification. For trivial tasks, use judgment, but do not use "judgment" as an excuse for broad unrelated edits.

## 0. What 9TO5 is

9TO5 is a personal autonomous AI orchestration system.

Mental model:

- **Orchestrator brain**: local Ollama model. Plans, replans, authors prompts, owns decisions.
- **Executor hands**: Claude Code CLI subprocess. Performs code edits, shell commands, git operations, and local tool work.
- **Python plumbing**: routes model decisions, subprocess execution, verification, state, memory, dashboards, and control.

Claude Code may be spawned by 9TO5 as an Executor. In that role, do the requested work, but do not silently take ownership of orchestration/product decisions beyond the task.

For deeper architecture, read:

- `LLM_MAP.md`
- `docs/DOC_MAINTENANCE.md`
- `docs/ARCHITECTURE.md`
- `docs/DANGER_MAP.md`
- `docs/TESTING.md`
- `docs/NIGHTCLAW.md`
- `docs/STATE.md`
- `docs/MEMORY.md`
- `docs/CUSTOM_SKILLS_AND_HOOKS.md`
- `docs/edit_recipes/`

## 1. Persistent session vocabulary

Use these terms consistently:

- **Terminal A** = a human-operated Claude Code terminal used to develop 9TO5 directly.
- **9TO5 Executor** = a Claude Code subprocess spawned by 9TO5 to execute a subtask.
- **Orchestrator** = the local Ollama-driven brain that plans, authors prompts, and replans.
- **Nightclaw** = the Discord bot / orchestrator-facing bot surface inside 9TO5.
- **Run** = one full 9TO5 work session.
- **Subtask** = a meaningful unit of work within a run.
- **ExecutionStep** = one concrete Claude/browser/native/local action.
- **Verification** = proof that work succeeded.

These instructions apply to both Terminal A sessions and 9TO5-spawned Executor subprocesses.

Terminal A has more human context, but it must still follow the same repo discipline so future automated 9TO5 subprocesses inherit a coherent codebase instead of a pile of archaeological layers.

## 2. Nightclaw terminology

For now, **Nightclaw refers to the actual Discord bot / orchestrator-facing bot surface inside 9TO5**.

If a task says:

- "improve Nightclaw CI/CD"
- "fix Nightclaw dashboard"
- "improve Nightclaw command handling"
- "make Nightclaw more reliable"

interpret it as improving the internal 9TO5/Nightclaw bot/orchestrator infrastructure.

Do not invent a separate human-controlled Nightclaw agent unless the task explicitly defines one.

## 3. Think before coding

Do not assume. Do not hide confusion. Surface tradeoffs.

Before implementing:

- State important assumptions when they matter.
- If multiple interpretations exist, identify them.
- If a simpler approach exists, say so.
- Push back on overcomplicated, unsafe, or off-scope requests.
- If a human is available and ambiguity blocks safe progress, ask.
- If running autonomously and no human is available, choose the safest smallest interpretation, document the ambiguity, and avoid irreversible/broad changes.

## 4. Simplicity first

Minimum code that solves the problem. Nothing speculative.

Rules:

- No features beyond what was asked.
- No abstractions for single-use code.
- No configurability that was not requested.
- No error handling for impossible scenarios.
- Prefer boring explicit code over clever dynamic machinery.
- If 200 lines could be 50, simplify.

Ask:

```txt
Would a senior engineer say this is overcomplicated?
```

If yes, simplify.

## 5. Surgical changes

Touch only what you must. Clean up only your own mess.

When editing existing code:

- Do not improve adjacent code, comments, or formatting.
- Do not refactor unrelated code.
- Match existing style.
- If you notice unrelated dead code, mention it instead of deleting it.
- Every changed line should trace directly to the task.

When your changes create orphans:

- Remove imports, variables, functions, or tests made unused by your change.
- Do not remove pre-existing dead code unless asked.

## 6. Core editing loop

For every coding task:

1. Understand the requested change.
2. Read `CLAUDE.md`.
3. Read the smallest relevant subset of the docs listed in `docs/DOC_MAINTENANCE.md`.
4. Locate the smallest relevant module/file.
5. Identify involved contracts and source-of-truth ownership.
6. Make the smallest safe patch.
7. Run the narrowest useful test.
8. If the test fails, inspect the failure and patch only the relevant cause.
9. Rerun the same focused test.
10. Escalate to broader tests only after focused tests pass.
11. Update relevant Markdown docs in the same patch if behavior, structure, commands, interfaces, state, or workflow changed.
12. Summarize files changed, behavior changed, docs updated, verification, and risks.

When in doubt:

```txt
smaller patch
narrower test
clearer explanation
```

## 7. Documentation persistence protocol

Documentation is part of the system, not an afterthought.

Every code change must keep the relevant Markdown files synchronized with the new reality.

When changing code, update docs in the same patch if the change affects any of:

- module ownership
- file structure
- lifecycle/status values
- source-of-truth ownership
- agent roles
- executor behavior
- verifier behavior
- ControlBus behavior
- dashboard behavior
- Nightclaw behavior
- self-improvement behavior
- universe/path policy behavior
- config shape
- test commands
- testing strategy
- generated/runtime artifact rules
- external integration behavior
- developer workflow

Do not leave documentation stale with "todo update docs later."

Use `docs/DOC_MAINTENANCE.md` as the canonical documentation protocol.

## 8. Patch-size discipline

Prefer:

- one behavior change per patch
- one module or tightly related module group per patch
- one focused test target per patch
- one clear verification command per patch

Avoid:

- broad unrelated refactors
- changing architecture while fixing a small bug
- formatting churn mixed with logic changes
- touching generated/runtime artifacts
- touching caches, logs, virtualenvs, secrets, or VCS internals
- changing lifecycle/status names without updating tests/docs/dashboard consumers
- modifying state schemas without migration notes
- expanding universe boundaries without explicit approval

## 9. Test-selection rules

Run the narrowest useful test first.

Suggested order:

1. Syntax/import/config sanity check
2. Focused module test
3. Related fake-backend integration test
4. Full suite
5. Live/browser/native/manual checks only when required

Prefer canonical commands from `docs/TESTING.md`, `Makefile`, `justfile`, or `scripts/check.py` if present.

Do not run slow, live, Discord, browser, native UI, or destructive checks unless the changed area requires them.

Do not claim tests passed unless they actually ran and passed.

## 10. Failure handling

When verification fails, do not rewrite broadly.

Instead:

1. Read the failure carefully.
2. Identify the smallest likely cause.
3. Inspect only relevant files.
4. Patch the cause.
5. Rerun the same focused test.
6. Escalate only if repeated focused fixes fail.

Good failure handling answers:

- what failed?
- what input caused it?
- what was expected?
- what happened instead?
- where is the likely relevant code?
- what command should be rerun?

## 11. Source-of-truth rules

Respect source-of-truth ownership.

General rules:

- Run state belongs to canonical task state / state store, not Discord or web UI.
- Control commands belong to ControlBus.
- Verification status belongs to verifier results.
- Persistent notes/context belong to Obsidian + disk fallback.
- Dashboard output is derived display state.
- File safety boundaries belong to Universe + guard policy.

Discord and web dashboards are windows into state. They are not the state machine.

## 12. Architecture invariants

Preserve these unless explicitly asked to redesign:

- strict protocol, replaceable intelligence
- deterministic lifecycle/state transitions
- explicit contracts over unstructured dicts where practical
- pure decision logic separated from side effects where practical
- verification gates before marking work complete
- retry-on-failure includes failure context
- dashboard state is derived from canonical run state
- learning/self-improvement consumes traces and proposes improvements, but does not bypass guards, verifier, adversary, or configured human gates
- `allowed_paths` are precision hints, not hard allowlists
- `hard_boundaries` are actual forbidden paths

## 13. Boundary rules

Do not touch:

- secrets
- credentials
- `.env` files unless explicitly authorized
- virtualenvs
- VCS internals such as `.git/`
- generated artifacts as if they were source
- runtime logs as implementation
- cache directories
- task state files unless the task is explicitly about state handling
- hard-boundary paths defined by Universe/path policy

Never hardcode secrets.

## 14. Naming discipline

Use stable terms consistently:

- **Goal** = human objective
- **ElaboratedGoal** = approved clarified objective
- **TaskGraph** = planned decomposition
- **Subtask** = meaningful unit of work
- **ExecutionStep** = one Claude/browser/native/local action
- **Verification** = proof that work succeeded
- **Review** = adversarial critique
- **Replan** = task graph modification after failure or new info
- **Run** = full work session
- **Terminal A** = human-operated Claude Code terminal developing 9TO5
- **Nightclaw** = Discord bot / orchestrator-facing bot surface inside 9TO5

Do not casually introduce synonyms unless they map to explicit canonical meanings.

## 15. File and module guidelines

Prefer files with one reason to change.

Ideal sizes:

- 100-350 lines: ideal
- 350-700 lines: acceptable
- 700-1200 lines: acceptable only if conceptually coherent
- 1200+ lines: refactor candidate

Avoid vague dumping grounds like:

- `utils.py`
- `helpers.py`
- `manager.py`
- `misc.py`

unless narrow and explicit.

Prefer explicit contracts:

- dataclasses
- TypedDicts
- Protocols
- enums/Literals
- small schema objects

Avoid unstructured cross-module dicts when schemas are feasible.

## 16. Documentation update rules

Update docs when changing:

- module ownership
- lifecycle/status values
- source-of-truth ownership
- agent interfaces
- verifier behavior
- executor behavior
- ControlBus behavior
- dashboard behavior
- self-improvement behavior
- universe/path policy behavior
- canonical commands
- test strategy

Use the appropriate doc:

- `LLM_MAP.md` for repo navigation
- `docs/DOC_MAINTENANCE.md` for documentation consistency rules
- `docs/ARCHITECTURE.md` for system design
- `docs/DANGER_MAP.md` for high-risk files/invariants
- `docs/TESTING.md` for test commands/tiers
- `docs/NIGHTCLAW.md` for Nightclaw-specific bot/dashboard details
- `docs/STATE.md` for task/run/control state schemas
- `docs/MEMORY.md` for Obsidian and persistent memory
- `docs/CUSTOM_SKILLS_AND_HOOKS.md` for automation hooks/skills
- `docs/edit_recipes/` for repeatable task playbooks

## 17. Final response format after edits

After making changes, respond with:

```txt
Changed:
- <file path>: <short reason>

Behavior:
- <what changed externally, if anything>
- <what stayed intentionally unchanged>

Documentation:
- <docs updated and why>
- <docs checked but not changed>
- <docs that may still need follow-up, if any>

Verification:
- <exact command run>: <pass/fail>
- <skipped tests, if any, and why>

Risks:
- <remaining uncertainty>
- <areas not touched>
- <suggested next focused step>
```

Do not produce vague summaries like "updated the codebase." Name files, behavior, commands, docs, and risks.
