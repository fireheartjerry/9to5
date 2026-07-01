# Work Profile Continuous Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace threshold-cliff enum/bool derivation in `work_profile.py`'s `policy()`/`guidance_block()` (and the 5 downstream consumers that branch on it) with continuous composite scores, seeded deterministic-per-run probabilistic rolls for the two genuinely binary infra/cost gates, and a numeric-weight + graded-phrase ladder for prompt text.

**Architecture:** `work_profile.py` gains pure-function primitives (`_pressure`, `_blend`, `seeded_roll`, `phrase_for_score`) and `RunIntentPolicy` is restructured to carry float scores (`discovery_pressure`, `fork_bias`, `review_strictness`, `lens_panel_probability`) instead of enum/bool fields. `policy()` gains an optional `seed: str` kwarg so `execution_environment_preference` can roll deterministically per-run via `policy_from_state()` (seeded by `state.task_id`); direct `policy()` callers that don't need that field simply omit the seed. Consumers (`judge_panel.py`, `fork_policy.py`, `control_mixin.py`, `evidence_gate.py`, `review_mixin.py`, `agents/discovery/__init__.py`) are updated to read the new float fields directly, with `fork_policy.py` and `agents/discovery/__init__.py` performing their own `seeded_roll()` calls using subtask/goal-scoped seed material.

**Tech Stack:** Python 3, pytest, stdlib `hashlib` (no new dependencies).

**Spec:** `docs/superpowers/specs/2026-07-01-work-profile-continuous-scoring-design.md`

---

## Task 1: Continuous primitives in `work_profile.py`

**Files:**
- Modify: `platform_core/orchestration/work_profile.py`
- Test: `tests/test_work_profile.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_work_profile.py` (near the top, after the imports):

```python
def test_pressure_scales_axis_to_unit_interval():
    axes = {"discovery": 0}
    assert wp._pressure(axes, "discovery") == 0.0
    axes = {"discovery": 50}
    assert wp._pressure(axes, "discovery") == 0.5
    axes = {"discovery": 100}
    assert wp._pressure(axes, "discovery") == 1.0


def test_blend_weights_multiple_axes_and_clamps():
    axes = {"discovery": 100, "architecture": 100, "stability": 0}
    assert wp._blend(axes, {"discovery": 0.5, "architecture": 0.5}) == 1.0
    assert wp._blend(axes, {"discovery": 0.5, "stability": 0.5}) == 0.5
    axes = {"discovery": 100}
    assert wp._blend(axes, {"discovery": 2.0}) == 1.0  # clamped, never exceeds 1.0


def test_seeded_roll_is_deterministic_for_same_seed():
    first = wp.seeded_roll("run-42:fork_pref", 0.5)
    second = wp.seeded_roll("run-42:fork_pref", 0.5)
    assert first == second


def test_seeded_roll_respects_probability_extremes():
    assert wp.seeded_roll("any-seed:gate", 0.0) is False
    assert wp.seeded_roll("any-seed:gate", 1.0) is True


def test_seeded_roll_varies_across_seeds_at_mid_probability():
    rolls = {wp.seeded_roll(f"seed-{i}:gate", 0.5) for i in range(30)}
    assert rolls == {True, False}  # both outcomes occur across enough distinct seeds
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_work_profile.py -k "pressure or blend or seeded_roll" -v`
Expected: FAIL with `AttributeError: module 'platform_core.orchestration.work_profile' has no attribute '_pressure'` (and similarly for `_blend`, `seeded_roll`).

- [ ] **Step 3: Implement the primitives**

In `platform_core/orchestration/work_profile.py`, add `import hashlib` to the imports at the top (alongside the existing `import json`), then add these functions directly after the existing `_axis()` function (after line 88, before the `@dataclass` for `WorkProfile`):

```python
def _pressure(axes: dict[str, int], axis: str) -> float:
    """Axis value (0-100) as a 0.0-1.0 float."""
    return _clamp(axes.get(axis, 0)) / 100.0


def _blend(axes: dict[str, int], weights: dict[str, float]) -> float:
    """Weighted composite of several axes' pressures, clamped to 0.0-1.0."""
    raw = sum(_pressure(axes, k) * w for k, w in weights.items())
    return max(0.0, min(1.0, raw))


def _seeded_unit(seed_material: str) -> float:
    """Deterministic pseudo-random float in [0, 1) from stable seed text."""
    digest = hashlib.sha256(seed_material.encode("utf-8")).hexdigest()
    return int(digest[:12], 16) / float(16 ** 12)


def seeded_roll(seed_material: str, probability: float) -> bool:
    """True with ~`probability` chance; deterministic for the same seed_material."""
    return _seeded_unit(seed_material) < max(0.0, min(1.0, probability))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_work_profile.py -k "pressure or blend or seeded_roll" -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/work_profile.py tests/test_work_profile.py
git commit -m "feat(work-profile): add continuous scoring primitives (_pressure, _blend, seeded_roll)"
```

---

## Task 2: Phrase ladder for continuous prompt text

**Files:**
- Modify: `platform_core/orchestration/work_profile.py`
- Test: `tests/test_work_profile.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_work_profile.py`:

```python
def test_phrase_for_score_picks_low_and_high_tiers():
    low = wp.phrase_for_score("discovery", 5)
    high = wp.phrase_for_score("discovery", 95)
    assert low != high
    assert isinstance(low, str) and isinstance(high, str)


def test_phrase_for_score_is_monotonically_banded():
    # Same band -> same phrase; crossing a band boundary -> different phrase.
    assert wp.phrase_for_score("evidence", 61) == wp.phrase_for_score("evidence", 79)
    assert wp.phrase_for_score("evidence", 59) != wp.phrase_for_score("evidence", 61)


def test_phrase_ladder_covers_every_axis():
    for axis in wp.AXES:
        assert len(wp.AXIS_PHRASE_LADDER[axis]) == 5
        for score in (0, 25, 50, 75, 100):
            assert wp.phrase_for_score(axis, score)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_work_profile.py -k phrase -v`
Expected: FAIL with `AttributeError: ... has no attribute 'phrase_for_score'`

- [ ] **Step 3: Implement the ladder**

In `platform_core/orchestration/work_profile.py`, add this directly after the `AXIS_SHORT` dict (after line 63, before `PRESET_DESCRIPTIONS`):

```python
AXIS_PHRASE_LADDER: dict[str, tuple[str, str, str, str, str]] = {
    "stability": (
        "Stability is not a concern here; prioritize other axes freely.",
        "Keep an eye on regressions but don't let it slow you down.",
        "Balance safety with progress; flag risky changes.",
        "Prefer safe, narrow, compatible changes; call out regression risks.",
        "Maximize safety: smallest possible diffs, exhaustive regression "
        "awareness, zero tolerance for silent breakage.",
    ),
    "evidence": (
        "Verification is optional here; trust reasonable judgment.",
        "Light verification is enough; spot-check the obvious paths.",
        "Verify the core behavior; tests are welcome but not exhaustive.",
        "Strengthen tests, verification, reproducible proof, and acceptance evidence.",
        "Demand rigorous, reproducible proof and exhaustive tests for every "
        "claim; treat unverified work as incomplete.",
    ),
    "architecture": (
        "Design purity is not the goal; ship the direct implementation.",
        "Keep the design reasonable but don't over-engineer.",
        "Consider boundaries and ownership where it's cheap to do so.",
        "Clarify boundaries, data flow, ownership, and maintainability tradeoffs.",
        "Treat architecture as first-class: rigorously define boundaries, "
        "ownership, and long-term maintainability before implementing.",
    ),
    "momentum": (
        "Take the time needed; thoroughness matters more than speed here.",
        "Move steadily; don't rush past open questions.",
        "Keep a reasonable pace without cutting corners.",
        "Keep the path shippable; avoid avoidable analysis loops and sprawling scope.",
        "Maximize delivery speed: ship the smallest concrete increment now, "
        "defer everything non-essential.",
    ),
    "discovery": (
        "Stay narrowly on the stated task; note opportunities only in passing.",
        "Mention adjacent opportunities briefly if they're free to note.",
        "Look for reasonable improvements adjacent to the task.",
        "Look for high-upside opportunities and transformative alternatives within scope.",
        "Actively hunt transformative, high-upside alternatives; treat the "
        "obvious solution as a floor, not a ceiling.",
    ),
}


def _band(score: int) -> int:
    """0-100 -> band index 0-4 (20-point bands)."""
    if score >= 80:
        return 4
    if score >= 60:
        return 3
    if score >= 40:
        return 2
    if score >= 20:
        return 1
    return 0


def phrase_for_score(axis: str, score: int) -> str:
    return AXIS_PHRASE_LADDER[axis][_band(_clamp(score))]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_work_profile.py -k "phrase" -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/work_profile.py tests/test_work_profile.py
git commit -m "feat(work-profile): add 5-tier phrase ladder for continuous prompt text"
```

---

## Task 3: Rewrite `RunIntentPolicy`, `policy()`, `preferred_roles()`, `guidance_block()`

This is the core rewrite. It's one atomic step (not broken into red/green sub-steps) because the dataclass shape, `policy()`, `preferred_roles()`, and `guidance_block()` all change together and can't pass tests independently mid-rewrite — every pinned assertion in `tests/test_work_profile.py` that touches these needs to move in lockstep with the implementation.

**Files:**
- Modify: `platform_core/orchestration/work_profile.py`
- Modify: `tests/test_work_profile.py`

- [ ] **Step 1: Replace the pinned/stale tests in `tests/test_work_profile.py`**

Replace `test_default_profile_is_balanced` (currently asserts `wp.policy(p).planner_posture == "blended"`):

```python
def test_default_profile_is_balanced():
    p = wp.resolve()
    assert p.preset == "balanced"
    assert p.axes["momentum"] == 55
    assert "momentum" in wp.policy(p).planner_posture
    assert "55/100" in wp.policy(p).planner_posture
```

Replace `test_presets_resolve_exactly` (currently asserts `wp.policy(p).planner_posture == "audit"`):

```python
def test_presets_resolve_exactly():
    p = wp.resolve("auditor")
    assert p.axes["stability"] == 90
    assert p.axes["evidence"] == 85
    assert "stability" in wp.policy(p).planner_posture
```

Replace `test_policy_contains_brownfield_knobs`:

```python
def test_policy_contains_brownfield_knobs():
    p = wp.resolve("inventor")
    pol = wp.policy(p)
    assert pol.discovery_pressure > 0.9
    assert pol.fork_bias > 0
    assert "researcher" in pol.society_strategy["preferred_roles"]
    assert pol.execution_environment_preference in ("local", "worktree", "isolated")


def test_fork_bias_is_negative_for_conservative_presets():
    p = wp.resolve("auditor")
    assert wp.policy(p).fork_bias < 0


def test_discovery_pressure_lens_probability_and_guidance_move_monotonically():
    prev_lens_p = -1.0
    prev_fork_bias = None
    for d in range(0, 101, 10):
        p = wp.resolve({"axes": {"discovery": d}})
        pol = wp.policy(p)
        assert pol.discovery_pressure == pytest.approx(d / 100.0)
        assert pol.lens_panel_probability >= prev_lens_p - 1e-9
        prev_lens_p = pol.lens_panel_probability
        if prev_fork_bias is not None:
            assert pol.fork_bias >= prev_fork_bias - 1e-9
        prev_fork_bias = pol.fork_bias
        text = wp.guidance_block(p)
        assert f"Discovery: {d}/100" in text
```

Replace `test_guidance_mentions_dominant_axes` (verify it still names "Evidence" and "tests" — no change needed to the assertions themselves, but confirm they still hold against the new ladder text by re-reading them):

```python
def test_guidance_mentions_dominant_axes():
    text = wp.guidance_block(wp.resolve("test-review"), context="planner")
    assert "Evidence" in text
    assert "tests" in text
    assert "never override user scope" in text
    assert "Context: planner" in text
```

(This test's assertions are unchanged — leave it as-is; it's included here only to confirm no edit is needed once Step 3's phrase ladder is in place, since `test-review`'s evidence=95 lands in the top band whose phrase must still contain "tests".)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_work_profile.py -v`
Expected: FAIL — `AttributeError: 'RunIntentPolicy' object has no attribute 'discovery_pressure'` (and similar) on the new/replaced tests; other tests still pass since they don't touch changed surface.

- [ ] **Step 3: Rewrite `RunIntentPolicy` (replaces lines 113-142)**

```python
@dataclass(frozen=True)
class RunIntentPolicy:
    """Compiled operational policy consumed by Nightclaw subsystems."""
    stability_pressure: float
    evidence_pressure: float
    architecture_pressure: float
    momentum_pressure: float
    discovery_pressure: float
    planner_posture: str
    effort_floor_by_task_kind: dict[str, str]
    review_strictness: float
    gemini_blocking_severity: str
    fork_bias: float
    lens_panel_probability: float
    execution_environment_preference: str
    safety_posture: dict[str, Any]
    society_strategy: dict[str, Any]
    horizon_fill_strategy: str
    learning_tags: dict[str, Any]

    def to_meta(self) -> dict[str, Any]:
        return {
            "version": VERSION,
            "stability_pressure": self.stability_pressure,
            "evidence_pressure": self.evidence_pressure,
            "architecture_pressure": self.architecture_pressure,
            "momentum_pressure": self.momentum_pressure,
            "discovery_pressure": self.discovery_pressure,
            "planner_posture": self.planner_posture,
            "effort_floor_by_task_kind": self.effort_floor_by_task_kind,
            "review_strictness": self.review_strictness,
            "gemini_blocking_severity": self.gemini_blocking_severity,
            "fork_bias": self.fork_bias,
            "lens_panel_probability": self.lens_panel_probability,
            "execution_environment_preference": self.execution_environment_preference,
            "safety_posture": self.safety_posture,
            "society_strategy": self.society_strategy,
            "horizon_fill_strategy": self.horizon_fill_strategy,
            "learning_tags": self.learning_tags,
        }
```

- [ ] **Step 4: Rewrite `policy()` (replaces lines 197-264, the old cliff-based body)**

```python
_EFFORT_XHIGH_THRESHOLD = 70
_EFFORT_HIGH_THRESHOLD = 40
_SEVERITY_STRICT_THRESHOLD = 0.7


def _effort_band(score: int) -> str:
    if score >= _EFFORT_XHIGH_THRESHOLD:
        return "xhigh"
    if score >= _EFFORT_HIGH_THRESHOLD:
        return "high"
    return "default"


def policy(profile: WorkProfile, *, seed: str = "") -> RunIntentPolicy:
    a = profile.axes
    dom = profile.dominant_axis()
    stability_p = _pressure(a, "stability")
    evidence_p = _pressure(a, "evidence")
    architecture_p = _pressure(a, "architecture")
    momentum_p = _pressure(a, "momentum")
    discovery_p = _pressure(a, "discovery")

    posture = f"{dom} ({a[dom]}/100 dominant)"

    effort_floor = {
        "default": "default",
        "strict_verify": "high",
        "design": _effort_band(a["architecture"]),
        "explore": _effort_band(a["discovery"]),
        "simple": "default" if momentum_p >= 0.5 else "high",
    }

    review_strictness = _blend(a, {"stability": 0.5, "evidence": 0.5})
    gemini_blocking_severity = (
        "medium" if review_strictness >= _SEVERITY_STRICT_THRESHOLD else "high"
    )

    fork_bias = (_blend(a, {"discovery": 0.5, "architecture": 0.3})
                 - _blend(a, {"stability": 0.4, "evidence": 0.3}))

    lens_panel_probability = max(0.03, min(0.97, discovery_p))

    isolation_score = _blend(a, {"stability": 0.5, "evidence": 0.5})
    worktree_score = discovery_p
    if seeded_roll(f"{seed}:env:isolated", isolation_score):
        env_pref = "isolated"
    elif seeded_roll(f"{seed}:env:worktree", worktree_score):
        env_pref = "worktree"
    else:
        env_pref = "local"

    debate_base = 1 + 4 * _blend(a, {"architecture": 0.5, "discovery": 0.5})
    debate_rounds = max(1, min(5, round(debate_base * (1 - 0.5 * momentum_p))))

    return RunIntentPolicy(
        stability_pressure=stability_p,
        evidence_pressure=evidence_p,
        architecture_pressure=architecture_p,
        momentum_pressure=momentum_p,
        discovery_pressure=discovery_p,
        planner_posture=posture,
        effort_floor_by_task_kind=effort_floor,
        review_strictness=review_strictness,
        gemini_blocking_severity=gemini_blocking_severity,
        fork_bias=fork_bias,
        lens_panel_probability=lens_panel_probability,
        execution_environment_preference=env_pref,
        safety_posture={
            "destructive_tolerance": "low" if a["stability"] >= 70 else "normal",
            "speculative_requires_isolation": a["discovery"] >= 70,
            "risky_actions_need_extra_justification": a["evidence"] >= 70,
        },
        society_strategy={
            "dominant_axis": dom,
            "debate_rounds": debate_rounds,
            "preferred_roles": preferred_roles(profile),
        },
        horizon_fill_strategy=posture,
        learning_tags={"preset": profile.preset, "dominant_axis": dom, "axes": dict(a)},
    )
```

Note on `safety_posture`: the spec called for reformulating its three sub-checks
"for consistency," but each is already a single-axis cliff (not a multi-axis
`max()` bucketing like `fork_strategy`/`review_thresholds` were), so there's no
cliff-of-a-composite to smooth out, and nothing reads this field today (confirmed
by the repo survey during brainstorming). Left byte-for-byte identical to the
current code to avoid inventing unrequested behavior on dead code (YAGNI).

- [ ] **Step 5: Rewrite `preferred_roles()` (replaces lines 274-290)**

```python
_ROLE_INCLUSION_FLOOR = 0.3


def preferred_roles(profile: WorkProfile | dict | None) -> list[str]:
    p = resolve(profile) if not isinstance(profile, WorkProfile) else profile
    a = p.axes
    role_scores = {
        "tester": _blend(a, {"stability": 0.5, "evidence": 0.5}),
        "reviewer": _blend(a, {"stability": 0.5, "evidence": 0.5}),
        "researcher": _blend(a, {"architecture": 0.5, "discovery": 0.5}),
        "planner": _blend(a, {"architecture": 0.5, "discovery": 0.5}),
    }
    ranked = sorted(role_scores, key=lambda r: role_scores[r], reverse=True)
    roles = ["coder"] + [r for r in ranked if role_scores[r] > _ROLE_INCLUSION_FLOOR]
    seen: list[str] = []
    for r in roles:
        if r not in seen:
            seen.append(r)
    return seen
```

- [ ] **Step 6: Rewrite `guidance_block()` (replaces lines 323-345)**

```python
def guidance_block(profile: WorkProfile | dict | None, *, context: str = "run") -> str:
    p = resolve(profile) if not isinstance(profile, WorkProfile) else profile
    pol = policy(p)
    lines = [
        "## Nightclaw work profile",
        f"Preset/source: {p.preset} / {p.source}. Axes: {p.compact()}.",
        f"Dominant posture: {pol.planner_posture}.",
        "Apply this as an operating policy, not decorative prose:",
        "- Hard boundaries: never override user scope, safety rules, feature flags, or available backends.",
    ]
    for axis in AXES:
        score = p.axes[axis]
        lines.append(f"- {axis.title()}: {score}/100 — {phrase_for_score(axis, score)}")
    return "\n".join(lines) + f"\nContext: {context}.\n"
```

- [ ] **Step 7: Update `policy_from_state()` to pass a run-stable seed and rebuild from the new field set (replaces lines 300-320)**

```python
def policy_from_state(state) -> RunIntentPolicy:
    meta = getattr(state, "meta", {}) or {}
    stored = meta.get("run_intent_policy")
    if isinstance(stored, dict) and stored.get("version") == VERSION:
        try:
            return RunIntentPolicy(
                stability_pressure=float(stored.get("stability_pressure", 0.0)),
                evidence_pressure=float(stored.get("evidence_pressure", 0.0)),
                architecture_pressure=float(stored.get("architecture_pressure", 0.0)),
                momentum_pressure=float(stored.get("momentum_pressure", 0.0)),
                discovery_pressure=float(stored.get("discovery_pressure", 0.0)),
                planner_posture=stored.get("planner_posture", ""),
                effort_floor_by_task_kind=dict(stored.get("effort_floor_by_task_kind") or {}),
                review_strictness=float(stored.get("review_strictness", 0.0)),
                gemini_blocking_severity=stored.get("gemini_blocking_severity", "high"),
                fork_bias=float(stored.get("fork_bias", 0.0)),
                lens_panel_probability=float(stored.get("lens_panel_probability", 0.03)),
                execution_environment_preference=stored.get(
                    "execution_environment_preference", "local"),
                safety_posture=dict(stored.get("safety_posture") or {}),
                society_strategy=dict(stored.get("society_strategy") or {}),
                horizon_fill_strategy=stored.get("horizon_fill_strategy", ""),
                learning_tags=dict(stored.get("learning_tags") or {}),
            )
        except Exception:
            pass
    seed = str(getattr(state, "task_id", "") or "")
    return policy(from_state(state), seed=seed)
```

- [ ] **Step 8: Run the full file's tests to verify they pass**

Run: `python -m pytest tests/test_work_profile.py -v`
Expected: PASS (all tests)

- [ ] **Step 9: Commit**

```bash
git add platform_core/orchestration/work_profile.py tests/test_work_profile.py
git commit -m "feat(work-profile): replace threshold-cliff policy() with continuous scores"
```

---

## Task 4: `judge_panel.py` — continuous weight scaling

**Files:**
- Modify: `platform_core/orchestration/judge_panel.py:38-52`
- Test: `tests/test_judge_panel.py` (verify only — no edit expected)

- [ ] **Step 1: Confirm the existing test still encodes the right contract**

Read `tests/test_judge_panel.py:75-78`. `test_profile_weights_raise_evidence_fact_weight` asserts `evidence.fact > base.fact` (an ordering check, not an exact value) — this should continue to pass after Step 3 below, since test-review's evidence axis (95) is higher than balanced's (45) under any monotonic scaling. No test edit needed. Run it now to confirm current baseline:

Run: `python -m pytest tests/test_judge_panel.py -v`
Expected: PASS (current behavior, before the change)

- [ ] **Step 2: Replace `weightsForProfile()` (lines 38-52) with continuous scaling**

```python
_MAX_BUMP_FACT = 0.2
_MAX_BUMP_RUBRIC = 0.15
_MAX_BUMP_RISK_UP = 0.2
_MAX_BUMP_RISK_DOWN = 0.1
_MAX_BUMP_COST = 0.15


def weightsForProfile(work_profile=None) -> JudgeWeights:
    """Profile-aware fork judging. Facts still dominate; weights only tune eligible branches."""
    base = _defaultWeights()
    try:
        from platform_core.orchestration import work_profile as _wp
        p = _wp.resolve(work_profile)
        a = p.axes
        evidence_p = a["evidence"] / 100.0
        rubric_p = max(a["architecture"], a["discovery"]) / 100.0
        stability_p = a["stability"] / 100.0
        discovery_p = a["discovery"] / 100.0
        momentum_p = a["momentum"] / 100.0
        return JudgeWeights(
            fact=base.fact + _MAX_BUMP_FACT * evidence_p,
            rubric=base.rubric + _MAX_BUMP_RUBRIC * rubric_p,
            risk=base.risk + _MAX_BUMP_RISK_UP * stability_p - _MAX_BUMP_RISK_DOWN * discovery_p,
            cost=base.cost + _MAX_BUMP_COST * momentum_p,
        )
    except Exception:  # noqa: BLE001
        return base
```

- [ ] **Step 3: Run tests to verify they still pass**

Run: `python -m pytest tests/test_judge_panel.py -v`
Expected: PASS (same test, now exercising continuous scaling)

- [ ] **Step 4: Commit**

```bash
git add platform_core/orchestration/judge_panel.py
git commit -m "feat(judge-panel): continuous axis scaling instead of threshold bumps"
```

---

## Task 5: `fork_policy.py` — seeded roll for `shouldFork`, weighted ranking for `forkPlan`

**Files:**
- Modify: `platform_core/orchestration/fork_policy.py:37-110`
- Modify: `tests/test_fork_policy.py`

- [ ] **Step 1: Update the pinned test to a statistical assertion**

Replace `test_discovery_profile_can_opt_in_design_fork` in `tests/test_fork_policy.py`:

```python
def test_discovery_profile_can_opt_in_design_fork():
    # inventor's fork_bias computes to ~0.48 (not ~1.0) -- this is a "CONSERVATIVE
    # OPT-IN gate" per the module docstring, and clamp01(fork_bias) intentionally
    # keeps most presets at 0 probability (see policy() in work_profile.py). Assert
    # the mechanism is correctly *biased*, not an exact magnitude: over 40 distinct
    # seeds, P(zero hits at p~=0.48) is ~2e-12, so `hi_hits > 0` is not flaky.
    hi_hits = 0
    lo_hits = 0
    for i in range(40):
        st = {"title": "Explore transformative architecture",
              "description": "ambiguous design options", "subtask_id": f"seed-{i}"}
        if fp.shouldFork(st, **_kwargs(work_profile="inventor")):
            hi_hits += 1
        st_lo = {"title": "Explore transformative architecture",
                 "description": "ambiguous design options", "subtask_id": f"seed-{i}"}
        if fp.shouldFork(st_lo, **_kwargs(work_profile="auditor")):
            lo_hits += 1
    assert hi_hits > 0     # inventor: positive fork_bias -> some seeds opt in
    assert lo_hits == 0    # auditor: negative fork_bias -> clamp01 forces probability 0, never opts in
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fork_policy.py::test_discovery_profile_can_opt_in_design_fork -v`
Expected: FAIL (current code has no `subtask_id`-seeded probabilistic path; behavior is still the old deterministic boolean, so counts won't match the new expected shape once Step 3 changes the underlying mechanism — this red step confirms the test exercises the not-yet-changed code path meaningfully once combined with Step 3's implementation change. If it happens to pass against old code, proceed directly to Step 3 and re-verify at Step 4.)

- [ ] **Step 3: Update `shouldFork()` (lines 43-53) to use a seeded roll**

Replace:

```python
        if not subtask.get("fork_eligible"):       # still the normal trigger
            try:
                from platform_core.orchestration import work_profile as _wp
                pol = _wp.policy(_wp.resolve(work_profile))
                if not pol.fork_strategy.get("prefer_forks"):
                    return False
                blob = f"{subtask.get('title', '')} {subtask.get('description', '')}".lower()
                if not any(w in blob for w in ("design", "architect", "explore", "transform", "ambiguous")):
                    return False
            except Exception:  # noqa: BLE001
                return False
```

with:

```python
        if not subtask.get("fork_eligible"):       # still the normal trigger
            try:
                from platform_core.orchestration import work_profile as _wp
                pol = _wp.policy(_wp.resolve(work_profile))
                seed = f"{subtask.get('subtask_id', '')}:fork_pref"
                if not _wp.seeded_roll(seed, max(0.0, pol.fork_bias)):
                    return False
                blob = f"{subtask.get('title', '')} {subtask.get('description', '')}".lower()
                if not any(w in blob for w in ("design", "architect", "explore", "transform", "ambiguous")):
                    return False
            except Exception:  # noqa: BLE001
                return False
```

- [ ] **Step 4: Update `forkPlan()` (lines 82-103) to weighted-order angles and continuously scale count**

Replace the body of `forkPlan` (lines 85-103, everything between `n = max(1, int(n))` and the `for i in range(n):` loop) with:

```python
    n = max(1, int(n))
    seeds: list = []
    try:
        from platform_core.orchestration import work_profile as _wp
        pol = _wp.policy(_wp.resolve(work_profile))
        pool = list(angles)
        if pol.fork_bias > 0:
            pool = pool + [
                "Approach D: bold redesign -- maximize long-term upside while preserving acceptance.",
            ]
        if pol.fork_bias < 0:
            pool = [
                "Approach A: conservative patch -- smallest safe change with regression awareness.",
                "Approach B: test-first patch -- prove the bug, then fix it.",
                "Approach C: safety review -- reduce risk before broadening the change.",
            ] + pool
        angles = tuple(dict.fromkeys(pool))  # de-dupe, preserve order
        n = max(1, round(n * (1.0 - 0.5 * pol.momentum_pressure)))
    except Exception:  # noqa: BLE001
        pass
```

(This replaces the old `if pol.fork_strategy.get("prefer_forks")` / `conservative_forks` / `rare_forks` cascade with score-ordered pool assembly and a continuous count formula. The rest of `forkPlan` — the `for i in range(n): ...` loop and `BranchSeed` construction — stays unchanged.)

- [ ] **Step 5: Run fork_policy tests to verify they pass**

Run: `python -m pytest tests/test_fork_policy.py tests/test_fork_policy_plan.py -v`
Expected: PASS (all tests, including the rewritten statistical one and the unchanged `test_profile_shapes_fork_angles`)

- [ ] **Step 6: Commit**

```bash
git add platform_core/orchestration/fork_policy.py tests/test_fork_policy.py
git commit -m "feat(fork-policy): seeded probabilistic fork gate + continuous angle/count scaling"
```

---

## Task 6: `control_mixin.py` — continuous review-threshold multiplier

**Files:**
- Modify: `platform_core/orchestration/control_mixin.py:340-353`

- [ ] **Step 1: Replace the boolean-bump block**

Replace lines 345-353:

```python
        try:
            from platform_core.orchestration import work_profile as _wp
            pol = _wp.policy(_wp.resolve(getattr(self, "_active_work_profile", None)))
            if pol.review_thresholds.get("review_short_outputs"):
                min_chars = max(80, min_chars // 2)
            if pol.review_thresholds.get("skip_repeat_reviews"):
                min_chars = int(min_chars * 1.5)
        except Exception:  # noqa: BLE001
            pass
```

with:

```python
        try:
            from platform_core.orchestration import work_profile as _wp
            pol = _wp.policy(_wp.resolve(getattr(self, "_active_work_profile", None)))
            multiplier = 1.5 - pol.review_strictness  # clamped [0.5, 1.5] since review_strictness in [0, 1]
            min_chars = max(80, int(min_chars * multiplier))
        except Exception:  # noqa: BLE001
            pass
```

- [ ] **Step 2: Run the relevant test file**

Run: `python -m pytest tests/ -k control_mixin -v`
Expected: PASS (no test currently pins the exact multiplier value; confirm no regressions)

- [ ] **Step 3: Commit**

```bash
git add platform_core/orchestration/control_mixin.py
git commit -m "feat(control-mixin): continuous review-strictness multiplier instead of boolean bumps"
```

---

## Task 7: `evidence_gate.py` — phrase-ladder verification criteria

**Files:**
- Modify: `platform_core/orchestration/evidence_gate.py:153-163`

- [ ] **Step 1: Replace the boolean-gated sentence block**

Replace lines 153-163:

```python
        try:
            from platform_core.orchestration import work_profile as _wp
            pol = _wp.policy_from_state(state)
            criteria += "\n\n" + _wp.guidance_block(state.meta.get("work_profile"),
                                                    context="independent-verifier")
            if pol.verify_requirements.get("affected_tests"):
                criteria += "\nEvidence policy: prefer affected tests and explicit acceptance proof.\n"
            if pol.verify_requirements.get("regression_checks"):
                criteria += "\nStability policy: look for regression and compatibility risk.\n"
        except Exception:  # noqa: BLE001
            pass
```

with:

```python
        try:
            from platform_core.orchestration import work_profile as _wp
            pol = _wp.policy_from_state(state)
            criteria += "\n\n" + _wp.guidance_block(state.meta.get("work_profile"),
                                                    context="independent-verifier")
            evidence_score = int(pol.evidence_pressure * 100)
            stability_score = int(pol.stability_pressure * 100)
            criteria += (f"\nEvidence policy ({evidence_score}/100): "
                        f"{_wp.phrase_for_score('evidence', evidence_score)}\n")
            criteria += (f"\nStability policy ({stability_score}/100): "
                        f"{_wp.phrase_for_score('stability', stability_score)}\n")
        except Exception:  # noqa: BLE001
            pass
```

- [ ] **Step 2: Run the relevant test file**

Run: `python -m pytest tests/ -k evidence_gate -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add platform_core/orchestration/evidence_gate.py
git commit -m "feat(evidence-gate): always-present phrase-ladder verification criteria"
```

---

## Task 8: `review_mixin.py` — flatten `gemini_blocking_severity` access

**Files:**
- Modify: `platform_core/orchestration/review_mixin.py:188`

- [ ] **Step 1: Update the single line**

Replace line 188:

```python
                bar = order.get(pol.review_thresholds.get("gemini_blocking_severity", "high"), 3)
```

with:

```python
                bar = order.get(pol.gemini_blocking_severity, 3)
```

- [ ] **Step 2: Run the relevant test file**

Run: `python -m pytest tests/ -k review_mixin -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add platform_core/orchestration/review_mixin.py
git commit -m "fix(review-mixin): read flattened gemini_blocking_severity field"
```

---

## Task 9: `agents/discovery/__init__.py` — seeded lens-panel roll + continuous innovation ratio

**Files:**
- Modify: `agents/discovery/__init__.py:56-82`
- Test: `tests/test_discovery_facade.py` (verify only)

- [ ] **Step 1: Run baseline test**

Run: `python -m pytest tests/test_discovery_facade.py -v`
Expected: PASS (current behavior, before the change)

- [ ] **Step 2: Replace lines 56-82**

Replace:

```python
    force_lenses = False
    transformative = False
    try:
        from platform_core.orchestration import work_profile as _wp
        pol = _wp.policy(_wp.resolve(work_profile))
        force_lenses = pol.discovery_depth in ("lenses", "transformative")
        transformative = pol.discovery_depth == "transformative"
    except Exception:  # noqa: BLE001
        pass

    if not force_lenses and not shouldRunFullDiscovery(goal_raw):
        LOG.info("Discovery: specific goal detected — skipping lens panel")
        return None

    try:
        from agents.discovery import lenses as lenses_mod
        from agents.discovery import synthesis as synthesis_mod
        LOG.info("Discovery: running lens panel")
        findings = lenses_mod.run_lens_panel(compiled)
        LOG.info("Discovery: synthesizing %d findings", len(findings))
        report = synthesis_mod.synthesize(findings)
        if transformative:
            try:
                report.innovation_ratio = max(float(getattr(report, "innovation_ratio", 0) or 0), 1.0)
                report.theme_suggestion = f"transformative: {report.theme_suggestion}"
            except Exception:  # noqa: BLE001
                pass
        LOG.info("Discovery: complete — %d findings, theme=%r",
                 len(report.findings), report.theme_suggestion)
        return report
    except Exception as e:  # noqa: BLE001
        LOG.warning("Discovery lens/synthesis failed (%s); run proceeds without report", e)
        return None
```

with:

```python
    discovery_pressure = 0.0
    force_lenses = False
    try:
        from platform_core.orchestration import work_profile as _wp
        pol = _wp.policy(_wp.resolve(work_profile))
        discovery_pressure = pol.discovery_pressure
        seed = f"{work_dir}:{goal_raw}:lens_panel"
        force_lenses = _wp.seeded_roll(seed, pol.lens_panel_probability)
    except Exception:  # noqa: BLE001
        pass

    if not force_lenses and not shouldRunFullDiscovery(goal_raw):
        LOG.info("Discovery: specific goal detected — skipping lens panel")
        return None

    try:
        from agents.discovery import lenses as lenses_mod
        from agents.discovery import synthesis as synthesis_mod
        LOG.info("Discovery: running lens panel")
        findings = lenses_mod.run_lens_panel(compiled)
        LOG.info("Discovery: synthesizing %d findings", len(findings))
        report = synthesis_mod.synthesize(findings)
        try:
            report.innovation_ratio = max(
                float(getattr(report, "innovation_ratio", 0) or 0), discovery_pressure)
            report.theme_suggestion = (
                f"[discovery {int(discovery_pressure * 100)}/100] {report.theme_suggestion}")
        except Exception:  # noqa: BLE001
            pass
        LOG.info("Discovery: complete — %d findings, theme=%r",
                 len(report.findings), report.theme_suggestion)
        return report
    except Exception as e:  # noqa: BLE001
        LOG.warning("Discovery lens/synthesis failed (%s); run proceeds without report", e)
        return None
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `python -m pytest tests/test_discovery_facade.py tests/test_discovery_integration.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add agents/discovery/__init__.py
git commit -m "feat(discovery): seeded probabilistic lens panel + continuous innovation ratio"
```

---

## Task 10: Full verification sweep

**Files:** none (verification only)

- [ ] **Step 1: Run the full affected test surface**

Run:
```bash
python -m pytest tests/test_work_profile.py tests/test_fork_policy.py tests/test_fork_policy_plan.py tests/test_judge_panel.py tests/test_society_roles.py tests/test_discovery_facade.py tests/test_discovery_integration.py tests/test_surfaces.py -v
```
Expected: PASS (all tests)

- [ ] **Step 2: Run the fast suite per project convention**

Run: `python tools/dev.py fast`
Expected: PASS

- [ ] **Step 3: Run the modularity size audit**

Run: `python tools/size_audit.py`
Expected: zero `must_split` violations. `work_profile.py` grew (~356 -> ~440 lines); if it crosses 450, split the phrase-ladder data (`AXIS_PHRASE_LADDER`, `phrase_for_score`, `_band`) into a new `platform_core/orchestration/work_profile_phrases.py` module and re-export from `work_profile.py`, per this repo's "large module -> sub-modules + re-export facade" pattern (see `.claude/rules/modularity.md`).

- [ ] **Step 4: Regenerate the module map**

`work_profile.py`'s exported symbols changed (new `seeded_roll`, `phrase_for_score`, `_pressure`/`_blend` are private; `RunIntentPolicy` field names changed). Run:

```bash
python tools/repo_map.py
```

Then check `git diff AGENTS.md` looks sane (updated `work_profile.py` row, no unrelated churn).

- [ ] **Step 5: Commit the generated docs update (if any diff)**

```bash
git add AGENTS.md
git commit -m "docs: regenerate AGENTS.md after work_profile.py export changes"
```

(Skip this step if `git diff AGENTS.md` is empty.)
