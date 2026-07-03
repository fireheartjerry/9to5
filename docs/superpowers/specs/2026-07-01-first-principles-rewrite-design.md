# 9TO5 First-Principles Rewrite — Design (2026-07-01)

Owner mandate: transformative, highest-ROI rewrites across the codebase, executed on
isolated worktree branch `fable/first-principles-rewrite`. Current implementation treated
as reference, not source of truth.

## How this design was produced

- 13 subsystem deep-readers + 4 cross-cutting auditors (duplication, state/persistence,
  concurrency, error-resilience) mapped all ~40k source LOC → 187 pain points,
  79 redesign candidates.
- 3 lens-diverse portfolio designers (architecture / reliability / leverage) + a merge
  judge that re-verified load-bearing claims against source produced the final
  12-item portfolio. Full detail: session artifact `portfolio.json` (each item carries
  implementation-ready design, files, test strategy, breaking changes).

## Baseline at HEAD (692747b)

`python tools/dev.py fast`: **3668 passed, 10 failed, 7 collection ERRORs**.
Suite is broken at HEAD — 5 test files corrupted by the repo_map AI-MAP splicer
(+2 near-dupes erroring), plus 10 pre-existing failures (repo-map drift, identity
globs, config robust-env, sie maintenance, trajectory-parallel, coherence-invariant,
deployment, eval-harness). Verification bar: zero errors, no new failures, pre-existing
failures fixed or explicitly accounted for by portfolio items.

## Portfolio (ROI-ranked)

| ID | Title | Impact/Effort/Risk |
|---|---|---|
| R1-safety-net | Repair 5 splice-corrupted test files; ban AI-MAP splicing from tests/; purge unittest-discover live-creds footgun; CI compileall + repo-map check | transformative/small/low |
| R6-operator-kill | ≤2s operator kill: in-flight subprocess cancel watcher + stderr drain deadlock fix (was: up to 600s) | transformative/small/low |
| R7-hooks-fail-closed | Guard hooks actually registered in .claude/settings.json, fail-closed, one risk taxonomy | transformative/medium/medium |
| R8-control-plane-sqlite | ControlBus → transactional SQLite (same public API); one Discord ingestion authority w/ explicit degraded fallback; idempotent autonomy ledger | transformative/medium/medium |
| R2-dead-purge | Delete zero-caller subsystems + test constellations (~-13k LOC): retry stack, monitoring/, scheduling/, NotificationBus, orchestration_pipeline, etc. | high/medium/low |
| R3-human-nature-amputation | Delete human_nature/ (2,881 LOC, zero production imports) + society's unwired half; wire society budget gate; specs stay in docs/, code recoverable at pre-deletion commit | high/medium/low |
| R9-run-lifecycle | Abort survives crashes (recovery checks bus.isAbort); single-writer task JSON; heartbeat liveness primitive; IPC out of task-store glob; launch handshake | high/medium/medium |
| R10-verification-receipt | Typed verification Receipt pipeline; kill silent FAIL→PASS test-runner override; diff-grounded checks; single fail-closed verdict parser | high/medium/medium |
| R4-io-kernel | platform_core/core/{fsio,jsonl_io,clock,git_io} — delete ~20 hand-rolled copies; fix invalid-jq PR-review bug; trajectory → true append-only JSONL | high/medium/low |
| R12-config-v2 | One env bootstrap; typed settings registry behind PEP 562 config facade; PROJECT_ROOT landmine defused; overrides = first-class layer | high/medium/medium |
| R11-best-effort | best_effort() degradation kernel (counted/deduped/surfaced); log-level env knob + rotation | high/medium/low |
| R5-llm-seam | One LLM client in llm_io; sim doubles dispatch on structured `act` tag, never prompt wording; parseJsonLoose unified | medium/medium/low |

Estimated net: ~-22k LOC. Live bugs fixed: verification FAIL→PASS override; invalid jq
(PR review state always "none"); control-bus corrupt-rebuild zeroing autonomy ledger;
abort-inverted-to-resume; 600s abort latency → ≤2s; stderr drain deadlock.

## Sequencing (waves; boundary gate between each)

- **Wave 1 (solo):** R1 — nothing is verifiable until pytest collects.
- **Wave 2 (parallel ×5, disjoint files):** R2, R3, R4, R6, R7. AGENTS.md regenerated
  once at wave end, never concurrently.
- **Wave 3a (parallel):** R9 (lifecycle) ∥ chain R5→R10 (share adversary_review.py; act
  tag lands before the VERIFY-RULES prompt change so sim dispatch is proven safe).
- **Wave 3b (parallel):** R8 (needs R9 heartbeat + R6 commands.py) ∥ R12 (needs R3 HN-knob
  removal; touches main.py after R9's edits land).
- **Wave 4 (solo, last):** R11 — instrument swallow sites only after all deletions.

Boundary gate: `python -m compileall -q tests` → full pytest → `python tools/repo_map.py`
(regen + check) → `python tools/size_audit.py` (zero must_split) → dry-run simulator suite.

## Non-goals (explicitly deferred, next session)

- Orchestrator mixin→pipeline rewrite + full typed-outcomes sweep (RunOutcome/PrDecision
  enums): real problems, but touches every file six items edit — merge hell this session.
- Experience-ledger TableSpec rewrite (R11's per-table degradation counters cover the
  observability gap now).
- notifications RunSnapshot consolidation; learning family-stats spine (bugs documented
  in portfolio for follow-up); git-eviction of committed state/ artifacts beyond R9's IPC fix.
- No model/effort routing changes. No new features. No new knobs beyond
  CANCEL_POLL_SECONDS and NINE_TO_FIVE_LOG_LEVEL.

## Invariants preserved

Root facades keep importing (config.py, orchestrator.py, knowledge.py, state/task.py,
llm_io re-exports). File ≤450 lines, functions ≤70. Source-of-truth ownership: task JSON
owns run state (single-writer post-R9), ControlBus owns control, verifier owns verdicts.
Windows-first. Tests updated where they pin replaced implementation details; deleted with
their dead subject code.
