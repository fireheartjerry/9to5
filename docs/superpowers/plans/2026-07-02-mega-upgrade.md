# Mega-Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax. Each PARTITION below is one subagent's assignment; partitions touch DISJOINT file sets so they run in parallel in the shared worktree. Fixer agents edit + run focused tests only — they do NOT run git; the orchestrator commits each partition after it returns.

**Goal:** Fix every confirmed bug, make the whole suite green + fast in both hermetic and live-`.env` environments, rewire the safety layer, add a bounded set of innovative features, and exercise nightclaw in isolation — all in worktree `worktree-mega-upgrade`.

**Architecture:** File-disjoint partitions executed by a fixer fleet (Workflow pipeline: fix → focused test). TDD where a behavior changes: write/adjust the failing test, fix, prove green. Config/test-sandbox partition (P0) lands first because every other partition's verification depends on a green, hermetic baseline.

**Tech Stack:** Python 3.11, pytest + pytest-xdist, discord.py, Ollama, ruff (F/E4/E7/E9/W6), Windows-first.

**Global rules for every partition:**
- Read the file before editing; match local style (camelCase functions, snake_case vars, ALL_CAPS constants).
- Keep public names/facades intact (re-exports must not break). No file may cross a size threshold (>450 lines split; >70-line functions split).
- No model/effort routing changes. No secrets. Preserve unrelated dirty content.
- Every code fix gets a focused test (`python tools/dev.py check <file>` or `python -m pytest tests/<t>.py -q`). Report exact pass/fail.
- Do NOT run `git`. Leave changes in the working tree.

---

## Execution order

1. **P0 (serial, first, alone):** Test sandbox + config pinning + worktree-path robustness. Unblocks a green hermetic baseline that every later partition verifies against.
2. **Wave 1 (parallel):** P1 ORCH-CORE, P2 AGENTS+HOOKS, P3 NOTIF-BOT, P4 MEMORY-LEARNING, P5 PLATFORM-RUNTIME, P6 WORKFLOWS-SOCIETY, P7 TOOLS-DEVX, P8 OPS-MONITORING.
3. **Wave 2 (parallel, features):** P9 CHAOS-SIM, P10 BOT-REPLAY + nightclaw exercise, P11 RETENTION, P12 FAILURE-AWARE-RETRIEVAL.
4. **Finalize (serial):** repo_map regen, docs, `.gitignore`, full fast+slow verify, ruff.

Between waves the orchestrator commits and re-runs the fast lane so a regression is attributable to one partition.

---

## P0 — TEST SANDBOX + CONFIG PINNING + WORKTREE ROBUSTNESS

**Why first:** worktree fast lane is 9-failed purely from path-sensitivity + `.env` flag leakage; slow lane hangs come from an un-sandboxed tunnel supervisor and prod-log FileHandler. Fixing these makes every later `dev.py fast/check` trustworthy.

**Files:**
- Modify: `config.py` (add `LOG_PATH` test-override honoring an env var; no routing change)
- Modify: `tests/conftest.py` (new autouse fixtures)
- Modify: `platform_core/core/identity.py` (resolve self-root from the file's own git toplevel; already excludes fable-rewrite/nightclaw — also exclude `.claude/worktrees`)
- Modify: `tools/repo_map.py` (scan `git ls-files` tracked set only — kills untracked-scratch trap; also fixes drift test)
- Test: `tests/test_repo_map.py`, `tests/test_identity.py`, `tests/test_identity_perf.py`, `tests/test_eval_harness.py`, `tests/test_deployment.py`, `tests/test_config_robust_env.py`, `tests/test_coherence_invariant.py`

- [ ] **Step 1 — Config-pinning autouse fixture.** In `tests/conftest.py` add an autouse fixture that snapshots then force-sets the documented test defaults regardless of the developer's `.env`, restoring after each test:

```python
@pytest.fixture(autouse=True)
def _pin_config_flags(monkeypatch):
    # Suite must pass with ANY user .env. Pin flags the suite assumes as defaults.
    import config
    for name, val in {
        "HUMAN_NATURE_ENABLED": False,
        "SEMANTIC_SAFETY_ENABLED": False,
    }.items():
        if hasattr(config, name):
            monkeypatch.setattr(config, name, val, raising=False)
```

- [ ] **Step 2 — Verify the 10 `test_integration.py::TestOffIsNoOp/TestAutonomyInit` failures pass.** Run: `python -m pytest tests/test_integration.py -q`. Expected: PASS (was 10 failed under live `.env`).

- [ ] **Step 3 — Claude-CLI spawn guard.** Add an autouse fixture mirroring `_no_real_ollama` that patches `agents.executor._resolveClaudeLauncher`/`subprocess.Popen` entry used by `runClaude` to raise unless `NINE_TO_FIVE_ALLOW_CLAUDE=1`. Confirm no test regresses: `python -m pytest tests/test_phase_3_architecture.py -q`.

- [ ] **Step 4 — Tunnel sandbox.** Add an autouse fixture that patches `notifications.tunnel.TunnelManager.start` to a no-op and blocks `notifications.tunnel_providers._spawn`. This removes the real `npx localtunnel` spawns and the supervisor-join hang. Verify: `python -m pytest tests/test_fuzz_executor.py tests/test_fuzz_brain.py -q --timeout=90`. Expected: PASS < 90s (was hanging > 300s).

- [ ] **Step 5 — Prod-log redirect.** In `config.py`, make the `9to5.log` FileHandler path honor an env override (e.g. `NINE_TO_FIVE_LOG_DIR`), and in `tests/conftest.py` set it to a tmp dir for the session. Verify `logs/9to5.log` in the worktree does NOT grow during a test run.

- [ ] **Step 6 — repo_map tracked-only.** In `tools/repo_map.py`, source the file list from `git ls-files` (tracked) rather than a filesystem walk, so untracked scratch files and nested worktrees never enter the map. Regenerate and confirm `python tools/repo_map.py --check` is clean and `tests/test_repo_map.py::TestRepoMapDrift::test_no_drift` passes.

- [ ] **Step 7 — identity worktree-robustness.** In `platform_core/core/identity.py`, exclude `.claude/worktrees` and resolve the self-code root from the git toplevel of `identity.py` itself (not a `C:\9to5` literal or cwd). Verify `python -m pytest tests/test_identity.py tests/test_identity_perf.py -q` passes from the worktree path.

- [ ] **Step 8 — Remaining path-sensitive tests.** For `test_eval_harness` (golden-goal path), `test_deployment` (normalize_work_dir absolute repo script), `test_config_robust_env`, `test_coherence_invariant`: locate the `C:\9to5`/cwd assumption and rebind to the repo root of the test file. Do NOT weaken assertions. Verify each file green.

- [ ] **Step 9 — Collection hygiene.** `tests/test_registry.py` re-exports `Test*` classes causing 50 double-collected tests — stop re-exporting test classes (import the module under test, not its test classes). `tests/test-trace-replay.py` is never collected (dash in name) — rename to `tests/test_trace_replay.py` (or underscore) so it collects; if it duplicates another trace-replay test, delete the dup. Verify `python -m pytest tests/test_registry.py -q` collects each test once.

- [ ] **Step 10 — Full hermetic fast lane.** Run `python tools/dev.py fast`. Expected: 0 failed. This is the gate for Wave 1.

---

## P1 — ORCHESTRATOR CORE

**Files (disjoint):** `llm_io.py`, `platform_core/orchestration/run_loop.py`, `platform_core/orchestration/run_loop_mixin.py`, `platform_core/orchestration/brain_io.py`, `platform_core/orchestration/control_mixin.py`; tests `tests/test_llm_io_pydantic.py`, `tests/test_brain_io_repair.py`, new `tests/test_orch_core_bugs.py`.

- [ ] **B1 `llm_io.py:~60`** — `responseText` wraps content extraction AND `_tap_brain(...)` telemetry in one try/except returning `""`. Move `_tap_brain` into its own `try/except Exception: pass` AFTER text is computed, so a telemetry/import failure can never blank a valid completion. Test: patch `_tap_brain` to raise; assert `responseText` still returns the extracted text.
- [ ] **B2 `run_loop.py:~89`** — self-ref isolation `git checkout`/`checkout -B` return code is never checked. Capture returncode; on nonzero, LOG error + Discord notice and abort self-ref prep (or fall back to `-B`), and only call `markSelfReferential(branch)` after checkout succeeds. Test: fake a failing checkout (subprocess returns rc=1); assert `markSelfReferential` NOT called and prep aborts.
- [ ] **B3 `run_loop_mixin.py:~217`** — parallel abort calls `exitWorktree` in the finally for still-running futures. Defer `exitWorktree` for futures where `not f.done()` until after the pool has shut down. Test: two futures, one still "running" (event-gated); assert its worktree exit runs only after pool join.
- [ ] **B4 `run_loop_mixin.py:~375`** — `_applyReplan` does `(add.get("title") or "untitled").strip()`, crashing on a non-string truthy title (7B emits ints/dicts). Coerce: `raw = add.get("title"); title = (raw if isinstance(raw, str) else "untitled").strip() or "untitled"`. Test: replan add with `title=5` and `title={"x":1}`; assert no raise and remaining adds/removes still applied.
- [ ] **B5 `brain_io.py:~26`** — `_fitUserToCtx` returns the FULL user payload when `budget <= 0` (system prompt alone exceeds window). Return a bounded tail slice (e.g. last `max(512, budget_floor)` chars) + LOG a warning; unify the chars/token constant with `compaction._approxTokens` (pick one, reference it). Test: system longer than window → returned user is trimmed, not full.
- [ ] **B6 `control_mixin.py:~359`** — `_worthGptReview` reads/writes `self._last_review_hash` unlocked and before the review runs. Make dedup per-sid (key hash by subtask id) under a small lock; only store the hash after a successful review. Test: two sids with same output don't dedup each other; a failed review doesn't suppress the next identical output.
- [ ] **Verify:** `python tools/dev.py check platform_core/orchestration/run_loop_mixin.py` + `python -m pytest tests/test_orch_core_bugs.py tests/test_llm_io_pydantic.py tests/test_brain_io_repair.py -q`.

---

## P2 — AGENTS + HOOKS (safety rewire)

**Files (disjoint):** `agents/executor_stream.py`, `agents/hooks.py`, `agents/hooks_selfmod.py`, `agents/native_executor.py`, `agents/executor_session.py`, `.claude/settings.json`; tests new `tests/test_hooks_registration.py`, new `tests/test_executor_stream_drain.py`, `tests/test_hooks_selfmod*.py`.

- [ ] **B7 `.claude/settings.json`** — `"hooks": {}` means block_destructive + self_modification_guard never run. Restore PreToolUse registrations mirroring `.codex/hooks.json` (same matcher→`venv python agents/hooks.py <hook>` command). Verify JSON valid and the executor `--settings` path still resolves.
- [ ] **B8 new `tests/test_hooks_registration.py`** — assert every hook name the dispatcher in `agents/hooks.py` handles is registered in `.claude/settings.json` (parse both), and vice-versa. This is the CI guard against a future strip.
- [ ] **B9 `agents/executor_stream.py:~209`** — in feed/streaming mode, stderr is read only after stdout EOF → pipe-full deadlock. Drain stderr on its own daemon thread concurrently with the stdout loop; join it before building the result. Test (`tests/test_executor_stream_drain.py`): a fake proc that writes > 64KB stderr while streaming stdout completes without deadlock.
- [ ] **B10 `agents/hooks.py:~42`** — guard sub-modules imported at module load; a broken import makes blocking guards fail OPEN. Import guards lazily inside dispatch and, for a BLOCKING guard, an import/exec error must exit 2 (block), not 0. Test: monkeypatch a guard import to raise; assert dispatch exits nonzero for the blocking hook.
- [ ] **B11 `agents/hooks_selfmod.py:~194`** — bash write-detection regex misses PowerShell verbs. Extend to `Set-Content|Out-File|Add-Content|New-Item|Remove-Item|Clear-Content` and downloaders `curl -o|-O|iwr .*-OutFile|wget`. Test: each verb string is detected as a write.
- [ ] **B12 `agents/native_executor.py:~121,110`** — close/terminate the launched Windows app when any action fails (no leak); mkdir the screenshot dir before saving. Test: failing action path calls terminate; missing dir is created.
- [ ] **B13 `agents/executor_session.py:~18`** — `_SESSION_LIMIT_STATE` is a process-global raced by concurrent workers. Guard reads/writes with a lock (or make per-run). Test: concurrent updates don't lose/duplicate the wait window.
- [ ] **Verify:** `python -m pytest tests/test_hooks_registration.py tests/test_executor_stream_drain.py tests/test_hooks_selfmod_boundaries.py tests/test_hooks_action_risk_parity.py -q` (adjust to existing selfmod test module names).

---

## P3 — NOTIFICATIONS + BOT + WEBDASH SECURITY

**Files (disjoint):** `notifications/tunnel.py`, `notifications/tunnel_providers.py`, `notifications/event_bus.py`, `notifications/bus.py`, `notifications/icons.py`, `notifications/discord_client.py`, `notifications/webdash.py`, `notifications/bot/cogs/control_cog.py`, `notifications/bot/core.py`; tests `tests/test_tunnel.py`, new `tests/test_webdash_control.py`, `tests/test_event_bus.py`, new `tests/test_bot_control_auth.py`.

- [ ] **B14 `notifications/webdash.py:~259`** (security, high) — control token served in the page HTML over the public tunnel. Split view-token vs control-token: page render uses view-only identity; control POST endpoints require a control token printed to local console/log only, never embedded in served HTML. Test (`tests/test_webdash_control.py`): GET `/` body does not contain the control token; control endpoint rejects a request lacking it.
- [ ] **B15 `notifications/tunnel.py`** — (a) `stop()` sets the stop event AND terminates the provider subprocess AND the supervisor thread exits promptly (fixes the join hang); (b) `:~157` reader loop re-announces the same URL after a session restart; (c) guard `LOG.*` calls in `_supervise`/`_demote` so a closed stream during teardown never raises `ValueError: I/O operation on closed file` (check handler stream or swallow). Test: `stop()` joins < 1s; same-URL re-announce fires.
- [ ] **B16 `notifications/event_bus.py:~56`** — `Event.to_dict` stamps `at` with `now()` at serialization, corrupting replayed timestamps. Stamp `at` at Event creation; `to_dict` serializes the stored value. Test: create event, wait, serialize twice → identical `at`.
- [ ] **B17 `notifications/bus.py:~52`** — `emit` swallows `BaseException` (eats KeyboardInterrupt/SystemExit). Catch `Exception`, let `BaseException` propagate. Test: a surface raising KeyboardInterrupt propagates; one raising ValueError is swallowed + logged.
- [ ] **B18 `notifications/icons.py:~74`** — `ensureIcons` latches an empty map on transient startup failure. On failure, do not cache the empty result; retry next call. Test: first call fails → second call (now succeeding) populates icons.
- [ ] **B19 `notifications/discord_client.py:~51`** — owner snowflake sent as JSON int in allowed_mentions; must be a string. Test: payload `allowed_mentions.users[0]` is a `str`.
- [ ] **B20 `notifications/bot/cogs/control_cog.py:~73`** — `/abort` runs blocking ControlBus file IO on the gateway loop. Wrap in `await asyncio.to_thread(...)`. Test: the cog's abort coroutine offloads (patch `to_thread`, assert called).
- [ ] **B21 `notifications/bot/core.py:~150`** — `on_message` ignores only self, not other bots; with unset owner any bot drives control. Ignore all `message.author.bot`. Test: a bot-authored `!abort` is ignored.
- [ ] **Verify:** `python -m pytest tests/test_tunnel.py tests/test_webdash_control.py tests/test_event_bus.py tests/test_bot_control_auth.py tests/test_notification_integration.py -q`.

---

## P4 — MEMORY + LEARNING

**Files (disjoint):** `memory/experience_subtasks.py`, `memory/retrieval.py`, `learning/adversary_trust.py`, `learning/sie.py`, `learning/lessons.py`; tests `tests/test_memory_subtask_manager.py`, new `tests/test_adversary_trust.py`, `tests/test_sie.py`, `tests/test_lessons*.py`.

- [ ] **B22 `memory/experience_subtasks.py:~88`** (data corruption, confirmed) — partial subtask upsert NULLs `title`, `position`, `ended_at`. Use `COALESCE(excluded.col, existing.col)` (or read-modify-write) so a `markDone` partial update preserves pre-existing fields. Test: insert full row, then partial update; assert title/position/ended_at survive.
- [ ] **B23 `learning/adversary_trust.py:~68`** — one torn JSONL line makes the whole log unreadable forever. Parse line-by-line with per-line try/except skip. Test: file with a good line, a torn line, a good line → 2 records returned.
- [ ] **B24 `learning/sie.py:~102`** — maintenance lock steal on a live > 1h owner + unlink/create TOCTOU. Only steal when the recorded owner pid is dead (psutil); create the lock with `O_EXCL`. Test: live-owner lock is NOT stolen; dead-owner lock is.
- [ ] **B25 `learning/lessons.py:~74`** — clear-then-rebuild of lessons/policy_arms non-atomic across transactions. Wrap clear+rebuild in one transaction/connection. Test: simulate failure mid-rebuild → old rows intact (no half state).
- [ ] **B26 `memory/retrieval.py:~321`** — `backfill_embeddings` embeds title-only while live path embeds goal+title (mixed vector space). Use the same compose function for both. Test: both code paths call the same `_embedText(goal, title)` helper.
- [ ] **Verify:** `python -m pytest tests/test_memory_subtask_manager.py tests/test_adversary_trust.py tests/test_sie.py -q`.

---

## P5 — PLATFORM RUNTIME + CONFIG PATHS + KNOWLEDGE SCAN

**Files (disjoint):** `platform_core/runtime/action_risk.py`, `platform_core/runtime/trajectory.py`, `platform_core/runtime/control.py`, `platform_core/app_config/paths.py`, `platform_core/app_config/discord.py`, `platform_core/ops/wipe.py`, `platform_core/execution/security.py`, `platform_core/knowledge_base/scraper.py`; tests `tests/test_action_risk.py`, `tests/test_trajectory*.py`, new `tests/test_wipe.py`, `tests/test_knowledge.py`.

- [ ] **B27 `action_risk.py:~117`** (fail-closed violation, confirmed) — dry-run regex checked before the mutating check lets mutating Bash auto-authorize. Reorder so the mutating/destructive check runs FIRST (fail-closed), dry-run allowance only for genuinely non-mutating commands. Test: `rm -rf x --dry-run`-style mutating+dryrun string is NOT auto-authorized.
- [ ] **B28 `paths.py:~47` + `discord.py:~19`** — `PROJECT_ROOT` defaults to `platform_core/app_config/`; submodules `load_dotenv` a nonexistent `app_config/.env`. Default `PROJECT_ROOT` to the real repo root (git toplevel / parents[2]); remove the dead `load_dotenv` (config.py already loads root `.env` first). Test: `config.PROJECT_ROOT` resolves to a dir containing `main.py`.
- [ ] **B29 `trajectory.py:~90`** — `_flush` uses a fixed shared temp name (cross-writer race). Use a unique temp (pid+tid+counter) then `os.replace`, mirroring `control.py`. Test: two threads flushing concurrently don't clobber.
- [ ] **B30 `control.py:~314`** — `ControlBus.clear()` bypasses both process and file locks. Take both locks like other mutations. Test: `clear()` acquires the lock (patch/assert) and is atomic.
- [ ] **B31 `platform_core/ops/wipe.py:~54`** — 'logs' category hardcodes `INSTALL_ROOT/logs`, ignoring configured `LOG_PATH`. Use `config.LOG_PATH`. Preserve wipe-safety (`_holdsPythonSource` fail-closed — never delete .py). Test (`tests/test_wipe.py`): logs wipe targets `LOG_PATH`; a category never deletes `.py`.
- [ ] **B32 `platform_core/execution/security.py:~34`** — blocked-mount fragment `/etc` matches as bare substring, blocking legit paths (e.g. `/data/etc-config`). Match path segments. Test: `/etc/passwd` blocked; `/data/etcd/x` allowed.
- [ ] **B33 `platform_core/knowledge_base/scraper.py:~344`** — `scanLocalClaude` recurses into `.claude/worktrees` full repo copies (slow + foreign skills injected). Exclude `.claude/worktrees/**`, `fable-rewrite/**`, `nightclaw/**`. Test: scan of a tree with a nested `.claude/worktrees/x/.claude` does not count the nested skills.
- [ ] **Verify:** `python -m pytest tests/test_action_risk.py tests/test_wipe.py tests/test_knowledge.py tests/test_durable_config.py -q`.

---

## P6 — WORKFLOWS + SOCIETY (cheap, flag-off)

**Files (disjoint):** `workflows/scheduler.py`, `society/worker.py`, `society/coordinator.py`; tests `tests/test_priority_scheduler.py`, `tests/test_society_coordinator.py`.

- [ ] **B34 `workflows/scheduler.py:~146`** — `cancel()` permanently deadlocks jobs depending on the cancelled one. On cancel, propagate: dependents are failed/released (never left waiting on a job that will never complete). Test: A blocks B; cancel A → B is released/failed, not stuck.
- [ ] **B35 `workflows/scheduler.py:~139`** — `complete()` accepts unknown/queued job_ids and grows `_completed` unboundedly. Ignore unknown ids; only record known ids. Test: completing an unknown id is a no-op.
- [ ] **B36 `society/worker.py:~80`** — workers never land subtask status → run loop livelocks and aborts. On worker completion (done/failed), set the subtask status. Test: a society worker result transitions its subtask out of pending.
- [ ] **B37 `society/coordinator.py:~125`** — `SOCIETY_TOKEN_BUDGET_USD` unenforced (`budgetExceeded()` dead). Enforce the pre-spawn budget gate (port the check present in `fable-rewrite/society/coordinator.py` — do NOT edit the fable-rewrite tree). Test: spawning stops once budget exceeded.
- [ ] **Verify:** `python -m pytest tests/test_priority_scheduler.py tests/test_society_coordinator.py tests/test_society_debate.py -q`.

---

## P7 — TOOLS / DEVX + SELFMOD RUNNER

**Files (disjoint):** `tools/dev_checks.py`, `tools/dev_reports.py`, `tools/size_audit.py`, `tools/repo_map_render.py`, `scripts/repo_health.py`, `selfmod.py`; tests `tests/test_repo_map.py` (render/util parts only — NOT drift, owned by P0), new `tests/test_selfmod_runner.py`. (Note: `tools/repo_map.py` tracked-only fix is owned by P0; this partition must NOT touch it.)

- [ ] **B38 `selfmod.py:~55`** — default self-mod gate runner is bare `unittest discover` (bypasses pytest sandbox, live side effects). Change default runner to `python -m pytest tests -x -q`. Test (`tests/test_selfmod_runner.py`): the default command list is the pytest form.
- [ ] **B39 `tools/repo_map_render.py:~75`** — generated AGENTS.md instructs `python -m unittest discover -s tests -v`. Change the emitted instruction to the pytest fast lane (`python tools/dev.py fast`). Test: rendered AGENTS.md text contains the pytest instruction, not unittest.
- [ ] **B40 `scripts/repo_health.py:~97`** — advertises `python -m unittest discover` as CI-canonical. Change to pytest. Test/verify: grep the file has no `unittest discover`.
- [ ] **B41 `tools/dev_checks.py:~61`** — `cmd_check` feeds deleted files to ruff/mypy, failing after any deletion. Filter to existing paths before invoking. Test: passing a deleted path is skipped, not fatal.
- [ ] **B42 `tools/dev_reports.py:~37`** — subprocess text pipes use cp1252 on Windows; Unicode in pytest output crashes slow-report/check --json. Force `encoding="utf-8", errors="replace"` on those subprocess calls. Test: a subprocess emitting non-cp1252 bytes is decoded without raising.
- [ ] **B43 `tools/size_audit.py:~41`** — document the tests/+untracked exclusion honestly in the module docstring and `--help` (the "every Python file" claim is the contradiction being fixed); optionally add a report-only tests bucket that never gates. No change to which files gate.
- [ ] **Verify:** `python tools/dev.py check tools/dev_checks.py` + `python -m pytest tests/test_selfmod_runner.py -q` + `python tools/size_audit.py` (zero must_split).

---

## P8 — OPS / MONITORING + LAUNCHER

**Files (disjoint):** `monitoring/tracker.py`, `monitoring/alerter.py`, `run.ps1`; tests `tests/test_monitoring.py`.

- [ ] **B44 `monitoring/tracker.py:~143`** — `_refreshAlerts()` wipes `critical_event_late_detection` alerts on the next `record_execution()`. Preserve late-detection alerts across refresh. Test: record a late critical event, then a normal execution → the critical alert survives.
- [ ] **B45 `monitoring/tracker.py:~34`** — `CRITICAL_DETECTION_WINDOW_SECS = 60` but every doc/spec says 120s. Set to 120 (docs are the contract). Test: `scripts/monitoring_check.py` acceptance ("within 2 minutes") holds; unit asserts constant == 120.
- [ ] **B46 `monitoring/alerter.py:~92`** — late-detected critical events fire two Discord alerts under two dedup keys. Use one dedup key. Test: a single late-critical event yields one alert.
- [ ] **B47 `run.ps1:~93`** — process hunt force-kills ANY python whose cmdline contains 'nightclaw' (per project memory, this self-matches worktree agents). Narrow to an exact `-m nightclaw` match and exclude the current PID/agent processes. **B48 `run.ps1:~214`** — re-query the process list after cleanup before deciding Ollama is "already running". (run.ps1 is untested by CI; verify by static review + a dry `-Check` run comment — do not actually restart the live stack.)
- [ ] **Verify:** `python -m pytest tests/test_monitoring.py -q` + `python scripts/monitoring_check.py` (exit 0).

---

## P9 — FEATURE: CHAOS SIMULATION MODE

**Files:** Create `platform_core/simulator/chaos.py`; Modify `platform_core/cli/main_cli.py` (+`--chaos [seed]` flag), `main.py` (route `--dry-run --chaos`); Test: new `tests/test_chaos_sim.py`.

- [ ] **Step 1** — `chaos.py`: `chaosRunClaude(seed)` wraps `simRunClaude`, deterministically (seeded) returning fault shapes drawn from the exact set the fuzz tests use: `None`, non-dict (`str`/`int`/`list`), `{}`, partial dict, mistyped dict, `is_error=True` envelope, and a simulated timeout marker. Also `chaosBrain(seed)` wrapping `SimBrain` to emit malformed JSON / empty completions.
- [ ] **Step 2 (test-first)** — `tests/test_chaos_sim.py`: for seeds 0..19, `buildOrchestrator` with chaos doubles, `runFull` on a temp work_dir reaches a graceful terminal status (`done|complete|partial|failed|aborted`) and never raises. Run: expect FAIL (module missing).
- [ ] **Step 3** — implement; wire `main.py`: `--dry-run --chaos [seed]` builds the chaos orchestrator. Run test → PASS.
- [ ] **Step 4** — CLI smoke: `python main.py --dry-run --chaos 7` prints a graceful summary. Mark slow (`chaos` filename not in slow patterns → keep test fast; the CLI smoke is manual).
- [ ] **Verify:** `python -m pytest tests/test_chaos_sim.py -q` + the CLI smoke.

---

## P10 — FEATURE: BOT REPLAY HARNESS + NIGHTCLAW EXERCISE

**Files:** Create `platform_core/simulator/bot_replay.py`; Test: new `tests/test_bot_replay.py`. Exercise findings become fixes in the OWNING partition's files (report back, orchestrator routes).

- [ ] **Step 1** — `bot_replay.py`: an offline driver that feeds synthetic gateway messages/interactions through the command spine (`notifications/commands.py` dispatch) against a scripted in-memory `ControlBus`, capturing side effects, with NO real Discord (`DISCORD_BOT_TOKEN` blank). Provide helpers to enqueue `!`-commands with arbitrary author/authorization/args.
- [ ] **Step 2 (test-first)** — `tests/test_bot_replay.py`: the aggressive matrix — every `!` command; malformed args; unauthorized + bot-author senders; duplicate/stale commands; pause/resume/abort races; oversized embed; unicode-garbage; cursor replay; simulated 429/401 at the REST chokepoint; watchdog stale path; dual-consumer double-apply probe. Each asserts: no unhandled exception, correct authorization gating, control ops deduped. Run: expect FAIL (module missing) then drive to green; any genuine bot bug uncovered is filed against P3's files.
- [ ] **Step 3** — implement harness; run the matrix; for each failure, patch the responsible module (P3 scope) and add the regression assertion here.
- [ ] **Step 4 (live-safe check)** — do NOT start a second live gateway. Confirm the harness runs fully offline (token blank → REST no-ops). Document in `docs/TESTING.md` that this replaces a second live instance.
- [ ] **Verify:** `python -m pytest tests/test_bot_replay.py -q`.

---

## P11 — FEATURE: STATE RETENTION SWEEP

**Files:** Create `platform_core/ops/retention.py`; Modify `platform_core/orchestration/run_phase_mixin.py` (call at run finalize, best-effort), `platform_core/app_config/llm.py` or paths (config keys); Test: new `tests/test_retention.py`.

- [ ] **Step 1 (test-first)** — `tests/test_retention.py`: given a tmp `state/blackboard` with 15 jsonl files of varied mtimes, `sweepBlackboard(keep_recent=10, max_age_days=14)` keeps the newest 10 (and anything younger than 14d), removes the rest, and NEVER touches `.py`. Same matrix for `state/compaction/ctx-*.txt`. Terminal-status task/control files older than 30d are ARCHIVED (moved to `state/archive/`), never deleted. Run: expect FAIL.
- [ ] **Step 2** — implement `retention.py` (`RETENTION_ENABLED` default true, `RETENTION_KEEP_RECENT`, `RETENTION_MAX_AGE_DAYS`); all operations fail-open (log + continue). Wire a best-effort call in the run teardown. Run test → PASS.
- [ ] **Verify:** `python -m pytest tests/test_retention.py -q`.

---

## P12 — FEATURE: FAILURE-AWARE RETRIEVAL

**Files:** Modify `memory/retrieval.py` (additive; must NOT collide with P4's B26 edit — P4 owns `backfill_embeddings`, P12 owns the query-time injection). To keep files disjoint, P12 runs AFTER P4 in Wave 2. Test: new `tests/test_retrieval_failures.py`.

- [ ] **Step 1 (test-first)** — `tests/test_retrieval_failures.py`: with `RETRIEVAL_FAILURES_ENABLED=True`, a retrieval for a spec similar to a past FAILED subtask injects up to 2 "similar past FAILURE" warnings alongside the past successes, tagged distinctly, bounded by an existing token budget. With the flag False, output is byte-identical to today. Run: expect FAIL.
- [ ] **Step 2** — implement behind the flag (default true), reusing the existing O(n) cosine scan and index (no new store). Run test → PASS.
- [ ] **Verify:** `python -m pytest tests/test_retrieval_failures.py tests/test_retrieval*.py -q`.

---

## Finalize (serial)

- [ ] Regenerate repo map: `python tools/repo_map.py` then `python tools/repo_map.py --check` (clean).
- [ ] `.gitignore`: add `fable-rewrite/` and `nightclaw/` (quarantine clones out of status).
- [ ] Docs: update `docs/TESTING.md` (sandbox guards, chaos lane, bot replay lane), `docs/STATE.md` (retention), `docs/DANGER_MAP.md` (hooks rewired + canary), `docs/CUSTOM_SKILLS_AND_HOOKS.md` (settings.json registration).
- [ ] `python tools/dev.py fast` → 0 failed (hermetic).
- [ ] `python -m pytest -m slow -n auto --dist loadscope` → 0 failed, no hangs, < 4min.
- [ ] Env-pinning proof: `$env:HUMAN_NATURE_ENABLED='true'; python tools/dev.py fast` → still 0 failed.
- [ ] `python tools/size_audit.py` → zero must_split. `python -m ruff check .` → no NEW violations in changed source files.
- [ ] Chaos smoke: `python main.py --dry-run --chaos 7` graceful. Bot replay suite green.

## Self-review notes (author)

- Spec coverage: WS1→P2/P3, WS2→P1/P2/P3/P4/P5/P6/P8, WS3→P0, WS4→P11, WS5→P9/P10/P3/P2/P12, WS6→P10, WS7→Finalize. All covered.
- Disjointness: `memory/retrieval.py` is touched by both P4 (B26) and P12 — resolved by ordering P12 after P4 in Wave 2 and scoping to different functions. `tools/repo_map.py` owned solely by P0; P7 explicitly excluded. No other file appears in two partitions.
- Safety canary (WS1.5) folded into P2 (hooks) + verified at run start; if time-bounded, it is additive to B7/B8 and does not gate the suite.
