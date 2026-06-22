# SIE Implementation Status

Progress tracker for the A→Z build of the Self-Improvement Engine. Spec:
`specs/2026-06-22-self-improvement-engine-design.md`. Plan:
`plans/2026-06-22-self-improvement-engine.md`. Built behind best-effort/flag seams so
existing behavior and tests stay green; phases needing GPU/Ollama/Discord/Obsidian are
implemented with the external call seam mocked and offline-testable logic real.

| Stage | Scope | State |
|---|---|---|
| **A — Capture + Measure** | Experience Ledger (`memory/experience.py`), best-effort TaskState sinks, backfill, eval-harness skeleton (`learning/eval_harness.py`) + golden suite + fitness math, config block | ✅ done |
| **B — Retrieval** | local embeddings + cosine top-K (`memory/retrieval.py`), lessons rendering w/ token cap, orchestrator injection, negative cache | ✅ done |
| **C — Consolidation + Policy** | ledger-rebuilt lessons (`learning/lessons.py`) + Thompson bandit (`learning/policy.py`), policy hint injection, fitness sparkline panel | ✅ done |
| **D — Prompt Evolution** | versioned registry (`learning/prompts.py`, byte-identical) + champion/challenger gate (`learning/promotion.py`), auto-runs in weekly tier | ✅ done |
| E — LoRA Distillation (SFT) | data-quality gate + gold dataset + local LoRA | ⬜ |
| F — Reward + DPO | composite reward + preference pairs | ⬜ |
| G — Rollout + Counterfactual | offline replay + shadow/canary + per-role adapters | ⬜ |
| H — Curriculum + Releases | self-play goals + model cards + attribution | ⬜ |
| NW1–NW7 — Next wave (J–R) | human feedback, confidence, post-mortems, multi-teacher, KG, solution cache, research track | ⬜ |
| **X1 — Auto-runner** | `learning/sie.py` cadence ladder, auto-fires after every run (hands-off), file-locked + throttled | ✅ done |
| X2 — Safety | `learning/safety.py` invariants I1–I6 + kill switch enforcement | ⬜ |

> **Automation (core philosophy):** the user only starts / aborts / checks. As of X1, all
> learning (embeddings, consolidation, policy rebuild, eval — and later promotion/LoRA)
> runs **automatically** in the orchestrator's `finally` block after every task, off-thread,
> throttled (~daily) and file-locked. Nothing here is ever run by hand.

## Phase A — what landed
- `memory/experience.py`: SQLite (WAL) ledger — `runs`/`subtasks`/`eval_runs` schema,
  idempotent upserts, `sync_run`/`sync_subtask` from TaskState shapes, `gold_examples`,
  `fitness_series`, `backfill_from_store`. Best-effort: never raises into a run.
- `state/task.py`: best-effort ledger sinks at `setStatus` / `recordVerify` /
  `addAdversaryReview` (no control-flow change).
- `learning/eval_harness.py`: pure `compute_fitness` + `aggregate` + `score`,
  `load_suite`, pluggable `run_suite(runner)`; CLI records a `no_runner` marker.
- `learning/eval_suite/`: 3 golden goals (bugfix / add-test / refactor) with held-out verifies.
- `config.py`: SIE block (ledger path, retrieval knobs, fitness weights, kill switch, brain tag).
- Tests: `tests/test_experience_ledger.py`, `tests/test_eval_harness.py`.

## Phase B — what landed
- `memory/retrieval.py`: local-Ollama embedding seam (`_embed_call`, mockable), float32
  `pack`/`unpack`, `cosine`, `top_k_similar` (verify-passing pool), `retrieve`,
  `render_lessons` (≤`RETRIEVAL_MAX_TOKENS`), `lessons_block` (best-effort one-call API),
  `backfill_embeddings` (off-hot-path), and a 60s negative cache so a dead embedder never
  adds latency to brain calls.
- `memory/experience.py`: `set_subtask_embedding` + `embedded_subtasks` (retrieval pool).
- `orchestrator.py`: prepend `retrieval.lessons_block(...)` in `authorSubtaskPlan` and
  `authorInvocationSpec` (no-op when empty). New `from memory import retrieval`.
- Tests: `tests/test_retrieval.py` (10; embeddings mocked). Full suite 235/235 green.

## Phase C — what landed
- `memory/experience.py`: `lessons` + `policy_arms` tables and helpers
  (`upsert_lesson`/`fetch_lessons`/`clear_lessons`, `set_arm`/`fetch_arms`/`clear_arms`).
- `learning/lessons.py` (L2): `family_of` clustering, `consolidate()` rebuilds effort
  lessons from the ledger (idempotent; min-support + win-gap gated) + writes `lessons.md`.
- `learning/policy.py` (L4): `compute_reward`, `rebuild_from_ledger` (deterministic, no
  hot-path writes), Gaussian-Thompson `select`, and best-effort `hint()`.
- `orchestrator.py`: `authorInvocationSpec` now prepends `policy.hint(...)` + lessons.
- `learning/eval_harness.py`: `fitness_panel()` sparkline (C3, dashboard-ready).
- Tests: `tests/test_lessons.py` (8), `tests/test_policy.py` (9), +2 eval-harness.
  Full suite 252/252 green.

## Phase X1 — Automation backbone (brought forward — core philosophy)
- `learning/sie.py`: `run_maintenance()` runs the throttled cadence ladder once —
  embeddings backfill → consolidation (L2) → policy rebuild (L4) → eval — each step
  best-effort/independent. File-locked (O_EXCL, stale-reclaim), throttled via
  `state/control/sie_state.json` (~daily without any cron), kill-switch aware.
  `run_maintenance_async()` fires it off a daemon thread.
- `orchestrator.py`: the `runFull` `finally` block dispatches it after **every** run
  (success/abort/fail), gated by `SIE_AUTO_MAINTENANCE`. The user never triggers learning.
- `config.py`: `SIE_AUTO_MAINTENANCE` (default on).
- Test hygiene: `tests/__init__.py` disables auto-dispatch + isolates the ledger to a
  temp DB so the suite stays fast and never pollutes `state/experience.db`.
- Tests: `tests/test_sie.py` (6: force/throttle/lock/kill-switch/idempotent). Suite 258/258.

## Phase D — Prompt Evolution (auto-promoted, hands-off)
- `memory/experience.py`: `prompt_variants` table + helpers (`register_variant`,
  `get_champion`/`get_champion_body`, `promote_variant`, `tag_run_prompt`,
  `prompt_field_stats`).
- `learning/prompts.py` (L3): `get(role, default)` returns the in-code constant
  **byte-identical** until a challenger is promoted; `propose`/`promote`/`champion_id`.
- `learning/promotion.py`: `proportion_z`, `decide` (min-uses + z gate), Thompson
  `pick_challenger`, `run_promotions` (auto-evaluates + promotes per role). Enforces
  invariant I2: the brain only proposes; the independent gate decides.
- `orchestrator.py`: `authorInvocationSpec` sources the constitution via `prompts.get`
  and tags the run's prompt id for field metrics (best-effort, byte-identical today).
- `learning/sie.py`: new **weekly tier** runs `run_promotions` automatically (7-day
  throttle) — promotion is hands-off; `gated` mode still needs `!approve` to apply.
- `config.py`: `PROMPT_PROMOTE_MIN_USES` (20), `PROMPT_PROMOTE_Z` (1.64).
- Tests: `tests/test_prompts.py` (5), `tests/test_promotion.py` (9). Suite 271/271 green.
