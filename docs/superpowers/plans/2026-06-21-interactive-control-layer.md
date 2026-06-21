# Interactive Control Layer — Implementation Plan

> **For agentic workers:** implement component-by-component. This project is NOT a git repo and has no unit-test harness for the orchestrator, so the skill's TDD/commit cadence is replaced by: after each component, `py_compile` + import, and after all components a live smoke-run of `main.py` against a tiny goal. Steps use `- [ ]` tracking.

**Goal:** Turn 9TO5 runs into a glass-box: per-subtask verification with retry, a live Discord dashboard, a local web dashboard, a gateway command bot, optional approval gates, and plan editing — all controllable while the human is away.

**Architecture:** A file-backed `ControlBus` (one JSON per task under `state/control/`) is the shared nervous system between three processes — the orchestrator run, the Discord gateway bot, and the web dashboard. The orchestrator polls the Discord channel (REST) and the ControlBus between steps; abort/pause/approve/skip/add all flow through the bus. Verification is brain-authored (`verify` block per subtask) and run deterministically by a `verifier` module; failures trigger a re-authored retry.

**Tech stack:** Python stdlib (`http.server`, `subprocess`, `json`, `threading`), `requests` (Discord REST), `discord.py` (gateway command bot), `ollama` (brain). Zero new third-party deps.

---

## File map

| File | New? | Responsibility |
|------|------|----------------|
| `config.py` | modify | control/verify/dashboard constants |
| `control.py` | **new** | `ControlBus` — file-backed cross-process control state (abort/pause/decisions/plan-ops) + `AbortRun` |
| `agents/verifier.py` | **new** | `runVerification(verify, work_dir, executor_result)` → deterministic pass/fail |
| `state/task.py` | modify | per-subtask `verify` + `verify_result`; `meta.control_mode`; `setVerify`/`recordVerify` |
| `notifications/discord_bot.py` | modify | add `createMessage`/`editMessage`/`fetchMessagesAfter`; keep builders + `_post` |
| `notifications/dashboard.py` | **new** | `DiscordDashboard` — one self-updating embed + event ring buffer |
| `notifications/webdash.py` | **new** | stdlib HTTP server: live HTML view + `/api/state` + control buttons (abort/approve/reject/skip) |
| `notifications/command_bot.py` | **new** | discord.py gateway bot: `!status !plan !log !abort !pause !resume !approve !reject !skip !add !retry` |
| `orchestrator.py` | modify | verify+retry loop; `_checkControl` (poll Discord + bus) at every boundary; gates; dashboards; abort handling |
| `agents/replanner.py` | modify | emit `verify` on added subtasks |
| `main.py` | modify | `--mode watch\|gated`, `--web-port`, `--no-web`; pass through |

---

## Contracts (locked)

### ControlBus (`control.py`)
File: `state/control/<task_id>.json`:
```json
{"abort": false, "pause": false, "decisions": {"plan": null, "pre_pr": null},
 "plan_ops": [{"op":"skip","subtask_id":"st-003"}, {"op":"add","title":"...","description":"..."}],
 "seen_discord_id": null}
```
Methods (camelCase): `load()/save()`, `requestAbort()/isAbort()`, `requestPause()/clearPause()/isPaused()`,
`decide(gate,verdict)/getDecision(gate)`, `pushOp(op)/drainOps()->list`, `setSeen(id)/getSeen()`, `clear()`.
`AbortRun(Exception)` raised by orchestrator on abort.

### verify block (per subtask)
```json
{"cmd": "python -m taskcli --help", "expect": "exit_zero"}
```
`expect` ∈ `exit_zero` | `stdout_contains:<text>` | `stdout_regex:<re>`. `cmd` null → fall back to executor exit 0.
`verify_result` = `{"passed":bool,"cmd":str,"expect":str,"returncode":int,"stdout":str,"stderr":str}`.

### Discord REST additions (`discord_bot.py`)
- `createMessage(embed)->str|None` (POST messages, returns message id)
- `editMessage(message_id, embed)->bool` (PATCH)
- `fetchMessagesAfter(after_id)->(list[{id,content,author_is_bot}], latest_id)` (GET ?after=)

### Control commands (Discord text + web buttons → ControlBus)
`!abort`→abort; `!pause`/`!resume`→pause; `!approve`/`!reject`→decide(current_gate); `!skip <id>`→pushOp skip;
`!add <title>`→pushOp add; `!retry`→pushOp retry current; `!status`/`!plan`/`!log`→read-only replies.

---

## Tasks

### Task 1 — config constants
Add: `CONTROL_DIR = PROJECT_ROOT/"state"/"control"`; `DISCORD_POLL_SECONDS=4`; `DISCORD_DASHBOARD=True`;
`WEB_DASHBOARD=True`; `WEB_DASHBOARD_PORT=8787`; `CONTROL_MODE_DEFAULT="watch"`; `VERIFY_DEFAULT_EXPECT="exit_zero"`;
`VERIFY_TIMEOUT_SECONDS=120`. Add `CONTROL_DIR` to `_REQUIRED_DIRS`.
- [ ] implement → compile

### Task 2 — `control.py` (ControlBus + AbortRun)
Atomic read-modify-write JSON; all methods above. No external deps.
- [ ] implement → import-test instantiate + abort round-trip

### Task 3 — `agents/verifier.py`
`runVerification(verify, work_dir, executor_result)`; safe subprocess (shell=False where possible, else cmd /c on nt),
timeout `VERIFY_TIMEOUT_SECONDS`, truncate outputs to 2000 chars. Eval all three `expect` modes.
- [ ] implement → unit-eval each expect mode inline

### Task 4 — `state/task.py`
`addSubtask(..., verify=None)` stores verify + `verify_result=None`; `recordVerify(sid, result)`;
`meta.control_mode` set in `create(...)` default from config; `setControlMode`.
- [ ] implement → import

### Task 5 — `notifications/discord_bot.py`
Add create/edit/fetch helpers (REST v10). Keep existing.
- [ ] implement → import

### Task 6 — `notifications/dashboard.py` (DiscordDashboard)
Ring buffer (last 8 events); `start(state)`→createMessage; `update(state, phase, note)`→editMessage with rich embed
(status, subtask X/Y, attempt, last verify ✓/✗, elapsed/ETA, recent events). Degrades to no-op if Discord unconfigured.
- [ ] implement → import

### Task 7 — `notifications/webdash.py`
`startWebDashboard(task_id)->thread`; ThreadingHTTPServer daemon. Routes: `/` HTML (auto-refresh via fetch /api/state),
`/api/state` JSON (TaskState + control), `/api/control` POST `{action,arg}` → ControlBus. Buttons: Abort, Approve, Reject, Skip.
- [ ] implement → import + bind smoke

### Task 8 — `notifications/command_bot.py` (gateway)
discord.py Client (message_content intent). Maps commands→ControlBus / read-only replies. Targets latest task.
Runnable `python -m notifications.command_bot`.
- [ ] implement → import (don't run gateway in CI)

### Task 9 — `agents/replanner.py`
System prompt + schema: added subtasks include `verify {cmd,expect}`. Pass spec constraints through (fixes the
stdlib-drift bug): include "respect goal constraints; do NOT add dependency-install/env steps unless the goal allows".
- [ ] implement → import

### Task 10 — `orchestrator.py` (the integration)
- `runFull(state, work_dir, auto_pr, control_mode)`.
- Construct `ControlBus`, `DiscordDashboard`, start `webdash`.
- `_checkControl(gate=None)`: `fetchMessagesAfter` → translate to bus ops; `drainOps` (apply skip/add/retry);
  if `isPaused` block-loop (sleep, re-poll) until resumed/abort; if `isAbort` raise `AbortRun`; if `gate` and gated,
  post "awaiting !approve" + wait for `getDecision(gate)` (or abort).
- Planner authors `verify`; store on subtasks.
- Exec loop: `_checkControl()` at top; run executor; `verifier.runVerification`; `recordVerify`; pass→done,
  fail→ re-author prompt WITH failure output, retry ≤ `MAX_SUBTASK_ATTEMPTS`; exhausted→failed + alert embed.
  `dashboard.update(...)` after every transition.
- Gates: after planning (`plan`), before PR (`pre_pr`).
- Wrap pipeline in try/except `AbortRun` → status `aborted`, final dashboard, aborted embed.
- [ ] implement → compile

### Task 11 — `main.py`
`--mode {watch,gated}` (default `config.CONTROL_MODE_DEFAULT`), `--web-port`, `--no-web`. Pass `control_mode`.
Print web dashboard URL on start.
- [ ] implement → compile

### Task 12 — Live verification
`py_compile` all; import all; run `main.py --goal "<tiny>" --hours 1 --auto-approve --mode watch` against a trivial goal
with a real `verify` (e.g. create a file then `python -c` checks it); confirm: verify ran, dashboard message created/edited,
web `/api/state` serves, `!abort` via injected bus flag stops gracefully.

---

## Self-review notes
- Spec coverage: verification gate (T3,T10) ✓; retry (T10) ✓; live Discord dashboard (T6,T10) ✓; REST-poll abort (T10) ✓;
  gateway command bot (T8) ✓; approval gates (T10 gated) ✓; plan editing (T2 plan_ops, T8/T7 emit, T10 apply) ✓; web dashboard (T7) ✓;
  replanner-drift fix (T9) ✓.
- No git → "commit" steps replaced by compile+import+live-run gates.
- Type consistency: `verify`/`verify_result`, `ControlBus` method names, Discord helper names are referenced identically across T2/T5/T10.
