# Phase 3 — Native Layer Architecture Sketch

**Status:** Design sketch (not yet built)
**Layer designation:** L2 — Native UI Automation (pywinauto / UIA)
**Builds on:** L3 Terminal (built, Phase 1) + L1 Browser CDP (built, Phase 2)

---

## Overview

Phase 3 adds a third "hands" modality: direct OS-level UI automation via the
Windows Accessibility API (UIA) and `pywinauto`. Where L3 drives the terminal and
L1 drives the browser, L2 drives **any native Windows application** (desktop GUI,
Electron shell, Office, IDE, etc.) that exposes the standard UIA tree.

The orchestrator brain (Ollama) authors a structured action spec under
`surface="native"` exactly as it does for `surface="browser"`, so the dispatcher
in `orchestrator.py` gains a third route without changing the subtask contract.

---

## Key Components

```
orchestrator._selectExecutor()
    ├── surface="terminal"  →  agents/executor.py          (L3, Claude CLI)
    ├── surface="browser"   →  agents/browser_executor.py  (L1, CDP/Playwright)
    └── surface="native"    →  agents/native_executor.py   (L2, UIA/pywinauto)  ← NEW
```

### `agents/native_executor.py`

Mirrors `browser_executor.py` in structure and result contract.

| Symbol | Role |
|---|---|
| `NativeUnavailable` | Raised when `pywinauto` is not installed; triggers clean degradation |
| `_run_native_actions(actions)` | Executes a structured action list via `pywinauto`; mockable for tests |
| `runNative(spec_or_prompt, **kw)` | Public entry-point; matches `runClaude` + `runBrowser` signature |
| `nativeActions(app, steps)` | Helper that builds a canonical action list from a high-level recipe |

### Supported Action Primitives

```jsonc
// Each action is a dict with an "action" key:
{"action": "launch",  "app": "notepad.exe"}
{"action": "connect", "app": "notepad.exe"}          // attach to running process
{"action": "find",    "title": "Untitled", "control_type": "Edit"}
{"action": "click",   "title": "OK"}
{"action": "type",    "text": "hello world"}
{"action": "press",   "key": "ctrl+s"}
{"action": "extract", "control_type": "Document"}    // read text content
{"action": "screenshot", "path": "snap.png"}
{"action": "close",   "app": "notepad.exe"}
```

### `config.py` additions

```python
NATIVE_LAYER_ENABLED: bool   # already present, defaults False
NATIVE_SCREENSHOT_DIR: Path  # where native screenshots land
NATIVE_ACTION_TIMEOUT_MS: int = 10000
```

### `surfaces.py` routing update

```python
SURFACE_EXECUTOR_MAP = {
    "terminal": "_run_claude",
    "browser":  "browser_executor.runBrowser",
    "native":   "native_executor.runNative",   # ← add
}
```

---

## Interactions

```
Orchestrator (Ollama brain)
    │
    │  authors spec: {surface:"native", native_actions:[...]}
    ▼
orchestrator._selectExecutor(spec)
    │   NATIVE_LAYER_ENABLED=True + surface="native"
    ▼
native_executor.runNative(spec)
    │
    ├─ normalizeSpec(spec)             ← reuse executor.normalizeSpec
    ├─ spec.get("native_actions") or   ← explicit action list
    │  _actions_from_prompt(prompt)    ← auto-derive from text (best-effort)
    │
    ▼
_run_native_actions(actions)
    │
    ├─ pywinauto.Application().start() / .connect()
    ├─ window.child_window(…).click()  / .type_keys()
    ├─ window.print_control_identifiers()  ← extract
    └─ returns transcript string
    │
    ▼
_result(spec, ok=True, stdout=transcript)   ← same shape as browser result
```

---

## Degradation Contract

Identical to L1:

| Condition | Behaviour |
|---|---|
| `pywinauto` not installed | `NativeUnavailable` → `ok=False, is_error=True` in result |
| App not found / launch fail | Exception caught → `ok=False, is_error=True` |
| Action timeout | Exception caught → `ok=False, is_error=True` |
| `NATIVE_LAYER_ENABLED=False` | Dispatcher falls back to `_run_claude` (L3) |

A failed native subtask is treated by the orchestrator identically to a failed
terminal subtask: the verify gate fires, retry logic applies, the adversary may
review, and the run continues rather than crashing.

---

## Key Differences from L1 (Browser)

| Dimension | L1 Browser | L2 Native |
|---|---|---|
| Transport | CDP (Playwright WebSocket) | UIA COM (pywinauto) |
| Target | Any web page | Any native Windows app |
| Selector language | CSS / XPath | `control_type`, `title`, `auto_id` |
| Headless capable | Yes (`headless=True`) | No — needs a display session (RDP or physical) |
| Install | `playwright install chromium` | `pip install pywinauto` |
| ChatGPT adversary brain | `askChatGPT` via CDP | N/A (Phase-2 feature stays on browser) |

---

## Testing Strategy

```
tests/test_native_executor.py
  TestNativeExecutor
    test_result_matches_runclaude_contract          # same keys as terminal + browser
    test_unavailable_backend_degrades               # NativeUnavailable -> clean error
    test_generic_exception_returns_error_result     # timeout/launch fail -> ok=False
    test_no_actions_is_clean_error                  # empty action list handled

  TestNativeDispatch
    test_dispatcher_routes_native_when_enabled      # NATIVE_LAYER_ENABLED=True + surface=native
    test_dispatcher_falls_back_when_disabled        # NATIVE_LAYER_ENABLED=False -> terminal
```

All tests mock `_run_native_actions` so pywinauto is never imported in CI;
the live integration path is exercised only with a real Windows session available.

---

## Implementation Order

1. `agents/native_executor.py` — scaffold with `NativeUnavailable`, `_run_native_actions`, `runNative`
2. `orchestrator._selectExecutor` — add `surface=="native"` branch
3. `config.py` — `NATIVE_LAYER_ENABLED` already present; add `NATIVE_SCREENSHOT_DIR`
4. `tests/test_native_executor.py` — full mock-based suite (no real pywinauto needed)
5. Manual smoke test: launch Notepad, type "hello", extract text, close
6. `NATIVE_LAYER_ENABLED=True` in `.env` on a machine with pywinauto installed
