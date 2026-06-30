# Epic 7 — Self-Evolving Intelligence (NET-NEW / amplify) — Design Spec

> **Date:** 2026-06-30 · **Status:** design (brainstorming output). Next: implementation
> plan (`docs/superpowers/plans/2026-06-30-epic7-self-evolving-intelligence.md`).
> **Read-only harvest.** Cites real source paths in `references/hermes`, `references/warp`,
> `references/loki-mode`, `references/generative-agents`, `references/bernstein` and the
> existing 9to5 SIE under `learning/`, `memory/`, `agents/`, `platform_core/`.
> **License posture:** hermes (MIT), warp (AGPL — patterns only, no file copy),
> generative-agents (Apache-2.0), bernstein (Apache-2.0) → portable ideas + reimplementation;
> loki-mode (BUSL-1.1) → **ideas only, reimplement**.

---

## 1. Goal + the new capability + honest contrast

### 1.1 Goal
Turn 9to5's self-improvement engine from one that evolves **only the brain's system
prompts** into one that **evolves its own executor-side procedural knowledge** — the
`.claude/skills/*`, the `agents/playbook.py` charters, the role constitutions, and reusable
playbooks — **distilled from real run outcomes, validated as a true improvement before
adoption, reversible, and continuous.** The compounding mechanism Hermes pioneers
(write-side learning loop → curated skill library) is the centerpiece.

### 1.2 The new / amplified capability
A closed **experience → insight → candidate → validation → promotion** loop for *capabilities*,
not just prompts:

1. **Consolidate** raw run outcomes into durable, **cited** principles (insights) — the
   generative-agents reflection primitive, missing today.
2. **Propose** a candidate change — a new/edited `.claude` skill, a playbook charter patch,
   or a constitution challenger — authored by a **forked Claude reviewer** (the strong
   teacher), grounded in those insights. This is the Hermes `background_review.py` pattern.
3. **Validate** the candidate beats the incumbent on a **held-out** suite via
   champion/challenger A-B before promotion (anti-reward-hacking, loki + bernstein).
4. **Promote or reject** safely — gated, reversible, audited — never touching
   `CORE_PROTECTED_FILES` or the core loop unsupervised.
5. **Curate** the accreting skill library into class-level umbrellas, archiving (never
   deleting) dead weight — the Hermes `curator.py` pattern.

### 1.3 Honest contrast — what the primitive SIE does today vs what this adds

The current SIE is **not** primitive on the prompt/policy/weights axis. It already has:

| Existing (keep, extend) | File |
|---|---|
| Cadence ladder (per-run / daily / weekly tiers, file-locked, kill-switch) | `learning/sie.py` |
| Champion/challenger **prompt** registry + provenance gate | `learning/prompts.py` |
| Statistical promotion gate (two-proportion z-test, Thompson pick, **I2 no-self-promotion**) | `learning/promotion.py` |
| Eval harness — golden suite + single `fitness` scalar; held-out verifies live in goal files | `learning/eval_harness.py` |
| Executor learning-summary capture + **trust-but-verify** cross-check | `learning/reflection.py` |
| Effort-stat lesson consolidation | `learning/lessons.py` |
| Failure taxonomy / KG / solution cache / policy / LoRA / DPO / curriculum / self-play | `learning/{postmortem,knowledge_graph,solution_cache,policy,finetune,curriculum,selfplay}.py` |
| Safety invariants I1/I2/I4 + kill switch + `panic_to_stock` | `learning/safety.py` |
| Core-file self-modification gate (post-run suite + causality-aware revert) | `selfmod.py` |

**Where it is genuinely primitive — the gaps this epic closes:**

| Gap | Today | This epic |
|---|---|---|
| **Skills are frozen** | `.claude/skills/*` and `agents/playbook.py::PROFILES` are **hardcoded constants**. `learning/toolsmith.py` can *rank* skills by verify-pass and flag prune candidates, but is explicitly **"analysis-only … authoring brand-new .claude tools is gated behind human approval"** — it never authors or patches a skill. | A write-side loop authors/patches skills + playbooks and gates them through the eval spine. |
| **Lessons are statistics, not insight** | `lessons.py` emits *"effort=high passed 80% vs default 40%"* — metadata, no reasoning. `reflection.py` captures executor self-reports but they become flat recipe strings. | An **insight tier**: importance-triggered reflection that synthesizes higher-level **cited** principles with provenance, decay, and recency (generative-agents). |
| **No write-side reviewer** | The brain never spawns a post-run reviewer to *propose* a capability change. | A forked Claude reviewer on a **write-only toolset** proposes candidates without touching the live run (Hermes `background_review.py`). |
| **Champion/challenger is prompt-only** | `prompt_variants` table + `promotion.py` evolve only system prompts. | A parallel **candidate registry** for skills/playbooks reusing the *same* promotion math + eval spine. |
| **No library curation** | Nothing consolidates or ages a growing skill set. | A **curator** with class-level umbrellas, archive-not-delete, dry-run, structured reports (Hermes `curator.py`). |

---

## 2. Non-Goals

- **NOT self-modifying the core loop or `CORE_PROTECTED_FILES` unsupervised.** Candidates
  that target `orchestrator.py`, `main.py`, `config.py`, `agents/hooks.py`, or any
  `CORE_PROTECTED_FILES` entry are **auto-rejected** by the evolution gate (new invariant
  I8). Core-loop self-edits keep flowing through the existing `selfmod.py` post-run suite
  gate + bytecode-inert pinning — this epic does **not** widen that surface.
- **NOT editing bundled / human-authored / pinned skills.** Evolution only touches
  **agent-authored** skills + the agent-authored override layer of playbooks (Hermes
  invariant; new I7). Hand-written skills (`architect-review`, `create-pr`, …) are read-only
  to the loop.
- **NOT self-promotion.** The evolver/brain may only *propose*; an independent statistical
  gate (+ human gate in `gated` mode) crowns. Extends existing **I2**.
- **NOT a new always-on daemon, no cloud, no API-graded validation.** Reuses the existing
  off-thread, file-locked, throttled `sie.run_maintenance` process model and the local eval
  harness. Zero marginal API cost stands (the forked reviewer reuses the Claude Code
  subprocess 9to5 already pays for).
- **NOT online adoption mid-run.** A candidate never changes the *running* run; it is
  inert until validated and promoted between runs (mirrors `selfmod.py` bytecode-inert rule).
- **NOT replacing** `prompts.py`, `promotion.py`, `eval_harness.py`, `reflection.py`,
  `lessons.py`, or `toolsmith.py` — every new module **extends** them.

---

## 3. Architecture (small units + interfaces)

New package `learning/evolution/` (skill/playbook candidate machinery) + one new
consolidation module `learning/insight.py` + a new candidate table. Everything else hangs
off existing seams. All new `learning/` code follows the **owning package's local style**
(`learning/` uses `snake_case` functions, `ALL_CAPS` consts — consistent with
`sie.py`/`promotion.py`); the one new file under `platform_core/orchestration/` follows that
package's `camelCase`. Every module ≤450 lines, every function ≤70 lines, with the required
`@AI-MAP v1` header.

```
runs accrue → (a) insight consolidation → (b) evolver proposes candidate
            → (c) held-out A-B validation → (d) gated promote / reject + audit
            → (e) extends sie.py ladder + prompts.py registry
```

### (a) Experience → insight consolidation loop — `learning/insight.py`

The generative-agents reflection primitive (`reference/generative-agents/.../reflect.py::run_reflect`
+ `retrieve.py::new_retrieve`), reimplemented over `experience.db`, plus loki's
episodic→semantic consolidation (`references/loki-mode` `memory/consolidation.py`, idea-only).

- **Importance scoring at write time.** Tag each new `subtasks`/`reflections`/`failure_modes`
  row with a `poignancy` 0–1 (generative-agents `generate_poig_score`): a cheap local-Ollama
  1-token score, or a deterministic proxy (failed verify + high attempts + adversary-challenged
  ⇒ high). Stored as a new column.
- **Importance-triggered reflection.** Not on a fixed schedule — fire when summed poignancy of
  new rows since last reflection crosses `INSIGHT_TRIGGER_BUDGET` (generative-agents
  `reflection_trigger`). The trigger lives as a new step in `sie.py`'s maintenance ladder.
- **Synthesis.** `consolidate_insights()` clusters recent high-poignancy rows by task family
  (reuse `lessons.family_of`) + bernstein failure taxonomy class, asks the local brain (or a
  deterministic template when offline) for the *3 most salient questions*, retrieves evidence
  rows, and writes higher-level **insight** records:
  - `text` (the durable principle), `scope` (family/taxonomy class), `poignancy`,
    `support_count`, `win_rate`, **`provenance_json`** = the run/subtask/reflection ids it was
    inferred from (generative-agents `filling`/`depth` — a citation graph; satisfies SIE **I6**).
  - Insights can cite insights (`depth`), giving an auditable derived-knowledge tree.
- **Retrieval upgrade.** `insight_block(goal, title)` ranks by **recency·importance·relevance**
  (generative-agents weighted score) not bare cosine, and is injected via the existing
  `_sieAuthoringContext` seam (`platform_core/orchestration/plan_mixin.py:357`) alongside
  today's `retrieval.lessons_block`. `lessons.py` stays for effort-stats; insight is the new
  higher tier.
- **Injection sanitizer.** Every insight string is collapsed/escaped before it enters any
  prompt (loki `memory/rag_injector.py::_sanitize_field`, idea-only) — strip control chars,
  defang leading markdown/instruction markers, per-field cap. Closes a real prompt-injection
  hole 9to5 has today (it injects retrieved lessons raw).

Interface:
```python
def score_poignancy(row: dict) -> float: ...
def consolidate_insights(*, db_path=None) -> dict: ...   # cited insights from recent runs
def insight_block(goal: str, title: str, *, db_path=None) -> str: ...  # sanitized, ranked
```

### (b) Skill / playbook / constitution evolution — `learning/evolution/`

The Hermes write-side loop, reimplemented for 9to5's "brain plans / Claude executes" split.

**`learning/evolution/evolver.py`** — the forked reviewer (Hermes
`references/hermes/agent/background_review.py`, MIT, the single most transferable idea).
- After a run finishes (and post-throttle), spawn a **separate Claude Code subprocess** as a
  *reviewer* — NOT the live executor — with:
  - a **write-only toolset**: `--disallowedTools` blocks everything except `Read`/`Glob`/`Grep`
    and the candidate-write surface (the reviewer writes a *candidate file under
    `state/evolution/candidates/`, never into `.claude/skills/` live). This is the 9to5
    analog of Hermes' `set_thread_tool_whitelist({memory, skills})` — the live run, its
    branch, and prompt-cache are never touched (Hermes' "fork on a restricted toolset so the
    main cache is never poisoned").
  - a prompt built from `evolver_prompts.py` carrying: the run's trusted `reflections`
    (`reflection.recipes`), the new high-poignancy `insights`, the bernstein failure-taxonomy
    deltas, and the `toolsmith.rank_tools` / `prune_candidates` evidence.
- **Authoring discipline ported near-verbatim from Hermes** `_SKILL_REVIEW_PROMPT`:
  - *Be ACTIVE but disciplined* — most runs should yield ≥1 small candidate, but "Nothing to
    propose" is a real option.
  - **Preference order**: (1) patch a currently-loaded skill, (2) patch an existing umbrella,
    (3) add a `references/`/`scripts/` support file, (4) create a new **class-level** skill —
    name at the class level, never a run id / error string / "fix-X-today" artifact.
  - **Do-NOT-capture list (port verbatim — this is the anti-poisoning core):**
    environment-dependent failures (missing binaries, unconfigured creds), **negative claims
    about tools** ("browser tools don't work" — these "harden into refusals the agent cites
    against itself for months"), transient errors that self-resolved, and one-off task
    narratives. These four rules are why a self-improving skill library doesn't rot.
- Output: one or more **candidate** records (never a live edit).

**`learning/evolution/candidate.py`** — the candidate registry (new `evolution_candidates`
table), the skills/playbooks analog of `prompt_variants`:
- Fields: `id`, `kind` ∈ {`skill`,`playbook`,`constitution`}, `target` (skill name / playbook
  profile / constitution role), `body`, `parent_champion_id`, `state` ∈
  {`proposed`,`validating`,`canary`,`champion`,`rejected`,`archived`}, `provenance_json`
  (cited insight/run ids → **I6**), field stats `{n, first_pass}` (for the z-gate).
- For **constitution** candidates this is a thin adapter over the *existing* `prompts.py`
  registry (`propose`/`promote`/`challengers`) — constitution evolution needs **no new
  storage**, only the candidate state machine to reach it. Skills/playbooks get the new table.
- `champion_body(kind, target)` returns the live skill/playbook text or the in-code constant
  byte-for-byte until a challenger is promoted (the zero-risk property of `prompts.get`).

**`learning/evolution/curator.py`** — library maintenance (Hermes
`references/hermes/agent/curator.py`, MIT):
- **Deterministic inactivity transitions** (always run, no LLM): walk agent-authored skills,
  move `active → stale → archived` by last-activity timestamp; **pinned bypass**; never
  delete — **archive is recoverable** (`state/evolution/.archive/`). Reuses
  `toolsmith.rank_tools` so a skill with enough support but a poor pass-rate becomes a prune
  candidate.
- **LLM umbrella-building consolidation** — **OFF by default** (Hermes
  `DEFAULT_CONSOLIDATE=False`); opt-in via config. Finds prefix clusters, merges siblings into
  class-level umbrellas, emits a structured YAML `consolidations:`/`prunings:` block with
  `absorbed_into=<umbrella>` so a downstream reviewer can tell consolidation from pruning.
- **Dry-run mode** (Hermes `CURATOR_DRY_RUN_BANNER`): preview the report without mutating.
- Per-run `run.json` + `REPORT.md` under `state/evolution/reports/` (Hermes report shape).

**`learning/evolution/evolver_prompts.py`** — the ported prompt strings (review discipline,
do-not-capture rules, curator umbrella policy) + the **HARDLINE skill-authoring standards**
from Hermes `references/hermes/agent/learn_prompt.py::_AUTHORING_STANDARDS` (description ≤60
chars, fixed section order, no invented APIs) so candidate skills are well-formed.

### (c) Validation harness — `learning/evolution/validate.py`

A candidate must **prove** it beats the incumbent before promotion. Extends
`eval_harness.run_suite`; never replaces it.

- **Champion/challenger A-B on the held-out suite.** Run the golden suite twice — once with
  the incumbent skill/playbook live, once with the candidate live — and compare `fitness`
  (`eval_harness.compute_fitness`). The candidate must win by the **same statistical gate**
  the prompt path already uses: `promotion.proportion_z` over first-pass rate with
  `PROMPT_PROMOTE_MIN_USES` / `PROMPT_PROMOTE_Z` (no new math).
- **Held-out spec evals (anti-reward-hacking)** — loki
  (`references/loki-mode` `skills/quality-gates.md`, idea-only) + the existing "verifies the
  brain did not author" property of `eval_harness.load_suite`. Reserve
  `clamp(round(0.25·N),1,5)` acceptance checks per goal, **hidden from the evolver's prompt**
  and from the candidate's view, evaluated only at the validation gate. A candidate that
  optimizes the checks it can see still fails the ones it can't.
- **Counterfactual offline replay** — re-run the candidate vs incumbent over **logged past
  subtasks** (deterministic, zero-API) to estimate uplift before any live exposure. Extends
  the existing `learning/counterfactual.py`.
- **Self-measuring adherence (the bernstein hint engine + loki Evidence Receipt).** Grade
  whether the candidate skill actually **changed executor behavior**: did the executor follow
  the new contract? Signal = the executor's `reflection.spec_feedback` / `verify_critique`
  (does it cite the new guidance?) blended with a deterministic adherence score. Produces an
  **Evidence Receipt** (loki `proof-generator.py`, idea-only): a `validation.json` splitting
  re-derivable **facts** (incumbent fitness, candidate fitness, held-out pass counts, z-score)
  from LLM **assessments** (the reviewer's opinion). The green "promote" verdict derives
  **only from facts** — an LLM opinion can never make it green.
- **Drift / Goodhart guard** — bernstein (`references/bernstein` `evolution/`, idea-only):
  watch the `fitness` series with a cheap change-point check (EWMA/CUSUM) before adopting; if
  recent fitness is already declining, freeze promotions and alert (reuses
  `eval_harness.fitness_panel`'s series).

Interface:
```python
def validate_candidate(candidate_id: int, *, runner=None, db_path=None) -> dict:
    # returns Evidence Receipt: {facts:{...}, assessments:{...}, verdict: promote|reject|insufficient}
```

### (d) Safe promotion + rollback + audit — `learning/evolution/promote.py` + extend `safety.py`

- **Promotion** is the candidate analog of `promotion.run_promotions`: pick one challenger per
  target (Thompson, reuse `promotion.pick_challenger`), call `validate_candidate`, and on a
  **facts-only** green verdict flip the champion. **I2 holds** — `safety.guard_promotion`
  refuses a `brain`/`evolver` actor; only this gate (and, in `gated` mode, a human `!approve`)
  crowns. Constitution candidates route straight through `prompts.promote` (unchanged path).
- **Staged rollout (warp feature-flag lanes, idea-only)** — `proposed → validating → canary
  (small fraction of real subtasks behind the existing policy bandit) → champion`, with
  auto-rollback at any stage (loki `checkpoint.ts` "undo is itself undoable", idea-only). The
  prior champion is always one row-flip away (O(1) total rollback, like `prompts`).
- **Protected-file / core-loop fences (first-class).** Before a skill/playbook candidate is
  ever *written* live, `promote.py` runs the **same** guard used by the executor:
  `selfmod.core_files_changed` + the `CORE_PROTECTED_FILES` set + the
  `agents/hooks_selfmod` path check. Any candidate touching a protected path or a core-loop
  file is **auto-rejected** (new **I8**). Skill writes land only under the agent-authored
  skill dirs (new **I7**); bundled/pinned skills are untouchable.
- **Human gate.** In `gated` mode, *shipping a self-authored skill always asks* (matches the
  prior SIE spec's subsystem-P rule "tool ship always asks"); constitution/playbook promotion
  auto-gates on the harness in `watch` mode. The kill switch (`SIE_KILL_SWITCH` / `!stock`)
  freezes all of evolution and `panic_to_stock` extends to retire champion skills/playbooks.
- **Audit.** Every propose/validate/promote/reject/rollback writes an Obsidian note + a
  Discord embed + a `REPORT.md` (Hermes curator report shape), and a row whose
  `provenance_json` cites the insights/runs that produced it.

### (e) How this extends `sie.py` + `prompts.py` (not replaces)

- `learning/sie.py::_maintenance_steps` gains an **`insight`** step (consolidation);
  `_weekly_steps` gains **`evolve`** (spawn evolver → register candidates), **`evolve_promote`**
  (validate + promote one challenger per target), and **`curate`** (curator pass). Each is an
  independent, best-effort, file-locked step — one failing never blocks the others (existing
  contract).
- A new **per-run inline hook** fires the evolver post-run from the orchestrator's `finally`
  block (where `sie.run_maintenance_async` already fires), throttled like every heavy pass.
- `prompts.py` is **unchanged**; constitution evolution reaches it through the candidate
  adapter. `promotion.py` gains a thin `decide`-reuse for the new `kind`s (or `promote.py`
  imports `promotion.decide`/`proportion_z` directly — no duplication).

---

## 4. Data flow

```
1. RUN executes (unchanged). reflection.capture() stores trusted executor summaries;
   experience.db accrues subtasks / failure_modes / pr_outcomes (unchanged sinks).
        │
2. CONSOLIDATE (insight.py, importance-triggered in sie.py ladder):
   score_poignancy → when budget crossed → consolidate_insights →
   cited `insights` rows (provenance = run/subtask ids).            [generative-agents + loki]
        │
3. PROPOSE (evolution/evolver.py, post-run inline + weekly):
   forked Claude reviewer (write-only toolset) reads insights + trusted reflections +
   taxonomy deltas + toolsmith ranking → writes CANDIDATE records (skill/playbook/
   constitution) under state/evolution/candidates/. Never edits live.   [hermes background_review]
        │
4. VALIDATE (evolution/validate.py, weekly):
   A-B the candidate vs incumbent on the held-out golden suite → proportion_z gate +
   held-out spec evals + counterfactual replay + adherence score → Evidence Receipt
   (facts vs assessments; green only from facts).              [loki + bernstein + eval_harness]
        │
5. PROMOTE or REJECT (evolution/promote.py, gated):
   facts-green + I7/I8 fences pass + (gated→human !approve) → flip champion via candidate
   registry / prompts.promote. Staged shadow→canary→champion; auto-rollback on regression.
        │
6. CURATE (evolution/curator.py, weekly): deterministic age-out (archive, recoverable) +
   opt-in umbrella consolidation.                                          [hermes curator]
        │
7. AUDIT: Obsidian note + Discord embed + REPORT.md; provenance row cites the insights/runs.
   Next run's _sieAuthoringContext injects the promoted skill/playbook + sanitized insights.
```

---

## 5. Exact file structure

### Created
| Path | Responsibility | ≤450? |
|---|---|---|
| `learning/insight.py` | Poignancy scoring, importance-triggered reflection, cited insight synthesis, ranked+sanitized `insight_block`. | yes |
| `learning/evolution/__init__.py` | Package facade — re-export `propose_candidates`, `validate_candidate`, `run_evolution_promotions`, `run_curator`. | yes |
| `learning/evolution/evolver.py` | Spawn the forked Claude reviewer on a write-only toolset; build candidates from insights/reflections. | yes |
| `learning/evolution/evolver_prompts.py` | Ported review-discipline + do-not-capture + curator + HARDLINE authoring-standard strings (consts). | yes |
| `learning/evolution/candidate.py` | `evolution_candidates` registry; champion/challenger state machine; constitution adapter over `prompts.py`. | yes |
| `learning/evolution/validate.py` | Held-out A-B, spec-eval holdout, counterfactual replay, adherence score, Evidence Receipt. | yes |
| `learning/evolution/promote.py` | Gated promotion + staged rollout + rollback + I7/I8 protected-file fences + audit. | yes |
| `learning/evolution/curator.py` | Deterministic age-out (archive-not-delete) + opt-in umbrella consolidation + dry-run + reports. | yes (split helpers if needed) |
| `platform_core/orchestration/evolution_hook.py` | `camelCase` thin hook: fire evolver post-run from the orchestrator `finally`, throttled. | yes |
| `tests/test_insight.py`, `test_evolution_candidate.py`, `test_evolution_validate.py`, `test_evolution_promote.py`, `test_evolution_curator.py`, `test_evolution_safety.py` | Unit + safety tests (see §7). | yes |
| `state/evolution/eval_suite/` (held-out fixtures) | Golden goals for skill/playbook A-B (mirrors `learning/eval_suite/`). | n/a |

### Modified (surgical, facades preserved)
| Path | Change |
|---|---|
| `memory/experience_schema.py` | Add `evolution_candidates` table; add `poignancy`/`provenance_json` cols to `insights` (new) + nullable `poignancy` to `subtasks`/`reflections`. Additive only (existing `_migrate` pattern). |
| `memory/experience.py` (+ a new `memory/experience_evolution.py` sub-module behind the facade) | CRUD for candidates + insights (matches the `experience_*` split convention). |
| `learning/sie.py` | Add `insight` to `_maintenance_steps`; add `evolve` / `evolve_promote` / `curate` to `_weekly_steps`. No control-flow change — same best-effort step list. |
| `learning/safety.py` | Add **I7** (only agent-authored skills evolve) + **I8** (no candidate touches `CORE_PROTECTED_FILES`/core loop) to `verify_invariants`; extend `panic_to_stock` to retire champion skills/playbooks. |
| `learning/promotion.py` | Export `decide`/`proportion_z` for reuse by `evolution/promote.py` (already public — no change) — documented dependency only. |
| `platform_core/orchestration/plan_mixin.py` | `_sieAuthoringContext` appends `insight.insight_block(...)` (one more best-effort `fn` in the existing loop) + injects the promoted playbook/skill champion bodies. |
| `agents/playbook.py` | `buildCharter`/`buildPlaybook` consult `evolution.candidate.champion_body("playbook", profile)`, falling back **byte-for-byte** to the in-code `PROFILES` constant until a challenger is promoted (the `prompts.get` zero-risk pattern). |
| `learning/toolsmith.py` | No logic change; `prune_candidates` becomes an input to the curator + evolver (documented consumer). |
| config (`platform_core/config_*`) | New consts: `EVOLUTION_ENABLED` (default False), `EVOLUTION_CONSOLIDATE` (default False), `INSIGHT_TRIGGER_BUDGET`, `EVOLUTION_CANARY_FRACTION`, `EVOLUTION_SUITE_DIR`. |
| `AGENTS.md` | Regenerate via `python tools/repo_map.py` after the new modules land. |

---

## 6. Error handling + safety rails

- **Best-effort isolation (existing SIE contract).** Every new step is wrapped like
  `sie._maintenance_steps`: one step's exception is logged + recorded as
  `{"error": ...}` and never blocks the run or the other steps. The evolver subprocess
  failing is a no-op for the run.
- **Validation gate is the load-bearing rail.** No candidate is adopted without a
  **facts-green** Evidence Receipt (held-out A-B win + spec-eval holdout pass). `insufficient`
  (too few uses) and `reject` keep the incumbent. The brain/evolver can never self-promote
  (`safety.guard_promotion`, **I2**).
- **Protected-file / core-loop fences (first-class, fail-closed).** `promote.py` re-uses
  `selfmod.core_files_changed` + `config.CORE_PROTECTED_FILES` + the `agents/hooks_selfmod`
  path classifier before any live write. A candidate targeting a protected/core path is
  rejected and the attempt audited (**I8**). Skill writes are confined to agent-authored
  skill dirs (**I7**); bundled/human-authored/pinned skills are untouchable.
- **Reversibility.** Every promotion is a one-row champion flip with the prior champion
  retained; curator archives (never deletes) into `state/evolution/.archive/` and supports
  restore (Hermes `curator restore`). Staged rollout (shadow→canary→champion) bounds blast
  radius; auto-rollback fires on a fitness regression (**I4**, extended to skills/playbooks).
- **Anti-poisoning of the library.** The Hermes do-not-capture rules + the loki injection
  sanitizer + `reflection.trust` (already cross-checks self-reports against the real verify +
  adversary verdict) mean only *trusted, non-environment-dependent* signal becomes an insight,
  and only insights feed candidates.
- **Kill switch.** `SIE_KILL_SWITCH` / `!stock` freezes consolidation, evolution, and
  promotion; `panic_to_stock` retires champion skills/playbooks back to the in-code constants
  — always one command from "stock."
- **Provenance (I6).** Every insight/candidate/champion row carries `provenance_json` tracing
  to the runs that produced it; an orphan-provenance candidate is refused (mirrors
  `prompts.get`'s provenance gate).

---

## 7. Testing strategy

Local-first, deterministic, offline. `python tools/dev.py check <file>` per edit; matching
`tests/test_*.py` (flat files — the playbook tester rule). Inject a deterministic
`runner(goal)->result` into `validate_candidate` so no live brain is needed (the
`eval_harness` already supports this seam).

**Core proof — a bad candidate is rejected, a good one promoted (the success criterion in test
form):**
- `test_evolution_validate.py`:
  - **Bad candidate rejected.** Seed a temp `experience.db`; register a challenger skill whose
    A-B run scores *worse* (lower `first_pass_rate`) than the incumbent on the held-out suite →
    assert `validate_candidate` returns `verdict="reject"` and the champion is unchanged.
  - **Reward-hacking candidate rejected.** A candidate that passes every *visible* acceptance
    check but fails the **held-out** 25% → assert `reject` (proves anti-reward-hacking).
  - **Good candidate promoted.** A challenger that beats the incumbent past
    `PROMPT_PROMOTE_MIN_USES`/`PROMPT_PROMOTE_Z` → `verdict="promote"`; after
    `promote.run_evolution_promotions`, `candidate.champion_body` returns the new body.
  - **Facts-only green.** A receipt whose LLM `assessment` is positive but `facts` show a
    fitness loss → still `reject` (assessment can't make it green).
- `test_evolution_safety.py` (I7/I8 fences):
  - A candidate whose `target`/diff touches a `CORE_PROTECTED_FILES` entry or core-loop file →
    auto-rejected; `verify_invariants` reports no violation after.
  - A candidate targeting a bundled/pinned skill → refused (I7).
  - `SIE_KILL_SWITCH=1` → `propose`/`validate`/`promote` all no-op; `panic_to_stock` retires
    champion skills/playbooks.
- `test_evolution_candidate.py`: champion/challenger state machine; `champion_body` returns the
  in-code constant byte-for-byte until a promotion (the `prompts.get` zero-risk invariant);
  constitution candidates round-trip through `prompts.propose`/`promote`.
- `test_insight.py`: poignancy scoring; importance trigger fires only past
  `INSIGHT_TRIGGER_BUDGET`; synthesized insight carries provenance ids (I6); `insight_block`
  ranks recency·importance·relevance and the sanitizer strips injected `###`/instruction lines.
- `test_evolution_curator.py`: deterministic age-out moves `active→stale→archived` and is
  **recoverable** (archive, not delete); pinned skills bypass; consolidation OFF by default;
  dry-run mutates nothing; structured `consolidations/prunings` parse.
- **Evolver subprocess** is unit-tested behind an injected spawn seam (no real Claude call in
  CI) asserting the **write-only toolset** (`--disallowedTools` blocks Edit/Write outside the
  candidate dir) and that the live run/branch is never touched.
- **Regression:** assert "consumes trace without mutating the live run" (the `learning/`
  target scenario in `docs/TESTING.md`) for every new step.

Verification commands: `python tools/dev.py check learning/evolution/validate.py` (and each
new file) → `python tools/dev.py fast` before handoff → `python tools/size_audit.py` (zero
`must_split`) → `python tools/repo_map.py` to regenerate `AGENTS.md`.

---

## 8. Risks + mitigations + sequencing

| Risk | Mitigation |
|---|---|
| **Reward-hacking the eval** (candidate games visible checks) | Held-out spec evals (loki) hidden from the evolver; held-out non-brain verifies (existing `eval_harness`); facts-only Evidence Receipt; independent adversary still in the loop. |
| **Library rot / self-imposed constraints** | Hermes do-not-capture rules (no env-dependent failures, no negative tool claims); `reflection.trust` gate; insight decay by support+recency; curator age-out. |
| **Prompt injection via retrieved insight** | loki injection sanitizer on every insight before it enters a prompt (closes a current 9to5 hole). |
| **Drift / Goodhart (fitness rises, real quality doesn't)** | bernstein change-point guard on the fitness series; eval-suite rotation + meta-test split (existing SIE subsystem R); auto-freeze on sustained decline. |
| **Compounding errors (a bad champion seeds worse candidates)** | Staged shadow→canary→champion; auto-rollback on regression (I4); provenance lets a bad insight be traced and quarantined. |
| **Self-mod safety (escaping the protected fence)** | I7/I8 fences reuse the *same* `selfmod`/`hooks_selfmod`/`CORE_PROTECTED_FILES` guards the executor already trusts; candidates inert until promoted; core-loop edits still only via the existing `selfmod.py` suite gate. |
| **Cost / runaway forked reviewers** | Throttled like every heavy pass (`sie` budget governor defers deepest tier first); evolver reuses the Claude subprocess already paid for; `EVOLUTION_ENABLED`/`EVOLUTION_CONSOLIDATE` default OFF. |

**Sequencing (each phase shippable, OFF by default until proven):**
1. **Insight tier** (`insight.py` + schema + `_sieAuthoringContext` injection). Pure read/consolidate — zero behavior change live. Lowest risk, immediate value.
2. **Candidate registry + constitution evolution** via the candidate adapter over `prompts.py` — proves the state machine on the already-validated prompt path.
3. **Validation harness** (`validate.py` + Evidence Receipt + held-out spec evals).
4. **Evolver** (forked reviewer) → **playbook** candidates first (in-process constants, smallest blast radius), then **skill** candidates.
5. **Curator** (deterministic age-out first; umbrella consolidation opt-in last).
6. Flip `EVOLUTION_ENABLED` on in `gated` mode; graduate to `watch` once the fitness series shows promoted candidates consistently winning held-out A-B.

---

## 9. Success criteria (measurable)

- **A challenger skill/playbook/constitution is promoted ONLY after beating the champion on a
  held-out suite** by the `proportion_z` gate — and the held-out 25% it never saw — with a
  facts-only-green Evidence Receipt. (The headline measurable, mirroring the existing prompt
  gate but now for capabilities.)
- A **rising, provable `fitness` time-series** attributable to promoted skills/playbooks
  (visible in `eval_harness.fitness_panel`), not just prompts.
- The brain demonstrably **stops repeating known failure classes**: bernstein taxonomy drift
  trends down for families where an insight→skill candidate was promoted.
- Every promoted capability is **traceable** (I6 provenance) to the runs that produced it, and
  **reversible** in one row-flip; a regression auto-rolls back (I4).
- **Zero protected-file / core-loop violations** ever reach a live write (`verify_invariants`
  clean; I7/I8 enforced) — and one command (`!stock`) returns every skill/playbook/constitution
  to its in-code constant.
- The skill library **stays curated** (bounded count via umbrellas + archive), never deletes,
  and `EVOLUTION_*` defaults keep the whole loop dormant until explicitly enabled.

---

### Appendix — primary sources actually read

**Hermes (MIT, centerpiece):** `references/hermes/agent/background_review.py` (forked
write-only reviewer, do-not-capture rules, class-level preference order, cache-parity
discipline), `references/hermes/agent/curator.py` (inactivity transitions, archive-not-delete,
`absorbed_into`, dry-run, structured YAML report), `references/hermes/agent/learn_prompt.py`
(HARDLINE authoring standards). **generative-agents (Apache-2.0):** `reflect.py` /
`retrieve.py` (importance-triggered reflection, recency·importance·relevance, `filling`/`depth`
provenance). **loki-mode (BUSL — ideas only):** `memory/consolidation.py`,
`memory/rag_injector.py`, `autonomy/lib/proof-generator.py`, held-out spec evals. **bernstein
(Apache-2.0):** `eval/taxonomy.py` (closed-set failure taxonomy + drift), `evolution/`
(change-point/Goodhart guards), self-measuring hint engine. **warp (AGPL — patterns only):**
self-improving skills via cron, `specializes` inheritance + lock-pinning, hybrid
LLM+deterministic-script skills, PR-review evidence gate.

**9to5 (read-only):** `learning/{sie,prompts,promotion,eval_harness,reflection,lessons,toolsmith,safety}.py`,
`learning/README.md`, `memory/experience_schema.py`, `agents/playbook.py`, `selfmod.py`,
`platform_core/orchestration/plan_mixin.py` (`_sieAuthoringContext`, `authorBackfillBatch`,
ORCHESTRATOR_CONSTITUTION via `prompts.get`), and the prior
`docs/superpowers/specs/2026-06-22-self-improvement-engine-design.md`.
