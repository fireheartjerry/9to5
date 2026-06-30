# Epic 1 — Durable Execution (Design Spec)

> **Date:** 2026-06-30 · **Status:** design (no code changed) · **Mode:** READ-ONLY harvest → spec.
> Harvested from `docs/references-harvest/` (MASTER steals #1, #5, #7). All three steals are
> MIT/Apache and share one seam: the **executor stdout stream tap** (`notifications/subprocess_feed.py`)
> + **`state/experience.db`** + **git**. `claude-code` is ideas-only (proprietary) — the worktree
> pattern is ported from **hermes** (`tools/environments/base.py`) and **guild**
> (`internal/quest/{accept,bounties}.go`), never from claude-code source.

---

## 1. Goal

Give 9TO5 mid-subtask crash durability, isolated parallel workers, and a cost-aware run trace by
adding (1) a step-level pending-writes journal that resumes from the last completed step, (2)
worktree-per-subtask isolation with a file-disjointness + atomic-CAS claim, and (3) a JSON span-tree
trajectory recorder with token/USD cost and orchestrator→executor spawn linking — closing brief gaps
**#3** (mid-subtask checkpoint/resume), **#6** (sandboxed/isolated executor), **#7** (multi-agent
topology / stop clobbering one tree), and **#5** (structured tracing + cost metrics).

## 2. Non-Goals

- **No new source of truth.** Run state stays owned by the state store (`state/task_schema.py`),
  control by `ControlBus` (`platform_core/runtime/control.py`), verification by the verifier
  (`agents/verifier.py`). The journal and trajectory are durable **observability/replay artifacts**;
  the resume *decision* still derives from committed state + a plan-signature guard, never from the
  journal alone.
- **No Docker/microVM/E2B backend.** Worktree is the only isolation tier this epic ships (hermes'
  `BaseEnvironment` interface is honored so a container backend can be added later — out of scope now).
- **No durable-workflow rewrite.** We do not model the executor loop as Temporal/DBOS/Smithers steps
  (eliza/pydantic-ai heavyweight target); we journal the existing attempt loop.
- **No OTel SDK / external trace backend.** File-based span tree only (eliza shape), matching 9TO5's
  no-logs-as-truth, file-state ethos. `gen_ai.*` schema not adopted here.
- **No planner/verifier changes.** Steals #2/#3/#9 ("trustworthy 7B loop") are a separate epic.
- **No time-travel/fork or run-wide undo.** The journal *enables* these later; not built now.

## 3. Architecture

Four small units, each fail-open. New modules respect the `≤450-line file / ≤70-line function`
thresholds and carry the `@AI-MAP v1` doc header; new ledger logic follows the established
`experience_<domain>.py` submodule + facade re-export pattern.

### (a) Step-journal schema + write path  *(steal #1 — LangGraph `put_writes`)*

**What it does.** Durably appends each completed executor step (one Claude tool call) as a row in
`experience.db`, keyed `(run_id, subtask_id, attempt, step_idx)` — the exact shape of LangGraph's
`writes` table (`references/langgraph/libs/checkpoint/.../base/__init__.py` `put_writes`,
`WRITES_IDX_MAP`; SQLite-native twin: `references/swarmclaw/src/lib/server/langgraph-checkpoint.ts`
`langgraph_writes`). 9TO5 already parses these tool calls in `SubprocessFeed._parse` for presentation
only — we tee the same parsed event to a durable sink.

- **Schema** — append one `CREATE TABLE IF NOT EXISTS step_journal` statement to
  `memory/experience_schema.py::_SCHEMA` (the module's documented extension point — no migration
  machinery): columns `run_id, subtask_id, attempt, step_idx, kind, tool, summary, input_json,
  plan_sig, session_id, ts`, with `UNIQUE(run_id, subtask_id, attempt, step_idx)` so a crash-resume
  upserts idempotently (matches the ledger's existing idempotency rule). Add an index
  `idx_journal_attempt ON step_journal(run_id, subtask_id, attempt)`.
- **Interface** — new submodule `memory/experience_journal.py`, re-exported through the
  `memory/experience.py` facade (like `experience_subtasks.py`):
  - `appendStep(run_id, subtask_id, attempt, step_idx, kind, tool, summary, input_obj, plan_sig, session_id) -> None`
  - `loadSteps(run_id, subtask_id, attempt) -> list[dict]`
  - `lastStepIdx(run_id, subtask_id, attempt) -> int` (−1 if none)
  - `markAttemptSuperseded(run_id, subtask_id, attempt) -> None` (resume bookkeeping)
  Every function wraps its DB work the way `experience.sync_subtask` does — a ledger failure logs a
  warning, never raises.
- **Write hook** — extend `SubprocessFeed.__init__` with an optional `on_step: Callable | None`
  callback; in `consume()`, after `self.bus.emit(event)`, call `self._emit_step(event)` which invokes
  `on_step(step_idx, tool, summary, input)` best-effort. **subprocess_feed keeps its narrow
  `DEPENDS-ON: notifications.event_bus`** — it never imports the ledger; the orchestrator injects the
  sink. `platform_core/orchestration/execute_mixin.py::_runOneAttempt` (where the feed is already
  constructed, lines ~186-188) builds the sink via
  `journal.makeSink(state.task_id, sid, attempt, plan_sig, lambda: resume_session)` and passes it as
  `SubprocessFeed(get_bus(), sid, time.monotonic(), on_step=sink)`.
- **Depends on:** `memory.experience_schema` (DB), the existing JSONL tap, `state.task_id`.

### (b) Resume-from-last-step path  *(steal #1 consumer — AGX `resume.js` + MAF graph-sig gate)*

**What it does.** Replaces the blind `in_progress → pending` reset in
`run_phase_mixin.py::_resumeSetup` (lines 107-109) with a journal-aware reconcile that keeps a crashed
subtask resumable, reconstructs an AGX-style step-level resume prompt, and rejects a stale resume when
the plan changed underneath it (MAF `_hash_graph_signature`,
`references/ms-agent-framework/.../_workflows/_checkpoint.py`).

- **Interface** — new module `platform_core/orchestration/step_resume.py`:
  - `planSignature(state) -> str` — stable hash over the task graph (each subtask's `subtask_id`,
    `title`, `depends_on`, and `verify.cmd`). Recorded on every journal row at write time; compared on
    resume. (MAF's restore-compat hash; cheap correctness guard for the self-edit-inert problem.)
  - `resumePlan(state, subtask, steps) -> dict` — AGX `resume.js` reconstruction: a token-budgeted
    block of `Done-When` criteria and plan steps marked `[x]` (completed, from the journal) / `[→]`
    (current) / `[ ]` (remaining), plus the **stability footer** *"Continue from the current step. Do
    NOT rewrite the plan or redo completed steps."* Returns `{resume_block, session_id, current_idx}`.
  - `reconcileResume(state) -> None` — for each `in_progress` subtask: if `planSignature(state)`
    matches the journal rows' `plan_sig` **and** `lastStepIdx ≥ 0`, mark it `resumable` and stash
    `resume_block` + the last healthy `session_id` on `subtask["session"]` (via
    `state.updateSubtask` — **state store still owns the mutation**); otherwise fall back to today's
    behavior (reset to `pending`, fresh attempt, journal attempt superseded).
- **Replay-skip semantics.** 9TO5 steps are *side-effecting file edits already on disk* (the work
  tree / worktree persists across the crash), so resume **informs, it does not re-execute**: the
  executor is told what is done and continues the same Claude session. `agents/executor.py::_prepareEnv`
  already folds context into the resume prompt and carries `--resume <session_id>` robustly (and
  already retries once on a fresh session if the session is unresumable, lines 207-211) — we reuse that
  path. `execute_mixin._runOneAttempt` reads `subtask["session"]["resume_block"]` + `resume_session_id`
  on attempt 1 of a `resumable` subtask and threads them as the resume context + `resume_session`.
- **Durable session id.** Persist the last healthy `session_id` (already extracted by
  `executor_stream._parseEnvelope`, surfaced as `result["session_id"]`) into
  `subtask["session"]["resume_session_id"]` on each non-error attempt, so a *process* crash (not just a
  retry) can resume — today `resume_session` lives only in a loop-local and dies with the process.
- **Depends on:** `memory.experience_journal`, `state.task_schema`, `agents.executor` (unchanged API).

### (c) Worktree-per-subtask + file-disjointness + atomic CAS claim  *(steal #5 — hermes/guild)*

**What it does.** Each parallel worker runs in its own git worktree; two subtasks run concurrently
only if their file-sets are disjoint and neither depends on the other; work is grabbed with a race-free
claim. This removes the reason `_remediationTreeShared` exists (a snapshot/restore would clobber peers)
so it can be **deleted** and adversary remediation re-enabled under parallelism.

- **Worktree backend** — new module `platform_core/runtime/worktree.py`, modeled on hermes'
  `BaseEnvironment` ABC (`references/hermes/tools/environments/base.py`) with a single concrete
  worktree backend (the claude-code `EnterWorktree` *pattern*, ported from hermes/guild, not its code):
  - `enterWorktree(state, sid) -> str` — `git worktree add` a branch `wt/<task8>/<sid>` off `HEAD`
    into `state/.sc-worktrees/<task8>/<sid>`; returns the path. **Fail-open:** any git error logs and
    returns the shared `work_dir` (degrades to today's behavior).
  - `exitWorktree(path, *, merge: bool) -> None` — on success `git merge --no-edit` the worktree
    branch back into the run branch then `git worktree remove`; on failure leave it for inspection.
  - `removeWorktree(path)` / `gcOrphans(state)` — TTL/whitelist cleanup (eliza
    `workspace-lifecycle.ts` `gcOrphanedWorkspaces`, path-scoped safe-remove refusing paths outside
    `state/.sc-worktrees/`).
- **Parallel-safety + claim** — new module `platform_core/orchestration/parallel_safety.py`, porting
  guild `bounties.go` + `accept.go`:
  - `filesTouched(subtask) -> set[str]` — from a new optional `files_touched` subtask field
    (planner-authored); **empty set ⇒ treat as conflicting** (conservative: serialize), so an
    un-annotated plan is never *less* safe than today.
  - `disjoint(a, b) -> bool` and `safeParallelSet(state, ready, limit) -> list[dict]` — greedily pick
    ready subtasks whose file-sets are pairwise disjoint and dependency-free (guild's "parallel-runnable
    iff file-sets disjoint AND no dep conflict").
  - `claim(state, sid) -> bool` — the atomic CAS: under the existing `self._state_lock`, re-read the
    subtask and set `pending → in_progress` **only if still `pending`** (rowcount-0 analogue → `False` =
    lost race). Preserves state-store ownership; maps guild's single-statement
    `UPDATE … WHERE status='next' AND claimed_by IS NULL` onto 9TO5's locked `updateSubtask`.
- **Schema** — `state/task_schema.py::addSubtask` gains `files_touched: list[str] = []` and
  `claimed_by: str | None = None` (additive, default-safe; no facade break).
- **Wiring** — `run_loop_mixin.py::_handleParallelBatch` (line 165) derives its batch from
  `parallel_safety.safeParallelSet(state, ready, parallelism)`, `claim()`s each, runs each in an
  `enterWorktree` cwd, `exitWorktree(merge=True)` after. `_remediate`
  (`execute_mixin.py:46`) snapshots `exec_cwd` (now the isolated worktree) instead of the shared
  `self._work_dir`, so keep-or-revert is peer-safe. `_remediationTreeShared`
  (`review_mixin.py:119`) and its skip-branch in `_runAdversaryReview` (`execute_mixin.py:290-296`) are
  removed; when the worktree backend falls back to the shared tree, a residual guard
  `worktree.isIsolated(exec_cwd)` gates remediation instead.
- **Depends on:** git, `state.task_schema`, `_state_lock`, `run_loop.py::_execCwd` (worktree path
  supersedes the `.sc-ctx` scratch for parallel runs).

### (d) Trajectory span-tree recorder + cost + spawn linking  *(steal #7 — eliza/swarmclaw)*

**What it does.** One append-only JSON span tree per run = the structured trace + consistent per-step
token/USD cost series 9TO5 lacks, with the orchestrator→executor-subprocess spawn link that fixes the
trace-continuity hole. Ported from eliza `trajectory-recorder.ts` + `services/spawn-trajectory.ts`,
cost windows from swarmclaw `cost.ts`.

- **Interface** — new module `platform_core/runtime/trajectory.py`:
  - `Recorder(run_id)` writing `state/trajectories/<run_id>.json` with **atomic tmp+rename**;
    **every method swallows its own errors — the recorder must never crash a run** (eliza invariant).
  - `openSpan(kind, parent_id, attrs) -> step_id` / `closeSpan(step_id, usage=None, cost_usd=None)`;
    `kind ∈ {architect, planner, executor, tool, verify, adversary, replan, remediation}`.
  - `RecordedUsage` from the envelope `usage` (incl. cache tokens) + `cost_usd` from
    `total_cost_usd` (already parsed in `executor_stream._parseEnvelope`); **local Ollama brain calls
    record a real `0`** cost while keeping the token series (eliza's honest-zero rule).
- **Spawn linking.** The orchestrator opens an `executor` span around `hands(spec, …)` in
  `_runOneAttempt` and passes its `step_id` to the subprocess via env var
  `NINE_TO_FIVE_PARENT_TRAJECTORY_STEP_ID` (eliza's `ELIZA_PARENT_TRAJECTORY_STEP_ID` pattern); the
  `on_step` sink from unit (a) opens child `tool` spans under it, so the per-tool-call stream stitches
  into the subtask span. One `on_step` callback fans to **both** the journal (a) and the recorder (d).
- **Cost budget bolt-on** — thin `platform_core/runtime/cost_budget.py`: rolling per-run cost sum over
  the trajectory's cost series; emits an 80%-warn and a hard-ceiling `Event` on `event_bus` (swarmclaw
  h/d/m windows, simplified to per-run). Optional within the epic; gated behind a config flag, off by
  default.
- **Depends on:** `executor_stream` envelope (read-only), `notifications.event_bus`, the (a) sink.

## 4. Data flow — one subtask: claim → journal → crash → resume

1. **Claim.** `_handleParallelBatch` computes `ready = _readySet(state)`,
   `batch = parallel_safety.safeParallelSet(state, ready, parallelism)`; for `st` in batch,
   `parallel_safety.claim(state, st)` flips `pending → in_progress` under `_state_lock` (lost race ⇒
   skipped). `planSignature(state)` is computed once.
2. **Isolate.** `worktree.enterWorktree(state, sid)` returns an isolated cwd `exec_cwd` (or the shared
   tree on fail-open).
3. **Trace + journal open.** `_runOneAttempt` opens an `executor` trajectory span (parent = subtask
   span), exports `NINE_TO_FIVE_PARENT_TRAJECTORY_STEP_ID`, and builds the `on_step` sink. The feed
   taps stdout: each Claude tool call → `appendStep(run_id, sid, attempt=1, step_idx=k, kind="tool",
   tool, summary, input, plan_sig, session_id)` **and** a child `tool` span. Edits land in the worktree.
4. **Crash** at step `k=7` (kill/deadline/process death). `resilience.run_with_recovery` reloads
   committed state (`reload_state`); the subtask is `in_progress`, journal has steps `0..7`, the last
   healthy `session_id` is on `subtask["session"]`.
5. **Resume.** Fresh process → `_resumeSetup` calls `step_resume.reconcileResume(state)`:
   `planSignature` matches the journal `plan_sig` and `lastStepIdx=7 ≥ 0` ⇒ subtask kept `resumable`,
   `resumePlan` builds the `[x]0-7 / [→]8 / [ ]…` block + stability footer + stashes `session_id`.
6. **Continue, don't redo.** `_executeSubtask → _runAttemptLoop → _runOneAttempt` reads the resume
   block + `resume_session_id`; `executor.runClaude` re-invokes with `--resume`, folding the block into
   the resume prompt (CLAUDE.md isn't re-read on resume). Claude continues from step 8; completed edits
   are already on disk, not re-applied. New steps journal as `attempt` continues; the span tree extends.
7. **Finish.** verify (unchanged) → `exitWorktree(merge=True)` lands the branch → `closeSpan` records
   final `cost_usd`/`usage`. *If `planSignature` had mismatched* (plan mutated during downtime),
   reconcile resets the subtask to `pending`, supersedes the journal attempt, and the subtask reruns
   clean — today's safe behavior.

## 5. Exact file structure

**New files**
| Path | Responsibility |
|---|---|
| `memory/experience_journal.py` | `step_journal` DML: `appendStep` / `loadSteps` / `lastStepIdx` / `markAttemptSuperseded` (fail-open). |
| `platform_core/orchestration/step_resume.py` | `planSignature`, `resumePlan` (AGX reconstruction + stability footer), `reconcileResume` (plan-sig gate). |
| `platform_core/runtime/worktree.py` | hermes-style env interface + git-worktree backend: `enterWorktree` / `exitWorktree` / `gcOrphans` / `isIsolated` (fail-open to shared tree). |
| `platform_core/orchestration/parallel_safety.py` | guild port: `filesTouched`, `disjoint`, `safeParallelSet`, atomic `claim`. |
| `platform_core/runtime/trajectory.py` | eliza-style file span-tree recorder: `Recorder`, `openSpan`/`closeSpan`, usage+USD cost, atomic write, never-crash. |
| `platform_core/runtime/cost_budget.py` | swarmclaw cost windows: per-run sum + 80%-warn/hard-ceiling alert (config-gated, off by default). |

**Modified files**
| Path | Change |
|---|---|
| `memory/experience_schema.py` | Append `step_journal` CREATE + index to `_SCHEMA`. |
| `memory/experience.py` | Re-export `experience_journal` public names through the facade. |
| `notifications/subprocess_feed.py` | Add optional `on_step` callback + `_emit_step`; no new module deps. |
| `platform_core/orchestration/execute_mixin.py` | Wire journal+trajectory sink and worktree enter/exit into `_runOneAttempt`; persist `resume_session_id`; consume `resume_block`; `_remediate` snapshots `exec_cwd`; drop the `_remediationTreeShared` skip branch in `_runAdversaryReview`. |
| `platform_core/orchestration/run_phase_mixin.py` | `_resumeSetup` calls `step_resume.reconcileResume` instead of blind `in_progress→pending`. |
| `platform_core/orchestration/run_loop_mixin.py` | `_handleParallelBatch` uses `safeParallelSet` + `claim` + worktrees. |
| `platform_core/orchestration/review_mixin.py` | Remove `_remediationTreeShared`; add `worktree.isIsolated` residual guard. |
| `state/task_schema.py` | `addSubtask` gains `files_touched` + `claimed_by`; helper to persist `resume_session_id` on `subtask["session"]`. |

Regenerate `AGENTS.md` via `python tools/repo_map.py` after the new modules land (exported-structure change).

## 6. Error handling + fail-open principle

**Journaling and tracing must NEVER crash a run** — they are best-effort, like the existing SIE ledger
sinks (`task_schema._ledgerSubtask`) and `subprocess_feed`'s own raw-line tolerance.

- Every `experience_journal` and `trajectory` method wraps its body in `try/except Exception` → log
  warning, return safe default. A locked/poisoned DB connection is already evicted by
  `experience_schema._connect`; trajectory uses atomic tmp+rename so a crash mid-write never corrupts
  the file (eliza/MAF discipline).
- `worktree.enterWorktree` **degrades to the shared tree** on any git error; `safeParallelSet` returns
  `[ready[0]]` (serialize) if disjointness can't be computed; `claim` returning `False` simply skips
  the subtask — all paths reduce to today's behavior, never worse.
- `reconcileResume` defaults to the current safe reset (`in_progress → pending`) whenever the plan-sig
  mismatches, the journal is empty/unreadable, or the session id is missing — a bad resume can only
  cost a clean rerun, never a corrupt one.
- The recorder's spawn-link env var is advisory; a missing parent id yields a root-level span, not an
  error. Cost-budget alerts are emitted via `event_bus` (which already drops on a full queue) and never
  abort a run (guild's critical/observability write-split principle).

## 7. Testing strategy

Pytest, per 9TO5 conventions (`.claude/rules/tests.md`); use `python tools/dev.py check <file>` for
focused edits and `python tools/dev.py fast` before handoff. Run locally via **pytest**, not bare
unittest (conftest sandboxes Discord/Ollama only under pytest).

- `tests/test_experience_journal.py` — `appendStep` then `loadSteps` round-trip; `UNIQUE` upsert is
  idempotent across a simulated resume (no double rows); `lastStepIdx` correctness; a forced DB error
  logs and returns a safe default (fail-open).
- `tests/test_step_resume.py` — `planSignature` stable under no-op reload, changes when a `verify.cmd`
  or `depends_on` mutates; `reconcileResume` keeps `in_progress` + stashes a resume block on sig-match,
  resets to `pending` on sig-mismatch and on empty journal; `resumePlan` emits `[x]/[→]/[ ]` markers
  and the stability footer.
- `tests/test_parallel_safety.py` — `disjoint`/`safeParallelSet` pick non-conflicting subtasks;
  empty `files_touched` serializes; `claim` returns `True` once and `False` on the lost-race second
  call (simulated concurrent claim under the lock).
- `tests/test_worktree.py` — `enterWorktree`/`exitWorktree(merge=True)` on a temp git repo; fail-open
  returns the shared tree when git is unavailable; `gcOrphans` refuses paths outside
  `state/.sc-worktrees/`. (Skip-guard if `git` absent in CI.)
- `tests/test_trajectory.py` — span-tree shape (parent/child via the spawn link), atomic write leaves
  no partial file, Ollama call records cost `0` with a non-empty token series, every method is
  exception-safe (inject a write error → no raise).
- **Regression:** extend/replace `tests/test_remediation_tree_shared.py` to assert remediation now runs
  under parallelism in an isolated worktree (the gate the epic removes). Keep `tests/test_resilience.py`
  green (resume path still terminal/deadline-aware) and `tests/test_subprocess_feed.py` green (feed
  works with `on_step=None`).

## 8. Risks / open issues + sequencing

**Sequencing (low-risk → high-risk):**
1. **(d) Trajectory recorder** — pure additive observability, zero behavior change; lands first and
   de-risks the `on_step` fan-out wiring.
2. **(a) Step-journal write path** — additive + fail-open; produces the journal that (b) consumes.
3. **(b) Resume-from-last-step** — first behavior change; the plan-sig guard makes a bad resume degrade
   to today's safe reset. Land behind a config flag (e.g. `STEP_RESUME_ENABLED`, default on after soak).
4. **(c) Worktree + parallel-safety + CAS** — largest change (removes `_remediationTreeShared`,
   re-enables remediation under parallelism); land behind a flag (`WORKTREE_ISOLATION_ENABLED`, default
   off → on after soak) so it can ship dark.

**Risks.**
- *Windows git worktree* — path length, file locks, and `git worktree remove` on a busy tree; the
  fail-open-to-shared-tree path is the safety net, but worktree must be soaked on Windows before
  default-on.
- *`files_touched` reliability* — the 7B planner may not author it; conservative empty-set-serializes
  keeps it safe but can collapse parallelism to serial. Mitigation/open item below.
- *Resume of side-effecting steps* — correctness hinges on "inform, don't re-execute"; a step that was
  *partially* applied at crash time (half-written file) is the residual hazard. The worktree + the
  executor's own re-read on resume mitigate; verify still gates the final state.
- *experience.db WAL contention* — N parallel workers + the journal add write pressure; the existing
  `_WRITE_LOCK` + pooled connections handle it, but journal writes must stay tiny (one row/tool call).
- *Trajectory file growth* — bounded per run; add a size cap / tail-trim if a run emits thousands of
  tool calls.

**Open issue (needs a decision — see summary):** how file-sets are determined for the disjointness
test — planner-authored `files_touched` vs. a derived heuristic (e.g. architect-doc / discovery
findings, or a read-only dry-run). Affects how much real parallelism (c) unlocks.

## 9. Success criteria

- A subtask killed mid-attempt **resumes from its last journaled step** (continues the Claude session,
  does not re-run completed edits) when the plan signature is unchanged; a changed plan signature
  **safely rerolls** the subtask to `pending`. Demonstrated by `test_step_resume.py` + a kill/resume
  integration check.
- `experience.db` contains a queryable `step_journal` row per executor tool call, keyed
  `(run_id, subtask_id, attempt, step_idx)`, written fail-open (a journal error never aborts a run).
- Two file-disjoint subtasks run **concurrently in separate worktrees**, an atomic claim prevents
  double-execution, and **adversary remediation runs under parallelism** (the `_remediationTreeShared`
  skip is gone) without clobbering peers.
- Each run produces one `state/trajectories/<run_id>.json` span tree with parent→child
  orchestrator→executor linking and a per-step token/USD cost series (Ollama brain = real `0`), written
  atomically and never crashing the run.
- `python tools/dev.py fast` is green; `AGENTS.md` regenerated; zero `must_split` violations
  (`python tools/size_audit.py`).
