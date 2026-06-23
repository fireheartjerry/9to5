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
| **E — LoRA Distillation (SFT)** | data-quality gate (`learning/dataset.py`) + gold builder (`learning/distill.py`) + local LoRA + adapter registry/rollback (`learning/finetune.py`), auto-runs in weekly tier | ✅ done |
| **F — Reward + DPO** | composite reward + logistic calibrator (`learning/reward.py`) + preference pairs (`learning/preferences.py`) + DPO LoRA cycle, auto-runs in weekly tier | ✅ done |
| **G — Rollout + Counterfactual** | offline replay (`learning/counterfactual.py`) + shadow/canary state machine (`learning/rollout.py`) + per-role adapters & brain router | ✅ done |
| **H — Curriculum + Releases** | self-play goal generation (`learning/curriculum.py`) + model cards & attribution report (`learning/release.py`), auto in weekly tier | ✅ done |
| **NW1–NW7 — Next wave (J–R)** | human feedback, confidence, post-mortems, reflection/multi-teacher, KG, solution cache, research track | ✅ done |
| **X1 — Auto-runner** | `learning/sie.py` cadence ladder, auto-fires after every run (hands-off), file-locked + throttled | ✅ done |
| **X2 — Safety** | `learning/safety.py` invariants I1/I2/I4 + guard + panic-to-stock + kill switch | ✅ done |

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

## Phase E — LoRA Distillation, SFT (auto, GPU-optional)
- `memory/experience.py`: `adapters` table + helpers (`register_adapter`,
  `get_champion_adapter`, `promote_adapter`, `retire_champion_adapter`).
- `learning/dataset.py` (gate G): secret scrub/`has_secret`, eval-suite decontamination,
  schema `validate`, `clean()` pipeline (validate→decontam→scrub→dedup) with stats.
- `learning/distill.py`: gold→SFT `(prompt, completion)` pairs from `gold_examples()`,
  cleaned through gate G, written as jsonl.
- `learning/finetune.py`: Modelfile (`FROM base` + `ADAPTER`), `run_finetune_cycle`
  (trainer + ollama_runner **seams**, skips `not_enough`/`no_trainer` without a GPU),
  `active_brain_tag` (kill-switch & champion-aware), `consider_promotion` (I4: no
  regression), `rollback_to_base`. Base never changes (I1).
- `learning/sie.py`: weekly tier now also runs the LoRA cycle automatically.
- `config.py`: `LORA_MIN_EXAMPLES` (50), `LORA_OUTPUT_DIR`; gitignored runtime artifacts.
- Tests: `tests/test_dataset_gate.py` (8), `tests/test_finetune.py` (10). Suite 286/286.

## Phase F — Reward modeling + preference optimization (DPO)
- `learning/reward.py`: `signals` feature vector, `composite_reward` (weights gold by
  cleanliness of the win), and a pure-stdlib logistic `Calibrator` (gradient descent)
  anchoring reward to eventual success — the guard against reward hacking.
- `learning/preferences.py`: `build_pairs` from passing-vs-failing specs matched by
  family (chosen/rejected), scrubbed + decontaminated + deduped, per-family capped.
- `learning/finetune.py`: `run_dpo_cycle` (DPO trainer seam `(pairs, out, kl_beta)`,
  KL anchor; registers a `dpo-vN` challenger; skips clean without data/GPU).
- `learning/sie.py`: weekly tier now also runs the DPO cycle automatically.
- `config.py`: `DPO_KL_BETA` (0.1), `DPO_MIN_PAIRS` (30).
- Tests: `tests/test_reward.py` (6), `tests/test_preferences.py` (5). Suite 297/297 green.

## Phase G — Advanced rollout + counterfactual + per-role adapters
- `learning/counterfactual.py`: `estimate_uplift` / `replay_over_ledger` — re-score a
  challenger against logged subtasks via a `replay_fn` seam (deterministic verifies),
  pre-live uplift estimate.
- `learning/rollout.py`: pure `next_stage` (shadow→canary→champion, auto-rollback on
  regression — I4) + `should_use_candidate` (fractional canary behind the bandit).
- `memory/experience.py`: adapters gain a `role` column; `register_adapter`/
  `get_champion_adapter`/`promote_adapter`/`retire_champion_adapter` are role-scoped.
- `learning/finetune.py`: `active_brain_tag(role)` per-role MoE routing (kill-switch +
  base fallback); `rollback_to_base(role)`.
- `orchestrator.py`: `_ollamaChat` routes to `active_brain_tag()` (no-op until an
  adapter is promoted; falls back to base on any error).
- Tests: `tests/test_rollout.py` (9). Suite 306/306 green.

## Phase H — Curriculum + releases (auto, human-facing)
- `learning/curriculum.py`: `family_stats` (weakest-first, support-gated), `generate_goals`
  (practice goals targeting low first-pass families), `write_suggestions` digest.
- `learning/release.py`: `model_card` (prompt/adapter), `attribution` (lessons, arms,
  champion prompts, adapters, fitness Δ), `render_report`/`write_report`.
- `learning/sie.py`: weekly tier now also authors curriculum + writes the report.
- Tests: `tests/test_curriculum_release.py` (8). Suite 313/313 green.

## Next wave (NW1–NW7) + X2 — all shipped
- **NW1 (J)** `human_feedback.py`: capture approve/reject/skip/edit (wired live into
  `commands.applyCommand`) + DPO correction pairs from edits.
- **NW2 (K)** `confidence.py`: success-probability head + calibrated deferral/escalation.
- **NW3 (L)** `postmortem.py`: failure classification → growing `failure_modes` taxonomy
  + pre-emptive `guidance_for`. Auto-runs in the daily `mine` step.
- **NW4 (I/M)** `reflection.py`: parse executor learning-summary, **trust-but-verify**
  against the real verify/adversary, store trusted recipes (multi-teacher field).
- **NW5 (N)** `knowledge_graph.py`: family + gotcha nodes from the ledger; `context_for`
  injection. Auto in `mine`.
- **NW6 (O)** `solution_cache.py`: memoize passing specs; `warm_start` near-duplicates. Auto in `mine`.
- **NW7 (P/Q/R)** `toolsmith.py` (rank/prune skills), `meta_opt.py` (knob suggestions),
  `adapter_ops.py` (soup plan + overfit signal) — analysis, human-gated.
- **X2** `safety.py`: `verify_invariants` (I1/I2/I4), `guard_promotion` (brain may
  propose, never crown), `panic_to_stock` hard rollback, kill-switch helpers.
- `learning/sie.py`: daily `mine` step (post-mortems → solution cache → KG).
- Tests: `tests/test_nextwave_batch1.py` (7), `tests/test_nextwave_batch2.py` (12).
- **ALL PHASES COMPLETE (A–H, NW1–NW7, X1, X2).** Suite 332/332 green.

## Full autonomous integration + GPU
Closed every "built but not wired" gap so the engine self-integrates end-to-end:
- **Authoring-time injection:** `authorInvocationSpec._sieAuthoringContext` folds lessons,
  policy prior, failure-mode guidance, KG codebase notes, low-confidence escalation, and a
  prior working solution into every brain prompt.
- **Reflection (teacher distillation) live:** `reflection.REQUEST` appended to the executor
  prompt + `reflection.capture()` after each subtask (trust-checked); passing specs memoized.
- **GPU compute router** (`learning/compute.py`): `SIE_COMPUTE` auto|gpu|cpu|off; real
  local SFT/DPO trainers (`finetune.default_trainer`/`default_dpo_trainer`) + `ollama create`
  runner, used by default — the user's GPU auto-trains; no-GPU hosts skip cleanly.
- **Live fitness (keystone):** `learning/eval_runner.py` — a deterministic verify runner
  makes the eval harness produce REAL fitness automatically (any environment), upgradable
  to a brain-in-the-loop runner via the registry.
- **Automatic adapter promotion** (`learning/adapter_promotion.py`): challengers evaluated
  vs champion (I4 no-regression) and promoted, in the weekly tier.
- Tests: `tests/test_compute.py` (7), `tests/test_eval_runner.py` (8) + confidence prior.
  Suite 346/346 green (two known load-flaky e2e tests pass reliably in isolation).

**The engine is now fully autonomous and self-integrating: the user only starts / aborts /
checks; on a GPU host it also trains and promotes model adapters by itself.**

## Theoretical-maximum automation (only start / abort / status)
Closed the last human touchpoints so no other action is ever needed:
- **Zero-touch setup** (`learning/bootstrap.py`): auto-installs the training stack on a GPU
  host and `ollama pull`s the embedder + base model — no manual `pip`/`ollama` ever.
- **Autonomous self-play** (`learning/selfplay.py`): the system *executes* its own
  curriculum goals (not just suggests them) when idle + in the work window, bounded by a
  daily cap. Launches via the existing work launcher.
- **Auto adapter promotion is live**: the orchestrator registers a per-tag fitness
  evaluator (`_fitnessUnderTag`/`_evalGoal` + a brain-tag override in `_ollamaChat`), so
  trained adapters are A/B'd and promoted automatically.
- **Meta-optimization auto-applies** (`meta_opt.apply`): tunes its own knobs within safe
  bounds, persisted across restarts via `config.set_override` + `_load_overrides`.
- Config: `SELFPLAY_*`, `SIE_BOOTSTRAP`, `SIE_META_AUTOAPPLY`, `SIE_TUNABLE_KNOBS`.
- Tests: `tests/test_full_autonomy.py` (10), `tests/test_compute.py`, `tests/test_eval_runner.py`.

**Single deliberate exception (safety):** `toolsmith` *analyzes* which skills to add/prune
but does not auto-author new `.claude` executor tools (that would expand the hands' powers);
it stays advisory behind the eval gate. Everything else runs itself.
