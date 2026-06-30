# Epic 6 — Solution-Space Exploration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For a planner-flagged `fork_eligible` subtask only, fork N=2 (default) diverse executor branches in isolated git worktrees, run them concurrently, select a winner by execution-grounded evidence first (Epic 2 receipt) then a rubric tie-breaker, merge the winner into the canonical tree, and GC the losers — while the non-fork path stays byte-identical to today's `_runAttemptLoop`.

**Architecture:** Five small fail-open units under `platform_core/orchestration/` (`fork_policy`, `branch_runner`, `judge_panel`, `winner_merge`, `solution_space` coordinator) plus a cross-epic seam module (`fork_seams`) that wraps the Epic-1 worktree backend and Epic-2 receipt headline so every unit is testable in isolation today. `solution_space.runForked(...)` returns the exact `(spec, result, vresult, combined, passed, attempt)` 6-tuple `_runAttemptLoop` returns, so all of `_executeSubtask`'s downstream enrichment is unchanged. Each branch runs the existing `_runAttemptLoop` inside its own worktree against a **cloned** `TaskState` (so a branch's internal `recordVerify`/`updateSubtask` never clobbers the canonical state); only the judged winner's `vresult` is committed canonically via the sanctioned `state.recordVerify` path. Ships dark behind `SOLUTION_FORK_ENABLED=False`.

**Tech Stack:** Python 3.11+, stdlib `concurrent.futures.ThreadPoolExecutor`, `dataclasses`, `copy.deepcopy`; pytest (NOT bare unittest — the conftest sandbox is pytest-only); 9TO5 config facade (`config.*`), `state.task.TaskState`, `agents.verifier`.

---

## Locked decisions for this epic (CONSERVATIVE OPT-IN)

These override the broader triggers in the design spec:

- **Opt-in only.** `shouldFork` fires ONLY when the planner sets `subtask["fork_eligible"] == True`. The spec's other auto-triggers (high effort, ambiguity phrases, prior-failure escalation) are intentionally **NOT wired** — fork-as-retry is OFF.
- **Default N = 2** branches (spec said 3; the locked decision wins → `SOLUTION_FORK_N` default `2`).
- **Tight cost ceiling.** A projected `N × per-branch` spend over `SOLUTION_FORK_COST_CEILING_USD` downgrades to a single attempt before any branch spawns.
- **Ships dark.** `SOLUTION_FORK_ENABLED` default `False`.
- **Non-fork path byte-identical.** With the flag off, `_executeSubtask` takes the exact same `_runAttemptLoop` call as today (Task 12 regression guard).
- **Ownership intact.** The judge never writes status. The winner commits via the existing `state.recordVerify`. State store owns run state; `ControlBus` owns control; verifier owns verification.

---

## Prerequisites & cross-epic seams

This epic structurally depends on two epics whose modules **do not exist in the tree yet**. To let Epic 6 build and test in isolation now, all consumed interfaces are funnelled through ONE seam module (`fork_seams.py`) with fail-open fakes; production wiring activates automatically once the real modules land.

**Epic 1 — durable execution** (`docs/superpowers/specs/2026-06-30-epic1-durable-execution-design.md`):

| Interface consumed | Used by | Seam today |
|---|---|---|
| `platform_core/runtime/worktree.py`: `enterWorktree(state, tag) -> str`, `exitWorktree(path, merge=False) -> dict`, `removeWorktree(path) -> bool`, `gcOrphans(state) -> int`, `isIsolated(path) -> bool` | `branch_runner`, `winner_merge`, `solution_space` | `fork_seams.loadWorktreeBackend()` returns the real module if importable, else `NullWorktree` (enter→shared cwd, `isIsolated`→`False`) so `shouldFork` short-circuits to `False` and the linear path runs. |
| `platform_core/runtime/cost_budget.py` (headroom) | `solution_space` projected-cost gate | Until it lands, projected cost = `SOLUTION_FORK_N × SOLUTION_FORK_BRANCH_COST_ESTIMATE_USD` (config). Marked **SEAM** in Task 9. |
| `platform_core/runtime/trajectory.py` (branch spans) | `branch_runner` telemetry | Best-effort `try/except` import; absence is a no-op. Marked **SEAM** in Task 7. |

**Epic 2 — trustworthy loop** (`docs/superpowers/specs/2026-06-30-epic2-trustworthy-loop-design.md`):

| Interface consumed | Used by | Seam today |
|---|---|---|
| `agents/evidence_receipt.py` Evidence Receipt with `headline ∈ {VERIFIED, VERIFIED_WITH_GAPS, NOT_VERIFIED}` | `judge_panel` facts gate | `fork_seams.headlineFromBranch(passed, receipt)`: uses `receipt.headline` when present, else degrades to facts-only — `passed → VERIFIED_WITH_GAPS`, `not passed → NOT_VERIFIED` (spec §8 degraded mode). |
| `agents/independent_verifier.py` rubric scorer | `judge_panel` rubric | `score_with_brain` callable injected via `ForkDeps`; `None` → rubric_mean = 0 (facts-only selection, still functional). |

**Stub/seam tasks (marked SEAM):** Task 3 builds `fork_seams.py` (the whole seam). Tasks 7/9 contain explicit SEAM notes where Epic-1 trajectory/cost-budget wiring is deferred. No Epic-1/Epic-2 source is created here — when those epics land, `loadWorktreeBackend()` and `headlineFromBranch` pick them up with zero Epic-6 changes.

---

## File structure

**New files**

| Path | Responsibility |
|---|---|
| `platform_core/orchestration/fork_seams.py` | Headline constants, `WorktreeBackend` Protocol, `NullWorktree`, `loadWorktreeBackend()`, `headlineFromBranch()`, `ForkDeps` bundle. The ONLY place Epic-1/Epic-2 interfaces are named. |
| `platform_core/orchestration/fork_policy.py` | `shouldFork` (opt-in gate), `forkPlan`, `BranchSeed`/`ForkPlan` dataclasses, `DIVERSITY_ANGLES`, `EFFORT_CYCLE`. |
| `platform_core/orchestration/branch_runner.py` | `BranchResult` dataclass, `runBranches` (parallel pool + crash isolation), `_diffLines`. |
| `platform_core/orchestration/judge_panel.py` | `factsGate`, `scoreBranches`, `pickWinner`, `BranchScore`, `JudgeWeights`, `JUDGE_RUBRIC`. |
| `platform_core/orchestration/winner_merge.py` | `mergeWinner`, `reclaimLosers`, `graftRunnerUp` (flag-gated). |
| `platform_core/orchestration/solution_space.py` | thin coordinator: `forkBranchState`, `forkBranchSubtask`, `worktreeIsolated`, `runForked` (the only new symbol `execute_mixin` imports), `cleanupForkStates`. |

**Modified files** (narrow patches; public facades preserved)

| Path | Change |
|---|---|
| `platform_core/app_config/llm.py` | Add the `SOLUTION_FORK_*` + judge-weight ALL_CAPS knobs beside `MAX_SUBTASK_ATTEMPTS` (line 234). Re-exported by `config.py`'s `from platform_core.app_config.llm import *`. |
| `state/task_schema.py` | `addSubtask` gains additive `fork_eligible: bool = False` field. |
| `platform_core/orchestration/execute_mixin.py` | Extract `_runSubtaskAttempts` that branches on `fork_policy.shouldFork`; `_executeSubtask` calls it instead of `_runAttemptLoop` directly. Flag-off ⇒ same call. |
| `AGENTS.md` | Regenerate via `python tools/repo_map.py` after the new modules land. |

**Config knobs** (`platform_core/app_config/llm.py`):

```python
SOLUTION_FORK_ENABLED:              bool  = _envBool("SOLUTION_FORK_ENABLED", False)   # ships dark
SOLUTION_FORK_N:                    int   = _envInt("SOLUTION_FORK_N", 2)              # locked: default 2
SOLUTION_FORK_MAX_CONCURRENCY:      int   = _envInt("SOLUTION_FORK_MAX_CONCURRENCY", 2)
SOLUTION_FORK_COST_CEILING_USD:     float = _envFloat("SOLUTION_FORK_COST_CEILING_USD", 5.0)
SOLUTION_FORK_BRANCH_COST_ESTIMATE_USD: float = _envFloat("SOLUTION_FORK_BRANCH_COST_ESTIMATE_USD", 1.0)
SOLUTION_FORK_GRAFT_ENABLED:        bool  = _envBool("SOLUTION_FORK_GRAFT_ENABLED", False)
# Judge composite weights
W_FACT:   float = _envFloat("SOLUTION_FORK_W_FACT", 0.5)
W_RUBRIC: float = _envFloat("SOLUTION_FORK_W_RUBRIC", 0.3)
W_RISK:   float = _envFloat("SOLUTION_FORK_W_RISK", 0.15)
W_COST:   float = _envFloat("SOLUTION_FORK_W_COST", 0.05)
```

---

## Task 1: Config knobs

**Files:**
- Modify: `platform_core/app_config/llm.py:234` (insert after `MAX_SUBTASK_ATTEMPTS` block)
- Test: `tests/test_solution_fork_config.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_solution_fork_config.py
"""Epic 6 config knobs ship dark with the locked defaults."""
import config


def test_fork_ships_dark_with_locked_defaults():
    assert config.SOLUTION_FORK_ENABLED is False        # ships dark
    assert config.SOLUTION_FORK_N == 2                   # locked: default 2 branches
    assert config.SOLUTION_FORK_MAX_CONCURRENCY == 2
    assert config.SOLUTION_FORK_COST_CEILING_USD == 5.0
    assert config.SOLUTION_FORK_GRAFT_ENABLED is False


def test_judge_weights_present_and_normalized_to_one():
    total = config.W_FACT + config.W_RUBRIC + config.W_RISK + config.W_COST
    assert abs(total - 1.0) < 1e-9
    assert config.W_FACT >= config.W_RUBRIC   # facts outweigh opinion
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_solution_fork_config.py -v`
Expected: FAIL with `AttributeError: module 'config' has no attribute 'SOLUTION_FORK_ENABLED'`

- [ ] **Step 3: Add the knobs**

Insert immediately after line 235 (`MAX_SUBTASKS: int = 8 ...`) in `platform_core/app_config/llm.py`:

```python

# --- Epic 6: solution-space forking (ships dark; CONSERVATIVE OPT-IN) -----
SOLUTION_FORK_ENABLED:                   bool  = _envBool("SOLUTION_FORK_ENABLED", False)
SOLUTION_FORK_N:                         int   = _envInt("SOLUTION_FORK_N", 2)
SOLUTION_FORK_MAX_CONCURRENCY:           int   = _envInt("SOLUTION_FORK_MAX_CONCURRENCY", 2)
SOLUTION_FORK_COST_CEILING_USD:          float = _envFloat("SOLUTION_FORK_COST_CEILING_USD", 5.0)
SOLUTION_FORK_BRANCH_COST_ESTIMATE_USD:  float = _envFloat("SOLUTION_FORK_BRANCH_COST_ESTIMATE_USD", 1.0)
SOLUTION_FORK_GRAFT_ENABLED:             bool  = _envBool("SOLUTION_FORK_GRAFT_ENABLED", False)
# Judge composite weights (sum to 1.0; facts outweigh rubric opinion).
W_FACT:   float = _envFloat("SOLUTION_FORK_W_FACT", 0.5)
W_RUBRIC: float = _envFloat("SOLUTION_FORK_W_RUBRIC", 0.3)
W_RISK:   float = _envFloat("SOLUTION_FORK_W_RISK", 0.15)
W_COST:   float = _envFloat("SOLUTION_FORK_W_COST", 0.05)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_solution_fork_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add platform_core/app_config/llm.py tests/test_solution_fork_config.py
git commit -m "feat(epic6): add solution-fork config knobs (ships dark, N=2)"
```

---

## Task 2: Additive `fork_eligible` subtask field

**Files:**
- Modify: `state/task_schema.py:303-325` (`addSubtask`)
- Test: `tests/test_solution_fork_schema.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_solution_fork_schema.py
"""addSubtask carries the additive planner fork_eligible hint (default-safe)."""
from state.task import TaskState


def test_fork_eligible_defaults_false():
    state = TaskState.create("goal", 1.0)
    st = state.addSubtask("title", "desc")
    assert st["fork_eligible"] is False


def test_fork_eligible_opt_in():
    state = TaskState.create("goal", 1.0)
    st = state.addSubtask("title", "desc", fork_eligible=True)
    assert st["fork_eligible"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_solution_fork_schema.py -v`
Expected: FAIL — first test `KeyError: 'fork_eligible'`, second `TypeError: addSubtask() got an unexpected keyword argument 'fork_eligible'`

- [ ] **Step 3: Add the field**

In `state/task_schema.py`, change the `addSubtask` signature (line 303-305) and the `st` dict. New signature:

```python
    def addSubtask(self, title: str, description: str, assigned_to: str = "executor",
                   layer: int = 3, depends_on: Optional[list[str]] = None,
                   verify: Optional[dict] = None, fork_eligible: bool = False) -> dict[str, Any]:
```

Add this line to the `st` dict literal, immediately after `"verify": verify,` (line 319):

```python
            "fork_eligible": bool(fork_eligible),   # Epic 6 planner opt-in hint (default-safe)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_solution_fork_schema.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add state/task_schema.py tests/test_solution_fork_schema.py
git commit -m "feat(epic6): additive fork_eligible subtask field (default False)"
```

---

## Task 3: Cross-epic seam module (`fork_seams.py`) — SEAM

**Files:**
- Create: `platform_core/orchestration/fork_seams.py`
- Test: `tests/test_fork_seams.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fork_seams.py
"""The seam degrades fail-open when Epic 1/2 modules are absent."""
from platform_core.orchestration import fork_seams as fs


def test_headline_constants():
    assert fs.VERIFIED == "VERIFIED"
    assert fs.VERIFIED_WITH_GAPS == "VERIFIED_WITH_GAPS"
    assert fs.NOT_VERIFIED == "NOT_VERIFIED"


def test_headline_from_branch_uses_receipt_when_present():
    class R:
        headline = fs.VERIFIED
    assert fs.headlineFromBranch(False, R()) == fs.VERIFIED   # receipt wins over passed flag


def test_headline_from_branch_degrades_to_facts_only():
    assert fs.headlineFromBranch(True, None) == fs.VERIFIED_WITH_GAPS
    assert fs.headlineFromBranch(False, None) == fs.NOT_VERIFIED


def test_null_worktree_is_not_isolated():
    wt = fs.NullWorktree()
    assert wt.isIsolated("/anything") is False
    assert wt.enterWorktree(None, "sid#b0") == ""          # shared/no isolation
    assert wt.exitWorktree("/p", merge=True) == {"merged": False}
    assert wt.removeWorktree("/p") is False
    assert wt.gcOrphans(None) == 0


def test_load_backend_returns_null_when_epic1_absent():
    # Epic 1 worktree.py does not exist yet -> NullWorktree, never raises.
    backend = fs.loadWorktreeBackend()
    assert hasattr(backend, "isIsolated")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fork_seams.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'platform_core.orchestration.fork_seams'`

- [ ] **Step 3: Write the module**

```python
# platform_core/orchestration/fork_seams.py
"""Cross-epic seams for solution-space forking (Epic 6).

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  VERIFIED / VERIFIED_WITH_GAPS / NOT_VERIFIED -- Epic 2 receipt headline constants.
  headlineFromBranch(passed, receipt) -> str -- receipt headline, else facts-only degrade.
  WorktreeBackend -- Protocol for the Epic 1 worktree backend.
  NullWorktree -- fail-open backend (no isolation) used when Epic 1 is absent.
  loadWorktreeBackend() -> WorktreeBackend -- real Epic 1 module if importable, else NullWorktree.
  ForkDeps -- injection bundle the coordinator passes to the units.
DEPENDS-ON: (stdlib only)
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/test_fork_seams.py
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol, runtime_checkable

# --- Epic 2 receipt headline vocabulary ----------------------------------
VERIFIED = "VERIFIED"
VERIFIED_WITH_GAPS = "VERIFIED_WITH_GAPS"
NOT_VERIFIED = "NOT_VERIFIED"
ELIGIBLE_HEADLINES = (VERIFIED, VERIFIED_WITH_GAPS)


def headlineFromBranch(passed: bool, receipt: Any) -> str:
    """Epic 2 receipt headline when present; else degrade to facts-only (spec §8)."""
    headline = getattr(receipt, "headline", None)
    if headline in (VERIFIED, VERIFIED_WITH_GAPS, NOT_VERIFIED):
        return headline
    return VERIFIED_WITH_GAPS if passed else NOT_VERIFIED


# --- Epic 1 worktree backend Protocol ------------------------------------
@runtime_checkable
class WorktreeBackend(Protocol):
    def enterWorktree(self, state: Any, tag: str) -> str: ...
    def exitWorktree(self, path: str, merge: bool = False) -> dict: ...
    def removeWorktree(self, path: str) -> bool: ...
    def gcOrphans(self, state: Any) -> int: ...
    def isIsolated(self, path: str) -> bool: ...


class NullWorktree:
    """Fail-open backend: no isolation. Forces shouldFork -> False until Epic 1 lands."""

    def enterWorktree(self, state: Any, tag: str) -> str:
        return ""

    def exitWorktree(self, path: str, merge: bool = False) -> dict:
        return {"merged": False}

    def removeWorktree(self, path: str) -> bool:
        return False

    def gcOrphans(self, state: Any) -> int:
        return 0

    def isIsolated(self, path: str) -> bool:
        return False


def loadWorktreeBackend() -> "WorktreeBackend":
    """Return the real Epic 1 worktree module if importable, else NullWorktree (never raises)."""
    try:
        from platform_core.runtime import worktree  # type: ignore  # Epic 1
        return worktree  # module duck-types the Protocol
    except Exception:  # noqa: BLE001 -- Epic 1 absent -> degrade, never crash
        return NullWorktree()


@dataclass
class ForkDeps:
    """Everything the coordinator injects into the units (keeps them testable in isolation)."""
    worktree: "WorktreeBackend"
    run_attempt_loop: Callable                  # orchestrator._runAttemptLoop (bound)
    remediate: Optional[Callable] = None        # orchestrator._remediate (bound); None => no graft
    score_with_brain: Optional[Callable] = None  # Epic 2 rubric scorer; None => facts-only
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_fork_seams.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/fork_seams.py tests/test_fork_seams.py
git commit -m "feat(epic6): fork_seams Epic-1/Epic-2 seam (fail-open NullWorktree)"
```

---

## Task 4: Fork policy gate (`shouldFork`)

**Files:**
- Create: `platform_core/orchestration/fork_policy.py`
- Test: `tests/test_fork_policy.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fork_policy.py
"""shouldFork is opt-in: fork_eligible flag is the ONLY trigger (fork-as-retry OFF)."""
from platform_core.orchestration import fork_policy as fp


def _kwargs(**over):
    base = dict(enabled=True, projected_cost=2.0, cost_ceiling=5.0,
                worktree_isolated=True, goal_elaborated="build a multi-file feature",
                is_self_referential=False)
    base.update(over)
    return base


def test_forks_only_when_eligible_flag_set():
    assert fp.shouldFork({"fork_eligible": True}, **_kwargs()) is True
    assert fp.shouldFork({"fork_eligible": False}, **_kwargs()) is False
    assert fp.shouldFork({}, **_kwargs()) is False


def test_high_effort_alone_does_not_fork():   # fork-as-retry / auto triggers OFF
    assert fp.shouldFork({"effort_level": "xhigh"}, **_kwargs()) is False


def test_global_flag_off_never_forks():
    assert fp.shouldFork({"fork_eligible": True}, **_kwargs(enabled=False)) is False


def test_over_cost_ceiling_downgrades():
    assert fp.shouldFork({"fork_eligible": True}, **_kwargs(projected_cost=9.0)) is False


def test_no_isolation_never_forks():
    assert fp.shouldFork({"fork_eligible": True}, **_kwargs(worktree_isolated=False)) is False


def test_single_deliverable_excluded():
    assert fp.shouldFork({"fork_eligible": True},
                         **_kwargs(goal_elaborated="edit config.py")) is False


def test_self_referential_excluded():
    assert fp.shouldFork({"fork_eligible": True}, **_kwargs(is_self_referential=True)) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fork_policy.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'platform_core.orchestration.fork_policy'`

- [ ] **Step 3: Write `shouldFork`**

```python
# platform_core/orchestration/fork_policy.py
"""Fork policy: decide IF (shouldFork) and HOW (forkPlan) to fork a subtask (Epic 6).

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  shouldFork(subtask, *, enabled, projected_cost, cost_ceiling, worktree_isolated,
             goal_elaborated, is_self_referential) -> bool -- opt-in fork gate.
  forkPlan(subtask, *, n, angles) -> ForkPlan -- build N diversity seeds.
  BranchSeed -- one branch's diversity seed (effort x angle).
  ForkPlan -- {branch_seeds, n}.
  DIVERSITY_ANGLES / EFFORT_CYCLE -- ALL_CAPS default banks.
DEPENDS-ON: config, platform_core.orchestration.subtask
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/test_fork_policy.py
"""
from __future__ import annotations

from dataclasses import dataclass, field

import config
from platform_core.orchestration.subtask import _singleDeliverable

# Angle-hint bank: orthogonal approaches injected per branch (claude-code coordinator idea).
DIVERSITY_ANGLES: tuple[str, ...] = (
    "Approach A: the smallest safe change that satisfies the acceptance check.",
    "Approach B: refactor the touched code for clarity first, then satisfy the check.",
    "Approach C: test-first -- write/strengthen the check, then make it pass.",
)
# Effort spread; via config.MODEL_BY_EFFORT an effort spread is also a model spread for free.
EFFORT_CYCLE: tuple[str, ...] = ("high", "xhigh", "high")

_DOC_ONLY_MARKERS = ("doc-only", "documentation only", "typo", "readme")


def _isDocOnly(subtask: dict) -> bool:
    blob = f"{subtask.get('title', '')} {subtask.get('description', '')}".lower()
    return any(m in blob for m in _DOC_ONLY_MARKERS)


def shouldFork(subtask: dict, *, enabled: bool, projected_cost: float, cost_ceiling: float,
               worktree_isolated: bool, goal_elaborated: str, is_self_referential: bool) -> bool:
    """CONSERVATIVE OPT-IN gate. Fork only when ALL hold (fork-as-retry is OFF)."""
    if not enabled:
        return False
    if not subtask.get("fork_eligible"):       # the ONLY trigger (locked decision)
        return False
    if not worktree_isolated:                  # forking REQUIRES isolation (else clobbers peers)
        return False
    if is_self_referential:                    # never fork a self-modification run
        return False
    if projected_cost > cost_ceiling:          # tight cost ceiling -> downgrade to single attempt
        return False
    if _isDocOnly(subtask):
        return False
    if _singleDeliverable(goal_elaborated):    # mechanical single-file edit: not fork-worthy
        return False
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_fork_policy.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/fork_policy.py tests/test_fork_policy.py
git commit -m "feat(epic6): fork_policy.shouldFork opt-in gate (fork-as-retry off)"
```

---

## Task 5: Fork plan / diversity seeds (`forkPlan`)

**Files:**
- Modify: `platform_core/orchestration/fork_policy.py` (append dataclasses + `forkPlan`)
- Test: `tests/test_fork_policy_plan.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fork_policy_plan.py
"""forkPlan emits N distinct seeds spanning effort x angle."""
from platform_core.orchestration import fork_policy as fp


def test_plan_emits_n_distinct_seeds():
    plan = fp.forkPlan({"subtask_id": "st-001"}, n=2)
    assert plan.n == 2
    assert len(plan.branch_seeds) == 2
    ids = [s.branch_id for s in plan.branch_seeds]
    assert ids == ["b0", "b1"]
    # No two seeds identical on (effort, angle).
    fingerprints = {(s.effort_level, s.angle_hint) for s in plan.branch_seeds}
    assert len(fingerprints) == 2


def test_plan_seeds_carry_routed_model():
    import config
    plan = fp.forkPlan({"subtask_id": "st-001"}, n=2)
    for s in plan.branch_seeds:
        assert s.model == config.MODEL_BY_EFFORT[s.effort_level]


def test_plan_caps_at_angle_bank_but_stays_distinct():
    plan = fp.forkPlan({"subtask_id": "st-001"}, n=3)
    assert len(plan.branch_seeds) == 3
    fingerprints = {(s.effort_level, s.angle_hint) for s in plan.branch_seeds}
    assert len(fingerprints) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fork_policy_plan.py -v`
Expected: FAIL with `AttributeError: module 'platform_core.orchestration.fork_policy' has no attribute 'forkPlan'`

- [ ] **Step 3: Append the dataclasses + `forkPlan`**

Append to `platform_core/orchestration/fork_policy.py`:

```python


@dataclass
class BranchSeed:
    """One branch's diversity seed: effort (also picks the model) + an angle hint."""
    branch_id: str
    effort_level: str
    angle_hint: str
    model: str


@dataclass
class ForkPlan:
    branch_seeds: list = field(default_factory=list)
    n: int = 0


def forkPlan(subtask: dict, *, n: int, angles: tuple = DIVERSITY_ANGLES) -> ForkPlan:
    """Build N diversity seeds spanning effort x angle. Distinct by construction."""
    n = max(1, int(n))
    seeds: list = []
    for i in range(n):
        effort = EFFORT_CYCLE[i % len(EFFORT_CYCLE)]
        angle = angles[i % len(angles)]
        model = config.MODEL_BY_EFFORT.get(effort, config.PRIMARY_MODEL)
        seeds.append(BranchSeed(branch_id=f"b{i}", effort_level=effort,
                                angle_hint=angle, model=model))
    return ForkPlan(branch_seeds=seeds, n=len(seeds))
```

Note: with `n=2` the seeds are `(high, A)` and `(xhigh, B)` — distinct on both axes. With `n=3` the angles cycle `A/B/C` so all three fingerprints differ even though effort repeats `high/xhigh/high`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_fork_policy_plan.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/fork_policy.py tests/test_fork_policy_plan.py
git commit -m "feat(epic6): forkPlan builds N distinct effort x angle seeds"
```

---

## Task 6: Judge panel (facts gate → rubric → deterministic winner)

**Files:**
- Create: `platform_core/orchestration/judge_panel.py`
- Test: `tests/test_judge_panel.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_judge_panel.py
"""Facts-first selection: NOT_VERIFIED can never win; tie-break is deterministic."""
from dataclasses import dataclass

from platform_core.orchestration import judge_panel as jp
from platform_core.orchestration import fork_seams as fs


@dataclass
class FakeBranch:
    branch_id: str
    headline: str
    diff_lines: int = 10
    cost_usd: float = 1.0
    crashed: bool = False


def test_facts_gate_excludes_not_verified_and_crashed():
    branches = [
        FakeBranch("b0", fs.VERIFIED),
        FakeBranch("b1", fs.NOT_VERIFIED),
        FakeBranch("b2", fs.VERIFIED_WITH_GAPS),
        FakeBranch("b3", fs.VERIFIED, crashed=True),
    ]
    eligible = jp.factsGate(branches)
    assert {b.branch_id for b in eligible} == {"b0", "b2"}


def test_empty_eligible_returns_none_winner():
    branches = [FakeBranch("b0", fs.NOT_VERIFIED)]
    scores = jp.scoreBranches(jp.factsGate(branches), goal="g", score_with_brain=None)
    assert jp.pickWinner(scores) is None


def test_verified_beats_gapped_on_facts_alone():
    branches = [FakeBranch("b0", fs.VERIFIED_WITH_GAPS), FakeBranch("b1", fs.VERIFIED)]
    scores = jp.scoreBranches(jp.factsGate(branches), goal="g", score_with_brain=None)
    assert jp.pickWinner(scores) == "b1"


def test_smaller_diff_breaks_tie_among_equal_facts():
    branches = [FakeBranch("b0", fs.VERIFIED, diff_lines=200),
                FakeBranch("b1", fs.VERIFIED, diff_lines=20)]
    scores = jp.scoreBranches(jp.factsGate(branches), goal="g", score_with_brain=None)
    assert jp.pickWinner(scores) == "b1"


def test_tie_break_is_reproducible():
    branches = [FakeBranch("b0", fs.VERIFIED, diff_lines=50, cost_usd=2.0),
                FakeBranch("b1", fs.VERIFIED, diff_lines=50, cost_usd=2.0)]
    scores = jp.scoreBranches(jp.factsGate(branches), goal="g", score_with_brain=None)
    first = jp.pickWinner(scores)
    again = jp.pickWinner(jp.scoreBranches(jp.factsGate(branches), goal="g", score_with_brain=None))
    assert first == again == "b0"          # lowest stable branch_id is the final tiebreak


def test_rubric_is_advisory_only():
    # A VERIFIED_WITH_GAPS branch with a glowing rubric cannot beat a plain VERIFIED one.
    def glowing(goal, branch):
        return {d: 5 for d in jp.JUDGE_RUBRIC}
    branches = [FakeBranch("b0", fs.VERIFIED, diff_lines=10),
                FakeBranch("b1", fs.VERIFIED_WITH_GAPS, diff_lines=10)]
    scores = jp.scoreBranches(jp.factsGate(branches), goal="g",
                              score_with_brain=lambda g, b: glowing(g, b) if b.branch_id == "b1" else {d: 1 for d in jp.JUDGE_RUBRIC})
    assert jp.pickWinner(scores) == "b0"   # facts gate dominates rubric


def test_rubric_llm_failure_does_not_block():
    def boom(goal, branch):
        raise RuntimeError("brain down")
    branches = [FakeBranch("b0", fs.VERIFIED)]
    scores = jp.scoreBranches(jp.factsGate(branches), goal="g", score_with_brain=boom)
    assert jp.pickWinner(scores) == "b0"   # rubric_mean=0, still wins on facts
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_judge_panel.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'platform_core.orchestration.judge_panel'`

- [ ] **Step 3: Write the module**

```python
# platform_core/orchestration/judge_panel.py
"""Judge panel: facts-first selection over branch results, rubric only as a tie-fine-tuner (Epic 6).

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  factsGate(branches) -> list -- non-crashed branches whose receipt headline is eligible.
  scoreBranches(eligible, *, goal, score_with_brain, weights) -> list[BranchScore] -- composite scores.
  pickWinner(scores) -> str | None -- winning branch_id via deterministic tie-break.
  BranchScore / JudgeWeights / JUDGE_RUBRIC -- scoring records + dimension bank.
DEPENDS-ON: config, platform_core.orchestration.fork_seams
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/test_judge_panel.py
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, NamedTuple, Optional

import config
from platform_core.orchestration import fork_seams as fs

# Rubric dimensions (0-5 each); advisory weight only -- never overrides the facts gate.
JUDGE_RUBRIC: tuple[str, ...] = ("correctness", "completeness", "safety", "simplicity", "test_strength")


class JudgeWeights(NamedTuple):
    fact: float
    rubric: float
    risk: float
    cost: float


def _defaultWeights() -> JudgeWeights:
    return JudgeWeights(config.W_FACT, config.W_RUBRIC, config.W_RISK, config.W_COST)


@dataclass
class BranchScore:
    branch_id: str
    headline: str
    fact_points: float
    rubric_mean: float
    norm_diff: float
    norm_cost: float
    diff_lines: int
    cost_usd: float
    total: float


def factsGate(branches: list) -> list:
    """Keep only non-crashed branches whose Epic 2 receipt headline is eligible."""
    return [b for b in branches
            if not getattr(b, "crashed", False) and b.headline in fs.ELIGIBLE_HEADLINES]


def _factPoints(headline: str) -> float:
    return 1.0 if headline == fs.VERIFIED else 0.6   # VERIFIED_WITH_GAPS


def _rubricMean(branch, goal: str, score_with_brain: Optional[Callable]) -> float:
    """0..1 mean of the 0-5 rubric. Advisory: any failure scores 0 (never blocks)."""
    if score_with_brain is None:
        return 0.0
    try:
        verdict = score_with_brain(goal, branch) or {}
        vals = [float(verdict.get(d, 0)) for d in JUDGE_RUBRIC]
        return (sum(vals) / len(vals)) / 5.0 if vals else 0.0
    except Exception:  # noqa: BLE001 -- judge opinion is advisory; flakiness never blocks
        return 0.0


def scoreBranches(eligible: list, *, goal: str, score_with_brain: Optional[Callable] = None,
                  weights: Optional[JudgeWeights] = None) -> list[BranchScore]:
    """Composite score per eligible branch. Empty in -> empty out (caller falls back)."""
    if not eligible:
        return []
    w = weights or _defaultWeights()
    max_diff = max((getattr(b, "diff_lines", 0) for b in eligible), default=0) or 1
    max_cost = max((getattr(b, "cost_usd", 0.0) for b in eligible), default=0.0) or 1.0
    scores: list[BranchScore] = []
    for b in eligible:
        fact = _factPoints(b.headline)
        rubric = _rubricMean(b, goal, score_with_brain)
        diff_lines = int(getattr(b, "diff_lines", 0))
        cost_usd = float(getattr(b, "cost_usd", 0.0))
        norm_diff = diff_lines / max_diff
        norm_cost = cost_usd / max_cost
        total = (w.fact * fact) + (w.rubric * rubric) - (w.risk * norm_diff) - (w.cost * norm_cost)
        scores.append(BranchScore(b.branch_id, b.headline, fact, rubric, norm_diff,
                                  norm_cost, diff_lines, cost_usd, total))
    return scores


def pickWinner(scores: list[BranchScore]) -> Optional[str]:
    """Winning branch_id. Deterministic tie-break so the same outputs always pick the same winner."""
    if not scores:
        return None
    # Sort key (all ascending) -> first element wins:
    #   -total (higher better), headline rank (VERIFIED first), diff (smaller), cost (lower), id (lowest).
    def key(s: BranchScore):
        headline_rank = 0 if s.headline == fs.VERIFIED else 1
        return (-s.total, headline_rank, s.diff_lines, s.cost_usd, s.branch_id)
    return sorted(scores, key=key)[0].branch_id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_judge_panel.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/judge_panel.py tests/test_judge_panel.py
git commit -m "feat(epic6): judge_panel facts gate + advisory rubric + deterministic tie-break"
```

---

## Task 7: Parallel branch runner — SEAM (trajectory)

**Files:**
- Create: `platform_core/orchestration/branch_runner.py`
- Test: `tests/test_branch_runner.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_branch_runner.py
"""runBranches: N results, a crashing branch is excluded-not-fatal, concurrency is capped."""
import threading

from platform_core.orchestration import branch_runner as br
from platform_core.orchestration import fork_policy as fp
from platform_core.orchestration import fork_seams as fs


def _plan(n):
    return fp.forkPlan({"subtask_id": "st-001"}, n=n)


def test_runs_one_result_per_seed():
    plan = _plan(2)

    def run_one(seed):
        return br.BranchResult(branch_id=seed.branch_id, seed=seed, worktree_path=f"/wt/{seed.branch_id}",
                               spec={}, result={}, vresult={"passed": True}, combined="", passed=True,
                               headline=fs.VERIFIED, diff_lines=10, cost_usd=1.0, crashed=False)

    results = br.runBranches(plan, run_one_branch=run_one, max_concurrency=2)
    assert len(results) == 2
    assert {r.branch_id for r in results} == {"b0", "b1"}


def test_crashing_branch_marked_not_fatal():
    plan = _plan(2)

    def run_one(seed):
        if seed.branch_id == "b1":
            raise RuntimeError("branch blew up")
        return br.BranchResult(branch_id=seed.branch_id, seed=seed, worktree_path="/wt/b0",
                               spec={}, result={}, vresult={"passed": True}, combined="", passed=True,
                               headline=fs.VERIFIED, diff_lines=10, cost_usd=1.0, crashed=False)

    results = br.runBranches(plan, run_one_branch=run_one, max_concurrency=2)
    assert len(results) == 2
    crashed = [r for r in results if r.crashed]
    assert len(crashed) == 1 and crashed[0].branch_id == "b1"
    assert crashed[0].headline == fs.NOT_VERIFIED   # a crash can never be eligible


def test_concurrency_respects_cap():
    plan = _plan(3)
    active = {"now": 0, "max": 0}
    lock = threading.Lock()
    barrier_evt = threading.Event()

    def run_one(seed):
        with lock:
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
        barrier_evt.wait(0.05)
        with lock:
            active["now"] -= 1
        return br.BranchResult(branch_id=seed.branch_id, seed=seed, worktree_path="/wt",
                               spec={}, result={}, vresult={}, combined="", passed=True,
                               headline=fs.VERIFIED, diff_lines=1, cost_usd=0.0, crashed=False)

    br.runBranches(plan, run_one_branch=run_one, max_concurrency=1)
    assert active["max"] == 1   # cap honored even though plan has 3 seeds
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_branch_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'platform_core.orchestration.branch_runner'`

- [ ] **Step 3: Write the module**

```python
# platform_core/orchestration/branch_runner.py
"""Parallel branch runner: run N seed-specialized attempt loops in isolated worktrees (Epic 6).

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  BranchResult -- one branch's captured outcome (one per seed).
  runBranches(fork_plan, *, run_one_branch, max_concurrency) -> list[BranchResult] -- pool + crash isolation.
DEPENDS-ON: config, platform_core.orchestration.fork_seams
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/test_branch_runner.py
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable

import config
from platform_core.orchestration import fork_seams as fs

LOG = config.getLogger("orchestrator")


@dataclass
class BranchResult:
    branch_id: str
    seed: Any
    worktree_path: str
    spec: dict | None
    result: dict | None
    vresult: dict | None
    combined: str
    passed: bool
    headline: str
    diff_lines: int
    cost_usd: float
    crashed: bool = False
    attempt: int = 0


def _crashedResult(seed) -> BranchResult:
    """A branch that raised: excluded from judging, never strands the subtask."""
    return BranchResult(branch_id=seed.branch_id, seed=seed, worktree_path="", spec=None,
                        result=None, vresult=None, combined="", passed=False,
                        headline=fs.NOT_VERIFIED, diff_lines=0, cost_usd=0.0, crashed=True)


def runBranches(fork_plan, *, run_one_branch: Callable, max_concurrency: int) -> list:
    """Submit each seed to a bounded pool. A crashing branch is caught and marked, not fatal.

    Mirrors run_loop_mixin._handleParallelBatch crash-isolation: a per-future try/except keeps
    one blown branch from sinking the subtask (spec §6).
    SEAM: when Epic 1 trajectory.py lands, open a `branch` child span per seed here (best-effort).
    """
    seeds = fork_plan.branch_seeds
    workers = max(1, min(len(seeds), int(max_concurrency)))
    results: list = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_one_branch, seed): seed for seed in seeds}
        for fut in as_completed(futures):
            seed = futures[fut]
            try:
                results.append(fut.result())
            except Exception as e:  # noqa: BLE001 -- a crashed branch must not strand the subtask
                LOG.error("fork branch %s crashed: %s", seed.branch_id, e, exc_info=True)
                results.append(_crashedResult(seed))
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_branch_runner.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/branch_runner.py tests/test_branch_runner.py
git commit -m "feat(epic6): branch_runner parallel pool with crash isolation"
```

---

## Task 8: Branch-state / branch-subtask isolation helpers

**Files:**
- Create: `platform_core/orchestration/solution_space.py` (helpers first; coordinator in Task 9)
- Test: `tests/test_solution_space_helpers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_solution_space_helpers.py
"""Branch clones isolate writes: a branch's recordVerify never touches canonical state."""
from state.task import TaskState
from platform_core.orchestration import solution_space as ss
from platform_core.orchestration import fork_policy as fp


def test_branch_state_is_isolated_clone():
    state = TaskState.create("goal", 1.0)
    state.addSubtask("title", "desc")
    clone = ss.forkBranchState(state, "b0")
    assert clone.task_id != state.task_id          # different file -> save() can't clobber canonical
    assert "b0" in clone.task_id
    # Mutating the clone leaves the canonical state untouched.
    clone.updateSubtask(clone.subtasks[0]["subtask_id"], status="in_progress")
    assert state.subtasks[0]["status"] == "pending"


def test_branch_subtask_folds_seed():
    seed = fp.forkPlan({"subtask_id": "st-001"}, n=1).branch_seeds[0]
    base = {"subtask_id": "st-001", "title": "t", "description": "do it", "effort_level": "default"}
    branch_st = ss.forkBranchSubtask(base, seed)
    assert branch_st is not base                    # copy, not alias
    assert branch_st["effort_level"] == seed.effort_level
    assert seed.angle_hint in branch_st["description"]
    assert base["description"] == "do it"           # original untouched
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_solution_space_helpers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'platform_core.orchestration.solution_space'`

- [ ] **Step 3: Write the helpers**

```python
# platform_core/orchestration/solution_space.py
"""Solution-space fork coordinator: the ONE seam execute_mixin imports (Epic 6).

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  forkBranchState(state, branch_id) -> TaskState -- isolated clone (branch writes never touch canonical).
  forkBranchSubtask(subtask, seed) -> dict -- seed-folded subtask copy (effort + angle).
  worktreeIsolated() -> bool -- True only when the Epic 1 backend can really isolate.
  runForked(orch, state, subtask, architect_doc, exec_cwd, bus, dashboard, sid, verify_spec) -> tuple.
  cleanupForkStates(state) -- best-effort removal of throwaway branch state files.
DEPENDS-ON: config, state.task, platform_core.orchestration.fork_seams, fork_policy,
            branch_runner, judge_panel, winner_merge
SIDE-EFFECTS: writes/removes state/<task_id>__fork_<branch>.json (throwaway branch states)
RUN/TEST: python -m pytest tests/test_solution_space_helpers.py tests/test_solution_space.py
"""
from __future__ import annotations

import copy

import config
from platform_core.orchestration import fork_seams as fs
from state.task import TaskState

LOG = config.getLogger("orchestrator")

_FORK_STATE_SUFFIX = "__fork_"


def forkBranchState(state: TaskState, branch_id: str) -> TaskState:
    """Deep-copy the run state into a throwaway clone whose save() targets a branch-specific file.

    A branch runs the real _runAttemptLoop, which calls state.recordVerify/updateSubtask. Routing
    those writes to a clone keeps the canonical state pristine -- only the judged winner's vresult is
    ever committed canonically (ownership preserved, spec §3d)."""
    data = copy.deepcopy(state.data)
    data["task_id"] = f"{state.task_id}{_FORK_STATE_SUFFIX}{branch_id}"
    return TaskState(data)


def forkBranchSubtask(subtask: dict, seed) -> dict:
    """Seed-folded copy: vary effort (also varies the routed model) + inject the angle hint."""
    branch_st = copy.deepcopy(subtask)
    branch_st["effort_level"] = seed.effort_level
    angle_block = f"\n\n[FORK ANGLE — {seed.branch_id}] {seed.angle_hint}"
    branch_st["description"] = (branch_st.get("description") or "") + angle_block
    return branch_st


def worktreeIsolated() -> bool:
    """True only when the Epic 1 backend exists AND can actually isolate (NullWorktree -> False)."""
    backend = fs.loadWorktreeBackend()
    try:
        return bool(backend.isIsolated(str(config.PROJECT_ROOT)))
    except Exception:  # noqa: BLE001
        return False


def cleanupForkStates(state: TaskState) -> int:
    """Best-effort removal of throwaway branch state files for this run."""
    removed = 0
    try:
        for path in config.STATE_DIR.glob(f"{state.task_id}{_FORK_STATE_SUFFIX}*.json"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    except Exception:  # noqa: BLE001 -- cleanup never affects a committed winner
        pass
    return removed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_solution_space_helpers.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/solution_space.py tests/test_solution_space_helpers.py
git commit -m "feat(epic6): solution_space branch-state/subtask isolation helpers"
```

---

## Task 9: Winner merge + loser reclaim

**Files:**
- Create: `platform_core/orchestration/winner_merge.py`
- Test: `tests/test_winner_merge.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_winner_merge.py
"""mergeWinner lands exactly the winner; reclaimLosers removes exactly the non-winners."""
from platform_core.orchestration import winner_merge as wm
from platform_core.orchestration import branch_runner as br
from platform_core.orchestration import fork_seams as fs


class RecordingWorktree:
    def __init__(self):
        self.exited = []
        self.removed = []

    def enterWorktree(self, state, tag): return f"/wt/{tag}"
    def exitWorktree(self, path, merge=False):
        self.exited.append((path, merge)); return {"merged": merge}
    def removeWorktree(self, path):
        self.removed.append(path); return True
    def gcOrphans(self, state): return 0
    def isIsolated(self, path): return True


def _branch(bid, headline=fs.VERIFIED):
    return br.BranchResult(branch_id=bid, seed=None, worktree_path=f"/wt/{bid}", spec={},
                           result={}, vresult={"passed": True, "branch": bid}, combined="",
                           passed=True, headline=headline, diff_lines=10, cost_usd=1.0)


def test_merge_winner_exits_only_winner_with_merge_true():
    wt = RecordingWorktree()
    winner = _branch("b1")
    vres = wm.mergeWinner(winner, worktree=wt)
    assert wt.exited == [("/wt/b1", True)]
    assert vres == {"passed": True, "branch": "b1"}   # returns winner vresult for canonical commit


def test_reclaim_removes_exactly_non_winners():
    wt = RecordingWorktree()
    branches = [_branch("b0"), _branch("b1"), _branch("b2")]
    winner = branches[1]
    wm.reclaimLosers(branches, winner, worktree=wt)
    assert set(wt.removed) == {"/wt/b0", "/wt/b2"}    # winner's tree is kept (it was merged)


def test_reclaim_is_best_effort_on_failure():
    class Flaky(RecordingWorktree):
        def removeWorktree(self, path):
            raise OSError("locked")
    branches = [_branch("b0"), _branch("b1")]
    # Must not raise -- a removal failure logs and is swept later by gcOrphans (Epic 1).
    wm.reclaimLosers(branches, branches[1], worktree=Flaky())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_winner_merge.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'platform_core.orchestration.winner_merge'`

- [ ] **Step 3: Write the module (merge + reclaim; graft added in Task 11)**

```python
# platform_core/orchestration/winner_merge.py
"""Winner merge-back + loser GC + optional advisory graft (Epic 6).

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  mergeWinner(winner, *, worktree) -> dict -- exitWorktree(merge=True) the winner; return its vresult.
  reclaimLosers(branches, winner, *, worktree) -> int -- removeWorktree every non-winner (best-effort).
  graftRunnerUp(orch, state, subtask, architect_doc, exec_cwd, runner_up, *, enabled) -> None.
DEPENDS-ON: config, platform_core.orchestration.fork_seams
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/test_winner_merge.py
"""
from __future__ import annotations

import config
from platform_core.orchestration import fork_seams as fs

LOG = config.getLogger("orchestrator")


def mergeWinner(winner, *, worktree) -> dict:
    """Land the winning branch into the canonical run branch via Epic 1 exitWorktree(merge=True).

    Returns the winner's vresult so the CALLER commits status through the normal state.recordVerify
    path -- this function never writes run status (ownership preserved, spec §3d)."""
    try:
        worktree.exitWorktree(winner.worktree_path, merge=True)
    except Exception as e:  # noqa: BLE001 -- merge-conflict handling is the caller's fallback (spec §6)
        LOG.error("winner merge-back failed for %s: %s", winner.branch_id, e, exc_info=True)
        raise
    return winner.vresult or {}


def reclaimLosers(branches: list, winner, *, worktree) -> int:
    """removeWorktree every non-winner branch. Best-effort: a failure logs; gcOrphans sweeps it."""
    reclaimed = 0
    for b in branches:
        if b.branch_id == winner.branch_id or not b.worktree_path:
            continue
        try:
            if worktree.removeWorktree(b.worktree_path):
                reclaimed += 1
        except Exception as e:  # noqa: BLE001 -- straggler swept by Epic 1 gcOrphans at run-phase boundary
            LOG.warning("reclaim of loser %s failed (will be GC'd): %s", b.branch_id, e)
    return reclaimed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_winner_merge.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/winner_merge.py tests/test_winner_merge.py
git commit -m "feat(epic6): winner_merge merge-back + best-effort loser reclaim"
```

---

## Task 10: Coordinator `runForked` (fork path + single-attempt fallback) — SEAM (cost budget)

**Files:**
- Modify: `platform_core/orchestration/solution_space.py` (append `runForked` + `_runForkAttempt`)
- Test: `tests/test_solution_space.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_solution_space.py
"""runForked returns a _runAttemptLoop-shaped tuple; all-crash falls back to a single attempt."""
from state.task import TaskState
from platform_core.orchestration import solution_space as ss
from platform_core.orchestration import branch_runner as br
from platform_core.orchestration import fork_seams as fs


class FakeWorktree:
    def __init__(self): self.entered = []; self.exited = []; self.removed = []
    def enterWorktree(self, state, tag): self.entered.append(tag); return f"/wt/{tag}"
    def exitWorktree(self, path, merge=False): self.exited.append((path, merge)); return {"merged": merge}
    def removeWorktree(self, path): self.removed.append(path); return True
    def gcOrphans(self, state): return 0
    def isIsolated(self, path): return True


class FakeOrch:
    """Minimal stand-in for the execute mixin: exposes the seams runForked needs."""
    def __init__(self):
        import threading
        self._state_lock = threading.RLock()
        self.attempt_calls = []

    def _runAttemptLoop(self, state, subtask, architect_doc, exec_cwd, bus, dashboard, sid, verify_spec):
        self.attempt_calls.append(exec_cwd)
        vres = {"passed": True, "cmd": "x"}
        return ({"effort_level": "high"}, {"ok": True}, vres, "out", True, 1)


def _state():
    st = TaskState.create("build a multi-file feature", 1.0)
    st.addSubtask("title", "desc", fork_eligible=True)
    return st


def test_runforked_winner_path_returns_attempt_shaped_tuple(monkeypatch):
    state = _state()
    sub = state.subtasks[0]
    orch = FakeOrch()
    wt = FakeWorktree()
    monkeypatch.setattr(ss.fs, "loadWorktreeBackend", lambda: wt)

    # Two healthy branches, b1 VERIFIED beats b0 GAPS.
    def fake_run_branches(plan, *, run_one_branch, max_concurrency):
        out = []
        for i, seed in enumerate(plan.branch_seeds):
            run_one_branch(seed)   # exercise the real per-branch closure (enter worktree + attempt loop)
            out.append(br.BranchResult(branch_id=seed.branch_id, seed=seed,
                                       worktree_path=f"/wt/st-001#{seed.branch_id}", spec={"e": i},
                                       result={}, vresult={"passed": True, "b": seed.branch_id},
                                       combined="c", passed=True,
                                       headline=fs.VERIFIED if seed.branch_id == "b1" else fs.VERIFIED_WITH_GAPS,
                                       diff_lines=10, cost_usd=1.0, attempt=1))
        return out
    monkeypatch.setattr(ss.branch_runner, "runBranches", fake_run_branches)

    tup = ss.runForked(orch, state, sub, "ARCH", "/canonical", bus=None, dashboard=None,
                       sid="st-001", verify_spec={"cmd": "x"})
    assert isinstance(tup, tuple) and len(tup) == 6        # _runAttemptLoop shape
    spec, result, vresult, combined, passed, attempt = tup
    assert passed is True
    assert vresult["b"] == "b1"                            # the VERIFIED branch won
    assert ("/wt/st-001#b1", True) in wt.exited            # winner merged
    assert state.subtasks[0]["verify_result"]["b"] == "b1"  # canonical recordVerify = winner's vresult


def test_runforked_all_crash_falls_back_to_single_attempt(monkeypatch):
    state = _state()
    sub = state.subtasks[0]
    orch = FakeOrch()
    wt = FakeWorktree()
    monkeypatch.setattr(ss.fs, "loadWorktreeBackend", lambda: wt)

    def all_crashed(plan, *, run_one_branch, max_concurrency):
        return [br.BranchResult(branch_id=s.branch_id, seed=s, worktree_path="", spec=None,
                                result=None, vresult=None, combined="", passed=False,
                                headline=fs.NOT_VERIFIED, diff_lines=0, cost_usd=0.0, crashed=True)
                for s in plan.branch_seeds]
    monkeypatch.setattr(ss.branch_runner, "runBranches", all_crashed)

    tup = ss.runForked(orch, state, sub, "ARCH", "/canonical", bus=None, dashboard=None,
                       sid="st-001", verify_spec={"cmd": "x"})
    assert len(tup) == 6 and tup[4] is True
    assert orch.attempt_calls[-1] == "/canonical"          # fallback ran on the canonical tree
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_solution_space.py -v`
Expected: FAIL with `AttributeError: module 'platform_core.orchestration.solution_space' has no attribute 'runForked'`

- [ ] **Step 3: Append `runForked` + helpers**

Add these imports near the top of `solution_space.py` (under the existing imports):

```python
from platform_core.orchestration import fork_policy, branch_runner, judge_panel, winner_merge
```

Append to `solution_space.py`:

```python


def _singleAttempt(orch, state, subtask, architect_doc, exec_cwd, bus, dashboard, sid, verify_spec):
    """Today's linear path -- the fail-open fallback. Byte-identical to never having forked."""
    return orch._runAttemptLoop(state, subtask, architect_doc, exec_cwd, bus, dashboard, sid, verify_spec)


def _makeRunOneBranch(orch, state, subtask, architect_doc, bus, dashboard, sid, verify_spec, backend):
    """Build the per-branch closure: enter an isolated worktree, run the attempt loop on a state clone."""
    def run_one_branch(seed):
        wt_path = backend.enterWorktree(state, f"{sid}#{seed.branch_id}") or ""
        branch_state = forkBranchState(state, seed.branch_id)
        branch_subtask = forkBranchSubtask(subtask, seed)
        spec, result, vresult, combined, passed, attempt = orch._runAttemptLoop(
            branch_state, branch_subtask, architect_doc, wt_path, bus, dashboard, sid, verify_spec)
        headline = fs.headlineFromBranch(passed, (vresult or {}).get("receipt"))
        diff_lines = int((vresult or {}).get("diff_lines", 0))
        cost_usd = float((vresult or {}).get("cost_usd", 0.0))
        return branch_runner.BranchResult(
            branch_id=seed.branch_id, seed=seed, worktree_path=wt_path, spec=spec, result=result,
            vresult=vresult, combined=combined, passed=passed, headline=headline,
            diff_lines=diff_lines, cost_usd=cost_usd, attempt=attempt)
    return run_one_branch


def runForked(orch, state, subtask, architect_doc, exec_cwd, bus, dashboard, sid, verify_spec) -> tuple:
    """Fork N branches, judge, merge the winner, reclaim losers. Returns the _runAttemptLoop tuple.

    Fail-open: no eligible winner / merge failure -> a single attempt on the canonical tree, so the
    result is never worse than today's linear path (spec §6).
    SEAM: Epic 1 cost_budget headroom is approximated by SOLUTION_FORK_BRANCH_COST_ESTIMATE_USD until
    cost_budget.py lands (the shouldFork ceiling check in execute_mixin already gated the spawn)."""
    backend = fs.loadWorktreeBackend()
    plan = fork_policy.forkPlan(subtask, n=config.SOLUTION_FORK_N)
    try:
        run_one = _makeRunOneBranch(orch, state, subtask, architect_doc, bus, dashboard,
                                    sid, verify_spec, backend)
        branches = branch_runner.runBranches(
            plan, run_one_branch=run_one, max_concurrency=config.SOLUTION_FORK_MAX_CONCURRENCY)
        eligible = judge_panel.factsGate(branches)
        scores = judge_panel.scoreBranches(eligible, goal=_goalText(state),
                                           score_with_brain=None)   # SEAM: Epic 2 rubric scorer
        winner_id = judge_panel.pickWinner(scores)
        if winner_id is None:                                       # none eligible -> fallback
            return _forkFallback(orch, state, subtask, architect_doc, exec_cwd, bus, dashboard,
                                 sid, verify_spec, backend, branches, None)
        winner = next(b for b in branches if b.branch_id == winner_id)
        try:
            winner_merge.mergeWinner(winner, worktree=backend)
        except Exception:  # noqa: BLE001 -- merge conflict -> single-attempt fallback (spec §6)
            return _forkFallback(orch, state, subtask, architect_doc, exec_cwd, bus, dashboard,
                                 sid, verify_spec, backend, branches, winner)
        with orch._state_lock:
            state.recordVerify(sid, winner.vresult or {})          # winner commits via the NORMAL path
        _afterWinner(orch, state, subtask, architect_doc, exec_cwd, winner, branches, backend)
        return (winner.spec, winner.result, winner.vresult, winner.combined, winner.passed, winner.attempt)
    finally:
        cleanupForkStates(state)


def _forkFallback(orch, state, subtask, architect_doc, exec_cwd, bus, dashboard, sid, verify_spec,
                  backend, branches, winner) -> tuple:
    """Reclaim every branch tree (start clean -- never trust un-judged edits) then single-attempt."""
    try:
        for b in branches:
            if b.worktree_path:
                try:
                    backend.removeWorktree(b.worktree_path)
                except Exception:  # noqa: BLE001
                    pass
    finally:
        pass
    return _singleAttempt(orch, state, subtask, architect_doc, exec_cwd, bus, dashboard, sid, verify_spec)


def _afterWinner(orch, state, subtask, architect_doc, exec_cwd, winner, branches, backend) -> None:
    """Optional graft of the top runner-up, then reclaim losing worktrees. All best-effort."""
    try:
        runner_up = _topRunnerUp(branches, winner)
        winner_merge.graftRunnerUp(orch, state, subtask, architect_doc, exec_cwd, runner_up,
                                   enabled=config.SOLUTION_FORK_GRAFT_ENABLED)
    except Exception:  # noqa: BLE001 -- graft never rolls back a committed winner
        pass
    try:
        winner_merge.reclaimLosers(branches, winner, worktree=backend)
    except Exception:  # noqa: BLE001
        pass


def _topRunnerUp(branches: list, winner):
    """The best non-winner that was itself VERIFIED, or None."""
    candidates = [b for b in branches
                  if b.branch_id != winner.branch_id and b.headline == fs.VERIFIED]
    return candidates[0] if candidates else None


def _goalText(state: TaskState) -> str:
    return state.meta.get("goal_elaborated") or state.meta.get("goal_raw", "")
```

Note on the test: `graftRunnerUp` is referenced here but defined in Task 11. Run Task 10's test with a temporary no-op shim if executing strictly in order — OR implement Task 11 immediately after Step 3 here. To keep tasks runnable in isolation, add this minimal stub to `winner_merge.py` now (Task 11 replaces its body):

```python
def graftRunnerUp(orch, state, subtask, architect_doc, exec_cwd, runner_up, *, enabled: bool) -> None:
    """Advisory graft of the top runner-up idea (filled in Task 11)."""
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_solution_space.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/solution_space.py platform_core/orchestration/winner_merge.py tests/test_solution_space.py
git commit -m "feat(epic6): runForked coordinator with single-attempt fail-open fallback"
```

---

## Task 11: Advisory graft pass (flag-gated, default off)

**Files:**
- Modify: `platform_core/orchestration/winner_merge.py` (replace `graftRunnerUp` stub)
- Test: `tests/test_winner_merge_graft.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_winner_merge_graft.py
"""Graft is advisory: routes the runner-up idea through _remediate, gated, skipped without a runner-up."""
from platform_core.orchestration import winner_merge as wm
from platform_core.orchestration import branch_runner as br
from platform_core.orchestration import fork_seams as fs


class SpyOrch:
    def __init__(self): self.remediate_calls = []
    def _remediate(self, state, subtask, architect_doc, exec_cwd, concerns, cancel_check=None):
        self.remediate_calls.append(concerns); return {"passed": True}


def _runner_up():
    return br.BranchResult(branch_id="b0", seed=None, worktree_path="/wt/b0", spec={},
                           result={}, vresult={"diff_summary": "did X", "residual_risks": "watch Y"},
                           combined="", passed=True, headline=fs.VERIFIED, diff_lines=10, cost_usd=1.0)


def test_graft_off_is_noop():
    orch = SpyOrch()
    wm.graftRunnerUp(orch, {}, {}, "ARCH", "/cwd", _runner_up(), enabled=False)
    assert orch.remediate_calls == []


def test_graft_on_routes_runner_up_idea_through_remediate():
    orch = SpyOrch()
    wm.graftRunnerUp(orch, {}, {"subtask_id": "st-001"}, "ARCH", "/cwd", _runner_up(), enabled=True)
    assert len(orch.remediate_calls) == 1
    assert "did X" in orch.remediate_calls[0][0]


def test_graft_skipped_when_no_runner_up():
    orch = SpyOrch()
    wm.graftRunnerUp(orch, {}, {}, "ARCH", "/cwd", None, enabled=True)
    assert orch.remediate_calls == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_winner_merge_graft.py -v`
Expected: FAIL — `test_graft_on_routes_runner_up_idea_through_remediate` fails (stub is a no-op, `remediate_calls` stays empty)

- [ ] **Step 3: Replace the `graftRunnerUp` stub**

In `platform_core/orchestration/winner_merge.py`, replace the stub body with:

```python
def graftRunnerUp(orch, state, subtask, architect_doc, exec_cwd, runner_up, *, enabled: bool) -> None:
    """Advisory graft: feed the top runner-up's idea to the winner via ONE bounded _remediate pass.

    NOT a git merge of two branches -- _remediate is snapshot-guarded keep-or-revert, so a graft can
    only keep-or-improve the already-passing winner (spec §3d). Skipped when disabled or no runner-up."""
    if not enabled or runner_up is None:
        return None
    vres = runner_up.vresult or {}
    idea = (
        f"A sibling approach also PASSED and did: {vres.get('diff_summary', '(no summary)')}. "
        f"It flagged: {vres.get('residual_risks', '(none)')}. Incorporate the GOOD idea WITHOUT "
        f"breaking the passing verification."
    )
    try:
        orch._remediate(state, subtask, architect_doc, exec_cwd, [idea], cancel_check=None)
    except Exception as e:  # noqa: BLE001 -- graft is advisory; never rolls back a committed winner
        LOG.warning("runner-up graft failed (winner kept): %s", e)
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_winner_merge_graft.py tests/test_solution_space.py -v`
Expected: PASS (3 + 2 passed)

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/winner_merge.py tests/test_winner_merge_graft.py
git commit -m "feat(epic6): advisory runner-up graft via bounded _remediate (default off)"
```

---

## Task 12: Wire the fork seam into `_executeSubtask` (flag-off byte-identical)

**Files:**
- Modify: `platform_core/orchestration/execute_mixin.py:411-412` (the `_runAttemptLoop` call site)
- Test: `tests/test_execute_mixin_fork_wiring.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_execute_mixin_fork_wiring.py
"""Flag-off path is byte-identical to _runAttemptLoop; flag-on + eligible routes to runForked."""
import config
from platform_core.orchestration.execute_mixin import OrchestratorExecuteMixin


class Harness(OrchestratorExecuteMixin):
    def __init__(self):
        import threading
        self._state_lock = threading.RLock()
        self.attempt_called = False
        self.fork_called = False

    def _runAttemptLoop(self, state, subtask, architect_doc, exec_cwd, bus, dashboard, sid, verify_spec):
        self.attempt_called = True
        return ("spec", "result", {"passed": True}, "combined", True, 1)


class FakeState:
    def __init__(self, **meta):
        self.meta = {"goal_elaborated": "build a multi-file feature", "is_self_referential": False, **meta}


def test_flag_off_calls_attempt_loop_only(monkeypatch):
    monkeypatch.setattr(config, "SOLUTION_FORK_ENABLED", False)
    h = Harness()
    sub = {"subtask_id": "st-001", "fork_eligible": True}
    tup = h._runSubtaskAttempts(FakeState(), sub, "ARCH", "/cwd", None, None, "st-001", {"cmd": "x"})
    assert h.attempt_called is True and h.fork_called is False
    assert tup == ("spec", "result", {"passed": True}, "combined", True, 1)


def test_flag_on_eligible_routes_to_runforked(monkeypatch):
    monkeypatch.setattr(config, "SOLUTION_FORK_ENABLED", True)
    import platform_core.orchestration.solution_space as ss
    monkeypatch.setattr(ss, "worktreeIsolated", lambda: True)

    def fake_runforked(orch, *a, **k):
        orch.fork_called = True
        return ("fspec", "fresult", {"passed": True}, "fcombined", True, 1)
    monkeypatch.setattr(ss, "runForked", fake_runforked)

    h = Harness()
    sub = {"subtask_id": "st-001", "fork_eligible": True}
    tup = h._runSubtaskAttempts(FakeState(), sub, "ARCH", "/cwd", None, None, "st-001", {"cmd": "x"})
    assert h.fork_called is True and h.attempt_called is False
    assert tup[0] == "fspec"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_execute_mixin_fork_wiring.py -v`
Expected: FAIL with `AttributeError: 'Harness' object has no attribute '_runSubtaskAttempts'`

- [ ] **Step 3: Add `_runSubtaskAttempts` and call it from `_executeSubtask`**

In `platform_core/orchestration/execute_mixin.py`, add this method immediately before `_executeSubtask` (before line 395, after `_postSubtaskEnrich`):

```python
    def _runSubtaskAttempts(self, state: TaskState, subtask: dict, architect_doc: str,
                            exec_cwd: str, bus: "ControlBus", dashboard: "DiscordDashboard",
                            sid: str, verify_spec: "dict | None") -> tuple:
        """Fork into parallel branches when the subtask is flagged + eligible; else today's linear loop.

        Returns the SAME (spec, result, vresult, combined, passed, attempt) tuple either way, so
        _executeSubtask below is unchanged. Flag-off => byte-identical to _runAttemptLoop."""
        from platform_core.orchestration import fork_policy, solution_space
        projected = config.SOLUTION_FORK_N * config.SOLUTION_FORK_BRANCH_COST_ESTIMATE_USD
        if fork_policy.shouldFork(
                subtask,
                enabled=config.SOLUTION_FORK_ENABLED,
                projected_cost=projected,
                cost_ceiling=config.SOLUTION_FORK_COST_CEILING_USD,
                worktree_isolated=solution_space.worktreeIsolated(),
                goal_elaborated=state.meta.get("goal_elaborated") or "",
                is_self_referential=bool(state.meta.get("is_self_referential"))):
            return solution_space.runForked(self, state, subtask, architect_doc, exec_cwd,
                                            bus, dashboard, sid, verify_spec)
        return self._runAttemptLoop(state, subtask, architect_doc, exec_cwd, bus, dashboard,
                                    sid, verify_spec)
```

Then change the call in `_executeSubtask` (line 411-412) from:

```python
        spec, result, vresult, combined, passed, attempt = self._runAttemptLoop(
            state, subtask, architect_doc, exec_cwd, bus, dashboard, sid, verify_spec)
```

to:

```python
        spec, result, vresult, combined, passed, attempt = self._runSubtaskAttempts(
            state, subtask, architect_doc, exec_cwd, bus, dashboard, sid, verify_spec)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_execute_mixin_fork_wiring.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the non-fork regression guards (must stay green)**

Run: `python -m pytest tests/ -k "execute_mixin or remediation_tree_shared or resilience" -q`
Expected: PASS (existing linear-path + worktree-isolation + orphan-GC tests unchanged)

- [ ] **Step 6: Commit**

```bash
git add platform_core/orchestration/execute_mixin.py tests/test_execute_mixin_fork_wiring.py
git commit -m "feat(epic6): route _executeSubtask through fork seam (flag-off byte-identical)"
```

---

## Task 13: Size audit, repo-map regen, focused module checks

**Files:**
- Modify: `AGENTS.md` (generated)
- No new test file

- [ ] **Step 1: Run the size audit (zero must_split required)**

Run: `python tools/size_audit.py`
Expected: zero `must_split` violations. If any new module > 450 lines or any function > 70 lines, split per `.claude/rules/modularity.md` (extract a `_*.py` sub-module + re-export facade) and re-run.

- [ ] **Step 2: Focused per-file checks on the new modules**

Run:
```bash
python tools/dev.py check platform_core/orchestration/fork_seams.py
python tools/dev.py check platform_core/orchestration/fork_policy.py
python tools/dev.py check platform_core/orchestration/branch_runner.py
python tools/dev.py check platform_core/orchestration/judge_panel.py
python tools/dev.py check platform_core/orchestration/winner_merge.py
python tools/dev.py check platform_core/orchestration/solution_space.py
```
Expected: each green (lint + mapped tests).

- [ ] **Step 3: Regenerate the repo map**

Run: `python tools/repo_map.py`
Expected: `AGENTS.md` updated with the six new `platform_core/orchestration/*` rows. Do NOT hand-edit generated rows.

- [ ] **Step 4: Run the fast lane**

Run: `python tools/dev.py fast`
Expected: PASS (whole fast suite green, including the 9 new Epic-6 test files).

- [ ] **Step 5: Commit**

```bash
git add AGENTS.md
git commit -m "docs(epic6): regenerate repo map for solution-space fork modules"
```

---

## Self-Review

**1. Spec coverage** (design spec §3–§9 mapped to tasks):

- §3a fork_policy `shouldFork`/`forkPlan`/`DIVERSITY_ANGLES` → Tasks 4, 5. (Locked-decision deviation: only the `fork_eligible` trigger is wired; auto/escalation triggers intentionally omitted — documented in "Locked decisions".)
- §3b branch_runner `runBranches`/`BranchResult`/crash isolation/concurrency cap → Task 7. Quorum early-cancel: **intentionally dropped** (spec marks it optional/default-off; YAGNI under the conservative profile) — noted here so the omission is deliberate, not a gap.
- §3c judge_panel facts gate / rubric / composite / deterministic tie-break / `JUDGE_RUBRIC` → Task 6. Anti-rubber-stamp guard: dropped as YAGNI (optional, measurement-only); flagged as a deliberate omission for the success-criteria phase.
- §3d winner_merge `mergeWinner` + advisory graft → Tasks 9, 11.
- §3e `reclaimLosers` + gcOrphans seam → Task 9 (+ Epic-1 `gcOrphans` consumed via seam).
- §4 data flow / §5 file structure / config knobs → Tasks 1, 8, 10, 12.
- §5 `fork_eligible` schema field → Task 2.
- §6 error handling: branch crash excluded (Task 7), all-crash/none-eligible fallback + merge-conflict fallback (Task 10), no-isolation short-circuit (Task 4), judge-LLM failure advisory (Task 6) → covered.
- §8 prerequisites/seams → "Prerequisites & cross-epic seams" + Task 3, with SEAM notes in Tasks 7/10.
- §9 success criteria: end-to-end stubbed (Task 10), facts-first selection (Task 6), fallback byte-identical (Tasks 10/12), reclaim (Task 9), ownership intact (winner commits via `state.recordVerify` in Task 10) → covered. The "measurable win-rate lift on the golden suite" is an A/B *measurement* activity, not an implementation task — out of scope for this build plan (noted).

**2. Placeholder scan:** No TBD/TODO/"add error handling"/"similar to Task N". Every code step is complete. The one forward reference (`graftRunnerUp` used in Task 10, defined in Task 11) is resolved inline by adding an explicit no-op stub in Task 10 Step 3, then replacing it in Task 11 — so Task 10 runs green standalone. Fixed.

**3. Type consistency:**
- `BranchResult` field set is identical across Tasks 7, 9, 10, 11 (`branch_id, seed, worktree_path, spec, result, vresult, combined, passed, headline, diff_lines, cost_usd, crashed, attempt`).
- `BranchSeed` fields (`branch_id, effort_level, angle_hint, model`) consistent across Tasks 5, 8, 10.
- `headlineFromBranch(passed, receipt)` signature consistent (Tasks 3, 10).
- Judge functions: `factsGate(branches)`, `scoreBranches(eligible, *, goal, score_with_brain, weights)`, `pickWinner(scores) -> str|None` consistent across Tasks 6, 10.
- `runForked(orch, state, subtask, architect_doc, exec_cwd, bus, dashboard, sid, verify_spec)` consistent (Tasks 10, 12) and returns the 6-tuple matching `_runAttemptLoop` (verified against `execute_mixin.py:228`).
- `mergeWinner(winner, *, worktree)` and `reclaimLosers(branches, winner, *, worktree)` consistent (Tasks 9, 10).
- `graftRunnerUp(orch, state, subtask, architect_doc, exec_cwd, runner_up, *, enabled)` consistent (Tasks 10, 11).

One issue found and fixed during review: the original draft had branches running `_runAttemptLoop` against the shared `TaskState`, which would make each branch's internal `state.recordVerify` clobber the canonical state (loser overwrites winner). Resolved by `forkBranchState` (Task 8) — branches write to a throwaway clone; only the winner's `vresult` is recorded canonically in `runForked` (Task 10). The `test_runforked_winner_path` assertion (`state.subtasks[0]["verify_result"]["b"] == "b1"`) locks this in.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-30-epic6-solution-space-exploration.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
