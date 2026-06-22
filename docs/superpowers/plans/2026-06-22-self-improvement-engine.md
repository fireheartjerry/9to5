# Self-Improvement Engine (SIE) — Implementation Plan

> **Status:** approved plan. Implements the design in
> `docs/superpowers/specs/2026-06-22-self-improvement-engine-design.md`.
> Phased A–H across ~6 months; each phase ships independently and no later phase blocks
> an earlier win. Develop on `claude/model-self-improvement-plan-rw1u32`.
> **Constraint:** strictly zero marginal API cost — local embeddings, local grading,
> local training; Claude Code CLI's existing outputs are the only training signal.

## Architecture (layering)

```
state/experience.db        SQLite (WAL) episodic ledger — the substrate                [new]
memory/experience.py(new)  ledger: schema + record_run/record_subtask + query helpers
memory/retrieval.py(new)   local embeddings (nomic-embed-text) + top_k_similar + lessons render
learning/__init__.py(new)
learning/eval_harness.py   golden-suite runner + fitness scoring (the spine)           [new]
learning/eval_suite/       ~15 golden goals + held-out (non-brain) verifies            [new]
learning/lessons.py(new)   L2 nightly consolidation → lessons rows + lessons.md
learning/policy.py(new)    L4 contextual bandit over policy_arms
learning/prompts.py(new)   versioned prompt registry (champion/challenger loader)
prompts/*.md               externalized system prompts + metadata                      [new]
learning/promotion.py(new) champion/challenger gate (eval + proportion test + Thompson)
learning/reward.py(new)    composite reward + local logistic calibrator
learning/preferences.py(new) DPO/ORPO pair builder (gold vs failed same-subtask)
learning/dataset.py(new)   data-quality gate G: dedup/decontam/scrub/validate
learning/distill.py(new)   SFT/DPO dataset materialization from gold_examples()
learning/finetune.py(new)  local LoRA driver + Modelfile + ollama create; per-role adapters
learning/counterfactual.py(new) offline replay of challengers on logged subtasks
learning/rollout.py(new)   shadow→canary→champion staging behind the bandit
learning/curriculum.py(new) self-play goal generation on weakest families
learning/release.py(new)   model cards, versioning, per-layer attribution report
config.py                  + SIE config block (all env-driven)                         [edit]
orchestrator.py            + retrieval injection (:441/:581); + adapter/role router     [edit]
state/task.py              sink shim: existing record* methods also write the ledger    [edit]
notifications/             + fitness time-series panel/embed                            [edit]
```

**No import cycles:** `memory/experience` is a leaf (stdlib only). `memory/retrieval`
imports `experience` + `config`. Everything in `learning/` imports `memory/*` +
`config`; nothing in `memory/` imports `learning/`. `orchestrator` imports `memory/*`
and `learning/{prompts,policy}` at its existing brain-call sites.

## Conventions (match the codebase)

`ALL_CAPS` module constants, `snake_case` variables, `camelCase` functions,
`pathlib.Path` everywhere (never `os.path`). No hardcoded secrets — all paths/thresholds
read from `config.py`, which reads `C:\supercritical\.env`. Tests are stdlib
`unittest` under `tests/`, runnable offline (mock Ollama/GPU). Ledger writes are
**best-effort** and must never block or fail a run.

## Data model — `state/experience.db` (SQLite, WAL)

- **`runs`**: `run_id PK, task_id, goal_raw, goal_elaborated, goal_embedding BLOB,
  universe_json, control_mode, started_at, ended_at, status, fitness_json,
  prompt_set_id, adapter_id`.
- **`subtasks`**: `id PK, run_id FK, st_id, position, title, signature_tags, effort,
  model, skills_json, subagents_json, invocation_spec_json, cost_usd, num_turns,
  session_id, verify_cmd, verify_expect, verify_passed, attempt_count,
  adversary_verdict, adversary_concerns_json, replan_delta_json, status, started_at,
  ended_at, embedding BLOB`.
- **`lessons`**: `id PK, scope(effort|skill|failure_fix|prompt_antipattern),
  signature_tags, text, support_count, win_rate, last_seen_at, embedding BLOB`.
- **`prompt_variants`**: `id PK, role, version, parent_id, body_hash, file_path,
  created_at, state(champion|challenger|retired)`.
- **`prompt_metrics`**: `variant_id FK, n_uses, first_pass_rate, mean_attempts,
  challenge_rate, clarify_rate, mean_cost, updated_at`.
- **`policy_arms`**: `id PK, context_key, action_json, pulls, reward_sum, reward_sq_sum`.
- **`eval_runs`**: `id PK, suite_version, prompt_set_id, adapter_id, ran_at,
  score_json, passed_gate BOOL`.
- **`adapters`**: `id PK, base_model, lora_path, modelfile_path, n_train_examples,
  trained_at, eval_run_id FK, state(champion|challenger|retired)`.

Public helpers: `record_run`, `record_subtask`, `top_k_similar(embedding, k, filter)`,
`arms_for(context_key)`, `gold_examples()`, `fitness_series()`.

## Algorithms (implement exactly)

**Retrieval (L1):** signature = `goal_embedding ⊕ title_embedding` (local
`nomic-embed-text`, cached per run) → `top_k_similar(sig, k=RETRIEVAL_K, filter=verify_passed)`
→ render ≤`RETRIEVAL_MAX_TOKENS` lessons block (effort, skills, one-line fix if a retry
was needed), compressed via the CLAUDE_CAPABILITIES routine → prepend through the
`injectCapabilities()` seam.

**Consolidation (L2, nightly):** group `subtasks` by `signature_tags`; per group
compute first-pass rate per effort level and per skill set; emit a `lessons` row when
`support_count ≥ LESSONS_MIN_SUPPORT` and the best/worst arm `win_rate` gap ≥ 20pts.
Decay: `last_seen_at > 30d` → halve `support_count`. Brain writes the `lessons.md` digest.

**Prompt promotion (L3):** challenger replaces champion only when **both** hold — (a)
eval-harness `first_pass_rate ≥ champion` AND `mean_cost` not worse by >10%; (b) field
metrics over ≥`PROMPT_PROMOTE_MIN_USES` uses pass a one-sided proportion test
(z ≥ `PROMPT_PROMOTE_Z`, default 1.64) on `first_pass_rate`. Else retire. Thompson
sampling picks the next challenger to trial.

**Policy bandit (L4):** `context_key` = coarse signature bucket (task family ×
predicted difficulty). Actions = effort × {opus, sonnet} × top skill sets. Reward =
`1.0·first_pass − 0.3·(attempts−1) − 0.2·norm_cost − 0.1·norm_wallclock`. Gaussian
Thompson sampling over `policy_arms`. Output is a prior the brain may override.

**LoRA (L5):** `gold_examples()` = `verify_passed ∧ attempt_count==1 ∧
adversary_verdict=approved ∧ no human override`, using held-out verifies → format SFT
pairs `(system+user → invocation_spec_json | plan | replan)`, dedup by `body_hash`,
cap per family → train LoRA (PEFT/unsloth) on frozen `qwen2.5-coder:7b` (host GPU,
queued) → Modelfile (`FROM qwen2.5-coder:7b` + `ADAPTER ./lora`), `ollama create
9to5-brain:vN`, register adapter as **challenger** → gate through harness incl. replay
set → promote or retire. Rollback = repoint the Ollama tag to the prior champion.

**Eval fitness:** `0.5·first_pass_rate + 0.2·(1−norm_attempts) + 0.15·(1−norm_cost)
+ 0.1·plan_stability + 0.05·(1−challenge_rate)`.

## Config additions (`config.py`, env-driven)

`EXPERIENCE_DB_PATH`, `EMBED_MODEL` (default `nomic-embed-text`), `RETRIEVAL_K` (5),
`RETRIEVAL_MAX_TOKENS` (350), `LESSONS_MIN_SUPPORT` (3), `PROMPT_PROMOTE_MIN_USES` (20),
`PROMPT_PROMOTE_Z` (1.64), `EVAL_SUITE_DIR`, `EVAL_FITNESS_WEIGHTS`, `REWARD_WEIGHTS`,
`LORA_MIN_EXAMPLES`, `LORA_OUTPUT_DIR`, `BRAIN_MODEL_TAG` (`9to5-brain`),
`PER_ROLE_ADAPTERS` (bool), `DPO_KL_BETA`, `CONSOLIDATION_CRON`, `PROMOTION_CRON`,
`SIE_KILL_SWITCH` (bool — revert to base + freeze promotions).

## Hook points in existing code (surgical)

- **Ledger writes:** add a best-effort `experience.record_*` call inside
  `TaskState.recordVerify` (`state/task.py:223`), `addAdversaryReview` (`:284`), and
  the replan-log write. No control-flow change — a parallel sink wrapped in try/except.
- **Retrieval injection:** in `authorSubtaskPlan` (`orchestrator.py:441`) and
  `authorInvocationSpec` (`:581`), prepend the lessons block through the same
  `injectCapabilities()` seam already used for capabilities.
- **Prompt registry:** `learning/prompts.py` loads the champion body for each role,
  replacing the constants at `orchestrator.py:198`, `replanner.py:21`,
  `elaborator.py:18`, `adversary.py:35`. Phase D keeps byte-identical champions so
  behavior is unchanged until a challenger is promoted.
- **Adapter/role router:** at brain-call sites, select the Ollama model tag from the
  champion adapter (per-role in Phase G) instead of the static `OLLAMA_MODEL`.

## Phasing — granular tickets (each with an acceptance check)

### Phase A — Capture + Measure (wk 1–2) — *days/weeks foundation*
- **A1** `memory/experience.py`: SQLite schema + `record_run`/`record_subtask`. ✅ unittest does an insert/query roundtrip on a temp DB.
- **A2** Wire best-effort sinks at `recordVerify`/`addAdversaryReview`/replan-log — no control-flow change. ✅ a live (or dry-run) task populates `experience.db`.
- **A3** Backfill script over `TaskState.iterStored()` + Obsidian. ✅ existing `state/tasks/*.json` appear as rows.
- **A4** `learning/eval_harness.py` skeleton + ~15-goal `eval_suite/` with held-out verifies + fitness formula. ✅ `python -m learning.eval_harness` writes an `eval_runs` row.

### Phase B — Retrieval (wk 3–4) — *days*
- **B1** `memory/retrieval.py`: local embeddings + `top_k_similar`. ✅ returns ranked neighbors on seeded data (Ollama mocked in tests).
- **B2** Lessons-block render + compression ≤ `RETRIEVAL_MAX_TOKENS`. ✅ unit test asserts the token cap.
- **B3** Inject at `authorSubtaskPlan`/`authorInvocationSpec`. ✅ harness fitness ≥ pre-B baseline.

### Phase C — Consolidation + Policy (month 2) — *days/weeks*
- **C1** `learning/lessons.py` nightly mining → `lessons` rows + `lessons.md`. ✅ digest regenerates from the ledger.
- **C2** `learning/policy.py` bandit + `policy_arms`; expose prior to the spec author. ✅ reward updates per subtask; arm stats persist.
- **C3** Discord/web fitness time-series panel. ✅ a daily fitness point is visible.

### Phase D — Prompt Evolution (month 2–3) — *weeks*
- **D1** `learning/prompts.py` registry; migrate hardcoded constants to `prompts/*.md`. ✅ champion bodies load byte-identical to today's constants (golden test).
- **D2** `learning/promotion.py` champion/challenger + proportion test + Thompson pick. ✅ a seeded clear-win challenger promotes; a clear-loss one retires.
- **D3** Gated-mode `!approve` hook on promotions + Obsidian/Discord log. ✅ promotion blocks on approval in `gated` mode.

### Phase E — LoRA Distillation, SFT (month 3+) — *months*
- **E0** `learning/dataset.py` quality gate G (dedup/decontam/scrub/validate). ✅ rejects eval-suite rows and secret-bearing rows.
- **E1** `learning/distill.py` gold dataset builder. ✅ emits deduped SFT jsonl from `gold_examples()`.
- **E2** `learning/finetune.py` queued local LoRA + Modelfile + `ollama create`. ✅ produces tag `9to5-brain:vN` (GPU job mockable in CI).
- **E3** Adapter promotion through harness incl. replay set; rollback + kill switch. ✅ a regressing adapter auto-retires; kill switch reverts to base.

### Phase F — Reward modeling + preference optimization (month 4) — *months*
- **F1** `learning/reward.py` composite reward + local logistic calibrator. ✅ reward correlates with eventual success on held-out rows.
- **F2** `learning/preferences.py` DPO pairs from gold-vs-failed same-subtask. ✅ emits chosen/rejected jsonl.
- **F3** DPO/ORPO path in `finetune.py` with KL anchor. ✅ adapter beats SFT-only on the harness.

### Phase G — Advanced rollout + counterfactual (month 4–5)
- **G1** `learning/counterfactual.py` offline replay on logged subtasks. ✅ produces an uplift estimate pre-live.
- **G2** `learning/rollout.py` shadow→canary→champion behind the bandit. ✅ challenger flows through stages; auto-rolls back on regression.
- **G3** Per-role adapters + router in `finetune.py`/orchestrator. ✅ each role serves its own tag.

### Phase H — Curriculum + releases (month 5–6)
- **H1** `learning/curriculum.py` self-play goal generation on weakest families. ✅ generates valid goals targeting low-first-pass clusters.
- **H2** `learning/release.py` model cards + per-layer attribution report. ✅ each promotion writes a card; monthly attribution lands on the dashboard.

**Continuous:** fitness dashboard, drift detection, governance, rollback, kill switch,
cadence-ladder scheduling.

## Testing strategy

- **Offline-first:** every test runs without a live Ollama/GPU. Mock the Ollama client
  (embeddings + chat) and the LoRA trainer behind thin seams (mirror the existing
  `_ollamaChat` injection pattern and `agents/executor.py` subprocess seams).
- **New `tests/`:** `test_experience_ledger.py` (schema + roundtrip + WAL concurrency),
  `test_retrieval.py` (top-K + token cap), `test_lessons.py` (consolidation thresholds
  + decay), `test_policy_bandit.py` (reward update + Thompson), `test_prompt_registry.py`
  (champion byte-identity), `test_promotion.py` (proportion test + rollback),
  `test_eval_harness.py` (fitness formula + held-out verify integrity),
  `test_dataset_gate.py` (dedup/decontam/scrub), `test_distill.py` (gold filter),
  `test_finetune.py` (Modelfile emission, trainer mocked).
- **Regression guard:** Phase A/B must show **no** change to existing test outcomes
  (capture + injection are additive); the prompt-registry golden test guarantees Phase
  D is behavior-neutral until a challenger is promoted.

## Verification (end-to-end)

1. `python -m unittest discover -s tests` green (incl. new SIE tests).
2. A dry-run task (`python main.py --goal "..." --dry-run`) populates `state/experience.db`
   (Phase A) and injects a lessons block visible in the Obsidian subtask note (Phase B).
3. `python -m learning.eval_harness` writes an `eval_runs` row and a fitness point; the
   dashboard panel renders the time-series.
4. A seeded challenger promotes/retires correctly through `learning/promotion.py` and is
   logged to Obsidian + Discord; `gated` mode blocks on `!approve`.
5. Kill switch (`SIE_KILL_SWITCH`) reverts brain calls to the base `OLLAMA_MODEL` and
   freezes promotions.
