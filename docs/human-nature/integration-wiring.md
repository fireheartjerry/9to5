# Human-Nature Layer — Integration Wiring Checklist

> **Code removed 2026-07-02 (R3-human-nature-amputation):** the `human_nature/` package,
> `memory/conviction_ledger.py`, and the `HN_*` config knobs were deleted from the tree
> (zero production imports). The full implementation is recoverable at pre-deletion commit
> `a7b1b2d`. These specs remain the source of truth for any revival.

**Status:** Ready for merge-time insertion into the run loop (Spec A + Spec B must land first).
**Key guarantee:** ALL wiring is behind `config.HUMAN_NATURE_ENABLED` (default `False`).
Until the flag is explicitly set, the merged run loop is byte-identical to pre-layer behaviour.

---

## Module

All hooks live in `human_nature/integration.py`. Import pattern (add to the relevant mixin):

```python
from human_nature import integration
```

No other `human_nature.*` import is needed at call sites — `integration` is the facade.

---

## Call-Site Checklist

### 1. Preamble / Run Initialisation

**File:** `platform_core/orchestration/run_phase_mixin.py`
**Method:** `_runPreamble` (or equivalent setup at the start of a run)
**Hook:** `integration.ensure_self_state(state)`

```python
# At the start of every run, lazily initialise the self_state interior.
integration.ensure_self_state(state)
```

- Returns `None` when disabled (no-op).
- Returns the live `SelfState` dict when enabled; idempotent on repeated calls.

---

### 2. Pre-Act Routing (per attempt)

**File:** `platform_core/orchestration/execute_mixin.py`
**Method:** `_runOneAttempt` (before the deliberative chain fires)
**Hook:** `integration.route_pre_act(state, domain, signals, chat=chat)`

```python
# Dual-process routing: "fast" (skip deliberation) or "deliberate" (full CoT).
# OFF → always "deliberate", snap/route never called.
routing = integration.route_pre_act(state, domain, signals, chat=chat)
if routing == "fast":
    ...  # skip heavy deliberation; only active when HN_INTUITION_SHORTCUT=True
```

- `domain`: current task domain string.
- `signals`: dict of momentary numeric signals (`p_true`, `self_consistency`, `ood`).
- `chat`: injectable callable; `None` uses the default snap (pure, no Ollama today).

---

### 3. Post-Event Appraisal

**File:** `platform_core/orchestration/run_phase_mixin.py`
**Method:** After any batch of run events is available (e.g., post-attempt, post-subtask)
**Hook:** `integration.observe_run_events(state, events)`

```python
# Appraise events and write the PAD affect vector into self_state.
# OFF → no state change.
integration.observe_run_events(state, events)
```

- `events`: list of event dicts; each may have `outcome` ("success"/"failure"), `agency`, `novelty`.
- Internally calls `appraise(events)` + `set_affect` on the stored self_state.

---

### 4. Periodic Instinct Check (per run, at most once)

**File:** `platform_core/orchestration/run_phase_mixin.py`
**Method:** At a mid-run checkpoint (e.g., after N attempts or a phase boundary)
**Hook:** `integration.maybe_run_instinct(state, reflections, failure_modes, chat=chat, db_path=...)`

```python
# Fire the ledger-grounded instinct check; at most once per run.
# OFF → None immediately (chat callable never invoked).
flag = integration.maybe_run_instinct(state, reflections, failure_modes, chat=chat)
if flag:
    ...  # surface to Nightclaw / narration (PRISM-gated off verifier)
```

- `reflections`: recent SIE reflection dicts (from `memory/experience_*`).
- `failure_modes`: recent failure-mode dicts (from `memory/experience_*`).
- `chat`: injectable callable `(system, user) -> response`; `None` uses Ollama.

---

### 5. Teardown / Consolidation

**File:** `platform_core/orchestration/run_phase_mixin.py`
**Method:** `_runTeardown` (at run end, after verification)
**Hooks (three in sequence):**

```python
# 5a. Consolidation cycle (competence update, counterfactual, amendment drafts).
# OFF → None.
report = integration.at_teardown(
    state, scored_judgments, reflections, chat=chat
)

# 5b. Continuity letter (diachronic narrative; written regardless of the flag
#     once the human-nature layer is live — it is the anti-drift anchor).
from human_nature.continuity import write_letter
write_letter(task_id, body_state={"competence": ..., "affect": ...})

# 5c. Psyche post to Nightclaw / web dashboard (PRISM-gated; off accuracy paths).
# Only when a psyche surface cog is wired in via Spec A+B.
```

- `scored_judgments`: list of `{"domain": str, "correct": bool}` dicts assembled from
  the verify pass/fail results for this run.
- `reflections`: free-text strings from the SIE reflection pass.
- `chat`: optional counterfactual callable; `None` skips counterfactual (pure competence update).

---

### 6. A/B Metric Recording

**File:** `platform_core/orchestration/run_phase_mixin.py`
**Method:** `_runTeardown` (after verification, alongside teardown hooks)
**Hook:** `human_nature.ab_harness.record_run`

```python
from human_nature.ab_harness import record_run
import config

arm = "on" if config.HUMAN_NATURE_ENABLED else "off"
record_run(
    run_id=state["meta"]["run_id"],
    arm=arm,
    metrics={
        "test_pass": float(verify_passed),           # 1.0 / 0.0
        "time_to_green": elapsed_seconds,
        "commit_quality": commit_score,              # optional; from SIE or scorer
    },
)
```

- Both arms ("on" and "off") must accumulate enough rows before any behaviour-coupling
  flag can be promoted to ON-by-default. Use `ab_harness.compare()` to inspect deltas.
- DB is isolated per-test via the `_isolate_ab_harness_db` autouse fixture in `tests/conftest.py`.

---

## Flag Summary

| Config flag | Default | Effect when True |
|---|---|---|
| `HUMAN_NATURE_ENABLED` | `False` | Master switch; enables all hooks above |
| `HN_INTUITION_SHORTCUT` | `False` | Allows `route_pre_act` to return "fast" |
| `HN_OPINIONS_BEHAVIOR` | `False` | Unlocks opinion veto paths (Phase 3.2) |
| `HN_EMOTIONS_BEHAVIOR` | `False` | Unlocks emotion → behaviour coupling (Phase 3.5) |

No flag flips to `True` by default until the A/B harness shows non-inferior task outcomes.

---

## Files Touched at Merge Time

| File | Change |
|---|---|
| `platform_core/orchestration/run_phase_mixin.py` | Add hooks 1, 3, 4, 5, 6 |
| `platform_core/orchestration/execute_mixin.py` | Add hook 2 |
| `notifications/cv2.py` / `notifications/webdash.py` | Psyche surface integration (hook 5c) |
| `notifications/bot/cogs/` | `!psyche` / `!dial` / `!charter` / `!whatyouknow` / `!why-i-feel` |

Do NOT edit `run_phase_mixin.py` or `execute_mixin.py` before Spec A + Spec B land —
those files have unmerged concurrent edits; a 3-way touch would conflict.
