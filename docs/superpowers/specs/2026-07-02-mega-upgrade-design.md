# 2026-07-02 — Mega-Upgrade Design (bugs, tests, safety, features, bot exercise)

Status: approved by standing user directive ("approve everything", autonomous run).
Executed in git worktree `worktree-mega-upgrade` (base `a99a378` + untracked `nightclaw/`,
`fable-rewrite/` carried over). Main tree left untouched for the live orchestrator run.

## Goal

Brutally upgrade the whole app: every confirmed bug fixed, every test passing fast in both
hermetic (no `.env`) and live-`.env` environments, safety layer rewired, bounded set of
high-value innovative features, and an isolated "run the bot and try stuff" exercise with
fixes for what breaks.

## Baseline (2026-07-02, main tree unless noted)

- Fast lane: 3909 passed / 49.8s (green). Worktree fast lane: 9 failed (path-sensitivity).
- Slow lane: 17 failed / 248 passed / 5m22s + 2 hung fuzz tests -> xdist worker crash -> pytest INTERNALERROR.
- Ruff: 1592 errors excl. new dirs (1310 in `.claude/`, ~110 in real source, 174 in tests).
- Size audit: clean. repo_map --check: FAILING in main tree (untracked scratch file trap).
- Audit: 12 subsystem mappers + adversarial verify -> ~80 bugs (12 confirmed hot, 2 refuted).

## Non-goals / constraints

- NO model/effort routing changes (project rule).
- NO second live gateway bot instance with the shared token (double-handling in live server).
- fable-rewrite/ Wave 2 content untouched (separate epic); only quarantine hardening.
- Society Epic-5 full wiring out of scope (flag-off in prod); only its 2 hot bugs get cheap fixes.
- No pushing secrets anywhere; `.env` never read or copied.
- CI workflow topology unchanged; only local-speed + report regeneration.

## Workstream 1 — Safety & security (highest priority)

1. **Rewire safety hooks**: `.claude/settings.json` has `"hooks": {}` (stripped by e208290)
   while `agents/hooks.py` dispatcher + guards exist and `.codex/hooks.json` holds the intended
   registration. Restore PreToolUse registrations (block_destructive, self_modification_guard)
   to `.claude/settings.json`, mirroring `.codex/hooks.json` semantics. Add a fast test that
   asserts registration matches the dispatcher's handled hook names (CI guard).
2. **Webdash control-token exposure** (`notifications/webdash.py:259`): page served over the
   public tunnel embeds the control token for any GET. Split view-token vs control-token:
   page render gets view-only; control endpoints require the control token which is only
   printed to local console/log, never served in HTML. Test: token not obtainable from `/`.
3. **action_risk dry-run precedence** (`platform_core/runtime/action_risk.py:117`): dry-run
   regex is checked before the mutating check, so mutating Bash can auto-authorize. Reorder:
   mutating check first (fail-closed). Add the bypass case to `tests/test_action_risk.py`.
4. **selfmod gate runs bare unittest** (`selfmod.py:55` default runner): swap default runner to
   `python -m pytest tests -x -q` (sandboxed); also fix `tools/repo_map_render.py:75` AGENTS.md
   template and `scripts/repo_health.py:97` advice strings (unittest -> pytest).
5. **Safety-layer canary handshake** (feature, pairs with #1): at run start, executor fires a
   deliberately-blocked no-op destructive probe through the hook path and records whether the
   hook layer actually blocked it; warn loudly (Discord + log) if hooks are inert.

## Workstream 2 — Confirmed core bugs (fix + focused test each)

Orchestrator core:
- `llm_io.py:60` — move `_tap_brain` out of the extraction try; telemetry failure must never blank a valid completion.
- `platform_core/orchestration/run_loop.py:89` — check `git checkout` returncode; only `markSelfReferential` after success; alert + abort self-ref prep on failure.
- `run_loop_mixin.py:217` — on parallel abort, defer `exitWorktree` for still-running futures until after pool shutdown.
- `run_loop_mixin.py:375` — coerce non-string replan titles (`isinstance(str)` guard, mirror `_asText`).
- `brain_io.py:26` — when budget <= 0 return a bounded tail slice + warning; unify chars/token constant with compaction.
- `control_mixin.py:359` — lock + per-sid dedup hash; commit hash only after successful review.

Executor/agents:
- `agents/executor_stream.py:209` — drain stderr on its own thread in feed mode (pipe-full deadlock).
- `agents/hooks.py:42` — lazy-import guard sub-modules inside dispatch; a broken import must fail CLOSED for blocking guards (exit 2), not open.
- `agents/native_executor.py:121` — close/kill launched app on action failure; `:110` mkdir screenshot dir.
- `agents/hooks_selfmod.py:194` — extend write-verb regex with PowerShell verbs (Set-Content, Out-File, Add-Content, curl -o, iwr -OutFile, etc.).

Notifications/bot:
- `notifications/tunnel.py` — stop event honored between provider sessions; `stop()` terminates provider subprocess; `_supervise` exits promptly; no logging after stream close (guard emit).
- `notifications/tunnel.py:157` — re-announce same URL after session restart.
- `notifications/event_bus.py:56` — stamp `at` at Event creation, not serialization.
- `notifications/bot/cogs/control_cog.py:73` — `/abort` ControlBus IO via `asyncio.to_thread`, unify through `slash._runControl`.
- `notifications/bot/core.py:150` — ignore all bot authors on gateway `on_message`, not just self.
- `notifications/discord_client.py:51` — owner snowflake as string in allowed_mentions.
- `notifications/bus.py:52` — catch `Exception`, re-raise `BaseException` (KeyboardInterrupt/SystemExit).
- `notifications/icons.py:74` — don't latch empty icon map on transient failure (retry next call).

Memory/learning:
- `memory/experience_subtasks.py:88` — partial upsert must COALESCE existing title/position/ended_at (data corruption).
- `learning/adversary_trust.py:68` — skip torn/corrupt JSONL lines (per-line try/except) instead of failing the whole log.
- `learning/sie.py:102` — lock steal only when owner pid dead (psutil), fix unlink/create TOCTOU via O_EXCL create.
- `learning/lessons.py:74` — wrap clear+rebuild in one transaction.

Platform/workflows/state:
- `workflows/scheduler.py:146` — `cancel()` must resolve/fail dependents (release deadlock).
- `platform_core/runtime/trajectory.py:90` — unique temp name per writer (pid+tid), mirroring control.py fix.
- `platform_core/runtime/control.py:314` — `clear()` takes both locks.
- `platform_core/app_config/paths.py:47` + `platform_core/app_config/discord.py:19` — PROJECT_ROOT default -> real repo root; drop dead load_dotenv of nonexistent app_config/.env.
- `platform_core/ops/wipe.py:54` — use configured LOG_PATH (respect wipe-safety constraint: data only, never .py).
- `platform_core/execution/security.py:34` — blocked-mount fragments match path segments, not bare substrings.
- `platform_core/knowledge_base/scraper.py:344` — exclude `.claude/worktrees/**` + `fable-rewrite/**` + `nightclaw/**` from scanLocalClaude.

Society (cheap, flag-off):
- `society/worker.py:80` — workers land subtask status (done/failed) on completion.
- `society/coordinator.py:125` — enforce budget gate pre-spawn (port the fable-rewrite variant's check).

Tools/devx:
- `tools/repo_map.py:74` — scan git-tracked files only (kills the untracked-scratch-file trap).
- `tools/dev_checks.py:61` — filter deleted files before ruff/mypy.
- `tools/dev_reports.py:37` — force UTF-8 on subprocess text pipes.
- `tools/size_audit.py:41` — document the tests/ + untracked exclusions explicitly in the module docstring and `--help` (auditing tests/ and splitting violating test files is out of scope; the silent contradiction with "every Python file" is the bug being fixed).

Ops/monitoring:
- `monitoring/tracker.py:143` — `_refreshAlerts` preserves critical_event_late_detection alerts; `:34` window 60s -> 120s (docs are the contract).
- `monitoring/alerter.py:92` — single dedup key for late-critical alerts.
- `run.ps1:93` — narrow process hunt to `-m nightclaw` exact cmdline (avoid self-match per project memory); `:214` re-query process list after cleanup before deciding Ollama is running.

## Workstream 3 — Test suite: green + fast, hermetic AND live-env

1. **Config pinning fixture** (root cause of 10+ failures): autouse fixture in `tests/conftest.py`
   pinning test-relevant `config` flags to documented defaults: `HUMAN_NATURE_ENABLED=False`,
   `SEMANTIC_SAFETY_ENABLED=False`, `DASHBOARD_CV2` and friends per `.env.example` defaults
   (mechanism: snapshot-restore of an explicit flag list). Suite must pass with ANY user `.env`.
2. **Sandbox hardening**: autouse guards for (a) real `claude` CLI spawn (mirror `_no_real_ollama`),
   (b) TunnelManager/providers (block `_spawn`, block supervisor start), (c) redirect
   `config.py:160` FileHandler to tmp during tests (stop 44MB prod-log pollution).
3. **Fuzz hangs**: fixed by tunnel stop-event fix (WS2) + sandbox (b). Verify both fuzz tests
   finish < 60s.
4. **Worktree path-robustness** (9 failures when repo runs from `.claude/worktrees/...`):
   fix `platform_core/core/identity.py` self-file enumeration, `tests/test_repo_map.py` drift
   check, `test_eval_harness` golden-goal paths, `test_deployment` normalize_work_dir,
   `test_config_robust_env`, `test_identity_perf` to resolve against the repo root they live in
   (git rev-parse toplevel of own file), not `C:\9to5` literals/cwd assumptions.
5. **Remaining failures**: e2e_operator (abort_at_gate, adversary_holds_the_pr), discovery
   ordering, dashboard lifecycle — diagnose under pinned flags first (expected to be env-flag
   fallout; fix genuinely if not).
6. **Collection hygiene**: `tests/test_registry.py` shim double-collection (50 dup tests),
   `tests/test-trace-replay.py` never collected (rename/underscore + collect), direct-run
   unittest shims documented as pytest-only.
7. **Speed**: regenerate `logs/slow-test-report.md`; repo_map test lane (34s) gets cached
   build_map; keep fast lane <= ~55s, slow lane target < 4min with zero hangs.

## Workstream 4 — State hygiene (feature: retention/GC sweep)

New `platform_core/ops/retention.py` + wiring at run finalize (best-effort, fail-open):
- `state/blackboard/*.jsonl` — keep newest N (default 10) or younger than 14d.
- `state/compaction/ctx-*.txt` — same policy (95 files/5MB today).
- `state/control/*.json`, `state/tasks/*.json` — archive terminal-status files older than 30d
  into `state/archive/` (never delete task state outright; wipe-safety constraint).
- Config keys: `RETENTION_ENABLED` (default true), `RETENTION_KEEP_RECENT`, `RETENTION_MAX_AGE_DAYS`.
- Tests: creation/expiry matrix with tmp dirs.

## Workstream 5 — Innovative features (bounded set)

1. **Chaos simulation mode** (`platform_core/simulator/chaos.py`): fault-injecting doubles
   wrapping SimBrain/simRunClaude — seeded random failures (malformed JSON, timeouts, empty
   completions, is_error envelopes, partial dicts). `main.py --dry-run --chaos [seed]` runs the
   full loop under fault injection and asserts graceful terminal state. This IS the safe
   version of "run it and try stuff that is out of hand".
2. **Bot run-replay harness** (`platform_core/simulator/bot_replay.py` + test lane): drive
   nightclaw cogs offline — fake gateway messages/interactions through the command spine
   (`notifications/commands.py`) against a scripted ControlBus, assert side effects. Used for
   the live bot exercise below; stays as a permanent regression lane (`tests/test_bot_replay.py`).
3. **Split view/control tunnel tokens** (WS1.2) — safe public spectating.
4. **Safety canary handshake** (WS1.5).
5. **Failure-aware retrieval** (`memory/retrieval.py`): alongside top-K past successes, inject
   top-2 similar past FAILURES as warnings ("similar attempt failed because ...") behind
   `RETRIEVAL_FAILURES_ENABLED` (default true, cheap — same index).
6. **Retention sweep** (WS4).

## Workstream 6 — Nightclaw exercise (isolated)

Constraint: live bot (nightclaw#6870) + live orchestrator run already active on the real
token/channel; only one `DISCORD_BOT_TOKEN` exists. A second gateway session would
double-handle events in the production server; a cloud env would require exfiltrating the
token. DECISION: exercise the bot in-process against the replay harness + full-loop
`--dry-run` / `--dry-run --chaos` runs in the worktree; NO second live gateway.

Exercise matrix (scripted, aggressive): every `!` command incl. malformed args, unauthorized
senders, bot-author senders, duplicate/stale commands, control floods (pause/resume/abort
races), oversized embeds, unicode garbage, cursor replay, 429/401 simulation at the REST
chokepoint, watchdog stale-run path, dual-consumer double-apply probe. Every crash/misbehavior
becomes a fix + regression test in the same patch.

## Workstream 7 — Docs & repo map

- Regenerate repo map artifacts (AGENTS.md, .repo-map.json, headers) AFTER structural changes.
- `.gitignore`: add `fable-rewrite/` and `nightclaw/` quarantine entries (keep worktree clones
  out of status noise; identity/repo_map already exclude them).
- Update `docs/TESTING.md` (new sandbox guards, chaos lane, bot replay lane), `docs/STATE.md`
  (retention), `docs/DANGER_MAP.md` (hooks rewired, canary), `docs/CUSTOM_SKILLS_AND_HOOKS.md`
  (settings.json hook registration).
- Fix generated-AGENTS.md unittest instruction (WS1.4).

## Verification

- `python tools/dev.py fast` green in worktree (hermetic) — includes all new tests.
- `python -m pytest -m slow -n auto` green, no hangs, < 4min.
- Env-pinning proof: fast lane green with `HUMAN_NATURE_ENABLED=true` exported.
- `python tools/size_audit.py` zero must_split; `python tools/repo_map.py --check` green.
- `python -m ruff check .` clean for changed files (no new violations; F401 facades preserved).
- Chaos: `python main.py --dry-run --chaos 7` reaches graceful terminal state.
- Bot replay suite green. Canary handshake verified in dry-run.

## Risks

- Hooks rewiring changes live executor behavior — validated via canary + non-blocking design
  (only explicit safety guards block, per orchestration rules).
- Worktree-robustness fixes touch identity fingerprint — must not weaken selfmod protections.
- Merge back to main tree happens while live run mutates it — final merge is a separate,
  reviewed step (branch stays available; no force operations).
