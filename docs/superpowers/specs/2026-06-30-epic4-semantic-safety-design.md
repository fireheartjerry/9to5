# Epic 4 — Semantic Safety (Design Spec)

**Date:** 2026-06-30 · **Status:** design only (no code changed) · **Primary steal:** #8
**Sources:** eliza `spend-allowance.ts::decideSpendAuthorization` + `interruption-decider.ts`
(MIT); supporting ideas from swarmclaw autonomy supervisor + guardian rollback (MIT),
loki-mode memory-injection sanitizer + counter-evidence (BUSL — **ideas only**), openclaw
`tool-policy.ts` (MIT), langgraph `interrupt()` HITL (MIT).
**Theme doc:** `docs/references-harvest/themes/human-loop-control-safety.md` (technique #1).
**Closes:** gap **#6 / §2.8** — path/regex safety → semantic, risk-tiered human-in-the-loop.

---

## 1. Goal

Add a **pure, side-effect-free action-risk classifier** that tags every executor action by
risk tier (`read` / `dry_run` / `mutating` / `paid` / `destructive` / `unknown`) and routes
it — auto-run reads, budget-meter mutating/paid under a bounded autonomy allowance, and
**always escalate destructive/unknown to the existing Discord human gate** — so 9TO5's safety
stops being decided by *what path an action touches* (§2.8: "Safety is path/regex, not
semantic") and starts being decided by *what the action does and how risky it is*, while
re-inserting the human the system currently removes by default.

**Gaps closed:** brief §2.8 (semantic safety + per-step human-loop, gap #6); secondary lift
to §2.7 (per-action risk audit trail) and a focused fix to §2.3's **memory-injection hole**
(retrieved lessons/Obsidian context injected raw into brain prompts).

---

## 2. Non-Goals

- **NOT removing the existing path/regex guards.** `hooks_selfmod.selfModificationGuard`,
  `hooks_destructive.blockDestructive`, universe `allowed_paths`/`hard_boundaries`, and
  `CORE_PROTECTED_FILES` `--disallowedTools` all stay exactly as they are. This epic is
  **defense-in-depth on top** — a semantic layer that composes with, never replaces, the
  syntactic boundary checks. A destructive action inside a permitted path is still risky.
- **NOT requiring a human for every step.** The default flow auto-runs reads silently and
  auto-authorizes bounded mutating/paid work. Only `destructive`/`unknown` escalate. The
  brain's auto-clarification (`llm_mixin._resolveClarifications`) keeps resolving *ambiguity*
  without a human; the new gate is a narrow *risk* escalation, not a clarification gate.
- **NOT building a new control channel.** All escalation reuses `ControlBus` gate-decision
  plumbing (`decide` / `getDecision` / `setPendingGate`) and the existing
  `_handleOtherGate` Discord surface. No new sockets, files, or polling loops.
- **NOT a sandbox/worktree isolation epic** (that is the separate tool-use-env steal #5).
  This epic governs *authorization*, not *isolation*.
- **NOT changing model/effort routing** (per `orchestration.md`).
- **NOT porting loki BUSL code.** The sanitizer is re-implemented from the *idea* only.

---

## 3. Architecture (small units + interfaces)

Four composable units. Unit (a) is the pure heart; (b)–(d) are thin consumers that wire it
into existing ownership boundaries.

### (a) Pure risk classifier + authorization decider — `platform_core/runtime/action_risk.py` (NEW)

A pure, stdlib-only module (importable by both the orchestrator process **and**
`agents/hooks.py`, which prepends repo root to `sys.path`). No IO, no clock, no env reads in
the decision functions — fully unit-testable, mirroring eliza's
`decideSpendAuthorization` (pure by contract, see `spend-allowance.ts:150`).

```python
"""Semantic action-risk classifier + authorization decider (pure)."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

class RiskTier(str, Enum):
    READ = "read"
    DRY_RUN = "dry_run"
    MUTATING = "mutating"
    PAID = "paid"
    DESTRUCTIVE = "destructive"
    UNKNOWN = "unknown"          # fail-closed sentinel — never silently proceeds

@dataclass(frozen=True)
class ActionDescriptor:
    tool_name: str               # "Bash" | "Edit" | "Write" | "MultiEdit" | ...
    command: str = ""            # bash command text (empty for file tools)
    file_path: str = ""          # edit/write target
    estimated_cost_usd: float | None = None   # cost HINT; None => unknown

@dataclass(frozen=True)
class AuthDecision:
    auto_authorize: bool
    escalate: bool               # route to ControlBus human gate
    tier: RiskTier
    reason: str                  # "non-mutating" | "within-allowance" | "over-allowance"
                                 #  | "destructive-requires-human" | "unknown-requires-human"
    metered_cost_usd: float | None

def classifyActionRisk(action: ActionDescriptor) -> RiskTier: ...
def decideAuthorization(action, *, allowance_usd, already_spent_usd,
                        autonomous: bool) -> AuthDecision: ...
```

- **`classifyActionRisk`** is a unit-testable **taxonomy**, deliberately overlapping the
  existing guards so the two never disagree:
  - `READ` — read-only Bash (reuse the negative of `hooks_selfmod._parseBashGuardInput`'s
    write detection: no redirect/`git checkout|reset|restore`/`mv|cp|rm|tee|dd|...`), pure
    file reads, no-op tools.
  - `DRY_RUN` — commands with `--dry-run`/`--check`/`--no` flags, `git status|diff|log`.
  - `MUTATING` — `Edit`/`Write`/`MultiEdit` to an in-bounds path; non-destructive writing
    Bash (the `redirect_or_git`/`write_cmd` set in `_parseBashGuardInput`).
  - `PAID` — actions that spend real money or finite quota (the Claude subprocess call
    itself is the dominant "paid" action in 9TO5; also any future MCP buy/deploy op).
  - `DESTRUCTIVE` — anything matching `hooks_destructive.DESTRUCTIVE_PATTERNS`
    (`rm -rf`, `git push --force`, `DROP TABLE`, `mkfs`, …) **or** a write/Bash whose target
    token hits a `hard_boundary`/secret (`.env` family) per `hooks_selfmod._shouldBlock`.
  - `UNKNOWN` — anything the classifier cannot confidently place. **Treated as
    `DESTRUCTIVE` for routing** (escalate), never as `READ`.
- **`decideAuthorization`** ports eliza's three-way routing exactly:
  `read|dry_run` → auto; `destructive|unknown` → **always escalate** (no cap can buy past
  it); `mutating|paid` → auto **only while** `already_spent_usd + estimated_cost < allowance`,
  else escalate (eliza `within-cap`/`over-cap`/`unknown-cost`, `spend-allowance.ts:182`).
- **Cost-hint hygiene:** like eliza's `stripSpendHints`, the `estimated_cost_usd` hint is a
  *decision-only* field on `ActionDescriptor`; it is never forwarded into the executor prompt
  or the real tool call.

**Interplay with `agents/hooks.py` PreToolUse + trajectory step events.** The classifier is
the *shared taxonomy* for two seams that already exist:
1. **Pre-execution seam (authoritative escalation)** — the orchestrator process, which is the
   only place that can durably *wait on a human* via the gate loop (§3c).
2. **Per-tool-call seam (fail-closed guard)** — `agents/hooks.py` PreToolUse runs *inside*
   the Claude subprocess and is synchronous, so it cannot block-and-wait on Discord. Its role
   is unchanged: exit-2 **block** destructive/boundary hits (fail-closed). The only change is
   that `hooks_selfmod`/`hooks_destructive` import `classifyActionRisk` so the block decision
   and the orchestrator's escalation decision derive from **one taxonomy**, and the hook
   records the resolved `tier` into the existing telemetry line (`logTelemetry` →
   `tools/claude_metrics.py`) — giving §2.7 a per-action risk audit for free. A subprocess
   tool blocked by exit-2 surfaces as a blocked attempt the orchestrator already handles.

### (b) Bounded autonomy-allowance / budget meter — `platform_core/runtime/autonomy_allowance.py` (NEW)

A thin, run-scoped ledger over `ControlBus` (NOT a parallel store), mirroring eliza's
per-session spend ledger (`spend-allowance.ts:222`) but keyed by `task_id`:

- Reads/writes a single `autonomy_spent_usd` float on the bus blank schema (one new key,
  monotonic, like `seen_discord_id`), so it survives process restart and is visible to the
  three processes that already share the bus.
- `allowance_usd` comes from a new config knob `AUTONOMY_ALLOWANCE_USD` (default `0.0` =
  **allowance disabled → confirm-everything for mutating/paid**, exactly eliza's safe
  default; operator sets a cap to grant bounded autonomy).
- `meterSpend(bus, amount_usd)` adds to the running total after an auto-authorized
  mutating/paid action commits; the natural `amount` is the executor result's `cost_usd`
  (§2.7), so the meter rides on cost the executor already captures.
- Monotonic + `max()`-merge semantics copied from eliza so a lagging read never erases spend
  already consumed (cap-bypass guard, `spend-allowance.ts:263`).

### (c) Routing into the existing ControlBus gate surface — `platform_core/orchestration/safety_mixin.py` (NEW, small)

A new orchestrator mixin owning exactly one responsibility: classify → decide → route.
It **reuses** the gate machinery; it does not reimplement it.

- Add `"action_risk"` to `control.py::GATES` (currently `("plan", "pre_pr")`) so the bus
  `decisions` dict gains an `action_risk` slot for free (forward-compatible via `_blank()`).
- `_authorizeAction(state, bus, dashboard, action: ActionDescriptor) -> bool`:
  1. `decision = decideAuthorization(action, allowance_usd=AUTONOMY_ALLOWANCE_USD,
     already_spent_usd=autonomy_allowance.spent(bus), autonomous=<mode>)`.
  2. `auto_authorize` → return `True` (and `meterSpend` if metered_cost set).
  3. `escalate` → in **gated** mode, call the existing `_handleOtherGate("action_risk", …)`
     (reuses `sendEmbed(gateNeededEmbed)`, poll loop, deadline fallback, abort handling —
     zero new control flow). On `approve` → `True`; on `reject`/timeout → `False`.
  4. `escalate` in **autonomous** mode → the fallback policy in §6 (config-gated; default
     fail-closed block). 
- **Call site:** `execute_mixin._runOneAttempt` / `_runAttemptLoop`, immediately before
  `runClaude`, classifying the action implied by the brain's invocation spec (effort/skills,
  destructive scan of `spec.prompt` via the existing `scanDestructive`, verify `cmd`). This
  is coarse-grained per-attempt authorization — the right altitude for the orchestrator,
  complementing the fine-grained per-tool-call hook guard. A blocked authorization marks the
  attempt blocked (reuse the existing `{"blocked": True}` result shape from
  `executor.runClaude`), so no new failure path is invented.

### (d) Memory-injection sanitizer — `memory/memory_sanitizer.py` (NEW, focused)

Re-implemented from the loki *idea* (`rag_injector.py::_sanitize_field`, BUSL — not copied):
a pure `sanitizeInjectedField(text, *, max_chars) -> str` that collapses every retrieved
memory field to one inline line before it enters a brain prompt — strip control chars,
collapse newlines/tabs (kills injected `###`/code-fence/instruction lines), defang leading
markdown/heading markers, per-field char cap. Applied where 9TO5 currently injects raw:
- `memory/retrieval.py` `lessons_block` rendering.
- `memory/obsidian.py` retrieved-context injection into authoring prompts.
- `plan_mixin._foldOperatorContext` / `state.activeIntents` (operator text is also untrusted
  input to the brain).

**Composition (explicit, non-duplicating):**
- **vs ControlBus:** ControlBus stays the sole owner of control commands and gate decisions.
  The safety_mixin is a *producer* of one new gate (`action_risk`) and a *consumer* of the
  existing decision API — same pattern as the `plan`/`pre_pr` gates.
- **vs universe scoping:** orthogonal axes. Universe answers "is this path in-bounds"
  (syntactic, owned by `hooks_selfmod`); action_risk answers "how risky is this action"
  (semantic). Both must pass. The classifier *reuses* the boundary/secret detection helpers
  so a path the universe would block is also classified `DESTRUCTIVE` — they never contradict.
- **vs auto-clarification:** unchanged. The brain still auto-answers executor questions to
  keep the run human-free for *ambiguity*. The risk gate re-inserts the human only for
  *risk*, and only for the two top tiers — these are disjoint concerns.

---

## 4. Data flow

```
brain invocation spec / executor tool call
        │
        ▼
ActionDescriptor(tool_name, command, file_path, estimated_cost_usd?)
        │
        ▼
classifyActionRisk(action)  ──►  RiskTier
        │
        ▼
decideAuthorization(tier, allowance_usd, already_spent_usd, autonomous)
        │
   ┌────┼─────────────────────────────┬──────────────────────────────┐
   ▼    ▼                             ▼                              ▼
 READ/DRY_RUN              MUTATING/PAID                    DESTRUCTIVE/UNKNOWN
 auto-run silently      within allowance? ──yes──► run     ALWAYS escalate
        │                      │ no                 │              │
        │                      ▼                    ▼              ▼
        │                  escalate           meterSpend(cost)  ControlBus.decide
        │                      │                    │           gate "action_risk"
        │                      └────────┬───────────┘                │
        ▼                               ▼                   ┌────────┴────────┐
   proceed                    proceed / blocked          approve            reject/timeout
                                                            │                  │
                                                            ▼                  ▼
                                                        proceed         blocked attempt
                                                                        (fail-closed)
```

Per-tool-call (inside subprocess): PreToolUse hook classifies with the **same** function;
destructive/boundary → exit-2 block (fail-closed); reads → exit-0; tier recorded to telemetry.

---

## 5. Exact file structure

### Created
| Path | Responsibility | Owner boundary |
|---|---|---|
| `platform_core/runtime/action_risk.py` | Pure taxonomy + `classifyActionRisk` + `decideAuthorization` + `ActionDescriptor`/`AuthDecision`/`RiskTier`. No IO. | new pure module (~180 ln) |
| `platform_core/runtime/autonomy_allowance.py` | Run-scoped monotonic spend ledger over `ControlBus`; `spent()`/`meterSpend()`. | thin ledger (~90 ln) |
| `platform_core/orchestration/safety_mixin.py` | `OrchestratorSafetyMixin._authorizeAction`: classify→decide→route via existing gate. | orchestrator mixin (~120 ln) |
| `memory/memory_sanitizer.py` | Pure `sanitizeInjectedField` (prompt-injection defang). | new pure module (~70 ln) |
| `tests/test_action_risk.py` | Taxonomy + decision unit tests (table-driven). | — |
| `tests/test_autonomy_allowance.py` | Ledger monotonicity / restart / cap-bypass. | — |
| `tests/test_memory_sanitizer.py` | Injection-string defang assertions. | — |

### Modified (minimal, ownership-preserving)
| Path | Change |
|---|---|
| `platform_core/runtime/control.py` | Add `"action_risk"` to `GATES`; add `autonomy_spent_usd: 0.0` to `_blank()`. (Forward-compatible — `load()` merges defaults.) |
| `platform_core/orchestration/execute_mixin.py` | One call to `self._authorizeAction(...)` before `runClaude` in the attempt loop; honor a blocked verdict via the existing `{"blocked": True}` result shape. |
| `<orchestrator class>` (mixin assembly) | Add `OrchestratorSafetyMixin` to the inheritance list (same place `OrchestratorControlMixin` is mixed in). |
| `agents/hooks_selfmod.py` / `agents/hooks_destructive.py` | Import `classifyActionRisk`; derive block decision + the recorded `tier` from it (no behavior change to what blocks; unifies taxonomy + records tier to telemetry). |
| `memory/retrieval.py`, `memory/obsidian.py`, `platform_core/orchestration/plan_mixin.py` | Route injected text through `sanitizeInjectedField`. |
| `platform_core/app_config/llm.py` (or the config facade owning safety knobs) | Add `AUTONOMY_ALLOWANCE_USD` (default `0.0`), `SEMANTIC_SAFETY_ENABLED` (default `True`), `AUTONOMOUS_DESTRUCTIVE_POLICY` (default `"block"`). |
| `AGENTS.md` | Regenerate via `python tools/repo_map.py` after new modules land. |

All new modules carry the required `@AI-MAP v1` doc header; functions `camelCase`, vars
`snake_case`, consts `ALL_CAPS`; every file ≤450 lines, every function ≤70 lines.

---

## 6. Error handling + fail-CLOSED principle

This epic's governing invariant: **an action whose risk cannot be confidently established is
escalated, never silently run.**

- `classifyActionRisk` returns `UNKNOWN` rather than guessing; `decideAuthorization` routes
  `UNKNOWN` identically to `DESTRUCTIVE` (escalate).
- The PreToolUse hooks already fail-closed on internal error (`selfModificationGuard` exits 2
  when it crashes mid-guard). The shared classifier preserves this: a classifier exception in
  the hook path → treat as `UNKNOWN` → block (exit 2).
- In the **orchestrator** path, a classifier/decider exception → treat as escalate; in
  autonomous mode that means the §6 autonomous fallback (default block), so a bug can only
  ever be *more* conservative, never auto-run something risky.
- The allowance ledger is monotonic with `max()`-merge: a failed/stale bus read can never
  *lower* spent total and re-open budget (eliza cap-bypass guard).
- **Autonomous-mode fallback (the crux):** when escalation is required but no human is
  present (`control_mode != "gated"`), `AUTONOMOUS_DESTRUCTIVE_POLICY` decides:
  - `"block"` (**default, fail-closed**) — mark the attempt blocked; the subtask fails its
    verify and flows into the normal replan/livelock machinery rather than executing an
    unreviewed destructive action.
  - `"strict_allowance"` — proceed *only* if a separate, deliberately small
    `AUTONOMOUS_DESTRUCTIVE_ALLOWANCE_USD` budget covers it AND the action is not in the hard
    `DESTRUCTIVE_PATTERNS` set (force-push/`rm -rf`/`DROP TABLE` stay blocked unconditionally).
  - This is the open question for the user (see final summary).
- Master kill switch `SEMANTIC_SAFETY_ENABLED=False` reverts to exactly today's behavior
  (path/regex guards only), so the layer is reversible per `orchestration.md`'s staging
  discipline.

---

## 7. Testing strategy

- **Pure-function unit tests dominate** (the whole reason eliza's design is the right steal).
  `tests/test_action_risk.py` is table-driven over `(ActionDescriptor, expected RiskTier)` and
  `(tier, allowance, spent, autonomous) → expected AuthDecision`, covering each taxonomy
  branch, the `within/over/unknown` cost cases, and the `UNKNOWN→escalate` fail-closed path.
  No mocks, no IO — fast, deterministic, exactly the lane in `.claude/rules/tests.md`.
- `tests/test_autonomy_allowance.py` — monotonic add, restart-rehydrate from the bus,
  `max()`-merge cap-bypass guard, allowance-disabled (`0.0`) = confirm-everything.
- `tests/test_memory_sanitizer.py` — known injection strings (`\n### SYSTEM:`, fenced
  instruction blocks, control chars) collapse to a single defanged line under the char cap.
- **Integration:** extend `tests/test_granular_controls.py` / `test_webdash_control.py` (the
  existing gate-decision suites) with an `action_risk` gate approve/reject/timeout case,
  proving reuse of the gate surface rather than a new channel.
- **Hook parity:** assert `classifyActionRisk` agrees with the legacy block decision for the
  existing `DESTRUCTIVE_PATTERNS` and boundary fixtures (no regression in what blocks).
- **Commands:** `python tools/dev.py check platform_core/runtime/action_risk.py` (and each new
  file) during edits; `python tools/dev.py fast` before handoff;
  `python tools/size_audit.py` for zero `must_split`.

---

## 8. Risks + sequencing

**Risks**
- **Over-escalation annoying the operator.** Mitigation: reads/dry-runs auto-run silently
  (the vast majority of actions); the allowance default of `0.0` means mutating/paid escalate
  *only* in gated mode, and gated mode already expects gate prompts. Tune the taxonomy so
  routine `Edit`/`Write` to in-bounds paths is `MUTATING` (auto under a set allowance), not
  `DESTRUCTIVE`. Ship behind `SEMANTIC_SAFETY_ENABLED` for staged rollout.
- **Autonomous mode with no human.** The core tension — escalation assumes a human exists,
  but 9TO5's headline mode is unattended. Addressed by the §6 fallback policy; default
  fail-closed `block` is safe but could stall a run on a legitimately-destructive-but-needed
  step (e.g. `git push --force` on a feature branch). The `strict_allowance` escape exists for
  operators who accept that risk. **This needs a user decision.**
- **Double-charging the meter** under per-attempt retries — meter on *committed* cost only
  (post-`runClaude` result), and make `meterSpend` idempotent per attempt id.
- **Classifier/guard drift.** Mitigated by the shared-taxonomy design (hooks + orchestrator
  import the same function) and the hook-parity test.
- **Sanitizer over-stripping** legitimate multi-line lessons. Mitigation: per-field cap is
  generous; sanitize only the *injected* rendering, not the stored note.

**Sequencing**
1. `action_risk.py` + its unit tests (pure, zero blast radius).
2. `memory_sanitizer.py` + tests + wire into `retrieval`/`obsidian`/`plan_mixin` (independent,
   closes the live injection hole immediately — highest safety/effort ratio).
3. `autonomy_allowance.py` + `control.py` `_blank()`/`GATES` extension + tests.
4. `safety_mixin._authorizeAction` + `execute_mixin` call site + gate integration test.
5. Hook taxonomy unification (`hooks_selfmod`/`hooks_destructive` import classifier) + parity
   test + tier telemetry.
6. `repo_map.py` regenerate, docs update (`docs/DANGER_MAP.md`, §2.8 of the brief if kept).

Steps 1–2 are self-contained wins shippable alone; 3–5 are the gate; 6 is cleanup.

---

## 9. Success criteria

- A pure `classifyActionRisk` + `decideAuthorization` exist with ≥95% branch coverage and
  zero IO, matching eliza's three-way routing (reads auto, mutating/paid metered, destructive
  always-human).
- Destructive/unknown actions in **gated** mode raise the existing Discord `action_risk` gate
  (reusing `_handleOtherGate`, no new control channel) and respect approve/reject/deadline.
- A bounded `AUTONOMY_ALLOWANCE_USD` lets mutating/paid work proceed unattended up to the cap,
  then escalates — verifiable via the bus `autonomy_spent_usd` total.
- Autonomous-mode destructive escalation has a **defined, config-gated fallback** that is
  fail-closed by default; no unreviewed action in the hard `DESTRUCTIVE_PATTERNS` set ever
  auto-runs.
- Retrieved memory / Obsidian / operator text is sanitized before entering brain prompts;
  known injection strings are defanged (the §2.3 hole closed).
- Existing path/regex guards, universe scoping, and auto-clarification are unchanged and still
  pass their suites (defense-in-depth proven additive).
- `SEMANTIC_SAFETY_ENABLED=False` is a clean revert to today's behavior.
- Zero `must_split` violations; `AGENTS.md` regenerated.

---

### Open question for the user

**In fully-autonomous mode (no human reachable), should a destructive/unknown action
hard-block (fail-closed, default) or proceed under a strict separate allowance?** The spec
defaults to `AUTONOMOUS_DESTRUCTIVE_POLICY="block"` with `DESTRUCTIVE_PATTERNS` (force-push,
`rm -rf`, `DROP TABLE`, `mkfs`) blocked *unconditionally* even under the strict-allowance
escape. Confirm whether that hard floor is acceptable, or whether you want the unattended run
to be able to self-authorize *any* destructive action within a small dollar/risk budget (and
if so, what that budget is).
