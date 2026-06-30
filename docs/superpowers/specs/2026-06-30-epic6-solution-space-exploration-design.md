# Epic 6 — Solution-Space Exploration (Design Spec)

> **Date:** 2026-06-30 · **Status:** design (no code changed) · **Mode:** READ-ONLY harvest → spec.
> Harvested from `docs/references-harvest/` — bernstein `core/orchestration/best_of_n.py` +
> `eval/judge.py` (Apache-2.0, portable), swarmclaw `agents/subagent-swarm.ts` + `eval/scorer.ts`
> (MIT, portable), metagpt `actions/action_node.py` `auto_review` + `write_code_review.py` (MIT,
> portable). loom (`specs/spool-system.md`, `specs/auto-commit-system.md`) and claude-code
> (`coordinator/coordinatorMode.ts`, `tools/EnterWorktreeTool/`) are **proprietary — ideas only**;
> their branch-per-line and worktree-isolation *patterns* are realized through Epic 1's already-ported
> `platform_core/runtime/worktree.py`, never from their source.
>
> **Transformative capability.** Today 9TO5 runs ONE linear trajectory per subtask: a bounded
> retry-on-failure loop (`platform_core/orchestration/execute_mixin.py::_runAttemptLoop`,
> `MAX_SUBTASK_ATTEMPTS=3`). This epic adds the ability, for *suitable* subtasks, to FORK N diverse
> approaches in parallel isolated worktrees, run them concurrently, then have a JUDGE PANEL select the
> winning result (optionally grafting runner-up ideas). **Quality via diversity + selection instead of
> one shot.**

---

## 1. Goal

Replace the single-trajectory subtask attempt, *for fork-worthy subtasks only*, with **parallel
solution-space exploration**: fork N diverse executor branches in isolated git worktrees, run them
concurrently, score each with an execution-grounded judge panel, merge the winner into the canonical
tree, and GC the losers — elevating gap **#1 (planning/solution quality:** best-of-N beats one-shot)
and gap **#2 (verification-as-selection:** the verifier stops being only a pass/fail gate and becomes
the *ranking* signal that chooses among real, executed candidates).

## 2. Non-Goals — when forking is NOT worth the cost

Forking costs **N× the executor tokens + wall-clock** of a subtask. It must be the exception, not the
default. This epic explicitly does **NOT**:

- **Fork every subtask.** `fork_policy.shouldFork` (§3a) gates hard: trivial / mechanical / low-effort
  / doc-only / single-obvious-answer subtasks keep the existing `_runAttemptLoop` path untouched.
  Default-off globally (`SOLUTION_FORK_ENABLED=False`) so the epic ships dark.
- **Fork without a cost ceiling.** A projected `N × effort` spend over the run budget (Epic 1
  `platform_core/runtime/cost_budget.py`) **downgrades to a single attempt** before any branch spawns.
- **Replace the retry loop.** Within one branch, the executor still runs the normal verify-retry loop;
  forking is a layer *above* the attempt loop, not a replacement for it.
- **Do tree-of-thought / recursive forking.** Branches do not themselves fork (no fork bomb); one fork
  generation per subtask, bounded N. (warp's "children forbidden to self-recurse" discipline,
  `themes/orchestration-planning.md` #20.)
- **Own verification or run state.** The judge *reads* the Epic 2 execution-grounded verifier; the
  verifier still owns status, the state store still owns run state, `ControlBus` still owns control.
  Branches are ephemeral; only the winner's outcome is ever committed to the subtask (§3d).
- **Graft by raw git-merging two branches.** Grafting runner-up ideas is **advisory** (a remediation
  pass fed the runner-up diff), never an automatic multi-branch merge — to avoid merge-conflict hell
  (§3d, gated off by default).
- **Add HTN/search-based planning.** Diversity here is *parallel sampling of one subtask*, not
  search over the task graph (that stays Epic 2's dual-ledger concern).

## 3. Architecture (small units + interfaces)

Five small fail-open units. Each new module carries the `@AI-MAP v1` header, respects the
`≤450-line file / ≤70-line function` thresholds, and uses `camelCase` funcs / `snake_case` vars /
`ALL_CAPS` consts. A thin coordinator (`solution_space.py`) ties them together and exposes ONE seam to
`execute_mixin.py`. **This epic structurally depends on Epic 1 (worktree isolation, trajectory) and
Epic 2 (the execution-grounded verifier/judge) — see §8.**

### (a) Fork policy — which subtasks fork, how many, how diversity is seeded

**Source:** bernstein `best_of_n.py` (the `best_of_n=K` flag, K∈2–5); warp bounded-fan-out recursion
budget (`themes/agent-comms-topology.md` #17).

New module `platform_core/orchestration/fork_policy.py`:

- `shouldFork(state, subtask, projected_cost) -> bool` — fork only when **all** hold:
  - global flag `config.SOLUTION_FORK_ENABLED` is on;
  - the subtask is *fork-worthy* by any trigger: `effort_level ∈ {high, xhigh, ultracode}`, a
    planner-authored `fork_eligible: true` flag (additive subtask field, §5), ambiguity signal
    (the goal/spec contains an `ADVERSARY_TRIGGER_PHRASES`-style "multiple approaches" marker, reusing
    `config.ADVERSARY_TRIGGER_PHRASES`), or **escalation**: the subtask already FAILED a prior
    linear attempt (fork as a smarter retry than re-running the same trajectory);
  - NOT excluded: not doc-only / not a `single_deliverable` goal mechanical edit
    (`platform_core/orchestration/subtask.py::_singleDeliverable`), not self-ref core-protected;
  - `projected_cost ≤ config.SOLUTION_FORK_COST_CEILING_USD` (and within Epic 1 `cost_budget` headroom).
- `forkPlan(state, subtask) -> ForkPlan` — builds N **diversity seeds**. `ForkPlan` is a small
  dataclass `{branch_seeds: list[BranchSeed], n: int}`; `BranchSeed{branch_id, effort_level, angle_hint,
  model, skills}`. Diversity is seeded along three orthogonal axes (any subset, capped at
  `config.SOLUTION_FORK_N`, default 3):
  - **effort axis** — vary `effort_level` across branches (e.g. `high`, `xhigh`, `high`), which also
    varies the routed model via the existing `config.MODEL_BY_EFFORT` (low→haiku, default/high→sonnet,
    xhigh/ultracode→opus) — so an effort spread is *also* a model spread for free;
  - **angle axis** — inject a distinct `angle_hint` into each branch's `claude_md_inject` ("Approach A:
    smallest safe change"; "Approach B: refactor for clarity"; "Approach C: test-first"), the
    coordinator's "synthesize a self-contained spec per worker" discipline
    (claude-code `coordinatorMode.ts §5`, idea-only);
  - **model axis** (optional, explicit) — directly pin `model` per branch when the planner requests it.
    Note: `.claude/rules/orchestration.md` forbids changing model/effort routing **as part of speed
    work**; this is *capability* work and the variation is the whole point, so it is allowed here, but
    gated and never applied to the non-fork path.
- `DIVERSITY_ANGLES: tuple[str, ...]` — the ALL_CAPS default angle-hint bank.

### (b) Parallel branch execution over isolated worktrees

**Source:** swarmclaw `subagent-swarm.ts` (`allSettled`/`quorumSettled`/`cancelAll`, concurrency
bucketing); bernstein `best_of_n.py` (spawn K candidates in isolated worktrees); Epic 1
`platform_core/runtime/worktree.py` (the actual isolation backend).

New module `platform_core/orchestration/branch_runner.py`:

- `BranchResult` dataclass: `{branch_id, seed, worktree_path, result, combined, passed, vresult,
  envelope, receipt, score, cost_usd, crashed}` — one per branch.
- `runBranches(state, subtask, architect_doc, fork_plan, deps) -> list[BranchResult]`:
  - for each `BranchSeed`, `worktree.enterWorktree(state, f"{sid}#{branch_id}")` (Epic 1) returns an
    isolated cwd off the run branch — **branches never share a tree**, so they cannot clobber each
    other (the exact property `themes/agent-comms-topology.md` §3 demands);
  - submit each to a `ThreadPoolExecutor(max_workers=min(n, config.SOLUTION_FORK_MAX_CONCURRENCY))`,
    mirroring `run_loop_mixin.py::_handleParallelBatch` (same crash-isolation, same
    `experience.close_pool()` cleanup, same per-future `cancel()` on abort);
  - each branch builds its seed-specialized invocation spec (effort/angle/model/skills folded into
    `authorInvocationSpec`) and runs the **existing** `_runAttemptLoop` *inside its worktree*
    (`exec_cwd = worktree_path`) — so a branch is a full normal attempt loop, just isolated;
  - the branch's Epic 2 `CompletionEnvelope` + deterministic `verify_result` are captured on the
    `BranchResult`;
  - a branch that raises is caught, marked `crashed=True`, and excluded from judging — **never strands
    the subtask** (§6);
  - the executor span (Epic 1 `trajectory.py`) opens a `branch` child span per branch so the trace
    shows the fork fan-out + per-branch cost.
- `CANCEL-ON-QUORUM` (optional, swarmclaw `quorumSettled`): once `config.SOLUTION_FORK_QUORUM` branches
  reach a `VERIFIED` receipt, remaining in-flight branches MAY be cancelled to cap cost; default off
  (let all branches finish so the judge ranks the full set).

### (c) Judge panel — reuse Epic 2's execution-grounded verifier as the scorer

**Source:** bernstein `eval/judge.py` (rubric verdict, 0–5 per dimension, PASS iff all ≥3); swarmclaw
`eval/scorer.ts` (weighted multi-criterion); metagpt `action_node.py::auto_review` + `write_code_review.py`
(per-field / LGTM-LBTM spec-vs-code review); Epic 2 `agents/independent_verifier.py` +
`agents/evidence_receipt.py` (the execution-grounded scorer this epic **reuses, not re-builds**).

New module `platform_core/orchestration/judge_panel.py`:

- **Facts gate first (selection by evidence, not opinion).** For each non-crashed `BranchResult`, the
  branch already carries an Epic 2 **Evidence Receipt** whose `headline ∈ {VERIFIED,
  VERIFIED_WITH_GAPS, NOT_VERIFIED}` is computed **only from re-derivable facts** (diff sha, test exit
  codes). `eligible = branches with headline ∈ {VERIFIED, VERIFIED_WITH_GAPS}`. A `NOT_VERIFIED` /
  inconclusive branch can never win (loki "inconclusive ≠ verified", `themes/verification-self-correction.md`
  #3). If `eligible` is empty → no winner (§6 fallback).
- **Rubric score among the eligible.** `scoreBranch(branch, goal, rubric) -> BranchScore` runs the
  bernstein-style rubric judge once per eligible branch (parallel, in a small `ThreadPoolExecutor`,
  swarmclaw's parallel-judge shape). The rubric dimensions (0–5 each, ALL_CAPS `JUDGE_RUBRIC`):
  `correctness`, `completeness`, `safety`, `simplicity`, `test_strength`. The LLM-judge opinion is
  **advisory weight only** — it ranks among branches that already passed the facts gate, so a verbose-
  but-wrong branch cannot be ranked #1 (it failed the facts gate before the rubric ever ran).
- **Composite score** (`BranchScore.total`), deterministic blend so ties are rare:
  `total = W_FACT·fact_points + W_RUBRIC·rubric_mean − W_RISK·norm_diff_size − W_COST·norm_cost`
  where `fact_points` rewards `VERIFIED` over `VERIFIED_WITH_GAPS`, `norm_diff_size` penalizes large
  blast radius, `norm_cost` lightly penalizes spend. Weights are `ALL_CAPS` config (`W_FACT`,
  `W_RUBRIC`, `W_RISK`, `W_COST`).
- **Deterministic tie-break** (`pickWinner(scores) -> BranchResult`): on equal `total`, prefer in
  order — (1) `VERIFIED` over `VERIFIED_WITH_GAPS`, (2) smaller diff (lower risk), (3) lower cost,
  (4) lowest stable `branch_id` — so the winner is reproducible given the same branch outputs
  (bernstein's "replay yesterday's plan, get yesterday's result" determinism).
- **Anti-rubber-stamp guard** (optional, loki `sycophancy.py` slice, `themes/verification-self-correction.md`
  #20): if all rubric verdicts are near-identical the judge logs low discriminative power; does not
  block, just flags that the fork added little signal (feeds the success-criteria measurement, §9).

### (d) Winner selection + merge-back + optional graft

**Source:** bernstein `best_of_n.py` ("keep winner's diff, reclaim losers' worktrees"); Epic 1
`worktree.exitWorktree(merge=True)`; metagpt `write_code_review.py` LBTM rewrite loop (the graft pass).

New module `platform_core/orchestration/winner_merge.py`:

- `mergeWinner(state, subtask, winner, deps) -> dict` — `worktree.exitWorktree(winner.worktree_path,
  merge=True)` (Epic 1) lands the winning branch into the canonical run branch; returns the winner's
  `vresult` so the caller commits status through the **normal** `state.recordVerify` / `_executeSubtask`
  path (ownership preserved — the judge never writes status directly).
- **Optional graft of runner-up ideas** (`config.SOLUTION_FORK_GRAFT_ENABLED`, **default off**):
  after the winner is merged, take the top runner-up's `CompletionEnvelope.diff_summary` +
  `residual_risks` and run **one bounded remediation-style pass** on the merged winner via the existing
  `_remediate` seam (`execute_mixin.py:46`) — "the winning approach passed; a sibling approach also did
  X and flagged Y; incorporate the good idea WITHOUT breaking the passing verify." This reuses
  `_remediate`'s snapshot/keep-or-revert guard, so a graft can only keep-or-improve. **It is an
  advisory feedback pass, never a raw `git merge` of two divergent branches** — sidestepping merge
  conflicts (the §8 risk). Grafting is skipped entirely if no runner-up was `VERIFIED`.

### (e) Branch cleanup / GC

**Source:** Epic 1 `worktree.gcOrphans` / `removeWorktree` (path-scoped safe-remove); loom spool
auto-reclaim (idea-only).

- `winner_merge.reclaimLosers(state, branches, winner)` — `worktree.removeWorktree(path)` for every
  non-winner branch (and its throwaway `wt/<task8>/<sid>#<branch>` branch ref), best-effort; a removal
  failure logs and is swept by `worktree.gcOrphans(state)` at run end (Epic 1), which refuses any path
  outside `state/.sc-worktrees/`.
- On crash mid-fork, `resilience.run_with_recovery` reload leaves orphan worktrees; `gcOrphans` at the
  next run-phase boundary reclaims them (TTL/whitelist). No new GC machinery — Epic 1 owns it.

## 4. Data flow — one fork-worthy subtask

```
subtask (fork-worthy?) ──fork_policy.shouldFork──▶ NO ─▶ _runAttemptLoop  (today's linear path, unchanged)
        │ YES
        ▼
fork_policy.forkPlan ─▶ N BranchSeeds (effort × angle × model diversity), N ≤ SOLUTION_FORK_N
        ▼
branch_runner.runBranches (ThreadPoolExecutor, one isolated worktree.enterWorktree per branch)
        │   each branch = seed-specialized authorInvocationSpec → _runAttemptLoop INSIDE its worktree
        │   → CompletionEnvelope + deterministic verify_result + Evidence Receipt  (Epic 2, per branch)
        │   crash ⇒ branch marked crashed, excluded
        ▼
judge_panel: facts gate (Receipt headline) → eligible set
        │   eligible empty? ─▶ FALLBACK: pick best-effort single attempt / today's behavior (§6)
        ▼   else: parallel rubric judge → composite score → deterministic tie-break
winner_merge.mergeWinner ─▶ worktree.exitWorktree(merge=True) lands winner into canonical run branch
        │   (optional) graft top runner-up idea via bounded _remediate pass  [flag, default off]
        ▼
winner.vresult ─▶ normal state.recordVerify / _executeSubtask commit  (verifier owns status)
        ▼
winner_merge.reclaimLosers ─▶ worktree.removeWorktree(losers); gcOrphans sweeps stragglers
```

The tuple `solution_space.runForked(...)` returns is **shape-identical** to `_runAttemptLoop`'s
`(spec, result, vresult, combined, passed, attempt)`, so all downstream enrichment in `_executeSubtask`
(`_postSubtaskEnrich`, adversary, SIE, replan, Obsidian note) is unchanged.

## 5. Exact file structure

**New files**

| Path | Responsibility |
|---|---|
| `platform_core/orchestration/fork_policy.py` | `shouldFork`, `forkPlan`, `ForkPlan`/`BranchSeed` dataclasses, `DIVERSITY_ANGLES`. Decides *if* and *how* to fork. |
| `platform_core/orchestration/branch_runner.py` | `runBranches` (parallel isolated-worktree execution of N seed-specialized attempt loops), `BranchResult`, optional quorum-cancel. |
| `platform_core/orchestration/judge_panel.py` | facts gate over Epic 2 receipts, parallel rubric judge (`scoreBranch`), composite score, `pickWinner` tie-break, `JUDGE_RUBRIC`. |
| `platform_core/orchestration/winner_merge.py` | `mergeWinner` (Epic 1 `exitWorktree(merge=True)`), optional `graftRunnerUp` via `_remediate`, `reclaimLosers` GC. |
| `platform_core/orchestration/solution_space.py` | thin coordinator: `runForked(state, subtask, architect_doc, exec_cwd, bus, dashboard, sid, verify_spec) -> tuple` returning the `_runAttemptLoop`-shaped tuple; the ONLY new symbol `execute_mixin` imports. |

**Modified files** (narrow patches; public facades preserved)

| Path | Change |
|---|---|
| `platform_core/orchestration/execute_mixin.py` | In `_executeSubtask` (line ~411), branch on `fork_policy.shouldFork(...)`: if true call `solution_space.runForked(...)` else the existing `_runAttemptLoop(...)`. Both return the same tuple; everything below the call is untouched. `_remediate` is reused by the graft pass. |
| `state/task_schema.py` | `addSubtask` gains additive `fork_eligible: bool = False` (planner hint; default-safe, no facade break). |
| `platform_core/app_config/llm.py` | New `ALL_CAPS` knobs (below), env-overridable, staged defaults so the epic ships dark. |
| `AGENTS.md` | Regenerate via `python tools/repo_map.py` after the new modules land (exported-structure change). |

**Config knobs** (`platform_core/app_config/llm.py`, beside `MAX_SUBTASK_ATTEMPTS`):

```python
SOLUTION_FORK_ENABLED:          bool  = _envBool("SOLUTION_FORK_ENABLED", False)   # ships dark
SOLUTION_FORK_N:                int   = _envInt("SOLUTION_FORK_N", 3)              # branches per fork
SOLUTION_FORK_MAX_CONCURRENCY:  int   = _envInt("SOLUTION_FORK_MAX_CONCURRENCY", 3)
SOLUTION_FORK_COST_CEILING_USD: float = _envFloat("SOLUTION_FORK_COST_CEILING_USD", 5.0)
SOLUTION_FORK_QUORUM:           int   = _envInt("SOLUTION_FORK_QUORUM", 0)         # 0 = no early-cancel
SOLUTION_FORK_GRAFT_ENABLED:    bool  = _envBool("SOLUTION_FORK_GRAFT_ENABLED", False)
# Judge composite weights
W_FACT:   float = _envFloat("SOLUTION_FORK_W_FACT", 0.5)
W_RUBRIC: float = _envFloat("SOLUTION_FORK_W_RUBRIC", 0.3)
W_RISK:   float = _envFloat("SOLUTION_FORK_W_RISK", 0.15)
W_COST:   float = _envFloat("SOLUTION_FORK_W_COST", 0.05)
```

## 6. Error handling (a branch crash must not sink the subtask)

Fork is **additive and fail-open**: every path degrades to today's single-attempt behavior, never
worse.

- **One branch crashes** → caught in `runBranches` (per-future `try/except`, mirroring
  `_handleParallelBatch` lines 187-191), marked `crashed=True`, excluded from judging. The other
  branches still compete.
- **All branches crash / none eligible** (`judge_panel` finds no `VERIFIED`/`VERIFIED_WITH_GAPS`) →
  `solution_space.runForked` **falls back to a single `_runAttemptLoop` on the canonical tree** and
  returns its tuple — identical to never having forked. (If a crashed-but-furthest branch left useful
  partial work, its worktree is GC'd; the fallback starts clean to avoid trusting un-judged edits.)
- **Worktree backend unavailable** (Epic 1 `enterWorktree` fail-open returns the shared tree) → forking
  cannot isolate, so `shouldFork` is short-circuited to `False` for that run (a fork on a shared tree
  would clobber peers — the exact hazard `_remediationTreeShared` guarded). Forking *requires*
  isolation; without it, take the linear path.
- **Cost ceiling exceeded mid-fork** (Epic 1 `cost_budget` hard-ceiling event) → cancel remaining
  in-flight branches (`cancelAll`), judge whatever finished; if nothing eligible, single-attempt
  fallback.
- **Merge-back conflict** (`exitWorktree(merge=True)` fails) → log, leave the worktree for inspection,
  fall back to re-running the winner's *spec* on the canonical tree once; if that also fails, mark the
  subtask failed via the normal path (no silent green).
- **Judge LLM failure** → a branch whose rubric call errors keeps its facts-gate standing but scores
  `rubric_mean = 0`; if the facts gate already passed it, it can still win on facts alone (judge
  opinion is advisory). The judge never blocks on its own LLM flakiness.
- **Best-effort everywhere**: GC, trajectory spans, and graft are all wrapped like the existing
  `_postSubtaskEnrich` contract — an enrichment/cleanup failure never rolls back a committed winner.

## 7. Testing strategy

Pytest, per `.claude/rules/tests.md`. Run via **pytest** (conftest sandboxes Discord/Ollama only under
pytest — memory note). Per-file focus: `python tools/dev.py check <file>`; `python tools/dev.py fast`
before handoff; `python tools/size_audit.py` (zero `must_split`).

- `tests/test_fork_policy.py` — `shouldFork` true on high-effort / `fork_eligible` / failed-prior /
  ambiguity; false on doc-only / single-deliverable / over-cost-ceiling / flag-off / shared-tree;
  `forkPlan` emits N distinct seeds spanning effort×angle (no two seeds identical).
- `tests/test_branch_runner.py` — **deterministic, stubbed branches**: monkeypatch `_runAttemptLoop`
  (and `worktree.enterWorktree`/`exitWorktree`) so each "branch" returns a canned
  `(result, vresult, envelope, receipt)`; assert N `BranchResult`s, a stubbed crashing branch is
  excluded not fatal, concurrency respects `SOLUTION_FORK_MAX_CONCURRENCY`.
- `tests/test_judge_panel.py` — facts gate excludes `NOT_VERIFIED`; among eligible, a higher-fact /
  smaller-diff branch wins; **deterministic tie-break** reproducible across runs; empty-eligible →
  signals fallback; rubric-LLM stubbed (no live brain) so scoring is pure.
- `tests/test_winner_merge.py` — `mergeWinner` calls `exitWorktree(merge=True)` once on the winner;
  `reclaimLosers` removes exactly the non-winner worktrees; graft (flag on) routes the runner-up diff
  through a stubbed `_remediate` and keeps-or-reverts; graft skipped when no runner-up `VERIFIED`.
- `tests/test_solution_space.py` — end-to-end with all branches stubbed: `runForked` returns a
  `_runAttemptLoop`-shaped tuple; all-crash → single-attempt fallback returns the linear tuple;
  flag-off → `_executeSubtask` never enters the fork path (regression: linear behavior byte-identical).
- **Regression guards (must stay green):** `tests/test_execute_mixin*.py` /
  `test_remediation_tree_shared.py` (Epic 1) — the non-fork path and worktree isolation are unchanged;
  `test_resilience.py` (orphan-worktree GC after a forked-run crash still terminal-safe).

## 8. Risks + sequencing + dependency on Epics 1 & 2

**Hard dependencies (this epic cannot ship before them):**
- **Epic 1 — per-subtask git-worktree isolation** (`platform_core/runtime/worktree.py`:
  `enterWorktree`/`exitWorktree(merge=True)`/`gcOrphans`/`isIsolated`). Each branch *needs its own
  tree*; without isolation a fork clobbers itself. Forking is short-circuited off when Epic 1 falls
  back to a shared tree (§6). Epic 1 also supplies `trajectory.py` (branch spans) and `cost_budget.py`
  (the cost ceiling).
- **Epic 2 — execution-grounded verifier / judge** (`agents/independent_verifier.py`,
  `agents/evidence_receipt.py`). The judge panel **selects by these receipts' fact-derived headline**;
  without execution-grounded scoring the "winner" would be chosen by narration, defeating the point.
  The bernstein `eval/judge.py` rubric port layers *on top of* Epic 2's facts gate.

Standalone-but-co-designed: Epic 6 introduces no new verification or state ownership; it composes the
two seams. If Epic 2 is unavailable, the judge degrades to facts-only (deterministic `verify_result`
exit codes + diff size) with no rubric — still functional, lower-fidelity selection.

**Risks & mitigations:**
- **N× cost / time.** The headline risk. Mitigations: hard `shouldFork` gate (exception not default),
  `SOLUTION_FORK_COST_CEILING_USD`, `SOLUTION_FORK_MAX_CONCURRENCY`, optional quorum early-cancel,
  ships dark (`SOLUTION_FORK_ENABLED=False`). Forking targets exactly the high-effort/ambiguous/
  previously-failed subtasks where the N× spend buys the most.
- **Merge conflicts when grafting.** Mitigation: graft is **advisory** (a `_remediate` feedback pass,
  not a git merge), default-off, snapshot-guarded keep-or-revert. Winner merge-back is a single
  worktree branch into the run branch (one merge, conflict → §6 fallback).
- **Non-determinism / unstable winner.** Mitigation: facts-first selection (re-derivable receipt) +
  fully deterministic composite tie-break (§3c) so the same branch outputs always pick the same winner;
  the anti-rubber-stamp guard surfaces when the fork added no real signal.
- **Fork explosion / runaway workers.** Mitigation: one fork generation (branches never self-fork),
  `SOLUTION_FORK_N` cap, concurrency cap that nests *under* the runtime's 16-worker pool, livelock
  guard unchanged (`run_loop_mixin._livelockGuard`).
- **Windows worktree friction** (path length, locks) — inherited from Epic 1; the fail-open-to-linear
  path is the safety net, soak on Windows before default-on.

**Sequencing (low-risk → high-risk, each independently flag-gated):**
1. **(a) fork_policy + (c) judge_panel** — pure deciders/scorers, no execution side effects; testable
   with stubbed branches first. Lands de-risked.
2. **(b) branch_runner** — parallel isolated execution; reuses Epic 1 worktrees + the existing
   `_runAttemptLoop`. First real fan-out.
3. **(d/e) winner_merge + reclaim** — merge-back + GC; reuses Epic 1 `exitWorktree`/`gcOrphans`.
4. **graft pass** — last, default-off, behind `SOLUTION_FORK_GRAFT_ENABLED`; flip only after the
   no-graft fork loop is proven on the golden suite.

## 9. Success criteria

- For a fork-worthy subtask with `SOLUTION_FORK_ENABLED=True`, 9TO5 spawns N diverse branches in
  **separate worktrees**, runs them concurrently, and a judge panel selects a winner whose result is
  merged into the canonical tree — demonstrated by `test_solution_space.py` end-to-end (stubbed).
- The winner is chosen **by execution-grounded evidence first** (Epic 2 receipt headline), rubric
  only as a tie-fine-tuner; a verbose-but-wrong branch can never win (facts gate excludes it). Tie-break
  is deterministic and reproducible.
- A crashing branch is excluded, not fatal; **all-crash / none-eligible falls back to a single
  `_runAttemptLoop`** with byte-identical downstream behavior; flag-off leaves the linear path
  unchanged (regression test).
- Losing worktrees are reclaimed (`reclaimLosers` + `gcOrphans`); no orphan worktree survives a clean
  run; a crashed forked run's orphans are swept at the next run-phase boundary.
- On the golden eval suite, forked subtasks show a measurable **win-rate / quality lift** over the
  linear baseline that justifies the N× cost (A/B with the flag), and the anti-rubber-stamp guard
  reports non-trivial discriminative power (the branches genuinely differ).
- Ownership intact: verifier still owns status (winner commits via `state.recordVerify`), state store
  owns run state, `ControlBus` owns control. `python tools/dev.py fast` green; `python tools/size_audit.py`
  zero `must_split`; `AGENTS.md` regenerated.

---

### Source-path appendix

- Best-of-N: `references/bernstein/src/bernstein/core/orchestration/best_of_n.py`,
  `core/orchestration/multi_criteria_rank.py` (Apache-2.0).
- Rubric judge: `references/bernstein/src/bernstein/eval/judge.py` (Apache-2.0).
- Swarm primitives / weighted scorer: `references/swarmclaw/src/lib/server/agents/subagent-swarm.ts`,
  `src/lib/server/eval/scorer.ts` (MIT).
- Per-field / spec-vs-code review: `references/metagpt/metagpt/actions/action_node.py` (`auto_review`),
  `actions/write_code_review.py` (MIT).
- Branch-per-line + auto-commit *patterns*: loom `specs/spool-system.md`,
  `specs/auto-commit-system.md` (**Proprietary — ideas only**).
- Coordinator + worktree *patterns*: claude-code `coordinator/coordinatorMode.ts`,
  `tools/EnterWorktreeTool/` (**Proprietary — ideas only**; realized via Epic 1 `worktree.py`).
- Dependencies: Epic 1 `docs/superpowers/specs/2026-06-30-epic1-durable-execution-design.md`
  (`platform_core/runtime/worktree.py`, `trajectory.py`, `cost_budget.py`); Epic 2
  `docs/superpowers/specs/2026-06-30-epic2-trustworthy-loop-design.md`
  (`agents/independent_verifier.py`, `agents/evidence_receipt.py`).
