# Danger Map

High-risk files, invariants, and forbidden edits for 9TO5.

Read this before touching orchestration, state, control, verification, self-modification, or dashboard code.

## Absolute forbidden edits unless explicitly authorized

Do not touch:

- secrets
- credentials
- `.env` files
- VCS internals such as `.git/`
- virtualenvs
- generated artifacts as implementation
- runtime logs as implementation
- cache directories
- hard-boundary paths defined by Universe/path policy
- task state files unless task is explicitly about state/migration/control behavior

## High-risk files

| File/area | Why risky | Required care |
|---|---|---|
| `main.py` | Core run loop wiring | Run focused integration/smoke checks |
| `orchestrator.py` | Brain/planning logic | Preserve lifecycle contracts |
| `platform_core/runtime/control.py` + `control_store.py` | Shared control state (SQLite `state/control.db`) | Test pause/resume/abort/gates |
| `config.py` | Runtime config/secrets loading | Never hardcode secrets |
| `agents/executor.py` | Claude subprocess execution | Avoid destructive command changes |
| `agents/verifier.py` | Done/not-done gate | Add tests for expectation behavior |
| `agents/replanner.py` | Task list mutation | Preserve dependency/status invariants |
| `agents/adversary.py` | Review gate | Avoid silent auto-approval behavior changes |
| `state/task.py` | Task JSON schema | Update `docs/STATE.md`; consider migration |
| `memory/obsidian.py` | Persistent memory | Preserve disk fallback |
| `notifications/dashboard.py` | Live dashboard | Keep display derived from state |
| `notifications/webdash.py` | Human control surface | Test control command wiring |
| `notifications/command_bot.py` | Discord commands | Preserve owner/auth/control behavior |
| `notifications/bot/` | Nightclaw cogs/UI | Update `docs/NIGHTCLAW.md` |
| `agents/hooks.py` + `platform_core/core/identity.py`/`platform_core/core/provenance.py`/`platform_core/core/epoch.py` | Guard/path policy; prevents bad self-edits | Never weaken hard boundaries; guards are registered in `.claude/settings.json` and fail CLOSED — keep both |
| `learning/promotion.py`, `learning/finetune.py`, `learning/adapter_promotion.py` | Adapter promotion can mutate future behavior | Require eval gates; never bypass verifier/adversary/guards |

## Core invariants

- Verification must pass before a subtask is marked done.
- Retry-on-failure must include failure context.
- Dashboard state must derive from canonical state.
- ControlBus owns pause/resume/abort/approval commands.
- Obsidian/memory must not become canonical run state.
- `allowed_paths` are hints, not hard allowlists.
- `hard_boundaries` are actual forbidden paths.
- Learning/self-improvement cannot bypass verifier, adversary, guards, or configured human gates.
- Discord/Nightclaw is a control/display surface, not a second orchestrator.

## Required after touching danger zones

After changing a danger-zone file:

1. Run the narrowest focused test.
2. Run relevant integration/smoke test if available.
3. Update affected docs:
   - `LLM_MAP.md`
   - `docs/ARCHITECTURE.md`
   - `docs/STATE.md`
   - `docs/NIGHTCLAW.md`
   - `docs/TESTING.md`
4. Report remaining risk explicitly.

## Semantic safety (Epic 4 — defense-in-depth)

`platform_core/runtime/action_risk.py` classifies every executor attempt by risk tier
(read/dry_run/mutating/paid/destructive/unknown). `OrchestratorSafetyMixin._authorizeAction`
routes it: reads auto-run, mutating/paid meter against `AUTONOMY_ALLOWANCE_USD`, and
**destructive/unknown hard-block unconditionally** (even autonomous, even under
`strict_allowance`). It composes ON TOP of the existing path/regex guards
(`hooks_selfmod`, `hooks_destructive`, universe boundaries, `CORE_PROTECTED_FILES`) — never
replacing them. Escalation reuses the ControlBus `action_risk` gate via `_handleOtherGate`
(no parallel channel). Ships dark behind `SEMANTIC_SAFETY_ENABLED` (default False);
flipping it OFF is a clean revert.

## Patch warning signs

Flag the patch if it:

- changes lifecycle statuses
- changes task JSON shape
- changes ControlBus schema
- changes verifier pass/fail semantics
- weakens guard/path policy
- makes dashboard mutate canonical state
- changes executor subprocess invocation
- touches generated logs/cache/state accidentally
- changes multiple unrelated modules
- adds behavior without tests
