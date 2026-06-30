# Epic 2 — Trustworthy 7B Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the brittle local `qwen2.5-coder:7b` brain reliable by stacking three flag-gated layers — schema-validated JSON self-correction, an execution-grounded independent verifier + Evidence Receipt, and a dual-ledger planner — without swapping the model or changing effort routing.

**Architecture:** Build strictly in the locked order **#9 (JSON self-correction) → #3 (execution-grounded verifier) → #2 (dual-ledger planner)**, because #3 and #2 ride on #9's reliable JSON and #2's plans want #3's evidence-based verdict from day one. Every layer is a new small module (`@AI-MAP v1` header, ≤450 lines, funcs ≤70 lines) plus a narrow patch to an existing mixin; each is independently flaggable. **Ownership is preserved**: the deterministic verifier (`agents/verifier_runner.py`) still owns verification status; the independent verifier and Evidence Receipt can only **downgrade** a deterministic pass via the verifier-owned `state.recordVerify` path, never upgrade a fail; `ControlBus` is untouched.

**LOCKED DECISION (this epic):** A `NOT_VERIFIED` Evidence Receipt is **MODE-DEPENDENT** — on a **self-improvement run** (`state.meta["is_self_referential"]`) it **HARD-FAILS** the subtask; on a **normal product run** it marks `VERIFIED_WITH_GAPS` and lets the run continue with a loud gap note. This is a one-line policy switch inside `_runAttemptVerify`. The independent verifier is read-only and at a fixed modest effort; it does NOT alter any existing subtask's effort or model routing. The 7B model is NOT swapped. The loki Evidence Receipt is **reimplemented natively** (BUSL — ideas only, no vendored code).

**Tech Stack:** Python 3.11 (Windows-only, rooted at `C:\9to5`); `pytest` (NEVER bare `unittest` — local `.env` carries live Discord/Ollama creds and the conftest sandbox is pytest-only); Ollama (`qwen2.5-coder:7b`) brain via `ollama-python`; Claude Code CLI hands; `json_repair` (new pip dep); stdlib `dataclasses`, `hashlib`, `subprocess`, `re`, `json`.

**Conventions:** `camelCase` functions, `snake_case` vars, `ALL_CAPS` consts. Free functions take an `ollama_chat` callable (mirroring `subtask.py` split-out helpers). After structural changes run `python tools/size_audit.py` (zero `must_split`) and `python tools/repo_map.py` (regenerates `AGENTS.md`). Per-file focus check: `python tools/dev.py check <file>`. Test methods stay `snake_case` (test-framework convention) but run through pytest.

**Grounded interfaces (read before starting):**
- Brain JSON path: `platform_core/orchestration/brain_io.py::parseJsonText` / `_chatJson` / `_chatText`; `llm_io.py::_firstBalancedObject` / `responseText`.
- Brain call: `platform_core/orchestration/llm_mixin.py::_ollamaChat(system, user, *, want_json=False, retries=3) -> resp|None`.
- Planner: `platform_core/orchestration/plan_mixin.py::authorSubtaskPlan` (lines 113-176), `critiqueSubtaskPlan` (178-211), `authorInvocationSpec` (273-330, append point beside `reflection.REQUEST` at line 326-327).
- Verifier (owns status): `agents/verifier_runner.py::runVerification`, `agents/verifier.py::isStrictVerify`.
- Verify loop: `platform_core/orchestration/execute_mixin.py::_runAttemptVerify` (97-154, self-ref downgrade pattern at 123-136), `_runSieAndReplan` (303-337).
- Replan: `platform_core/orchestration/run_loop_mixin.py::_applyReplan` (296-343); `self._replan = replanner.replan` returns `{action, add, remove, reason}`.
- State: `state/task_schema.py::TaskState` — `addSubtask(..., depends_on=...)` (303), `nextActionable` honors `depends_on` (379), `recordVerify` (279), `meta` dict.
- Read-only spawn seam: `agents/executor.py::_buildRunConfig` (116-159) — `--disallowedTools` already used for `CORE_PROTECTED_FILES` at line 137-139.
- Config: `platform_core/app_config/llm.py` (re-exported by `config`); `_envBool`/`_envInt` helpers; `MAX_SUBTASKS=8`.

---

## File Structure

**New modules:**

| File | Responsibility |
|---|---|
| `platform_core/orchestration/brain_json.py` | `chatJsonValidated`, `_makeRetryPrompt`, `_validateShape` (pydantic-ai retry loop, no pydantic dep) |
| `platform_core/orchestration/task_ledger.py` | `TaskLedger` dataclass + ledger prompt constants + `(de)serialize` to `state.meta` |
| `platform_core/orchestration/plan_shape_check.py` | `checkPlanShape`, `shapeViolationReport` (deterministic; bernstein) |
| `platform_core/orchestration/dual_ledger_planner.py` | `authorTaskLedger`, `deriveSubtaskDag`, `materializeDag`, `progressLedgerStep`, `updateStallCount`, `rootCauseReplan` |
| `agents/completion_envelope.py` | `CompletionEnvelope`, `EnvelopeParse`, `COMPLETION_ENVELOPE_INSTRUCTION`, `parseCompletionEnvelope`, `summarizeEnvelope`, `envelopeCorrection` (eliza port) |
| `agents/independent_verifier.py` | `Verdict`, `buildVerifierPrompt`, `verdictFromEnvelope`, `shouldRunIndependentVerify`, `runIndependentVerification` (eliza port) |
| `agents/evidence_receipt.py` | `buildReceipt`, `_computeFacts`, `_computeHeadline`, `_diffSha256` (loki ideas, reimplemented native) |

**Modified files:** `platform_core/app_config/llm.py` (5 knobs), `platform_core/orchestration/brain_io.py` (json_repair rung), `agents/executor.py` (`read_only` spec flag → `--disallowedTools Edit Write`), `platform_core/orchestration/plan_mixin.py` (delegate planner + append envelope instruction), `platform_core/orchestration/execute_mixin.py` (evidence gate + stall replan), `platform_core/orchestration/run_loop_mixin.py` (`_cascadeResetDependents` + stall branch), `state/task_schema.py` (`dependentsOf`), `requirements.txt` (`json-repair`), `AGENTS.md` (regenerated).

---

# PHASE A — Steal #9: JSON self-correction (smallest, de-risks the rest)

## Task 1: Config knobs for all three layers

**Files:**
- Modify: `platform_core/app_config/llm.py` (append after the `# --- Verification gate ---` block, ~line 239)
- Test: `tests/test_epic2_config.py`

- [ ] **Step 1: Write the failing test**

```python
"""Epic 2 staged-default config knobs are exposed via the config facade."""
import config


def test_dual_ledger_default_off():
    assert config.DUAL_LEDGER_PLANNER_ENABLED is False


def test_independent_verify_default_on():
    assert config.INDEPENDENT_VERIFY_ENABLED is True


def test_evidence_receipt_default_on():
    assert config.EVIDENCE_RECEIPT_ENABLED is True


def test_retry_and_stall_ints():
    assert config.BRAIN_JSON_RETRY_MAX == 2
    assert config.STALL_THRESHOLD == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_epic2_config.py -v`
Expected: FAIL with `AttributeError: module 'config' has no attribute 'DUAL_LEDGER_PLANNER_ENABLED'`

- [ ] **Step 3: Add the knobs**

In `platform_core/app_config/llm.py`, after the `VERIFY_TIMEOUT_SECONDS` line:

```python
# --- Epic 2: Trustworthy 7B loop (staged defaults; each layer independently flaggable) ---
# Dual-ledger planner ships DARK first (A/B vs the current planner on the golden eval suite).
DUAL_LEDGER_PLANNER_ENABLED: bool = _envBool("DUAL_LEDGER_PLANNER_ENABLED", False)
# Execution-grounded independent verifier + Evidence Receipt: additive, only DOWNGRADES, on by default.
INDEPENDENT_VERIFY_ENABLED: bool = _envBool("INDEPENDENT_VERIFY_ENABLED", True)  # code-change subtasks only
EVIDENCE_RECEIPT_ENABLED: bool = _envBool("EVIDENCE_RECEIPT_ENABLED", True)
# JSON self-correction: how many times to re-prompt the brain with exact field errors before giving up.
BRAIN_JSON_RETRY_MAX: int = _envInt("BRAIN_JSON_RETRY_MAX", 2)
# Dual-ledger stall counter: root-cause replan fires at/above this many consecutive stalls.
STALL_THRESHOLD: int = _envInt("STALL_THRESHOLD", 2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_epic2_config.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add platform_core/app_config/llm.py tests/test_epic2_config.py
git commit -m "feat(epic2): add staged-default config knobs for trustworthy-loop layers"
```

---

## Task 2: `json_repair` salvage rung in `brain_io.parseJsonText`

**Files:**
- Modify: `requirements.txt`
- Modify: `platform_core/orchestration/brain_io.py:49-65` (`parseJsonText` + new `_jsonRepairSalvage`)
- Test: `tests/test_brain_io_repair.py`

- [ ] **Step 1: Install the dep and add it to requirements**

```bash
python -m pip install json-repair
```

Add this line to `requirements.txt` (alphabetical-ish near other small deps):

```text
json-repair>=0.30
```

- [ ] **Step 2: Write the failing test**

```python
"""parseJsonText gains a third ladder rung: json_repair salvages truncated/malformed 7B JSON
AFTER strict parse + balanced-object extraction fail. Garbage still returns None."""
from platform_core.orchestration import brain_io


def test_truncated_object_salvaged():
    # missing closing brace + trailing comma: strict json.loads and balanced-walk both fail
    out = brain_io.parseJsonText('{"subtasks": [{"title": "a"},], "n": 3')
    assert isinstance(out, dict)
    assert out["n"] == 3


def test_clean_json_passthrough():
    assert brain_io.parseJsonText('{"x": 1}') == {"x": 1}


def test_pure_prose_returns_none():
    assert brain_io.parseJsonText("no json here at all") is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_brain_io_repair.py -v`
Expected: FAIL on `test_truncated_object_salvaged` (returns `None`)

- [ ] **Step 4: Add the rung**

In `platform_core/orchestration/brain_io.py`, replace the tail of `parseJsonText` (the `chunk = ...` block) and add a helper:

```python
def parseJsonText(text: str):
    """Parse JSON text, tolerating fences and leading/trailing prose.

    Ladder: (1) strict json.loads after fence-strip, (2) first balanced {...} object,
    (3) json_repair salvage of truncated/malformed 7B output (last resort)."""
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        pass
    chunk = llm_io._firstBalancedObject(text)
    if chunk:
        try:
            return json.loads(chunk)
        except Exception:  # noqa: BLE001
            pass
    return _jsonRepairSalvage(text)


def _jsonRepairSalvage(text: str):
    """Last-resort salvage of malformed/truncated JSON via the json_repair pip dep.

    Returns a dict/list only -- a repaired scalar/empty (e.g. from pure prose) yields None so the
    schema validator above this layer still rejects genuinely-broken output. No-op if json_repair
    is not installed."""
    try:
        from json_repair import repair_json
    except Exception:  # noqa: BLE001 -- optional dep; degrade to no salvage
        return None
    try:
        repaired = repair_json(text, return_objects=True)
    except Exception:  # noqa: BLE001
        return None
    return repaired if isinstance(repaired, (dict, list)) and repaired else None
```

- [ ] **Step 5: Run new + regression tests**

Run: `python -m pytest tests/test_brain_io_repair.py tests/test_chatjson_salvage.py -v`
Expected: PASS (all). `test_chatjson_salvage.py` still green proves the existing salvage contract is unchanged.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt platform_core/orchestration/brain_io.py tests/test_brain_io_repair.py
git commit -m "feat(epic2): add json_repair salvage rung to parseJsonText (steal #9)"
```

---

## Task 3: `brain_json._validateShape`

**Files:**
- Create: `platform_core/orchestration/brain_json.py`
- Test: `tests/test_brain_json.py`

- [ ] **Step 1: Write the failing test**

```python
"""Lightweight dict-shape validation: required keys present + per-field validators, no pydantic."""
from platform_core.orchestration import brain_json


def test_missing_required_key_reported():
    errors = brain_json._validateShape({"a": 1}, ["a", "b"], {})
    assert any("b:" in e and "missing" in e for e in errors)


def test_non_object_root_reported():
    errors = brain_json._validateShape([1, 2], ["a"], {})
    assert errors and "<root>" in errors[0]


def test_validator_failure_reports_repr():
    errors = brain_json._validateShape(
        {"n": "oops"}, ["n"], {"n": lambda v: isinstance(v, int)})
    assert any("n:" in e and "'oops'" in e for e in errors)


def test_clean_object_no_errors():
    assert brain_json._validateShape({"n": 3}, ["n"], {"n": lambda v: isinstance(v, int)}) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_brain_json.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'platform_core.orchestration.brain_json'`

- [ ] **Step 3: Create the module with `_validateShape`**

```python
"""Schema-validated JSON self-correction loop for the 7B brain (no pydantic dependency).

Wraps -- never replaces -- the existing brain JSON path: it calls a chat callable, parses via the
hardened brain_io.parseJsonText, runs a lightweight dict-shape check, and on failure re-prompts the
brain with its EXACT field errors (pydantic-ai's _format_error_details ported to plain strings).

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  chatJsonValidated(ollama_chat, system, user, *, required_keys, validators, max_retries) -- validated brain JSON call with field-error retry
DEPENDS-ON: config, platform_core.orchestration.brain_io
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/test_brain_json.py
"""
from __future__ import annotations

from typing import Callable, Optional

import config
from platform_core.orchestration.brain_io import _chatText, parseJsonText


def _validateShape(obj, required_keys: list[str], validators: dict) -> list[str]:
    """Return a list of human-readable field errors ('' => valid). Each error is the pydantic-ai
    shape: '<key>: <msg> [got <repr>]'."""
    if not isinstance(obj, dict):
        return [f"<root>: expected a JSON object [got {type(obj).__name__}]"]
    errors: list[str] = []
    for key in required_keys or []:
        if key not in obj:
            errors.append(f"{key}: required key missing [got <absent>]")
    for key, fn in (validators or {}).items():
        if key not in obj:
            continue
        try:
            ok = bool(fn(obj[key]))
        except Exception:  # noqa: BLE001 -- a throwing validator means the value is wrong-shaped
            ok = False
        if not ok:
            errors.append(f"{key}: failed validation [got {obj[key]!r}]")
    return errors
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_brain_json.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/brain_json.py tests/test_brain_json.py
git commit -m "feat(epic2): add brain_json._validateShape (steal #9)"
```

---

## Task 4: `brain_json._makeRetryPrompt`

**Files:**
- Modify: `platform_core/orchestration/brain_json.py`
- Test: `tests/test_brain_json.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/test_brain_json.py`:

```python
def test_retry_prompt_carries_exact_errors():
    prompt = brain_json._makeRetryPrompt(["b: required key missing [got <absent>]"])
    assert "b: required key missing" in prompt
    assert "ONLY" in prompt  # instructs the brain to return only corrected JSON
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_brain_json.py::test_retry_prompt_carries_exact_errors -v`
Expected: FAIL with `AttributeError: module ... has no attribute '_makeRetryPrompt'`

- [ ] **Step 3: Add `_makeRetryPrompt`**

In `platform_core/orchestration/brain_json.py`, after `_validateShape`:

```python
def _makeRetryPrompt(errors: list[str]) -> str:
    """Build the corrective re-prompt (pydantic-ai's retry message, plain-string form).
    Hands the brain its exact field errors so the next attempt is targeted, not a blind re-roll."""
    bullets = "\n".join(f"- {e}" for e in errors)
    return (
        "Your previous response was NOT valid for the required schema. Fix EXACTLY these field "
        "errors and respond with ONLY the corrected JSON object (no prose, no fences):\n" + bullets
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_brain_json.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/brain_json.py tests/test_brain_json.py
git commit -m "feat(epic2): add brain_json._makeRetryPrompt (steal #9)"
```

---

## Task 5: `brain_json.chatJsonValidated` retry loop

**Files:**
- Modify: `platform_core/orchestration/brain_json.py`
- Test: `tests/test_brain_json.py`

- [ ] **Step 1: Add the failing test (mocked chat callable, no real Ollama)**

Append to `tests/test_brain_json.py`:

```python
class _FakeChat:
    """A stand-in for self._ollamaChat: returns a queued list of fake resp dicts in order."""
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, system, user, *, want_json=False):
        self.calls.append(user)
        body = self.replies.pop(0)
        return {"message": {"content": body}}


def test_recovers_within_retry_budget():
    chat = _FakeChat(['{"a": "wrong"}', '{"a": 1, "b": 2}'])
    out = brain_json.chatJsonValidated(
        chat, "sys", "do it", required_keys=["a", "b"],
        validators={"a": lambda v: isinstance(v, int)}, max_retries=2)
    assert out == {"a": 1, "b": 2}
    # the 2nd call's user prompt must carry the exact field error from the 1st
    assert "a: failed validation" in chat.calls[1]


def test_exhausts_and_returns_none():
    chat = _FakeChat(['not json', 'still not', 'nope'])
    out = brain_json.chatJsonValidated(
        chat, "sys", "do it", required_keys=["a"], max_retries=2)
    assert out is None
    assert len(chat.calls) == 3  # initial + 2 retries, bounded by max_retries
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_brain_json.py -k chatJsonValidated_or_recovers -v` then
Run: `python -m pytest tests/test_brain_json.py -v`
Expected: FAIL with `AttributeError: ... has no attribute 'chatJsonValidated'`

- [ ] **Step 3: Add `chatJsonValidated`**

In `platform_core/orchestration/brain_json.py`, after `_makeRetryPrompt`:

```python
def chatJsonValidated(ollama_chat: Callable, system: str, user: str, *,
                      required_keys: list[str], validators: Optional[dict] = None,
                      max_retries: Optional[int] = None) -> Optional[dict]:
    """Call the brain for JSON, validate its shape, and re-prompt with exact field errors on failure.

    ``ollama_chat`` is a ``(system, user, *, want_json=True) -> resp`` callable (typically
    ``self._ollamaChat``). Returns the validated dict, or ``None`` when the brain still fails after
    ``max_retries`` corrective re-prompts (the caller then keeps its existing fallback)."""
    validators = validators or {}
    if max_retries is None:
        max_retries = config.BRAIN_JSON_RETRY_MAX
    cur_user = user
    for _ in range(max_retries + 1):
        resp = ollama_chat(system, cur_user, want_json=True)
        parsed = parseJsonText(_chatText(resp).strip())
        errors = _validateShape(parsed, required_keys, validators)
        if not errors:
            return parsed
        cur_user = user + "\n\n" + _makeRetryPrompt(errors)
    return None
```

- [ ] **Step 4: Run test + size check**

Run: `python -m pytest tests/test_brain_json.py -v`
Expected: PASS (7 passed)
Run: `python tools/dev.py check platform_core/orchestration/brain_json.py`
Expected: PASS (lint/size clean)

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/brain_json.py tests/test_brain_json.py
git commit -m "feat(epic2): add brain_json.chatJsonValidated retry loop (steal #9)"
```

---

# PHASE B — Steal #3: execution-grounded verifier + Evidence Receipt

## Task 6: `agents/completion_envelope.py` — schema + parser

**Files:**
- Create: `agents/completion_envelope.py`
- Test: `tests/test_completion_envelope.py`

- [ ] **Step 1: Write the failing test (port eliza's parser cases)**

```python
"""CompletionEnvelope parser: absent => fall-back, malformed => correction, valid => parsed."""
from agents import completion_envelope as ce


_VALID = '''Done. Summary follows.
```json
{"diff_summary": "added foo", "files_changed": ["foo.py"],
 "test_results": [{"command": "pytest", "exit_code": 0, "summary": "1 passed"}],
 "acceptance_criteria_status": [{"criterion": "foo works", "met": true, "evidence": "pytest green"}],
 "residual_risks": []}
```'''


def test_absent_envelope_falls_back():
    parse = ce.parseCompletionEnvelope("just some narration, no fenced json")
    assert parse.present is False
    assert parse.envelope is None


def test_valid_envelope_parsed():
    parse = ce.parseCompletionEnvelope(_VALID)
    assert parse.present and not parse.malformed
    env = parse.envelope
    assert env.files_changed == ["foo.py"]
    assert env.test_results[0]["exit_code"] == 0
    assert env.acceptance_criteria_status[0]["met"] is True


def test_malformed_envelope_flagged():
    bad = "```json\n{\"diff_summary\": \"x\"\n```"  # missing required keys + broken
    parse = ce.parseCompletionEnvelope(bad)
    assert parse.present and parse.malformed
    assert parse.error


def test_last_fenced_block_wins():
    text = "```json\n{\"old\": 1}\n```\nthen\n" + _VALID
    parse = ce.parseCompletionEnvelope(text)
    assert parse.envelope is not None and parse.envelope.files_changed == ["foo.py"]


def test_envelope_correction_mentions_error():
    msg = ce.envelopeCorrection("missing key: files_changed")
    assert "files_changed" in msg and "json" in msg.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_completion_envelope.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agents.completion_envelope'`

- [ ] **Step 3: Create the module**

```python
"""CompletionEnvelope -- the structured "what I did + evidence" block the executor emits when FINISHED.

Ported from eliza's plugin-agent-orchestrator completion-envelope.ts (MIT). The envelope is the
contract the independent verifier and the Evidence Receipt consume. Parsing is pure: the LAST fenced
```json block is authoritative; absent => caller keeps today's heuristic verify path (back-compat);
present-but-malformed => the caller re-prompts via envelopeCorrection.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  CompletionEnvelope  -- executor's structured completion claim
  EnvelopeParse  -- (envelope, present, malformed, error) parse outcome
  COMPLETION_ENVELOPE_INSTRUCTION  -- appended to the executor prompt
  parseCompletionEnvelope(text)  -- parse the last fenced json block into an EnvelopeParse
  summarizeEnvelope(env)  -- one-line human summary for notes/receipts
  envelopeCorrection(error)  -- targeted re-prompt for a malformed envelope
DEPENDS-ON: (stdlib only)
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/test_completion_envelope.py
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

_REQUIRED_KEYS = ("diff_summary", "files_changed", "test_results",
                  "acceptance_criteria_status", "residual_risks")

COMPLETION_ENVELOPE_INSTRUCTION: str = (
    "\n\nWHEN FINISHED, end your FINAL message with a single fenced ```json block matching EXACTLY "
    "this schema (no prose after it):\n"
    '{"diff_summary": "<one line>", "files_changed": ["<path>"], '
    '"test_results": [{"command": "<cmd>", "exit_code": 0, "summary": "<short>"}], '
    '"acceptance_criteria_status": [{"criterion": "<text>", "met": true, "evidence": "<how>"}], '
    '"residual_risks": ["<risk>"], "screenshot_paths": []}\n'
    "Report acceptance_criteria_status HONESTLY -- mark met=false with evidence when a criterion is "
    "not satisfied; do not claim a passing test you did not run."
)


@dataclass
class CompletionEnvelope:
    diff_summary: str
    files_changed: list
    test_results: list           # [{command, exit_code, summary}]
    acceptance_criteria_status: list  # [{criterion, met, evidence}]
    residual_risks: list
    screenshot_paths: list = field(default_factory=list)


@dataclass
class EnvelopeParse:
    envelope: "CompletionEnvelope | None"
    present: bool
    malformed: bool
    error: str = ""


_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def parseCompletionEnvelope(text: str) -> EnvelopeParse:
    """Parse the LAST fenced json block of *text* into an EnvelopeParse."""
    if not text:
        return EnvelopeParse(None, present=False, malformed=False)
    blocks = _FENCE_RE.findall(text)
    if not blocks:
        return EnvelopeParse(None, present=False, malformed=False)
    raw = blocks[-1]
    try:
        obj = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        return EnvelopeParse(None, present=True, malformed=True, error=f"invalid JSON: {e}")
    if not isinstance(obj, dict):
        return EnvelopeParse(None, present=True, malformed=True, error="envelope is not an object")
    missing = [k for k in _REQUIRED_KEYS if k not in obj]
    if missing:
        return EnvelopeParse(None, present=True, malformed=True,
                             error="missing key(s): " + ", ".join(missing))
    env = CompletionEnvelope(
        diff_summary=str(obj.get("diff_summary", "")),
        files_changed=list(obj.get("files_changed") or []),
        test_results=[t for t in (obj.get("test_results") or []) if isinstance(t, dict)],
        acceptance_criteria_status=[c for c in (obj.get("acceptance_criteria_status") or [])
                                    if isinstance(c, dict)],
        residual_risks=list(obj.get("residual_risks") or []),
        screenshot_paths=list(obj.get("screenshot_paths") or []),
    )
    return EnvelopeParse(env, present=True, malformed=False)


def summarizeEnvelope(env: "CompletionEnvelope | None") -> str:
    """One-line human summary for an Obsidian note / receipt assessment."""
    if env is None:
        return "(no completion envelope)"
    met = sum(1 for c in env.acceptance_criteria_status if c.get("met"))
    total = len(env.acceptance_criteria_status)
    green = sum(1 for t in env.test_results if t.get("exit_code") == 0)
    return (f"{met}/{total} criteria met; {green}/{len(env.test_results)} checks green; "
            f"{len(env.files_changed)} file(s) changed")


def envelopeCorrection(error: str) -> str:
    """Targeted re-prompt when the executor emitted a malformed envelope."""
    return (f"Your completion envelope was malformed ({error}). Re-emit ONLY a single fenced "
            "```json block with keys: " + ", ".join(_REQUIRED_KEYS) + ".")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_completion_envelope.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add agents/completion_envelope.py tests/test_completion_envelope.py
git commit -m "feat(epic2): add CompletionEnvelope schema + parser (steal #3, eliza port)"
```

---

## Task 7: `agents/evidence_receipt.py` — facts → headline (loki ideas, reimplemented)

**Files:**
- Create: `agents/evidence_receipt.py`
- Test: `tests/test_evidence_receipt.py`

- [ ] **Step 1: Write the failing test**

```python
"""Evidence Receipt headline is derived ONLY from facts (diff sha + exit codes), never LLM opinion."""
from agents import evidence_receipt as er


def _facts(checks, files_changed=2, diff="a.py | 3 +++"):
    git = {"base_sha": "b", "head_sha": "h", "diff_sha256": er._diffSha256(diff)}
    return {"git": git, "files_changed": files_changed, "criteria_reported": 1, "checks": checks}


def test_failed_check_forces_not_verified():
    f = _facts([{"command": "pytest", "exit_code": 1, "status": "fail"}])
    assert er._computeHeadline(f) == "NOT_VERIFIED"


def test_all_green_nonempty_diff_is_verified():
    f = _facts([{"command": "pytest", "exit_code": 0, "status": "pass"}])
    assert er._computeHeadline(f) == "VERIFIED"


def test_inconclusive_check_is_gaps():
    f = _facts([{"command": "pytest", "exit_code": None, "status": "inconclusive"}])
    assert er._computeHeadline(f) == "VERIFIED_WITH_GAPS"


def test_no_criteria_reported_is_gaps():
    f = _facts([{"command": "pytest", "exit_code": 0, "status": "pass"}])
    f["criteria_reported"] = 0
    assert er._computeHeadline(f) == "VERIFIED_WITH_GAPS"


def test_empty_diff_forces_not_verified():
    f = _facts([{"command": "pytest", "exit_code": 0, "status": "pass"}], files_changed=0, diff="")
    assert er._computeHeadline(f) == "NOT_VERIFIED"


def test_diff_sha_is_stable():
    assert er._diffSha256("a.py | 3 +++") == er._diffSha256("a.py | 3 +++")


def test_build_receipt_separates_facts_and_assessments():
    rec = er.buildReceipt(
        goal="g",
        git_info={"base_sha": "b", "head_sha": "h", "diff_text": "a.py | 3 +++", "files_changed": 2},
        det_check={"command": "python a.py", "exit_code": 0},
        indep_checks=[{"command": "pytest", "exit_code": 0, "summary": "1 passed"}],
        criteria_reported=1,
        assessments={"criteria": [{"criterion": "x", "met": True}], "adversary_verdict": "approved"})
    assert rec["headline"] == "VERIFIED"
    assert "git" in rec["facts"] and "criteria" in rec["assessments"]
    assert rec["assessments"]["non_binding"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_evidence_receipt.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agents.evidence_receipt'`

- [ ] **Step 3: Create the module**

```python
"""Evidence Receipt -- facts vs assessments, with a headline derived ONLY from facts.

Reimplements the IDEAS of loki-mode's proof-generator (BUSL -- NO code vendored). A receipt splits
re-derivable FACTS (git shas, a sha256 of the canonical diff, per-check exit codes) from non-binding
LLM ASSESSMENTS (per-criterion judgments, adversary verdict). The headline is computed purely from
facts so the same brain can never bless its own work: VERIFIED / VERIFIED_WITH_GAPS / NOT_VERIFIED.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  buildReceipt(goal, git_info, det_check, indep_checks, criteria_reported, assessments)  -- pure receipt dict
DEPENDS-ON: (stdlib only)
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/test_evidence_receipt.py
"""
from __future__ import annotations

import hashlib

VERIFIED = "VERIFIED"
VERIFIED_WITH_GAPS = "VERIFIED_WITH_GAPS"
NOT_VERIFIED = "NOT_VERIFIED"


def _diffSha256(diff_text: str) -> str:
    """sha256 of the canonical diff text -- a re-derivable fingerprint of the change."""
    return hashlib.sha256((diff_text or "").encode("utf-8", errors="ignore")).hexdigest()


def _statusFor(exit_code) -> str:
    if exit_code is None:
        return "inconclusive"
    return "pass" if exit_code == 0 else "fail"


def _computeFacts(git_info: dict, det_check: dict, indep_checks: list, criteria_reported: int) -> dict:
    """Assemble the deterministic, re-derivable fact set (NON-LLM)."""
    diff_text = (git_info or {}).get("diff_text", "")
    git = {
        "base_sha": (git_info or {}).get("base_sha"),
        "head_sha": (git_info or {}).get("head_sha"),
        "diff_sha256": _diffSha256(diff_text) if diff_text else "",
    }
    checks: list[dict] = []
    for c in ([det_check] if det_check else []) + list(indep_checks or []):
        ec = c.get("exit_code")
        checks.append({"command": c.get("command"), "exit_code": ec, "status": _statusFor(ec)})
    return {
        "git": git,
        "files_changed": int((git_info or {}).get("files_changed") or 0),
        "criteria_reported": int(criteria_reported or 0),
        "checks": checks,
    }


def _computeHeadline(facts: dict) -> str:
    """Headline from FACTS ONLY (loki _compute_headline idea). A hard-failed ran-check or an empty
    diff forces NOT_VERIFIED; an inconclusive check or zero reported criteria => VERIFIED_WITH_GAPS;
    otherwise VERIFIED."""
    checks = facts.get("checks") or []
    ran = [c for c in checks if c.get("exit_code") is not None]
    inconclusive = [c for c in checks if c.get("exit_code") is None]
    empty_diff = not facts.get("git", {}).get("diff_sha256") or facts.get("files_changed", 0) == 0
    if any(c["exit_code"] != 0 for c in ran) or empty_diff or not ran:
        return NOT_VERIFIED
    if inconclusive or facts.get("criteria_reported", 0) < 1:
        return VERIFIED_WITH_GAPS
    return VERIFIED


def buildReceipt(goal: str, git_info: dict, det_check: dict, indep_checks: list,
                 criteria_reported: int, assessments: dict) -> dict:
    """Pure: build the Evidence Receipt dict. The caller persists it as a per-subtask Obsidian note
    and gates ONLY on ``headline`` (through the verifier-owned recordVerify path)."""
    facts = _computeFacts(git_info, det_check, indep_checks, criteria_reported)
    return {
        "goal": goal,
        "facts": facts,
        "assessments": {**(assessments or {}), "non_binding": True},
        "headline": _computeHeadline(facts),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_evidence_receipt.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add agents/evidence_receipt.py tests/test_evidence_receipt.py
git commit -m "feat(epic2): add Evidence Receipt facts->headline (steal #3, loki ideas reimplemented)"
```

---

## Task 8: `agents/executor.py` — `read_only` spec flag

**Files:**
- Modify: `agents/executor.py:134-139` (`_buildRunConfig`)
- Test: `tests/test_executor_readonly.py`

- [ ] **Step 1: Write the failing test**

```python
"""A spec with read_only=True must disallow Edit/Write at the hands layer (enforced read-only verify)."""
from unittest import mock

import config
from agents import executor


def _build(spec):
    with mock.patch.object(executor, "_resolveClaudeLauncher", return_value=["claude"]):
        fresh_cmd, _resume, _env, _flags, _model = executor._buildRunConfig(
            spec, task_state=None, subtask=None, resume_session=None,
            work=str(config.PROJECT_ROOT), effort="default", flag=None,
            charter="", claude_md_path=None)
    return fresh_cmd


def test_read_only_disallows_edit_write():
    cmd = _build({"read_only": True})
    assert "--disallowedTools" in cmd
    i = cmd.index("--disallowedTools")
    assert cmd[i + 1] == "Edit" and cmd[i + 2] == "Write"


def test_normal_spec_has_no_global_disallow():
    cmd = _build({})
    # no bare 'Edit'/'Write' disallow tokens for a normal write subtask
    assert "Edit" not in cmd and "Write" not in cmd
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_executor_readonly.py -v`
Expected: FAIL (`--disallowedTools Edit Write` not present)

- [ ] **Step 3: Honor `read_only` in `_buildRunConfig`**

In `agents/executor.py`, immediately after the `--add-dir` line (134) and before the self-ref core-file block:

```python
    base_cmd += ["--add-dir", str(config.PROJECT_ROOT)]   # make .claude discoverable from a sub-cwd
    # Epic 2: a read-only spec (the independent verifier) is denied Edit/Write at the hands layer, so
    # read-only is enforced by the tools layer -- not just the prompt -- same mechanism as the
    # CORE_PROTECTED_FILES self-ref disallow below.
    if isinstance(spec, dict) and spec.get("read_only"):
        base_cmd += ["--disallowedTools", "Edit", "Write"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_executor_readonly.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add agents/executor.py tests/test_executor_readonly.py
git commit -m "feat(epic2): honor read_only spec flag -> --disallowedTools Edit Write (steal #3)"
```

---

## Task 9: `agents/independent_verifier.py` — verdict + gating + spawn

**Files:**
- Create: `agents/independent_verifier.py`
- Test: `tests/test_independent_verifier.py`

- [ ] **Step 1: Write the failing test (pure parts + mocked spawn)**

```python
"""Independent verifier: verdict from an envelope, gating, and a read-only spawn that NEVER auto-passes."""
from unittest import mock

from agents import completion_envelope as ce
from agents import independent_verifier as iv


def test_verdict_passes_only_when_all_met_and_green():
    env = ce.CompletionEnvelope(
        diff_summary="x", files_changed=["a.py"],
        test_results=[{"command": "pytest", "exit_code": 0}],
        acceptance_criteria_status=[{"criterion": "c", "met": True}], residual_risks=[])
    v = iv.verdictFromEnvelope(env)
    assert v.passed and not v.inconclusive and v.unmet == []


def test_verdict_unmet_criterion_fails():
    env = ce.CompletionEnvelope(
        diff_summary="x", files_changed=["a.py"],
        test_results=[{"command": "pytest", "exit_code": 0}],
        acceptance_criteria_status=[{"criterion": "c", "met": False}], residual_risks=[])
    v = iv.verdictFromEnvelope(env)
    assert not v.passed and v.unmet == ["c"]


def test_no_envelope_is_inconclusive_never_passes():
    v = iv.verdictFromEnvelope(None)
    assert not v.passed and v.inconclusive


def test_no_criteria_is_inconclusive():
    env = ce.CompletionEnvelope("x", ["a.py"], [{"command": "p", "exit_code": 0}], [], [])
    v = iv.verdictFromEnvelope(env)
    assert v.inconclusive and not v.passed


def test_gating_requires_code_change_and_flag():
    assert iv.shouldRunIndependentVerify(enabled=True, has_code_change=True, tree_shared=False)
    assert not iv.shouldRunIndependentVerify(enabled=False, has_code_change=True, tree_shared=False)
    assert not iv.shouldRunIndependentVerify(enabled=True, has_code_change=False, tree_shared=False)
    assert not iv.shouldRunIndependentVerify(enabled=True, has_code_change=True, tree_shared=True)


def test_spawn_crash_is_inconclusive():
    def boom(*a, **k):
        return {"ok": False, "stdout": "", "stderr": "spawn failed"}
    parse = iv.runIndependentVerification(
        boom, goal="g", acceptance_criteria="c", diff_summary="d",
        work_dir=".", task_state=None, subtask={"subtask_id": "st-001"})
    assert parse.present is False  # no envelope => caller treats as inconclusive, never auto-pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_independent_verifier.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agents.independent_verifier'`

- [ ] **Step 3: Create the module**

```python
"""Independent execution-grounded verifier (Agent-as-a-Judge), ported from eliza (MIT).

A SEPARATE read-only Claude subprocess re-runs tests/build/typecheck, reads files and `git diff`, and
emits ONLY a CompletionEnvelope. Its verdict can only DOWNGRADE a deterministic pass, never upgrade a
fail: no envelope (spawn crash / empty) => inconclusive => never auto-pass. Read-only is enforced by
the hands layer via the spec's ``read_only`` flag (--disallowedTools Edit Write), not just the prompt.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  Verdict  -- (passed, unmet, failed_commands, inconclusive)
  buildVerifierPrompt(goal, acceptance_criteria, diff_summary)  -- the judge prompt
  verdictFromEnvelope(env)  -- derive a Verdict from a CompletionEnvelope (or None)
  shouldRunIndependentVerify(*, enabled, has_code_change, tree_shared)  -- gating
  runIndependentVerification(run_claude, goal, acceptance_criteria, diff_summary, work_dir, task_state, subtask, cancel_check)  -- spawn + parse
DEPENDS-ON: agents.completion_envelope
SIDE-EFFECTS: spawns a read-only Claude subprocess
RUN/TEST: python -m pytest tests/test_independent_verifier.py
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from agents.completion_envelope import (
    COMPLETION_ENVELOPE_INSTRUCTION, EnvelopeParse, parseCompletionEnvelope)


@dataclass
class Verdict:
    passed: bool
    unmet: list
    failed_commands: list
    inconclusive: bool


def buildVerifierPrompt(goal: str, acceptance_criteria: str, diff_summary: str) -> str:
    """The eliza independent-verifier prompt: confirm by EXECUTION, not narration; read-only."""
    return (
        "You are an INDEPENDENT verifier. Do NOT trust any narration of what was done -- confirm by "
        "EXECUTION. You are READ-ONLY: run the tests/build/typecheck, read files, and inspect "
        "`git diff`; you may NOT edit or write any file.\n\n"
        f"GOAL:\n{goal}\n\nACCEPTANCE CRITERIA:\n{acceptance_criteria}\n\n"
        f"CLAIMED CHANGE:\n{diff_summary}\n\n"
        "Judge EACH acceptance criterion by the evidence you gather yourself. Output ONLY a "
        "CompletionEnvelope." + COMPLETION_ENVELOPE_INSTRUCTION
    )


def verdictFromEnvelope(env) -> Verdict:
    """passed only when every criterion met AND every test exit_code==0 AND >=1 criterion reported.
    No envelope or no criteria => inconclusive (never auto-pass)."""
    if env is None:
        return Verdict(False, [], [], inconclusive=True)
    criteria = env.acceptance_criteria_status or []
    if not criteria:
        return Verdict(False, [], [], inconclusive=True)
    unmet = [c.get("criterion", "?") for c in criteria if not c.get("met")]
    failed = [t.get("command", "?") for t in (env.test_results or [])
              if t.get("exit_code") not in (0, None)]
    passed = (not unmet) and (not failed)
    return Verdict(passed, unmet, failed, inconclusive=False)


def shouldRunIndependentVerify(*, enabled: bool, has_code_change: bool, tree_shared: bool) -> bool:
    """Gate: only for code-change subtasks, only when enabled, and NEVER on a shared tree under
    parallelism (a read-only spawn is fine, but we reuse the adversary's shared-tree guard so the
    bounded extra Claude cost is skipped where remediation would also be skipped)."""
    return bool(enabled) and bool(has_code_change) and not bool(tree_shared)


def runIndependentVerification(run_claude: Callable, *, goal: str, acceptance_criteria: str,
                               diff_summary: str, work_dir: str, task_state, subtask: dict,
                               cancel_check: Optional[Callable] = None) -> EnvelopeParse:
    """Spawn a SEPARATE read-only Claude subprocess and parse its CompletionEnvelope.

    On any spawn failure / empty output the parse is ``present=False`` (inconclusive) so the caller
    can never turn a flaky verifier into a green run."""
    spec = {
        "prompt": buildVerifierPrompt(goal, acceptance_criteria, diff_summary),
        "effort_level": "high",      # fixed modest effort; does NOT change the subtask's own routing
        "read_only": True,           # hands layer denies Edit/Write
        "claude_md_inject": "",
        "skills_to_invoke": [], "subagent": None,
        "pre_tool_hooks": [], "post_tool_hooks": [], "use_workflow": False,
        "workflow_definition": None,
    }
    try:
        result = run_claude(spec, work_dir=work_dir, task_state=task_state, subtask=subtask,
                            cancel_check=cancel_check)
    except Exception:  # noqa: BLE001 -- a spawn crash is inconclusive, never a false pass
        return EnvelopeParse(None, present=False, malformed=False, error="verifier spawn crashed")
    stdout = result.get("stdout", "") if isinstance(result, dict) else ""
    return parseCompletionEnvelope(stdout)
```

- [ ] **Step 4: Run test + size check**

Run: `python -m pytest tests/test_independent_verifier.py -v`
Expected: PASS (6 passed)
Run: `python tools/dev.py check agents/independent_verifier.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agents/independent_verifier.py tests/test_independent_verifier.py
git commit -m "feat(epic2): add independent execution-grounded verifier (steal #3, eliza port)"
```

---

## Task 10: Append `COMPLETION_ENVELOPE_INSTRUCTION` in `authorInvocationSpec`

**Files:**
- Modify: `platform_core/orchestration/plan_mixin.py:326-329` (beside `reflection.REQUEST`)
- Test: `tests/test_envelope_instruction_append.py`

- [ ] **Step 1: Write the failing test**

```python
"""When INDEPENDENT_VERIFY_ENABLED, the executor prompt carries the CompletionEnvelope instruction."""
import tempfile
from pathlib import Path
from unittest import mock

import config
from agents import completion_envelope as ce
from orchestrator import Orchestrator
from state.task import TaskState


def _spec_with_flag(flag):
    d = Path(tempfile.mkdtemp())
    with mock.patch.object(config, "STATE_DIR", d), \
         mock.patch.object(config, "INDEPENDENT_VERIFY_ENABLED", flag), \
         mock.patch.object(config, "SIE_REFLECTION_ENABLED", False):
        st = TaskState.create("goal", 1.0)
        st.meta["goal_elaborated"] = "build a thing"
        orch = Orchestrator()
        # brain returns a minimal valid spec with a prompt
        orch._ollamaChat = mock.Mock(return_value={"message": {"content":
            '{"prompt": "do the work", "claude_md_inject": "", "effort_level": "high"}'}})
        sub = {"subtask_id": "st-001", "title": "t", "description": "d", "verify": {}}
        return orch.authorInvocationSpec(st, sub, "arch")


def test_instruction_appended_when_enabled():
    spec = _spec_with_flag(True)
    assert ce.COMPLETION_ENVELOPE_INSTRUCTION.strip()[:20] in spec["prompt"]


def test_instruction_absent_when_disabled():
    spec = _spec_with_flag(False)
    assert "CompletionEnvelope" not in spec["prompt"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_envelope_instruction_append.py -v`
Expected: FAIL on `test_instruction_appended_when_enabled`

- [ ] **Step 3: Append the instruction**

In `platform_core/orchestration/plan_mixin.py`, add the import near the top (after line 19, the `from agents import verifier`):

```python
from agents.completion_envelope import COMPLETION_ENVELOPE_INSTRUCTION
```

Then in `authorInvocationSpec`, replace the SIE reflection block (lines 325-329) with:

```python
        # SIE subsystem I: ask the executor (the strong teacher) for a learning summary so
        # we can distill its reasoning. Best-effort + only if it produced a prompt.
        try:
            if config.SIE_REFLECTION_ENABLED and spec.get("prompt"):
                spec["prompt"] = f"{spec['prompt']}\n\n{reflection.REQUEST}"
        except Exception:  # noqa: BLE001
            pass
        # Epic 2 (steal #3): require a CompletionEnvelope so the independent verifier + Evidence
        # Receipt have a structured claim to judge. Gated; absent envelope => today's heuristic path.
        if config.INDEPENDENT_VERIFY_ENABLED and spec.get("prompt"):
            spec["prompt"] = spec["prompt"] + COMPLETION_ENVELOPE_INSTRUCTION
        return spec
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_envelope_instruction_append.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/plan_mixin.py tests/test_envelope_instruction_append.py
git commit -m "feat(epic2): append CompletionEnvelope instruction in authorInvocationSpec (steal #3)"
```

---

## Task 11: Evidence gate in `_runAttemptVerify` — MODE-DEPENDENT downgrade (LOCKED)

**Files:**
- Modify: `platform_core/orchestration/execute_mixin.py` (new `_gitDiffFacts` + `_runEvidenceGate`; call site in `_runAttemptVerify` after the self-ref gate block, ~line 134)
- Test: `tests/test_evidence_gate.py`

- [ ] **Step 1: Write the failing test**

```python
"""The evidence gate can only DOWNGRADE a deterministic pass, and the downgrade is MODE-DEPENDENT:
self-improvement run => HARD-FAIL; normal product run => VERIFIED_WITH_GAPS, run continues."""
import tempfile
from pathlib import Path
from unittest import mock

import config
from agents import evidence_receipt as er
from agents import independent_verifier as iv
from agents.completion_envelope import EnvelopeParse
from orchestrator import Orchestrator
from state.task import TaskState


def _orch_state(self_ref):
    d = Path(tempfile.mkdtemp())
    p = mock.patch.object(config, "STATE_DIR", d)
    p.start()
    st = TaskState.create("goal", 1.0)
    st.meta["goal_elaborated"] = "build a thing"
    st.meta["is_self_referential"] = self_ref
    st.addSubtask("t", "d")  # st-001
    orch = Orchestrator()
    orch.obs = mock.Mock()
    orch._work_dir = str(config.PROJECT_ROOT)
    orch._parallelism = 1
    return orch, st, p


def _run_gate(orch, st):
    sub = st.getSubtask("st-001")
    vres = {"passed": True, "cmd": "python a.py", "expect": "exit_zero", "returncode": 0,
            "stdout": "", "stderr": ""}
    # force a NOT_VERIFIED outcome: non-empty diff but the independent verifier returns no envelope
    with mock.patch.object(orch, "_gitDiffFacts", return_value={
            "base_sha": "b", "head_sha": "h", "diff_text": "a.py | 1 +", "files_changed": 1}), \
         mock.patch.object(iv, "runIndependentVerification",
                           return_value=EnvelopeParse(None, present=False, malformed=False)), \
         mock.patch.object(er, "_computeHeadline", return_value="NOT_VERIFIED"):
        return orch._runEvidenceGate(st, sub, {"ok": True, "stdout": ""},
                                     str(config.PROJECT_ROOT), dict(vres), "st-001")


def test_self_ref_not_verified_hard_fails():
    orch, st, p = _orch_state(self_ref=True)
    try:
        vres, passed = _run_gate(orch, st)
        assert passed is False
        assert vres["passed"] is False
        assert vres.get("evidence_headline") == "NOT_VERIFIED"
    finally:
        p.stop()


def test_product_run_not_verified_continues_with_gaps():
    orch, st, p = _orch_state(self_ref=False)
    try:
        vres, passed = _run_gate(orch, st)
        assert passed is True  # run continues
        assert vres.get("evidence_headline") == "VERIFIED_WITH_GAPS"
        assert vres.get("evidence_gap")  # loud gap note attached
    finally:
        p.stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_evidence_gate.py -v`
Expected: FAIL with `AttributeError: 'Orchestrator' object has no attribute '_runEvidenceGate'`

- [ ] **Step 3: Add imports, `_gitDiffFacts`, and `_runEvidenceGate`**

In `platform_core/orchestration/execute_mixin.py`, add to the imports (after line 18 `from agents import adversary, second_brain, verifier`):

```python
from agents import evidence_receipt, independent_verifier
from agents.completion_envelope import summarizeEnvelope
```

Add `import subprocess` near the top imports (after `import time`).

Then add these two methods to `OrchestratorExecuteMixin` (place after `_runAttemptVerify`):

```python
    def _gitDiffFacts(self, work_dir: str) -> dict:
        """Best-effort, re-derivable git facts for the receipt: head sha, working-tree diff text, and
        the count of changed files. Returns {} on any error (gate then treats it as no code change)."""
        def _git(*args) -> str:
            try:
                out = subprocess.run(["git", "-C", work_dir, *args], capture_output=True,
                                     text=True, timeout=config.GIT_TIMEOUT_SECONDS)
                return (out.stdout or "").strip()
            except Exception:  # noqa: BLE001
                return ""
        head = _git("rev-parse", "HEAD")
        if not head:
            return {}
        diff_text = _git("diff", "--stat")
        porcelain = _git("status", "--porcelain")
        files_changed = len([ln for ln in porcelain.splitlines() if ln.strip()])
        return {"base_sha": head, "head_sha": head, "diff_text": diff_text,
                "files_changed": files_changed}

    def _runEvidenceGate(self, state: TaskState, subtask: dict, result: dict, exec_cwd: str,
                         vresult: dict, sid: str) -> "tuple[dict, bool]":
        """For a code-change subtask that PASSED the deterministic gate: run the independent verifier,
        build an Evidence Receipt, and DOWNGRADE on a NOT_VERIFIED headline. MODE-DEPENDENT (LOCKED):
        self-improvement run => HARD-FAIL; product run => VERIFIED_WITH_GAPS + loud gap note, continue.
        Can only downgrade a pass, never upgrade a fail. Best-effort: any error leaves the
        deterministic status untouched."""
        try:
            git_info = self._gitDiffFacts(self._work_dir or exec_cwd)
            has_code_change = bool(git_info) and git_info.get("files_changed", 0) > 0
            tree_shared = self._remediationTreeShared(exec_cwd)
            if not independent_verifier.shouldRunIndependentVerify(
                    enabled=config.INDEPENDENT_VERIFY_ENABLED,
                    has_code_change=has_code_change, tree_shared=tree_shared):
                return vresult, True
            goal = state.meta.get("goal_elaborated") or state.meta.get("goal_raw", "")
            criteria = f"{subtask.get('title', '')}\n{subtask.get('description', '')}"
            parse = independent_verifier.runIndependentVerification(
                self._run_claude, goal=goal, acceptance_criteria=criteria,
                diff_summary=git_info.get("diff_text", ""), work_dir=exec_cwd,
                task_state=state, subtask=subtask,
                cancel_check=lambda: self._deadlinePassed(state))
            verdict = independent_verifier.verdictFromEnvelope(parse.envelope)
            indep_checks = list((parse.envelope.test_results if parse.envelope else []) or [])
            criteria_reported = len(parse.envelope.acceptance_criteria_status) if parse.envelope else 0
            det_check = {"command": vresult.get("cmd"), "exit_code": vresult.get("returncode")}
            receipt = evidence_receipt.buildReceipt(
                goal=goal, git_info=git_info, det_check=det_check, indep_checks=indep_checks,
                criteria_reported=criteria_reported,
                assessments={"criteria": (parse.envelope.acceptance_criteria_status
                                          if parse.envelope else []),
                             "verifier_summary": summarizeEnvelope(parse.envelope),
                             "verdict_passed": verdict.passed,
                             "inconclusive": verdict.inconclusive})
            headline = receipt["headline"]
            if config.EVIDENCE_RECEIPT_ENABLED:
                self._persistReceipt(state, sid, receipt)
            if headline == evidence_receipt.NOT_VERIFIED:
                gap = (f"Evidence Receipt NOT_VERIFIED (unmet={verdict.unmet} "
                       f"failed_cmds={verdict.failed_commands} inconclusive={verdict.inconclusive})")
                vresult = dict(vresult)
                vresult["evidence_headline"] = headline
                # LOCKED MODE-DEPENDENT switch:
                if state.meta.get("is_self_referential"):
                    vresult.update({"passed": False, "returncode": 1, "stderr": gap})
                    with self._state_lock:
                        state.addNotification("evidence_hard_fail", f"{sid}: {gap}")
                    LOG.warning("%s: evidence receipt NOT_VERIFIED -> HARD-FAIL (self-improvement run)", sid)
                    return vresult, False
                vresult["evidence_headline"] = evidence_receipt.VERIFIED_WITH_GAPS
                vresult["evidence_gap"] = gap
                with self._state_lock:
                    state.addNotification("evidence_gap", f"{sid}: {gap} (run continues)")
                LOG.warning("%s: evidence receipt NOT_VERIFIED -> VERIFIED_WITH_GAPS (product run)", sid)
                return vresult, True
            vresult = dict(vresult)
            vresult["evidence_headline"] = headline
            return vresult, True
        except Exception as e:  # noqa: BLE001 -- receipt is best-effort; deterministic status stands
            LOG.warning("%s: evidence gate failed (deterministic pass kept): %s", sid, e)
            return vresult, True

    def _persistReceipt(self, state: TaskState, sid: str, receipt: dict) -> None:
        """Write the Evidence Receipt as a per-subtask Obsidian note (durable audit artifact)."""
        try:
            rel = f"{state.vaultTaskDir()}/subtasks/{sid}-receipt.md"
            body = "# Evidence Receipt " + sid + "\n\n```json\n" + json.dumps(receipt, indent=2) + "\n```\n"
            self.obs.writeNote(rel, body)
        except Exception:  # noqa: BLE001
            pass
```

- [ ] **Step 4: Wire the gate into `_runAttemptVerify`**

In `platform_core/orchestration/execute_mixin.py::_runAttemptVerify`, immediately AFTER the self-ref quality-gate block (after line 134, before `with self._state_lock: state.recordVerify`):

```python
        # Epic 2 (steal #3): execution-grounded downgrade. Runs ONLY when the deterministic gate
        # already passed; can never upgrade a fail. MODE-DEPENDENT NOT_VERIFIED handled inside.
        if passed and config.INDEPENDENT_VERIFY_ENABLED:
            vresult, passed = self._runEvidenceGate(state, subtask, result, exec_cwd, vresult, sid)
```

- [ ] **Step 5: Run new + regression tests**

Run: `python -m pytest tests/test_evidence_gate.py tests/test_verify_multi_requirement.py tests/test_verify_shell_safety.py -v`
Expected: PASS (evidence gate 2 passed; regression suites still green — proves the deterministic gate is unchanged)
Run: `python tools/dev.py check platform_core/orchestration/execute_mixin.py`
Expected: PASS (size: confirm `execute_mixin.py` stays ≤450 lines; if it crosses, extract `_gitDiffFacts`/`_runEvidenceGate`/`_persistReceipt` into `platform_core/orchestration/evidence_gate.py` and call them as thin delegates — see Modularity note below)

- [ ] **Step 6: Commit**

```bash
git add platform_core/orchestration/execute_mixin.py tests/test_evidence_gate.py
git commit -m "feat(epic2): mode-dependent Evidence Receipt downgrade in _runAttemptVerify (steal #3)"
```

> **Modularity note:** `execute_mixin.py` is 437 lines pre-patch. The three new methods (~70 lines) push it over 450. During Step 5, if `size_audit` flags `must_split`, move `_gitDiffFacts`, `_runEvidenceGate`, `_persistReceipt` bodies into a new `platform_core/orchestration/evidence_gate.py` module (free functions taking the orchestrator's `_run_claude`, `_state_lock`, `obs`, `_remediationTreeShared`, `_deadlinePassed`) and keep the three mixin methods as one-line delegates. Add the `@AI-MAP v1` header to the new module and re-run repo_map.

---

# PHASE C — Steal #2: dual-ledger planner + DAG + stall replan

## Task 12: `TaskState.dependentsOf` helper

**Files:**
- Modify: `state/task_schema.py` (after `nextActionable`, ~line 396)
- Test: `tests/test_dependents_of.py`

- [ ] **Step 1: Write the failing test**

```python
"""dependentsOf returns the subtasks that depend on a given id (for cascade reset)."""
import tempfile
from pathlib import Path
from unittest import mock

import config
from state.task import TaskState


def test_dependents_of():
    with mock.patch.object(config, "STATE_DIR", Path(tempfile.mkdtemp())):
        st = TaskState.create("g", 1.0)
        a = st.addSubtask("a", "da")               # st-001
        st.addSubtask("b", "db", depends_on=[a["subtask_id"]])  # st-002 depends on st-001
        st.addSubtask("c", "dc")                   # st-003 independent
        deps = st.dependentsOf(a["subtask_id"])
        assert [d["subtask_id"] for d in deps] == ["st-002"]
        assert st.dependentsOf("st-003") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dependents_of.py -v`
Expected: FAIL with `AttributeError: 'TaskState' object has no attribute 'dependentsOf'`

- [ ] **Step 3: Add the helper**

In `state/task_schema.py`, after `nextActionable` (before the final return of the class):

```python
    def dependentsOf(self, subtask_id: str) -> list[dict[str, Any]]:
        """Subtasks whose depends_on includes ``subtask_id`` (used by the dual-ledger cascade reset
        when a stall replan removes/replaces a subtask)."""
        return [s for s in self.subtasks if subtask_id in (s.get("depends_on") or [])]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dependents_of.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add state/task_schema.py tests/test_dependents_of.py
git commit -m "feat(epic2): add TaskState.dependentsOf for cascade reset (steal #2)"
```

---

## Task 13: `platform_core/orchestration/task_ledger.py` — dataclass + prompts + (de)serialize

**Files:**
- Create: `platform_core/orchestration/task_ledger.py`
- Test: `tests/test_task_ledger.py`

- [ ] **Step 1: Write the failing test**

```python
"""TaskLedger round-trips through state.meta and carries the autogen-derived prompt constants."""
import tempfile
from pathlib import Path
from unittest import mock

import config
from platform_core.orchestration import task_ledger as tl
from state.task import TaskState


def test_ledger_roundtrip_through_meta():
    with mock.patch.object(config, "STATE_DIR", Path(tempfile.mkdtemp())):
        st = TaskState.create("g", 1.0)
        led = tl.TaskLedger(given_facts=["gf"], lookup_facts=["lf"], derive_facts=["df"],
                            guess_facts=["gg"], plan=["step 1", "step 2"], revision=0)
        tl.saveToState(st, led)
        loaded = tl.loadFromState(st)
        assert loaded.plan == ["step 1", "step 2"]
        assert loaded.given_facts == ["gf"]
        assert loaded.revision == 0


def test_load_absent_returns_none():
    with mock.patch.object(config, "STATE_DIR", Path(tempfile.mkdtemp())):
        st = TaskState.create("g", 1.0)
        assert tl.loadFromState(st) is None


def test_prompt_constants_present():
    assert "facts" in tl.TASK_LEDGER_FACTS_PROMPT.lower()
    assert "plan" in tl.TASK_LEDGER_PLAN_PROMPT.lower()
    assert tl.PROGRESS_LEDGER_PROMPT and tl.FACTS_UPDATE_PROMPT and tl.PLAN_UPDATE_PROMPT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_task_ledger.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'platform_core.orchestration.task_ledger'`

- [ ] **Step 3: Create the module**

```python
"""TaskLedger -- the stable outer plan (facts + bullet plan) for the dual-ledger planner.

Mirrors autogen Magentic-One's task-ledger prompts (MIT): facts FIRST, plan SECOND -- each a bounded
question a 7B can answer. Persisted to state.meta["task_ledger"] so a resilience restart and the
root-cause replan path can read it.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  TaskLedger  -- facts buckets + bullet plan + revision
  saveToState(state, ledger)  -- persist ledger to state.meta
  loadFromState(state)  -- read ledger from state.meta (None if absent)
DEPENDS-ON: (stdlib only)
SIDE-EFFECTS: writes state.meta["task_ledger"]
RUN/TEST: python -m pytest tests/test_task_ledger.py
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

# --- autogen Magentic-One derived prompts (one bounded question per call) ---
TASK_LEDGER_FACTS_PROMPT: str = (
    "Below is a software goal. Build a sheet of the FACTS, in four buckets, as JSON ONLY: "
    '{"given_facts": [...], "lookup_facts": [...], "derive_facts": [...], "guess_facts": [...]}. '
    "given_facts: facts stated verbatim in the goal. lookup_facts: facts to look up (say where). "
    "derive_facts: facts to compute/deduce. guess_facts: educated guesses. Keep each list short."
)
TASK_LEDGER_PLAN_PROMPT: str = (
    "Given the goal and the fact sheet, write a short bullet PLAN as JSON ONLY: "
    '{"plan": ["step ...", "step ..."]}. Each bullet is ONE concrete deliverable/step in order. '
    "Prefix a bullet with '[independent]' ONLY when it does NOT depend on the immediately prior step."
)
FACTS_UPDATE_PROMPT: str = (
    "The plan stalled. First explain the ROOT CAUSE in one sentence, then REWRITE the fact sheet as "
    'JSON ONLY with the same four buckets: '
    '{"root_cause": "...", "given_facts": [...], "lookup_facts": [...], '
    '"derive_facts": [...], "guess_facts": [...]}.'
)
PLAN_UPDATE_PROMPT: str = (
    "Given the rewritten facts, write the NEW bullet plan for the REMAINING work as JSON ONLY: "
    '{"plan": ["step ..."]}. Do not repeat already-completed steps.'
)
PROGRESS_LEDGER_PROMPT: str = (
    "Assess progress on the goal. Respond JSON ONLY with EXACTLY these keys, each an object "
    '{"reason": str, "answer": ...}: '
    '{"is_request_satisfied": {"reason": "...", "answer": false}, '
    '"is_in_loop": {"reason": "...", "answer": false}, '
    '"is_progress_being_made": {"reason": "...", "answer": true}, '
    '"instruction": {"reason": "...", "answer": "<next hint>"}}.'
)


@dataclass
class TaskLedger:
    given_facts: list = field(default_factory=list)
    lookup_facts: list = field(default_factory=list)
    derive_facts: list = field(default_factory=list)
    guess_facts: list = field(default_factory=list)
    plan: list = field(default_factory=list)
    revision: int = 0


def saveToState(state, ledger: TaskLedger) -> None:
    state.meta["task_ledger"] = asdict(ledger)
    state.save()


def loadFromState(state) -> Optional[TaskLedger]:
    raw = state.meta.get("task_ledger")
    if not isinstance(raw, dict):
        return None
    return TaskLedger(
        given_facts=list(raw.get("given_facts") or []),
        lookup_facts=list(raw.get("lookup_facts") or []),
        derive_facts=list(raw.get("derive_facts") or []),
        guess_facts=list(raw.get("guess_facts") or []),
        plan=list(raw.get("plan") or []),
        revision=int(raw.get("revision") or 0),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_task_ledger.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/task_ledger.py tests/test_task_ledger.py
git commit -m "feat(epic2): add TaskLedger + autogen-derived prompts (steal #2)"
```

---

## Task 14: `platform_core/orchestration/plan_shape_check.py`

**Files:**
- Create: `platform_core/orchestration/plan_shape_check.py`
- Test: `tests/test_plan_shape_check.py`

- [ ] **Step 1: Write the failing test**

```python
"""checkPlanShape deterministically rejects degenerate plans (bernstein vertical-slice)."""
from platform_core.orchestration import plan_shape_check as psc


def _sub(sid, deps=None, verify=None):
    return {"subtask_id": sid, "title": sid, "depends_on": deps or [], "verify": verify}


def test_clean_plan_passes():
    subs = [_sub("st-001", verify={"cmd": "python a.py"}),
            _sub("st-002", deps=["st-001"], verify={"cmd": "python b.py"})]
    assert psc.checkPlanShape(subs, multi_deliverable=True) == []


def test_zero_subtasks_flagged():
    assert any("0 subtasks" in v or "no subtasks" in v.lower() for v in psc.checkPlanShape([]))


def test_over_cap_flagged():
    subs = [_sub(f"st-{i:03d}", verify={"cmd": "x"}) for i in range(1, 20)]
    assert any("MAX_SUBTASKS" in v or "too many" in v.lower() for v in psc.checkPlanShape(subs))


def test_dangling_dep_flagged():
    subs = [_sub("st-001", deps=["st-999"], verify={"cmd": "x"})]
    assert any("st-999" in v for v in psc.checkPlanShape(subs))


def test_cycle_flagged():
    subs = [_sub("st-001", deps=["st-002"], verify={"cmd": "x"}),
            _sub("st-002", deps=["st-001"], verify={"cmd": "x"})]
    assert any("cycle" in v.lower() for v in psc.checkPlanShape(subs))


def test_empty_verify_on_multi_deliverable_flagged():
    subs = [_sub("st-001", verify={"cmd": "python a.py"}),
            _sub("st-002", verify=None)]
    assert any("verify" in v.lower() for v in psc.checkPlanShape(subs, multi_deliverable=True))


def test_violation_report_is_string():
    rep = psc.shapeViolationReport(["a", "b"])
    assert "a" in rep and "b" in rep
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_plan_shape_check.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create the module**

```python
"""Deterministic plan shape-check (bernstein vertical-slice's _run_shape_check_with_retry idea).

Rejects degenerate plans WITHOUT trusting the 7B more: 0 subtasks, over the MAX_SUBTASKS cap, a
depends_on cycle, a dangling dep id, or an empty verify on a multi-deliverable goal. The caller
re-prompts the brain ONCE with shapeViolationReport, then accepts whatever returns (no infinite loop).

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  checkPlanShape(subtasks, *, max_subtasks, multi_deliverable)  -- list of violation strings ([] = clean)
  shapeViolationReport(violations)  -- structured re-prompt text
DEPENDS-ON: config
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/test_plan_shape_check.py
"""
from __future__ import annotations

from typing import Optional

import config


def _hasCycle(ids: set, edges: dict) -> bool:
    """DFS cycle detection over depends_on edges (only ids present in the plan are followed)."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {i: WHITE for i in ids}

    def visit(node: str) -> bool:
        color[node] = GRAY
        for dep in edges.get(node, []):
            if dep not in color:
                continue
            if color[dep] == GRAY:
                return True
            if color[dep] == WHITE and visit(dep):
                return True
        color[node] = BLACK
        return False

    return any(color[i] == WHITE and visit(i) for i in ids)


def checkPlanShape(subtasks: list, *, max_subtasks: Optional[int] = None,
                   multi_deliverable: bool = True) -> list:
    """Return a list of human-readable violations ([] => the plan is acceptable)."""
    cap = max_subtasks if max_subtasks is not None else config.MAX_SUBTASKS
    subs = [s for s in (subtasks or []) if isinstance(s, dict)]
    violations: list[str] = []
    if not subs:
        violations.append("plan has 0 subtasks (need at least one deliverable)")
        return violations
    if len(subs) > cap:
        violations.append(f"too many subtasks ({len(subs)} > MAX_SUBTASKS={cap})")
    ids = {s.get("subtask_id") for s in subs if s.get("subtask_id")}
    edges = {s.get("subtask_id"): list(s.get("depends_on") or []) for s in subs}
    for sid, deps in edges.items():
        for d in deps:
            if d not in ids:
                violations.append(f"{sid} depends on a dangling/unknown id '{d}'")
    if _hasCycle(ids, edges):
        violations.append("plan has a depends_on cycle")
    if multi_deliverable and len(subs) > 1:
        for s in subs:
            if not (s.get("verify") or {}).get("cmd"):
                violations.append(f"{s.get('subtask_id')} has an empty verify on a multi-deliverable goal")
    return violations


def shapeViolationReport(violations: list) -> str:
    """Build the single corrective re-prompt handed back to the brain."""
    bullets = "\n".join(f"- {v}" for v in violations)
    return ("Your plan has these shape violations. Return a CORRECTED plan (same JSON schema) that "
            "fixes ALL of them:\n" + bullets)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_plan_shape_check.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/plan_shape_check.py tests/test_plan_shape_check.py
git commit -m "feat(epic2): add deterministic plan_shape_check (steal #2, bernstein)"
```

---

## Task 15: `dual_ledger_planner.authorTaskLedger`

**Files:**
- Create: `platform_core/orchestration/dual_ledger_planner.py`
- Test: `tests/test_dual_ledger_planner.py`

- [ ] **Step 1: Write the failing test (mocked chat callable)**

```python
"""Dual-ledger planner free functions, all driven by a mocked ollama_chat callable."""
from platform_core.orchestration import dual_ledger_planner as dlp


class _Chat:
    def __init__(self, replies):
        self.replies = list(replies)

    def __call__(self, system, user, *, want_json=False):
        return {"message": {"content": self.replies.pop(0)}}


def test_author_task_ledger_two_calls():
    chat = _Chat([
        '{"given_facts": ["g"], "lookup_facts": [], "derive_facts": [], "guess_facts": []}',
        '{"plan": ["step one", "[independent] step two"]}',
    ])
    led = dlp.authorTaskLedger(chat, "build X", "arch doc")
    assert led is not None
    assert led.given_facts == ["g"]
    assert led.plan == ["step one", "[independent] step two"]


def test_author_task_ledger_none_on_bad_json():
    chat = _Chat(["not json", "not json", "not json", "not json", "not json", "not json"])
    assert dlp.authorTaskLedger(chat, "build X", "arch") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dual_ledger_planner.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create the module with `authorTaskLedger`**

```python
"""Dual-ledger planner free functions (autogen Magentic-One + metagpt DAG, MIT).

Replaces the one-shot 7B planner with many small, schema-bounded calls: a Task Ledger (facts then
plan), a deterministic DAG derivation with real depends_on, a tiny per-step Progress Ledger, a stall
counter, and a root-cause facts+plan rewrite. Every brain call routes through brain_json.chatJsonValidated
so a bad shape gets exact-field-error retries instead of collapsing to a fallback.

Free functions take an ``ollama_chat`` callable (mirroring subtask.py's split-out helpers) so they
are unit-testable without an Orchestrator instance.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  authorTaskLedger(ollama_chat, goal, architect_doc)  -- facts call then plan call -> TaskLedger|None
  deriveSubtaskDag(ledger, goal)  -- plan bullets -> subtask dicts with index-based depends_on
  materializeDag(state, subs)  -- create real subtasks, resolving index deps to st-ids
  progressLedgerStep(ollama_chat, goal, recent)  -- the 4-key progress ledger dict|None
  updateStallCount(progress, current)  -- pure stall-counter update
  rootCauseReplan(ollama_chat, goal, ledger, failure_summary)  -- facts+plan rewrite -> TaskLedger|None
DEPENDS-ON: config, platform_core.orchestration.brain_json, platform_core.orchestration.task_ledger
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/test_dual_ledger_planner.py
"""
from __future__ import annotations

from typing import Callable, Optional

import config
from platform_core.orchestration.brain_json import chatJsonValidated
from platform_core.orchestration import task_ledger as tl

_INDEP = "[independent]"


def authorTaskLedger(ollama_chat: Callable, goal: str, architect_doc: str) -> "Optional[tl.TaskLedger]":
    """Two bounded calls (facts, then plan), each validated. None if either call never validates."""
    facts_user = f"GOAL:\n{goal}\n\nARCHITECTURE:\n{(architect_doc or '')[:2000]}"
    facts = chatJsonValidated(
        ollama_chat, tl.TASK_LEDGER_FACTS_PROMPT, facts_user,
        required_keys=["given_facts", "lookup_facts", "derive_facts", "guess_facts"],
        validators={k: lambda v: isinstance(v, list)
                    for k in ("given_facts", "lookup_facts", "derive_facts", "guess_facts")})
    if facts is None:
        return None
    plan_user = f"GOAL:\n{goal}\n\nFACTS:\n{facts}"
    plan = chatJsonValidated(
        ollama_chat, tl.TASK_LEDGER_PLAN_PROMPT, plan_user,
        required_keys=["plan"],
        validators={"plan": lambda v: isinstance(v, list) and len(v) >= 1})
    if plan is None:
        return None
    return tl.TaskLedger(
        given_facts=list(facts.get("given_facts") or []),
        lookup_facts=list(facts.get("lookup_facts") or []),
        derive_facts=list(facts.get("derive_facts") or []),
        guess_facts=list(facts.get("guess_facts") or []),
        plan=[str(b) for b in plan.get("plan") or []],
        revision=0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dual_ledger_planner.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/dual_ledger_planner.py tests/test_dual_ledger_planner.py
git commit -m "feat(epic2): add dual_ledger_planner.authorTaskLedger (steal #2)"
```

---

## Task 16: `deriveSubtaskDag` + `materializeDag`

**Files:**
- Modify: `platform_core/orchestration/dual_ledger_planner.py`
- Test: `tests/test_dual_ledger_planner.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/test_dual_ledger_planner.py`:

```python
import tempfile
from pathlib import Path
from unittest import mock

import config
from platform_core.orchestration import task_ledger as tl
from state.task import TaskState


def test_derive_dag_sequential_and_independent():
    led = tl.TaskLedger(plan=["build module", "[independent] write docs", "wire it up"])
    subs = dlp.deriveSubtaskDag(led, "goal")
    assert len(subs) == 3
    assert subs[0]["depends_on"] == []            # first bullet, no dep
    assert subs[1]["depends_on"] == []            # [independent] breaks the chain
    assert subs[2]["depends_on"] == [1]           # sequential: depends on the prior index
    assert subs[1]["title"] == "write docs"       # marker stripped


def test_materialize_resolves_index_deps_to_ids():
    with mock.patch.object(config, "STATE_DIR", Path(tempfile.mkdtemp())):
        st = TaskState.create("g", 1.0)
        led = tl.TaskLedger(plan=["a", "b"])  # b depends on a (index 0)
        subs = dlp.deriveSubtaskDag(led, "g")
        created = dlp.materializeDag(st, subs)
        assert created[1]["depends_on"] == [created[0]["subtask_id"]]
        assert st.getSubtask(created[1]["subtask_id"])["depends_on"] == [created[0]["subtask_id"]]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dual_ledger_planner.py -k dag -v`
Expected: FAIL with `AttributeError: ... has no attribute 'deriveSubtaskDag'`

- [ ] **Step 3: Add the two functions**

In `platform_core/orchestration/dual_ledger_planner.py`:

```python
def deriveSubtaskDag(ledger: "tl.TaskLedger", goal: str) -> list:
    """Turn the bullet plan into subtask dicts with INDEX-based depends_on (metagpt dependent_task_ids
    mapped onto positions). Sequential bullets depend on the prior index; an '[independent]' prefix
    breaks the chain. Index deps are resolved to real st-ids by materializeDag."""
    subs: list[dict] = []
    for i, bullet in enumerate(ledger.plan or []):
        text = str(bullet).strip()
        independent = text.lower().startswith(_INDEP)
        if independent:
            text = text[len(_INDEP):].strip()
        deps = [] if (independent or i == 0) else [i - 1]
        subs.append({
            "title": text[:80] or f"step {i + 1}",
            "description": text,
            "layer": 3,
            "effort_level": "high",
            "verify": None,
            "depends_on": deps,   # INDEX form; materializeDag rewrites to st-ids
        })
    return subs


def materializeDag(state, subs: list) -> list:
    """Create the subtasks in order via state.addSubtask, resolving each index dep to the real st-id
    of the already-created earlier subtask. Returns the created subtask dicts."""
    created: list[dict] = []
    for s in subs:
        dep_ids = [created[idx]["subtask_id"] for idx in (s.get("depends_on") or [])
                   if isinstance(idx, int) and 0 <= idx < len(created)]
        st = state.addSubtask(s.get("title", "step"), s.get("description", ""),
                              layer=s.get("layer", 3), depends_on=dep_ids, verify=s.get("verify"))
        created.append(st)
    return created
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dual_ledger_planner.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/dual_ledger_planner.py tests/test_dual_ledger_planner.py
git commit -m "feat(epic2): add deriveSubtaskDag + materializeDag with real depends_on (steal #2)"
```

---

## Task 17: `progressLedgerStep` + `updateStallCount`

**Files:**
- Modify: `platform_core/orchestration/dual_ledger_planner.py`
- Test: `tests/test_dual_ledger_planner.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/test_dual_ledger_planner.py`:

```python
def test_progress_ledger_step_validates_four_keys():
    chat = _Chat(['{"is_request_satisfied": {"reason": "no", "answer": false}, '
                  '"is_in_loop": {"reason": "no", "answer": false}, '
                  '"is_progress_being_made": {"reason": "yes", "answer": true}, '
                  '"instruction": {"reason": "next", "answer": "do step 2"}}'])
    out = dlp.progressLedgerStep(chat, "goal", "recent output")
    assert out["instruction"]["answer"] == "do step 2"


def test_update_stall_count_increments_on_loop():
    prog = {"is_in_loop": {"answer": True}, "is_progress_being_made": {"answer": True}}
    assert dlp.updateStallCount(prog, 0) == 1


def test_update_stall_count_increments_on_no_progress():
    prog = {"is_in_loop": {"answer": False}, "is_progress_being_made": {"answer": False}}
    assert dlp.updateStallCount(prog, 1) == 2


def test_update_stall_count_decrements_on_progress_floor_zero():
    prog = {"is_in_loop": {"answer": False}, "is_progress_being_made": {"answer": True}}
    assert dlp.updateStallCount(prog, 0) == 0   # never below zero
    assert dlp.updateStallCount(prog, 2) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dual_ledger_planner.py -k "progress or stall" -v`
Expected: FAIL with `AttributeError: ... has no attribute 'progressLedgerStep'`

- [ ] **Step 3: Add the functions**

In `platform_core/orchestration/dual_ledger_planner.py`:

```python
def progressLedgerStep(ollama_chat: Callable, goal: str, recent: str) -> Optional[dict]:
    """One tiny per-step Progress Ledger call (autogen ORCHESTRATOR_PROGRESS_LEDGER_PROMPT, minus
    next_speaker -- 9to5 is a star topology). Returns the validated 4-key dict, or None."""
    user = f"GOAL:\n{goal}\n\nMOST RECENT OUTCOME:\n{(recent or '')[:2000]}"
    _obj = lambda v: isinstance(v, dict) and "answer" in v
    return chatJsonValidated(
        ollama_chat, tl.PROGRESS_LEDGER_PROMPT, user,
        required_keys=["is_request_satisfied", "is_in_loop",
                       "is_progress_being_made", "instruction"],
        validators={"is_request_satisfied": _obj, "is_in_loop": _obj,
                    "is_progress_being_made": _obj, "instruction": _obj})


def updateStallCount(progress: dict, current: int) -> int:
    """autogen n_stalls: +1 when in a loop OR no progress; -1 (floored at 0) when progressing."""
    in_loop = bool(((progress or {}).get("is_in_loop") or {}).get("answer"))
    progressing = bool(((progress or {}).get("is_progress_being_made") or {}).get("answer"))
    if in_loop or not progressing:
        return current + 1
    return max(0, current - 1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dual_ledger_planner.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/dual_ledger_planner.py tests/test_dual_ledger_planner.py
git commit -m "feat(epic2): add progressLedgerStep + updateStallCount (steal #2)"
```

---

## Task 18: `rootCauseReplan`

**Files:**
- Modify: `platform_core/orchestration/dual_ledger_planner.py`
- Test: `tests/test_dual_ledger_planner.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/test_dual_ledger_planner.py`:

```python
def test_root_cause_replan_bumps_revision_and_rewrites():
    led = tl.TaskLedger(given_facts=["old"], plan=["old step"], revision=1)
    chat = _Chat([
        '{"root_cause": "wrong assumption", "given_facts": ["new"], "lookup_facts": [], '
        '"derive_facts": [], "guess_facts": []}',
        '{"plan": ["new step a", "new step b"]}',
    ])
    new_led = dlp.rootCauseReplan(chat, "goal", led, "subtask failed twice")
    assert new_led is not None
    assert new_led.revision == 2            # bumped
    assert new_led.given_facts == ["new"]
    assert new_led.plan == ["new step a", "new step b"]


def test_root_cause_replan_none_on_bad_json_keeps_caller_fallback():
    led = tl.TaskLedger(plan=["x"], revision=0)
    chat = _Chat(["junk"] * 6)
    assert dlp.rootCauseReplan(chat, "goal", led, "fail") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dual_ledger_planner.py -k root_cause -v`
Expected: FAIL with `AttributeError: ... has no attribute 'rootCauseReplan'`

- [ ] **Step 3: Add `rootCauseReplan`**

In `platform_core/orchestration/dual_ledger_planner.py`:

```python
def rootCauseReplan(ollama_chat: Callable, goal: str, ledger: "tl.TaskLedger",
                    failure_summary: str) -> "Optional[tl.TaskLedger]":
    """autogen TASK_LEDGER_FACTS_UPDATE then ..._PLAN_UPDATE: explain the root cause, rewrite facts,
    then re-plan the remaining tail. Bumps revision. None (caller keeps greedy replan) on bad JSON."""
    facts_user = (f"GOAL:\n{goal}\n\nPRIOR FACTS:\n{ledger.given_facts + ledger.derive_facts}\n\n"
                  f"WHAT STALLED:\n{(failure_summary or '')[:1500]}")
    facts = chatJsonValidated(
        ollama_chat, tl.FACTS_UPDATE_PROMPT, facts_user,
        required_keys=["root_cause", "given_facts", "lookup_facts", "derive_facts", "guess_facts"],
        validators={k: lambda v: isinstance(v, list)
                    for k in ("given_facts", "lookup_facts", "derive_facts", "guess_facts")})
    if facts is None:
        return None
    plan_user = f"GOAL:\n{goal}\n\nREWRITTEN FACTS:\n{facts}\n\nROOT CAUSE:\n{facts.get('root_cause')}"
    plan = chatJsonValidated(
        ollama_chat, tl.PLAN_UPDATE_PROMPT, plan_user,
        required_keys=["plan"],
        validators={"plan": lambda v: isinstance(v, list) and len(v) >= 1})
    if plan is None:
        return None
    return tl.TaskLedger(
        given_facts=list(facts.get("given_facts") or []),
        lookup_facts=list(facts.get("lookup_facts") or []),
        derive_facts=list(facts.get("derive_facts") or []),
        guess_facts=list(facts.get("guess_facts") or []),
        plan=[str(b) for b in plan.get("plan") or []],
        revision=ledger.revision + 1)
```

- [ ] **Step 4: Run test + size check**

Run: `python -m pytest tests/test_dual_ledger_planner.py -v`
Expected: PASS (9 passed)
Run: `python tools/dev.py check platform_core/orchestration/dual_ledger_planner.py`
Expected: PASS (confirm ≤450 lines; ~200 actual)

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/dual_ledger_planner.py tests/test_dual_ledger_planner.py
git commit -m "feat(epic2): add rootCauseReplan facts+plan rewrite (steal #2)"
```

---

## Task 19: `run_loop_mixin._cascadeResetDependents` + stall replan branch

**Files:**
- Modify: `platform_core/orchestration/run_loop_mixin.py` (new `_cascadeResetDependents` + `_stallReplan`)
- Test: `tests/test_cascade_reset.py`

- [ ] **Step 1: Write the failing test**

```python
"""Cascade reset removes only PENDING dependents of a replaced/removed subtask (freeze done prefix)."""
import tempfile
from pathlib import Path
from unittest import mock

import config
from orchestrator import Orchestrator
from state.task import TaskState


def _setup():
    d = Path(tempfile.mkdtemp())
    p = mock.patch.object(config, "STATE_DIR", d)
    p.start()
    st = TaskState.create("g", 1.0)
    a = st.addSubtask("a", "da")                              # st-001
    b = st.addSubtask("b", "db", depends_on=[a["subtask_id"]])  # st-002 pending dependent
    c = st.addSubtask("c", "dc", depends_on=[b["subtask_id"]])  # st-003 transitive dependent
    orch = Orchestrator()
    orch.obs = mock.Mock()
    return orch, st, p


def test_cascade_resets_pending_dependents_transitively():
    orch, st, p = _setup()
    try:
        orch._cascadeResetDependents(st, ["st-001"])
        assert st.getSubtask("st-002")["status"] == "removed"
        assert st.getSubtask("st-003")["status"] == "removed"
    finally:
        p.stop()


def test_cascade_freezes_done_dependents():
    orch, st, p = _setup()
    try:
        st.updateSubtask("st-002", status="done")   # executed prefix -> frozen
        orch._cascadeResetDependents(st, ["st-001"])
        assert st.getSubtask("st-002")["status"] == "done"     # not reset
        assert st.getSubtask("st-003")["status"] == "removed"  # still-pending dependent reset
    finally:
        p.stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cascade_reset.py -v`
Expected: FAIL with `AttributeError: 'Orchestrator' object has no attribute '_cascadeResetDependents'`

- [ ] **Step 3: Add the helpers**

In `platform_core/orchestration/run_loop_mixin.py`, add to `OrchestratorRunLoopMixin` (after `_applyReplan`):

```python
    def _cascadeResetDependents(self, state: TaskState, removed_ids: list) -> None:
        """Remove only the still-PENDING dependents (transitively) of removed/replaced subtasks, so a
        root-cause replan invalidates downstream work that built on now-stale assumptions while the
        executed prefix (done/failed) is frozen (metagpt reset_task; cf. nextActionable FX-21)."""
        queue = list(removed_ids or [])
        seen: set = set(queue)
        while queue:
            rid = queue.pop()
            for dep in state.dependentsOf(rid):
                if dep["status"] != "pending":
                    continue
                state.updateSubtask(dep["subtask_id"], status="removed")
                state.addNotification("cascade_reset", f"{dep['subtask_id']} (depended on {rid})")
                if dep["subtask_id"] not in seen:
                    seen.add(dep["subtask_id"])
                    queue.append(dep["subtask_id"])

    def _stallReplan(self, state: TaskState, architect_doc: str, failure_summary: str) -> bool:
        """Stall-driven root-cause replan: rewrite facts+plan, freeze the executed prefix, remove the
        pending tail + cascade-reset its dependents, then re-derive the remaining DAG. Gated by
        DUAL_LEDGER_PLANNER_ENABLED. Returns True when a rewrite was applied."""
        from platform_core.orchestration import dual_ledger_planner as dlp
        from platform_core.orchestration import task_ledger as tl
        ledger = tl.loadFromState(state)
        if ledger is None:
            return False
        goal = state.meta.get("goal_elaborated") or state.meta.get("goal_raw", "")
        new_ledger = dlp.rootCauseReplan(self._ollamaChat, goal, ledger, failure_summary)
        if new_ledger is None:
            return False
        with self._state_lock:
            pending = [s["subtask_id"] for s in state.subtasks if s["status"] == "pending"]
            for pid in pending:
                state.updateSubtask(pid, status="removed")
            self._cascadeResetDependents(state, pending)
            subs = dlp.deriveSubtaskDag(new_ledger, goal)
            dlp.materializeDag(state, subs)
            tl.saveToState(state, new_ledger)
            state.meta["stall_count"] = 0
            state.save()
            state.addNotification("root_cause_replan",
                                  f"revision {new_ledger.revision}: {failure_summary[:160]}")
        LOG.info("root-cause replan applied (revision %d)", new_ledger.revision)
        return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cascade_reset.py -v`
Expected: PASS (2 passed)
Run: `python tools/dev.py check platform_core/orchestration/run_loop_mixin.py`
Expected: PASS (confirm ≤450 lines; if it crosses, extract `_stallReplan` + `_cascadeResetDependents` into `platform_core/orchestration/dual_ledger_replan.py` free functions and delegate)

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/run_loop_mixin.py tests/test_cascade_reset.py
git commit -m "feat(epic2): add cascade reset + stall-driven root-cause replan (steal #2)"
```

---

## Task 20: Wire `authorSubtaskPlan` + `critiqueSubtaskPlan` to the dual-ledger path

**Files:**
- Modify: `platform_core/orchestration/plan_mixin.py` (`authorSubtaskPlan` 113-176, `critiqueSubtaskPlan` 178-211)
- Test: `tests/test_dual_ledger_wiring.py`

- [ ] **Step 1: Write the failing test**

```python
"""When DUAL_LEDGER_PLANNER_ENABLED, authorSubtaskPlan delegates to the dual-ledger planner and yields
real depends_on; when OFF, the legacy one-shot path is unchanged. critiqueSubtaskPlan applies the
deterministic shape-check with one corrective re-prompt."""
import tempfile
from pathlib import Path
from unittest import mock

import config
from orchestrator import Orchestrator
from platform_core.orchestration import dual_ledger_planner as dlp
from platform_core.orchestration import task_ledger as tl


def test_dual_ledger_on_produces_depends_on():
    with mock.patch.object(config, "STATE_DIR", Path(tempfile.mkdtemp())), \
         mock.patch.object(config, "DUAL_LEDGER_PLANNER_ENABLED", True):
        orch = Orchestrator()
        led = tl.TaskLedger(plan=["build module", "wire it up"])
        with mock.patch.object(dlp, "authorTaskLedger", return_value=led):
            subs = orch.authorSubtaskPlan("build X (1) a (2) b", "arch")
        # second bullet depends on the first (index form survives until materialize)
        assert len(subs) == 2 and subs[1]["depends_on"] == [0]


def test_dual_ledger_off_uses_legacy_path():
    with mock.patch.object(config, "STATE_DIR", Path(tempfile.mkdtemp())), \
         mock.patch.object(config, "DUAL_LEDGER_PLANNER_ENABLED", False):
        orch = Orchestrator()
        orch._ollamaChat = mock.Mock(return_value={"message": {"content":
            '{"subtasks": [{"title": "a", "description": "d", "verify": {"cmd": "python a.py", "expect": "exit_zero"}}]}'}})
        subs = orch.authorSubtaskPlan("trivial goal", "arch")
        assert subs and subs[0]["title"] == "a"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dual_ledger_wiring.py -v`
Expected: FAIL on `test_dual_ledger_on_produces_depends_on` (legacy path ignores the flag)

- [ ] **Step 3: Add the delegate at the top of `authorSubtaskPlan`**

In `platform_core/orchestration/plan_mixin.py`, add imports after line 25 (`from platform_core.orchestration.subtask import ...`):

```python
from platform_core.orchestration import dual_ledger_planner as _dlp
from platform_core.orchestration import plan_shape_check as _shape
```

Then make `authorSubtaskPlan` delegate when the flag is on — insert at the very start of the method body (before the existing `system = (`):

```python
    def authorSubtaskPlan(self, goal_elaborated: str, architect_doc: str) -> list[dict]:
        # Epic 2 (steal #2): dual-ledger planner. Flag-gated; on failure it returns None and we fall
        # straight through to the legacy one-shot planner below (never worse than today).
        if config.DUAL_LEDGER_PLANNER_ENABLED:
            try:
                ledger = _dlp.authorTaskLedger(self._ollamaChat, goal_elaborated, architect_doc)
                if ledger is not None and ledger.plan:
                    subs = _dlp.deriveSubtaskDag(ledger, goal_elaborated)
                    if subs:
                        LOG.info("dual-ledger planner authored %d subtasks with depends_on", len(subs))
                        return subs
            except Exception as e:  # noqa: BLE001 -- dual-ledger never blocks; legacy path follows
                LOG.warning("dual-ledger planner failed (%s); using legacy planner", e)
        system = (
```

(The rest of the legacy method body is unchanged.)

> **Note on ids:** `deriveSubtaskDag` returns INDEX-form `depends_on`. The run-phase caller that
> persists the plan must use `materializeDag` (or `state.addSubtask` with resolved ids). Confirm the
> plan-persisting call site (`run_phase_mixin`) routes the dual-ledger subtasks through
> `_dlp.materializeDag(state, subs)` so index deps become real st-ids; the legacy `addSubtask` loop
> is unchanged for the off path. If the call site currently does a plain `addSubtask` loop, add a
> branch: `if config.DUAL_LEDGER_PLANNER_ENABLED and subs and isinstance(subs[0].get("depends_on"), list) and subs[0]["depends_on"] and isinstance(subs[0]["depends_on"][0], int): _dlp.materializeDag(state, subs)`.

- [ ] **Step 4: Add the shape-check to `critiqueSubtaskPlan`**

In `critiqueSubtaskPlan`, after the existing single-deliverable collapse block (after line 191) and before the `system = (` brain critique, insert:

```python
        # Epic 2 (steal #2): deterministic shape-check with ONE corrective re-prompt (bernstein).
        if config.DUAL_LEDGER_PLANNER_ENABLED:
            violations = _shape.checkPlanShape(
                subs, multi_deliverable=not self._singleDeliverable(goal_elaborated))
            if violations:
                LOG.info("plan shape-check found %d violation(s) -> 1 corrective re-prompt",
                         len(violations))
                report = _shape.shapeViolationReport(violations)
                resp = self._ollamaChat(
                    "You are a 9TO5 plan fixer. Return corrected JSON only, schema {\"subtasks\":[...]}.",
                    f"Goal:\n{goal_elaborated}\n\nPlan:\n{json.dumps({'subtasks': subs})}\n\n{report}",
                    want_json=True)
                fixed = _chatJson(resp)
                cand = fixed.get("subtasks") if isinstance(fixed, dict) else None
                if isinstance(cand, list) and cand and all(isinstance(x, dict) for x in cand):
                    subs = cand   # accept whatever returns -- no infinite loop
```

- [ ] **Step 5: Run new + regression tests**

Run: `python -m pytest tests/test_dual_ledger_wiring.py tests/test_plan_strengthen.py -v`
Expected: PASS (wiring 2 passed; `test_plan_strengthen.py` still green — legacy planner contract intact)

- [ ] **Step 6: Commit**

```bash
git add platform_core/orchestration/plan_mixin.py tests/test_dual_ledger_wiring.py
git commit -m "feat(epic2): delegate planner to dual-ledger + shape-check when enabled (steal #2)"
```

---

## Task 21: Stall counter in `_runSieAndReplan`

**Files:**
- Modify: `platform_core/orchestration/execute_mixin.py::_runSieAndReplan:303-337`
- Test: `tests/test_stall_replan_trigger.py`

- [ ] **Step 1: Write the failing test**

```python
"""A stalling progress-ledger sequence triggers EXACTLY one root-cause replan at STALL_THRESHOLD."""
import tempfile
from pathlib import Path
from unittest import mock

import config
from orchestrator import Orchestrator
from platform_core.orchestration import dual_ledger_planner as dlp
from state.task import TaskState


def test_stall_threshold_triggers_one_root_cause_replan():
    with mock.patch.object(config, "STATE_DIR", Path(tempfile.mkdtemp())), \
         mock.patch.object(config, "DUAL_LEDGER_PLANNER_ENABLED", True), \
         mock.patch.object(config, "STALL_THRESHOLD", 2):
        st = TaskState.create("g", 1.0)
        st.meta["goal_elaborated"] = "build (1) a (2) b"
        st.meta["stall_count"] = 0
        sub = st.addSubtask("a", "da")
        orch = Orchestrator()
        orch.obs = mock.Mock()
        stalling = {"is_in_loop": {"answer": True}, "is_progress_being_made": {"answer": False},
                    "is_request_satisfied": {"answer": False}, "instruction": {"answer": "retry"}}
        with mock.patch.object(dlp, "progressLedgerStep", return_value=stalling), \
             mock.patch.object(orch, "_stallReplan", return_value=True) as m_replan, \
             mock.patch.object(orch, "_singleDeliverable", return_value=False):
            # first stall: count 0 -> 1, no replan
            orch._runSieAndReplan(st, sub, {"prompt": "p"}, "out", True, "done", "arch",
                                  mock.Mock(), None, False)
            assert m_replan.call_count == 0
            # second stall: count 1 -> 2 == threshold -> exactly one replan, counter reset by _stallReplan
            orch._runSieAndReplan(st, sub, {"prompt": "p"}, "out", True, "done", "arch",
                                  mock.Mock(), None, False)
            assert m_replan.call_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_stall_replan_trigger.py -v`
Expected: FAIL (legacy `_runSieAndReplan` never calls `_stallReplan` / progress ledger)

- [ ] **Step 3: Add the stall branch in `_runSieAndReplan`**

In `platform_core/orchestration/execute_mixin.py::_runSieAndReplan`, replace the final replan block (lines 321-337, from `# Replan after a PASSED subtask ...` to the end) with:

```python
        # Epic 2 (steal #2): when the dual-ledger planner is on, drive replanning from the Progress
        # Ledger + stall counter (root-cause rewrite at STALL_THRESHOLD) instead of the greedy heuristic.
        if config.DUAL_LEDGER_PLANNER_ENABLED:
            self._progressLedgerReplan(state, subtask, combined, architect_doc, dashboard)
            return
        # Legacy path: replan after a PASSED subtask always; after a FAILED one ONLY on a self-ref run.
        self_ref = bool(state.meta.get("is_self_referential"))
        replan_ok = final == "done" or (self_ref and final == "failed")
        if replan_ok and not self._singleDeliverable(state.meta.get("goal_elaborated", "")):
            with self._state_lock:                       # snapshot for parallel-safety
                subs_snapshot = list(state.subtasks)
            decision = self._replan(state.meta["goal_elaborated"], subs_snapshot, subtask, combined,
                                    self_referential=bool(state.meta.get("is_self_referential")),
                                    remaining_hours=self._remainingHours(state))
            if decision.get("action") == "mutate" and (decision.get("add") or decision.get("remove")):
                dashboard.update(state, "replanning", f"replanning after {sid}")
                with self._state_lock:
                    self._applyReplan(state, decision)
                from notifications import run_arc as _arc
                self._arcBeat(state, _arc.beat_replan(f"after {sid}"))
                self._narrate(f"🔁 Replanning after {sid}. Scope was wider than expected.")
```

Then add the new helper method to `OrchestratorExecuteMixin` (after `_runSieAndReplan`):

```python
    def _progressLedgerReplan(self, state: TaskState, subtask: dict, combined: str,
                              architect_doc: str, dashboard: "DiscordDashboard") -> None:
        """Dual-ledger replan driver: one tiny Progress Ledger call updates the stall counter; at
        STALL_THRESHOLD fire exactly one root-cause facts+plan rewrite. Best-effort."""
        from platform_core.orchestration import dual_ledger_planner as dlp
        sid = subtask["subtask_id"]
        if self._singleDeliverable(state.meta.get("goal_elaborated", "")):
            return
        goal = state.meta.get("goal_elaborated") or state.meta.get("goal_raw", "")
        progress = dlp.progressLedgerStep(self._ollamaChat, goal, combined)
        if progress is None:
            return
        with self._state_lock:
            cur = int(state.meta.get("stall_count", 0))
            new_count = dlp.updateStallCount(progress, cur)
            state.meta["stall_count"] = new_count
            state.save()
        if new_count >= config.STALL_THRESHOLD:
            dashboard.update(state, "replanning", f"root-cause replan after {sid} (stall {new_count})")
            summary = f"stalled after {sid}: {((progress.get('instruction') or {}).get('answer'))}"
            self._stallReplan(state, architect_doc, summary)
```

- [ ] **Step 4: Run new + regression tests**

Run: `python -m pytest tests/test_stall_replan_trigger.py tests/test_apply_replan.py -v`
Expected: PASS (stall 1 passed; `test_apply_replan.py` still green — legacy greedy replan unchanged)
Run: `python tools/dev.py check platform_core/orchestration/execute_mixin.py`
Expected: PASS (re-check ≤450 lines; extract to `evidence_gate.py`/`dual_ledger_replan.py` delegates if `must_split`)

- [ ] **Step 5: Commit**

```bash
git add platform_core/orchestration/execute_mixin.py tests/test_stall_replan_trigger.py
git commit -m "feat(epic2): drive replan from Progress Ledger + stall counter when enabled (steal #2)"
```

---

## Task 22: Regenerate docs, full size audit, fast suite

**Files:**
- Modify: `AGENTS.md` (generated), any module headers flagged

- [ ] **Step 1: Regenerate the repo map**

Run: `python tools/repo_map.py`
Expected: `AGENTS.md` updated with the 7 new modules; no manual edits to generated rows.

- [ ] **Step 2: Size audit — zero `must_split`**

Run: `python tools/size_audit.py`
Expected: zero `must_split` violations. If `execute_mixin.py`, `run_loop_mixin.py`, or `plan_mixin.py` are flagged, perform the extraction noted in Tasks 11/19 (`evidence_gate.py` / `dual_ledger_replan.py` free-function modules with `@AI-MAP v1` headers + thin mixin delegates), then re-run `repo_map.py`.

- [ ] **Step 3: Full focused regression run**

Run: `python -m pytest tests/test_epic2_config.py tests/test_brain_io_repair.py tests/test_brain_json.py tests/test_completion_envelope.py tests/test_evidence_receipt.py tests/test_independent_verifier.py tests/test_executor_readonly.py tests/test_envelope_instruction_append.py tests/test_evidence_gate.py tests/test_dependents_of.py tests/test_task_ledger.py tests/test_plan_shape_check.py tests/test_dual_ledger_planner.py tests/test_cascade_reset.py tests/test_dual_ledger_wiring.py tests/test_stall_replan_trigger.py -v`
Expected: ALL PASS

- [ ] **Step 4: Regression guards + fast lane**

Run: `python -m pytest tests/test_verify_multi_requirement.py tests/test_verify_shell_safety.py tests/test_apply_replan.py tests/test_chatjson_salvage.py tests/test_adversary.py tests/test_adversary_teeth.py tests/test_adversary_verdict_failclosed.py tests/test_plan_strengthen.py -v`
Expected: ALL PASS (proves the deterministic gate, replan cap, and adversary contract are unchanged)
Run: `python tools/dev.py fast`
Expected: green

- [ ] **Step 5: Commit**

```bash
git add AGENTS.md
git commit -m "docs(epic2): regenerate repo map for trustworthy-loop modules"
```

---

## Self-Review

**1. Spec coverage** (every section of `2026-06-30-epic2-trustworthy-loop-design.md` mapped to a task):
- §3a Task Ledger dataclass + persist → Task 13. DAG with real `depends_on` → Tasks 16, 12 (`dependentsOf`). Plan shape-check + 1 re-prompt → Tasks 14, 20. Progress Ledger → Task 17. Stall counter → Task 17. Root-cause replan + freeze prefix + cascade reset → Tasks 18, 19, 21. ✓
- §3b CompletionEnvelope + instruction → Tasks 6, 10. Independent verifier (prompt/verdict/gating/spawn, read-only via `--disallowedTools`) → Tasks 8, 9. Evidence Receipt facts/assessments/headline → Task 7. Slots beside `verifier.py`, downgrades via `recordVerify`, MODE-DEPENDENT (LOCKED) → Task 11. ✓
- §3c `json_repair` rung → Task 2. `chatJsonValidated` + `_makeRetryPrompt` + `_validateShape` → Tasks 3-5. ✓
- §5 config knobs → Task 1; `requirements` → Task 2; `AGENTS.md` → Task 22. ✓
- §7 testing (pure units + mocked-brain integration + regression guards + gate sequence) → every task uses pytest; regression guards in Task 22 Step 4. ✓
- §8 sequencing #9→#3→#2 → Phases A/B/C in that order, each flag-gated. ✓
- LOCKED decision (MODE-DEPENDENT NOT_VERIFIED, one-line switch) → Task 11 Step 3 (`if state.meta.get("is_self_referential")`). ✓

**2. Placeholder scan:** No "TBD"/"handle edge cases"/"similar to". Every code step shows complete code. The one forward-reference (run-phase `materializeDag` call site) is called out explicitly with the exact branch to add in Task 20's note — not left vague. Fixed.

**3. Type consistency:**
- `chatJsonValidated(ollama_chat, system, user, *, required_keys, validators, max_retries)` — same signature in Task 5 (def), Tasks 15/17/18 (calls). ✓
- `EnvelopeParse(envelope, present, malformed, error)` — Task 6 def; Tasks 9, 11 construct/consume with the same fields. ✓
- `CompletionEnvelope` field names (`acceptance_criteria_status`, `test_results`, `files_changed`) consistent across Tasks 6, 7, 9, 11. ✓
- `Verdict(passed, unmet, failed_commands, inconclusive)` — Task 9 def; Task 11 reads `.unmet`, `.failed_commands`, `.inconclusive`, `.passed`. ✓
- `buildReceipt(goal, git_info, det_check, indep_checks, criteria_reported, assessments)` — Task 7 def + test; Task 11 call uses the same kwargs. ✓ `git_info` keys (`base_sha`, `head_sha`, `diff_text`, `files_changed`) match between `_gitDiffFacts` (Task 11) and `_computeFacts` (Task 7). ✓
- `deriveSubtaskDag` returns INDEX-form `depends_on`; `materializeDag` resolves to st-ids — consistent across Tasks 16, 19, 20. ✓
- `TaskLedger` fields identical in Tasks 13, 15, 18. `saveToState`/`loadFromState` names consistent in Tasks 13, 19. ✓
- `_stallReplan` / `_cascadeResetDependents` defined in Task 19, called in Tasks 19, 21. `progressLedgerStep`/`updateStallCount` defined Task 17, called Task 21. ✓

One inconsistency found and fixed inline: Task 11's `_runEvidenceGate` originally referenced a receipt persist before defining it — added the `_persistReceipt` method in the same task and gated it on `EVIDENCE_RECEIPT_ENABLED`. ✓

No gaps remain; ownership invariant (verifier-only-downgrade, never-upgrade, ControlBus untouched) is enforced structurally in Task 11 (gate runs only `if passed`, only sets `passed=False`).

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-30-epic2-trustworthy-loop.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
