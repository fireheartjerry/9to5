# Full-Stack Activation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One master switch (`FULL_STACK`, default ON) that activates all 8 epics + Human-Nature every session; wire Human-Nature so it actually _influences_ run decisions (not observe-only); and force the E7 self-evolution steps to run each session (bounded by the existing per-day/idle caps).

**Architecture:** A single `_fullStack()` helper in `platform_core/app_config/settings.py` becomes the _default source_ for every dark epic flag (each individual env var still overrides it). The master also raises default parallelism to 2 and picks a `worktree` execution backend so E5 Society + E6 Fork's second-order gates are satisfied. Human-Nature coupling is added as **advisory, best-effort, gated** signals at existing run-loop seams — a hard veto only _downgrades to a soft signal_, never aborts a run. E7 forcing is a throttle-bypass that keeps all spawn caps.

**Tech Stack:** Python 3.11/3.12, existing `EpicFlags`/`llm` config dataclasses, `human_nature/integration.py` API, `learning/sie.py` maintenance, pytest.

**Non-negotiable safety invariants:**

1. Every new coupling is a **no-op** when its flag is off (byte-identical run).
2. Human-Nature is **best-effort**: any exception is swallowed + logged; it can _bias/annotate_ a decision but MUST NOT block, abort, or empty a plan. A hard-veto becomes a logged soft-signal.
3. E7 forcing keeps `SELFPLAY_MAX_PER_DAY`, `CURRICULUM_AUTO_QUEUE_MAX_PER_DAY`, the idle (`activeRun`) check, and `work_launcher._spawnBlocked`.
4. The whole stack is reversible with one env: `FULL_STACK=0`.

---

## Phase 1 — Full-Stack Master Switch

### Task 1: `_fullStack()` default source + flag rewiring

**Files:**

- Modify: `platform_core/app_config/settings.py` (EpicFlags block ~60-123; add helper near top of module)
- Modify: `platform_core/app_config/llm.py` (EVOLUTION_ENABLED:250, CURRICULUM_AUTO_QUEUE_ENABLED:286, DEFAULT_PARALLELISM:328)
- Test: `tests/platform/test_full_stack_switch.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/platform/test_full_stack_switch.py
import importlib
import config as _config


def _reload(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import platform_core.app_config.settings as s
    importlib.reload(s)
    return s


def test_full_stack_on_enables_dark_epics(monkeypatch):
    monkeypatch.setenv("FULL_STACK", "1")
    for k in ("SOCIETY_ENABLED", "SOLUTION_FORK_ENABLED", "WORKTREE_ISOLATION_ENABLED",
              "EXECUTION_FABRIC_ENABLED", "DUAL_LEDGER_PLANNER_ENABLED", "HUMAN_NATURE_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    import platform_core.app_config.settings as s
    importlib.reload(s)
    cfg = s.settings().epic
    assert cfg.SOCIETY_ENABLED and cfg.SOLUTION_FORK_ENABLED
    assert cfg.WORKTREE_ISOLATION_ENABLED and cfg.EXECUTION_FABRIC_ENABLED
    assert cfg.HUMAN_NATURE_ENABLED
    assert s.settings().epic.EXECUTION_BACKEND == "worktree"


def test_full_stack_off_keeps_dark_defaults(monkeypatch):
    monkeypatch.setenv("FULL_STACK", "0")
    for k in ("SOCIETY_ENABLED", "SOLUTION_FORK_ENABLED", "EXECUTION_FABRIC_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    import platform_core.app_config.settings as s
    importlib.reload(s)
    cfg = s.settings().epic
    assert not cfg.SOCIETY_ENABLED and not cfg.SOLUTION_FORK_ENABLED
    assert not cfg.EXECUTION_FABRIC_ENABLED


def test_individual_env_overrides_master(monkeypatch):
    monkeypatch.setenv("FULL_STACK", "1")
    monkeypatch.setenv("SOCIETY_ENABLED", "0")
    import platform_core.app_config.settings as s
    importlib.reload(s)
    assert s.settings().epic.SOCIETY_ENABLED is False
```

- [ ] **Step 2: Run test — expect FAIL** (`FULL_STACK` not honored yet)

Run: `python -m pytest tests/platform/test_full_stack_switch.py -q`

- [ ] **Step 3: Add the helper + rewire flags**

In `settings.py`, near the top of the module (after imports):

```python
def _fullStack() -> bool:
    """Master switch: when on (default), every 'dark' epic flag + Human-Nature defaults ON and
    the run config (parallelism, execution backend) is set so E5/E6's second-order gates are met.
    Any individual X_ENABLED env var still overrides. Flip everything off with FULL_STACK=0."""
    return _envBool("FULL_STACK", True)
```

Then change each dark flag's default from a literal `False`/`"local"`/`1` to derive from `_fullStack()`:

```python
# EpicFlags
WORKTREE_ISOLATION_ENABLED: bool = _F(default_factory=lambda: _envBool("WORKTREE_ISOLATION_ENABLED", _fullStack()))
COST_BUDGET_ENABLED: bool = _F(default_factory=lambda: _envBool("COST_BUDGET_ENABLED", _fullStack()))
STEP_RESUME_ENABLED: bool = _F(default_factory=lambda: _envBool("STEP_RESUME_ENABLED", _fullStack()))
DUAL_LEDGER_PLANNER_ENABLED: bool = _F(default_factory=lambda: _envBool("DUAL_LEDGER_PLANNER_ENABLED", _fullStack()))
SOCIETY_ENABLED: bool = _F(default_factory=lambda: _envBool("SOCIETY_ENABLED", _fullStack()))
SOLUTION_FORK_ENABLED: bool = _F(default_factory=lambda: _envBool("SOLUTION_FORK_ENABLED", _fullStack()))
SOLUTION_FORK_GRAFT_ENABLED: bool = _F(default_factory=lambda: _envBool("SOLUTION_FORK_GRAFT_ENABLED", _fullStack()))
EXECUTION_FABRIC_ENABLED: bool = _F(default_factory=lambda: _envBool("EXECUTION_FABRIC_ENABLED", _fullStack()))
EXECUTION_BACKEND: str = _F(default_factory=lambda: os.getenv("EXECUTION_BACKEND", "worktree" if _fullStack() else "local"))
HUMAN_NATURE_ENABLED: bool = _F(default_factory=lambda: _envBool("HUMAN_NATURE_ENABLED", _fullStack()))
HN_OPINIONS_BEHAVIOR: bool = _F(default_factory=lambda: _envBool("HN_OPINIONS_BEHAVIOR", _fullStack()))
HN_EMOTIONS_BEHAVIOR: bool = _F(default_factory=lambda: _envBool("HN_EMOTIONS_BEHAVIOR", _fullStack()))
HN_INTUITION_SHORTCUT: bool = _F(default_factory=lambda: _envBool("HN_INTUITION_SHORTCUT", _fullStack()))
```

In `llm.py`: `EVOLUTION_ENABLED` and `CURRICULUM_AUTO_QUEUE_ENABLED` default to `_fullStack()` (import the helper from settings or duplicate a tiny local reader), and `DEFAULT_PARALLELISM` default `2 if _fullStack() else 1`. (Note: `_fullStack` lives in settings; llm.py may import it or read `_envBool("FULL_STACK", True)` directly — mirror whichever avoids a circular import; llm.py already imports `_envBool`.)

- [ ] **Step 4: Run test — expect PASS**
- [ ] **Step 5: Commit** `feat(config): FULL_STACK master switch defaults all epics + Human-Nature on`

---

## Phase 2 — Force E7 self-evolution each session

### Task 2: throttle bypass keeping the caps

**Files:**

- Modify: `learning/sie.py` (`run_maintenance` ~138, `weekly_due` gate ~178-180)
- Modify: `platform_core/app_config/llm.py` (add `SIE_FORCE_WEEKLY` default `_fullStack()`)
- Test: `tests/evolution/test_sie_force_weekly.py`

- [ ] **Step 1: Write the failing test** — with `SIE_FORCE_WEEKLY=1`, the weekly steps run even when the weekly window is NOT due; the per-day spawn caps are still consulted (assert `work_launcher.spawn` is gated by `activeRun`/cap, not called blindly).

```python
def test_force_weekly_runs_steps_off_window(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SIE_FORCE_WEEKLY", True)
    monkeypatch.setattr(config, "EVOLUTION_ENABLED", True)
    # patch _weekly_due -> False; assert evolve step still invoked
    ...
```

- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Implement** — in `sie.run_maintenance`, gate the weekly tier on `weekly_due or config.SIE_FORCE_WEEKLY`. Do NOT touch the inner caps (`SELFPLAY_MAX_PER_DAY`, curriculum cap, `activeRun` idle checks, `_spawnBlocked`) — they stay as the runaway guard.
- [ ] **Step 4: Run — expect PASS**
- [ ] **Step 5: Commit** `feat(sie): FULL_STACK forces weekly self-evolution each run (caps preserved)`

---

## Phase 3 — Wire Human-Nature to influence runs (advisory, best-effort)

Reference: `docs/human-nature/integration-wiring.md` (call-site checklist) + `human_nature/integration.py` API
(`route_pre_act`, `maybe_run_instinct`, `opinions.tier`, `emotions.couple`, `intuition.route`).

### Task 3: HN advisory bridge functions

**Files:**

- Modify: `platform_core/orchestration/human_nature_bridge.py` (add `preActRouting`, `midRunInstinct`, `opinionSignal` — each gated, best-effort, returning an ADVISORY value; never raising)
- Test: `tests/human_nature/test_hn_advisory_bridge.py`

- [ ] **Step 1: Failing tests** — `preActRouting(state, domain, signals)` returns `"fast"|"deliberate"` and is `"deliberate"` when `HUMAN_NATURE_ENABLED` off; `opinionSignal(...)` returns `{"tier": "...", "veto": bool}` and `{"tier":"none","veto":False}` when off; a raising faculty is swallowed to the safe default.
- [ ] **Step 2: Run — FAIL**
- [ ] **Step 3: Implement** thin best-effort wrappers over `integration.route_pre_act` / `integration.maybe_run_instinct` / `opinions.tier`, each wrapped in `try/except -> safe default` + `LOG.debug`.
- [ ] **Step 4: PASS** · **Step 5: Commit** `feat(hn): advisory best-effort bridge (pre-act/instinct/opinion)`

### Task 4: wire the advisory signals into the run loop

**Files:**

- Modify: `platform_core/orchestration/execute_mixin.py` (pre-act routing before the executor attempt → modulate effort/verify-depth; the routing result only _biases_ effort, never blocks)
- Modify: `platform_core/orchestration/plan_mixin.py` or `control_mixin._autoApprovePlan` (opinion signal → annotate/soft-reorder the plan; a `veto` is logged + recorded as a soft concern, NEVER removes all subtasks or rejects the plan)
- Modify: `run_phase_mixin.py` / stall path (mid-run instinct → surface an advisory dashboard event)
- Test: `tests/human_nature/test_hn_coupling_run_loop.py` + a run-invariance test: with HN on, a hard-veto plan STILL executes (never aborts).

- [ ] **Steps** (TDD per site): failing test → wire the single call site (guarded by the specific behavior flag) → assert the advisory effect happens AND the run is never blocked → PASS → commit each site separately:
  - `feat(hn): pre-act routing biases executor effort`
  - `feat(hn): opinion tier annotates the plan (advisory, never blocks)`
  - `feat(hn): mid-run instinct surfaces an advisory event`

### Task 5: enable the emotion/intuition couplings

**Files:**

- Modify the pre-act/effort path to consult `emotions.couple(...)` under `HN_EMOTIONS_BEHAVIOR` and `intuition.route(..., shortcut_enabled=config.HN_INTUITION_SHORTCUT)` — advisory bias only.
- Test: coupling changes the advisory value when the flag is on; no effect when off.
- [ ] TDD + commit `feat(hn): emotion/intuition couplings (advisory)`

---

## Phase 4 — Cleanup + live verification

### Task 6: dead-code + verify

- [ ] Remove or wire `platform_core/orchestration/evolution_hook.py` (`fireEvolver` has no caller). Simplest: delete the module + its test, since evolution fires via `sie._weekly_steps`. Commit `chore: remove dead evolution_hook seam`.
- [ ] Regenerate repo map: `python tools/repo_map.py`; run `python tools/size_audit.py` (must_split: 0).
- [ ] Full affected-domain suite green: `python -m pytest tests/platform tests/orchestration tests/evolution tests/human_nature tests/notifications tests/control -q`.
- [ ] **Live proof:** from an isolated worktree, `FULL_STACK=1` sim run with `--parallel 2` and a multi-deliverable goal (≥2 disjoint files). Confirm via logs/Discord: Discovery fires; Society batch engages (kind="society" bus events); Fork/worktree provisioning; Human-Nature `arm=on` + a pre-act/opinion advisory line; SIE forced weekly step at teardown. Tear down the worktree + clean Discord test messages after.

---

## Self-review notes

- Spec coverage: D1 master switch (Task 1), D3 force-E7 (Task 2), D2 HN wiring (Tasks 3-5), cleanup+verify (Task 6). ✓
- Safety: invariants 1-4 enforced per task; the run-invariance test in Task 4 is the guard that HN can never break a run.
- Risk order: Phase 1/2 mechanical first; Phase 3 (behavior-changing) last and incremental, one call-site per commit, each behind its own flag.
