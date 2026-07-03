# Work Profile: Continuous Scoring Design

## Problem

`platform_core/orchestration/work_profile.py` stores each work-profile axis
(stability, evidence, architecture, momentum, discovery) as a continuous
0-100 int, but `policy()` immediately collapses every axis into a small enum
or boolean via hard `>=` cliffs (e.g. `discovery >= 85 -> "transformative"`).
Downstream consumers then branch on those enums/bools, so a discovery score
of 61 and 99 produce identical behavior, and 59 vs 61 produce a step change.
`guidance_block()` has the same shape in prose form: a fixed sentence either
appears or doesn't at a single threshold per axis — the "act innovative"
prompt-injection pattern the user flagged. Nothing about the *strength* of a
score currently reaches behavior; only which side of a line it's on.

## Goals

- Every axis's magnitude, not just its side of a threshold, influences
  downstream behavior, prompt text, and numeric parameters.
- Where a decision is genuinely binary (pick one infra backend; run the
  costly lens panel or not), replace the fixed-axis cliff with a seeded
  probabilistic roll weighted by a smooth composite score — same mechanism
  category, no more arbitrary single-point cliffs, but still literally
  "cross a line" because the consumer needs one concrete answer.
- Where a decision is a safety/blocking gate (review-blocking severity,
  safety_posture) or flavor-text selection (fork angle-hint banks), keep it
  deterministic but derive the line from a smooth blended score instead of a
  single raw axis threshold.
- Preserve existing hard safety boundaries (self-referential runs, cost
  ceiling, doc-only, single-deliverable) unchanged — those are correctness
  gates, not profile-tuning, and are out of scope.

## Non-goals

- Not changing the `WorkProfile`/axes/preset layer (0-100 ints, presets,
  parsing) — already continuous, already fine.
- Not adding new axes or presets.
- Not touching `debate_rounds`/`safety_posture`/`learning_tags` consumers,
  because none exist today (confirmed by repo survey) — only their
  *formulas* inside `policy()` change, for internal consistency, since
  they're cheap and adjacent to everything else being rewritten.

## Architecture

### New primitives in `work_profile.py`

```python
def _pressure(axes: dict[str, int], axis: str) -> float:
    """axis value -> 0.0-1.0."""
    return _clamp(axes.get(axis, 0)) / 100.0

def _blend(axes: dict[str, int], weights: dict[str, float]) -> float:
    """Weighted composite of several axes, clamped to 0.0-1.0."""
    raw = sum(_pressure(axes, k) * w for k, w in weights.items())
    return max(0.0, min(1.0, raw))

def _seeded_unit(seed_material: str) -> float:
    """Deterministic pseudo-random float in [0, 1) from stable seed text."""
    import hashlib
    digest = hashlib.sha256(seed_material.encode()).hexdigest()
    return int(digest[:12], 16) / float(16 ** 12)

def seeded_roll(seed_material: str, probability: float) -> bool:
    """True with ~`probability` chance, deterministic for the same seed."""
    return _seeded_unit(seed_material) < max(0.0, min(1.0, probability))

def phrase_for_score(axis: str, score: int) -> str:
    """Pick from a 5-tier ladder of phrasing for an axis, by score band."""
    ...  # AXIS_PHRASE_LADDER[axis][band(score)]
```

`seeded_roll` is the one probabilistic primitive. Seed material is always a
string built from stable identifiers already in scope at the call site
(subtask id, work_dir + goal text, run id) plus a fixed salt naming the gate
— e.g. `f"{subtask_id}:fork_pref"` — so a replayed/resumed run reproduces
the same roll, but different subtasks/runs at the same score genuinely
differ. No global `random` state is touched.

### `RunIntentPolicy` field changes

| Field | Before | After |
|---|---|---|
| `discovery_depth: str` (4 enum) | cliff on `discovery` | removed; replaced by `discovery_pressure: float` + `lens_panel_probability: float` (clamped to [0.03, 0.97] so extremes stay probabilistic, never a hard 0/1) |
| `planner_posture: str` | cliff at `a[dom] >= 65` else `"blended"` | becomes a generated descriptive string built from continuous values every time: `f"{dom} ({a[dom]}/100 dominant)"`, no more binary "blended" fallback. Still human-readable for the prompt text consumers (`run_loop_mixin`), but no consumer branches on its exact value today (confirmed by survey), so this is a safe pure-text change. |
| `effort_floor_by_task_kind: dict[str,str]` | single `>=70`/`>=75`/`>=80` cliff per kind | 3-band mapping (`"default"`/`"high"`/`"xhigh"`) from the relevant composite score via two breakpoints instead of one (never auto-selects `"ultracode"` — reserved for explicit user opt-in) |
| `review_thresholds["review_short_outputs"/"skip_repeat_reviews"]: bool` | two independent boolean bumps | replaced by `review_strictness: float` composite; `control_mixin.py` computes `min_chars` as a continuous multiplier of it instead of two fixed-factor bumps |
| `review_thresholds["gemini_blocking_severity"]` | cliff, `"medium"`/`"high"` | **stays deterministic** (safety exception): computed from `review_strictness` (a blend, not a single raw axis) instead of `max(stability, evidence)` alone |
| `verify_requirements: dict[str,bool]` | 4 independent booleans | removed; `evidence_gate.py` uses `evidence_pressure`/`stability_pressure` floats directly with the phrase-ladder pattern (see below) |
| `fork_strategy: dict[str,bool]` (`prefer_forks`/`conservative_forks`/`rare_forks`) | 3 independent booleans | removed; replaced by single `fork_bias: float` in range roughly [-1, 1] (positive = bolder/more forking, negative = conservative), computed as `_blend(axes, {"discovery": 0.5, "architecture": 0.3}) - _blend(axes, {"stability": 0.4, "evidence": 0.3})` |
| `execution_environment_preference: str` | 2 cliffs, `isolated` overrides `worktree` overrides `local` | same priority order, now via sequential **probabilistic** rolls: roll `isolated` first with probability `_blend(axes, {"stability": 0.5, "evidence": 0.5})`; if that misses, roll `worktree` with probability `discovery_pressure`; else `local`. Seeded by run/state id so the choice is stable within a run. |
| `safety_posture: dict` | cliffs, unused today | **stays deterministic**; formulas rewritten to use blended composites instead of single axes, for consistency, even though nothing reads it yet |
| `society_strategy["debate_rounds"]: int` | 3-value cliff, unused today | continuous formula `round(1 + 4 * _blend(axes, {"architecture": 0.5, "discovery": 0.5}))`, clamped 1-5, for consistency only |
| `society_strategy["preferred_roles"]` | threshold-append per axis | `preferred_roles()` (already list-based) changes internally to rank roles by a continuous suitability score per axis-group and sort descending, instead of appending on `>=60`. Output is still an ordered list — same shape, continuous derivation. |

### Per-consumer changes

- **`judge_panel.py` `weightsForProfile()`**: replace `base + (0.2 if a[x]>=70 else 0.0)` with `base + MAX_BUMP * pressure`, where `MAX_BUMP` constants match today's bump magnitudes (0.2/0.15/0.2/-0.1/0.15) so behavior at axis=100 matches today's behavior at axis>=70, but now scales smoothly from axis=0. `pressure` values pulled straight from `WorkProfile.axes` (this function already bypasses `RunIntentPolicy`).

- **`fork_policy.shouldFork()`**: the `prefer_forks` boolean check becomes `seeded_roll(f"{subtask.get('subtask_id','')}:fork_pref", clamp01(fork_bias))`. All existing hard AND-gates (enabled, worktree_isolated, is_self_referential, cost ceiling, doc-only, single-deliverable) are untouched.

- **`fork_policy.forkPlan()`**: angle bank becomes one pool `DIVERSITY_ANGLES + (BOLD_ANGLE,) + (CONSERVATIVE_ANGLES...)` deterministically re-ordered by `fork_bias` (positive sorts bold-first, negative sorts conservative-first), then the first `n` distinct angles are used — continuous ranking, no coin flip, keeps `any("test-first" in ...)`-style tests meaningful. Fork count: the old `rare_forks` cliff was keyed on `momentum >= 80` (not on `fork_bias`, which only mixes discovery/architecture/stability/evidence), so count-scaling uses `momentum_pressure` directly: `n = max(1, round(n * (1.0 - 0.5 * momentum_pressure)))` — continuously shrinks toward roughly half `n` as momentum approaches 100, matches old `min(n, 2)` behavior at the momentum=80+ end without a cliff.

- **`control_mixin.py`**: `min_chars` multiplier becomes `1.5 - review_strictness` (clamped [0.5, 1.5]) instead of two independent fixed-factor bumps.

- **`plan_mixin.py`**: `effort_floor_by_task_kind` reads the new 3-band dict directly (no local branching needed, the banding lives in `policy()`).

- **`evidence_gate.py`**: replace the two boolean-gated canned sentences with the phrase-ladder pattern — always print `f"Evidence: {a['evidence']}/100 — {phrase}"` and same for stability, where `phrase` is picked from a 5-tier list by score band.

- **`review_mixin.py`**: reads `gemini_blocking_severity` exactly as before (still an ordinal `"low"/"medium"/"high"` tier, since findings themselves are pre-tiered) — only the *derivation* inside `policy()` changes to use the blended `review_strictness` score.

- **`agents/discovery/__init__.py`**: `force_lenses` becomes `seeded_roll(f"{work_dir}:{goal_raw}:lens_panel", pol.lens_panel_probability)`. The `transformative` hard floor (`innovation_ratio = max(x, 1.0)`) becomes `innovation_ratio = max(x, pol.discovery_pressure)` — continuous, only reaches 1.0 at discovery=100. The `"transformative: "` string prefix on `theme_suggestion` is replaced with an always-present numeric tag: `f"[discovery {int(pol.discovery_pressure*100)}/100] {theme_suggestion}"`.

### Prompt text pattern (numeric weight + graded phrase ladder)

`guidance_block()` is rewritten to always print all 5 axes as `"{Label}: {score}/100 — {phrase}"`, where `phrase` comes from a per-axis 5-tier ladder (bands roughly 0-20/20-40/40-60/60-80/80-100) with monotonically escalating language (e.g. discovery's ladder runs from "note opportunities only in passing" up to "actively hunt transformative, high-upside alternatives"). No axis line is conditionally omitted anymore — every run sees all 5 numbers and their matching phrase, so the LLM gets the same information whether an axis reads 10 or 90, just phrased differently, plus the literal number for the fine-grained signal. `evidence_gate.py` reuses the same ladder helper for its 2 axes rather than authoring a second copy.

## Error handling

Every existing consumer already wraps `work_profile` calls in
`try/except Exception: pass`-style fallbacks to a safe default (no crash on
malformed/missing profile). That pattern is unchanged — the new composite
helpers (`_blend`, `seeded_roll`, `phrase_for_score`) are pure functions with
no new failure modes beyond what `_clamp`/`resolve` already handle.

## Testing strategy

- `tests/test_work_profile.py`: replace the 4 exact-enum/bool pins
  (`test_policy_contains_brownfield_knobs`, and the two `planner_posture`
  string-equality assertions) with range/monotonicity assertions, e.g.
  `pol.discovery_pressure > 0.9` for "inventor", `pol.fork_bias > 0` for
  "inventor" vs `< 0` for "auditor", `pol.lens_panel_probability` strictly
  increasing across balanced -> inventor.
- `tests/test_fork_policy.py` (`test_discovery_profile_can_opt_in_design_fork`):
  convert to a statistical assertion — call `shouldFork` with the same
  subtask shape across N distinct synthetic `subtask_id`s (fixed seed list)
  and assert the True-fraction is high (e.g. >= 0.8) for "inventor" and low
  for "auditor" on the same non-eligible-flag path, instead of pinning a
  single deterministic `True`.
- `tests/test_fork_policy_plan.py` (`test_profile_shapes_fork_angles`):
  unchanged in spirit — deterministic ranking still guarantees "auditor"
  surfaces `"test-first"`/`"conservative"` angles, since ranking (not
  randomness) drives angle-bank order.
- `tests/test_society_roles.py`: unchanged — `preferred_roles()` still
  returns `"researcher"` at/near the top for "inventor" under the new
  ranking, since discovery/architecture dominate its suitability score.
- `tests/test_judge_panel.py`: unchanged — `evidence.fact > base.fact`
  ordering assertion holds under the continuous formula too.
- New/adjusted coverage: add a small monotonicity test in
  `tests/test_work_profile.py` sweeping `discovery` 0->100 and asserting
  `lens_panel_probability`, `fork_bias` (discovery term), and
  `guidance_block()`'s printed number move monotonically with it.

## Files touched

`platform_core/orchestration/work_profile.py`,
`platform_core/orchestration/judge_panel.py`,
`platform_core/orchestration/fork_policy.py`,
`platform_core/orchestration/control_mixin.py`,
`platform_core/orchestration/plan_mixin.py`,
`platform_core/orchestration/evidence_gate.py`,
`platform_core/orchestration/review_mixin.py` (derivation-only, no interface change),
`agents/discovery/__init__.py`,
`tests/test_work_profile.py`, `tests/test_fork_policy.py`,
`tests/test_fork_policy_plan.py` (verify only, likely no edit needed).
