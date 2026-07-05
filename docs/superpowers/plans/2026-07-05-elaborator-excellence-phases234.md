# Elaborator Excellence — Phases 2–4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) tracking. Builds on Phase 1 (committed on `feat/elaborator-excellence`).

**Goal:** Complete spec sections §3d, §3b(band), §4(Layer-2), and §7 (the full pipeline + world-model lookahead + deferral) — all behind flags, default OFF, byte-identical when off.

**Architecture:** Additive sub-modules in `agents/planning/elaborator/` reusing real 9to5 machinery (memory/retrievals embedding index, adversary review, QD archive, portfolio optimizer, society debate, SIE). Two pieces (Stage D SIE-evolve, §7.5 Claude deferral) have no existing seam and land as defensive, degrade-to-local hooks. Public API of `elaborate()`/`extractUniverse()` stays frozen.

**Tech Stack:** Python 3.12, unittest, `llm_io` seam, `platform_core/app_config` flag registry.

**Spec:** `docs/superpowers/specs/2026-07-05-elaborator-excellence-design.md`

---

## Flags to add (Task P0 — all in `EpicFlags`, ship dark)

Pattern (confirmed): `NAME: bool = _F(default_factory=lambda: _envBool("NAME", False))` in `platform_core/app_config/epic_flags.py`. Surfaces as `config.NAME` via PEP 562.

- `ELABORATOR_PRECEDENT_ENABLED` (bool, False) — §3d CBR grounding.
- `ELABORATOR_BESTOFN_ENABLED` (bool, False) — §7 A′/A/B candidate pipeline.
- `ELABORATOR_LOOKAHEAD_ENABLED` (bool, False) — §7 B′ world-model prediction.
- `ELABORATOR_DEFER_ENABLED` (bool, False) — §7.5 Claude escalation.
- `ELABORATOR_CANDIDATES_MAX` (int, 5) — `_envInt`, upper bound on best-of-N.

Reused existing flags (no change): `SOCIETY_ENABLED` (Layer-2 judge + debate), `QD_ARCHIVE_ENABLED` (diversity), `PORTFOLIO_OPTIMIZER_ENABLED` (select), `SIE_FORCE_WEEKLY`/`SIE_KILL_SWITCH` (evolve). Test: assert each new flag ships dark in `tests/platform/test_epic_flags_config.py`.

---

# PHASE 2 — precedent (§3d) + calibrated band (§3b) + Layer-2 judge (§4)

## Task P2.1: `precedent.py` — case-based-reasoning grounding

**Files:** Create `agents/planning/elaborator/precedent.py`; Test `tests/orchestration/test_elaborator_precedent.py`.

Reuses (real signatures): `memory.retrievals.core.retrieve(goal, title="", *, k=None, db_path=None) -> list[dict]` (top-k similar PASSED past goals), `retrieve_failures(goal, title="", *, k=None) -> list[dict]` (similar FAILED), `lessons_block(goal, title="", *, db_path=None) -> str`. All are best-effort and return `[]`/`""` when the embedding index is empty/unavailable (cold start).

Public API:
```python
def precedentBlock(goal: str, *, k: int = 3, retrieve_fn=None, fail_fn=None) -> str:
    """Top-k similar past (goal->outcome) exemplars + anti-patterns as a compact prompt
    block, or "" when nothing is retrievable. retrieve_fn/fail_fn are injectable seams
    (default: memory.retrievals.core.retrieve / retrieve_failures) so tests run offline."""
```
Behavior: call `retrieve_fn(goal, k=k)`; for each hit format one line `- past success: {title} (score {score:.2f})`. Call `fail_fn(goal, k=2)`; format `- avoid (past failure): {title}`. Join under headers "PRECEDENT (how similar goals resolved before):". Wrap each seam call in try/except → on any error contribute nothing (best-effort). Empty retrieval → "".

Tests (inject fakes, never touch real index):
- `precedentBlock` with a fake `retrieve_fn` returning `[{"title":"add flag","score":0.9}]` → block contains "add flag" and "PRECEDENT".
- fake returning `[]` and `fail_fn` `[]` → returns "".
- `retrieve_fn` raising → returns "" (no crash).
- failures present → block contains "avoid (past failure)".

- [ ] Write tests → run FAIL → implement → run PASS (4 tests) → commit `feat(elaborator): case-based-reasoning precedent grounding (§3d)` (files: precedent.py + test).

## Task P2.2: `uncertainty.py` — calibrated conformal risk band (§3b)

**Files:** Create `agents/planning/elaborator/uncertainty.py`; Test `tests/orchestration/test_elaborator_uncertainty.py`.

No LLM call. Pure function turning objective signals into a distribution-free band (not self-report).

Public API:
```python
def riskBand(*, path_verified: bool, precedent_support: bool) -> str:
    """Return 'low' or 'elevated'. An inferred assumption is 'low' only when its referenced
    paths verified (§5) AND precedent corroborates it; otherwise 'elevated'. Distribution-free
    proxy, deliberately NOT the model's self-reported confidence (RLHF miscalibrates that)."""

def runUncertainty(*, elevated_count: int, objective_spread: float, precedent_hits: int,
                   threshold: int = 2) -> dict:
    """Aggregate run-level uncertainty. Returns {'defer': bool, 'score': int, 'reasons': [...]}.
    defer=True when elevated_count >= threshold OR (objective_spread < 0.05 AND precedent_hits == 0)."""
```
Tests: `riskBand(path_verified=True, precedent_support=True)` == 'low'; any False → 'elevated'. `runUncertainty(elevated_count=2, ...)` → defer True; `runUncertainty(elevated_count=0, objective_spread=0.2, precedent_hits=3)` → defer False; the no-precedent+flat-spread case → defer True with a reason.

- [ ] Write tests → FAIL → implement → PASS (5 tests) → commit `feat(elaborator): calibrated conformal risk band + deferral decision (§3b)`.

## Task P2.3: Layer-2 semantic judge (§4) — reuse adversary review

**Files:** Modify `agents/review/adversary_review.py` (add `'elaboration'` to `REVIEW_GUIDANCE` dict ~line 77); create `agents/planning/elaborator/judge.py`; Test `tests/orchestration/test_elaborator_judge.py`.

Real: `review(subtask_title, trigger_reason, executor_output, *, ollama_chat=None, goal='', review_type='subtask') -> dict{verdict, concerns, must_fix, ...}`. `systemFor(review_type)` reads `REVIEW_GUIDANCE[review_type]`.

P2.3a — add to `REVIEW_GUIDANCE`:
```python
"elaboration": (
    "You are judging an ELABORATED SPEC (not code). Flag: ungrounded file paths, "
    "objectives that don't match the goal, missing acceptance criteria, and over-broad "
    "scope. Approve if the spec is grounded and buildable."
),
```
Test in existing `tests/orchestration/test_adversary_review.py` (or the judge test): `systemFor("elaboration")` contains "ELABORATED SPEC".

P2.3b — `judge.py`:
```python
def judgeElaboration(spec_body: str, goal: str, *, chat=None) -> dict:
    """Advisory semantic judge of an elaborated spec via the adversary review seam.
    Returns the review dict (verdict/concerns/...). Never raises; returns
    {'verdict':'unreviewed'} on any failure. chat is the injectable ollama seam."""
```
Implement by calling `adversary_review.review(subtask_title="elaboration", trigger_reason="elaboration-quality", executor_output=spec_body, ollama_chat=chat, goal=goal, review_type="elaboration")` in a try/except.

Tests: inject a `chat` double → `judgeElaboration` returns a dict with a `verdict` key; a raising chat → `{'verdict':'unreviewed'}`.

- [ ] Write tests → FAIL → implement (P2.3a + P2.3b) → PASS → commit `feat(elaborator): Layer-2 semantic judge via adversary review (§4)`.

## Task P2.4: Wire Phase 2 into `core.py` (flag-gated, byte-identical off)

**Files:** Modify `agents/planning/elaborator/core.py`; Test append to `tests/orchestration/test_elaborator.py`.

Wiring (all inside `if config.ELABORATOR_EXCELLENCE_ENABLED` and the specific sub-flag):
- In `elaborate()`, after the vague-goal bundle block: if `config.ELABORATOR_PRECEDENT_ENABLED`, `pb = precedent.precedentBlock(goal_raw); if pb: user += "\n\n"+pb`.
- After self-review produces `inferred`: if `config.SOCIETY_ENABLED` and `inferred`, call `judge.judgeElaboration(out, goal_raw, chat=chat)`; if verdict == "challenged", append `\n\n# Review Note\n{concerns}` to `out` (advisory, never blocks).
- Keep everything guarded so flag-off/sub-flag-off is byte-identical.

Tests: with master ON + `ELABORATOR_PRECEDENT_ENABLED` ON + injected precedent seam (monkeypatch `precedent.precedentBlock`) → "PRECEDENT" reaches prompt. With sub-flags OFF → not present. Byte-identical test still passes.

- [ ] Write tests → FAIL → implement → PASS → commit `feat(elaborator): wire precedent + Layer-2 judge (Phase 2, flag-gated)`.

---

# PHASE 3 — the §7 candidate pipeline (A′ → A → B → C → D)

## Task P3.1: `candidates.py` — adaptive N + generate + portfolio select

**Files:** Create `agents/planning/elaborator/candidates.py`; Test `tests/orchestration/test_elaborator_candidates.py`.

Real reuse: `platform_core.orchestration.portfolio_optimizer.optimize(candidates, *, deps=(), conflicts=(), weight_fn=None, safe_only=False) -> PortfolioSelection(selected_candidate_ids, demoted_candidate_ids, ..., objective_value)`; each candidate needs an `id`. `QDElite`/`QDArchive` (invention_types + qd_archive) for diversity (optional, behind `QD_ARCHIVE_ENABLED`).

Public API (pure orchestration over injected seams — no direct Ollama in tests):
```python
STANCES = ("minimal-scope", "thorough", "risk-averse")

def budgetFor(goal: str, *, is_vague: bool, precedent_hits: int, max_n: int) -> int:
    """§7 A': compute-optimal N. Precise goal -> 1; vague + no close precedent -> up to max_n."""

def generate(goal, work_dir, *, n, gen_fn) -> list[dict]:
    """Call gen_fn(goal, work_dir, stance) for the first n STANCES; return
    [{'id': stance, 'stance': stance, 'spec': text}, ...]. gen_fn is injectable."""

def selectBest(candidates: list[dict], *, weight_fn) -> dict:
    """§7 B: portfolio optimize by weight_fn(candidate)->float; return the winning candidate.
    Falls back to max(weight_fn) sort if PORTFOLIO_OPTIMIZER_ENABLED is off or optimize errors."""

def meritWeight(candidate: dict, *, groundedness=0.0, precedent=0.0, predicted=0.0,
                elevated=0) -> float:
    """§7 B weight_fn: predicted_success + groundedness + precedent - 0.5*elevated."""
```
`budgetFor`: `1` if not is_vague; else `min(max_n, 2 + (precedent_hits == 0) * 2 + 1)` clamped `[1, max_n]`. Keep deterministic/simple.

Tests (all offline via injected `gen_fn`/`weight_fn`): `budgetFor` precise→1, vague+0 precedent→>=3, respects max_n cap; `generate` with a fake gen_fn returns n candidates with right ids; `selectBest` picks highest weight; `meritWeight` monotonic in predicted/groundedness/precedent and decreasing in elevated.

- [ ] Write tests → FAIL → implement → PASS → commit `feat(elaborator): candidate pipeline — adaptive N + portfolio select (§7 A'/A/B)`.

## Task P3.2: `evolve.py` — Stage D fitness recording seam (defensive)

**Files:** Create `agents/planning/elaborator/evolve.py`; Test `tests/orchestration/test_elaborator_evolve.py`.

HONEST NOTE: there is no existing "elaboration outcome" ledger seam (confirmed). This task lands the RECORDING FUNCTION + a clear extension point; the orchestrator-loop call site is a documented seam (a follow-up wires it post-run). It degrades to a no-op when SIE is off/unavailable — no behavior change.

```python
def recordElaborationOutcome(goal: str, stance: str, *, clean_run: bool, store_fn=None) -> bool:
    """Best-effort: record (goal, winning stance, clean_run) so SIE promotion can later learn
    which stance wins for which goal-family. store_fn injectable (default: a thin wrapper over
    memory.retrievals.core.embed_and_store using stance+outcome in the title). Returns False and
    logs on any failure or when SIE_KILL_SWITCH is set. Never raises."""
```
Tests: injected `store_fn` receives the goal/stance/outcome and returns True → function returns True; `store_fn` raising → returns False (no crash); with `SIE_KILL_SWITCH` monkeypatched True → returns False without calling store_fn.

- [ ] Write tests → FAIL → implement → PASS → commit `feat(elaborator): Stage D elaboration-fitness recording seam (§7 D, defensive)`.

## Task P3.3: Wire Phase 3 pipeline into `core.py` (flag-gated)

**Files:** Modify `core.py`; Test append to `test_elaborator.py`.

When `config.ELABORATOR_EXCELLENCE_ENABLED and config.ELABORATOR_BESTOFN_ENABLED`: replace the single `elaborate` brain call with the candidate pipeline —
1. `n = candidates.budgetFor(goal_raw, is_vague=isVagueGoal(goal_raw), precedent_hits=<len of precedent>, max_n=config.ELABORATOR_CANDIDATES_MAX)`.
2. If `n == 1`: current single-shot path (unchanged).
3. Else: `cands = candidates.generate(goal_raw, work_dir, n=n, gen_fn=_stanceGen)` where `_stanceGen(goal, wd, stance)` builds the stance-flavored system prompt and calls `_chat`. `best = candidates.selectBest(cands, weight_fn=lambda c: candidates.meritWeight(c, groundedness=_ground(c), precedent=..., elevated=...))`. Use `best["spec"]` as `out`.
- `_ground(c)` reuses path_verify on any paths named — keep simple/deterministic.
- Debate (Stage C) is OPTIONAL and defensive: only if `config.SOCIETY_ENABLED` and the top-2 candidates' weights are within 5%, attempt `society.debate.runDebate` in a try/except to pick the winner; on any error keep the portfolio winner. (Given debate's blackboard coupling, this is best-effort — never block.)

Tests: `ELABORATOR_BESTOFN_ENABLED` OFF → single-shot unchanged (byte-identical). ON with n forced to a small value via injected budget and a scripted `chat` returning distinct specs per stance → `elaborate` returns one of the candidate specs; assert selection ran. Keep tests offline.

- [ ] Write tests → FAIL → implement → PASS → commit `feat(elaborator): wire best-of-N pipeline + optional debate (§7, flag-gated)`.

---

# PHASE 4 — world-model lookahead (§7 B′) + uncertainty deferral (§7.5)

## Task P4.1: `predict.py` — propose-simulate-score (§7 B′)

**Files:** Create `agents/planning/elaborator/predict.py`; Test `tests/orchestration/test_elaborator_predict.py`.

One shallow (1-step) brain call per candidate, grounded on the real snapshot. Own sub-flag `ELABORATOR_LOOKAHEAD_ENABLED` (default OFF even under master).

```python
def predictOutcome(spec_body: str, work_dir: str | None, *, chat=None) -> dict:
    """Imagine the executor's FIRST action on this spec. Returns
    {'likely_files': [...], 'likely_failure': str, 'predicted_success': float in [0,1]}.
    One llm_io call (want_json). Never raises; returns predicted_success=0.5 (neutral) on
    any failure so it can't block. chat injectable."""
```
System prompt: "Predict the IMMEDIATE consequence of an engineer executing this spec's first step. Output JSON {likely_files, likely_failure, predicted_success}." Parse via `llm_io.responseJson`; clamp `predicted_success` to [0,1]; default 0.5 on parse failure.

Tests (injected chat): valid JSON → parsed dict with clamped score; malformed → neutral 0.5; None resp → 0.5. Exactly one brain call.

- [ ] Write tests → FAIL → implement → PASS → commit `feat(elaborator): world-model lookahead predict.py (§7 B', dark)`.

## Task P4.2: `defer.py` — uncertainty-aware Claude escalation (§7.5, degrading)

**Files:** Create `agents/planning/elaborator/defer.py`; Test `tests/orchestration/test_elaborator_defer.py`.

HONEST NOTE: no reusable Claude seam in `llm_io` (executor uses `runClaude()` subprocess). So `defer.py` owns the DECISION (fully implemented + tested) and calls an injectable `escalate_fn`; the default `escalate_fn` is a thin, defensive wrapper that returns `None` (→ keep local candidate) unless a real Claude seam is provided. This matches the spec's "degrades to keep best local candidate" contract.

```python
def maybeDefer(local_spec: str, goal: str, uncertainty: dict, *, escalate_fn=None) -> str:
    """If uncertainty['defer'] and ELABORATOR_DEFER_ENABLED, call escalate_fn(goal) for a
    higher-capability spec; return it when non-empty, else the local_spec. Never raises."""
```
Tests: `defer=False` → returns local_spec, escalate_fn not called. `defer=True` + `escalate_fn` returning "BIG SPEC" → returns "BIG SPEC". `defer=True` + `escalate_fn` returning None/"" → returns local_spec (degrade). `defer=True` + `escalate_fn` raising → returns local_spec.

- [ ] Write tests → FAIL → implement → PASS → commit `feat(elaborator): uncertainty-aware deferral seam (§7.5, degrading)`.

## Task P4.3: Wire Phase 4 into `core.py` (flag-gated) + final sweep

**Files:** Modify `core.py`; Test append to `test_elaborator.py`.

- In the best-of-N path (P3.3), when `config.ELABORATOR_LOOKAHEAD_ENABLED`, compute `predicted = predict.predictOutcome(c["spec"], work_dir, chat=chat)["predicted_success"]` per candidate and pass into `meritWeight(predicted=predicted)`. Off → predicted defaults 0.0 (selection on static merit only).
- After a winner is chosen, when `config.ELABORATOR_DEFER_ENABLED`: build `unc = uncertainty.runUncertainty(...)` from elevated-assumption count + portfolio spread + precedent hits; `out = defer.maybeDefer(out, goal_raw, unc, escalate_fn=None)`.
- All new behavior flag-guarded; flag-off byte-identical.

Tests: lookahead ON with scripted predict → higher-predicted candidate wins. defer ON with injected escalate_fn → escalated spec returned. All OFF → unchanged.

Final sweep:
- [ ] `python -m pytest tests/orchestration/test_elaborator*.py tests/platform/test_epic_flags_config.py -q` → all green.
- [ ] `python tools/size_audit.py` → zero must_split (split any module that exceeds 300 lines into a helper).
- [ ] Byte-identical: `python -m pytest tests/orchestration/test_elaborator.py -k "byte_identical or flag_off"` → green.
- [ ] commit `feat(elaborator): wire lookahead + deferral (Phase 4, flag-gated)`.

---

## Self-Review (spec coverage)

- §3d precedent → P2.1 + P2.4. §3b band → P2.2. §4 Layer-2 → P2.3 + P2.4.
- §7 A′/A/B → P3.1 + P3.3. §7 C debate → P3.3 (defensive). §7 D evolve → P3.2 (recording seam; orchestrator wiring is a documented follow-up).
- §7 B′ lookahead → P4.1 + P4.3. §7.5 deferral → P4.2 + P4.3.
- Flags → P0. Every stage flag-gated; flag-off byte-identical (asserted each wiring task).
- Honest deferrals: Stage D post-run orchestrator call-site and §7.5 real Claude transport are seams that degrade to no-op/local — documented, not hidden. A Phase-5 follow-up can wire the live transports once burned in.

## Non-goals
- No live Claude subprocess transport for deferral in this plan (seam only).
- No orchestrator-loop edit to call the Stage D recorder post-run (seam only).
- No deep (>1 step) rollout. No public-API change. No model/effort routing change to the main loop.
