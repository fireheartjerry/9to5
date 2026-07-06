# Elaborator Excellence — Design Spec

**Date:** 2026-07-05
**Status:** Approved design, pending implementation plan
**Scope:** Elevate `agents/planning/elaborator.py` from SOLID to a self-improving,
multi-candidate goal-elaboration subsystem.
**Gating:** Everything below sits behind a new master flag `ELABORATOR_EXCELLENCE_ENABLED`
(default **OFF**). Flag-off behavior is **byte-identical** to today's elaborator.

---

## 1. Motivation

The elaborator is the first brain touch of every run: it expands a human's raw goal
(`ElaboratedGoal` in the run lifecycle, `docs/ARCHITECTURE.md:76`) into the spec a coding
agent executes. A prior audit rated it **SOLID** — clean facade, graceful degradation,
real repo-grounding (the AGENTS.md + git-history injection from commit `324f9f04`, BUG-018).
Two gaps and one ceiling motivate this work:

- **Gap A (regression):** the `TestRepoGrounding` regression tests added with `324f9f04`
  are missing from the current `tests/orchestration/test_elaborator.py`. The single most
  important behavior (not hallucinating fake paths) is no longer defended by CI.
- **Gap B (validation):** `elaborate()` returns a raw markdown string with no schema
  enforcement; `extractUniverse()` coerces defaults but never checks that `allowed_paths`
  reference real files. Malformed or hallucinated output flows downstream unflagged.
- **Ceiling:** the elaborator is static. It guesses what a vague goal ("improve everything",
  "fix bugs") means, but it never gets *better* at guessing — a failed run's lessons don't
  flow back into how the next goal is elaborated.

The goal: an elaborator that (1) turns even a two-word goal into a grounded, structured
spec naming real files; (2) validates its own output against a schema and the real
filesystem; (3) resolves genuine ambiguity by inference — never by blocking on a human —
while recording every guess auditable; and (4) **compounds** — learns which elaboration
stances succeed for which goal-families, using machinery 9to5 already has.

### Research grounding

The design is grounded in current (2026) practice on the two behaviors that matter most —
**prompt elaboration** and **inferring intent instead of asking**:

- **5W3H structured prompting for intent alignment** — arxiv 2603.18976. Expanding a terse
  instruction across Why/Who/When/Where/How dimensions measurably beats a flat "make it
  detailed" prompt. → Section 2 prompt structure.
- **Adaptive mediator / upstream intent correction** — arxiv 2602.07338 ("Intent Mismatch
  Causes LLMs to Get Lost in Multi-Turn Conversation"). Instead of the downstream agent
  asking clarifying questions, an upstream mediator silently refines ambiguous input into a
  complete, unambiguous instruction. **This is the elaborator's exact job.** → Sections 2–3.
- **Verbalizing assumptions to control sycophancy** — arxiv 2604.03058. When a model must
  guess, making it *state the assumption and the reason* keeps the guess auditable rather
  than silent. → Section 2 self-review.
- **Measuring intent comprehension** — arxiv 2506.16584. Success = "output matches what they
  *wanted*," not "what they *typed*." → the yardstick for the self-review pass.
- **Writing a good spec for AI agents** — Addy Osmani. Short brief in, full `spec.md` out,
  used as a persistent reference. Matches `elaborate()`'s existing shape.
- **Layered output validation** ([AI Security in Practice], [FutureAGI]): deterministic
  Layer-1 schema check first, probabilistic Layer-2 semantic judge second; track
  `schema_validity_rate × semantic_quality`, not raw parse rate. → Section 4.
- **Generate-then-verify / RAG grounding** ([CodeAnt], agentic-architecture-playbook):
  post-check generated output against the real repo, flag references absent from retrieved
  context. Retrieval alone does not guarantee the model *used* it. → Section 5.
- **Reflexion survey** (arxiv 2401.01313): uncalibrated *repeated* self-critique reinforces
  errors rather than fixing them. → self-review is capped at exactly **one** pass.

### Frontier grounding (Part II — §3d, §3b correction, §7 A′/B′, §7.5)

A second research pass surfaced four techniques beyond the mainstream 2026 patterns above,
and one **correction** to §3b:

- **Calibration correction** ([Zylos: LLM calibration in production], arxiv 2604.07036
  "ReDAct"): RLHF *systematically degrades* calibration, and verbalized confidence
  (high/medium/low self-report) is **unreliable** for deciding when to escalate. → §3b's
  confidence signal is replaced with a calibrated one: **I-CALM reward-framed abstention**
  (arxiv 2604.07036 — "+2 grounded / −2 wrong / 0 if flagged") plus a conformal risk band,
  not free-form self-rating.
- **Case-based reasoning for LLM agents** (arxiv 2504.06943): retrieve-reuse-revise-retain
  over precedent exemplars beats abstract lessons for reducing hallucination on structured
  tasks. → new §3d, using the existing `memory/retrievals/core.py` embedding index.
- **Compute-optimal test-time scaling** (arxiv 2506.12928, "Scaling Test-time Compute for
  LLM Agents"): best-of-N gains are power-law in *prompt difficulty*; allocate samples
  adaptively rather than a fixed N. → §7 Stage A′.
- **World models / propose-simulate-score** (arxiv 2606.30639 "Self-Evolving World Models
  for LLM Agent Planning"): imagine each candidate's immediate consequence before
  committing; limit look-ahead to 1–3 steps and re-sync to real state to bound drift. → §7
  Stage B′.
- **Uncertainty-aware deferral** (arxiv 2604.07036 "ReDAct"): a small model abstains and
  defers to a larger one when unsure — cost-aware cascading. → §7.5, mapped onto 9to5's
  existing Ollama-orchestrator → Claude-executor split.

---

## 2. Module layout

The current 162-line `agents/planning/elaborator.py` grows past the 300-line ideal once it
carries 5+ capabilities. Split it into a package, following the repo's own "large module →
sub-modules + re-export facade" convention (per `.claude/rules/modularity.md`, mirrors
`memory/experience_*.py`, `memory/ledger/`):

```
agents/planning/elaborator/
  __init__.py       # re-export facade: elaborate(), extractUniverse() (public API unchanged)
  core.py           # orchestration: grounding → generate → schema → self_review → path_verify
  grounding.py      # _repoContext() (moved verbatim) + vague-goal state-of-repo bundle
  schema.py         # pydantic models ElaboratedSpec / Universe; Layer-1 validation + coercion
  self_review.py    # ONE calibrated verbalized-assumption pass (ambiguity → inferred assumptions)
  path_verify.py    # deterministic generate-then-verify: allowed_paths vs real repo tree
  precedent.py      # (§3d) case-based-reasoning grounding via memory/retrievals/core.py
  candidates.py     # (excellence tier) adaptive best-of-N generate + portfolio select + debate
  predict.py        # (§7 B′) world-model lookahead: propose-simulate-score predicted run outcome
  uncertainty.py    # (§3b/§7.5) calibrated risk band + Ollama→Claude deferral decision
```

- `agents/elaborator.py` (top-level facade) and the current
  `agents/planning/elaborator.py` re-export path both keep working unchanged — the outer
  facades point one level deeper. Callers using `from agents.elaborator import elaborate`
  or `from agents.planning.elaborator import elaborate` are unaffected.
- Each new file stays well under the 300-line ideal / 25-line-function target.
- **Public API is frozen:** `elaborate(goal_raw, work_dir=None, chat=None) -> str` and
  `extractUniverse(goal_raw, goal_elaborated, work_dir, chat=None) -> dict` keep their exact
  signatures and return types. The excellence tier is additive and flag-gated inside `core.py`.

---

## 3. The elaboration prompt (5W3H) + calibrated self-review

### 3a. Restructured prompt

Today's `ELABORATOR_SYSTEM` asks flatly for Objective / Deliverables / Acceptance Criteria /
Constraints / Assumptions. The new prompt walks the model through the intent dimensions
*before* it writes the final sections (per arxiv 2603.18976):

- **Why** — the motivation / problem being solved (inferred from the goal + grounding).
- **Who** — which code areas and owners this touches (from grounding).
- **Where** — repo areas / real modules (from grounding; see 3c for vague goals).
- **How** — the intended approach.
- **What** — deliverables, with **real** file paths.

The existing `CRITICAL GROUNDING RULE` (no placeholder paths) is preserved verbatim. The
output sections stay the same five so downstream parsers are unaffected; the 5W3H walk is
scaffolding that produces richer, more grounded final sections.

### 3b. Verbalized-assumption self-review (the "predict what they wanted" mechanism)

One additional Ollama call, narrowly scoped: *"Find every point where you guessed rather
than grounded. For each, emit `Inferred: {guess} — because {reason}`."* This directly
implements the design decision that the elaborator **predicts what the human wanted** rather
than blocking to ask (the adaptive-mediator pattern, arxiv 2602.07338): ambiguity is
resolved *and logged*, never bounced back to a person. The `— because {reason}` is what
makes each inference auditable (arxiv 2604.03058); a human skimming the spec's Assumptions
section can still catch a bad guess.

**Capped at exactly one pass — no loop.** Per the reflexion survey (arxiv 2401.01313),
uncalibrated repeated self-critique reinforces early hallucinations rather than correcting
them.

**Confidence is calibrated, not self-reported (correction from the frontier pass).** The
naive `[confidence: high|medium|low]` self-tag is deliberately **not** used: RLHF degrades
calibration and verbalized confidence is unreliable for escalation decisions (Zylos; ReDAct,
arxiv 2604.07036). Instead, `uncertainty.py` derives a per-assumption **risk band** from
signals that don't depend on the model's self-report:

- The **I-CALM reward frame** (arxiv 2604.07036): the self-review prompt is framed with an
  explicit payoff — "+2 for a grounded claim, −2 for a wrong one, 0 for one you flag as
  unsure" — which shifts the model toward rational epistemic humility (flagging) without any
  model modification.
- A **conformal risk band**: bucket each inferred assumption by objective proxies —
  did §5 path-verify confirm its referenced paths? does §3d precedent retrieval corroborate
  it? — into `low` / `elevated` risk, a distribution-free signal rather than a felt one.

This calibrated band (not a self-rating) feeds Section 4 (Layer-2 fires only when an
`elevated`-risk assumption exists), Section 7 Stage C (debate the contested axis), and §7.5
(defer to the larger model when too many assumptions land `elevated`).

### 3d. Case-based-reasoning grounding (precedent exemplars)

`precedent.py` upgrades grounding from abstract lessons to full **case-based reasoning**
(retrieve-reuse-revise-retain, arxiv 2504.06943), reusing the embedding index that already
exists — **zero new infra**:

- `retrieve(goal, title="", *, k=...)` (`memory/retrievals/core.py:254`) → top-k *similar
  past goals* whose runs **passed** (`top_k_similar(..., only_passed=True)`,
  `core.py:231`). Their `(goal → elaborated spec → outcome)` become **precedent exemplars**
  injected as few-shot context: "here's how a similar goal was successfully specced before."
- `retrieve_failures(goal, title, *, k=...)` (`core.py:263`) → similar past goals that
  **failed**, injected as anti-patterns ("a similar goal failed when specced this way").
- `lessons_block(goal, title, *, db_path=...)` (`core.py:419`) → the already-formatted
  lessons text, folded into the §3c vague-goal bundle.

Precedent retrieval is the strongest form of the "predict what they wanted" mechanism: the
best evidence for what *this* user means by a terse goal is how *their own* similar past
goals resolved. Retrieval is embedding-cheap and gated: if the index is empty (cold start)
or returns nothing above threshold, `precedent.py` returns "" and grounding degrades to
§3c. The **retain** half of the CBR cycle is Section 7 Stage D — a completed run's
`(goal → spec → outcome)` is already embedded into the index by the existing
`embed_and_store()` (`core.py:163`), so precedent compounds automatically.

### 3c. Vague-goal grounding bundle

The failure case for any elaborator is a short goal with a generic verb and no anchor
("improve everything", "fix bugs", "clean up", "optimize"). `grounding.py` detects this
(short + generic verb + no named path/module/feature) and, instead of only AGENTS.md + git
log, assembles a **state-of-repo signal bundle** from artifacts 9to5 *already generates*:

- `tools/size_audit.py` output → concrete `must_split` violations ("these 3 files are over budget").
- Recent git churn (existing) → which files are hot/risky right now.
- `learning/feedback/postmortem.py::guidance_for(title, db_path=...)` and consolidated
  lessons → known past incidents, so "fix bugs" doesn't re-discover a documented bug.
- `.repo-map.json` module list (richer structured form than AGENTS.md's prose digest) →
  real module names to put in Deliverables instead of placeholders.

This bundle feeds the 5W3H prompt: "improve everything" → **Where** gets populated with real
candidates (the must_split files, the hottest-churn module), **Why** with the matching
lesson/postmortem if one exists, and the spec names actual files. Stays inside the existing
7000-char prompt budget (the bundle is counts + top-N names, **not** raw dumps) and adds
**zero** new LLM calls — pure file/JSON reads.

---

## 4. Structured output validation (two-layer)

New `schema.py`, pydantic models:

- `ElaboratedSpec`: `objective`, `why`, `who`, `where`, `how`, `deliverables: list[str]`,
  `acceptance_criteria: list[str]`, `constraints: list[str]`, `assumptions: list[str]`
  (including the `Inferred:` lines from §3b with their confidence tags).
- `Universe`: `description`, `allowed_paths`, `allowed_to_expand_to`, `hard_boundaries`.

**Layer 1 — deterministic, always runs, no LLM cost.** Required fields present, non-empty,
correctly typed; `hard_boundaries` always includes the existing baseline
(`config.UNIVERSE_DEFAULT_HARD_BOUNDARIES` — `.git`, `.env`, venv, task state; current
lines 180–182 preserved). Catches the large majority of malformed output cheaply.

**Layer 2 — two triggers, both conditional (not every run).**
- *Schema-repair (on Layer-1 failure):* one retry of the chat call with the validation error
  folded into the prompt ("your last output was missing X; fix it"). If the retry *also*
  fails validation → fall back to `_fallbackSpec()` (never raises — the current contract is
  preserved exactly).
- *Semantic judge (on `elevated`-risk):* when §3b's calibrated band flags an
  `elevated`-risk assumption, run one probabilistic quality pass — reusing the existing
  adversary review dispatch, `review(...)` / `systemFor(review_type=...)`
  (`agents/review/adversary_review.py:259` / `:97`) with a new `review_type="elaboration"`
  case, rather than a parallel judge module. Its verdict is advisory: it can demote a
  candidate in Stage B, never hard-block. Gated by `SOCIETY_ENABLED` (same adversary
  subsystem); off → skip, rely on Layer-1 + path-verify only.

**Observability (log, do not enforce):** record whether each elaboration passed Layer-1
first try, needed a retry, or hit fallback — a cheap `schema_validity_rate` signal for
noticing a prompt regression silently degrading quality later.

---

## 5. Path verification (generate-then-verify)

New `path_verify.py`, run after `extractUniverse()` returns. For each `allowed_paths` entry,
check existence against the real repo tree (`work_dir`-relative `Path.exists()` / glob):

- Paths that exist → unchanged.
- Paths that don't exist → moved to a **new `unverified_paths` field** rather than silently
  kept or silently dropped. A path can legitimately not exist yet (a new file the goal will
  create), so this is an **honesty flag** for downstream (architect / executor / adversary)
  to weigh, not a hard reject.

Mirrors the "post-process the output against retrieved context, flag unfounded references"
pattern (CodeAnt / agentic-architecture-playbook), applied to paths instead of code diffs.
**Zero** new LLM calls — pure filesystem check.

---

## 6. Testing

- **Restore `TestRepoGrounding`** (Gap A) to `tests/orchestration/test_elaborator.py`:
  `test_elaborate_grounds_prompt_in_real_repo`, `test_extract_universe_grounds_prompt_in_real_repo`.
- Per-module tests, all using the existing `_chat()` seam injection (no real Ollama /
  subprocess calls, consistent with current test style):
  - `schema.py`: valid input passes Layer-1; a missing field triggers retry-then-fallback.
  - `path_verify.py`: a real path passes; a fake path lands in `unverified_paths`.
  - `self_review.py`: seam-injected mock chat verifies **exactly one** pass, no loop; an
    inferred assumption gets an `elevated` risk band when path-verify fails to corroborate it.
  - `grounding.py` vague-goal bundle: temp-repo fixture with a `size_audit` violation + a
    lesson file → bundle picks them up and names them.
  - `precedent.py`: seeded embedding index → `retrieve()` returns a passing exemplar and
    `retrieve_failures()` an anti-pattern; empty index → returns "" (cold-start degrade).
  - `uncertainty.py`: conformal band buckets a corroborated assumption `low` and an
    unverifiable one `elevated`; deferral fires only past the `elevated`-count threshold.
  - `predict.py`: seam-injected mock chat returns a predicted-outcome dict; a spec naming
    a real hot-churn file scores higher predicted-success than one naming an unverified path.
- Excellence-tier tests (Section 7) run flag-on; a flag-off test asserts byte-identical
  output to today's `elaborate()` for a fixed goal + mock chat.
- Tests use `str(config.PROJECT_ROOT)`, never a hardcoded `C:\9to5` (per project memory
  `hand-compact-no-autoformat`).

---

## 7. The Elevated Elaborator — size → generate → predict → select → resolve → evolve

The excellence tier turns single-shot elaboration into a staged pipeline: size the search
(A′), generate diverse candidates (A), predict each one's run outcome (B′), select the
strongest (B), resolve the one contested axis (C), and learn from the result (D) — with an
uncertainty escape hatch to a larger model (§7.5). Each stage **reuses real existing
machinery** (signatures verified against the codebase, cited below) except the one net-new
predictor (B′), and each does only what that machinery is actually good at.

### Stage A′ — Compute-optimal candidate budget

Best-of-N is **not** a fixed N. Test-time-compute gains are power-law in *prompt difficulty*
(arxiv 2506.12928), so `candidates.py` sizes the candidate budget to goal difficulty using a
cheap heuristic already available from grounding — a precise goal naming a real module gets
`N=1` (no search needed); a two-word vague goal ("improve everything") with must_split
violations and thin precedent gets `N=up to 5`. Difficulty signals: goal length / generic
verb (§3c detector), whether §3d precedent retrieval found close matches (close precedent →
lower N), and the §5 groundedness of a quick first draft. Bounded `[1, N_max]`,
`N_max` configurable (default 5). This spends tokens only where ambiguity actually warrants
the search, and `N=1` collapses cleanly to §3 single-shot.

### Stage A — Generate (best-of-N + diversity)

Produce the **N candidate elaborations** (N from Stage A′) from deliberately different
stances — `minimal-scope`, `thorough`, `risk-averse` — each still going through the §3
grounded 5W3H prompt. Use the MAP-Elites archive as a **diversity filter** so the candidates
are genuinely different points in spec-space, not rewordings of one guess:

- `qd_archive.QDArchive.add(elite: QDElite) -> bool` — `platform_core/orchestration/qd_archive.py:70`.
  Bins each candidate into a `(scope-size × risk)` cell, keeps one champion per cell.
- Gated by `QD_ARCHIVE_ENABLED` (`platform_core/app_config/inventor_flags.py:50`, default False).
  Off → skip diversity filtering, keep the N raw candidates.

Cost note: N-generate is the real token cost (N× the elaboration call). Elaboration happens
**once per run**, so this is cheap relative to the whole run.

### Stage B′ — World-model lookahead (propose-simulate-score)

Before scoring candidates statically, `predict.py` runs a **shallow, brain-simulated
lookahead** on each — the propose-simulate-score pattern from world-model planning (arxiv
2606.30639). For each candidate spec, one Ollama call imagines the *immediate* consequence
of the executor running it: which real files would change, and the single most-likely
failure mode. It returns a predicted-outcome dict `{likely_files, likely_failure,
predicted_success: float}`. This is the one genuinely **net-new** module (no existing
harness — the glob for `platform_core/simulation/` found nothing), so it is scoped tightly
to bound world-model drift (the documented failure mode of deep rollouts):

- **1 step only** — imagine the first executor action's consequence, never a multi-step
  rollout.
- **Grounded** — the prediction is fed the §3 repo snapshot + §5 verified paths, so it
  imagines against real state, not a hallucinated repo.
- **Advisory, never authoritative** — `predicted_success` is only a *term* in the Stage B
  `weight_fn`, never a hard gate; a wrong prediction can at worst mis-rank, not block.
- Gated by its own `ELABORATOR_LOOKAHEAD_ENABLED` sub-flag (default OFF even when the
  master flag is on, given it is the highest-risk / newest component). Off → Stage B scores
  on static groundedness alone.

The payoff: Stage B's selector stops being static. The `weight_fn` becomes
**predicted-success (B′) + groundedness (§5) + precedent-match (§3d) − elevated-risk-count
(§3b)** — a forward-looking selector that prefers the spec most likely to *actually run
clean*, not just the one that looks most complete on paper.

### Stage B — Select (portfolio optimizer — the clean reuse)

- `portfolio_optimizer.optimize(candidates, *, deps=(), conflicts=(), weight_fn=None, safe_only=False) -> PortfolioSelection`
  — `platform_core/orchestration/portfolio_optimizer.py:175`. Domain-agnostic; solves
  max-weight closure exactly.
- We pass a **custom `weight_fn`** scoring *elaboration merit*, the forward-looking blend
  from Stage B′: `predicted_success` (B′) + groundedness (fraction of named paths that
  verified real, per §5) + precedent-match (§3d cosine to passing exemplars) + 5W3H
  completeness, minus a penalty per `elevated`-risk inferred assumption (§3b). `conflicts=`
  edges encode mutually-exclusive scopings. Returns `selected_candidate_ids` /
  `demoted_candidate_ids` / `objective_value`.
- The default `candidate_weight()` biases toward invention novelty/reversibility — **we
  override `weight_fn` entirely** for elaboration merit. The optimizer itself doesn't care
  that its candidates are specs, not patches — a natural fit.
- Gated by `PORTFOLIO_OPTIMIZER_ENABLED` (`inventor_flags.py:48`, default **True**,
  read-only scoring). Off → pick the single highest-groundedness candidate by simple sort.

### Stage C — Resolve the contested axis (debate, used narrowly)

Portfolio selection surfaces *where* the top candidates genuinely disagree on a real axis
(e.g. minimal-scope vs thorough). **Only then** — not every run — resolve that one axis:

- `runDebate(blackboard, subtask_id, roster, *, arbiter_fn=None, max_rounds=None, goal="") -> dict`
  — `society/debate.py:51`. Returns `{resolved: bool, winner: str|None, reason: str, rounds: int}`.
- **Honest scoping:** debate is built for consensus on *one contested result*, not for
  ranking a field of N. So we use it *only* to break the single contested tie Stage B
  surfaces — a small roster arguing that one axis — never to score all candidates. This
  respects what debate actually does well.
- Gated by `SOCIETY_ENABLED` (`platform_core/app_config/epic_flags.py:43`, default
  `_fullStack()`); rounds by `SOCIETY_DEBATE_MAX_ROUNDS` (`epic_flags.py:45`, default 3).
  Off, or no genuine contested axis → skip; use Stage B's top pick directly.

### Stage D — Evolve (the compounding property)

After the run completes, write an **elaboration-fitness signal** — did this spec lead to a
clean run, or to replans / verification failures / adversary HOLDs? — into the experience
ledger. The existing post-run maintenance pass learns from it:

- `sie.run_maintenance(*, reason="post-run", force=False, throttle_seconds=..., db_path=None) -> dict`
  — `learning/evolution/sie.py:138`. Already runs in the orchestrator's post-run `finally`
  block; already has a weekly promotion tier (`promotion.py`, `meta_opt.py`).
- The fitness signal lets promotion learn **which generation stance (Stage A) wins for which
  goal-family** (`learning/feedback/lessons.py::family_of` — `lessons.py:35`). Next run, the
  §3c vague-goal bundle surfaces that learned preference via
  `postmortem.guidance_for(title, db_path=...)` (`postmortem.py:64`). **The elaborator gets
  better at guessing what you wanted the more it is used.** This is the actual "next level"
  property — every other section is static correctness; this one compounds.
- No new storage and no new schema: the signal rides the existing experience-ledger →
  consolidate → promotion → guidance pipeline.
- Gated by `SIE_FORCE_WEEKLY` (`platform_core/app_config/llm.py:240`, default `_fullStack()`)
  and halted by `SIE_KILL_SWITCH` (`llm.py:243`, default False). Off → §3–6 behavior with no
  learning; the fitness signal is simply not written.

## 7.5 Uncertainty-aware deferral (Ollama → Claude escalation)

The whole tier so far runs on the local Ollama brain. But some goals are genuinely too
ambiguous for the small model to elaborate well — and the research is explicit that the
right move is **deferral, not more local self-critique**: a small model should abstain and
escalate to a larger one when calibrated uncertainty is high (ReDAct, arxiv 2604.07036),
which maps precisely onto 9to5's existing **Ollama-orchestrator → Claude-executor** split.

`uncertainty.py` computes a run-level uncertainty from signals that don't rely on the
model's self-report: the count of `elevated`-risk assumptions (§3b conformal band), the
Stage B `objective_value` spread (candidates all scoring low = no good option found), and
§3d precedent coverage (no similar past goal = genuinely novel, higher uncertainty). When
that crosses a threshold, the elaboration of *that one goal* is **deferred to Claude** (the
already-available executor model) for a single high-capability pass, instead of accepting a
weak local spec.

- Cost-aware by construction: escalation is the expensive path, taken only when the cheap
  local path is calibrated-unlikely to be good — the explicit ReDAct cost/benefit trade.
- Gated by `ELABORATOR_DEFER_ENABLED` (default OFF). Off → never escalates; the best local
  candidate is used as-is (today's behavior, plus the rest of the tier).
- Honest limit: this reuses the executor's Claude seam for a *planning* call, which is a new
  call-site for that model. If the seam isn't available (e.g. offline / dry-run), deferral
  degrades to "keep the best local candidate" rather than failing the run.

### Graceful degradation matrix

| Sub-flag off | Effect |
|---|---|
| `ELABORATOR_LOOKAHEAD_ENABLED` (B′) | No world-model prediction; Stage B scores on static groundedness only |
| `QD_ARCHIVE_ENABLED` | Stage A keeps N raw candidates, no diversity filter |
| `PORTFOLIO_OPTIMIZER_ENABLED` | Stage B → simple highest-groundedness sort |
| `SOCIETY_ENABLED` | Stage C skipped; use Stage B top pick |
| `SIE_FORCE_WEEKLY` / `SIE_KILL_SWITCH` | Stage D writes no fitness signal; no learning |
| `ELABORATOR_DEFER_ENABLED` (§7.5) | No Claude escalation; best local candidate used as-is |
| **`ELABORATOR_EXCELLENCE_ENABLED`** (master) | **Entire tier off → §2–6 path only; if all excellence code is skipped, output is byte-identical to today** |

Empty precedent index (§3d cold start) and an empty embedding store are also degradations,
not errors: precedent returns "", CBR contributes nothing, and the tier runs on §3c grounding.

Nothing in this tier is force-wired into the core run loop; every stage degrades to the
tier below it.

---

## 8. Rollout

1. Land §2–6 (module split, 5W3H prompt, self-review, schema, path-verify, restored tests)
   behind `ELABORATOR_EXCELLENCE_ENABLED=OFF`. Verify byte-identical flag-off output.
2. Land §3d precedent + §3b calibrated risk band (both reuse existing infra) — still gated
   under the master flag. Burn-in with the flag on in a dev/sim run; confirm
   `schema_validity_rate` logging, `unverified_paths`, and precedent cold-start degrade.
3. Land §7 Stages A′/A/B/C/D, each behind its existing sub-flag; verify the degradation matrix.
4. Land the two highest-risk / newest pieces **last and default-OFF even under the master
   flag**: §7 Stage B′ world-model lookahead (`ELABORATOR_LOOKAHEAD_ENABLED`) and §7.5
   Claude deferral (`ELABORATOR_DEFER_ENABLED`). These are the only net-new call-sites; gate
   them separately so the rest of the tier can go on without them.
5. Flip `ELABORATOR_EXCELLENCE_ENABLED` default to ON only after burn-in shows no regression
   vs. the current elaborator on a fixed goal battery. Keep B′ and deferral opt-in until
   their own burn-in data justifies default-ON.

## 9. Non-goals (YAGNI)

- No multi-round debate across all candidates (Stage C resolves one axis only).
- No deep (>1 step) world-model rollout — Stage B′ is single-step and advisory only, to
  bound the drift the research warns deep simulation causes.
- No new persistent store — Stage D and §3d precedent both ride the existing experience
  ledger / embedding index; nothing new is created.
- No repeated self-critique loop (§3b is exactly one pass, per the reflexion survey).
- No change to model/effort routing for the main loop (per `.claude/rules/orchestration.md`);
  §7.5 deferral is an elaboration-only escalation behind its own default-OFF flag, not a
  routing change.
- No change to the frozen public API of `elaborate()` / `extractUniverse()`.
