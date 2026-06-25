# Gnarly-audit: remaining MEDIUM/LOW findings

The 30-agent systematic-debugging audit (2026-06-25) confirmed 42 real bugs. All **CRITICAL** and
all **HIGH** findings are FIXED on this branch (audit/gnarly-bug-hunt) with regression tests. The
MEDIUM/LOW findings below remain for follow-up (each adversarially verified). A handful of MEDIUMs
were duplicates of a CRITICAL/HIGH cluster fix and are already resolved -- noted inline.

## [20] MEDIUM — browser_executor.py 253-273 (_preflightLoginBlocki
**Pre-flight reports 'login timed out' on any transient open/navigation error, aborting the whole /work launch**

- **Root cause:** _preflightLoginBlocking wraps sess.open() + page.goto('https://chatgpt.com/', timeout=30000) + the READY poll in one broad `except Exception: return False`. open() runs profile_hygiene.sanitize() and launch_persistent_context (which can throw 'profile already in use', a Playwright driver error, or a 30s nav timeout if chatgpt.com is briefly slow/offline). ALL of those collapse to the same False return that the caller (slash.work / views._launch) interprets as 'login timed out (5 min)'.
- **Impact:** A transient browser/network hiccup blocks the entire run from launching and the message misattributes it to a login timeout, so the user re-logs-in pointlessly. The run cannot start until the transient condition clears, despite the orchestrator child
- **Fix:** Distinguish 'not logged in yet' (keep polling until deadline) from a hard launch/nav exception. On an open()/goto exception, either retry with backoff inside the deadline or return a tri-state so the caller can proceed with the launch (letting the orchestrator's own probe-and-degrade handle GPT availability) instead of hard-aborting the run. At min

## [21] MEDIUM — main.py 56 and 99 and 314 (thread star
**Two threads read sys.stdin concurrently in interactive non-auto-approve runs (terminal-control daemon vs input()/_collectEditedSpec)**

- **Root cause:** _startTerminalControl (line 291, fresh run) launches a daemon thread that loops `for line in sys.stdin` (line 56) to mirror control commands. It is started BEFORE the elaboration-approval prompt. In the non---auto-approve path the MAIN thread then also reads the same sys.stdin: `input('Approve elaboration? [Y / edit / n] ')` (line 314) and, on 'edit', `_collectEditedSpec()` which does `for line in sys.stdin` (line 99). Two threads concurrently consuming one stdin file object is a race: a typed l
- **Impact:** In interactive gated/non-auto-approve runs the approval gate and spec-edit flow become unreliable: keystrokes meant for one consumer are stolen by the other, so the gate can hang (input() never gets its line), mis-read a control word as an approval, 
- **Fix:** Do not run both stdin readers at once. Gate _startTerminalControl on sys.stdin.isatty() AND defer starting it until after all main-thread interactive prompts (goal input, approval, spec edit) have completed -- i.e. start the terminal control thread only immediately before run_with_recovery, not before elaboration. Alternatively, route all stdin thr

## [22] MEDIUM — resilience.py 68-73 (pick_resume_task) vs C:
**Documented 'orphan resume on a fresh process' is never wired: a hard-killed run is not auto-resumed at startup**

- **Root cause:** resilience.pick_resume_task() exists to find 'the most-recent interrupted (non-terminal) task to auto-resume' (and the module docstring lists 'Orphan resume -- on a fresh process, pick up an interrupted non-terminal task' as a core guarantee). A grep of the whole tree shows pick_resume_task is referenced ONLY in resilience.py and tests/test_resilience.py -- main.py never calls it. A fresh `python main.py` (no --resume) goes straight to creating a brand-new task; it never checks for an interrupte
- **Impact:** The advertised crash-survival guarantee for true process death depends on an external actor issuing --resume; an unattended machine that simply reboots (the 9am->5pm 'come back at 5pm' scenario) will not resume the in-flight task on its own.
- **Fix:** At the top of main() (before the fresh-run branch, when no --goal/--resume implies a possible orphan, or always as a best-effort), call resilience.pick_resume_task(); if it returns an id whose run_pid is not alive (reuse work_launcher._runPidAlive), route into the existing --resume path instead of creating a new task. Alternatively document explici

## [23] MEDIUM — orchestrator.py 425-435 (with agents/executor.
**Eval/fitness Claude runs execute in PROJECT_ROOT without task_state, bypassing universe/self-mod hard-boundary guarding**

- **Root cause:** `_runEvalGoal` (orchestrator.py:425-429) creates an ephemeral eval TaskState that is never marked self-referential and has no universe set, then calls `self._run_claude(spec, work_dir=str(config.PROJECT_ROOT))` WITHOUT the `task_state=` kwarg. In executor.runClaude the env pins (`NINE_TO_FIVE_TASK_FILE`/`TASK_ID`/`SUBTASK_ID`) and the self-ref `--disallowedTools` core-file lock are gated on `task_state is not None` (executor.py:405-409, 421-429). With no task_state exported, the hooks' `_resolve
- **Impact:** An eval/fitness run can edit the real project tree (including potentially core files when no active self-ref task is the latest) without the intended per-task universe/core-file guarding, because the deterministic env-pinned resolution the guard reli
- **Fix:** Pass `task_state=state` (and a `subtask=`) to the `_run_claude` call in `_runEvalGoal` so the executor exports the env pins and the guard resolves explicitly; set a minimal universe (at least the baseline hard_boundaries) on the eval state via setUniverse before the run so the guard has a concrete scope even on the eval path.

## [24] MEDIUM — orchestrator.py 1218-1250 (leak created at 122
**ChatGPT browser session leaked when startConversation fails after a passing probe (teardown can never reclaim it)**

- **Root cause:** In _openChatGptSession the success-side handle assignment `self._chatgpt_session = browser_executor` (line 1233) happens AFTER browser_executor.startConversation(...) (line 1232). browser_executor.probe() (line 1228) calls ChatGPTSession.health_probe(), which on SUCCESS leaves the Chromium persistent context OPEN (chatgpt_driver.health_probe returns True without close(); only the failure branch closes). So once probe() returns True the global _SESSION browser is live. If startConversation() then
- **Impact:** A leaked headless/head-ful Chromium plus Playwright driver thread persists until the next _launch() runs profile_hygiene.sanitize() (next fresh process), holding the profile single-instance lock. Within the current long-lived supervisor process the s
- **Fix:** Make teardown independent of the success-side handle: assign self._chatgpt_session = browser_executor BEFORE calling startConversation (so the finally can always close it), or in the except branch at 1238 call browser_executor.closeSession() directly (it operates on the global _SESSION regardless of the instance attribute) before returning. Also ha

## [25] MEDIUM — orchestrator.py 2129-2135 (architect call); co — ✅ ALREADY FIXED (cluster dup)
**Architect setup call omits cancel_check, so a session-token-limit hit during setup wedges the run up to 5h x3 ignoring abort and the deadline**

- **Root cause:** runFull's setup-phase architect invocation _runArchitect (lines 2129-2133) calls self._run_claude({...}, work_dir=..., system_prompt=ARCHITECT_SYSTEM_PROMPT, task_state=state) WITHOUT a cancel_check argument. In executor.runClaude, when the Claude Pro session token budget is exhausted (_isRateLimitError true), the call enters the `while _isRateLimitError(result) and tries < SESSION_LIMIT_MAX_RETRIES` loop and _waitForSessionReset(cancel_check=None). With cancel_check None, the wait sleeps in 30s
- **Impact:** An abort issued (or a deadline reached) during the architect setup phase is ignored for up to ~5h per retry cycle (up to 3), violating the 9am-5pm 'finished or finalized by the deadline, never wedged' promise and the explicit CB-9 abort/deadline-awar
- **Fix:** Thread a cancel_check into the setup architect call exactly like the execution loop: pass cancel_check=lambda: bus.isAbort() or self._deadlinePassed(state) to self._run_claude inside _runArchitect (bus is in scope in runFull). Apply the same to _evalGoal's _run_claude if it can hit production rate limits. This lets the session-reset wait break earl

## [26] MEDIUM — orchestrator.py 2019-2047 (detect+prepare); ag
**External target repo misclassified as self-referential via the bare "9to5" goal marker, creating an sc/ branch there and wrongly core-file-locking it**

- **Root cause:** _detectSelfReferential (orchestrator.py:2019-2027) returns True if `same_dir` OR if the goal text contains any of the markers, which include the bare product name "9to5". For a run explicitly targeting an EXTERNAL repo (`--work-dir C:\someproject`, so same_dir is False), a goal that merely mentions 9to5 (e.g. 'have 9to5 refactor my parser') still matches the "9to5" marker -> the run is treated as self-referential. _prepareSelfReferential (2029-2047) then runs `git checkout -B sc/<id>` inside the
- **Impact:** 9to5 silently creates an unexpected git branch in a user's unrelated repo and refuses to edit legitimately-targeted files there whenever they share a basename with 9to5's own core files. The run burns all attempts failing a deliverable it is structur
- **Fix:** Gate the textual markers on actually operating in the install tree, not on the bare product name. Drop "9to5" from the marker list (it is the install-path/product name the comment at 2022 already warns about) and rely on `same_dir` plus narrowly self-targeting phrases ('itself', 'self-modify', 'its own code'); or require BOTH a self-target phrase A

## [27] MEDIUM — orchestrator.py 335-358 (salvage at 352); reac — ✅ ALREADY FIXED (cluster dup)
**Greedy-regex JSON salvage in _chatJson concatenates multi-object brain output into an unparseable blob, collapsing the plan/spec to the degenerate fallback**

- **Root cause:** llm_io._firstBalancedObject/responseJson was added specifically to fix the maximally-greedy `re.search(r"\{.*\}", text, re.DOTALL)` span bug (it spans from the first `{` to the LAST `}`, gluing two separate JSON objects into one invalid blob). That fix was applied ONLY in llm_io (used by replanner). orchestrator._chatJson at line 352 STILL uses the old greedy regex. _chatJson is the parser for authorSubtaskPlan (632), critiqueSubtaskPlan (694), authorInvocationSpec (802), _autoApprovePlan (967),
- **Impact:** On the (reachable) format=json-dropped salvage path, a recoverable multi-object reply is discarded instead of salvaged, collapsing a real multi-step plan into one unverified catch-all subtask -- the exact failure llm_io._firstBalancedObject was writt
- **Fix:** Replace the body of orchestrator._chatJson with a call to llm_io.responseJson (which already handles the pydantic shape, the ```json fence, AND the balanced-brace walk). Same for agents/adversary._loadJsonLoose (line 49) and agents/vlm_healer (line 52), which carry the identical greedy regex.

## [28] MEDIUM — adversary.py 49 (_loadJsonLoose); consumed  — ✅ ALREADY FIXED (cluster dup)
**Adversary's greedy-regex JSON salvage can drop a real 'challenged' verdict to a conservative 'approved', neutering the pre-PR hold**

- **Root cause:** adversary._loadJsonLoose uses the same maximally-greedy `re.search(r"\{.*\}", text, re.DOTALL)` (line 49) that llm_io._firstBalancedObject replaced. The function's own FX-5 docstring states that a fenced/prose-wrapped 'challenged' verdict that fails json.loads silently degrades to a conservative 'approved' and 'would neuter the PR-hold and remediation' -- yet the salvage step it relies on still has the span bug for any multi-object reply.
- **Impact:** A real adversarial block on a structurally-risky change can be silently downgraded to approved, letting a flagged PR through. Lower-probability than the orchestrator case because format=json is normally set, but the consequence (shipping work the rev
- **Fix:** Route _loadJsonLoose through llm_io.responseJson / llm_io._firstBalancedObject so a multi-object or fenced reviewer reply is correctly salvaged instead of dropped.

## [29] MEDIUM — orchestrator.py 1283-1286 (_remediate), 1268-1 — ✅ ALREADY FIXED (cluster dup)
**Adversary remediation calls the executor WITHOUT cancel_check, so a rate-limit pause ignores abort/deadline for up to ~5h per attempt**

- **Root cause:** The main retry loop fires the executor with `cancel_check=lambda: bus.isAbort() or self._deadlinePassed(state)` (orchestrator.py:1530) specifically so the executor's session-token-limit pause (_waitForSessionReset) can break early on abort/deadline (CB-9). _remediate calls `self._run_claude(spec, work_dir=exec_cwd, task_state=state, subtask=subtask)` (orchestrator.py:1285) with NO cancel_check. Inside executor.runClaude, _isRateLimitError -> _waitForSessionReset is then called with cancel_check=
- **Impact:** An unattended run can hang for hours inside best-effort remediation, ignoring both operator abort and the work-horizon deadline -- the exact failure mode CB-9 fixed for the primary executor path but which remediation reintroduces. Remediation is enri
- **Fix:** Thread the same cancel predicate through _remediate and pass it: `self._run_claude(spec, work_dir=exec_cwd, task_state=state, subtask=subtask, cancel_check=lambda: bus.isAbort() or self._deadlinePassed(state))`. Pass `bus`/cancel into _remediate from _executeSubtask (it already has `bus`). Also bail the remediation loop early when the wait was canc

## [30] MEDIUM — orchestrator.py 866-886; notifications/bot/cor
**Cross-process double-apply of '!' commands: in-run REST poller and gateway bot both apply the same message (duplicate !add subtasks)**

- **Root cause:** Two independent consumers act on the same Discord message: (1) the in-run poller _translateDiscord (main.py process) reads messages via discord.fetchMessagesAfter and calls commands.applyCommand for each; (2) the optional gateway bot's on_message (notifications/bot/core.py) ALSO calls handleCommand->applyCommand on the same message. The per-process _poll_lock only de-dupes within the run process; there is no cross-process coordination (the gateway never touches the bus seen-cursor). For idempote
- **Impact:** When both control surfaces run concurrently, every queued (non-idempotent) command is applied twice: duplicate subtasks from !add, double skip/edit ops. Wasted time-horizon and potentially conflicting parallel edits to the same files. The docs frame 
- **Fix:** Make queued ops idempotent / deduplicated at the source: give each pushed op a client-generated op_id (e.g. derived from the Discord message id) and have drainOps/_applyOps drop ops whose id was already processed; or have exactly one consumer own command application (e.g. the gateway pushes ops and the in-run poller never applies mutating commands,

## [31] MEDIUM — verifier.py 286-322, 307-312
**Compound stdout_contains_all / single stdout_contains gate ignores return code -> a crashing program that prints the needles false-PASSES**

- **Root cause:** For expect=stdout_contains:/stdout_contains_all:/stdout_regex:/stdout_regex_all:, _evaluate decides PASS purely on substring/regex presence in the haystack and never consults returncode. runVerification only folds stderr into the haystack when rc==0, but it still calls _evaluate which returns True if the needles appear in stdout regardless of rc. A program that prints the expected tokens to stdout and THEN crashes (non-zero exit, traceback to stderr) passes the gate. The compound `stdout_contain
- **Impact:** Partial/broken work that happens to emit the marker strings before crashing is reported as a verified PASS. This is the precise class of bug the compound verify was added to prevent (a subtask that did N-1 of N, or printed markers then died). It can 
- **Fix:** For the stdout_contains*/stdout_regex* families, require returncode==0 in addition to the needle match (a program asserting its own output should exit cleanly), or at minimum gate the compound *_all forms on rc==0 since they back the strict multi-requirement check. Keep exit_zero as the rc-only shape. Document that a 'contains' check implies a clea

## [32] MEDIUM — orchestrator.py 1146-1158 (_adversaryReview / 
**GPT session that persistently SOFT-fails is never disabled, so every review for the rest of the run re-attempts the browser (hammering) instead of pinning to Ollama**

- **Root cause:** The orchestrator only disables GPT for the run when consult returns session_dead=True, which _FatalProbe sets ONLY for the three fatal typed errors (ChatGPTLoginRequired/Blocked/RateLimited). A persistent NON-fatal soft failure -- empty reply, unparseable JSON after the repair nudges (chatgpt_driver.ask returns None), or a ChatGPTSelectorMiss the VLM can't heal -- yields a stub with probe.fatal=None, so _chatgpt_session_ok stays True. Because session_ok is re-read True at the start of every _adv
- **Impact:** On a UI break, repeated streaming timeouts, or chronic JSON-repair exhaustion, the run pays a full browser round-trip per triggered review for the entire horizon (latency + flakiness), instead of pinning to Ollama after the first persistent failure. 
- **Fix:** Track consecutive non-fatal GPT stub failures (e.g. a counter incremented when consult tier!='gpt' while session_ok was True) and clear _chatgpt_session_ok after a small threshold (e.g. 2-3), mirroring the session_dead disable + one-time Discord notice. Optionally have chatgpt_driver classify repeated selector-miss / JSON-repair exhaustion as a sof

## [33] MEDIUM — experience.py 239-251, 269-279
**Connection leaked (never closed, never registered) when schema/WAL setup raises during first-open of a DB path**

- **Root cause:** In `_new_conn`, the sqlite3 connection is opened at line 240, but it is only appended to the global `_all_conns` registry at line 249-250 -- AFTER the `if first:` schema block (lines 243-248) runs `PRAGMA journal_mode=WAL`, all of `_SCHEMA`, and `_applyMigrations`. If ANY of those statements raises (e.g. SQLITE_BUSY on `PRAGMA journal_mode=WAL`/`CREATE TABLE` while another process holds the DB on concurrent first-open, or 'duplicate column name' from the migration race where two processes run `A
- **Impact:** Leaked SQLite connection = leaked OS file handle plus the WAL/SHM file handles it pins. On Windows those handles keep locks on experience.db-wal/-shm, which can block later os.replace/delete/cleanup of the DB or its sidecar files and accumulate acros
- **Fix:** Guard the schema-setup block so the connection is closed if it raises before being registered: wrap lines 243-248 (and append to _all_conns first, or use try/except that closes conn on failure). E.g. `try: <schema block>; with _pool_lock: _all_conns.append(conn) except BaseException: conn.close(); raise`. Apply the same protection to the `elif firs

## [34] MEDIUM — retrieval.py 129-153, 163-194
**Retrieval applies NO similarity floor -- every authoring prompt is force-fed up to K 'past lessons' even when cosine ~ 0 (or all 0.0 after an embed-model change)**

- **Root cause:** top_k_similar() sorts the candidate pool by cosine score and returns out[:k] with no minimum-score threshold. render_lessons() then ignores the per-neighbor 'score' field entirely and renders whatever rows it is handed under the header '## RELEVANT PAST LESSONS (from similar subtasks that PASSED)'. cosine() (line 100-101) returns 0.0 -- not an error -- when len(a) != len(b). So if config.EMBED_MODEL is ever changed (e.g. nomic-embed-text -> a model with a different embedding dimension), every pr
- **Impact:** On every subtask plan/spec authoring (_sieAuthoringContext -> lessons_block, called once per subtask), the Ollama brain receives a confidently-labelled but irrelevant 'RELEVANT PAST LESSONS' section. This pollutes the prompt with noise that can steer
- **Fix:** Introduce a config RETRIEVAL_MIN_SCORE (e.g. 0.35) and filter in top_k_similar (drop rows with score < floor) AND/OR have render_lessons skip neighbors whose 'score' is below the floor. Also guard cosine length-mismatch as a hard skip (treat len(a)!=len(b) as 'not comparable' and exclude, rather than score 0.0 that still sorts into the top-K when t

## [35] MEDIUM — eval_harness.py 107-140 (run_suite), 36-63 (ag
**Empty/missing eval suite records a fabricated 'scored' fitness of 0.5 into the progress series**

- **Root cause:** run_suite(runner=...) only takes the transparent 'no_runner' marker branch when runner is None. When a runner IS supplied but load_suite() returns [] (the suite dir learning/eval_suite is empty, renamed, or misconfigured), the `for goal in goals` loop runs zero times, results=[], and score([]) -> aggregate([]) returns the n==0 neutral defaults {first_pass_rate:0, norm_attempts:0, norm_cost:0, plan_stability:1.0, challenge_rate:0}. compute_fitness then yields a fixed, non-trivial scalar: 0.5*0 + 
- **Impact:** The fitness series is the system's headline, months-long 'proof it is getting better' surface (fitness_panel sparkline in Discord/web, release.write_report, adapter_ops.overfit_signal). A misconfigured/empty suite silently injects fabricated 0.5 poin
- **Fix:** In run_suite, after load_suite, treat an empty goal list the same as no runner: if not goals, record/return a transparent marker payload {status:'empty_suite', suite_size:0} instead of scoring []. Alternatively make aggregate([]) / score([]) refuse to emit a fitness for n==0 (return status 'empty' with no 'fitness' key) so it can never be plotted a

## [36] MEDIUM — core.py 96-110 (on_message -> handleCo
**Gateway control handlers run blocking ControlBus file IO (with time.sleep backoffs) directly on the asyncio event loop**

- **Root cause:** Every gateway control path applies commands synchronously on the bot's single event-loop thread without asyncio.to_thread. on_message calls handleCommand(message.content) directly (core.py:105); slash._runControl calls commands.applyCommand inline (slash.py:48); views._applyControl/_skipCurrent call applyCommand inline (views.py:31,52); the dynamic SubtaskButton.callback and plan_cog modal call applyCommand/pushOp inline. All of these route into ControlBus._mutate -> _fileLock (a cross-process O
- **Impact:** Gateway-wide stall: while one control handler is blocked in synchronous file IO on the loop, no other slash command, button, message, or heartbeat is serviced. Repeated contention can accumulate to multi-second freezes and, in the worst case, a heart
- **Fix:** Wrap every gateway-side ControlBus mutation/read in asyncio.to_thread, e.g. msg = await asyncio.to_thread(commands.applyCommand, ControlBus(state.task_id), state, cmd) in slash._runControl, views._applyControl, views._skipCurrent, core.handleCommand path, dynamic.SubtaskButton.callback, and the plan_cog pushOp calls. ControlBus construction (which 

## [37] MEDIUM — core.py 96-110 (on_message) vs orchest
**When the gateway bot and an active run coexist, a single '!add' (and !skip/!retry) is applied twice -> duplicate subtasks**

- **Root cause:** Two independent consumers read the same Discord channel with no shared dedup. The gateway's on_message handles every '!' message in DISCORD_CHANNEL_ID and calls handleCommand -> applyCommand -> bus.pushOp({'op':'add',...}). The orchestrator run's _translateDiscord ALSO fetches that same message via fetchMessagesAfter and calls applyCommand -> bus.pushOp({'op':'add',...}). The poller's seen_discord_id cursor is private to the run and does not suppress the gateway, and vice-versa. _applyOps then d
- **Impact:** Plan corruption: duplicated subtasks (wasted executor cycles, double work, skewed progress X/Y) whenever the standalone gateway is run alongside a live run. abort/pause/approve/reject are idempotent so they're unaffected, but add/retry are not.
- **Fix:** Make plan-op enqueue idempotent or single-source the channel poll. Options: (a) when a run is active, have the gateway NOT apply mutating '!' commands itself and let the run's poller be the sole consumer (or vice-versa); (b) tag each pushOp with the originating Discord message id and have _applyOps de-duplicate ops by message id; (c) share the seen

## [38] MEDIUM — health.py 55-72 (_claudeCli), 60-63
**/health Claude CLI check orphans node/claude grandchildren on its 40s timeout (Windows process-tree leak)**

- **Root cause:** _claudeCli launches a FULL agent session via `subprocess.run(launcher + ["--print", ...], timeout=40)` where on Windows `launcher = ["cmd", "/c", exe]` because shutil.which("claude") returns the npm shim claude.cmd. subprocess.run's timeout handling kills only the DIRECT child (cmd.exe); the real worker is the grandchild node/claude process it spawned, which is left running. This is exactly the Windows orphan failure mode documented in config.py:162-164 that the executor specifically fixed with 
- **Impact:** Each timed-out /health run leaks a detached claude/node agent that continues consuming CPU/tokens and may hold file handles in PROJECT_ROOT. Because collectHealth() is also callable from the gateway bot's /diagnostics, repeated diagnostics under a de
- **Fix:** Kill the whole process tree on timeout the way the executor does: spawn with subprocess.Popen + CREATE_NEW_PROCESS_GROUP, and on TimeoutExpired call the existing executor._killProcessTree (or `taskkill /F /T /PID`) before returning, instead of relying on subprocess.run's single-child kill.

## [39] LOW — hooks.py 344-353 (with config.py:485)
**Default 'state/tasks' hard boundary false-blocks a target project that has its own state/tasks directory**

- **Root cause:** `UNIVERSE_DEFAULT_HARD_BOUNDARIES` (config.py:485) always injects `state/tasks` as a hard boundary for EVERY task (added in extractUniverse and re-enforced in _boundarySetFor), intended to protect 9to5's OWN task store. The guard's match (agents/hooks.py:344-353) blocks any edit whose normalized path contains `\state\tasks\` as a path segment. For a non-self-referential run whose --work-dir is an unrelated project that legitimately contains a `state/tasks/` directory (a common path), an Edit/Wri
- **Impact:** 9to5 cannot edit a legitimately-in-scope `state/tasks/...` file in a user's target project; the run silently degrades / the subtask fails on a false-positive safety refusal. The baseline boundary is path-relative (segment match) rather than anchored 
- **Fix:** Anchor the 9to5-internal baseline boundaries (state/tasks, and arguably venv) to the 9to5 INSTALL_ROOT/PROJECT_ROOT absolute path rather than matching the bare relative segment anywhere; only apply the relative-segment form when the edit target is under config.PROJECT_ROOT. Keep `.env`/`.git` as relative (those are universally sensitive), but make 

## [40] LOW — orchestrator.py 335-358 (specifically 352) — ✅ ALREADY FIXED (cluster dup)
**Planner/replanner JSON salvage still uses the greedy-regex span bug that llm_io.responseJson was created to fix**

- **Root cause:** A new module, llm_io.py, was introduced specifically to fix a JSON-extraction bug: its docstring states the naive `re.search(r"\{.*\}", text, re.DOTALL)` is 'maximally greedy: on any output that contains two separate JSON objects it spans from the first `{` to the LAST `}`, producing a concatenated blob that fails json.loads.' llm_io.responseJson replaces it with `_firstBalancedObject` (a depth-aware, string-literal-aware brace walk). However orchestrator.py keeps its OWN private `_chatJson` (li
- **Impact:** When the 7B brain wraps or appends a second object around its JSON (a known qwen2.5 failure mode the surrounding code explicitly guards against elsewhere), the planner/replanner discards a recoverable plan and silently degrades to the fallback plan i
- **Fix:** Delete orchestrator._chatJson's body and delegate to the fixed helper: `return llm_io.responseJson(resp)` (it already takes the raw response and runs responseText + fence-strip + _firstBalancedObject). This removes the duplicated greedy-regex line 352 and guarantees the loop's JSON salvage matches the hardened extractor. No other call-site changes 

## [41] LOW — orchestrator.py 1014-1039; 2218
**Gated pre_pr gate at the deadline overwrites a fully-completed run's status with 'aborted'**

- **Root cause:** In gated mode, after the execution loop finishes with ALL subtasks done, runFull calls _checkControl(..., gate='pre_pr') (line 2218). The gate wait loop (lines 1019-1039) blocks for a human approve/reject. If the deadline passes first, line 1034 raises AbortRun('gate timed out at deadline'). That propagates to runFull's AbortRun handler (line 2293) which calls state.setStatus('aborted'), overwriting the otherwise-'done' outcome. The completed, verified work is thus reported as 'aborted' with no 
- **Impact:** A gated unattended run whose work fully succeeded is mislabeled 'aborted' and produces no completion record/PR if the human is absent at the deadline. The completed state is lost in the summary/dashboard/Discord embed (shows aborted, not done/partial
- **Fix:** On the pre_pr-gate deadline timeout, do not raise AbortRun; instead break out of the gate wait, skip PR creation (conservative: don't auto-ship in gated mode), and let runFull finalize with the real done/partial status plus a 'PR held: gate not approved before deadline' notification. Reserve AbortRun for an explicit reject/abort.

## [42] LOW — ask_cog.py 39-45
**/ask natural-language control can ABORT a run with no confirmation, unlike every other abort surface**

- **Root cause:** detectControlIntent maps short imperatives like 'stop'/'kill'/'cancel'/'abort' to the 'abort' verb (ask.py:_INTENTS), and ask_cog applies it directly via applyCommand(... Command('abort','')) after only an isAuthorized check. Every other abort entry point (slash.py abort:166-178, views.ControlPanelView.abort:103-107, views.BlockedView.abort:136-141) routes through confirmDestructive() and requires an explicit Confirm click. The /ask path skips that confirmation entirely.
- **Impact:** An accidental or ambiguous phrasing ('cancel that', 'kill it') silently aborts a long-horizon run with no undo and no confirmation step, defeating the deliberate confirm guard the other surfaces enforce. Bounded by being owner-only and config-gated (
- **Fix:** Route the NL-control 'abort' (and any destructive verb) through the same confirmDestructive flow used by slash/buttons, or require an explicit confirmation reply before applying an NL-inferred abort.
