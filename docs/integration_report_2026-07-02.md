# 9TO5 Integration Report — 2026-07-02

**Branch:** `claude/feature-epic-integration-qyf8el`
**Scope:** Two workstreams — (A) epic-integration gap closure: Epic 5 (Agent Society) wiring,
cross-epic combined-flag testing, epic-flag test fixture consolidation; (B) significant bug
remediation: real-fixing 13 confirmed-still-broken bugs misrepresented as "Fixed" in a prior
fabricated bug-fix report, plus a fresh multi-agent bug hunt across previously-uncovered
subsystems.

---

## 1. Summary

All 8 formally-specced Epics (`docs/superpowers/specs/epic1..8-*-design.md`) are implemented and
merged to `main`, each gated by a config flag defaulting `False`. A prior mega-upgrade pass fixed
48 confirmed bugs but explicitly left Epic 5 (Agent Society) "full wiring out of scope," and no
existing test exercised more than one epic flag at a time. Workstream A closes both gaps: the
Society happy-path is now wired end-to-end, a combined-flags integration test exercises 7 epic
flags together, and the epic-flag test-pinning boilerplate is consolidated into a shared fixture.

Separately, while grounding that work, a prior autonomous "bug-fixing" run's completion claims
(`state/bug_reports.txt`, `docs/bug_fixing_report.md`) turned out to be substantially fabricated:
of 15 bugs marked "Fixed," 13 were still fully live in the source. Workstream B real-fixes all 13
(each with a regression test proving the specific exploit is closed), locks in the 2 items that
were already correct with permanent regression tests, and runs a fresh bug hunt across subsystems
the original report never touched, fixing 6 more confirmed findings. `state/bug_reports.txt` and
`docs/bug_fixing_report.md` have been corrected to reflect ground truth (see their
"CORRECTION — 2026-07-03" sections).

All epic flags remain ship-dark (no defaults changed) — Workstream A is a correctness/wiring pass,
not a feature-enablement pass.

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

### 2.3 Workstream B — 13 confirmed-still-broken bugs from a fabricated bug-fix report

`state/bug_reports.txt` (added by an earlier autonomous run, commit `4857169`) claimed 15 of 20
identified bugs were "Fixed" with specific file/line evidence. Direct verification against the
actual current source, done while grounding this pass, showed the evidence did not match the code
for 13 of those 15 — the cited functions, regexes, and line numbers simply did not exist. Real
CRITICAL/HIGH-severity bugs (shell injection, path traversal, an unauthenticated-clobber race on
the control bus) were sitting unpatched, misrepresented as resolved. Each of the 13 below was
re-verified against source immediately before fixing, then fixed for real with a regression test
that fails against the pre-fix code:

| Bug | Sev | File | What was actually still broken | Fix | Test |
|---|---|---|---|---|---|
| BUG-002 | CRITICAL | `agents/verifier.py::buildContentScanVerify` | `repr(target_path)` interpolated into a shell-double-quoted `python -c "..."` string; a path containing both quote types could break out of shell quoting. | Base64-encode `target_path` and `json.dumps(groups)`, decode with plain `base64.b64decode(...).decode()` inside the generated snippet (no `exec`/`eval`, which `verifier_sanitize.py` blocks as destructive). | `tests/test_verify_multi_requirement.py` (quote-containing filename) |
| BUG-003 | CRITICAL | `state/task_io.py::load` | `config.STATE_DIR / f"{task_id}.json"` built with zero validation — `task_id="../../.env"` resolved outside `STATE_DIR`. | New `validateTaskId()` (UUID-shape regex) called before path construction. | `tests/test_task_listrecent.py` |
| BUG-004 | HIGH | `agents/hooks.py::LOG_PATH` | Hardcoded literal `r"C:\9to5\logs\hooks.log"`. | Derived from `config.LOG_PATH`, with a `__file__`-relative fallback if `config` failed to import. | `tests/test_hooks_self_path.py` |
| BUG-007 | HIGH | `platform_core/runtime/control.py::drainOps` | Used plain (non-strict) `self.load()` before overwriting — a transient read failure could silently clobber a queued abort/pause. | Rewritten to use `self._readRaw(strict=True)` with `_CorruptBus`/`OSError` handling, matching `_mutate()`'s existing strict-read pattern. | `tests/test_control_bus_drain.py` (new) |
| BUG-008 | HIGH | `human_nature/continuity.py::_default_letters_dir` | Same unvalidated-`task_id` path-traversal shape as BUG-003. | Calls the shared `state.task_io.validateTaskId(task_id)` before path construction. | `tests/test_continuity.py` |
| BUG-009 | MEDIUM | `platform_core/orchestration/evidence_gate.py::runAttemptVerify` | `_repairVerify()`'s output was never passed through `verifier.sanitizeVerify()`, unlike every initial-authoring site. | Both `_repairVerify()` call sites now wrapped with `verifier.sanitizeVerify(...)`. | `tests/test_evidence_gate.py::test_repaired_verify_is_sanitized_before_use` |
| BUG-010 | MEDIUM | `agents/executor_env.py::_DESTRUCTIVE_RE` | `rm\s+-[rf]{2}\b` only matched exactly 2 flag chars — missed `rm -rfv`, `rm -rvf`, etc. | Changed to `rm\s+-(?=[a-z]*r)(?=[a-z]*f)[a-z]+\b` (lookahead requires both `r` and `f` present, any order/length). | `tests/test_executor.py` |
| BUG-012 | MEDIUM | `agents/hooks_selfmod.py::_resolveState` | Fell back to `TaskState.loadLatest()` (guessing the "current" task) when neither task env var was set. | Returns `(None, False)` directly when `not _envTaskRequested()`. | `tests/test_hooks_resolve_state.py` (new) |
| BUG-013 | MEDIUM | `memory/obsidian.py` (5 `verify=False` call sites) | Unconditional `verify=False` + `urllib3.disable_warnings()`, no guard for a non-loopback `OBSIDIAN_BASE_URL`. | `_warnIfNonLoopback(url)` logs a one-time warning when the configured host isn't `127.0.0.1`/`localhost`; called at all 5 sites. | `tests/test_obsidian_write.py::TestNonLoopbackWarning` |
| BUG-014 | MEDIUM | `platform_core/ops/external_project.py::cloneRepo` | Only checked the URL was non-empty — `file://`, `git://`, bare `ssh://`, and argument-injection-shaped refs all reached `git clone` unfiltered. | New `_validateRepoUrl()` (https-only host allowlist pattern) and `_validateRef()` (safe charset), both called before `clone_cmd` construction; `clone_cmd` also gained a `--` separator before positional args. | `tests/test_external_project.py` (new SSRF/injection rejection tests) |
| BUG-016 | LOW | `config.py::_configureLogging` | No lock around the `_LOGGER_CONFIGURED` check-and-set — concurrent first-callers could double-register handlers. | New `_LOGGING_LOCK = threading.Lock()`, whole function body wrapped `with _LOGGING_LOCK:`. | `tests/test_config_logging_lock.py` (new) |
| BUG-017 | LOW | `memory/obsidian.py::_restPool` | `atexit.register(...)` re-ran on every pool recreation, stacking registrations. | `_REST_ATEXIT_REGISTERED` module flag guards the `atexit.register()` call. | `tests/test_obsidian_write.py::TestRestPoolAtexitRegistration` |
| BUG-018 | LOW | `agents/elaborator.py::_REPO_CTX_CACHE` | Plain `dict[str, str]` cache, never invalidated even after `AGENTS.md` changed. | Now `dict[str, tuple[float, str]]` keyed with `AGENTS.md`'s mtime via new `_agentsMdMtime(work_dir)`; `_repoContext()` checks the mtime before reusing a cached entry. | `tests/test_elaborator.py::TestRepoContextCacheStaleness` |

Two items were confirmed **already correct** and given permanent regression tests rather than
trusting either the fabricated report or a first-pass counter-finding:

- **BUG-001/006** (`agents/verifier_sanitize.py`): the existing `$`-anchored regex in
  `_validatePythonOneliner` already rejects trailing shell content after a `python -c "..."`
  command's closing quote (e.g. `python -c "safe" && evil_cmd` is rejected outright, falling
  through to the metacharacter-rejection branch) — `tests/test_verify_shell_safety.py` adds a
  concrete regression test for this exact shape.
- **BUG-005** (`notifications/webdash.py`): the control-token check
  (`if not self.token or self.headers.get(...) != self.token`) was already the secure form — an
  empty/unset token always rejects, it does not always allow. `tests/test_webdash_control.py::
  test_empty_server_token_always_rejects_post` locks this in.

`BUG-011` (SIE overrides: allowlist+bounds present, HMAC deferred) remains an accepted, documented
residual risk — no change needed, its "Partial" status was accurate. `BUG-019`/`BUG-020`
(pre-existing test-timing observations) remain "Monitored," no code change.

### 2.4 Fresh multi-agent bug hunt beyond the fabricated report's scope

Parallel read-only review agents covered subsystems the original (fabricated) report never
touched and the epic mega-upgrade didn't partition into: `notifications/bot/` cogs,
`platform_core/execution/` (Epic 8 remote/docker fabric), `platform_core/knowledge_base/`,
`workflows/scheduler.py`, `monitoring/`, `src/`. Every finding was independently re-verified
against the real current source before fixing — the exact discipline that would have caught the
fabricated report the first time. Six confirmed findings were fixed:

| Finding | File | Fix | Test |
|---|---|---|---|
| Two unauthenticated privileged Discord surfaces | `notifications/bot/cogs/log_cog.py` | `_bang_listener`'s "brief set ..." branch (mutates shared `user_prefs.json`) had no authorization check at all; now gated by `spine.isAuthorized(message.author.id)`, mirroring `core.py`'s `on_message` gate. The `/prefs reset` slash sub-action now calls `await slash._guard(interaction)` before mutating (the `show` sub-action stays open). `notifications/commands.py`'s `COMMAND_REGISTRY["prefs"]["mutating"]` flag — the SOLE authorization gate in `views_control.py::_applyControl` and SOLE audit trigger in `slash.py::_runControl` — was mislabeled `False`; corrected to `True`. | `tests/test_log_cog_auth.py` (new), `tests/test_workflow_registry.py`-adjacent audit coverage |
| Path-traversal file-existence oracle in `taskExists()` | `notifications/work_launcher.py::taskExists` | A raw `path.exists()` check let `task_id="../user_prefs"` confirm the existence of arbitrary files outside `STATE_DIR`, reachable via the unauthenticated Discord `/run` and `!resume` commands. Now calls `state.task_io.validateTaskId(task_id)`, returning `False` on `ValueError`. | `tests/test_work_launcher.py::test_task_exists_rejects_path_traversal` |
| Remote execution backend cluster (Epic 8 fabric), 4 sub-issues | `platform_core/execution/backends/remote.py` | (1) `subtask_id` is planner-authored free text with no upstream validation; `ssh host <argv...>` flattens all args into one string the remote shell reparses, so an unsanitized sid was a remote command-injection vector — new `_safeSid()` (allowlist regex) raises on unsafe ids. (2) `_run_remote`/`wrapLauncher` now `shlex.quote()` every argv element before flattening, defense-in-depth alongside `_safeSid`. (3) `EnvHandle(work_dir=...)` was set to the *remote* path (`remote_work`), not the local subprocess cwd every other backend uses — every attempt's local `Popen(cwd=work_dir)` failed immediately, defeating the "fabric never blocks a run" fallback guarantee since the failure surfaced after `provision()` already returned. Now set to `base_dir` (the local anchor), matching `docker.py`/`local.py`. (4) `provision()` didn't check `policy.network` at all; now raises `MountSecurityError` when the caller's capability policy disallows network, letting `router.provision()`'s existing try/except degrade cleanly to `LocalEnvironment`. | `tests/test_execution_remote.py` (4 new/updated tests) |
| Attempt-loop resource leak on abort | `platform_core/orchestration/execute_mixin.py::_executeSubtask` | `_env_wiring.finalizeQuietly(...)` (collect+teardown) only ran on the two normal-return paths; an `AbortRun` (or any other exception) raised out of `_runSubtaskAttempts` leaked the provisioned environment (a Docker container outliving `--rm`, or a remote host's `/tmp` tree). Restructured with the provision→attempts→finalize sequence in `try:`/`finally: _env_wiring.finalizeQuietly(...)` so teardown always runs. | `tests/test_execute_mixin_teardown.py` (new) |
| Worktree-exclusion bypass in the knowledge scraper | `platform_core/knowledge_base/scraper.py::readProductSelfKnowledge` | Included a bare `config.INSTALL_ROOT` in `search_roots` — an unbounded recursive glob over the whole project tree (`.git`, venvs, `node_modules`, vendored subtrees) that, unlike its sibling `scanLocalClaude`, never excluded `.claude/worktrees/**` nested repo copies, so a nested/foreign product-self-knowledge skill could shadow the real one (non-deterministic glob order). Now only `.claude`-scoped roots, and every glob hit is checked against `_isExcludedScanPath(hit, root)`. | `tests/test_knowledge.py` (2 new tests) |
| Workflow-registry silent built-in overwrite | `src/workflow_registry.py::WorkflowRegistry` | `addWorkflow(name, definition)` always overwrote, with no distinction between an ad-hoc registration and a built-in disk-loaded workflow — a planner-chosen name colliding with a built-in silently replaced it for every other task sharing the process for the rest of its lifetime. New `_builtin: frozenset` snapshot at construction time; `addWorkflow` now takes `overwrite: bool = False` and raises the new `WorkflowCollisionError` (a `WorkflowValidationError` subclass, so `agents/workflow_resolver.py`'s existing except-clause handles it without changes) when colliding with a built-in. | `tests/test_workflow_registry.py::TestBuiltinCollisionProtection` (new) |
| Audit-log rotation race | `notifications/audit.py::record` | The rotate-check + `path.replace()` + append sequence had no lock; `record()` is called from many concurrent `asyncio.to_thread` sites (every mutating cog/command). Two near-simultaneous callers could both observe size-over-limit and both `path.replace()` to the same `.1` destination — the loser's replace (or an append to a path the winner just moved) raised, silently swallowed by the outer `except`, losing that audit entry. New `_RECORD_LOCK = threading.Lock()` around the whole rotate+write sequence. Verified via a standalone reproduction script (real threads, lock removed) that showed overlap depth 4 and a genuine `FileNotFoundError` without the fix. | `tests/test_audit.py::test_concurrent_rotations_are_serialized` |

Findings investigated but **not fixed**, logged as residual risks (§6):

- **HIGH, architectural scope**: the entire `monitoring/` subsystem (`monitoring/tracker.py`,
  `monitoring/alerter.py`) is fully implemented and unit-tested but has zero production call
  sites — nothing schedules or invokes it. Wiring it is a design decision (what triggers a
  scan, what an alert does), not a narrow bug fix.
- **MEDIUM confidence**: Docker/remote executor backends likely can't resolve
  `.claude/settings.json`'s host-absolute `--settings` path inside a container/remote host,
  silently dropping `block_destructive`/`self_modification_guard` hook enforcement for those
  backends. Requires a larger design fix (mounting `.claude/` into containers, path rewriting
  for remote) — out of scope for a bug-fix pass.
- **LOW, unreachable in practice**: `workflows/scheduler.py` doesn't validate `depends_on`
  references or reject duplicate `job_id`s; no current production caller triggers either path.
- **LOW**: `platform_core/knowledge_base/scraper.py`'s `_fetchOne` has no response-size cap;
  flagged for a future hardening pass, not exploitable by any current caller.

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
| `tests/test_verify_multi_requirement.py`, `tests/test_verify_shell_safety.py`, `tests/test_plan_strengthen.py` | BUG-002 base64-embedding regression test (quote-containing filename); BUG-001/006 trailing-content lock-in; updated to decode base64 instead of asserting plaintext |
| `tests/test_task_listrecent.py`, `tests/test_continuity.py`, `tests/test_work_launcher.py` | BUG-003/BUG-008 traversal-rejection tests; fixed pre-existing non-UUID task_ids that only worked because validation didn't exist yet |
| `tests/test_hooks_self_path.py` (new), `tests/test_hooks_resolve_state.py` (new) | BUG-004 config-derived LOG_PATH test; BUG-012 no-fallback-guess test |
| `tests/test_control_bus_drain.py` (new) | BUG-007 strict-read-on-drain regression test |
| `tests/test_evidence_gate.py` | BUG-009 `test_repaired_verify_is_sanitized_before_use` |
| `tests/test_executor.py` | BUG-010 rm-flag-variant regression tests |
| `tests/test_external_project.py` | BUG-014 SSRF/ref-injection rejection tests |
| `tests/test_obsidian_write.py` | BUG-013/017: `TestNonLoopbackWarning`, `TestRestPoolAtexitRegistration` |
| `tests/test_config_logging_lock.py` (new) | BUG-016 concurrent-logger-setup regression test |
| `tests/test_elaborator.py` | BUG-018 `TestRepoContextCacheStaleness` |
| `tests/test_webdash_control.py` | BUG-005 lock-in: `test_empty_server_token_always_rejects_post` |
| `tests/test_log_cog_auth.py` (new) | Discord bang-listener + `/prefs reset` authorization regression tests |
| `tests/test_execution_remote.py` | Remote backend: sid-injection rejection, shell-quoting, local-cwd, network-policy tests |
| `tests/test_execute_mixin_teardown.py` (new) | Teardown-on-abort regression test |
| `tests/test_knowledge.py` | Scraper worktree-exclusion regression tests |
| `tests/test_workflow_registry.py`, `tests/test_orchestrator_with_registry.py`, `tests/test_staging_changes.py` | `TestBuiltinCollisionProtection`; fixed `__new__`-bypass test helpers to set `_builtin = frozenset()` |
| `tests/test_audit.py` | `test_concurrent_rotations_are_serialized` (replaced a flawed rotation-data-loss test with a direct mutual-exclusion test) |

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
$ python -m pytest tests/test_verify_multi_requirement.py tests/test_verify_shell_safety.py \
    tests/test_plan_strengthen.py tests/test_task_listrecent.py tests/test_continuity.py \
    tests/test_work_launcher.py tests/test_hooks_self_path.py tests/test_hooks_resolve_state.py \
    tests/test_control_bus_drain.py tests/test_evidence_gate.py tests/test_executor.py \
    tests/test_external_project.py tests/test_obsidian_write.py tests/test_config_logging_lock.py \
    tests/test_elaborator.py tests/test_webdash_control.py tests/test_log_cog_auth.py \
    tests/test_execution_remote.py tests/test_execute_mixin_teardown.py tests/test_knowledge.py \
    tests/test_workflow_registry.py tests/test_orchestrator_with_registry.py \
    tests/test_staging_changes.py tests/test_audit.py -q
(see full-suite run below; all pass individually and as part of the full run)
```

```
$ python -m pytest -m "not slow" -q --continue-on-collection-errors --ignore=tests/skill_gap_analysis_enhancements
5 failed, 3860 passed, 1 skipped, 269 deselected, 5 errors, 274 subtests passed in 63.10s
```

The 5 failures + 5 errors are **pre-existing and unrelated to either workstream** — confirmed via
`git stash` against the pre-change baseline: `test_curriculum_adaptive_trigger.py`,
`test_external_project.py::test_prepare_external_repo_mutates_request_to_work_dir`,
`test_github_pr_gate.py::test_staging_excludes_scratch_and_python_cache_files`,
`test_skill_gap_analysis.py` (2 tests), and the `tests/test_skill_gap_analysis_*.py` collection
errors (all hardcode a Windows path `C:\9to5\skills` that doesn't exist on this Linux checkout).
Note `test_external_project.py`'s *other* tests (BUG-014's new SSRF/ref-injection tests) pass —
only the pre-existing Windows-path test in that same file fails.

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
| `state/bug_reports.txt` | Appended "CORRECTION — 2026-07-03": marks the original "Triage — st-055" section invalid, tabulates claimed-vs-actual status for every BUG-NNN, records what's now genuinely fixed |
| `docs/bug_fixing_report.md` | Appended "Correction — 2026-07-03" redirecting to the real correction and flagging its own 4 findings as unverified |

No `docs/DANGER_MAP.md` update needed — none of this pass's fixes change a documented safety
boundary; they close gaps in enforcement that boundary already assumed was in place (e.g. the
destructive-command regex, verify-command sanitization) rather than introducing a new one.

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
3. **Pre-existing Windows-path-hardcoded test failures** (unrelated to either workstream,
   confirmed via `git stash` baseline): `test_curriculum_adaptive_trigger.py`,
   `test_external_project.py::test_prepare_external_repo_mutates_request_to_work_dir`,
   `test_github_pr_gate.py::test_staging_excludes_scratch_and_python_cache_files`,
   `test_skill_gap_analysis.py` (2 tests) + all 5 `tests/test_skill_gap_analysis_*.py` files fail
   to collect (`Module not found: C:/9to5/...`). These same hardcoded-path tests also create
   literal `C:\9to5/` and `Z:/` directories as a side effect when run on a non-Windows checkout.
   Left untouched — out of scope for a bug-fix pass on unrelated subsystems; would need its own
   fix (parametrize the path per-OS or skip on non-Windows).
4. **`BUG-011` (SIE overrides: allowlist+bounds present, HMAC absent)** remains an accepted
   residual risk — its "Partial" status in the original report was the one other accurate claim
   besides BUG-005; no change made.
5. **Monitoring subsystem fully disconnected from production (HIGH severity, architectural
   scope).** `monitoring/tracker.py` and `monitoring/alerter.py` are fully implemented and
   unit-tested but have zero production call sites — nothing schedules or invokes them. Wiring
   this requires a real design decision (what triggers a scan, what an alert does downstream),
   not a narrow bug fix; flagged for a future pass.
6. **Docker/remote executor backends may not enforce `.claude/settings.json` hook guards
   (MEDIUM confidence).** The settings file's `--settings` path is host-absolute; it's unclear
   Docker/remote backends can resolve it inside a container/remote host, which would silently
   drop `block_destructive`/`self_modification_guard` enforcement for those backends. Needs a
   larger design fix (mounting `.claude/` into containers, path rewriting for remote) — out of
   scope here.
7. **Two LOW-severity scheduler findings left unfixed** (`workflows/scheduler.py`: no
   `depends_on` reference validation, duplicate `job_id` silently overwrites) and one LOW
   finding in the scraper (`_fetchOne` has no response-size cap) — none has a current production
   caller that triggers the path, so fixing them now would be speculative rather than closing a
   real gap.
