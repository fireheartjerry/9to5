# Human-Nature Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `human_nature/` layer — a functional cognitive architecture (the access-consciousness build) whose five faculties are projections of one `SelfState`, expressed honestly through the Cast, grounded in a calibrated conviction substrate.

**Architecture:** A plain-dict `SelfState` lives in `TaskState.meta["self_state"]` (no new serialization — the codebase stores state as dicts). A Conviction Engine (`momentary × track_record`, recalibrated) reads a SQLite Conviction Ledger and feeds every "earned" signal. Faculties are pure functions over `SelfState`; a Global Workspace broadcasts the winning faculty output as momentary "conscious content." All expression is PRISM-gated off the verifier; every behavior-coupling defaults OFF until an in-house A/B proves it.

**Tech Stack:** Python 3, stdlib `sqlite3`/`uuid`/`math`, pytest with the repo's autouse isolation fixtures, Ollama (mocked in tests) for the LLM-backed momentary signals, the existing `notifications/personas.py` Cast registry and `config` star-import pattern.

**Source spec:** `docs/superpowers/specs/2026-06-28-human-nature-insertion-design.md`
**Evidence:** `docs/plans/human-nature-research-digest-2026-06-28.md` (F1–F11)

---

## Scope & Decomposition

This layer is large (≈20 modules) and the spec sequences the build **after Spec A (`feat/observability-surfaces`) and Spec B (`feat/intelligence-control`) merge and stabilize**. Per the writing-plans scope rule, this document is a **master plan**:

- **Phase 1 (Substrate)** is written below as **complete, offline-testable, bite-sized TDD tasks** — no Ollama/Discord dependency, so it can be built and verified immediately, even before A+B merge, in an isolated worktree.
- **Phases 2–5** are specified as **task contracts** (files, exact interface signatures, concrete test cases, acceptance criteria, dependencies). Each phase **MUST be expanded into its own dated bite-sized plan at execution time**, against the *then-current* A+B interfaces (the LiveEventBus, Cast, Nightclaw Instinct, user_prefs all land via A+B and must not be guessed at now). This is deliberate decomposition, not deferred placeholders.

**Deviations from the spec, locked here for codebase consistency:**
- Conviction Ledger lives at `memory/conviction_ledger.py` (not `learning/`) — it mirrors the existing `memory/experience_*` SQLite ledger pattern.
- `TaskState.meta` gains only `self_state`, `autonomy`, `charter_version` (affect/morale/open_stances live *inside* `self_state`, avoiding duplication).
- The human-nature instinct module is `human_nature/instinct.py` and **wraps** Spec-B's `notifications/instinct.py` once merged; tests live in `tests/test_instinct_hn.py` to avoid colliding with Spec-B's `tests/test_instinct.py`.

---

## Conventions (apply to every task)

- **TDD:** write the failing test, run it red, write minimal code, run it green, commit. One action per step.
- **Tests:** pytest only (never bare unittest — live `.env` creds). The repo provides autouse fixtures (`tests/conftest.py`): `_isolate_state`, `_no_real_ollama`, `_no_real_discord`, `_isolate_experience_db`, `_fast_sleep`. Run a single file with `python tools/dev.py check tests/test_<name>.py` or `pytest tests/test_<name>.py -v`.
- **Module header:** every new module starts with the `@AI-MAP v1` docstring block (see `notifications/entry.py` for the canonical format) and `from __future__ import annotations`.
- **Style:** constants `ALL_CAPS`, normal vars `snake_case`, functions `camelCase` per the existing modules; match local style in files you touch.
- **Size:** ≤300 lines ideal / ≤450 hard (`python tools/size_audit.py` must show zero `must_split`). Functions ≤25 ideal / ≤70 hard.
- **After structure changes:** `python tools/repo_map.py` to regenerate `AGENTS.md` (don't hand-edit generated rows).
- **Commits:** frequent, one per task; message `feat(human-nature): <task>`.

---

## File Structure (locked)

| File | Responsibility | Phase |
|---|---|---|
| `human_nature/__init__.py` | package marker + @AI-MAP | 1 |
| `human_nature/self_state.py` | the unified interior dict + pure accessors (single source of truth) | 1 |
| `human_nature/conviction.py` | Conviction Engine: `momentary × track_record`, recalibration, cold-start | 1 |
| `human_nature/gating.py` | PRISM gate: expression allowed iff surface not accuracy-critical | 1 |
| `human_nature/drift.py` | output-layer drift heuristic (never self-report) | 1 |
| `memory/conviction_ledger.py` | SQLite judgment→outcome calibration store | 1 |
| `platform_core/app_config/human_nature.py` | config flags (all OFF), thresholds, model, db path | 1 |
| `human_nature/workspace.py` | Global Workspace (GWT): specialists compete → broadcast | 2 |
| `human_nature/attention_schema.py` | Attention Schema (AST): model of own attention | 2 |
| `human_nature/opinions.py` | tiered/domain/conviction-gated opinions + neutral-judge re-derivation | 3 |
| `human_nature/intuition.py` | System-1 pre-verbal signal + dual-process handoff | 3 |
| `human_nature/momentary.py` | black-box momentary providers: verbalized P(True), self-consistency | 3 |
| `human_nature/instinct.py` | ledger-grounded "something feels off" (wraps Spec-B instinct) | 3 |
| `human_nature/emotions.py` | PAD affect state + behavior/comms coupling | 3 |
| `human_nature/appraisal.py` | appraisal engine (Scherer/OCC vars → affect coordinate) | 3 |
| `human_nature/self_model.py` | metacognitive supervisor: competence, Johari, dissonance | 3 |
| `human_nature/autonomy.py` | earned-autonomy dynamic trust contract | 4 |
| `human_nature/character_vector.py` | TARS dials (structured, versioned traits) | 4 |
| `human_nature/charter.py` | Living Constitution propose/ratify | 4 |
| `human_nature/consolidation.py` | "sleep" cycle: consolidate, counterfactual, amend, schedule practice | 4 |
| `human_nature/continuity.py` | diachronic narrative self / letters to future self | 4 |
| `human_nature/user_model.py` | Theory-of-Mind of the user (dyad), service-only | 4 |
| `human_nature/psyche_surface.py` | web + Discord interior readouts | 5 |
| `docs/human-nature/cast-charter.md` | the versioned constitution document | 4 |

Modified (additive): `state/task_schema.py`, `tests/conftest.py`, `config.py`, `notifications/personas.py`, plus Phase-5 integration into `run_phase_mixin.py` / `execute_mixin.py` / `webdash.py` / `cv2.py` / bot cogs (expanded at execution, post-A+B).

---

## PHASE 1 — Substrate (bite-sized, offline-testable)

### Task 1.0: Scaffold the package

**Files:**
- Create: `human_nature/__init__.py`

- [ ] **Step 1: Create the package marker**

```python
"""human_nature — the human-nature layer: a functional cognitive architecture.

Faculties (opinions, intuition, instinct, emotions, self-awareness) are pure
projections of a single SelfState interior. This package owns the interior, the
conviction substrate, gating, and drift control. See
docs/superpowers/specs/2026-06-28-human-nature-insertion-design.md.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  (package)
DEPENDS-ON: (stdlib only)
SIDE-EFFECTS: none
RUN/TEST: python -m pytest tests/test_self_state.py
"""
from __future__ import annotations
```

- [ ] **Step 2: Commit**

```bash
git add human_nature/__init__.py
git commit -m "feat(human-nature): scaffold human_nature package"
```

---

### Task 1.1: Config knobs (all behavior-coupling OFF)

**Files:**
- Create: `platform_core/app_config/human_nature.py`
- Modify: `config.py` (add one star-import line, matching the existing block)
- Test: `tests/test_hn_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hn_config.py
import config

def test_behavior_flags_default_off():
    assert config.HUMAN_NATURE_ENABLED is False
    assert config.HN_OPINIONS_BEHAVIOR is False
    assert config.HN_EMOTIONS_BEHAVIOR is False
    assert config.HN_INTUITION_SHORTCUT is False

def test_thresholds_and_paths_present():
    assert config.HN_THETA_HARD > config.HN_THETA_SOFT
    assert config.HN_RECAL_TEMPERATURE > 1.0
    assert str(config.CONVICTION_DB_PATH).endswith("conviction.db")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_hn_config.py -v`
Expected: FAIL with `AttributeError: module 'config' has no attribute 'HUMAN_NATURE_ENABLED'`

- [ ] **Step 3: Write minimal implementation**

```python
# platform_core/app_config/human_nature.py
"""Human-nature layer configuration knobs.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  HUMAN_NATURE_ENABLED, HN_OPINIONS_BEHAVIOR, HN_EMOTIONS_BEHAVIOR,
  HN_INTUITION_SHORTCUT, HN_THETA_SOFT, HN_THETA_HARD, HN_RECAL_TEMPERATURE,
  HN_FAST_MODEL, CONVICTION_DB_PATH
DEPENDS-ON: os, platform_core.app_config.llm, platform_core.app_config.paths
SIDE-EFFECTS: reads environment variables at import
RUN/TEST: python -m pytest tests/test_hn_config.py
"""
from __future__ import annotations

import os

from platform_core.app_config.llm import _envBool, _envFloat
from platform_core.app_config.paths import PROJECT_ROOT

# Behaviour-coupling defaults OFF until an in-house A/B proves it (spec validation gate).
HUMAN_NATURE_ENABLED: bool = _envBool("HUMAN_NATURE_ENABLED", False)
HN_OPINIONS_BEHAVIOR: bool = _envBool("HN_OPINIONS_BEHAVIOR", False)
HN_EMOTIONS_BEHAVIOR: bool = _envBool("HN_EMOTIONS_BEHAVIOR", False)
HN_INTUITION_SHORTCUT: bool = _envBool("HN_INTUITION_SHORTCUT", False)

# Opinion veto thresholds (Q1/Q3): soft-vote vs hard-veto conviction floors.
HN_THETA_SOFT: float = _envFloat("HN_THETA_SOFT", 0.60)
HN_THETA_HARD: float = _envFloat("HN_THETA_HARD", 0.85)

# Conviction recalibration temperature (F11: RLHF overconfidence correction).
HN_RECAL_TEMPERATURE: float = _envFloat("HN_RECAL_TEMPERATURE", 2.5)

# Cheap Ollama model for the pre-verbal / fast faculties.
HN_FAST_MODEL: str = os.getenv("HN_FAST_MODEL", "qwen2.5:1.5b")

# Conviction ledger database (mirrors EXPERIENCE_DB_PATH location).
CONVICTION_DB_PATH = PROJECT_ROOT / "state" / "conviction.db"
```

Then add to `config.py` alongside the existing star-imports (after the `llm` line):

```python
from platform_core.app_config.human_nature import *  # noqa: E402, F401, F403
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_hn_config.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add platform_core/app_config/human_nature.py config.py tests/test_hn_config.py
git commit -m "feat(human-nature): config knobs (behavior-coupling OFF by default)"
```

---

### Task 1.2: SelfState — the unified interior

**Files:**
- Create: `human_nature/self_state.py`
- Test: `tests/test_self_state.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_self_state.py
from human_nature.self_state import (
    new_self_state, get_competence, observe_competence, set_affect,
)

def test_new_self_state_defaults():
    ss = new_self_state()
    assert ss["morale"] == 0.0
    assert ss["competence"] == {}
    assert ss["affect"] == {"valence": 0.0, "arousal": 0.0, "control": 0.0}
    assert ss["open_stances"] == []
    assert ss["convictions"] == []

def test_observe_competence_is_incremental_mean():
    ss = new_self_state()
    observe_competence(ss, "async", True)
    observe_competence(ss, "async", False)
    c = get_competence(ss, "async")
    assert c["n"] == 2
    assert abs(c["p"] - 0.5) < 1e-9

def test_unknown_domain_defaults_to_half():
    ss = new_self_state()
    assert get_competence(ss, "never_seen") == {"p": 0.5, "n": 0}

def test_set_affect_writes_pad_vector():
    ss = new_self_state()
    set_affect(ss, -0.4, 0.8, -0.2)
    assert ss["affect"] == {"valence": -0.4, "arousal": 0.8, "control": -0.2}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_self_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'human_nature.self_state'`

- [ ] **Step 3: Write minimal implementation**

```python
# human_nature/self_state.py
"""SelfState — the unified interior of the human-nature layer (a serializable dict).

The interior is a plain dict so it round-trips through TaskState.meta['self_state']
with no new serialization machinery. Faculties are pure functions over this dict;
this module owns its shape, defaults, and the basic competence/affect updates.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  new_self_state() -> dict -- fresh interior with neutral defaults
  get_competence(ss, domain) -> dict -- {"p","n"} calibrated competence (defaults p=0.5,n=0)
  observe_competence(ss, domain, success) -> None -- fold one outcome into competence (incremental mean)
  set_affect(ss, valence, arousal, control) -> None -- write the PAD affect vector
DEPENDS-ON: (stdlib only)
SIDE-EFFECTS: mutates the passed-in dict in place
RUN/TEST: python -m pytest tests/test_self_state.py
"""
from __future__ import annotations

from typing import Any

SCHEMA_VERSION = 1


def new_self_state() -> dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "competence": {},      # domain -> {"p": float, "n": int}
        "affect": {"valence": 0.0, "arousal": 0.0, "control": 0.0},
        "morale": 0.0,         # slow homeostat in [-1, 1]
        "convictions": [],     # crystallized stable stances
        "open_stances": [],    # live opinions this run
        "dissonance": 0.0,
    }


def get_competence(ss: dict[str, Any], domain: str) -> dict[str, Any]:
    return ss["competence"].get(domain, {"p": 0.5, "n": 0})


def observe_competence(ss: dict[str, Any], domain: str, success: bool) -> None:
    cur = get_competence(ss, domain)
    n = cur["n"] + 1
    p = cur["p"] + ((1.0 if success else 0.0) - cur["p"]) / n
    ss["competence"][domain] = {"p": p, "n": n}


def set_affect(ss: dict[str, Any], valence: float, arousal: float, control: float) -> None:
    ss["affect"] = {
        "valence": float(valence),
        "arousal": float(arousal),
        "control": float(control),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_self_state.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add human_nature/self_state.py tests/test_self_state.py
git commit -m "feat(human-nature): SelfState interior + competence/affect accessors"
```

---

### Task 1.3: TaskState carries the interior

**Files:**
- Modify: `state/task_schema.py` (add 3 keys to the `meta` dict inside `create()`)
- Test: `tests/test_task_schema_hn.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_task_schema_hn.py
from state.task_schema import TaskState

def test_create_has_human_nature_meta_fields():
    ts = TaskState.create("ship the thing", 1.0)
    meta = ts.data["meta"]
    for key in ("self_state", "autonomy", "charter_version"):
        assert key in meta
        assert meta[key] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_task_schema_hn.py -v`
Expected: FAIL with `KeyError` / `assert 'self_state' in meta`

- [ ] **Step 3: Write minimal implementation**

In `state/task_schema.py`, inside `TaskState.create()`'s `meta` dict, add three keys next to the existing optional fields (e.g. after `"discovery_report": None,`):

```python
            "self_state": None,      # human_nature interior (lazily initialised by the layer)
            "autonomy": None,        # human_nature earned-autonomy ceilings per domain
            "charter_version": None, # ratified Cast-charter version in effect
```

(Keep `state/` free of any `import human_nature` — the interior is initialised lazily by the layer, not the state module.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_task_schema_hn.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add state/task_schema.py tests/test_task_schema_hn.py
git commit -m "feat(human-nature): TaskState.meta carries self_state/autonomy/charter_version"
```

---

### Task 1.4: Conviction Engine (pure math)

**Files:**
- Create: `human_nature/conviction.py`
- Test: `tests/test_conviction.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_conviction.py
from human_nature.conviction import recalibrate, track_weight, compute_conviction

def test_recalibrate_pulls_extremes_toward_center():
    # temperature scaling (T>1) reduces overconfidence: 0.95 -> lower
    assert recalibrate(0.95, temperature=2.5) < 0.95
    assert abs(recalibrate(0.5, temperature=2.5) - 0.5) < 1e-9  # 0.5 stays 0.5

def test_cold_start_gives_no_teeth():
    # below MIN_SAMPLES, track contributes zero weight
    assert track_weight({"rate": 0.9, "total": 3}) == 0.0

def test_track_weight_uses_rate_when_seasoned():
    assert track_weight({"rate": 0.8, "total": 50}) == 0.8

def test_compute_conviction_is_momentary_times_track():
    track = {"rate": 1.0, "total": 50}      # full track, no recal scaling on history
    c = compute_conviction(0.5, track, recal=False)  # 0.5 * 1.0
    assert abs(c - 0.5) < 1e-9

def test_compute_conviction_zero_on_cold_start():
    assert compute_conviction(0.99, {"rate": 0.99, "total": 1}) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_conviction.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'human_nature.conviction'`

- [ ] **Step 3: Write minimal implementation**

```python
# human_nature/conviction.py
"""Conviction Engine — the single source of every "earned" signal.

conviction = recalibrate(momentary) * track_weight(track_record), clamped to [0,1].
Cold start (history below MIN_SAMPLES) yields zero teeth, so a new install cannot
veto on day one. Recalibration is temperature scaling (F11) to undo RLHF
overconfidence. The momentary signal itself is produced black-box elsewhere
(human_nature/momentary.py) because the closed API exposes no hidden states (F10).

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  recalibrate(p, temperature=2.5) -> float -- temperature-scale a probability via logit
  track_weight(track) -> float -- 0.0 below MIN_SAMPLES else track["rate"]
  compute_conviction(momentary, track, *, recal=True) -> float -- earned conviction in [0,1]
DEPENDS-ON: math
SIDE-EFFECTS: none (pure)
RUN/TEST: python -m pytest tests/test_conviction.py
"""
from __future__ import annotations

import math
from typing import Any

MIN_SAMPLES = 5  # cold-start floor: below this, track_record gives no teeth


def recalibrate(p: float, temperature: float = 2.5) -> float:
    p = min(max(float(p), 1e-6), 1.0 - 1e-6)
    logit = math.log(p / (1.0 - p)) / float(temperature)
    return 1.0 / (1.0 + math.exp(-logit))


def track_weight(track: dict[str, Any]) -> float:
    if int(track.get("total", 0)) < MIN_SAMPLES:
        return 0.0
    return float(track.get("rate", 0.0))


def compute_conviction(momentary: float, track: dict[str, Any], *, recal: bool = True) -> float:
    m = recalibrate(momentary) if recal else float(momentary)
    return max(0.0, min(1.0, m * track_weight(track)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_conviction.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add human_nature/conviction.py tests/test_conviction.py
git commit -m "feat(human-nature): Conviction Engine (momentary x track_record, cold-start)"
```

---

### Task 1.5: Conviction Ledger (SQLite) + test isolation

**Files:**
- Create: `memory/conviction_ledger.py`
- Modify: `tests/conftest.py` (add an autouse fixture isolating `CONVICTION_DB_PATH`)
- Test: `tests/test_conviction_ledger.py`

- [ ] **Step 1: Add the isolation fixture (so no test touches the real db)**

In `tests/conftest.py`, alongside `_isolate_experience_db`, add:

```python
@pytest.fixture(autouse=True)
def _isolate_conviction_db(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONVICTION_DB_PATH", tmp_path / "conviction.db", raising=False)
    yield
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_conviction_ledger.py
from memory.conviction_ledger import record_judgment, score_judgment, track_record

def test_unscored_judgments_do_not_count(tmp_path):
    db = tmp_path / "c.db"
    record_judgment(judgment_type="opinion", domain="async", conviction=0.7, db_path=db)
    tr = track_record("opinion", "async", db_path=db)
    assert tr == {"hits": 0, "total": 0, "rate": 0.0}

def test_scored_judgments_build_track_record(tmp_path):
    db = tmp_path / "c.db"
    j1 = record_judgment(judgment_type="opinion", domain="async", conviction=0.7, db_path=db)
    j2 = record_judgment(judgment_type="opinion", domain="async", conviction=0.7, db_path=db)
    assert score_judgment(j1, True, db_path=db) is True
    assert score_judgment(j2, False, db_path=db) is True
    tr = track_record("opinion", "async", db_path=db)
    assert tr["total"] == 2
    assert tr["hits"] == 1
    assert abs(tr["rate"] - 0.5) < 1e-9

def test_track_record_is_domain_scoped(tmp_path):
    db = tmp_path / "c.db"
    j = record_judgment(judgment_type="opinion", domain="async", conviction=0.7, db_path=db)
    score_judgment(j, True, db_path=db)
    assert track_record("opinion", "windows", db_path=db)["total"] == 0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_conviction_ledger.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'memory.conviction_ledger'`

- [ ] **Step 4: Write minimal implementation**

```python
# memory/conviction_ledger.py
"""Conviction Ledger — SQLite store of judgment -> outcome calibration.

Every opinion/flag/gut/prediction is recorded; reality later scores it (verify
pass/fail, user ack/override, run result). track_record() returns the per-type,
per-domain hit-rate that the Conviction Engine turns into "earned" teeth. Mirrors
the memory/experience_* SQLite pattern; owns its own table (clean ownership).

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  record_judgment(*, judgment_type, domain, conviction, db_path=None) -> str -- insert, return id
  score_judgment(judgment_id, correct, db_path=None) -> bool -- set outcome; True if a row updated
  track_record(judgment_type, domain, db_path=None) -> dict -- {"hits","total","rate"} over scored rows
DEPENDS-ON: sqlite3, uuid, datetime, pathlib, config
SIDE-EFFECTS: creates/writes the conviction SQLite db at CONVICTION_DB_PATH (or db_path)
RUN/TEST: python -m pytest tests/test_conviction_ledger.py
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS judgments (
  id            TEXT PRIMARY KEY,
  judgment_type TEXT NOT NULL,
  domain        TEXT NOT NULL,
  conviction    REAL NOT NULL,
  correct       INTEGER,
  created_at    TEXT NOT NULL
);
"""


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else config.CONVICTION_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    return conn


def record_judgment(*, judgment_type: str, domain: str, conviction: float,
                    db_path: Optional[Path] = None) -> str:
    jid = str(uuid.uuid4())
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO judgments (id, judgment_type, domain, conviction, correct, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (jid, judgment_type, domain, float(conviction), None,
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    return jid


def score_judgment(judgment_id: str, correct: bool, db_path: Optional[Path] = None) -> bool:
    with _connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE judgments SET correct = ? WHERE id = ?",
            (1 if correct else 0, judgment_id),
        )
        conn.commit()
        return cur.rowcount > 0


def track_record(judgment_type: str, domain: str, db_path: Optional[Path] = None) -> dict[str, Any]:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(correct), 0) AS hits FROM judgments"
            " WHERE judgment_type = ? AND domain = ? AND correct IS NOT NULL",
            (judgment_type, domain),
        ).fetchone()
    total = int(row["total"] or 0)
    hits = int(row["hits"] or 0)
    rate = (hits / total) if total else 0.0
    return {"hits": hits, "total": total, "rate": rate}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_conviction_ledger.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add memory/conviction_ledger.py tests/conftest.py tests/test_conviction_ledger.py
git commit -m "feat(human-nature): Conviction Ledger (SQLite) + test isolation"
```

---

### Task 1.6: PRISM gate

**Files:**
- Create: `human_nature/gating.py`
- Test: `tests/test_gating.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gating.py
from human_nature.gating import is_expression_allowed, ACCURACY_CRITICAL

def test_verifier_surfaces_are_blocked():
    for surface in ("verifier", "verdict", "test_judgment", "diff_correctness"):
        assert surface in ACCURACY_CRITICAL
        assert is_expression_allowed(surface) is False

def test_human_facing_surfaces_allowed():
    for surface in ("discord", "narration", "brief", "psyche", "pr"):
        assert is_expression_allowed(surface) is True

def test_case_and_whitespace_insensitive():
    assert is_expression_allowed("  VERIFIER ") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gating.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'human_nature.gating'`

- [ ] **Step 3: Write minimal implementation**

```python
# human_nature/gating.py
"""PRISM gate — persona/affect expression is allowed on human-facing surfaces only.

F2: personas raise UX but degrade discriminative accuracy, so expressive faculties
are gated OFF accuracy-critical paths. The verifier owns verdicts; affect never
colors a result.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  ACCURACY_CRITICAL -- frozenset of surfaces where expression is forbidden
  is_expression_allowed(surface) -> bool -- True iff surface is not accuracy-critical
DEPENDS-ON: (stdlib only)
SIDE-EFFECTS: none (pure)
RUN/TEST: python -m pytest tests/test_gating.py
"""
from __future__ import annotations

ACCURACY_CRITICAL = frozenset({"verifier", "verdict", "test_judgment", "diff_correctness"})


def is_expression_allowed(surface: str) -> bool:
    return (surface or "").strip().lower() not in ACCURACY_CRITICAL
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gating.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add human_nature/gating.py tests/test_gating.py
git commit -m "feat(human-nature): PRISM gate (expression off the verifier)"
```

---

### Task 1.7: Drift monitor (output-layer heuristic)

**Files:**
- Create: `human_nature/drift.py`
- Test: `tests/test_drift.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_drift.py
from human_nature.drift import measure_drift, has_drifted

def test_empty_window_is_no_drift():
    assert measure_drift([], 0.5) == 0.0

def test_aligned_window_is_no_drift():
    assert measure_drift([0.5, 0.5, 0.5], 0.5) == 0.0

def test_drift_is_mean_abs_deviation_capped_at_one():
    assert abs(measure_drift([0.2, 0.8], 0.5) - 0.3) < 1e-9
    assert measure_drift([5.0], 0.0) == 1.0  # capped

def test_has_drifted_threshold():
    assert has_drifted([0.9, 0.9], 0.5, threshold=0.3) is True
    assert has_drifted([0.55], 0.5, threshold=0.3) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_drift.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'human_nature.drift'`

- [ ] **Step 3: Write minimal implementation**

```python
# human_nature/drift.py
"""Drift monitor — measures expressed persona intensity vs the charter target.

F3: expressed persona decays over long runs while self-report stays stable, so we
measure at the OUTPUT layer, never by asking the agent. Phase 1 is a deterministic
heuristic over a window of expressed-intensity scores; a richer LLM tone comparison
can later feed the same inputs without changing this contract.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  measure_drift(expressed, target) -> float -- mean abs deviation from target, clamped [0,1]
  has_drifted(expressed, target, threshold=0.3) -> bool -- True iff drift >= threshold
DEPENDS-ON: (stdlib only)
SIDE-EFFECTS: none (pure)
RUN/TEST: python -m pytest tests/test_drift.py
"""
from __future__ import annotations

from typing import Sequence


def measure_drift(expressed: Sequence[float], target: float) -> float:
    if not expressed:
        return 0.0
    dev = sum(abs(float(x) - float(target)) for x in expressed) / len(expressed)
    return min(1.0, dev)


def has_drifted(expressed: Sequence[float], target: float, threshold: float = 0.3) -> bool:
    return measure_drift(expressed, target) >= threshold
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_drift.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add human_nature/drift.py tests/test_drift.py
git commit -m "feat(human-nature): output-layer drift monitor"
```

---

### Task 1.8: Phase-1 gate (size, repo-map, full focused suite)

- [ ] **Step 1: Size audit** — Run: `python tools/size_audit.py` · Expected: exit 0, zero `must_split`.
- [ ] **Step 2: Regenerate nav** — Run: `python tools/repo_map.py` · then `git add AGENTS.md` if tracked (note: `AGENTS.md` may be gitignored — skip if so).
- [ ] **Step 3: Run all Phase-1 tests** — Run: `pytest tests/test_hn_config.py tests/test_self_state.py tests/test_task_schema_hn.py tests/test_conviction.py tests/test_conviction_ledger.py tests/test_gating.py tests/test_drift.py -v` · Expected: all PASS.
- [ ] **Step 4: Commit** — `git commit -am "chore(human-nature): phase 1 substrate gate green"` (if repo_map changed tracked files).

---

## PHASES 2–5 — Task Contracts (expand each into its own dated plan at execution, post-A+B)

Each contract below specifies the interface, concrete test cases, and acceptance bar. At execution time, expand the contract into bite-sized TDD steps like Phase 1, reading the *then-current* A+B interfaces (LiveEventBus, Cast, Nightclaw Instinct, user_prefs) before writing code that touches them.

### PHASE 2 — Consciousness spine

**2.1 Global Workspace — `human_nature/workspace.py`**
- Interface: `class Workspace: register(name, specialist); def tick(state) -> dict` where each specialist is `callable(state) -> {"content": str, "salience": float}`; `tick` runs all specialists, selects max-salience, returns the winner as the broadcast `{"winner","content","salience","losers"}`; `broadcast(winner)` notifies every registered specialist.
- Tests: highest-salience specialist wins; ties broken deterministically (registration order); losers preserved; empty registry → `None`.
- Acceptance: pure/offline (specialists are injected callables); no Ollama. Behavior-coupling OFF (broadcast is informational until Phase 5 wiring).

**2.2 Attention Schema — `human_nature/attention_schema.py`**
- Interface: `class AttentionSchema: update(winner) -> None; focus() -> dict {"attending": str, "intensity": float, "faded": list}`.
- Tests: focus reflects last winner; intensity decays across `update`s without a refresh; faded list accumulates displaced content.
- Acceptance: pure/offline; feeds `psyche_surface` in Phase 5.

### PHASE 3 — Faculties (projections; expression-only, gated off verifier)

**3.1 Momentary providers — `human_nature/momentary.py`**
- Interface: `verbalized_p_true(question, *, chat=None) -> float` (Ollama MC/TF "P(True)" call, recalibrated via `conviction.recalibrate`); `self_consistency(sampler, n=5) -> float` (fraction agreeing); `cross_cast_agreement(votes) -> float`.
- Tests: Ollama mocked (autouse `_no_real_ollama`; inject a fake `chat`); P(True) parsed from "TRUE"/"FALSE"/prob; self_consistency over a deterministic sampler returns the agreement fraction; cross_cast over `["a","a","b"]` → 2/3.
- Acceptance: all network mocked; pure parsing logic unit-tested without a live model.

**3.2 Opinions — `human_nature/opinions.py`**
- Interface: `class Opinion {text, domain, conviction}`; `tier(conviction, domain) -> "cosmetic"|"soft"|"hard"` (uses `HN_THETA_SOFT/HARD`; hard only for domains `{"tactics","scope"}` i.e. D1/D2; goal-domain "goal"/D3 caps at soft; "self"/D4 always cosmetic-min); `rederive(user_assertion, my_stance, evidence) -> dict` implementing the neutral-judge re-frame (F5) — returns `{"hold"|"concede", "rationale"}` from a fresh comparison, never an in-thread fold.
- Tests: tier thresholds (below soft→cosmetic, between→soft, above hard in D1/D2→hard, above hard in D3→still soft); D4 never exceeds cosmetic; `rederive` calls the judge frame and returns a structured verdict (Ollama mocked); confident-but-evidence-free user assertion does NOT flip a high-conviction stance.
- Acceptance: tier logic pure; rederive uses mocked Ollama; **no veto path is wired to control** (expression-only) until A/B.

**3.3 Intuition — `human_nature/intuition.py`**
- Interface: `snap(domain, signals) -> {"p": float, "vibe": str, "ood": bool}` (fuses `momentary` providers + semantic-similarity-to-failures); `route(snap_result) -> "fast"|"deliberate"` (fast iff confident AND calibrated AND in-distribution AND `HN_INTUITION_SHORTCUT`).
- Tests: OOD flag forces "deliberate"; low confidence forces "deliberate"; with `HN_INTUITION_SHORTCUT=False`, always "deliberate" (default OFF); fused p is recalibrated; never gates verify (assert gating).
- Acceptance: providers mocked; shortcut behavior flag-gated OFF by default.

**3.4 Instinct — `human_nature/instinct.py`**
- Interface: `class HumanNatureInstinct: maybe_flag(state, reflections, failure_modes) -> Optional[str]` — ledger-grounded; wraps Spec-B `notifications/instinct.py` when present (import-guard: `try: from notifications import instinct` else degrade); strength from `conviction_ledger.track_record("instinct", domain)`; ≤1/run via `state.meta["instinct_flags"]`.
- Tests: returns None when nothing anomalous (mocked Ollama returns empty); respects once-per-run; degrades gracefully when `notifications.instinct` absent; logs each flag to the conviction ledger.
- Acceptance: Ollama mocked; absent-Spec-B path covered.

**3.5 Appraisal + Emotions — `human_nature/appraisal.py`, `human_nature/emotions.py`**
- Interface: `appraise(events) -> dict` (Scherer/OCC vars: goal_congruence, self_agency, novelty, certainty, coping → PAD coordinate); `emotion_label(pad) -> str` (region map); `couple(emotion, state) -> dict` (behavior intent + comms text; behavior only when `HN_EMOTIONS_BEHAVIOR`); `regulate(pad) -> pad` (decay + thrash-detection down-regulation); always emits the functional label string.
- Tests: clean run → satisfaction region; failure-streak → frustration; novelty → curiosity → `couple` returns "explore" intent (only when flag ON; OFF returns comms-only); mood (morale) biases an ambiguous appraisal negative when morale<0; every output carries `(functional: ...)`.
- Acceptance: pure appraisal math; behavior intents flag-gated; manipulation forbidden (expressed = honest readout, asserted by a test that `couple` never takes user-affect as input).

**3.6 Self-model — `human_nature/self_model.py`**
- Interface: `competence_report(ss, domain) -> dict {"p","interval","verdict"}`; `johari(ss, ood_signal, surprise) -> dict {"known_unknowns","unknown_unknowns"}`; `dissonance(felt, demonstrated, self_report, observed) -> dict {"overconfidence","drift"}`; `honest_phenomenology() -> str` (the access-vs-phenomenal answer, fixed honest text).
- Tests: low competence → verdict "ask for help / raise verification"; surprise spike → unknown-unknown surfaced; both dissonance channels computed; `honest_phenomenology()` never claims phenomenal experience and never dodges (assert key phrases present/absent).
- Acceptance: pure; the honest-phenomenology string is reviewed against the spec.

### PHASE 4 — Advanced systems

**4.1 Earned Autonomy — `human_nature/autonomy.py`**: `ceiling(domain, ledger) -> "cosmetic"|"soft"|"hard"` from Brier/track_record; `revoke_on_miscalibration(...)`. Tests: ceiling rises with proven calibration, drops on miscalibration; never exceeds proven reliability.

**4.2 Character Vector — `human_nature/character_vector.py`**: versioned trait dict `{honesty,humor,terseness,...}`; `set_dial(trait,value)`, `propose_change(...)` (propose-only), `version()`. Tests: dials clamp [0,100]; proposals never auto-apply; version increments on ratify only.

**4.3 Living Constitution — `human_nature/charter.py` + `docs/human-nature/cast-charter.md`**: `draft_amendment(evidence) -> proposal`; `ratify(proposal) -> version` (human-gated); `active_charter() -> dict`. Tests: amendments require explicit ratify; charter is read-authority; self-apply path is impossible (no function mutates the doc without a ratify token).

**4.4 Consolidation — `human_nature/consolidation.py`**: `run_cycle(state, ledger) -> report` (replay → competence update → counterfactual reflection → amendment drafts → practice schedule). Tests: updates competence from scored judgments; emits proposals not applications; Ollama mocked.

**4.5 Continuity — `human_nature/continuity.py`**: `write_letter(state) -> str` (what to keep, honest about loss); `read_letters(task_id) -> list`. Tests: letter is an inspectable artifact (saved to `state/tasks/<id>/letters/`), not hidden state; survives a simulated run boundary.

**4.6 User Model (dyad) — `human_nature/user_model.py`**: `update(observation)`, `snapshot() -> dict` (prefs, risk tolerance, attention, trust); strictly service-only. Tests: `snapshot` fully inspectable (backs `!whatyouknow`); a test asserts no function consumes the model to alter *timing* of asks (manipulation guard); persisted to `memory/user_prefs` namespace (Spec-B), not a hidden store.

### PHASE 5 — Surfaces + validation

**5.1 Cast sci-fi archetypes — `notifications/personas.py`**: add archetype personas (a Data, a TARS, a Jarvis) to `CAST`; selectable; Character-Vector tunes within one. Tests: new personas resolve via `persona(role)`; default unchanged.

**5.2 Psyche surface — `human_nature/psyche_surface.py`**: `render_web(ss) -> html_fragment` and `render_discord(ss) -> embed_dict` showing competence heatmap, mood-core, dissonance, autonomy curve, attention focus, charter version. Tests: renders from a `SelfState` dict; PRISM-gated (never rendered into a verifier surface).

**5.3 Discord commands** (cogs, post-Spec-B cog framework): `!psyche`, `!dial <trait> <n>`, `!charter`, `!whatyouknow`, `!why-i-feel`. Tests: command routers pure; Discord mocked.

**5.4 Run-loop integration** (`run_phase_mixin.py`, `execute_mixin.py`): workspace tick per phase, intuition pre-act read, emotion appraisal on events, instinct periodic, consolidation at teardown, psyche posts — **all behind `HUMAN_NATURE_ENABLED` and the per-faculty behavior flags**. Tests: with all flags OFF (default), the run loop behaves byte-identically to pre-layer (regression guard).

**5.5 A/B validation harness**: a flag-gated experiment mode that records, per Run, commit quality / test-pass / time-to-green with the layer's behavior-coupling ON vs OFF, written to the conviction ledger / experience ledger for offline comparison. Acceptance: **no behavior-coupling flag flips to ON-by-default until this harness shows non-inferior task outcomes.**

---

## Self-Review

**1. Spec coverage:** Substrate (Conviction Engine/Ledger, gating, drift, SelfState, config) → Phase 1 ✓. Consciousness stack (GWT/AST) → 2 ✓. Five faculties (opinions/intuition/instinct/emotions+appraisal/self-model) → 3 ✓. Advanced (autonomy/character-vector/charter/consolidation/continuity/user-model) → 4 ✓. Surfaces + sci-fi Cast + A/B gate → 5 ✓. Higher-order/interoceptive/IIT-integration are realized within self_model + appraisal + the shared workspace (no separate module, per spec). Parliament realized within Cast voting (momentary.cross_cast_agreement + opinions) — noted in 3.1/5.1. Honest-phenomenology → 3.6 ✓. Manipulation/welfare guards → tests in 3.5/4.6 ✓.

**2. Placeholder scan:** Phase 1 has complete code in every step. Phases 2–5 are explicit task *contracts* (interfaces + tests + acceptance), labeled for dated expansion — not "TODO"/"implement later" placeholders inside a bite-sized task.

**3. Type consistency:** `track_record` returns `{"hits","total","rate"}` in both the ledger (1.5) and the engine consumer (1.4, via `track_weight`). `SelfState` shape (`competence`/`affect`/`morale`/`open_stances`/`convictions`/`dissonance`) is consistent across 1.2 and its Phase-3/5 consumers. `is_expression_allowed`/`ACCURACY_CRITICAL` names match across 1.6 and the faculty acceptance criteria. Config names (`HN_THETA_SOFT/HARD`, `HN_*_BEHAVIOR`, `HN_INTUITION_SHORTCUT`, `CONVICTION_DB_PATH`) match between 1.1 and Phases 3–5.

---

## Execution Handoff

Phase 1 is ready to build now (offline, no A+B dependency). Phases 2–5 expand into their own dated plans after Spec A + Spec B merge and stabilize, against the real upstream interfaces.
