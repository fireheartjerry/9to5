# SIE Implementation Status

Progress tracker for the A→Z build of the Self-Improvement Engine. Spec:
`specs/2026-06-22-self-improvement-engine-design.md`. Plan:
`plans/2026-06-22-self-improvement-engine.md`. Built behind best-effort/flag seams so
existing behavior and tests stay green; phases needing GPU/Ollama/Discord/Obsidian are
implemented with the external call seam mocked and offline-testable logic real.

| Stage | Scope | State |
|---|---|---|
| **A — Capture + Measure** | Experience Ledger (`memory/experience.py`), best-effort TaskState sinks, backfill, eval-harness skeleton (`learning/eval_harness.py`) + golden suite + fitness math, config block | ✅ done |
| B — Retrieval | local embeddings + top-K + lesson injection | ⬜ next |
| C — Consolidation + Policy | nightly lessons mining + contextual bandit | ⬜ |
| D — Prompt Evolution | versioned registry + champion/challenger | ⬜ |
| E — LoRA Distillation (SFT) | data-quality gate + gold dataset + local LoRA | ⬜ |
| F — Reward + DPO | composite reward + preference pairs | ⬜ |
| G — Rollout + Counterfactual | offline replay + shadow/canary + per-role adapters | ⬜ |
| H — Curriculum + Releases | self-play goals + model cards + attribution | ⬜ |
| NW1–NW7 — Next wave (J–R) | human feedback, confidence, post-mortems, multi-teacher, KG, solution cache, research track | ⬜ |
| X1/X2 — Orchestrator + Safety | `learning/sie.py` cadence ladder + `learning/safety.py` invariants | ⬜ |

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
