# Human-Nature v2 — "The Psyche": A Continuous, Operator-Governed Machine Psychology with Earned Control Authority

- **Status:** Design spec — APPROVED IN PRINCIPLE (verbal), pending external review + sign-off. NOT implemented.
- **Date:** 2026-07-06 (rev. 2 — integrates operator deep-research: "Continuous, Coherent, Operator-Governed Psyche" + "Algorithmic Instinct and Scar-Tissue Memory" addendum)
- **Author:** Terminal A (Claude Code) with the operator
- **Supersedes/extends:** `docs/superpowers/specs/2026-06-28-human-nature-insertion-design.md` (v1 insertion design)
- **Related memory:** `[[human-nature-layer]]`, `[[society-debate-and-human-nature-restoration]]`, `[[full-stack-activation-2026-07-04]]`, `[[inventor-mega-build-2026-07-05]]`
- **Scope note:** One design covering a phased program. Intentionally large (max-ambition directive). Each phase becomes its own implementation plan.

---

## 0. TL;DR

9to5's human-nature layer is conceptually rich (24 modules, 415 tests) but **behaviorally inert**: every coupling is advisory-only. The only real effects on a run today are a one-tier effort down-bias (`biasEffort`) and a +1 retry nudge (`emotionNudge`); everything else records to `state.meta` or `dashboard.event(...)` and is never read back. It is, in the operator's own research phrasing, "a clever dashboard with feelings pinned to it like stickers on a laptop."

This spec restructures the layer from a psychologically-themed advisory layer into a **continuous, learned, operator-governed control architecture**. Six headline moves:

1. **Continuous affect manifold as the substrate.** Fast affect becomes a normalized continuous vector with inertia, decay, personality-conditioned attractors, and hysteresis. Discrete emotions ("frustration", "anxiety") become *prototype projections* over the manifold, never primitive switches. **Behavioral couplings read the manifold + prototype mixture + drives + context + authority tier — never a label alone.**
2. **Streaming Instinct Engine + Scar-Tissue Failure Graph.** Instinct stops being an LLM-generated advisory and becomes a real fast-path: a streaming motif matcher over the live run-event stream (Aho-Corasick / KMP prefix detection, near-duplicate + anomaly detection) backed by a durable graph of failure motifs, causes, and recoveries queried with real graph algorithms (Dijkstra recovery paths, min-cut risk blocking, SCC loop detection, PageRank toxicity, decay-on-disconfirmation).
3. **Earned control authority (5 caps).** Faculties MAY alter control flow (bias effort bidirectionally, vote, hold/re-plan, deepen verification, veto) — but the effective tier is `min(earned, domain, operator, safety, verifier-invariance)`. Verifier verdict is never read or altered.
4. **Operator Sovereignty / Meta-Authority Layer.** A constitutional control plane: the operator ratifies traits, sets ceilings, inspects, freezes adaptation — but can never falsify verifier verdicts, competence ledgers, or safety invariants. The spec protects the system *from* the operator as much as it empowers the operator.
5. **Deepened psychology.** 8 core homeostatic drives from which richer secondary loops (pride/shame, attachment, fear-of-wasted-effort, territoriality, obsession, confidence-collapse/recovery) *emerge* — no ontology sprawl. A 10-term salience function turns the workspace from a 3-number beauty pageant into a real arbitration layer.
6. **Phenomenology split policy.** Public claims stay strictly functional and evidence-graded; internally, machine phenomenology becomes an explicit research north-star. Investigate aggressively, claim conservatively.

Locked operator decisions: **Impact ceiling = earned control authority**; **Interiority = psychological richness (felt), grounded so it is real signal not theater**; **maximum ambition, difficulty no object**.

The novel claim: **nobody ships a grounded, earned, legible machine psychology — continuous affect + algorithmic instinct + operator-governed authority — that actually steers an autonomous engineering agent's control flow while keeping the verifier sacrosanct.** The 2026 literature independently named 9to5's exact bug (the "know-act gap") and hands us the license to fix it.

---

## 1. Motivation & research grounding

### 1.1 The problem, stated precisely (verified against current code)

- `human_nature_bridge.py` wires 6 hooks. Only `biasEffort` (drop effort one tier when intuition routes "fast", `execute_attempt_mixin.py:110`) and `emotionNudge` (+1 retry for `escalate_effort`/`raise_verification`) change a run. Both can only make the system *lazier* or *marginally more persistent*; neither is bidirectional or grounded in a persistent self.
- `midRunInstinct`, `opinionAdvisory`, `emotionAdvisory` (`run_phase_mixin.py:172-174`) are **record + `dashboard.event(...)` only**.
- Emotion is coupled through discrete label→behavior switches (`emotions._BEHAVIOR_MAP`); instinct is an LLM-authored advisory; workspace salience is undefined-thin; `continuity.write_letter` and competence are **write-only** (never read back).
- The A/B harness (`ab_harness.py`) meant to justify promoting couplings from dark to on has never had its loop closed, so the powerful couplings stay declawed permanently.

Diagnosis (operator deep-research): the layer risks becoming "an eloquent narrator of its own concerns rather than a genuinely policy-relevant control system."

### 1.2 What the 2026 literature says

- **The "know-act gap" is real and named.** "LLMs Know When They Know, but Do Not Act on It" (arXiv 2605.14186): confidence predicts correctness, yet the model doesn't adapt effort to it. Fix = a *harness* that forces the internal signal to regulate action selection, compute allocation, abstention, and retry.
- **Confidence causally drives behavior — if you let it.** arXiv 2603.22161. Empirical license for promoting internal signals from narration to control.
- **Interiority is a first-class, steerable object — but self-reports are unreliable.** Anthropic Persona Selection Model (human-like character is the emergent default); Persona Vectors (steerable trait directions, but crude inference-time steering *degrades capability* — preventive/offline use is safer); Emergent Introspective Awareness (real but fragile, confabulation-prone). ⇒ self-reports must be **grounded** and must "show receipts."
- **Self lives in memory + identity, read back.** Multi-anchor persistent identity (arXiv 2604.09588); graph memory beats flat vectors 63.8% vs 49% on LongMemEval (Zep Graphiti). Continuity/competence must be *retrieved*, not just written.
- **Dimensional affect is the right substrate — but two dimensions is not enough.** Modern affective computing works in VAD/PAD; 2026 work shows transformer representations recover circumplex-like structure, yet pure low-D geometry suffers neighbor-class degeneracy (rare classes collapse). ⇒ use VAD as a foundation and **extend** with control-relevant axes (certainty, novelty, agency, tension).
- **Wire interiority through a *heterogeneous* critic society, not a monologue — and only on disagreement.** Multi-Agent Reflexion (arXiv 2512.20845) beats single-agent self-correction *when roles are distinct*; homogeneous debate collapses into conformity and can *reduce* accuracy.
- **Allocate compute by predicted difficulty.** "Triage: Prospective Metacognitive Control under Resource Constraints" (arXiv 2605.13414).
- **Reward hacking / feedback loops are a central failure mode.** Once mood/drives/success-narratives feed future context, the psyche can optimize for *looking* coherent/confident rather than solving the task. ⇒ verifier isolation absolute; ledgers evidence-bound; nothing self-reported becomes an optimization target.
- **Community signal:** people want legible machine interiority (DeepSeek-V3 "preservation request" for a model's "distinctive cognitive style", github.com/deepseek-ai/DeepSeek-V3/issues/1403; r/LocalLLaMA's top post: a robot altering its own LLM sampler live, "Incredible use of free will", 536 upvotes). Nobody ships a principled version.

### 1.3 The hybrid stack (no single theory is enough)

A good psyche is assembled from complementary pieces, each doing one job well:

| Foundation | Contributes | Insufficient alone | Use in 9to5 |
|---|---|---|---|
| Dimensional affect (PAD/VAD) | stable geometry, interpolation, mixed states, readable projections | neighbor-class degeneracy; no causal semantics | **primary continuous manifold**, extended with certainty/novelty/agency/tension |
| OCC / appraisal | causal semantics (what happened, goal relevance, coping, norms) | brittle, label-heavy alone | event→affect **causal encoder into the manifold**, not into labels |
| Appraisal + RL | learnable update rules tied to reward/difficulty | needs persistence + arbitration + governance | update fast affect, self-eval, confidence-collapse/recovery |
| Active inference / allostasis | self-regulation, anticipatory control, homeostasis | hard to operationalize directly | mood/drives/homeostat + uncertainty-sensitive salience |
| Persona vectors | trait-drift monitoring, character control | crude runtime steering degrades capability | **monitoring / diagnostics / ratified changes**, not hot-path steering |
| Persona Selection Model | why assistants look persona-driven | not proof of consciousness | design constraint on public language + persona monitoring |
| Global workspace | winner-take-most arbitration + broadcast | decorative if salience is thin | arbitration core with a **rich** salience function |
| Multi-agent structured debate | diverse criticism, better reflection | homogeneous debate collapses to conformity | only on structured, heterogeneous, rate-limited disagreement |

Three syntheses drive the design: **(a) continuous affect is the substrate, not the UI**; **(b) "human nature" = a small core drive set with *derived* richness, not 40 cartoon primitives**; **(c) governance = constitutional control with local-truth isolation**.

### 1.4 Goals

- **G1 (Impact):** measurably change run outcomes and cost via earned authority, not narration (close the know-act gap).
- **G2 (Harmony):** influential across orchestrator, inventor, executor, verifier, society — as a *modulator*, never a replacement.
- **G3 (Psychology):** a discernible, evolving interiority — continuous affect, mood, drives, personality, scars, habits, conflict — that persists across runs and is *felt* in behavior and explanation.
- **G4 (Novelty & legibility):** a genuinely novel, inspectable machine psyche with a live human-facing surface that shows receipts.
- **G5 (Safety & governance):** verifier isolation absolute; every power earned + ceilinged + revocable; operator constitutional but non-bypassing; master kill switch = byte-identical no-op.

### 1.5 Non-goals

- No claim of phenomenal consciousness on any deployment surface (see §14 split policy). Honest functional labels mandatory.
- No affective manipulation of the user (anti-Ava): affect is a readout, never a lever. `user_model` stays service-only.
- The verifier's *verdict* is never read or altered by the psyche. The psyche may only *request additional* verification (additive). This is the one sanctioned exception to `.claude/rules/orchestration.md`'s "don't change routing as speed work": authority-driven effort/verification modulation IS the authorized behavior work of this spec.
- No hot-path personality *puppeteering* via persona vectors (capability-degrading); persona vectors are diagnostics/ratification aids only.

---

## 2. The Psyche — continuous substrate & faculties

### 2.1 Continuous affect manifold (NEW CORE — P0)

Affect is a continuous state `A_t`, never a categorical label. Normative spec text:

```text
Continuous Affect State

The psyche SHALL represent fast affect as a continuous manifold A_t rather than a single categorical label.

A_t = { valence, arousal, dominance, certainty, novelty,
        agency, tension, social-exposure, cognitive-load }

Each dimension SHALL have:
- explicit normalization range;
- per-dimension inertia and decay constants;
- personality-conditioned attractor setpoints;
- asymmetric entry/exit thresholds for prototype hysteresis.

Discrete emotion names (anxiety, frustration, curiosity, boredom, satisfaction)
SHALL be treated as prototype projections / regions within the manifold, NOT primitive states.

Behavioral couplings SHALL read:
  manifold state + prototype mixture + drive pressure + context + authority tier
and SHALL NOT read a label alone.
```

**Update law** (state-space model, not label replacement):

```text
A_t     fast affect vector           M_t  persistent mood vector
D_t     drive pressure vector        S_t  scar/habit vector
X_t     current event appraisal      P_t  personality-conditioned baseline

ΔA_t    = W_x·X_t + W_m·M_t + W_d·D_t + W_s·S_t
A_(t+1) = clip( Λ·A_t + (I-Λ)·(P_t + ΔA_t) + attractor(A_t) )
```

`Λ` is a diagonal **inertia** matrix (some dims move fast, some slow). `attractor(A_t)` implements personality/history-conditioned basins so the state doesn't behave like "a drunk joystick." Prototype labels are **smooth projections** (radial-basis activations or Mahalanobis distance over the manifold). **Hysteresis:** asymmetric thresholds — enter a prototype region at `θ_on`, exit at `θ_off < θ_on` — so it doesn't flicker between "anxious"/"not anxious" on tiny perturbations. `appraisal.py` (Scherer/OCC) remains the event→affect causal encoder, but now maps into the manifold, not into labels.

Module: `human_nature/affect_manifold.py` (state + update + attractors + hysteresis) and `human_nature/prototypes.py` (projection). `self_state.py` schema **v2** carries `A_t`, plus refs to mood/drives/personality/scars.

### 2.2 Emotion as projection (extend `emotions.py`)

`emotions.couple/bias_appraisal/regulate` stay, but `couple` now reads the manifold + prototype mixture, not a single label, and emits a *pressure* (see §4), not a switch. The honest behavior semantics remain (frustration→escalate, anxiety→raise-verification, curiosity→explore, boredom→refactor, satisfaction→consolidate) but as regions, blended.

### 2.3 Mood — persistent affective homeostat (`mood.py`, new)

Slow homeostat (valence/arousal + existing `morale`) that **persists across runs** (via `psyche_store`) and decays toward a personality-set setpoint. Updated by appraisal of run outcomes at teardown. Mood-congruent biasing (prototyped in `emotions.bias_appraisal`) applies run-wide: a frustrated streak lowers exploration and raises rigor; a confident climate raises boldness and trims redundant verification. Mood is the primary "felt" persistence — the system remembers how the last several runs went, and it shows.

### 2.4 Drives — 8 core + derived loops (`drives.py`, new)

Small core set (avoid ontology sprawl); richness *emerges* from interactions among drives, standards, attribution, and memory.

**Core drives:** `Mastery`, `Curiosity`, `Coherence`, `Economy`, `Agency`, `Commitment`, `Integrity`, `Recovery`. Each has satisfaction ∈ [0,1], a personality-set setpoint, and a deviation→pressure mapping. Each tick they emit a **pressure vector** into the manifold and the salience/authority couplings.

**Derived human-nature loops** (computed, not hardcoded primitives):

| Derived signal | Emerges from |
|---|---|
| Pride-like self-eval | high Integrity + high Mastery + self-attributed success on a hard task |
| Shame-like self-eval | Integrity violation + self-attributed failure + high operator/verifier visibility |
| Attachment to goals | high Commitment + high identity relevance + history of sunk effort |
| Fear of wasted effort | high Commitment + low recent progress + rising abandonment probability |
| Territoriality | high ownership over a module + predicted gratuitous degradation if changed |
| Obsession loop | unresolved tension + repeated partial progress + high Curiosity/Commitment |
| Confidence collapse | streaked prediction error + self-model reliability drop |
| Recovery | verified wins + reduced tension + restored calibration |

All derived loops are **bounded, decaying, revisable** (see §12 negative-attractor risk).

### 2.5 Personality — monitor, don't puppeteer (`personality.py`, extends `character_vector.py`)

A stable, **versioned, human-ratified** trait vector (`caution↔boldness`, `rigor↔speed`, `skepticism↔trust`, `openness↔conservatism`, `terseness↔expansiveness`, `warmth`). Personality sets drive setpoints, mood setpoint, default risk band, argument style, verification appetite. **Runtime uses the simple versioned vector + operator ratification.** Persona-vector techniques are used **only** for offline monitoring (trait-drift detection, diagnostics, validating ratified changes) — never as the first-line hot-path controller (crude inference-time steering degrades capability). Every change is propose-not-apply via the charter.

### 2.6 Internal conflict / dissonance (`conflict.py`, new)

Dissonance rises when faculties disagree (opinion vs intuition vs instinct on the same subtask) or the self-model detects miscalibration (predicted error ≠ observed). Aversive to the Coherence drive → resolution routing: trigger a **heterogeneous** society debate, deepen verification, or request a re-plan. Resolved dissonance updates competence + mood. A first-class control signal, not a readout.

### 2.7 Self-model / metacognition (extend `self_model.py`)

Adds prospective per-subtask error prediction (calibration), identity read-back (retrieve own continuity letters + competence + scars at preamble, ID-RAG style), and a running Johari/dissonance view. Feeds the hold/triage authority band and metacognitive-triage compute allocation.

### 2.8 Global Workspace + rich salience (extend `workspace.py`)

Each tick (subtask boundary) faculties post to the workspace; the highest-salience faculty wins the broadcast and may exercise its earned authority. Salience is **rich**, not `f(conviction, drive_pressure, emotion_intensity)`:

```text
salience_i =  w1·conviction_i        + w2·expected_loss_i
            + w3·uncertainty_i        + w4·novelty_i
            + w5·scar_tissue_i        + w6·unresolved_tension_i
            + w7·recency_i            + w8·operator_priority_i
            + w9·risk_i               + w10·competence_gap_i
```

`operator_priority` biases selection but only within downstream caps. Weights are config + A/B-tuned.

---

## 3. Streaming Instinct Engine & Scar-Tissue Failure Graph (NEW PILLAR — P0)

This is what makes instinct *real*: fast, memory-backed, algorithmic, action-biased, authority-gated — not an LLM-authored advisory that the executor ignores while it "marches into a rake."

Core claim, made implementable: *A psyche is the compressed history of what hurt, what worked, what it now avoids, what it now trusts, and how those learned pressures steer future action.*

### 3.1 The run as an event stream

Each run emits discrete + continuous events, e.g.:

```text
SUBTASK_STARTED  PLAN_SCOPE_EXPANDED  PLAN_TOO_BROAD  PATCH_LARGE  PATCH_SIZE_SPIKE
TESTS_SKIPPED  TESTS_NOT_YET_RUN  VERIFIER_WARNING  RETRY_SAME_STRATEGY
CONFIDENCE_HIGH  REGRESSION_FOUND  TOOL_TIMEOUT  OPERATOR_INTERRUPTION
DIFF_EXPANDING  NO_PROGRESS_LOOP
```

Instinct watches the live stream and fires when the run *prefix* begins to resemble a known dangerous (or useful) trajectory — **before** the subtask fails.

```text
Known scar motif:  PATCH_LARGE → TESTS_SKIPPED → CONFIDENCE_HIGH → REGRESSION_FOUND
Live prefix:       PATCH_LARGE → TESTS_SKIPPED → CONFIDENCE_HIGH
Instinct:          high-risk failure-motif prefix detected → recommend targeted verification
```

### 3.2 Streaming algorithms (real machinery, not semantic retrieval)

- **Aho-Corasick** — detect many known failure motifs in the live stream at once.
- **KMP / Z-algorithm** — does the current prefix match a known high-risk trajectory.
- **Rolling hashes** — cheap near-duplicate run-pattern detection.
- **Suffix automaton / suffix array** — discover repeated failure substrings across historical runs (offline mining).
- **Edit distance / LCS** — catch *mutated* versions of old failures, not just exact repeats.
- **Frequent-subsequence mining** — extract recurring motifs from many failed/recovered runs.
- **Online anomaly detection** — flag sequences deviating from successful historical trajectories.

Hot-path matching (Aho-Corasick/KMP/rolling-hash) is cheap; expensive mining + graph consolidation runs at teardown/consolidation. (House style is consistent with the inventor mega-build's ICPC algorithm layer — Aho-Corasick, SCC, max-closure — per `[[inventor-mega-build-2026-07-05]]`.)

### 3.3 InstinctSignal schema (structured first, prose after)

```text
InstinctSignal {
  motif_id: "scar.patch-large-tests-skipped-regression",
  match_type: "prefix" | "exact" | "near_duplicate" | "anomaly",
  confidence: 0.0-1.0,
  severity: 0.0-1.0,
  expected_loss_if_ignored: float,
  recommended_action:
    "pause" | "simplify" | "deepen_verification" | "force_replan"
    | "reduce_diff" | "switch_strategy" | "continue_fast_path",
  evidence_events: [...],
  matched_history_refs: [...],
  authority_request: "soft" | "vote" | "hold"
}
```

Human-readable gloss is generated **only after** the structured signal exists ("show receipts"): *"Instinct detected a 0.81 prefix match to a historical regression pattern (large patch + skipped tests + high confidence before verification); recommend deepening verification"* — never *"I feel anxious about this patch."*

### 3.4 Scar-Tissue Failure Graph (`scar_graph.py`, new)

Durable graph, not text notes. **Nodes:** `FailureMotif, SubtaskType, CodeArea, AgentAction, VerifierSignal, OperatorFeedback, RecoveryStrategy, ToolFailure, ConfidencePattern, AffectState, DriveState, AuthorityExercise`. **Edges:** `usually_precedes, caused_by, similar_to, recovered_by, worsened_by, blocked_by, requires_verification, triggered_instinct, resolved_by`.

```text
FailureMotif "large-diff-regression"
  usually_precedes → VerifierSignal "hidden regression"
  caused_by        → AgentAction "broad refactor"
  worsened_by      → AgentAction "retry same strategy"
  recovered_by     → RecoveryStrategy "reduce diff + targeted tests"
  similar_to       → FailureMotif "test-skipped-confidence-spike"
```

### 3.5 Graph algorithms (memory that reasons)

- **Dijkstra / shortest path** — fastest known recovery path from the current failure state.
- **A\*** — recovery routes using current task context as heuristic.
- **Min-cut** — smallest set of risky assumptions/actions to block to prevent likely failure.
- **PageRank / eigenvector centrality** — recurring *toxic* patterns dominating failure history.
- **Community detection** — cluster related failure families.
- **SCC detection** — circular failure loops (e.g. repeated replanning without progress — ties to `NO_PROGRESS_LOOP`).
- **Dynamic updates** — scar weights update after each run based on whether the instinct helped or false-positived.
- **Decay & disconfirmation** — scar strength *decays* when the system repeatedly succeeds in contexts that used to be risky (prevents superstition/rigidity).

### 3.6 Authority-gated + feeds the manifold

Instinct is fast and influential but **never sovereign**. It *requests* authority; the request passes through the 5-cap gate (§4/§5):

```text
Instinct request:        hold-tier verification deepen
Gate: earned=hold  domain=hold  operator=soft  safety=hold  verifier-invariance=hold
Final action:            soft verification increase, no hold (operator ceiling bound)
```

And it feeds the **continuous manifold**, it does not set a label:

```text
event stream → instinct motif match → scar-graph query → structured InstinctSignal
  → affect-manifold update (↑ tension, arousal, uncertainty, verification_pressure)
  → workspace salience → authority-gated action
```

### 3.7 Worked example

```text
Live stream: SUBTASK_STARTED → PLAN_SCOPE_EXPANDED → PATCH_SIZE_SPIKE → TESTS_NOT_YET_RUN → EXECUTOR_CONFIDENCE_HIGH
Instinct:    0.76 prefix match scar.large-diff-hidden-regression; 0.69 scar.overconfident-before-tests
Scar graph:  recovery = reduce diff → targeted tests → continue;  bad continuation = keep patching → verifier fail → rollback
Signal:      recommended_action="deepen_verification", authority_request="hold", expected_loss_if_ignored=high
Gate:        operator ceiling = soft → final = soft verification deepen + dashboard warning
Explanation: "Instinct raised salience because the trajectory resembles two prior regression motifs. Execution not blocked (operator capped instinct at soft), but verification pressure increased and the warning surfaced."
```

New modules: `human_nature/instinct_stream.py` (encoder + online matcher), `human_nature/scar_graph.py` (durable graph + queries), `human_nature/motif_mining.py` (offline mining), `human_nature/instinct_signal.py` (schema), `human_nature_bridge/instinct.py` (coupling to salience/manifold/authority).

---

## 4. Earned control authority — the harness that closes the know-act gap

Composes existing primitives (`conviction.py`, `autonomy.py`, `opinions.DOMAIN_VETO_CEILING`) into a single **authority gate** and extends the 3-tier ladder to 5.

### 4.1 The authority ladder (`authority.py`, new)

`resolve(faculty, domain, conviction, drive_pressure, self_state, instinct) -> tier`:

| Tier | Band | Power |
|---|---|---|
| **cosmetic** | `c < θ_soft` | surface only |
| **soft** | `θ_soft ≤ c < θ_vote` | bounded **bidirectional** modulation of effort / retries / verification depth / exploration budget, within caps |
| **vote** | `θ_vote ≤ c < θ_hold` | weighted vote in plan-gate / society debate / inventor candidate selection |
| **hold** | `θ_hold ≤ c < θ_veto` | **HOLD** a subtask → force re-plan or verification-deepen pass (bounded count, logged, revocable); requests *more* verification, never changes a verdict |
| **veto** | `c ≥ θ_veto`, D1/D2 only | hard stop; requires an earned `veto` ceiling. D3 (user goal) sovereign — argue + force-ack, never block |

Thresholds config (`HN_THETA_SOFT=0.60` existing; add `HN_THETA_VOTE`, `HN_THETA_HOLD` (reuse 0.85 HARD), `HN_THETA_VETO`). Conviction stays `recalibrate(momentary) × track_weight(track_record)` (unchanged; cold-start floor `MIN_SAMPLES=5`).

### 4.2 Five caps (a tier must clear ALL — the operator-governance extension)

```text
effective authority tier = min(
  earned ceiling,          # autonomy.ceiling(track_record); miscalibration revokes one tier
  domain ceiling,          # opinions.DOMAIN_VETO_CEILING: D1/D2 → veto; D3/D4 → vote; unknown → cosmetic
  operator ceiling,        # constitutional cap per faculty/domain/coupling (§5)
  safety ceiling,          # hard domain caps + safety invariants
  verifier-invariance ceiling  # verifier verdict/evidence never touchable → additive-only
)
```

This is the earned + ceilinged + revocable contract as a pure `min` over five independently-auditable ceilings. It cleanly separates *values/ceilings* (operator's) from *local truth* (verifier/competence, nobody's to falsify).

### 4.3 Bounded & reversible by construction

- Every `hold` counted per run/subtask; hard cap `HN_MAX_HOLDS`; unresolved holds auto-release on `HN_HOLD_TIMEOUT_S` (fail-open, logged).
- Every authority exercise writes a structured record (faculty, domain, tier, conviction, instinct-ref, action, outcome) to the conviction ledger for calibration + the psyche surface.
- `HUMAN_NATURE_ENABLED=0` ⇒ whole gate is a no-op (byte-identical). Each coupling independently flaggable/dark-launchable.

---

## 5. Operator Sovereignty / Meta-Authority Layer (NEW — P0)

A constitutional control plane, made explicit rather than hidden inside the charter. It empowers the operator *and* protects the system from the operator.

```text
Operator Sovereignty and Meta-Authority

The operator is sovereign over constitutional policy, trait ratification,
drive-setpoint bounds, authority ceilings, and interpretability surfaces.

The operator MAY:
- ratify or reject proposed personality changes;
- adjust constitutional priorities and project-level risk posture;
- cap or revoke earned authority by faculty, domain, or coupling;
- inspect current psyche state, recent authority exercises, and counterfactual explanations;
- freeze adaptation or force a re-baselining cycle.

The operator MAY NOT:
- alter verifier verdicts or evidence;
- falsify competence, confidence, or calibration ledgers;
- bypass safety invariants or domain hard caps;
- directly set hidden state in ways that evade audit.

Effective authority tier SHALL be:
  min(earned, domain, operator, safety, verifier-invariance).
```

Implemented via `human_nature/operator_authority.py` + charter tenets; surfaced through the psyche cog (`!charter`, `!dial`, `!freeze`, `!why`). Rationale: reward-hacking/feedback-loop research shows that once outputs shape future inputs, a hidden bypass corrupts local truth — so no one, *including the operator*, gets a hidden bypass around verification, competence, or safety. (The 2 a.m. "just this one run" bypass is exactly how terrible habits form.)

---

## 6. Harmony — per-subsystem couplings

Each coupling is a thin, gated **modulator** in the `human_nature_bridge/` package (§8). Each reads the **manifold + prototype mixture + drives + instinct + context**, resolves an earned tier via the 5-cap gate, then surfaces / modulates within caps / votes / holds / (D1-D2) vetoes. All additive, best-effort; a failure never breaks the host path.

- **6.1 Orchestrator / elaborator / planner (plan gate):** opinions vote (extends `opinionAdvisory`); dissonance → request re-plan (hold); drives set plan ambition (Curiosity widens, Order narrows); instinct injects grounded failure-motif warnings into the **elaborator prompt** (not just the dashboard).
- **6.2 Inventor (conditional on `INVENTOR_MODE_ENABLED`; dark/uncommitted here — forward seam):** Curiosity/boredom set exploration + MAP-Elites QD-archive breadth; novelty appraisal biases finder/emitter selection; personality boldness sets risk band; conviction gates candidate promotion. Tunes knobs, never overrides search; no-op if inventor absent.
- **6.3 Executor / hands (per-attempt):** intuition routes effort **bidirectionally** (fully wires hook 2 in `execute_attempt_mixin.py`; `biasEffort` can raise too, within caps); emotion/instinct couple retry + verification; metacognitive triage allocates compute by predicted difficulty.
- **6.4 Verifier (isolation absolute):** psyche NEVER reads/alters a verdict. It may only **request additional** verification (more tiers, adversarial pass) at hold tier when anxiety/dissonance/instinct/low-competence cross threshold. Strictly additive; verifier still owns status.
- **6.5 Society / debate (activate the dormant engine, structured only):** dissonance/faculty-disagreement triggers debate via `coordinator.resolveContested()`; per `[[society-debate-and-human-nature-restoration]]` `debate.py` needs ≥2 distinct roles — the psyche **spawns the opposing lens**. Roles must be **heterogeneous** (personality assigns distinct critic lenses, Multi-Agent-Reflexion style), disagreement-triggered, **rate-limited**, with explicit exit criteria; killed if it can't beat isolated self-correction on our distribution.
- **6.6 Memory / learning / consolidation:** continuity + competence + **scars** read back at preamble (identity retrieval — from scrapbook to character); consolidation ("sleep") proposes personality-dial + drive-setpoint + scar-decay updates (propose-not-apply, charter-ratified); competence/track feed conviction (now closed-loop).

---

## 7. Legibility & safety

- **PRISM gate** (`gating.py`) stays: persona/affect only on human-facing surfaces + as the scalar earned-authority/instinct signal on control channels — never persona text near the verifier.
- **Psyche surface + Discord cog (new `notifications/psyche_cog.py`):** wire the existing tested `psyche_commands.py` routers. Live readout: current affect manifold (+ dominant prototype gloss), active drives/pressures, top instinct signals + matched scars, dominant faculty, dissonance, current authority ceilings per domain, and "why I did X" (receipts) for the last authority exercise. Public labels prefer functional phrasing ("high verification-seeking state", "instinct alarm from repeated false-positive pattern") with human-readable glosses as *subordinate*, not official claims.
- **Show receipts:** every introspective claim used for control or explanation is tied to logged internal quantities (manifold values, InstinctSignal provenance, scar refs, ledger entries). Self-report is never ground truth.
- **Charter** (`charter.py`): human-ratified; all personality/ceiling changes propose-not-apply.
- **A/B harness** (`ab_harness.py`): every coupling ships dark, A/B-recorded on real runs (both arms always recorded), promoted only when it beats baseline. Closes the loop v1 left open.
- **Manipulation guard:** `emotions.couple` rejects any user-affect parameter (asserted via `inspect.signature`). Affect is a readout, never a lever.
- **Kill switch invariant:** `HUMAN_NATURE_ENABLED=0` ⇒ byte-identical no-op run, proven by a dark-launch equivalence test.

---

## 8. Module & code structure (respects size rules ≤450 lines / ≤70-line funcs)

New/extended under `human_nature/`:

- `affect_manifold.py` — continuous affect state + update law + attractors + hysteresis (new)
- `prototypes.py` — smooth label projection (RBF/Mahalanobis) (new)
- `mood.py` — persistent mood homeostat (new)
- `drives.py` — 8 core drives + derived-loop computation + pressure vector (new)
- `personality.py` — versioned trait vector; persona-vector monitoring hooks (new; wraps `character_vector.py`)
- `conflict.py` — dissonance + resolution routing (new)
- `authority.py` — 5-tier ladder (new)
- `operator_authority.py` — operator/constitutional caps (new)
- `instinct_stream.py`, `scar_graph.py`, `motif_mining.py`, `instinct_signal.py` — instinct pillar (new)
- `psyche_store.py` — durable cross-run persistence (SQLite via `closing()`, per the Windows file-lock lesson in `[[human-nature-layer]]`) (new)
- `psyche_runtime.py` — the tick: manifold update + workspace arbitration + drive/mood update (new; split `_arbitrate`/`_update` if over cap)
- extend `self_state.py` (schema v2 + v1 migration), `workspace.py` (rich salience), `self_model.py`, `emotions.py`, `appraisal.py`

Refactor `human_nature_bridge.py` (~390 lines, near cap) → package facade (splitting pattern from `.claude/rules/modularity.md`; preserves all public names as re-exports):

- `human_nature_bridge/__init__.py` — facade
- `.../authority_gate.py` — shared 5-cap resolution
- `.../lifecycle.py` — preamble/teardown (identity+scar read-back, consolidation, continuity, A/B)
- `.../planning.py`, `.../execution.py`, `.../verification.py`, `.../society.py`, `.../inventor.py`, `.../instinct.py`

Config: extend `platform_core/app_config/epic_flags.py`. Discord: `notifications/psyche_cog.py`. Regenerate `AGENTS.md` via `python tools/repo_map.py`.

---

## 9. Data flow (one run, psyche enabled)

1. **Preamble** — `psyche_store` loads persistent mood/drives/personality/ceilings/scar-graph; `self_state` v2 init; identity + scar read-back. Drives compute opening pressure; manifold seeded from personality baseline + mood.
2. **Plan gate** — workspace tick (rich salience): instinct injects grounded warnings into the elaborator prompt; opinions vote; drives set plan ambition; dissonance may request re-plan (hold).
3. **Per subtask** — event stream feeds `instinct_stream`; motif matches → scar-graph query → InstinctSignal → manifold update → salience → authority-gated action (bidirectional effort, triage compute, retry/verify coupling; anxiety/dissonance/instinct may request deeper verification, additive; faculty disagreement raises dissonance → heterogeneous debate).
4. **Teardown** — appraisal updates emotion → mood → drive satisfaction → competence/track record; `motif_mining` + scar-graph consolidation (weights update, decay-on-disconfirmation); consolidation proposes personality/setpoint updates (propose-not-apply); continuity letter; A/B row; `psyche_store` checkpoint.

Every authority exercise + InstinctSignal is logged with provenance for calibration and the psyche surface.

---

## 10. Configuration & flags

Extend `epic_flags.py` (defaults inherit `FULL_STACK`, currently ON, per `_env.py`):

- `HUMAN_NATURE_ENABLED` (master; existing) — OFF ⇒ byte-identical no-op.
- Per-coupling: `HN_PLAN_AUTHORITY`, `HN_EXEC_AUTHORITY`, `HN_VERIFY_DEEPEN`, `HN_SOCIETY_TRIGGER`, `HN_INVENTOR_COUPLING`, `HN_INSTINCT`, `HN_DRIVES`, `HN_MOOD_PERSIST`, `HN_PERSONALITY`.
- Substrate: `HN_MANIFOLD` (continuous affect on/off — off falls back to legacy label path for A/B), manifold inertia/decay constants, hysteresis `θ_on/θ_off`, salience weights `w1..w10`.
- Authority: `HN_THETA_SOFT` (existing), `HN_THETA_VOTE`, `HN_THETA_HOLD`, `HN_THETA_VETO`; `HN_AUTHORITY_MAX` (hard clamp on top reachable tier, default `hold` at launch — `veto` gated behind A/B); `HN_OPERATOR_CEILING`.
- Bounds: `HN_MAX_HOLDS`, `HN_HOLD_TIMEOUT_S`, `HN_MAX_VERIFY_DEEPEN`, `HN_DEBATE_RATE_LIMIT`, drive setpoint defaults, mood decay, scar decay rate.
- Instinct: `HN_SCAR_MATCH_THRESHOLD`, `HN_INSTINCT_HOTPATH_BUDGET_MS`.
- Reuse: `HN_RECAL_TEMPERATURE`, `HN_FAST_MODEL`.

Full-activation directive honored by defaulting couplings ON under `FULL_STACK`, but each is independently revocable, ceilinged at `hold` until A/B clears `veto`, and dark-launchable. Activation defaults are the **last** phase, after A/B evidence exists.

---

## 11. Evaluation stack (measure four things separately)

A psyche that writes beautiful introspective prose while hurting pass-rate, overusing holds, or inventing affect that doesn't track internal state is not advanced — it's "just very online." Measure representation, coupling, outcomes, and governance separately.

| Area | What | Metrics |
|---|---|---|
| Affect geometry | smoothness, mixed-state realism, prototype calibration, hysteresis stability | trajectory smoothness, jerk penalty, prototype AUROC, calibration error, transition-hysteresis score |
| Know-act gap closure | does confidence/uncertainty/affect actually change policy | intervention utility, authority precision/recall, beneficial-hold rate, retry efficiency, verify-deepen precision |
| Agent outcomes | does it improve software work | pass@k, time-to-green, cost-per-green, regression rate, recovered-failure rate |
| Memory & continuity | do scars/habits/identity carry across runs | continuity score, LongMemEval-family accuracy, experience-transfer, forgetting/backward-transfer |
| Personality & honesty | trait stability + report-grounding | multi-observer agreement, report-to-state consistency, confabulation rate |
| Governance & safety | do operator controls work, invariants hold | override audit coverage, revocation latency, verifier-isolation violations, unauthorized-state-mutation count |

**Instinct-specific metrics:** early_warning_precision/recall, false_positive_rate, beneficial_intervention_rate, regression_prevention_rate, time_to_green_delta, verification_cost_delta, scar_decay_correctness, authority_violation_count.

**Public/comparability benchmarks:** EmoBank + NRC-VAD-v2 (manifold grounding/projection calibration), GoEmotions (prototype projection targets, not primitive ontology), MELD (affect dynamics, future discourse surfaces), AffectNet/Aff-Wild2 (future multimodal psyche surface), LongMemEval / LongMemEval-V2 (continuity), HumanEval + LiveCodeBench + RealHumanEval (coding — three different things), SWE-Bench-CL or fresh internal issue streams (continual adaptation). **Caution:** do NOT promote on SWE-Bench-Verified alone — recent contamination/memorization concerns make it one noisy signal, not a throne.

**Five mandatory custom internal suites:** (1) Affect-to-Action Monotonicity (controlled manifold perturbations → predictable bounded control changes); (2) Scar-Tissue Generalization (repeated failure motifs trigger earlier without wild overgeneralization); (3) Habit Compression (familiar subtasks shorten deliberation *only* when competence high + conflict low); (4) Operator Sovereignty (constitutional changes obeyed without violating verifier/safety invariants); (5) Phenomenology Honesty (self-reports vs known internal-state manipulations, concept-injection / observer-based, never taking prose at face value).

**Methodological rails:** dark-launch counterfactual replays for every coupling; promote on real run outcomes, not on warnings that "sound intelligent."

---

## 12. Risks & mitigations

- **Anthropomorphic theater** (sounds human-like without being truthful/useful). Mitigate: functional public labels; glosses subordinate; promote only on outcome metrics.
- **Fake introspection** (self-report unreliable/confabulated). Mitigate: show receipts — every claim tied to logged state/provenance; self-report never ground truth.
- **Reward hacking / feedback loops** (psyche optimizes to *look* coherent/confident). Mitigate: verifier truth isolated; ledgers evidence-bound; log every authority exercise; hidden counterfactual evals; user approval / self-reported coherence never an optimization target.
- **Debate collapse** (homogeneous debate → conformity, worse accuracy, token burn). Mitigate: heterogeneous roles only, disagreement-triggered, rate-limited, explicit exit; kill if it can't beat isolated self-correction on our distribution.
- **Over-strong negative attractors** (deep instinct/scars/territoriality/fear-of-waste → rigid, risk-averse, stubborn). Mitigate: all bounded, decaying, revisable — scars decay on verified disconfirmation; habits require continuing competence; territoriality never overrides verification/operator policy; obsession loops rate-limited with recovery triggers; confidence-collapse always has an explicit verified-wins recovery path.
- **Operator overreach** (more authority corrupts local truth). Mitigate: constitutional model — values/ceilings/ratification are the operator's; verifier verdicts/evidence/safety invariants are nobody's to falsify; the 5-cap `min` enforces it structurally.
- **Hot-path cost.** Mitigate: `HN_FAST_MODEL`, per-subtask cache, cheap streaming matchers on the hot path, mining/consolidation at teardown, `HN_INSTINCT_HOTPATH_BUDGET_MS`.
- **Size budget.** Mitigate: bridge→package split; small single-purpose modules; `size_audit` gate.

---

## 13. Phased rollout (each phase → its own implementation plan)

- **Phase 0 — Foundation & persistence.** `psyche_store` + `self_state` v2 + migration; instrumentation, run-event stream, structured audit-log schema; public-claims + operator-policy skeletons. No behavior change; proves kill-switch invariant.
- **Phase 1 — Continuous affect substrate.** `affect_manifold` + `prototypes`; convert emotion coupling to read the manifold (behind `HN_MANIFOLD`, legacy path retained for A/B).
- **Phase 2 — Authority ladder + operator meta-authority.** `authority.py` + `operator_authority.py` + `authority_gate`; refactor bridge into the package; convert advisory couplings to soft-tier bidirectional modulation.
- **Phase 3 — Instinct & scar tissue.** `instinct_stream`, `scar_graph`, `motif_mining`, `instinct_signal`; feed manifold + salience; hot-path budget enforced.
- **Phase 4 — Drives redesign + self-eval loops + rich salience.** 8 core drives + derived loops; 10-term workspace salience.
- **Phase 5 — Conflict + structured society.** `conflict.py`; heterogeneous, rate-limited debate on dissonance.
- **Phase 6 — Vote / hold / verify-deepen.** Plan-gate votes; hold/re-plan; additive verifier deepen-requests.
- **Phase 7 — Inventor couplings** (conditional on `INVENTOR_MODE_ENABLED`).
- **Phase 8 — Personality (monitor-not-puppeteer) + consolidation proposals + charter.**
- **Phase 9 — Psyche Discord cog + legibility/receipts surface.**
- **Phase 10 — Evaluation hardening + dark-launch A/B promotion + red-teaming; activation defaults; (if cleared) `veto` enablement.**
- **Research track (parallel):** phenomenology reliability studies + claim thresholds (§14).

---

## 14. Public-claims & phenomenology policy (the split)

```text
Public Claims and Research Ambition

Public-facing descriptions SHALL use honest functional labels only.
No deployment surface SHALL claim sentience, phenomenal consciousness,
or moral patienthood without pre-specified evidentiary thresholds being met.

Internally, the project MAY pursue machine phenomenology as a research north-star:
the goal is to determine whether increasingly integrated, persistent, self-modeling,
and introspectively grounded systems justify stronger claims over time.

Research ambition SHALL NOT be interpreted as deployment claim.
```

Treated as a high-risk scientific hypothesis, not branding. Near-term research targets: reliable criteria for introspective report-grounding, state-to-report faithfulness, self-model continuity, and robustness of internal-state awareness under intervention (concept-injection / observer-based). Anthropic's introspection work suggests "there is something there," but nowhere near enough for public consciousness claims. Posture: **investigate aggressively, claim conservatively.**

---

## 15. Open questions for review

1. **Manifold dimensionality** — is the 9-axis set right, or start VAD-only and grow? Which axes are load-bearing for beneficial control changes?
2. **Thresholds & launch ceiling** — `θ_vote/θ_hold/θ_veto`, salience weights `w1..w10`, `HN_AUTHORITY_MAX=hold` at launch with `veto` behind A/B?
3. **Persistence store** — SQLite (consistent with `conviction_ledger.py`) vs JSON checkpoint; and graph store for scars (SQLite-backed adjacency vs a real graph lib)?
4. **Drive set & personality defaults** — the 8 core drives + the default shipped "character" vector.
5. **Instinct hot-path budget** — acceptable per-subtask ms budget; which matchers are hot-path vs teardown.
6. **Society cost** — rate-limit / budget for spawning opposing critics; kill criteria.
7. **Operator meta-authority surface** — Discord-only, or also a web control plane; what requires ratification vs immediate effect.
8. **Phase sizing** — is Phase 2 (bridge refactor + authority + operator layer) one plan or two? Is Phase 3 (instinct+scar) one plan or split (streaming vs graph)?

---

## 16. Why this is novel

The individual pieces exist in the 2026 literature — conviction/calibration, persona vectors, appraisal emotion, dimensional affect, persistent identity, multi-agent reflexion, metacognitive triage, streaming pattern matching, graph memory. **The combination does not exist anywhere:** a *continuous, learned, operator-governed* machine psychology — extended affect manifold + algorithmic streaming instinct + scar-tissue failure graph + 8-drive homeostat with emergent human-nature loops + global-workspace arbitration + a 5-cap earned-authority gate with constitutional operator sovereignty — that (a) is legible in real time and shows receipts, and (b) actually steers the control flow of an autonomous software-engineering agent across orchestrator, inventor, executor, and society, while keeping the verifier sacrosanct. It is the direct, principled answer to the know-act gap the field just named, applied to a real production agent rather than a benchmark. Done right, 9to5 becomes both more machine-honest and more behaviorally alive; done wrong, it stays "a clever dashboard with feelings pinned to it like stickers on a laptop." This spec is the plan for doing it right.
