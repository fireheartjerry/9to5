# Self-Improvement Engine (SIE) — The Brain That Gets Better Over Months — Design

> **Status:** approved design (brainstorming output). Next: implementation plan
> (`docs/superpowers/plans/2026-06-22-self-improvement-engine.md`).
> Greenfield subsystem — no existing learning/training/eval/RAG infrastructure in the
> repo. New top-level packages `memory/` (extends) and `learning/` (new). Zero new
> *required* deps for Phases A–D; Phase E+ adds optional, locally-installed training deps.

## Objective

Make 9to5's brain — today a **stateless** local Ollama model
(`qwen2.5-coder:7b`) — **measurably better over time on every horizon at once**:
hours, days, weeks, and months. "Better" must reach all the way down to the model's
weights (local LoRA), not stop at better prompting. The entire loop stays **strictly
zero marginal API cost**: the brain stays local, training data comes only from
trajectories Claude Code already produces, and all grading/embedding/training runs
locally.

This is the missing half of the system. 9to5 already has world-class *observability*
(rich Obsidian + task-state logging); it has **zero cross-run learning**. Every run
starts from scratch. The SIE closes that loop.

## The problem, concretely (what exploration found)

- The Ollama brain never reads past task outcomes. Every `_ollamaChat()`
  (`orchestrator.py:308`) injects only static system prompts + the current goal +
  the live Claude-Code capabilities block. There is no history parameter.
- Every brain system prompt is a **hardcoded module constant**
  (`ORCHESTRATOR_CONSTITUTION` `orchestrator.py:198`, `REPLANNER_SYSTEM`
  `replanner.py:21`, `ELABORATOR_SYSTEM` `elaborator.py:18`, adversary `_SYSTEM`
  `adversary.py:35`). They cannot change without a code edit and carry no outcome metrics.
- `TaskState` + Obsidian are effectively **write-only**: `readNote()` is called in
  exactly one place (`orchestrator.py:1229`, to recover the architect doc on resume).
  Adversary concerns, replan deltas, and verify history are written and never read back.
- `context_handoffs` (`state/task.py:64`) and `addHandoff()` exist but are **dead
  code** — a placeholder for exactly this feature.
- A repo-wide grep for `train|finetune|lora|dataset|embedding|rag|vector` returns
  **zero** substantive infrastructure.

The asymmetry the SIE exploits: **Python has the disk and the history; the brain does
not.** The existing `injectCapabilities()` (`knowledge.py:644`) already proves the
pattern — it augments every brain call with live, compressed context. The SIE adds a
second, learned context source (the system's own experience) and, eventually, updates
the weights themselves.

## Non-goals (YAGNI / scope discipline)

- **No cloud training, no API-based grading, no synthetic-data-from-a-frontier-model.**
  Hard zero-API constraint. (Claude Code CLI is already the "hands"; its outputs are
  free, in-budget training signal.)
- **No RL-from-scratch, no online weight updates mid-run.** Weights change only in
  gated, offline, queued LoRA cycles.
- **No replacing the base model.** Base `qwen2.5-coder:7b` stays frozen forever; only
  LoRA adapters and prompt/policy state evolve. This guarantees instant rollback.
- **No heavyweight vector DB.** Embeddings live in the same SQLite ledger
  (stay file-backed — matches project philosophy).

## The core idea — five concentric layers + an eval spine

The system already emits a firehose of high-signal data (plans, invocation specs,
verify pass/fail, adversary verdicts, telemetry) and throws it away each run. The SIE
captures it **once** and lets five layers learn from it, ordered cheapest/fastest →
slowest/deepest. A single **Evaluation Harness** gates every change so improvement is
*provable*, not faith-based.

```
                 ┌────────────  EVAL HARNESS (gates every promotion)  ────────────┐
  Layer 0  Experience Ledger ........ capture every run as structured, queryable data
  Layer 1  Retrieval (RAG-on-self) .. inject similar past lessons into the brain's prompt
  Layer 2  Consolidation ............ "sleep-time" mining → durable lessons + heuristics
  Layer 3  Prompt Evolution ......... versioned prompts, champion/challenger, bandit promote
  Layer 4  Policy Learning .......... learned effort/skill/model routing (contextual bandit)
  Layer 5  Local LoRA Distillation .. fine-tune the brain on its own gold trajectories
```

### Multi-timescale by design (hours / days / weeks / months)

The layers are deliberately ordered by feedback latency, so each owns a horizon. Fast
layers deliver immediate wins **and** generate the clean signal the slow layers later
distill into weights. The slow layers ride on the fast layers' exhaust — no layer waits
on another to start paying off.

| Horizon | Layers | What improves, and how fast |
|---|---|---|
| **Same run → hours** | L0 capture + L1 retrieval | Later subtasks benefit from earlier ones; an injected lesson changes the *next* spec immediately. |
| **Days** | L1 retrieval + L2 nightly consolidation | "Stops repeating yesterday's mistakes." Each morning the brain wakes with fresh distilled lessons + effort priors. |
| **Weeks** | L3 prompt evolution + L4 policy learning | Champion prompts and routing policies accumulate enough samples to beat incumbents on the harness; prompts and effort/model choices visibly sharpen. |
| **Months** | L5 local LoRA distillation | Enough gold trajectories accumulate to fine-tune the brain's weights; the model itself gets better, not just its context. |

## The layers

### Layer 0 — Experience Ledger (the substrate)
Turn today's write-only logging into structured, mineable data. New module
`memory/experience.py`, backed by **SQLite** (stdlib `sqlite3`, WAL mode for the
multi-process ControlBus world — zero new deps) at `state/experience.db`, mirrored to
Obsidian for the glass-box. Captured at the *existing* sink call sites
(`TaskState.recordVerify` `state/task.py:223`, `addAdversaryReview` `:284`, the replan
log) — **no new control flow**, just a parallel structured sink. Backfilled from
`state/tasks/*.json` via `TaskState.iterStored()` so it never starts cold. This layer
changes no behavior; it is safe to ship first and finally gives `context_handoffs` a
real consumer.

### Layer 1 — Retrieval-Augmented Brain (fastest visible win)
At plan/spec authoring time, retrieve the K most-similar **successful** past subtasks
and inject a ruthlessly-compressed lessons block into the Ollama prompt via the
`injectCapabilities()` seam (`orchestrator.py:441` / `:581`). Embeddings come from a
**local** Ollama model (`nomic-embed-text`), vectors live in the ledger. The brain
stops repeating mistakes within *days*. Example injected lesson: *"Similar past
subtask used effort=high and passed; default-effort attempts failed verify twice.
Prefer high."*

### Layer 2 — Consolidation ("sleep-time" learning)
A nightly pass mines the ledger into compact, durable artifacts: effort priors per
subtask family, skill/subagent → verify-pass correlations, common failure→fix patterns,
and prompt anti-patterns that triggered clarifications/adversary challenges. Writes
structured `lessons` rows + a human-readable `lessons.md` digest, injected alongside L1.

### Layer 3 — Prompt Evolution (measurable, reversible)
Move the hardcoded system prompts into a **versioned registry** (`prompts/*.md` +
metadata). Each variant accrues outcome stats from the ledger. A meta-loop proposes a
challenger; the eval harness + a field-metrics statistical test decide promotion;
champions are git-committed → fully reproducible and reversible.

### Layer 4 — Policy Learning (effort/skill/model routing)
A pure-Python **contextual bandit** over the ledger recommends effort level
(`EFFORT_LEVELS`), skills, subagents, and model (opus vs sonnet) per subtask family.
Reward favors first-attempt verify-pass, penalized by attempts/cost/time. Output is a
*prior* the brain may override.

### Layer 5 — Local LoRA Distillation (the literal "model gets better")
Distill Claude Code's *successful* behavior into the brain. Build a gold-only SFT/DPO
dataset from the ledger, fine-tune a **local** LoRA over frozen `qwen2.5-coder:7b`,
build the new Ollama model via a Modelfile `ADAPTER`, and gate it through the same eval
harness as prompts. Base never changes → rollback is repointing a tag.

## Advanced subsystems (what makes it a *full* system, not a RAG bolt-on)

### A. Cognitive memory hierarchy
Four tiers, each with a distinct write/read/forget policy and independent rollback:
**Episodic** (ledger, append-only) → **Semantic** (`lessons`, decays by support +
recency) → **Procedural** (`policy_arms`, updated by reward) → **Parametric** (LoRA
adapters, gated training only). Information flows upward as evidence accumulates and
confidence rises.

### B. Reward model + preference optimization (DPO, beyond plain SFT)
Binary verify-pass is weak. Build a **composite reward** from signals 9to5 already
emits (`verify_passed`, `attempt_count`, `adversary_verdict`, `clarify_count`, `cost`,
`wallclock`, `replan_churn`). Two consumers: (1) **preference pairs** — for one subtask,
a gold trajectory (chosen) vs a failed earlier attempt (rejected) is a *free,
naturally-occurring* DPO/ORPO pair, teaching the brain what *not* to do — the single
biggest quality jump over plain imitation; (2) **reward-weighted SFT**. A locally-fit
logistic **reward calibrator** keeps the weighting honest; human spot-checks anchor it.

### C. Self-generated curriculum (self-play over months)
Mine failure clusters and **author new training/eval goals** in the weakest families
(active learning on highest-loss regions). Synthetic goals run in idle 9–5 cycles,
generating fresh gold + hard negatives exactly where the brain needs them.

### D. Counterfactual offline replay
Because verifies are deterministic and zero-API, a challenger prompt/adapter is
**re-run against logged past subtasks** offline to estimate uplift *before* any live
exposure — a cheap prior and a regression catcher.

### E. Shadow → canary → champion rollout
No challenger flips straight to champion. **Shadow** (authors in parallel, output
unused, scored counterfactually) → **canary** (small fraction of real subtasks behind
the bandit) → **champion** (only after harness + canary clear the gate). Auto-rollback
at any stage; the prior champion tag is always live.

### F. Per-role adapters + router (lightweight MoE)
Train **separate small LoRA adapters per brain role** (elaborate / plan / author-spec /
replan / adversary) and a trivial router that selects by call site, so each role
improves on its own cadence and no monolithic adapter drags down unrelated roles.

### G. Data-quality & safety pipeline (mandatory before any training)
Between ledger and any training set: **dedup** by body hash, **decontaminate** (never
train on the eval suite — held out by construction), **secret/PII scrub** (reuse
`.env`/hard-boundary patterns), **schema-validate** specs, and **drop per-family
near-duplicates** to prevent collapse. Non-negotiable: bad data is the fastest way to
make a self-improving system worse.

### H. Brain releases, model cards & attribution
Every champion prompt-set and adapter is a **versioned release** (`9to5-brain:vN`) with
an auto-generated **model card** (training-data summary, eval deltas, known
regressions) committed to git, plus a **per-layer attribution report** estimating how
much of the month's fitness gain came from L1 vs L3 vs L5.

## The spine — Evaluation Harness (most important single piece)

A fixed benchmark of ~15 golden 9to5 goals across families (bugfix, add-test, refactor,
doc, discord-feature), each with a known-good verify the brain did **not** author. Run
sandboxed (git worktree), scored automatically into a single **fitness** number:

```
fitness = 0.5·first_pass_rate + 0.2·(1 − norm_attempts) + 0.15·(1 − norm_cost)
        + 0.1·plan_stability + 0.05·(1 − challenge_rate)
```

**Every** prompt variant and **every** adapter must beat the incumbent here before
promotion. A persisted **fitness time-series** on the Discord/web dashboards makes
months-long improvement visible. Without this spine, self-improvement is unfalsifiable
and can regress silently.

## The meta-loop — a cadence ladder (autonomous across all horizons)

- **Per-run (hours):** L0 capture + L1 retrieval, inline — no schedule.
- **Nightly (days):** L2 consolidation → refreshed lessons/priors + a daily fitness point.
- **Weekly (weeks):** promotion pass — evaluate prompt (L3) and policy (L4) challengers,
  promote winners, roll back regressions.
- **Monthly / on-threshold (months):** L5 LoRA cycle when ≥N new gold trajectories exist.

9to5 schedules these itself during 9–5; `SELF_IMPROVEMENT_PHILOSOPHY` (`config.py:217`)
already frames the intent — the ladder gives it a concrete, measurable agenda.

## Governance / safety / alignment

- **Champion/challenger + auto-rollback** for every prompt and adapter; all versioned in git.
- **Reward-hacking defense (multi-layer):** independent adversary + held-out
  (non-brain-authored) verifies + the data-quality gate (G) + periodic human spot-check.
  Catches the brain authoring trivially-passing verifies or gaming the composite reward.
- **Catastrophic-forgetting defense:** frozen base + replay set in the eval suite +
  KL/anchor regularization in DPO + never-promote-on-regression.
- **Drift detection:** watch the fitness time-series for sustained decline across any
  tier; auto-freeze training and alert past a threshold.
- **Kill switch:** one env flag / Discord command reverts the brain to the base model
  and disables all promotions — always one command from "stock."
- The existing `self_modification_guard` hook + `CORE_PROTECTED_FILES` (`config.py`)
  protect core files mid-run; in `gated` mode promotions require human `!approve`.
- Every promotion/rollback/training run logged to Obsidian + a Discord embed, model card linked.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Reward / verify gaming | Held-out non-brain verifies in the eval suite; independent adversary; human spot-check; gate G |
| Catastrophic forgetting (LoRA) | Frozen base; replay set in eval; KL anchor; never promote on regression |
| SQLite concurrency (multi-process ControlBus) | WAL mode; short write txns; ledger writes are best-effort, never block the run |
| 8192-ctx budget pressure | Aggressive compression of injected lessons (reuse CLAUDE_CAPABILITIES routine); strict token cap |
| Local GPU availability for training | Finetune is an optional, queued job; system degrades gracefully to L0–L4 |
| Bad/duplicated training data | Mandatory data-quality gate (G) before any training |

## Success criteria

A rising, **provable** fitness time-series on the eval harness over weeks→months; the
brain demonstrably stops repeating known failure patterns (L1/L2); champion
prompts/policies that beat the original hardcoded constants on the gate (L3/L4); and at
least one LoRA adapter that beats prompt-only on the harness (L5) — all at zero
marginal API cost, with one-command rollback intact throughout.
