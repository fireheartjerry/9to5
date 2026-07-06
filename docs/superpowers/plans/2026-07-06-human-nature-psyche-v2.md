# Human-Nature Psyche v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn 9to5's advisory-only human-nature layer into a continuous, operator-governed machine psychology with earned control authority — implemented phase by phase, every module dark-flagged, TDD-tested, size-audited, and byte-identical when `HUMAN_NATURE_ENABLED=0`.

**Architecture:** New pure modules under `human_nature/` (continuous affect manifold, 8-drive homeostat, 5-tier authority gate, streaming instinct + scar-tissue graph, operator meta-authority) plus a refactor of `human_nature_bridge.py` into a package of thin, gated couplings into the run loop. Every faculty is a pure projection over a serializable `SelfState`; every coupling is best-effort, additive, and gated. Verifier verdict is never read or altered.

**Tech Stack:** Python 3.11/3.12, stdlib-first (mirrors existing `human_nature/` modules), SQLite via `closing()` for persistence, pytest. Config through `platform_core/app_config/epic_flags.py`. Full design in `docs/superpowers/specs/2026-07-06-human-nature-psyche-v2-design.md`.

**House rules (apply to EVERY task):**
- Every new module gets the standard `@AI-MAP v1` docstring header (see `.claude/rules/modularity.md`) and `from __future__ import annotations`.
- Size budget: files ≤450 lines, functions ≤70 lines (`python tools/size_audit.py` must show zero `must_split`).
- Constants ALL_CAPS, variables snake_case, functions camelCase (global convention).
- New behavior gated behind a config flag defaulting via `FULL_STACK`; `HUMAN_NATURE_ENABLED=0` ⇒ no-op.
- TDD: failing test → run-fails → minimal impl → run-passes → commit. Tests under `tests/human_nature/`.
- After adding/renaming modules: `python tools/repo_map.py` (regenerates `AGENTS.md`).
- Run `python tools/dev.py check <file>` for focused validation; `python tools/dev.py fast` before finishing a phase.
- Preserve all existing public names as re-exports when splitting a module.

---

## Phase 0 — Foundation & persistence

Delivers cross-run durability + the run-event stream + audit schema. No behavior change.

### Task 0.1: Config flags for the whole program

**Files:**
- Modify: `platform_core/app_config/epic_flags.py`
- Test: `tests/human_nature/test_hn_config.py`

- [ ] **Step 1:** Add the new flags (all default via the existing `_fullStack()` for booleans, sensible numeric defaults) alongside the current `HN_*` block:
  - Booleans (default `_fullStack()`): `HN_MANIFOLD`, `HN_INSTINCT`, `HN_DRIVES`, `HN_MOOD_PERSIST`, `HN_PERSONALITY`, `HN_PLAN_AUTHORITY`, `HN_EXEC_AUTHORITY`, `HN_VERIFY_DEEPEN`, `HN_SOCIETY_TRIGGER`, `HN_INVENTOR_COUPLING`.
  - Floats: `HN_THETA_VOTE` (0.72), `HN_THETA_HOLD` (0.85), `HN_THETA_VETO` (0.95), `HN_MOOD_DECAY` (0.15), `HN_SCAR_DECAY` (0.1), `HN_SCAR_MATCH_THRESHOLD` (0.6).
  - Ints/str: `HN_MAX_HOLDS` (2), `HN_HOLD_TIMEOUT_S` (120), `HN_MAX_VERIFY_DEEPEN` (2), `HN_DEBATE_RATE_LIMIT` (1), `HN_AUTHORITY_MAX` ("hold"), `HN_OPERATOR_CEILING` ("veto"), `HN_INSTINCT_HOTPATH_BUDGET_MS` (25).
  - Re-export each through `config` the same way existing `HN_*` flags are surfaced.
- [ ] **Step 2:** Test that each new flag is readable via `config.<NAME>` and that setting the env var overrides it (mirror the existing `test_hn_config.py` patterns; monkeypatch env + reload).
- [ ] **Step 3:** Run `pytest tests/human_nature/test_hn_config.py -v` → PASS. Commit.

### Task 0.2: `psyche_store.py` — durable cross-run persistence

**Files:**
- Create: `human_nature/psyche_store.py`
- Test: `tests/human_nature/test_psyche_store.py`

Public API (pure-ish; all I/O confined here):
```python
def open_store(db_path: str | None = None) -> "PsycheStore"        # closing()-based SQLite wrapper
def load_psyche(store, project_key: str) -> dict                    # {} when absent
def save_psyche(store, project_key: str, state: dict) -> None       # upsert JSON blob + schema col
```
- [ ] **Step 1:** Failing test: `save_psyche` then `load_psyche` round-trips a nested dict (mood/drives/personality/scars); missing key → `{}`; a second open on the same path sees the write (Windows file-lock safe via `closing()`).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement using `sqlite3` + `contextlib.closing`, JSON-encoded blob keyed by `project_key`, `schema_version` column. DB path from `config` (STATE_DIR) with `db_path` override. **Step 4:** Run → PASS. **Step 5:** `python tools/repo_map.py`; commit.

### Task 0.3: `self_state.py` schema v2 + migration

**Files:**
- Modify: `human_nature/self_state.py`
- Test: `tests/human_nature/test_self_state.py` (extend)

- [ ] **Step 1:** Failing tests: `new_self_state()` includes new keys `affect_manifold` (9-axis dict, all 0.0), `drives` ({} — filled Phase 4), `personality_ref`, `mood`, `scars_ref`; a `migrate(ss)` upgrades a v1 dict (bumps `schema` 1→2, adds missing keys, preserves existing `competence`/`affect`/`morale`).
- [ ] **Step 2:** FAIL. **Step 3:** Bump `SCHEMA_VERSION=2`; extend `new_self_state()`; add `migrate(ss)`. Keep existing keys + functions unchanged (back-compat). **Step 4:** PASS (existing tests still green). **Step 5:** repo_map; commit.

### Task 0.4: Run-event stream + audit schema

**Files:**
- Create: `human_nature/run_events.py`
- Test: `tests/human_nature/test_run_events.py`

Public API:
```python
EVENT_TYPES: frozenset[str]   # PLAN_SCOPE_EXPANDED, PATCH_LARGE, TESTS_SKIPPED, VERIFIER_WARNING,
                              # RETRY_SAME_STRATEGY, CONFIDENCE_HIGH, REGRESSION_FOUND, TOOL_TIMEOUT,
                              # DIFF_EXPANDING, NO_PROGRESS_LOOP, SUBTASK_STARTED, ...
def new_event_log() -> list                                  # ordered event list held in state.meta
def record_event(log: list, etype: str, **fields) -> None    # append {type, seq, fields}; ignore unknown etype
def event_sequence(log: list) -> list[str]                   # ["PATCH_LARGE","TESTS_SKIPPED",...] for matching
```
- [ ] **Step 1:** Failing test: recording known types appends in order; unknown type is dropped (best-effort); `event_sequence` returns the type string list. **Step 2:** FAIL. **Step 3:** Implement (pure, stdlib). **Step 4:** PASS. **Step 5:** repo_map; commit.

### Task 0.5: Wire persistence into lifecycle (no behavior change)

**Files:**
- Modify: `platform_core/orchestration/human_nature_bridge.py` (`runPreambleHooks`, `runTeardownHooks`)
- Test: `tests/orchestration/test_human_nature_bridge.py` (extend)

- [ ] **Step 1:** Failing test: with `HUMAN_NATURE_ENABLED=1`, preamble loads persisted psyche into `state.meta["self_state"]` and teardown checkpoints it (use a temp store path); with `HUMAN_NATURE_ENABLED=0`, neither fires and behavior is byte-identical. **Step 2:** FAIL. **Step 3:** Add best-effort load/save calls guarded by the master flag + `HN_MOOD_PERSIST`. **Step 4:** PASS + `python tools/dev.py fast`. **Step 5:** repo_map; commit. **End Phase 0.**

---

## Phase 1 — Continuous affect manifold

### Task 1.1: `affect_manifold.py` — state + update law + attractors + hysteresis

**Files:**
- Create: `human_nature/affect_manifold.py`
- Test: `tests/human_nature/test_affect_manifold.py`

Axes: `AXES = ("valence","arousal","dominance","certainty","novelty","agency","tension","social_exposure","cognitive_load")`. Public API:
```python
def new_manifold() -> dict                       # all axes 0.0
def update(a: dict, appraisal: dict, mood: dict, drive_pressure: dict, scars: dict,
           personality_baseline: dict, inertia: dict | None = None) -> dict   # A_(t+1), clipped [-1,1]
def decay(a: dict, rate: float) -> dict          # toward baseline
```
- [ ] **Step 1:** Failing tests: `update` moves each axis toward `baseline + Δ` scaled by (1−inertia); high-inertia axis barely moves, low-inertia axis moves a lot; output clipped to [-1,1]; empty inputs → returns baseline (no NaN); pure (does not mutate inputs). **Step 2:** FAIL. **Step 3:** Implement the state-space law `A' = clip(Λ·A + (I-Λ)·(P + ΔA) + attractor(A))` with a diagonal inertia dict (per-axis default) and a simple bounded attractor pulling extreme values slightly toward baseline. **Step 4:** PASS. **Step 5:** repo_map; commit.

### Task 1.2: `prototypes.py` — smooth emotion projection + hysteresis

**Files:**
- Create: `human_nature/prototypes.py`
- Test: `tests/human_nature/test_prototypes.py`

```python
PROTOTYPES: dict[str, dict]    # label -> anchor point in manifold space (frustration, anxiety,
                               # curiosity, boredom, satisfaction, neutral)
def mixture(a: dict) -> dict[str, float]         # RBF activation per prototype, normalized (sums→1)
def dominant(a: dict, prev: str | None = None, theta_on=0.5, theta_off=0.35) -> str  # hysteretic label
```
- [ ] **Step 1:** Failing tests: a manifold near the "frustration" anchor yields `dominant=="frustration"`; mixture is a normalized dict; hysteresis: once in "anxiety", a small drift that would fall between `theta_off` and `theta_on` stays "anxiety" (no flicker); neutral when far from all anchors. **Step 2:** FAIL. **Step 3:** Implement RBF/Mahalanobis-lite (Euclidean with per-axis scale) + asymmetric enter/exit thresholds. **Step 4:** PASS. **Step 5:** repo_map; commit.

### Task 1.3: Emotion coupling reads the manifold (behind `HN_MANIFOLD`)

**Files:**
- Modify: `human_nature/emotions.py`, `platform_core/orchestration/human_nature_bridge.py` (`_affectToLabel` / `emotionAdvisory`)
- Test: `tests/human_nature/test_emotions.py`, `tests/orchestration/test_human_nature_bridge.py`

- [ ] **Step 1:** Failing test: when `HN_MANIFOLD=1`, the emotion label used by `emotionAdvisory` comes from `prototypes.dominant(manifold)` rather than the legacy `_affectToLabel(affect)` PAD rule; when `HN_MANIFOLD=0`, the legacy path is byte-identical. **Step 2:** FAIL. **Step 3:** Branch on the flag; keep legacy path intact for A/B. **Step 4:** PASS + `tools/dev.py fast`. **Step 5:** repo_map; commit. **End Phase 1.**

---

## Phase 2 — Authority ladder + operator meta-authority

### Task 2.1: `authority.py` — 5-tier ladder

**Files:** Create `human_nature/authority.py`; Test `tests/human_nature/test_authority.py`.

```python
TIERS = ("cosmetic","soft","vote","hold","veto")
def band(conviction: float) -> str                       # threshold bands from HN_THETA_*
def earned_ceiling(track: dict) -> str                   # extends autonomy.ceiling to 5 tiers
def resolve(conviction, track, domain_ceiling, operator_ceiling,
            safety_ceiling, verifier_ceiling) -> str     # min over all five on TIERS ordering
```
- [ ] **Step 1:** Failing tests: `band` maps conviction to the right tier at the θ boundaries; `resolve` returns the `min` tier across all five caps; cold-start (`track.total < 5`) ⇒ earned ceiling cosmetic; a `veto`-band conviction capped to `hold` when `HN_AUTHORITY_MAX="hold"`. **Step 2:** FAIL. **Step 3:** Implement (compose `autonomy.TIERS` semantics, extend to 5). **Step 4:** PASS. **Step 5:** repo_map; commit.

### Task 2.2: `operator_authority.py` — constitutional caps

**Files:** Create `human_nature/operator_authority.py`; Test `tests/human_nature/test_operator_authority.py`.
```python
def operator_ceiling(faculty: str, domain: str, charter: dict) -> str
def safety_ceiling(domain: str) -> str          # hard caps: unknown->cosmetic, verifier domain->cosmetic
def verifier_invariance_ceiling(action: str) -> str  # any verdict-touching action -> cosmetic; additive-> hold
```
- [ ] **Step 1:** Failing tests: a verdict-altering action resolves to cosmetic (can never touch the verifier); an additive verify-deepen action may reach `hold`; operator charter cap lowers a faculty's ceiling. **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS. **Step 5:** repo_map; commit.

### Task 2.3: Refactor `human_nature_bridge.py` → package (preserve all public names)

**Files:** Create `platform_core/orchestration/human_nature_bridge/` package (`__init__.py` facade + `authority_gate.py`, `lifecycle.py`, `planning.py`, `execution.py`, `verification.py`, `society.py`, `instinct.py`, `inventor.py`); move logic out of the old single module. Test: existing `tests/orchestration/test_human_nature_bridge.py` must pass unchanged.
- [ ] **Step 1:** Confirm the existing test suite for the bridge is green (baseline). **Step 2:** Create the package; `__init__.py` re-exports every current public function (`midRunInstinct`, `opinionAdvisory`, `emotionNudge`, `emotionAdvisory`, `attemptSignals`, `preActRouting`, `biasEffort`, `runPreambleHooks`, `runTeardownHooks`). Move each function into the domain module; import into facade. **Step 3:** `authority_gate.resolveTier(faculty, domain, conviction, state, action)` composes `authority.resolve` + `operator_authority.*`. **Step 4:** Run the full bridge test suite → PASS unchanged; `tools/dev.py fast`. **Step 5:** repo_map; commit. **End Phase 2.**

### Task 2.4: Soft-tier bidirectional modulation

**Files:** Modify `human_nature_bridge/execution.py` (`biasEffort`), Test extend.
- [ ] **Step 1:** Failing test: at `soft` tier with a "deliberate/careful" routing and earned ceiling ≥ soft, `biasEffort` can RAISE effort one tier (bounded), not only lower; capped at ladder ends; `HN_EXEC_AUTHORITY=0` ⇒ legacy behavior. **Step 2:** FAIL. **Step 3:** Make `biasEffort` bidirectional via the authority gate. **Step 4:** PASS. **Step 5:** commit.

---

## Phase 3 — Streaming instinct + scar-tissue graph

### Task 3.1: `instinct_signal.py` — schema
Create `human_nature/instinct_signal.py`; Test `tests/human_nature/test_instinct_signal.py`. Dataclass `InstinctSignal{motif_id, match_type, confidence, severity, expected_loss_if_ignored, recommended_action, evidence_events, matched_history_refs, authority_request}` + `to_dict`/`from_dict` + validation of enum fields. TDD: construct, round-trip, reject bad `match_type`/`recommended_action`. Commit.

### Task 3.2: `instinct_stream.py` — streaming motif matcher
Create `human_nature/instinct_stream.py`; Test `tests/human_nature/test_instinct_stream.py`.
```python
def build_matcher(motifs: list[list[str]]) -> "Matcher"      # Aho-Corasick over event-type alphabet
def match_prefix(seq: list[str], motif: list[str]) -> float  # KMP/Z prefix-overlap score in [0,1]
def scan(matcher, seq: list[str]) -> list[dict]              # {motif_id, match_type, score}
def near_duplicate(seq_a, seq_b) -> float                     # rolling-hash / LCS ratio
```
TDD: exact motif in stream detected; a prefix of a dangerous motif scored high before completion; a mutated (one-insertion) motif still detected via near_duplicate/LCS; unrelated stream scores ~0. Hot-path cheap (no LLM). Commit.

### Task 3.3: `scar_graph.py` — durable failure graph + algorithms
Create `human_nature/scar_graph.py`; Test `tests/human_nature/test_scar_graph.py`.
```python
def new_graph() -> dict                                  # {nodes, edges} adjacency
def add_motif(g, motif_id, **attrs) -> None
def link(g, src, dst, relation, weight=1.0) -> None
def recovery_path(g, failure_node) -> list               # Dijkstra shortest recovery
def toxic_patterns(g, k=5) -> list                       # PageRank/centrality top-k
def loops(g) -> list                                     # SCC (Tarjan) circular-failure detection
def decay(g, disconfirmed: list[str], rate: float) -> None  # lower scar weight on verified success
```
TDD: add motifs+edges; `recovery_path` returns the min-weight recovery route; `loops` finds a replan→noprogress cycle; `decay` reduces disconfirmed scar weights; PageRank ranks a hub motif top. Pure (persistence via `psyche_store`). Commit.

### Task 3.4: `motif_mining.py` — offline mining (teardown)
Create `human_nature/motif_mining.py`; Test `tests/human_nature/test_motif_mining.py`. `mine_frequent(sequences, min_support) -> list[list[str]]` (frequent subsequence mining) + `anomaly_score(seq, success_seqs) -> float`. TDD: a subsequence present in ≥min_support failed runs is mined; an off-distribution sequence scores anomalous. Commit.

### Task 3.5: `human_nature_bridge/instinct.py` — coupling
Modify `human_nature_bridge/instinct.py`; wire `midRunInstinct` (and a new per-subtask `instinctCheck`) to: read `state.meta` event log → `scan` motifs → `scar_graph` query → build `InstinctSignal` → feed manifold (↑tension/uncertainty via `affect_manifold.update`) → request authority via `authority_gate` (additive verify-deepen only) → surface receipts. Gated by `HN_INSTINCT`; `=0` no-op. TDD: a dangerous prefix in the event log produces a signal that raises manifold tension and requests (but the gate may cap) verification deepening; verifier verdict never read. Commit. **End Phase 3.**

---

## Phase 4 — Drives + rich salience

### Task 4.1: `drives.py` — 8 core drives + derived loops
Create `human_nature/drives.py`; Test `tests/human_nature/test_drives.py`.
```python
CORE = ("mastery","curiosity","coherence","economy","agency","commitment","integrity","recovery")
def new_drives() -> dict                                 # each {level:0.5, setpoint}
def update(d, outcome_features: dict) -> dict            # homeostatic update from run outcomes
def pressure(d) -> dict                                  # deficit->pressure per drive
def derived(d, standards, attribution, memory) -> dict   # pride/shame/attachment/territoriality/obsession/...
```
TDD: a verified success raises `mastery` toward setpoint; deficit yields positive pressure; `derived` computes shame from integrity-violation+self-attributed-failure+visibility; all outputs bounded. Commit.

### Task 4.2: Rich 10-term salience in `workspace.py`
Modify `human_nature/workspace.py`; Test extend. Add `salience(item: dict, weights: dict) -> float` summing the 10 terms (conviction, expected_loss, uncertainty, novelty, scar_tissue, unresolved_tension, recency, operator_priority, risk, competence_gap). TDD: higher scar/expected_loss raises salience; operator_priority biases within provided range; deterministic ordering. Commit. **End Phase 4.**

---

## Phase 5 — Conflict + structured society

### Task 5.1: `conflict.py` — dissonance + routing
Create `human_nature/conflict.py`; Test `tests/human_nature/test_conflict.py`.
```python
def dissonance(opinion, intuition, instinct, self_model_calibration) -> float
def route(dissonance_level: float, budget: dict) -> str   # "debate" | "deepen_verify" | "replan" | "none"
```
TDD: disagreement among faculties raises dissonance; high dissonance + budget routes to "debate"; rate-limit exhausted routes to "deepen_verify". Commit.

### Task 5.2: Society trigger coupling
Modify `human_nature_bridge/society.py`; wire high dissonance → spawn a heterogeneous opposing lens → `coordinator.resolveContested()` (activates `society/debate.py`). Gated `HN_SOCIETY_TRIGGER`, rate-limited `HN_DEBATE_RATE_LIMIT`. TDD (with a fake coordinator): dissonance above threshold calls resolveContested with ≥2 distinct roles; below threshold no-op; disabled flag no-op. Commit. **End Phase 5.**

---

## Phase 6 — Vote / hold / verify-deepen couplings

### Task 6.1: Plan-gate vote (`planning.py`)
Extend `opinionAdvisory` → at `vote` tier cast a weighted, logged vote that flags/down-ranks a subtask (never removes it); at `hold` tier request a re-plan (bounded `HN_MAX_HOLDS`, timeout `HN_HOLD_TIMEOUT_S`, auto-release). TDD: vote recorded; hold bounded + auto-released; D3 goal domain never blocks. Commit.

### Task 6.2: Verifier deepen-request (`verification.py`)
New additive-only path: at `hold` tier the psyche appends an extra verification tier/adversarial pass request to `state.meta`; the verifier verdict is never read. Gated `HN_VERIFY_DEEPEN`, capped `HN_MAX_VERIFY_DEEPEN`. TDD: request appended + capped; verdict untouched; disabled no-op. Commit. **End Phase 6.**

---

## Phase 7 — Inventor coupling (conditional)

### Task 7.1: `inventor.py` coupling (no-op when inventor absent)
Modify `human_nature_bridge/inventor.py`; when `INVENTOR_MODE_ENABLED` and the inventor package importable, map Curiosity/boredom → exploration/QD budget, novelty → finder selection, personality boldness → risk band, conviction → candidate promotion gate. When the package is absent, every function is a clean no-op. TDD: with a fake inventor seam, budgets scale with curiosity; with the seam absent, no-op + no import error. Commit. **End Phase 7.**

---

## Phase 8 — Personality + consolidation + charter

### Task 8.1: `personality.py` (monitor-not-puppeteer)
Create `human_nature/personality.py` wrapping `character_vector.py`; versioned trait vector setting drive/mood setpoints, risk band, argument style; persona-vector hooks are offline/diagnostic only (no hot-path steering). TDD: setpoints derive from traits; a proposed change is propose-not-apply (needs ratify). Commit.

### Task 8.2: Consolidation proposals
Extend `consolidation.run_cycle` to propose personality-dial + drive-setpoint + scar-decay updates (propose-not-apply, charter-ratified). TDD: proposals produced, never auto-applied without ratify. Commit. **End Phase 8.**

---

## Phase 9 — Psyche surface (Discord cog + receipts)

### Task 9.1: `notifications/psyche_cog.py`
Wire the tested `human_nature/psyche_commands.py` routers to a real cog (`!psyche`, `!dial`, `!charter`, `!why`, `!freeze`). Read-only live readout of manifold + dominant prototype gloss + drives/pressures + top instinct signals + authority ceilings + last-authority receipts. Guarded by the master flag. TDD: router→cog rendering with a fake Discord ctx (follow existing cog test patterns). Commit. **End Phase 9.**

---

## Phase 10 — Evaluation, A/B, activation

### Task 10.1: Custom eval suites (5)
Create `tests/human_nature/eval/` with the five suites (Affect-to-Action Monotonicity, Scar-Tissue Generalization, Habit Compression, Operator Sovereignty, Phenomenology Honesty). Each asserts a bounded, monotonic, or invariant property. Commit.

### Task 10.2: A/B wiring + activation defaults
Ensure `ab_harness.record_run` captures the new metrics (beneficial-hold rate, verify-deepen precision, regression-prevention). Confirm every coupling honors its flag and the dark-launch equivalence test still passes with the master flag off. `python tools/dev.py fast` + `python tools/size_audit.py` (zero must_split) + `python tools/repo_map.py`. Commit. **End Phase 10.**

---

## Global self-review checklist (run before opening the PR)
- [ ] `HUMAN_NATURE_ENABLED=0` ⇒ byte-identical run (dark-launch equivalence test green).
- [ ] Verifier verdict never read/altered anywhere in `human_nature*` (grep + test).
- [ ] `python tools/size_audit.py` → zero `must_split`.
- [ ] `python tools/repo_map.py` → `AGENTS.md` drift test green.
- [ ] `python tools/dev.py fast` green.
- [ ] Every new module has the `@AI-MAP v1` header + a mapped test.
- [ ] All existing `tests/human_nature/` + `tests/orchestration/test_human_nature_bridge.py` still green.
