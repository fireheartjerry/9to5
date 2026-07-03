# 9TO5 Integration Report — 2026-07-02

**Branch:** `claude/feature-epic-integration-qyf8el`
**Scope:** Epic-integration gap closure (Workstream A) — Epic 5 (Agent Society) wiring, cross-epic
combined-flag testing, epic-flag test fixture consolidation.

---

## 1. Summary

All 8 formally-specced Epics (`docs/superpowers/specs/epic1..8-*-design.md`) are implemented and
merged to `main`, each gated by a config flag defaulting `False`. A prior mega-upgrade pass fixed
48 confirmed bugs but explicitly left Epic 5 (Agent Society) "full wiring out of scope," and no
existing test exercised more than one epic flag at a time. This pass closes both gaps: the Society
happy-path is now wired end-to-end, a combined-flags integration test exercises 7 epic flags
together, and the epic-flag test-pinning boilerplate is consolidated into a shared fixture.

All epic flags remain ship-dark (no defaults changed) — this is a correctness/wiring pass, not a
feature-enablement pass.

---

## 2. Bugs Found and Fixed

### 2.1 Epic 5 (Agent Society) wiring — Bugs A, B, C

**Bug A — society successes never reached a terminal status.**
`society/worker.py::_landStatus()` returned early on success, leaving the subtask permanently
`"in_progress"` (the docstring said "left for the verifier to gate up to done," but no verifier
was ever called). Downstream, `nextActionable()`/`_readySet()` only select `"pending"` subtasks, so
a successful society batch made the subtask invisible to the run loop, `_pendingCount()` kept
counting it as active, and `_livelockGuard` eventually aborted the run.

**Fix:** `WorkerAgent.run()` now calls `agents.verifier.runVerification()` (the same single-shot
verifier contract `adversary_loop.py` uses) after the executor returns, and lands `"done"` or
`"failed"` based on the result — for both outcomes, not just failure.

**Bug B — society path ignored the orchestrator's injected `run_claude`.**
`run_loop_mixin.py::_runParallelStep` called `_handleSocietyBatch(...)` without `run_fn=`, which
defaulted through to `society/worker.py::_defaultRunFn` — an unconditional import of the *real*
`agents.executor.runClaude`, bypassing `self._run_claude` (the DI seam every other execution path
uses). This silently broke orchestrator-level test doubles for the society path only.

**Fix:** `_runParallelStep` now passes `run_fn=self._run_claude` into `_handleSocietyBatch`.

**Bug C — file-disjoint scheduling seam built but never connected.**
`society/society_batch.py::handleSocietyBatch` called `coord.selectDisjointBatch(...)` without
`file_sets_fn=`, so it always fell back to `ready[:max_workers]` — no real file-disjointness
enforcement despite the coordinator's own docstring claiming it.

**Fix:** wired `file_sets_fn=parallel_safety.filesTouched` into the `selectDisjointBatch` call.

### 2.2 Planner-authored `files_touched` silently dropped at every subtask-creation site (found via the new combined-flag test)

While validating Bug C's fix under the new combined-flags test (§3), Society never actually
engaged even with `SOCIETY_ENABLED=True` and 3 ready subtasks. Root cause: **`files_touched`, the
field the planner is supposed to author so Epic 1's `safeParallelSet` and Epic 5's
`selectDisjointBatch` can schedule non-conflicting subtasks concurrently, was never forwarded from
a brain-authored plan dict into the real subtask record** at any of the 4 places subtasks get
created:

- `run_phase_mixin.py::_persistPlanSubtasks` (initial plan)
- `dual_ledger_planner.py::materializeDag` (Epic 2 dual-ledger plan)
- `run_loop_mixin.py::_backfill` (horizon-fill)
- `run_loop_replan_mixin.py::_applyReplan` (replan adds)

Each called `state.addSubtask(...)` without passing `files_touched=s.get("files_touched")`, even
though `TaskState.addSubtask()` has accepted that parameter since Epic 1c. In production this
meant `filesTouched()` always saw an empty set for every subtask, `disjoint()` always treated that
as conflicting, and `safeParallelSet`/`selectDisjointBatch` always serialized to one subtask at a
time — regardless of what a planner authored. Epic 5's Bug C fix was effectively dead code without
this.

**Fix:** all 4 call sites now forward `files_touched=<source dict>.get("files_touched")`.

---

## 3. Features Integrated

### 3.1 `pin_flags` test fixture

New factory fixture in `tests/conftest.py`:

```python
@pytest.fixture
def pin_flags(monkeypatch):
    def _pin(**flags):
        for name, value in flags.items():
            monkeypatch.setattr(config, name, value, raising=False)
    return _pin
```

Deduplicates the hand-rolled `monkeypatch.setattr(config, "FLAG", value, raising=False)` pattern.
Migrated: `test_epic2_config.py`, `test_durable_config.py`, `test_society_config.py`,
`test_solution_fork_config.py`, `test_execution_router.py`. Intentionally left alone:
`test_action_risk.py` (doesn't actually monkeypatch flags), `test_emotions.py`/`test_intuition.py`
(single-flag, low value), `test_trajectory_parallel.py` (multi-flag, not touched otherwise).

### 3.2 Combined-flags integration test

New `tests/test_epic_flags_combined.py`: turns on `STEP_RESUME_ENABLED`,
`WORKTREE_ISOLATION_ENABLED`, `COST_BUDGET_ENABLED`, `COMPACTION_ENABLED`,
`SEMANTIC_SAFETY_ENABLED`, `SOCIETY_ENABLED`, `SOLUTION_FORK_ENABLED`, and
`EXECUTION_FABRIC_ENABLED` (backend `local`) TOGETHER against a real `BuilderBrain` run in a real
git repo (needed for worktree isolation). `DUAL_LEDGER_PLANNER_ENABLED` intentionally stays off —
`BuilderBrain` doesn't emit ledger-shaped completions and extending the shared double was out of
scope. Assertions: `runFull` never raises, reaches a graceful terminal status, **at least one
subtask lands `"done"`** (the real regression guard for Bugs A/B — a run that silently failed
every subtask via crash-containment would still reach a "terminal status" under a weaker check),
and no subtask is left `pending`/`in_progress`.

Getting this test to mean anything required two supporting fixes to the shared `BuilderBrain`
simulator double (`platform_core/simulator/simulation.py`), both backward-compatible (existing
`test_simulation_advanced.py`/`test_simulator.py`/`test_builder_sim.py`/`test_chaos_sim.py` all
still pass unchanged):

- `builderRunClaude`'s path-traversal containment check compared the plan-authored absolute target
  path against the *per-attempt* `work_dir`, which becomes a worktree copy under
  `WORKTREE_ISOLATION_ENABLED` — mismatching the plan's fixed original-root paths and blocking every
  write. Now bound via `functools.partial(..., _project_root=str(work_dir))` at construction time,
  so the boundary stays pinned to the true project root regardless of which worktree an attempt
  executes in.
- `BuilderBrain._plan()` now authors `files_touched=[f"feature_{i}.py"]` per subtask so Epic 1/5's
  disjoint-scheduling seams have real data to work with (see §2.2) — without this, the combined
  test never actually exercised the Society code path at all despite `SOCIETY_ENABLED=True`.

---

## 4. Test Coverage

| File | Change |
|------|--------|
| `tests/test_society_worker.py` | Updated success-status assertion (`in_progress`→`done`); added `test_failing_verify_lands_failed` |
| `tests/test_society_coordinator.py` | Updated success-status assertion (`in_progress`→`done`) |
| `tests/test_society_off_invariance.py` | Fixed Bug-B workaround (now wires `run_fn` via `self._run_claude` like the real orchestrator); added `BLACKBOARD_DIR` tmp-dir patch (was silently writing to the real repo); added `test_handle_society_batch_enforces_file_disjointness` |
| `tests/test_epic_flags_combined.py` (new) | Combined 7-epic-flag smoke test, 2 tests |
| `tests/test_files_touched_propagation.py` (new) | Regression coverage for all 4 `files_touched` forwarding sites, 4 tests |
| `tests/test_orch_core_bugs.py` | `_FakeState.addSubtask` stub updated to accept `files_touched` (kept in sync with the production signature) |
| `tests/test_epic2_config.py`, `test_durable_config.py`, `test_society_config.py`, `test_solution_fork_config.py`, `test_execution_router.py` | Migrated to `pin_flags` |

### Verification commands and output

```
$ python -m pytest tests/test_society_worker.py tests/test_society_coordinator.py \
    tests/test_society_debate.py tests/test_society_off_invariance.py \
    tests/test_priority_scheduler.py tests/test_parallel_safety.py \
    tests/test_epic_flags_combined.py tests/test_files_touched_propagation.py \
    tests/test_dual_ledger_planner.py tests/test_builder_sim.py tests/test_chaos_sim.py \
    tests/test_simulation_advanced.py tests/test_simulator.py -q
165 passed in 12.94s
```

```
$ python -m pytest -m "not slow" -q --continue-on-collection-errors --ignore=tests/skill_gap_analysis_enhancements
5 failed, 3811 passed, 1 skipped, 269 deselected, 5 errors, 274 subtests passed in 60.59s
```

The 5 failures + 5 errors are **pre-existing and unrelated** — confirmed via `git stash` against
the pre-change baseline: `test_curriculum_adaptive_trigger.py`, `test_external_project.py`,
`test_github_pr_gate.py`, `test_skill_gap_analysis.py` (2 tests), and the
`tests/test_skill_gap_analysis_*.py` collection errors (all hardcode a Windows path
`C:\9to5\skills` that doesn't exist on this Linux checkout). Not touched by this pass; flagged as
a residual risk below.

```
$ python tools/size_audit.py
[size-audit] file thresholds: ideal <=300, acceptable <=450, must_split >450
[size-audit] must_split: 0 file(s)
[size-audit] functions must_split: 0

$ python tools/repo_map.py --check
[repo_map] up to date.
```

---

## 5. Documentation

| Document | Action |
|----------|--------|
| `docs/TESTING.md` | Added `pin_flags` fixture note and combined-flags-test tier under Tier 2 |

No `docs/DANGER_MAP.md` update needed — the Society fixes and `files_touched` propagation fix
don't touch a safety-relevant boundary.

---

## 6. Residual Risks / Known Limitations

1. **Debate/contested-resolution is fully dead code end-to-end.** `society/debate.py::runDebate`
   and `Coordinator.detectContested()` are implemented and unit-tested but have zero production
   call sites. Wiring them requires a genuine design decision (how a debate verdict maps to final
   subtask status) — out of scope for this pass, matches the original "full wiring out of scope"
   call from the mega-upgrade.
2. **Society workers never get worktree isolation**, even when `WORKTREE_ISOLATION_ENABLED=True` —
   only `_handleParallelBatch` calls `worktree.enterWorktree`. With the `files_touched` fix (§2.2),
   concurrent society workers at least won't touch overlapping files when a planner authors
   `files_touched`, but they still share one working tree with no per-worker branch/commit
   isolation. The combined-flag test asserts graceful behavior for this combination, not isolation
   correctness. Fully wiring it is a feature-sized change, not a bug fix.
3. **Pre-existing Windows-path-hardcoded test failures** (unrelated to this pass, confirmed via
   `git stash` baseline): `test_curriculum_adaptive_trigger.py`,
   `test_external_project.py::test_prepare_external_repo_mutates_request_to_work_dir`,
   `test_github_pr_gate.py::test_staging_excludes_scratch_and_python_cache_files`,
   `test_skill_gap_analysis.py` (2 tests) + all 5 `tests/test_skill_gap_analysis_*.py` files fail
   to collect (`Module not found: C:/9to5/...`). These same hardcoded-path tests also create
   literal `C:\9to5/` and `Z:/` directories as a side effect when run on a non-Windows checkout.
   Candidate targets for the fresh bug-hunt pass (Workstream B).
