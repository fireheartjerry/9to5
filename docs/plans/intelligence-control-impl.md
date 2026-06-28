# Intelligence & Control (Spec B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the intelligence & control layer for 9to5 — preference memory, on-demand briefing, mid-run intent injection, brain dialogue, predictive flags, granular ControlBus controls, Nightclaw instinct, and visible self-improvement (wisdom/growth).

**Architecture:** Pure, network-free, fully-testable cores in `memory/`, `notifications/`, and `learning/`; thin Discord gateway shells (cogs + on_message listener) over those cores; new mid-run controls routed through `ControlBus` (booleans for hot-loop signals, queued ops for data mutations) and drained by the orchestrator control mixin. Every Ollama/Discord call is injectable so the suite never hits a live service. Source-of-truth ownership preserved: state store owns run state, ControlBus owns control commands.

**Tech Stack:** Python 3, stdlib + existing deps (ollama client injected, discord.py for cogs), pytest, the existing `llm_io` / `experience` (SQLite ledger) / `commands` spine.

**Source of truth:** `docs/superpowers/specs/2026-06-28-intelligence-control-design.md`. Companion Spec A (`feat/observability-surfaces`) owns `notifications/event_bus.py` (LiveEventBus), the wisdom-trail web column, codename/health_score/arc state fields, and self-reflection. Where Spec B references those, code against a defensive `state.meta.get(...)` seam and document it; do NOT reimplement Spec A.

---

## Conventions (every task)

- New modules MUST start with `from __future__ import annotations` and the `@AI-MAP v1` doc header (template in `.claude/rules/modularity.md`).
- ALL_CAPS constants, snake_case vars, camelCase functions (project style).
- Files ≤450 lines, functions ≤70 lines (`python tools/size_audit.py` must show zero `must_split`).
- Run tests with `python tools/dev.py check tests/<file>.py` (pytest sandbox) — NEVER bare `unittest` (live `.env` creds).
- All Ollama calls take an injectable `chat`/`brain` parameter; all tests inject a fake. Discord posting is best-effort and wrapped so absence is a no-op (conftest blanks the token).
- Commit after each task with a clear message.

---

## Spec A integration seams (document, don't build)

| Seam | Spec B usage | Defensive access |
|---|---|---|
| `state.meta["codename"]` | brief one-line, growth post | `state.meta.get("codename") or state.task_id[:8].upper()` |
| `state.meta["health_score"]` | brief one-line | `state.meta.get("health_score")` → render `—` if None |
| `notifications/event_bus.py` LiveEventBus | instinct event stream, `!brief raw` | fall back to `state.data["notifications"]` ring when bus absent |
| self-reflection post (teardown) | `!growth` auto-post follows it | growth post is independent; just fires at teardown |
| wisdom-trail web column | `!wisdom` Discord mirror | `!wisdom` reads `experience.fetch_reflections()` directly |

---

## File structure

**New modules**
- `memory/user_prefs.py` — preference store + NL `!prefer` / `!brief set` parsers (pure).
- `notifications/briefing.py` — `generate_brief(state, prefs, depth, *, chat=None)` + depth renderers (pure core, injectable chat).
- `notifications/brain_dialogue.py` — `build_context` + `answer` for `!why`/`!explain`/`!plan-rationale`/`!ask` (pure, injectable chat).
- `notifications/predictive.py` — `PredictiveFlags` heuristic engine (+ optional Ollama enhancement) (pure, injectable data + chat).
- `notifications/instinct.py` — `NightclawInstinct` periodic-call builder + `maybe_fire` (pure, injectable chat).
- `learning/wisdom.py` — `wisdomTrail(state, reflections)` + `growthSummary(...)` (pure, reads experience ledger).
- `notifications/bot/cogs/log_cog.py` — gateway shell: slash `/brief /why /explain /wisdom /growth /intent /prefer /prefs` + a `Cog.listener` `on_message` for the Ollama-backed `!brief /!why /!explain /!ask /!wisdom /!growth` bang commands.
- `notifications/bot/cogs/context_cog.py` — 3 context-menu commands (Explain / Why / Brief-here), thin shells over the same cores.

**Modified**
- `state/task_schema.py` — additive: `user_intents`, `instinct_flags` in `create()`; methods `addIntent/clearIntents/activeIntents/addInstinctFlag/extendDeadline`.
- `platform_core/runtime/control.py` — additive bus fields/methods: `kill_subprocess`, `force_replan` booleans; new queued-op kinds consumed by the control mixin.
- `notifications/commands.py` — additive registry rows + `applyCommand` branches for the FAST control commands (`intent/effort/mode/replan/deadline/kill/inject/set-effort/prefer/prefs`).
- `platform_core/orchestration/control_mixin.py` — `_applyOps` handles new op kinds (intent, intent_clear, inject_context, set_effort, set_run_effort, extend_deadline).
- `platform_core/orchestration/execute_mixin.py` — kill-subprocess wired into `cancel_check`; per-sid effort override + injected-context fold into the attempt.
- `platform_core/orchestration/plan_mixin.py` — `authorInvocationSpec` folds active intents + injected context + per-sid effort override deterministically into the spec.
- `platform_core/orchestration/run_loop_mixin.py` — force-replan check + deadline-extend already honored via meta; instinct periodic trigger call site.
- `platform_core/orchestration/run_phase_mixin.py` — `_maybeInstinct` periodic call; `_postGrowth` at teardown.
- `notifications/cv2.py` — additive cockpit Section header + 3 select stubs (subtask/effort/mode) in the component tree.
- `notifications/bot/core.py` — register the two new cogs in `EXTENSIONS`.
- `platform_core/app_config/llm.py` — additive config constants (`BRIEF_MODEL`, `BRAIN_DIALOGUE_SYSTEM_PROMPT`, `INSTINCT_*`, `PREDICTIVE_*`).

**Tests** (all pytest, all mocked): `tests/test_user_prefs.py`, `tests/test_briefing.py`, `tests/test_intent_injection.py`, `tests/test_brain_dialogue.py`, `tests/test_predictive_flags.py`, `tests/test_instinct.py`, `tests/test_log_cog.py`, `tests/test_context_cog.py`.

---

## Task 0: Branch + config constants

**Files:**
- Modify: `platform_core/app_config/llm.py` (append a new section near the other knobs)

- [ ] **Step 1: Confirm branch**

Run: `git branch --show-current`
Expected: `feat/intelligence-control`

- [ ] **Step 2: Add config constants** (append after the `# --- Effort levels ---` block in `platform_core/app_config/llm.py`)

```python
# --- Intelligence & Control (Spec B) -------------------------------------
# Cheapest/fastest model for the on-demand briefing + brain-dialogue calls.
BRIEF_MODEL: str = os.getenv("BRIEF_MODEL", OLLAMA_MODEL)
BRAIN_DIALOGUE_SYSTEM_PROMPT: str = os.getenv(
    "BRAIN_DIALOGUE_SYSTEM_PROMPT",
    "You are the reasoning core of the 9to5 orchestrator brain, answering the operator "
    "mid-run in the voice of a thoughtful engineer explaining their own work. Use ONLY the "
    "plan + state provided. Be direct, concrete, 1-4 sentences. Reference subtask ids "
    "(st-00N). Explain dependency/ordering reasons honestly; never invent results.")
# Predictive flags: heuristic-first; optional NL explanation gated off by default (fast).
PREDICTIVE_FLAGS_ENABLED: bool = _envBool("PREDICTIVE_FLAGS_ENABLED", True)
PREDICTIVE_FLAG_OLLAMA: bool = _envBool("PREDICTIVE_FLAG_OLLAMA", False)
PREDICTIVE_FLAG_MIN_INTERVAL_SECONDS: float = _envFloat("PREDICTIVE_FLAG_MIN_INTERVAL_SECONDS", 90)
# Nightclaw instinct: periodic "something feels off" call, at most once per run.
INSTINCT_ENABLED: bool = _envBool("INSTINCT_ENABLED", True)
INSTINCT_INTERVAL_SECONDS: float = _envFloat("INSTINCT_INTERVAL_SECONDS", 900)  # ~15 min
INSTINCT_SYSTEM_PROMPT: str = os.getenv(
    "INSTINCT_SYSTEM_PROMPT",
    "You are 9to5's pattern-recognition layer. Read the current run state and your accumulated "
    "experience. If anything feels wrong or unexpected -- even if you can't articulate why -- say "
    "so in ONE sentence. If everything looks normal, respond with exactly an empty line. Do not "
    "explain, do not list evidence. Trust your pattern.")
```

- [ ] **Step 3: Verify import**

Run: `python tools/dev.py check platform_core/app_config/llm.py`
Expected: PASS (mapped test `tests/test_llm_io_pydantic.py` green). Then `python -c "import config; print(config.BRIEF_MODEL, config.INSTINCT_INTERVAL_SECONDS, config.PREDICTIVE_FLAGS_ENABLED)"`.

- [ ] **Step 4: Commit**

```bash
git add platform_core/app_config/llm.py
git commit -m "feat(intel): add Spec B config constants (brief/instinct/predictive)"
```

---

## Task 1: `memory/user_prefs.py` (foundation)

**Files:**
- Create: `memory/user_prefs.py`
- Test: `tests/test_user_prefs.py`

Path strategy: default file = `Path(config.STATE_DIR).parent / "user_prefs.json"`, resolved at **call time** so the conftest `STATE_DIR` monkeypatch isolates every test. All functions accept an optional `path` override.

- [ ] **Step 1: Write the failing test** (`tests/test_user_prefs.py`)

```python
"""Tests for the cross-session user-preference store + NL prefer/brief-set parsers."""
import json

from memory import user_prefs


def test_load_returns_defaults_when_absent(tmp_path):
    prefs = user_prefs.load(path=tmp_path / "p.json")
    assert prefs["brief_default_depth"] == "standard"
    assert prefs["brief_include_cost"] is True
    assert prefs["instinct_enabled"] is True


def test_set_pref_persists(tmp_path):
    p = tmp_path / "p.json"
    user_prefs.set_pref("brief_include_cost", False, path=p)
    assert user_prefs.load(path=p)["brief_include_cost"] is False
    assert json.loads(p.read_text())["brief_include_cost"] is False


def test_reset_restores_defaults(tmp_path):
    p = tmp_path / "p.json"
    user_prefs.set_pref("brief_tone", "minimal", path=p)
    user_prefs.reset(path=p)
    assert user_prefs.load(path=p)["brief_tone"] == "colleague"


def test_unknown_key_rejected(tmp_path):
    p = tmp_path / "p.json"
    assert user_prefs.set_pref("not_a_key", 1, path=p) is None
    assert "not_a_key" not in user_prefs.load(path=p)


def test_parse_prefer_brief_without_cost():
    assert user_prefs.parsePreferIntent("brief without cost") == ("brief_include_cost", False)


def test_parse_prefer_no_tool_call_narration():
    assert user_prefs.parsePreferIntent("no tool-call narration") == (
        "narration_include_tool_calls", False)


def test_parse_prefer_deep_and_one_line():
    assert user_prefs.parsePreferIntent("deep") == ("default_detail_level", "deep")
    assert user_prefs.parsePreferIntent("one-line") == ("default_detail_level", "one-line")


def test_parse_brief_set_tool_calls_off():
    assert user_prefs.parseBriefSet("set tool-calls off") == ("brief_include_tool_calls", False)


def test_parse_prefer_unknown_returns_none():
    assert user_prefs.parsePreferIntent("make me a sandwich") is None


def test_apply_prefer_persists_and_reports(tmp_path):
    p = tmp_path / "p.json"
    msg = user_prefs.applyPrefer("brief without cost", path=p)
    assert "cost" in msg.lower()
    assert user_prefs.load(path=p)["brief_include_cost"] is False


def test_format_prefs_is_readable(tmp_path):
    out = user_prefs.formatPrefs(user_prefs.load(path=tmp_path / "p.json"))
    assert "brief_default_depth" in out
```

- [ ] **Step 2: Run test, expect failure**

Run: `python tools/dev.py check tests/test_user_prefs.py`
Expected: FAIL (module `memory.user_prefs` not found).

- [ ] **Step 3: Implement `memory/user_prefs.py`**

```python
"""Cross-session user-preference store + natural-language prefer/brief-set parsers.

A small JSON file (default ``<state_dir>/../user_prefs.json``) holding the operator's
briefing/narration/alert/detail preferences. Pure + injectable path so the suite isolates
every test. Never raises: a missing/corrupt file degrades to defaults.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  DEFAULTS  -- the default preference dict
  load(path=None) -> dict  -- merged defaults + stored prefs
  save(prefs, path=None) -> bool
  get(key, path=None)
  set_pref(key, value, path=None) -> Optional[dict]  -- None if key unknown
  reset(path=None) -> dict
  parsePreferIntent(text) -> Optional[tuple[str, object]]  -- NL "!prefer ..." -> (key, value)
  parseBriefSet(text) -> Optional[tuple[str, object]]  -- "!brief set ..." -> (key, value)
  applyPrefer(text, path=None) -> str  -- parse+persist+human reply
  applyBriefSet(text, path=None) -> str
  formatPrefs(prefs) -> str
DEPENDS-ON: config
SIDE-EFFECTS: writes user_prefs.json
RUN/TEST: python -m pytest tests/test_user_prefs.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import config

LOG = config.getLogger("user_prefs")

DEFAULTS: dict = {
    "brief_default_depth": "standard",
    "brief_include_cost": True,
    "brief_include_adversary": True,
    "brief_include_discovery": True,
    "brief_include_tool_calls": False,
    "brief_tone": "colleague",
    "narration_include_tool_calls": False,
    "narration_subtask_transitions": True,
    "narration_adversary_events": True,
    "narration_replan_events": True,
    "narration_moments": True,
    "predictive_flags_enabled": True,
    "instinct_enabled": True,
    "flag_min_severity": "medium",
    "default_detail_level": "standard",
    "persistent_intents": [],
}

_DEPTHS = ("one-line", "standard", "deep", "raw")


def _path(path: Optional[Path]) -> Path:
    if path is not None:
        return Path(path)
    return Path(config.STATE_DIR).parent / "user_prefs.json"


def load(path: Optional[Path] = None) -> dict:
    """Merged defaults + stored prefs. Missing/corrupt -> a fresh copy of DEFAULTS."""
    merged = {**DEFAULTS, "persistent_intents": list(DEFAULTS["persistent_intents"])}
    try:
        raw = json.loads(_path(path).read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for k, v in raw.items():
                if k in DEFAULTS:
                    merged[k] = v
    except FileNotFoundError:
        pass
    except Exception as e:  # noqa: BLE001 -- corrupt file degrades to defaults
        LOG.warning("user_prefs load failed (defaults used): %s", e)
    return merged


def save(prefs: dict, path: Optional[Path] = None) -> bool:
    try:
        p = _path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(prefs, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception as e:  # noqa: BLE001
        LOG.warning("user_prefs save failed (ignored): %s", e)
        return False


def get(key: str, path: Optional[Path] = None):
    return load(path).get(key, DEFAULTS.get(key))


def set_pref(key: str, value, path: Optional[Path] = None) -> Optional[dict]:
    """Persist one key. Returns the updated prefs, or None if the key is unknown."""
    if key not in DEFAULTS:
        return None
    prefs = load(path)
    prefs[key] = value
    save(prefs, path)
    return prefs


def reset(path: Optional[Path] = None) -> dict:
    fresh = {**DEFAULTS, "persistent_intents": []}
    save(fresh, path)
    return fresh


# ---- natural-language parsers (pure) ---------------------------------------
def parsePreferIntent(text: str) -> Optional[tuple[str, object]]:
    """Map a short '!prefer ...' phrase to a (key, value). None when nothing matches."""
    t = (text or "").strip().lower()
    if not t:
        return None
    # detail-level shortcuts
    if t in _DEPTHS:
        return ("default_detail_level", t)
    table = [
        (("without cost", "no cost"), ("brief_include_cost", False)),
        (("with cost",), ("brief_include_cost", True)),
        (("without adversary", "no adversary"), ("brief_include_adversary", False)),
        (("without discovery", "no discovery"), ("brief_include_discovery", False)),
        (("no tool-call narration", "no tool call narration",
          "without tool-call narration"), ("narration_include_tool_calls", False)),
        (("with tool-call narration",), ("narration_include_tool_calls", True)),
        (("no predictive flags", "disable predictive flags"), ("predictive_flags_enabled", False)),
        (("no instinct", "disable instinct"), ("instinct_enabled", False)),
    ]
    for phrases, kv in table:
        if any(p in t for p in phrases):
            return kv
    if t.startswith("tone "):
        tone = t.split(maxsplit=1)[1].strip()
        if tone in ("colleague", "analyst", "minimal"):
            return ("brief_tone", tone)
    return None


def parseBriefSet(text: str) -> Optional[tuple[str, object]]:
    """Map '!brief set <field> <on|off>' to (key, value)."""
    t = (text or "").strip().lower()
    if t.startswith("set "):
        t = t[4:].strip()
    parts = t.split()
    if len(parts) != 2 or parts[1] not in ("on", "off"):
        return None
    field_map = {
        "cost": "brief_include_cost",
        "adversary": "brief_include_adversary",
        "discovery": "brief_include_discovery",
        "tool-calls": "brief_include_tool_calls",
        "tool_calls": "brief_include_tool_calls",
    }
    key = field_map.get(parts[0])
    if not key:
        return None
    return (key, parts[1] == "on")


def applyPrefer(text: str, path: Optional[Path] = None) -> str:
    kv = parsePreferIntent(text)
    if kv is None:
        return ("Could not parse that preference. Try: `!prefer brief without cost`, "
                "`!prefer no tool-call narration`, `!prefer deep`, `!prefer tone analyst`.")
    set_pref(kv[0], kv[1], path)
    return f"Preference saved: `{kv[0]}` = `{kv[1]}` (applies to this run and all future runs)."


def applyBriefSet(text: str, path: Optional[Path] = None) -> str:
    kv = parseBriefSet(text)
    if kv is None:
        return "usage: `!brief set <cost|adversary|discovery|tool-calls> <on|off>`"
    set_pref(kv[0], kv[1], path)
    return f"Briefing preference saved: `{kv[0]}` = `{kv[1]}`."


def formatPrefs(prefs: dict) -> str:
    lines = ["**9TO5 preferences**"]
    for k in DEFAULTS:
        if k == "persistent_intents":
            continue
        lines.append(f"`{k}` = `{prefs.get(k, DEFAULTS[k])}`")
    pers = prefs.get("persistent_intents") or []
    if pers:
        lines.append("**persistent intents:** " + "; ".join(str(p) for p in pers))
    return "\n".join(lines)
```

- [ ] **Step 4: Run test, expect pass**

Run: `python tools/dev.py check tests/test_user_prefs.py`
Expected: PASS (all tests green).

- [ ] **Step 5: Commit**

```bash
git add memory/user_prefs.py tests/test_user_prefs.py
git commit -m "feat(intel): user preference store + prefer/brief-set NL parsers"
```

---

## Task 2: `notifications/briefing.py` + `!brief`

**Files:**
- Create: `notifications/briefing.py`
- Test: `tests/test_briefing.py`

Depth levels: `one-line` and `raw` are **deterministic** (no Ollama, instant). `standard` and `deep` synthesize via an injected `chat(system, user) -> str`; deep prepends a deterministic breakdown. Default depth comes from prefs (`brief_default_depth`, overridden by `default_detail_level` when set away from "standard").

- [ ] **Step 1: Write the failing test** (`tests/test_briefing.py`)

```python
"""Tests for the on-demand briefing generator (depth levels + preference tuning)."""
from notifications import briefing
from memory import user_prefs


class _State:
    def __init__(self):
        self.task_id = "abcd1234-0000"
        self.meta = {"goal_raw": "Fix the connection pool", "status": "executing",
                     "control_mode": "watch", "started_at": "2026-06-28T09:00:00",
                     "deadline_at": "2026-06-28T10:00:00", "codename": "IRON_PHOENIX",
                     "health_score": 87}
        self.subtasks = [
            {"subtask_id": "st-001", "title": "scaffold", "status": "done",
             "verify_result": {"passed": True}},
            {"subtask_id": "st-002", "title": "pool fix", "status": "done",
             "verify_result": {"passed": True}},
            {"subtask_id": "st-003", "title": "wire it", "status": "in_progress"},
        ]
        self.data = {"notifications": [{"at": "t", "kind": "subtask_done", "detail": "st-002"}],
                     "adversary_reviews": []}


def test_one_line_is_deterministic_and_single_line():
    out = briefing.generate_brief(_State(), user_prefs.DEFAULTS, depth="one-line")
    assert "\n" not in out.strip()
    assert "IRON_PHOENIX" in out
    assert "st-003" in out


def test_raw_returns_event_snapshot():
    out = briefing.generate_brief(_State(), user_prefs.DEFAULTS, depth="raw")
    assert "subtask_done" in out


def test_standard_uses_injected_chat():
    seen = {}

    def chat(system, user):
        seen["user"] = user
        return "IRON_PHOENIX is moving; st-003 active. ETA ~10min."

    out = briefing.generate_brief(_State(), user_prefs.DEFAULTS, depth="standard", chat=chat)
    assert "st-003" in out
    assert "IRON_PHOENIX" in seen["user"]  # context carried the codename


def test_standard_degrades_when_chat_offline():
    def boom(system, user):
        raise RuntimeError("ollama down")

    out = briefing.generate_brief(_State(), user_prefs.DEFAULTS, depth="standard", chat=boom)
    # falls back to the deterministic one-line so the operator always gets an answer
    assert "IRON_PHOENIX" in out


def test_deep_includes_subtask_breakdown():
    out = briefing.generate_brief(_State(), user_prefs.DEFAULTS, depth="deep",
                                  chat=lambda s, u: "synth")
    assert "st-001" in out and "st-002" in out and "st-003" in out


def test_default_depth_follows_prefs():
    prefs = dict(user_prefs.DEFAULTS, brief_default_depth="one-line")
    out = briefing.generate_brief(_State(), prefs, depth=None)
    assert "\n" not in out.strip()


def test_cost_pref_off_drops_cost_from_context():
    prefs = dict(user_prefs.DEFAULTS, brief_include_cost=False)
    seen = {}
    briefing.generate_brief(_State(), prefs, depth="standard",
                            chat=lambda s, u: seen.setdefault("u", u) or "ok")
    assert "cost" not in seen["u"].lower()
```

- [ ] **Step 2: Run test, expect failure**

Run: `python tools/dev.py check tests/test_briefing.py`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `notifications/briefing.py`**

Key requirements: `resolveDepth(prefs, depth)`; `_oneLine(state)` deterministic (codename · pct · current sid · health · ETA — reuse `_pct`/ETA math locally, mirror `cv2.etaStr` logic but inline to avoid a cycle); `_raw(state)` last-50 notification lines; `_context(state, prefs)` compact text honoring cost/adversary/discovery/tool-call prefs + `brief_tone`; `generate_brief` dispatches by depth and falls back to `_oneLine` on any chat error. `_defaultChat` builds an `ollama.Client` using `config.BRIEF_MODEL` (pragma no cover). Full module ≤300 lines; each function ≤25 lines (split deep breakdown into `_deepBreakdown(state)`).

```python
"""On-demand briefing generator -- preference-tuned, depth-leveled, never blocks a run.

Pure core: ``generate_brief(state, prefs, depth, *, chat=None)``. one-line and raw are
deterministic (instant); standard and deep synthesize a colleague-voice paragraph via an
injectable ``chat(system, user) -> str`` (defaults to a cheap Ollama call on config.BRIEF_MODEL).
Any chat failure degrades to the deterministic one-line so the operator always gets an answer.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  resolveDepth(prefs, depth) -> str
  generate_brief(state, prefs, depth=None, *, chat=None) -> str
DEPENDS-ON: config, llm_io
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/test_briefing.py
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

import config
import llm_io

LOG = config.getLogger("briefing")
_DEPTHS = ("one-line", "standard", "deep", "raw")


def resolveDepth(prefs: dict, depth: Optional[str]) -> str:
    if depth in _DEPTHS:
        return depth
    detail = (prefs or {}).get("default_detail_level")
    if detail in _DEPTHS and detail != "standard":
        return detail
    d = (prefs or {}).get("brief_default_depth", "standard")
    return d if d in _DEPTHS else "standard"


def _codename(state) -> str:
    return state.meta.get("codename") or state.task_id[:8].upper()


def _progress(state):
    subs = [s for s in state.subtasks if s.get("status") != "removed"]
    done = sum(1 for s in subs if s.get("status") == "done")
    total = max(len(subs), 1)
    return done, total


def _current(state):
    return (next((s for s in state.subtasks if s.get("status") == "in_progress"), None)
            or next((s for s in state.subtasks if s.get("status") == "pending"), None))


def _eta(state, done: int, total: int) -> str:
    try:
        start = datetime.fromisoformat(str(state.meta.get("started_at")))
        now = datetime.now(start.tzinfo) if start.tzinfo else datetime.now()
        elapsed = (now - start).total_seconds()
        remaining = total - done
        if done <= 0 or remaining <= 0 or elapsed <= 0:
            return "—"
        mins = int((elapsed / done) * remaining / 60)
        return f"~{mins}min" if mins else "~<1min"
    except Exception:  # noqa: BLE001
        return "—"


def _oneLine(state) -> str:
    done, total = _progress(state)
    pct = int(100 * done / total)
    cur = _current(state)
    cur_txt = f"{cur['subtask_id']} active" if cur else "idle"
    health = state.meta.get("health_score")
    health_txt = f"⬤ {health} health · " if health is not None else ""
    return f"{_codename(state)} · {pct}% · {cur_txt} · {health_txt}{_eta(state, done, total)}"


def _raw(state) -> str:
    notifs = (state.data.get("notifications") or [])[-50:]
    lines = [f"{n.get('at','')} {n.get('kind','?')}: {n.get('detail','')}" for n in notifs]
    return "```\n" + ("\n".join(lines) or "(no events)") + "\n```"


def _deepBreakdown(state, prefs: dict) -> str:
    lines = [f"**{_codename(state)}** deep brief"]
    for s in state.subtasks:
        vr = s.get("verify_result") or {}
        mark = " ✅" if vr.get("passed") else (" ❌" if vr else "")
        lines.append(f"- `{s['subtask_id']}` [{s.get('status')}]{mark} {s.get('title','')}")
    if prefs.get("brief_include_adversary"):
        advs = state.data.get("adversary_reviews") or []
        lines.append(f"adversary reviews: {len(advs)}")
    if prefs.get("brief_include_discovery"):
        dr = state.meta.get("discovery_report")
        if dr:
            lines.append(f"discovery findings: {len(dr.get('findings', []))}")
    return "\n".join(lines)


def _context(state, prefs: dict) -> str:
    done, total = _progress(state)
    cur = _current(state)
    parts = [
        f"CODENAME: {_codename(state)}", f"GOAL: {state.meta.get('goal_raw','')}",
        f"STATUS: {state.meta.get('status','?')} | PROGRESS: {done}/{total}",
        f"CURRENT: {(cur['subtask_id'] + ' ' + cur['title']) if cur else '—'}",
        f"TONE: {prefs.get('brief_tone','colleague')}",
    ]
    for s in state.subtasks:
        vr = s.get("verify_result") or {}
        mark = " PASS" if vr.get("passed") else (" FAIL" if vr else "")
        parts.append(f"  {s['subtask_id']} [{s.get('status')}]{mark} {s.get('title','')}")
    if prefs.get("brief_include_adversary"):
        parts.append(f"ADVERSARY_REVIEWS: {len(state.data.get('adversary_reviews') or [])}")
    if prefs.get("brief_include_cost"):
        parts.append("COST: include a cost line if cost data is present")
    notifs = (state.data.get("notifications") or [])[-8:]
    parts.append("RECENT: " + "; ".join(n.get("kind", "?") for n in notifs))
    return "\n".join(parts)


def _systemPrompt(prefs: dict) -> str:
    tone = prefs.get("brief_tone", "colleague")
    voice = {"colleague": "a sharp colleague giving a quick verbal update",
             "analyst": "a precise analyst stating facts",
             "minimal": "a terse status line, no flourish"}.get(tone, "a sharp colleague")
    return ("You are Nightclaw briefing the 9to5 operator on the CURRENT run. Write as "
            f"{voice}. 2-4 sentences, concrete, reference subtask ids, end with an ETA if known. "
            "Use ONLY the state provided; never invent results.")


def _defaultChat(system: str, user: str) -> str:  # pragma: no cover -- needs live Ollama
    import ollama
    client = ollama.Client(host=config.OLLAMA_HOST, timeout=config.OLLAMA_TIMEOUT_SECONDS)
    resp = client.chat(model=config.BRIEF_MODEL,
                       messages=[{"role": "system", "content": system},
                                 {"role": "user", "content": user}],
                       options={"num_ctx": config.OLLAMA_NUM_CTX},
                       keep_alive=config.OLLAMA_KEEP_ALIVE)
    return llm_io.responseText(resp)


def generate_brief(state, prefs: dict, depth: Optional[str] = None, *,
                   chat: Optional[Callable[[str, str], str]] = None) -> str:
    prefs = prefs or {}
    depth = resolveDepth(prefs, depth)
    if depth == "one-line":
        return _oneLine(state)
    if depth == "raw":
        return _raw(state)
    chat = chat or _defaultChat
    try:
        body = (chat(_systemPrompt(prefs), _context(state, prefs)) or "").strip()
    except Exception:  # noqa: BLE001
        LOG.warning("brief chat failed; degrading to one-line", exc_info=True)
        body = ""
    if not body:
        body = _oneLine(state)
    if depth == "deep":
        return _deepBreakdown(state, prefs) + "\n\n" + body
    return body
```

- [ ] **Step 4: Run test, expect pass**

Run: `python tools/dev.py check tests/test_briefing.py`
Expected: PASS.

- [ ] **Step 5: size_audit + commit**

```bash
python tools/size_audit.py
git add notifications/briefing.py tests/test_briefing.py
git commit -m "feat(intel): on-demand briefing generator with depth levels"
```

---

## Task 3: Intent injection — schema, ControlBus ops, `!intent`, spec fold

**Files:**
- Modify: `state/task_schema.py` (additive methods + `create()` fields)
- Modify: `platform_core/runtime/control.py` (boolean bus fields)
- Modify: `notifications/commands.py` (registry + applyCommand)
- Modify: `platform_core/orchestration/control_mixin.py` (`_applyOps` op kinds)
- Modify: `platform_core/orchestration/plan_mixin.py` (`authorInvocationSpec` fold)
- Test: `tests/test_intent_injection.py`

- [ ] **Step 1: Write the failing test** (`tests/test_intent_injection.py`)

```python
"""Intent injection: schema methods, command routing -> bus op, _applyOps, and spec fold."""
import config
from state.task import TaskState
from platform_core.runtime.control import ControlBus
from notifications import commands as spine


def _mk(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path, raising=False)
    monkeypatch.setattr(config, "CONTROL_DIR", tmp_path, raising=False)
    st = TaskState.create("Fix the windows path bug", 1.0)
    st.save()
    return st


def test_add_and_active_intents(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch)
    st.addIntent("focus on the windows edge case")
    assert "windows edge case" in st.activeIntents()[0]


def test_intents_expire_after_two_completions(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch)
    st.addIntent("temporary steer")
    for sid in ("st-001", "st-002"):
        st.addSubtask(sid, sid)
    # mark two subtasks terminal -> intent (added at 0 completions) expires at 2
    for s in st.subtasks:
        st.updateSubtask(s["subtask_id"], status="done")
    assert st.activeIntents() == []


def test_clear_intents(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch)
    st.addIntent("steer A")
    st.clearIntents()
    assert st.activeIntents() == []


def test_command_intent_pushes_bus_op(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch)
    bus = ControlBus(st.task_id)
    msg = spine.applyCommand(bus, st, spine.Command("intent", "deprioritize cleanup"))
    ops = bus.drainOps()
    assert any(o.get("op") == "intent" and "cleanup" in o.get("text", "") for o in ops)
    assert "intent" in msg.lower()


def test_command_intent_clear_pushes_clear_op(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch)
    bus = ControlBus(st.task_id)
    spine.applyCommand(bus, st, spine.Command("intent", "clear"))
    assert any(o.get("op") == "intent_clear" for o in bus.drainOps())


def test_command_intent_persist_writes_prefs(tmp_path, monkeypatch):
    from memory import user_prefs
    st = _mk(tmp_path, monkeypatch)
    bus = ControlBus(st.task_id)
    spine.applyCommand(bus, st, spine.Command("intent", "persist always run black"))
    prefs = user_prefs.load(path=tmp_path.parent / "user_prefs.json")
    assert any("black" in str(p) for p in prefs["persistent_intents"])
```

(Note: `STATE_DIR` is set to `tmp_path`; `user_prefs` default path is `tmp_path.parent / user_prefs.json` — the test reads it there.)

- [ ] **Step 2: Run test, expect failure**

Run: `python tools/dev.py check tests/test_intent_injection.py`
Expected: FAIL (`addIntent` missing, `intent` not in registry).

- [ ] **Step 3a: Add schema methods** (`state/task_schema.py`)

In `create()` add to the `meta` dict (additive): `"user_intents": [],` and `"instinct_flags": [],` and `"injected_context": [],`. Add methods:

```python
    def _terminalCount(self) -> int:
        return sum(1 for s in self.subtasks if s["status"] in ("done", "failed", "removed"))

    def addIntent(self, text: str, *, persist: bool = False) -> dict[str, Any]:
        rec = {"text": text, "at": nowIso(), "added_at_completed": self._terminalCount()}
        self.meta.setdefault("user_intents", []).append(rec)
        self.save()
        return rec

    def clearIntents(self) -> None:
        self.meta["user_intents"] = []
        self.save()

    def activeIntents(self) -> list[str]:
        """Intent texts still in force: those added < 2 subtask-completions ago."""
        now_done = self._terminalCount()
        out = []
        for rec in self.meta.get("user_intents", []) or []:
            if now_done - int(rec.get("added_at_completed", 0)) < 2:
                out.append(rec.get("text", ""))
        return [t for t in out if t]

    def addInstinctFlag(self, text: str) -> dict[str, Any]:
        rec = {"text": text, "at": nowIso()}
        self.meta.setdefault("instinct_flags", []).append(rec)
        self.save()
        return rec

    def addInjectedContext(self, text: str) -> None:
        self.meta.setdefault("injected_context", []).append({"text": text, "at": nowIso()})
        self.save()

    def takeInjectedContext(self) -> list[str]:
        """Return queued injected-context texts and clear them (consumed by the next attempt)."""
        items = [c.get("text", "") for c in self.meta.get("injected_context", []) or []]
        if items:
            self.meta["injected_context"] = []
            self.save()
        return [t for t in items if t]

    def extendDeadline(self, delta_seconds: float) -> str:
        from datetime import datetime, timedelta
        try:
            dl = datetime.fromisoformat(self.meta["deadline_at"]) + timedelta(seconds=delta_seconds)
            self.meta["deadline_at"] = dl.isoformat(timespec="seconds")
            self.save()
            return self.meta["deadline_at"]
        except Exception:  # noqa: BLE001
            return self.meta.get("deadline_at", "")
```

- [ ] **Step 3b: Add ControlBus boolean fields** (`platform_core/runtime/control.py`)

In `_blank()` add: `"kill_subprocess": False,` and `"force_replan": False,`. Add methods near the abort/pause block:

```python
    def requestKillSubprocess(self) -> None:
        self._mutate(lambda d: d.__setitem__("kill_subprocess", True))

    def isKillSubprocess(self) -> bool:
        return bool(self.load().get("kill_subprocess"))

    def clearKillSubprocess(self) -> None:
        self._mutate(lambda d: d.__setitem__("kill_subprocess", False))

    def requestForceReplan(self) -> None:
        self._mutate(lambda d: d.__setitem__("force_replan", True))

    def isForceReplan(self) -> bool:
        return bool(self.load().get("force_replan"))

    def clearForceReplan(self) -> None:
        self._mutate(lambda d: d.__setitem__("force_replan", False))
```

- [ ] **Step 3c: Add command routing** (`notifications/commands.py`)

Add to `COMMAND_REGISTRY` (additive rows):

```python
    "intent":  {"arg": "required", "mutating": True,  "help": "steer the run: !intent <text> | clear | persist <text>"},
    "prefer":  {"arg": "required", "mutating": True,  "help": "set a preference: !prefer brief without cost"},
    "prefs":   {"arg": "optional", "mutating": False, "help": "show/reset preferences: !prefs [show|reset]"},
    "effort":  {"arg": "required", "mutating": True,  "help": "run-level effort: !effort high"},
    "mode":    {"arg": "required", "mutating": True,  "help": "switch control mode: !mode gated|watch"},
    "replan":  {"arg": "none",     "mutating": True,  "help": "force a replanning pass now"},
    "deadline":{"arg": "required", "mutating": True,  "help": "extend horizon: !deadline +1h"},
    "kill":    {"arg": "none",     "mutating": True,  "help": "kill the current Claude attempt (not the run)"},
    "inject":  {"arg": "required", "mutating": True,  "help": "add context to next attempt: !inject <text>"},
    "set-effort": {"arg": "required", "mutating": True, "help": "per-subtask effort: !set-effort st-003 high"},
```

`parseCommand` already supports `name` + rest-arg; ensure hyphenated `set-effort` parses — the split on the leading `!` token works because the token is `set-effort` (no space). Confirm: `s[1:].split(maxsplit=1)` → `["set-effort", "st-003 high"]`. Good. Add `applyCommand` branches (after the existing ones, before the final `return _helpText()`):

```python
    if n == "intent":
        arg = cmd.arg.strip()
        if arg.lower() == "clear":
            bus.pushOp({"op": "intent_clear"})
            return "Cleared active intents."
        if arg.lower().startswith("persist "):
            text = arg[len("persist "):].strip()
            from memory import user_prefs
            prefs = user_prefs.load()
            prefs["persistent_intents"] = list(prefs.get("persistent_intents") or []) + [text]
            user_prefs.save(prefs)
            bus.pushOp({"op": "intent", "text": text})
            return f"Persisted intent (every run) + active now: {text}"
        if not arg:
            return "usage: `!intent <text>` | `!intent clear` | `!intent persist <text>`"
        bus.pushOp({"op": "intent", "text": arg})
        return f"Intent noted — the brain will weigh it at the next decision: {arg}"
    if n == "prefer":
        from memory import user_prefs
        return user_prefs.applyPrefer(cmd.arg)
    if n == "prefs":
        from memory import user_prefs
        sub = cmd.arg.strip().lower()
        if sub == "reset":
            user_prefs.reset()
            return "Preferences reset to defaults."
        return user_prefs.formatPrefs(user_prefs.load())
    if n == "effort":
        lvl = cmd.arg.strip().lower()
        if lvl not in config.EFFORT_FLAG_MAP:
            return f"usage: `!effort <{'|'.join(sorted(set(config.EFFORT_FLAG_MAP)))}>`"
        bus.pushOp({"op": "set_run_effort", "level": lvl})
        return f"Run effort -> `{lvl}` for all future subtasks this run."
    if n == "mode":
        m = cmd.arg.strip().lower()
        if m not in ("gated", "watch"):
            return "usage: `!mode gated|watch`"
        state.setControlMode(m)
        return f"Control mode -> `{m}`."
    if n == "replan":
        bus.requestForceReplan()
        return "Replanning pass requested — runs at the next loop tick."
    if n == "deadline":
        import re as _re
        m = _re.match(r"^\+?(\d+(?:\.\d+)?)\s*([hm])$", cmd.arg.strip().lower())
        if not m:
            return "usage: `!deadline +1h` or `!deadline +30m`"
        secs = float(m.group(1)) * (3600 if m.group(2) == "h" else 60)
        bus.pushOp({"op": "extend_deadline", "delta_seconds": secs})
        return f"Deadline extension queued: +{cmd.arg.strip()}"
    if n == "kill":
        bus.requestKillSubprocess()
        return "Kill signal sent — the current Claude attempt will be terminated."
    if n == "inject":
        if not cmd.arg.strip():
            return "usage: `!inject <text>`"
        bus.pushOp({"op": "inject_context", "text": cmd.arg.strip()})
        return "Context queued for the next attempt (no replan)."
    if n == "set-effort":
        parts = cmd.arg.split()
        if len(parts) != 2 or not _SKIP_ID_RE.match(parts[0]) or parts[1].lower() not in config.EFFORT_FLAG_MAP:
            return "usage: `!set-effort st-00N <level>`"
        bus.pushOp({"op": "set_effort", "subtask_id": parts[0], "level": parts[1].lower()})
        return f"Effort override queued for `{parts[0]}` -> `{parts[1].lower()}`."
```

- [ ] **Step 3d: Handle new op kinds in `_applyOps`** (`platform_core/orchestration/control_mixin.py`, inside the `for op in bus.drainOps():` loop, add branches):

```python
                elif kind == "intent":
                    state.addIntent(op.get("text", ""))
                    dashboard.event(f"intent noted: {op.get('text','')[:60]}")
                elif kind == "intent_clear":
                    state.clearIntents()
                    dashboard.event("intents cleared")
                elif kind == "inject_context":
                    state.addInjectedContext(op.get("text", ""))
                    dashboard.event("context injected for next attempt")
                elif kind == "set_effort":
                    sid = op.get("subtask_id")
                    if state.getSubtask(sid):
                        state.updateSubtask(sid, effort_override=op.get("level"))
                        dashboard.event(f"effort override {sid} -> {op.get('level')}")
                elif kind == "set_run_effort":
                    state.meta["run_effort_override"] = op.get("level")
                    state.save()
                    dashboard.event(f"run effort -> {op.get('level')}")
                elif kind == "extend_deadline":
                    new_dl = state.extendDeadline(float(op.get("delta_seconds", 0)))
                    dashboard.event(f"deadline extended -> {new_dl}")
```

- [ ] **Step 3e: Fold intents + injected context + effort override into the spec** (`platform_core/orchestration/plan_mixin.py`, in `authorInvocationSpec`, after the `failure_feedback` fold block, before the reflection REQUEST append):

```python
        # Spec B: fold active operator intents + queued injected-context + per-sid effort override
        # into the spec deterministically (so they reach the executor even when the brain returns
        # empty). Intents are CONTEXT the brain weighs; injected context is a one-shot CLAUDE.md add.
        intents = []
        try:
            intents = state.activeIntents()
        except Exception:  # noqa: BLE001
            intents = []
        injected = []
        try:
            injected = state.takeInjectedContext()
        except Exception:  # noqa: BLE001
            injected = []
        extra = ""
        if intents:
            extra += "\n\n## Operator intent (weigh this; it is direction, not a hard command)\n- " \
                     + "\n- ".join(intents[:8])
        if injected:
            extra += "\n\n## Operator-injected context for this attempt\n- " + "\n- ".join(injected[:8])
        if extra:
            spec["claude_md_inject"] = ((spec.get("claude_md_inject") or "") + extra).strip()
            spec["prompt"] = (spec.get("prompt") or "") + extra
        ov = subtask.get("effort_override") or state.meta.get("run_effort_override")
        if ov in config.EFFORT_FLAG_MAP:
            spec["effort_level"] = ov
```

- [ ] **Step 4: Run test, expect pass**

Run: `python tools/dev.py check tests/test_intent_injection.py`
Expected: PASS.

- [ ] **Step 5: Regression — commands + control still green**

Run: `python tools/dev.py check tests/test_commands.py` then `python tools/dev.py check tests/test_control_concurrency.py`
Expected: PASS (no regression in the spine or bus).

- [ ] **Step 6: Commit**

```bash
git add state/task_schema.py platform_core/runtime/control.py notifications/commands.py platform_core/orchestration/control_mixin.py platform_core/orchestration/plan_mixin.py tests/test_intent_injection.py
git commit -m "feat(intel): intent injection + ControlBus ops + spec fold"
```

---

## Task 4: Brain dialogue — `!why` / `!explain` / `!plan-rationale` / `!ask`

**Files:**
- Create: `notifications/brain_dialogue.py`
- Test: `tests/test_brain_dialogue.py`

Pure core like `notifications/ask.py`. `build_context(state, kind, arg)` assembles plan + last-3 events + the architect doc excerpt (read defensively from state's notifications / meta) + the question. `answer(kind, arg, state, *, chat=None)` runs the injected chat with `config.BRAIN_DIALOGUE_SYSTEM_PROMPT`, degrades gracefully.

- [ ] **Step 1: Write the failing test** (`tests/test_brain_dialogue.py`)

```python
"""Brain-dialogue pure core: context builder + graceful answer (chat injected)."""
from notifications import brain_dialogue as bd


class _State:
    task_id = "t1"
    meta = {"goal_raw": "wire the pool", "goal_elaborated": "wire the connection pool",
            "status": "executing"}
    subtasks = [
        {"subtask_id": "st-004", "title": "pool fix", "status": "done", "depends_on": []},
        {"subtask_id": "st-005", "title": "verify pool", "status": "pending",
         "depends_on": ["st-004"], "description": "verify against the pool"},
    ]
    data = {"notifications": [{"at": "t", "kind": "subtask_done", "detail": "st-004"}],
            "adversary_reviews": []}


def test_why_context_has_plan_and_question():
    ctx = bd.build_context(_State(), "why", "st-004 before st-005?")
    assert "st-004" in ctx and "st-005" in ctx
    assert "st-004 before st-005?" in ctx


def test_explain_context_targets_subtask():
    ctx = bd.build_context(_State(), "explain", "st-005")
    assert "verify against the pool" in ctx


def test_answer_uses_injected_chat():
    out = bd.answer("why", "st-004 before st-005?", _State(),
                    chat=lambda s, u: "st-005 depends on st-004's pool fix.")
    assert "depends" in out


def test_answer_offline_degrades():
    def boom(s, u):
        raise RuntimeError("down")
    out = bd.answer("ask", "what now?", _State(), chat=boom)
    assert "offline" in out.lower() or "unavailable" in out.lower()


def test_explain_unknown_sid_message():
    out = bd.answer("explain", "st-999", _State(), chat=lambda s, u: "x")
    assert "st-999" in out
```

- [ ] **Step 2: Run test, expect failure**

Run: `python tools/dev.py check tests/test_brain_dialogue.py`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `notifications/brain_dialogue.py`**

Mirror `notifications/ask.py` structure (`SYSTEM = config.BRAIN_DIALOGUE_SYSTEM_PROMPT`, `_defaultChat` using `config.BRIEF_MODEL`, `build_context`, `answer`). `build_context` branches on `kind`: `why`/`plan-rationale` → full plan with deps + last-3 events + question; `explain` → target subtask detail (and if the sid is unknown, the question still routes but `answer` short-circuits with a friendly "st-999 isn't in the current plan."); `ask` → general context + question. Keep each function ≤25 lines.

- [ ] **Step 4: Run test, expect pass**

Run: `python tools/dev.py check tests/test_brain_dialogue.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add notifications/brain_dialogue.py tests/test_brain_dialogue.py
git commit -m "feat(intel): brain dialogue core (why/explain/plan-rationale/ask)"
```

---

## Task 5: Predictive flags

**Files:**
- Create: `notifications/predictive.py`
- Test: `tests/test_predictive_flags.py`

Heuristic-first, all data injectable. `Flag = namedtuple("Flag", "signal severity text")`. `PredictiveFlags` instance holds rate-limit state (`_last_emit_ts`, `_seen_signals: set`). Pure heuristic functions take precomputed history so tests never hit the DB; `evaluate(state, *, now=None, history=None)` where `history` is a dict of `{subtask_avgs, replan_avg, adversary_rate_avg, failing_specs, file_hotspots, retry_rates}` (defaults pulled from `experience.fetch_*` when None). `emit_due(state, ...)` applies rate-limit (≤1 / `config.PREDICTIVE_FLAG_MIN_INTERVAL_SECONDS`, never same signal twice) and returns the single flag to post (or None). Optional `_ollamaExplain(flag, chat)` gated by `config.PREDICTIVE_FLAG_OLLAMA`.

- [ ] **Step 1: Write the failing test** (`tests/test_predictive_flags.py`)

```python
"""Predictive flag engine: heuristics + rate limiting (all data injected, no DB/Ollama)."""
import time

from notifications import predictive


class _State:
    task_id = "t1"
    meta = {"goal_raw": "x", "started_at": "2026-06-28T09:00:00",
            "deadline_at": "2026-06-28T10:00:00"}
    subtasks = [
        {"subtask_id": "st-003", "title": "touch hot file", "status": "in_progress",
         "description": "edit notifications/discord_client.py", "started_at": "2026-06-28T09:50:00"},
    ]
    data = {"notifications": [], "adversary_reviews": []}


def test_file_hotspot_flag():
    eng = predictive.PredictiveFlags()
    hist = {"file_hotspots": {"notifications/discord_client.py": 6}}
    flags = eng.evaluate(_State(), history=hist)
    assert any(f.signal == "file_hotspot" for f in flags)


def test_verify_similarity_flag():
    eng = predictive.PredictiveFlags()
    st = _State()
    st.subtasks = [{"subtask_id": "st-003", "title": "t", "status": "pending",
                    "verify": {"cmd": "python -m pytest tests/test_pool.py -q"}}]
    hist = {"failing_specs": ["python -m pytest tests/test_pool.py -q"]}
    flags = eng.evaluate(st, history=hist)
    assert any(f.signal == "verify_similarity" for f in flags)


def test_rate_limit_one_per_window():
    eng = predictive.PredictiveFlags()
    hist = {"file_hotspots": {"notifications/discord_client.py": 6}}
    first = eng.emit_due(_State(), history=hist, now=1000.0)
    second = eng.emit_due(_State(), history=hist, now=1000.5)
    assert first is not None
    assert second is None  # within 90s window AND same signal already seen


def test_same_signal_never_twice():
    eng = predictive.PredictiveFlags()
    hist = {"file_hotspots": {"notifications/discord_client.py": 6}}
    eng.emit_due(_State(), history=hist, now=0.0)
    later = eng.emit_due(_State(), history=hist, now=10_000.0)  # window elapsed
    assert later is None  # signal already seen this run


def test_disabled_returns_nothing(monkeypatch):
    import config
    monkeypatch.setattr(config, "PREDICTIVE_FLAGS_ENABLED", False)
    eng = predictive.PredictiveFlags()
    assert eng.emit_due(_State(), history={"file_hotspots": {"x.py": 9}}, now=0.0) is None
```

- [ ] **Step 2: Run test, expect failure**

Run: `python tools/dev.py check tests/test_predictive_flags.py`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `notifications/predictive.py`**

Implement heuristics: `_fileHotspotFlags` (subtask description/title mentions a file with ≥ threshold past-run modifications → `📁` flag); `_verifySimilarityFlags` (pending/active subtask verify cmd string-overlap >70% with any known failing spec → `⚠️` flag); `_runtimeFlag` (current in-progress subtask runtime > 2.5× the historical avg for its type → `⏱` flag); `_paceFlag` (deadline <20% time remaining but >40% work remaining). `evaluate` aggregates non-rate-limited flags. `emit_due` enforces: skip when `not config.PREDICTIVE_FLAGS_ENABLED`; pick the highest-severity unseen flag; enforce `_last_emit_ts` window; record signal in `_seen_signals`. Keep functions ≤25 lines; split helpers as needed. Provide module-level `_defaultHistory(state)` (pragma no cover) pulling `experience.fetch_failure_modes()` / `fetch_subtasks()` for the real path.

- [ ] **Step 4: Run test, expect pass**

Run: `python tools/dev.py check tests/test_predictive_flags.py`
Expected: PASS.

- [ ] **Step 5: size_audit + commit**

```bash
python tools/size_audit.py
git add notifications/predictive.py tests/test_predictive_flags.py
git commit -m "feat(intel): predictive-flag heuristic engine with rate limiting"
```

---

## Task 6: Granular mid-run controls — wire kill-subprocess, force-replan into the loop

**Files:**
- Modify: `platform_core/orchestration/execute_mixin.py` (kill-subprocess cancel_check)
- Modify: `platform_core/orchestration/run_loop_mixin.py` (force-replan check site)
- Test: extend `tests/test_intent_injection.py` OR add focused asserts in a new `tests/test_granular_controls.py`

The data ops (inject/set-effort/run-effort/deadline) already land via `_applyOps` (Task 3). This task wires the two **boolean** signals into the live loop.

- [ ] **Step 1: kill-subprocess into cancel_check** (`execute_mixin.py`, `_runOneAttempt`)

Change the cancel_check passed to `hands(...)` to also honor a kill request, and clear the flag after the attempt so it only kills the current one:

```python
        result = hands(spec, work_dir=exec_cwd, task_state=state, subtask=subtask,
                       resume_session=resume_session,
                       cancel_check=lambda: bus.isAbort() or bus.isKillSubprocess()
                       or self._deadlinePassed(state))
        if bus.isKillSubprocess():
            bus.clearKillSubprocess()
            with self._state_lock:
                state.addNotification("kill_subprocess", f"{sid}: operator killed the attempt")
```

(The executor already terminates the process tree when `cancel_check` returns True — `kill_subprocess` reuses that path. The run continues to the next attempt; it does NOT abort the run.)

- [ ] **Step 2: force-replan check in the loop** (`run_loop_mixin.py`, `runExecutionLoop`, near the top of the `while True:` body after `self._checkControl(...)`)

```python
            if bus.isForceReplan():
                bus.clearForceReplan()
                self._forcedReplan(state, architect_doc, dashboard)
```

Add `_forcedReplan` to `run_loop_mixin.py` (≤25 lines): pick the last `done` subtask as context, call `self._replan(...)` like `_runSieAndReplan` does, apply via `self._applyReplan` under the state lock; best-effort (never raises into the loop). Skip for single-deliverable goals.

```python
    def _forcedReplan(self, state, architect_doc, dashboard) -> None:
        """Operator-requested replanning pass (via !replan / ControlBus.force_replan)."""
        try:
            goal = state.meta.get("goal_elaborated") or state.meta.get("goal_raw", "")
            last_done = next((s for s in reversed(state.subtasks) if s["status"] == "done"), None)
            with self._state_lock:
                subs = list(state.subtasks)
            decision = self._replan(goal, subs, last_done or {}, "operator-forced replan",
                                    self_referential=bool(state.meta.get("is_self_referential")),
                                    remaining_hours=self._remainingHours(state))
            if decision.get("action") == "mutate" and (decision.get("add") or decision.get("remove")):
                dashboard.update(state, "replanning", "operator-forced replan")
                with self._state_lock:
                    self._applyReplan(state, decision)
        except Exception as e:  # noqa: BLE001 -- forced replan is best-effort
            LOG.warning("forced replan failed (ignored): %s", e)
```

- [ ] **Step 3: Write focused test** (`tests/test_granular_controls.py`)

```python
"""Granular controls: ControlBus boolean signals + op-driven state mutations."""
import config
from state.task import TaskState
from platform_core.runtime.control import ControlBus
from notifications import commands as spine


def _mk(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path, raising=False)
    monkeypatch.setattr(config, "CONTROL_DIR", tmp_path, raising=False)
    st = TaskState.create("goal", 1.0)
    st.addSubtask("a", "a")
    st.save()
    return st


def test_kill_sets_and_clears(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch)
    bus = ControlBus(st.task_id)
    spine.applyCommand(bus, st, spine.Command("kill", ""))
    assert bus.isKillSubprocess() is True
    bus.clearKillSubprocess()
    assert bus.isKillSubprocess() is False


def test_replan_sets_force_flag(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch)
    bus = ControlBus(st.task_id)
    spine.applyCommand(bus, st, spine.Command("replan", ""))
    assert bus.isForceReplan() is True


def test_deadline_extend_op_updates_meta(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch)
    before = st.meta["deadline_at"]
    st.extendDeadline(3600)
    assert st.meta["deadline_at"] != before


def test_set_effort_op_records_override(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch)
    sid = st.subtasks[0]["subtask_id"]
    st.updateSubtask(sid, effort_override="high")
    assert st.getSubtask(sid)["effort_override"] == "high"
```

- [ ] **Step 4: Run tests, expect pass**

Run: `python tools/dev.py check tests/test_granular_controls.py`
Expected: PASS. Then regression: `python tools/dev.py check tests/test_commands.py`.

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/execute_mixin.py platform_core/orchestration/run_loop_mixin.py tests/test_granular_controls.py
git commit -m "feat(intel): wire kill-subprocess + force-replan ControlBus signals into the loop"
```

---

## Task 7: Nightclaw instinct

**Files:**
- Create: `notifications/instinct.py`
- Modify: `platform_core/orchestration/run_phase_mixin.py` (`_maybeInstinct`)
- Modify: `platform_core/orchestration/run_loop_mixin.py` (call site)
- Test: `tests/test_instinct.py`

`NightclawInstinct` pure core: `build_prompt(state, reflections, failure_modes, events) -> tuple[str, str]` using `config.INSTINCT_SYSTEM_PROMPT`; `maybe_fire(state, *, reflections=None, failure_modes=None, chat=None, already_fired=False) -> Optional[str]` — returns the instinct sentence if the model emits non-empty text AND not already fired this run, else None. Reads last-10 reflections + last-5 failure modes (injected; default from `experience.fetch_reflections()` / `fetch_failure_modes()`).

The orchestrator side: `_maybeInstinct(state, bus)` on the run-phase mixin — guarded by `config.INSTINCT_ENABLED` + user pref + `state.meta.get("instinct_flags")` empty + `_last_instinct_ts` interval; fires the Ollama call **off-thread** (daemon thread) so the loop never blocks; on a non-empty result records `state.addInstinctFlag(text)` and posts to Discord. Called from `runExecutionLoop` once per iteration (the interval guard makes it cheap).

- [ ] **Step 1: Write the failing test** (`tests/test_instinct.py`)

```python
"""Nightclaw instinct: prompt builder + at-most-once-per-run firing (chat injected)."""
from notifications import instinct


class _State:
    task_id = "t1"
    meta = {"goal_raw": "wire pool", "status": "executing", "instinct_flags": []}
    subtasks = [{"subtask_id": "st-001", "title": "a", "status": "done"}]
    data = {"notifications": [{"at": "t", "kind": "subtask_done", "detail": "st-001"}],
            "adversary_reviews": []}


def test_build_prompt_includes_state_and_experience():
    eng = instinct.NightclawInstinct()
    system, user = eng.build_prompt(_State(), reflections=[{"approach": "used pool guard"}],
                                    failure_modes=[{"root_cause": "timing"}], events=[])
    assert "pattern" in system.lower()
    assert "pool guard" in user or "timing" in user


def test_fires_on_nonempty_response():
    eng = instinct.NightclawInstinct()
    out = eng.maybe_fire(_State(), reflections=[], failure_modes=[],
                         chat=lambda s, u: "Something feels off about the pool ordering.")
    assert out and "off" in out.lower()


def test_silent_on_empty_response():
    eng = instinct.NightclawInstinct()
    assert eng.maybe_fire(_State(), reflections=[], failure_modes=[],
                          chat=lambda s, u: "  ") is None


def test_at_most_once_per_run():
    eng = instinct.NightclawInstinct()
    st = _State()
    st.meta["instinct_flags"] = [{"text": "already flagged"}]
    out = eng.maybe_fire(st, reflections=[], failure_modes=[],
                         chat=lambda s, u: "new signal", already_fired=True)
    assert out is None


def test_offline_is_silent():
    eng = instinct.NightclawInstinct()
    def boom(s, u):
        raise RuntimeError("down")
    assert eng.maybe_fire(_State(), reflections=[], failure_modes=[], chat=boom) is None
```

- [ ] **Step 2: Run test, expect failure**

Run: `python tools/dev.py check tests/test_instinct.py`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `notifications/instinct.py`**

Pure core per the test. `maybe_fire`: short-circuit when `already_fired`; build prompt; call injected `chat` (default `_defaultChat` on `config.BRIEF_MODEL`, pragma no cover); strip; return text or None; swallow all exceptions → None.

- [ ] **Step 4: Wire the orchestrator trigger** (`run_phase_mixin.py`)

Add `_maybeInstinct(self, state, bus)` (≤30 lines): guard `config.INSTINCT_ENABLED`; check `memory.user_prefs.get("instinct_enabled")` (best-effort); skip if `state.meta.get("instinct_flags")`; throttle via `getattr(self, "_last_instinct_ts", 0)` vs `config.INSTINCT_INTERVAL_SECONDS`; set the ts; spawn a `threading.Thread(daemon=True, target=_run)` where `_run` calls `instinct.NightclawInstinct().maybe_fire(state, chat=self._instinctChat)` and on a hit does `state.addInstinctFlag(text)` + `discord.sendEmbed(discord.noticeEmbed(text, title="Nightclaw instinct"))`. `_instinctChat(system, user)` wraps `self._ollamaChat(system, user)` → `_chatText`. Add the call in `runExecutionLoop` (run_loop_mixin) right after `self._checkControl(state, bus, dashboard)`:

```python
            try:
                self._maybeInstinct(state, bus)
            except Exception:  # noqa: BLE001 -- instinct is best-effort, never blocks the loop
                pass
```

Initialize `self._last_instinct_ts = 0.0` in `runExecutionLoop` setup (near `position = 0`).

- [ ] **Step 5: Run test + regression, expect pass**

Run: `python tools/dev.py check tests/test_instinct.py`
Expected: PASS. Confirm orchestrator imports: `python -c "import orchestrator"`.

- [ ] **Step 6: Commit**

```bash
git add notifications/instinct.py platform_core/orchestration/run_phase_mixin.py platform_core/orchestration/run_loop_mixin.py tests/test_instinct.py
git commit -m "feat(intel): nightclaw instinct (periodic off-thread pattern signal)"
```

---

## Task 8: Wisdom + growth (`learning/wisdom.py`) + teardown growth post

**Files:**
- Create: `learning/wisdom.py`
- Modify: `platform_core/orchestration/run_phase_mixin.py` (`_postGrowth` at teardown)
- Test: covered by `tests/test_log_cog.py` (Task 9) — add a `tests/test_wisdom.py` for the pure helpers

Decision: wisdom/growth helpers live in `learning/wisdom.py` (the SIE/learning domain owns experience-derived summaries; keeps `briefing.py` focused). Pure, reads the injected reflections list.

- [ ] **Step 1: Write the failing test** (`tests/test_wisdom.py`)

```python
"""Wisdom trail + growth summary pure helpers (reflections injected, no DB)."""
from learning import wisdom


class _State:
    meta = {"goal_raw": "fix windows subprocess timing"}
    task_id = "t1"


def test_wisdom_trail_keyword_matches_goal():
    refs = [
        {"approach": "windows subprocess timing under load is unreliable", "run_id": "r9",
         "confidence": 0.8, "subtask_id": "st-002"},
        {"approach": "unrelated css refactor", "run_id": "r3", "confidence": 0.5,
         "subtask_id": "st-001"},
    ]
    out = wisdom.wisdomTrail(_State(), reflections=refs)
    assert "windows subprocess timing" in out
    assert "css refactor" not in out


def test_wisdom_trail_empty_message():
    out = wisdom.wisdomTrail(_State(), reflections=[])
    assert "no" in out.lower()


def test_growth_summary_reads_reflections():
    refs = [{"approach": "learned a thing", "run_id": "r9", "confidence": 0.7}]
    out = wisdom.growthSummary(reflections=refs, runs=[{"task_id": "r9", "status": "done"}])
    assert "learned a thing" in out or "r9" in out
```

- [ ] **Step 2: Run test, expect failure**

Run: `python tools/dev.py check tests/test_wisdom.py`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `learning/wisdom.py`**

`_keywords(goal) -> set[str]` (lowercased words ≥4 chars, minus stopwords); `wisdomTrail(state, *, reflections=None) -> str` — default `experience.fetch_reflections()`; keep reflections whose `approach`/`reusable_recipe` text overlaps the goal keywords; format with run id + confidence; "No relevant past reflections yet." when empty; `growthSummary(*, domain=None, reflections=None, runs=None) -> str` — 2-line learning summary from the most recent reflections (optionally filtered by `domain` keyword), reading `experience.fetch_reflections()` / `fetch_runs()` by default. Each function ≤25 lines.

- [ ] **Step 4: Add `_postGrowth` at teardown** (`run_phase_mixin.py`, in `_runTeardown`, after SIE maintenance dispatch — best-effort, never blocks):

```python
        try:
            from learning import wisdom
            line = wisdom.growthSummary()
            if line:
                discord.sendEmbed(discord.noticeEmbed(line, title="9TO5 growth"))
        except Exception:  # noqa: BLE001 -- growth post is best-effort
            LOG.debug("growth post failed (ignored)", exc_info=True)
```

- [ ] **Step 5: Run test, expect pass**

Run: `python tools/dev.py check tests/test_wisdom.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add learning/wisdom.py platform_core/orchestration/run_phase_mixin.py tests/test_wisdom.py
git commit -m "feat(intel): wisdom trail + growth summary + teardown growth post"
```

---

## Task 9: Gateway shells — `log_cog.py` + `context_cog.py` + cockpit selects

**Files:**
- Create: `notifications/bot/cogs/log_cog.py`
- Create: `notifications/bot/cogs/context_cog.py`
- Modify: `notifications/bot/core.py` (`EXTENSIONS`)
- Modify: `notifications/cv2.py` (additive Section header + select stubs)
- Test: `tests/test_log_cog.py`, `tests/test_context_cog.py`

The cogs are thin gateway shells (mostly `# pragma: no cover`). Tests assert the module imports, the cog class exposes the expected app-command callbacks, `setup` is callable, and the Ollama-backed bang dispatch maps the right prefixes to the right cores (test the dispatch helper, not a live gateway).

- [ ] **Step 1: Write the failing tests**

`tests/test_log_cog.py`:

```python
"""log_cog gateway shell: command surface + bang-dispatch routing (no live gateway)."""
from notifications.bot.cogs import log_cog


def test_cog_exposes_expected_slash_commands():
    names = log_cog.LogCog.__cog_app_commands__ if hasattr(log_cog.LogCog, "__cog_app_commands__") else []
    # fall back to attribute scan if discord stores them differently
    attrs = dir(log_cog.LogCog)
    for cmd in ("brief", "why", "explain", "wisdom", "growth", "intent", "prefer", "prefs"):
        assert cmd in attrs


def test_setup_is_callable():
    assert callable(log_cog.setup)


def test_bang_dispatch_routes_brief(monkeypatch):
    seen = {}
    monkeypatch.setattr(log_cog.briefing, "generate_brief",
                        lambda state, prefs, depth, chat=None: seen.setdefault("d", depth) or "BRIEF")
    out = log_cog.dispatchBang("!brief one-line", state=object(), prefs={})
    assert out == "BRIEF" and seen["d"] == "one-line"


def test_bang_dispatch_routes_why(monkeypatch):
    monkeypatch.setattr(log_cog.brain_dialogue, "answer",
                        lambda kind, arg, state, chat=None: f"{kind}:{arg}")
    out = log_cog.dispatchBang("!why st-004 before st-005", state=object(), prefs={})
    assert out.startswith("why:")


def test_bang_dispatch_ignores_non_bang():
    assert log_cog.dispatchBang("hello", state=object(), prefs={}) is None
```

`tests/test_context_cog.py`:

```python
"""context_cog gateway shell: imports + setup callable + 3 context-menu builders."""
from notifications.bot.cogs import context_cog


def test_setup_is_callable():
    assert callable(context_cog.setup)


def test_module_defines_three_context_commands():
    # the cog registers exactly three context-menu commands (Explain / Why / Brief here)
    assert len(context_cog.CONTEXT_COMMAND_NAMES) == 3
```

- [ ] **Step 2: Run tests, expect failure**

Run: `python tools/dev.py check tests/test_log_cog.py`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `log_cog.py`**

Module-level `dispatchBang(content, *, state, prefs, chat=None) -> Optional[str]` — pure routing helper (testable): parse the leading `!brief|!why|!explain|!ask|!wisdom|!growth` token, call the matching core (`briefing.generate_brief`, `brain_dialogue.answer`, `wisdom.wisdomTrail`, `wisdom.growthSummary`) with the remaining arg; return None for any non-matching content. The `LogCog` class: slash commands `brief/why/explain/wisdom/growth/intent/prefer/prefs` (each `# pragma: no cover` — defer + `asyncio.to_thread` + post, routing slash control commands through `slash._runControl` for intent/prefer/prefs and through `dispatchBang`-style helpers for the Ollama ones) plus a `@dpy_commands.Cog.listener("on_message")` that calls `dispatchBang` for the Ollama bang commands (loads prefs + a real chat via a small adapter; best-effort post). Keep imports: `from notifications import briefing, brain_dialogue`, `from learning import wisdom`, `from memory import user_prefs`, `from notifications import commands as spine, slash`.

- [ ] **Step 4: Implement `context_cog.py`**

`CONTEXT_COMMAND_NAMES = ("Explain this", "Why this order", "Brief here")`. `setup(bot)` registers three `app_commands.ContextMenu` message commands (each `# pragma: no cover`) that resolve the latest task and reply via `brain_dialogue.answer` / `briefing.generate_brief`. The pure list constant is what the test checks.

- [ ] **Step 5: Register cogs** (`notifications/bot/core.py`, append to `EXTENSIONS`):

```python
    "notifications.bot.cogs.log_cog",      # /brief /why /wisdom /growth /intent /prefer (+ ! bang)
    "notifications.bot.cogs.context_cog",  # 3 context-menu commands (Spec B)
```

- [ ] **Step 6: Cockpit selects** (`notifications/cv2.py`, in `buildCockpit`, additive — before the control-button rows append a Section header text line; add 3 ActionRow String Select stubs with custom_ids `cv2_subtask_select` / `cv2_effort_select` / `cv2_mode_select`):

Add after `children.append(separator())` that precedes the control rows:

```python
    children.append(text("**Steering** — subtask · effort · mode"))
    children.append({"type": 1, "components": [{
        "type": 3, "custom_id": "cv2_effort_select", "placeholder": "Set run effort",
        "options": [{"label": lvl, "value": lvl} for lvl in
                    ("low", "default", "high", "xhigh", "ultracode")]}]})
    children.append({"type": 1, "components": [{
        "type": 3, "custom_id": "cv2_mode_select", "placeholder": "Control mode",
        "options": [{"label": "watch", "value": "watch"}, {"label": "gated", "value": "gated"}]}]})
```

(Type 3 = String Select. The subtask select is added by the gateway dynamically where subtask ids are known; the effort/mode selects are static and safe in the pure tree. Keep `buildCockpit` ≤70 lines — if it grows past the ceiling, extract `_steeringRows()` helper.)

- [ ] **Step 7: Run tests + cv2 regression**

Run: `python tools/dev.py check tests/test_log_cog.py` then `python tools/dev.py check tests/test_context_cog.py` then `python tools/dev.py check tests/test_cv2.py`
Expected: PASS (all three).

- [ ] **Step 8: size_audit + commit**

```bash
python tools/size_audit.py
git add notifications/bot/cogs/log_cog.py notifications/bot/cogs/context_cog.py notifications/bot/core.py notifications/cv2.py tests/test_log_cog.py tests/test_context_cog.py
git commit -m "feat(intel): gateway cogs (log/context) + cockpit steering selects"
```

---

## Task 10: Final verification, docs, repo-map

**Files:**
- Modify: `AGENTS.md` (regenerated, do not hand-edit)
- Modify: `docs/MEMORY.md` or `docs/STATE.md` if state/command surface docs exist (additive note on new commands + schema fields)

- [ ] **Step 1: Regenerate repo map**

Run: `python tools/repo_map.py`
Expected: updates `AGENTS.md` rows for the new modules.

- [ ] **Step 2: Size audit — zero must_split**

Run: `python tools/size_audit.py`
Expected: zero `must_split` violations. If any new file/function exceeds the ceiling, split (helper sub-functions / extract a module) and re-run.

- [ ] **Step 3: Broad fast suite**

Run: `python tools/dev.py fast`
Expected: PASS (or only pre-existing unrelated failures — capture real output). Investigate any failure touching commands/control/cv2/orchestrator import.

- [ ] **Step 4: Targeted Spec B suite**

Run: `python -m pytest tests/test_user_prefs.py tests/test_briefing.py tests/test_intent_injection.py tests/test_brain_dialogue.py tests/test_predictive_flags.py tests/test_instinct.py tests/test_granular_controls.py tests/test_wisdom.py tests/test_log_cog.py tests/test_context_cog.py -q`
Expected: all PASS.

- [ ] **Step 5: Update docs** (additive)

Add a short section to the closest command/state doc (e.g. `docs/STATE.md` for the new `user_intents`/`instinct_flags`/`injected_context` meta fields and `docs/` command reference for the new `!` commands). Keep `CLAUDE.md` untouched (already ≤200 lines).

- [ ] **Step 6: Commit**

```bash
git add AGENTS.md docs/
git commit -m "docs(intel): regenerate repo map + document Spec B commands/state"
```

---

## Self-review checklist (run before declaring done)

1. **Spec coverage:** Briefing (T2) · Intent injection (T3) · Brain dialogue (T4) · Predictive flags (T5) · Granular controls (T3 ops + T6 signals) · Nightclaw instinct (T7) · Availability/preferences (T1 + commands in T3 + cogs T9) · Self-improvement visible (T8). All 8 concepts mapped.
2. **ControlBus ownership:** every new mid-run control routes through ControlBus (booleans `kill_subprocess`/`force_replan`; queued ops `intent`/`inject_context`/`set_effort`/`set_run_effort`/`extend_deadline`). No bypass.
3. **Never blocks a run:** instinct + brief + brain-dialogue Ollama calls are off-thread (instinct daemon thread) or gateway-only (cogs); the in-run poller only applies fast control ops.
4. **No live services in tests:** every core takes an injectable `chat`; experience data is injected; conftest blanks Discord + blocks Ollama.
5. **Size:** new modules ≤300 target / ≤450 hard; `buildCockpit` watched for the 70-line ceiling.
6. **Spec A seams:** codename/health_score/event_bus/self-reflection accessed defensively; documented above; not reimplemented.
