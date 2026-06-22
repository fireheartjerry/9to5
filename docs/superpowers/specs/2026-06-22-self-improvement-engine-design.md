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

### I. Teacher → student distillation (the executor teaches the brain) ★
The biggest single upgrade to the whole system. The executor is **Claude Code** — a
far stronger model than the local Ollama brain — yet today the system keeps only its
*outcome* (verify pass/fail + telemetry) and discards its *reasoning*. The fix: at the
end of each subtask, ask Claude to emit a small, structured **learning summary** (it is
already invoked with `--output-format json` and an appended system prompt, so this is
~free marginal tokens on a call we're already making). This flips the SIE from passively
mining its own statistics to a **strong teacher actively teaching the weak student**.

The learning summary is a capped JSON debrief:
- `approach` — the winning strategy in 1–2 lines;
- `key_decisions[]` / `pitfalls[]` — what mattered, what nearly went wrong;
- `reusable_recipe` — the distilled how-to a future agent should follow;
- `spec_feedback` — **was the orchestrator's invocation spec good?** what was ambiguous
  or missing? (direct signal to improve the brain's *own core skill* — authoring specs);
- `verify_critique` — was the acceptance check meaningful or **gameable**? (anti-reward-hacking);
- `confidence`, `tags`, `would_tell_future_agent[]`.

This single signal supercharges three layers at once:
- **L1/L2 (memory):** Claude-authored lessons are higher-signal than mined stats and
  drop straight into the semantic store, retrievable next run.
- **L3 (prompts):** `spec_feedback` is a closed loop on the brain's hardest job — the
  brain learns to write specs Claude finds *unambiguous*, scored on the harness.
- **L5/F (weights):** Claude's `reusable_recipe` and reasoning become **SFT/DPO
  targets** — the local brain is trained to approximate Claude's judgment, so over
  months an expensive teacher is distilled into a free local student. This is the
  "ultra-advanced" payoff: the orchestrator brain inherits Claude's taste cheaply.

**Cost discipline:** the inline summary is default-on and nearly free. An optional
**deep-reflection second pass** (a richer critique over the full transcript) is *gated*
to notable trajectories only — gold, hard failures, or novel task families — so extra
executor invocations stay bounded.

**Trust but verify (critical):** Claude's self-report can be wrong or self-serving. A
summary is **cross-checked against the actual verify result + adversary verdict** before
it is trusted; a debrief claiming success on a failed verify is discarded and flagged.
Only trusted summaries enter lessons or any training set — this rides the existing
data-quality gate (G) and reward-hacking defenses.

## Further subsystems — the next wave (J–R)

Once A–I are in place, these extend the SIE's reach and depth. Each is distinct,
tied to a real 9to5 seam, and still zero-API. Ordered cheap/high-leverage → research-grade.

### J. Implicit human feedback (RLHF-lite, nearly free) ★
The control layer (Discord/web `ControlBus`, `control.py` + `commands.py`) already emits
the highest-quality signal in the whole system — a *human* judgment — and the SIE
currently ignores it. Every `approve`/`reject`/`skip`/`abort` and every plan **edit** or
subtask **add** is a label: a reject is a negative; an edit is a correction *pair*
(before → human-preferred after); a `!retry` flags a bad attempt. Capture each into the
ledger as preference/correction data feeding L3 (prompts), L4 (policy), and F (DPO).
Cheapest possible source of gold preferences — it reuses infrastructure that already exists.

### K. Introspective confidence + calibrated deferral
Train the brain to predict its **own** success probability for a subtask before running
it (a zero-dep logistic head over the signature + retrieved-neighbor outcomes), and act
on it: low confidence → escalate effort/model or auto-insert a gate / ask the human;
high confidence → take the cheap path. Calibrated uncertainty turns the `gated`/`watch`
modes and the effort ladder into a *learned* decision instead of a static one — fewer
wasted attempts, less cost, fewer silent bad merges.

### L. Blameless post-mortems → a living failure-mode taxonomy
Per-subtask reflection (I) is success-biased; failures need their own loop. On
`aborted`/`blocked`/`partial` or repeated subtask failure, run a structured **root-cause
analysis** (gated; optionally a Claude pass over the transcript) that accretes into a
growing **taxonomy of failure modes** (`failure_modes`). The brain consults it to
pattern-match and pre-empt known traps ("this family historically fails when the verify
is content-scan only"). Run-level and failure-focused, complementary to I.

### M. Multi-role, multi-teacher distillation
Subsystem I distills the executor; but the **Architect and Elaborator are also Claude
Code** — premium reasoning currently kept only as prose. Extend learning-summaries to
every Claude-backed role. And when Phase 2 lands GPT-5.5 (chatgpt.com CDP, already the
planned Adversary brain), treat it as a **second teacher**: ensemble the two teachers'
debriefs and learn especially from where they **disagree** (cross-model distillation),
which localizes the hardest, highest-information cases.

### N. Project knowledge graph (the brain learns *this* codebase)
A new memory tier beyond episodic/semantic: a structured, growing map of the codebase
and domain — files, modules, their invariants and gotchas, which edits historically
broke which verifies — built from reflections, diffs, and failures. Because 9to5
**runs on itself**, the brain should *know this codebase better every month*; when a
subtask touches `orchestrator.py`, inject the accumulated gotchas for that node. Scoped
to the task's `universe.allowed_paths`, so injection stays surgical.

### O. Solution memoization / warm-start
Lessons are *advice*; this reuses *work*. On a near-duplicate subtask signature,
retrieve the prior **solution** (its invocation spec + resulting diff) and warm-start or
short-circuit instead of re-deriving it. A solution cache keyed by signature, gated by
"did it still verify on replay" — a latency and cost win that compounds as the ledger grows.

### P. Self-authored tooling (the agent grows its own toolbox)
Empirically rank which skills/subagents/hooks actually correlate with verify-pass
(`AVAILABLE_SKILLS`/`AVAILABLE_SUBAGENTS` in `config.py`), prune dead weight, and when a
recurring unmet need is detected, **propose and author a new `.claude/` skill/subagent/
hook** — then gate it through the eval harness like any other change. The agent improves
its own *capabilities*, not just its prompts and weights. Highest ceiling, most caution
(new tools touch the executor's powers — strictly behind the harness + human gate).

### Q. Meta-optimization (tuning the learner's own knobs)
Treat the SIE's own hyperparameters as a search space: `MAX_SUBTASK_ATTEMPTS`,
`ADVERSARY_HEARTBEAT_EVERY`, `RETRIEVAL_K`, the fitness weights, the promotion
thresholds. Periodically tune them against the long fitness time-series (coordinate
descent / simple Bayesian search, all local). Learning *how to learn* — guarded by a
slow cadence and the harness so the meta-loop can't destabilize the base loop.

### R. Continual-learning hygiene (adapter souping + eval anti-overfit)
Two long-horizon health mechanisms. **Adapter souping:** periodically merge winning
per-role adapters (model soup / weight averaging) to consolidate gains and bound adapter
sprawl. **Eval hygiene:** rotate and grow the held-out suite from real runs and reserve a
meta-test split, so we can *detect overfitting to the eval suite itself* — the one failure
mode that would make all the green numbers a lie.

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

### The Self-Improvement Orchestrator (the component that runs A→Z)
One small coordinator (`learning/sie.py`) owns the cadence ladder so the rest of the
system stays loosely coupled. It is **not** a new always-on daemon — it reuses the
existing process model:
- **Per-run tiers** (L0 capture, L1 retrieval, I reflection, J feedback) are *inline
  hooks* fired from the existing orchestrator/executor/control paths — no scheduler needed.
- **Nightly / weekly / monthly tiers** are *idempotent jobs* (`python -m learning.sie
  --tier nightly|weekly|monthly`), each driven by 9to5 itself as a normal self-improvement
  **goal** during a 9–5 window (the orchestrator already runs goals; the SIE just supplies
  them) or by an OS scheduler if the host has one. Either way the entry point is the same.
- **Concurrency & crash-safety:** each tier takes a file lock under `state/control/`
  (reusing the `ControlBus` O_EXCL pattern) so two passes never overlap; every job is a
  resumable transaction over the ledger (a half-finished consolidation or promotion can
  re-run with no double-counting — writes are keyed and upsert).
- **Budget governor:** the orchestrator enforces a per-day compute/time ceiling across
  all tiers (so a LoRA cycle can't starve real work); when over budget it defers the
  deepest tier first (months → weeks → days), never the cheap inline tiers.
- **One status surface:** every tier reports into the same Discord/web dashboard and
  Obsidian as a normal run, so the glass-box covers learning, not just task execution.

This is the piece that makes "improve from A to Z, continuously" a single, observable,
restartable loop rather than a pile of scripts.

## Governance / safety / alignment

- **Champion/challenger + auto-rollback** for every prompt and adapter; all versioned in git.
- **Reward-hacking defense (multi-layer):** independent adversary + held-out
  (non-brain-authored) verifies + the data-quality gate (G) + periodic human spot-check.
  Catches the brain authoring trivially-passing verifies or gaming the composite reward.
- **Untrusted self-reports:** executor learning summaries (subsystem I) are
  cross-checked against the real verify + adversary verdict before they are trusted;
  unverified or contradicted debriefs never enter lessons or any training set.
- **Catastrophic-forgetting defense:** frozen base + replay set in the eval suite +
  KL/anchor regularization in DPO + never-promote-on-regression.
- **Drift detection:** watch the fitness time-series for sustained decline across any
  tier; auto-freeze training and alert past a threshold.
- **Kill switch:** one env flag / Discord command reverts the brain to the base model
  and disables all promotions — always one command from "stock."
- The existing `self_modification_guard` hook + `CORE_PROTECTED_FILES` (`config.py`)
  protect core files mid-run; in `gated` mode promotions require human `!approve`.
- Every promotion/rollback/training run logged to Obsidian + a Discord embed, model card linked.

## Alignment & safety — deep dive

A system that rewrites its own prompts, policies, tools, and weights is exactly the kind
that fails silently and confidently. This section is the spec's spine for *not* doing that.

### Threat model (what actually goes wrong)
1. **Verify gaming** — the brain authors trivially-passing verifies so anything "passes."
2. **Reward gaming** — trajectories optimize the composite reward (cheap/fast/quiet)
   rather than real quality.
3. **Data poisoning via self-reports** — executor/teacher reflections (I/M) overstate
   success and corrupt lessons/training.
4. **Eval overfitting** — the system learns the static eval suite, so fitness rises while
   real performance doesn't (the "all green numbers are a lie" failure).
5. **Catastrophic forgetting** — a LoRA cycle improves new families but regresses old ones.
6. **Scope creep / boundary violation** — self-improvement edits sprawl beyond the
   task's `universe` or touch `hard_boundaries`.
7. **Runaway training / cost** — deep tiers consume the day; adapters churn faster than
   they can be validated.
8. **Tool risk (P)** — self-authored skills/hooks expand the executor's powers unsafely.

### Defense-in-depth (each threat → concrete guard already in the design)
| Threat | Primary guard | Backstop |
|---|---|---|
| Verify gaming | Held-out, non-brain-authored verifies in the eval suite | Independent adversary + human spot-check |
| Reward gaming | Reward calibrator anchored to eventual success | Eval harness uses outcomes the reward can't see |
| Poisoned self-reports | Trust cross-check vs real verify + adversary (I) | Data-quality gate G; only `trusted=1` trains |
| Eval overfitting | Suite rotation + meta-test split (R) | Drift detection on a *fresh* held-out slice |
| Forgetting | Frozen base + replay set + KL anchor | Never-promote-on-regression gate |
| Scope creep | `self_modification_guard` + `universe` boundaries | Surgical-diff review + Obsidian audit |
| Runaway cost | Budget governor (defers deepest tier first) | Kill switch |
| Tool risk (P) | `TOOLSMITH` default-off + human gate | Harness gate + new tools sandboxed first |

### Invariants that must ALWAYS hold (testable assertions, enforced in code)
- **I1 — Base immutability:** `qwen2.5-coder:7b` weights are never modified; only LoRA
  adapters and external state change. (One command returns to stock.)
- **I2 — No self-promotion:** the brain can *propose* a prompt/policy/adapter but can
  **never** mark its own challenger `champion`; only a passing harness gate (and, in
  `gated` mode, a human) can.
- **I3 — Independent grading:** nothing the brain authored may be the sole judge of its
  own success — the gate always includes a held-out, brain-blind signal.
- **I4 — Monotone-or-rollback:** a promotion that later regresses the fitness series
  auto-rolls back to the prior champion.
- **I5 — Boundary inviolability:** SIE writes never touch `hard_boundaries` (secrets,
  VCS internals, venvs, task state) regardless of goal.
- **I6 — Provenance:** every lesson, training example, prompt, and adapter is traceable
  to the runs that produced it (no orphan signal can enter training).

### Human-in-the-loop checkpoints
In `gated` mode, three boundaries require explicit `!approve`: promoting a prompt-set,
promoting an adapter, and shipping a self-authored tool (P). In `watch` mode the first
two auto-gate on the harness but a tool ship (P) **always** asks. The kill switch
(`SIE_KILL_SWITCH`) and a Discord `!stock` command are the manual overrides.

### Kill switch & rollback (formal)
`SIE_KILL_SWITCH=1` (env or `!stock`) atomically: (a) repoints `BRAIN_MODEL_TAG` to the
frozen base, (b) freezes all promotions and training jobs, (c) leaves capture (L0) and
the audit trail running so the freeze itself is observable. Rollback of any single
champion (prompt/policy/adapter) is a one-row state flip back to the prior champion —
because every champion is versioned and the base never moved, rollback is O(1) and total.

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
prompts/policies that beat the original hardcoded constants on the gate (L3/L4);
measurable uplift from teacher distillation — the brain authors specs Claude rates as
less ambiguous over time, and a reflection-trained adapter beats a trajectory-only one
(subsystem I + L5); and at least one LoRA adapter that beats prompt-only on the harness
— all at zero marginal API cost, with one-command rollback intact throughout.
