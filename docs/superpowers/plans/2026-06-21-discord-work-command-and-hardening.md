# Discord `/work` Command + Full-Surface Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/work` Discord slash command (optional params; modal+dropdown onboarding when blank) that launches a full 9to5 run exactly like the CLI, auto-unpin the live dashboard when a run ends, and harden + professionalize the entire Discord integration.

**Architecture:** A new pure, discord-free `notifications/commands.py` becomes the single source of truth for the `!` grammar + authorization + active-run policy, consumed by the gateway bot, the orchestrator's in-run poller, and the new `work_launcher.py`. All Discord REST is funneled through one `_request` chokepoint (429 backoff, 401-only disable, embed clamping). `/work` spawns `main.py` as a detached child. The dashboard pins at start and unpins in `runFull`'s `finally`.

**Tech Stack:** Python 3.11 stdlib (`subprocess`, `threading`, `re`, `unittest`), `requests` (Discord REST), `discord.py` 2.7.1 (`app_commands`, modals, views), `ollama`. **Zero new third-party deps.** Tests run with `venv\Scripts\python -m unittest`.

**Spec:** `docs/superpowers/specs/2026-06-21-discord-work-command-design.md` (base + Addendum v2).

---

## File map

| File | New? | Responsibility |
|------|------|----------------|
| `config.py` | modify | `DISCORD_*` limit/timeout/retry constants; `DISCORD_GUILD_ID`; relocate `_EFFORT_LABELS` → `EFFORT_LABELS` |
| `notifications/commands.py` | **new** | pure command spine: `COMMAND_REGISTRY`, `parseCommand`/`applyCommand`, `decide`, `isAuthorized`, `resolveTargetTask`/`isRunActive` |
| `notifications/discord_bot.py` | modify | `_request` chokepoint, `_clampEmbed`/`truncate`, `unpinMessage`, owner-only mentions, `formatVerdict` allowlist, `fetchMessagesAfter` author_id, `baselineLatestId`, named milestone builders |
| `notifications/work_launcher.py` | **new** | pure launcher: `WorkRequest`, `parseHours`, `validate`, `buildArgv`, `activeRun`, `newestTaskSince`, `spawn` |
| `notifications/command_bot.py` | modify | delegate to `commands.py`; authorize-before-dispatch; defer→followup; `/work` slash + `WorkModal` + `WorkSetupView`; sync-once; `tree.on_error` |
| `orchestrator.py` | modify | seed cursor once; poller → `commands.decide`/`applyCommand`; named milestone embeds; `dashboard.unpin()` in `finally` |
| `notifications/dashboard.py` | modify | deadlock-free snapshot + `_send_lock`; recover-once; `unpin()`; density/footer/timestamp cleanups |
| `tests/test_commands.py` | **new** | unit tests for the command spine |
| `tests/test_discord_rest.py` | **new** | unit tests for REST chokepoint + clamping + builders |
| `tests/test_work_launcher.py` | **new** | unit tests for the launcher core |

**Build order matches the tasks below.** Each task is independently committable.

---

## Task 1: config.py — Discord constants + effort-label relocation

**Files:**
- Modify: `config.py` (Discord section ~line 51-56; effort section ~line 169-179)

- [ ] **Step 1: Add the Discord limit/timeout/guild constants**

In `config.py`, in the `# --- Discord ---` block (after `DISCORD_HUMAN_USER_ID`), add:

```python
# Guild for instant slash-command registration; 0 => global (can take ~1h to propagate).
_RAW_GUILD = os.getenv("DISCORD_GUILD_ID", "0") or "0"
DISCORD_GUILD_ID: int = int(_RAW_GUILD) if _RAW_GUILD.isdigit() else 0

# Discord hard limits (single source of truth for all truncation/clamping).
DISCORD_MAX_CONTENT: int = 2000
DISCORD_MAX_EMBED_DESC: int = 4096
DISCORD_MAX_FIELD_NAME: int = 256
DISCORD_MAX_FIELD_VALUE: int = 1024
DISCORD_EMBED_TOTAL_MAX: int = 6000
DISCORD_REST_TIMEOUT: int = 15      # seconds per Discord REST call
DISCORD_RETRY_MAX: int = 2          # 429 retries for milestone sends (NOT the control poll)
```

- [ ] **Step 2: Relocate the effort labels into config**

In `config.py`, in the `# --- Effort levels ---` block (after `EFFORT_BARS`), add:

```python
# Human display labels (single home; discord_bot.effortBar reads these — no private copy).
EFFORT_LABELS: dict[str, str] = {
    "low": "Low", "default": "Standard", "medium": "Standard",
    "high": "High", "xhigh": "Very High", "ultracode": "Max",
}
```

- [ ] **Step 3: Verify it imports**

Run: `venv\Scripts\python -c "import config; print(config.DISCORD_MAX_FIELD_VALUE, config.DISCORD_GUILD_ID, config.EFFORT_LABELS['high'])"`
Expected: `1024 0 High`

- [ ] **Step 4: Commit**

```bash
git add config.py
git commit -m "config: Discord limit/timeout/guild constants + EFFORT_LABELS relocation"
```

---

## Task 2: notifications/commands.py — the pure command spine (+ tests)

**Files:**
- Create: `notifications/commands.py`
- Test: `tests/test_commands.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_commands.py`:

```python
"""Unit tests for the pure command spine (no gateway needed)."""
import unittest
from unittest import mock

import config
from notifications import commands
from state.task import TaskState


def _state(status="executing"):
    st = TaskState.create("test goal", 1.0)
    st.meta["status"] = status
    return st


class TestParseCommand(unittest.TestCase):
    def test_non_bang_returns_none(self):
        self.assertIsNone(commands.parseCommand("hello"))

    def test_unknown_returns_none(self):
        self.assertIsNone(commands.parseCommand("!frobnicate"))

    def test_exact_token_match(self):
        cmd = commands.parseCommand("!abort")
        self.assertEqual(cmd.name, "abort")
        self.assertEqual(cmd.arg, "")

    def test_skipfoo_does_not_match_skip(self):
        self.assertIsNone(commands.parseCommand("!skipfoo"))

    def test_add_arg_sliced_correctly(self):
        cmd = commands.parseCommand("!add write a parser")
        self.assertEqual(cmd.name, "add")
        self.assertEqual(cmd.arg, "write a parser")

    def test_skip_arg(self):
        cmd = commands.parseCommand("!skip st-003")
        self.assertEqual((cmd.name, cmd.arg), ("skip", "st-003"))


class TestIsAuthorized(unittest.TestCase):
    def test_unset_allows_all(self):
        with mock.patch.object(config, "DISCORD_HUMAN_USER_ID", ""):
            self.assertTrue(commands.isAuthorized(12345))
            self.assertTrue(commands.isAuthorized(None))

    def test_blank_string_no_crash(self):
        with mock.patch.object(config, "DISCORD_HUMAN_USER_ID", "   "):
            self.assertTrue(commands.isAuthorized(1))

    def test_set_owner_only(self):
        with mock.patch.object(config, "DISCORD_HUMAN_USER_ID", "777"):
            self.assertTrue(commands.isAuthorized(777))
            self.assertTrue(commands.isAuthorized("777"))
            self.assertFalse(commands.isAuthorized(778))
            self.assertFalse(commands.isAuthorized(None))


class TestDecide(unittest.TestCase):
    def test_bot_author_blocked(self):
        with mock.patch.object(config, "DISCORD_HUMAN_USER_ID", ""):
            self.assertIsNone(commands.decide(1, True, "!abort"))

    def test_unauthorized_blocked(self):
        with mock.patch.object(config, "DISCORD_HUMAN_USER_ID", "777"):
            self.assertIsNone(commands.decide(778, False, "!abort"))

    def test_authorized_passes(self):
        with mock.patch.object(config, "DISCORD_HUMAN_USER_ID", "777"):
            cmd = commands.decide(777, False, "!abort")
            self.assertEqual(cmd.name, "abort")


class TestIsRunActive(unittest.TestCase):
    def test_terminal_inactive(self):
        for s in TaskState._TERMINAL:
            self.assertFalse(commands.isRunActive(_state(s)), s)

    def test_executing_active(self):
        self.assertTrue(commands.isRunActive(_state("executing")))


class TestApplyCommand(unittest.TestCase):
    def test_reject_copy_is_rejected_not_rejectd(self):
        st = _state("executing")
        bus = mock.Mock()
        bus.getPendingGate.return_value = "plan"
        out = commands.applyCommand(bus, st, commands.Command("reject", ""))
        self.assertIn("rejected", out.lower())
        self.assertNotIn("rejectd", out.lower())
        bus.decide.assert_called_once_with("plan", "reject")

    def test_skip_bad_id_rejected(self):
        st = _state("executing")
        bus = mock.Mock()
        out = commands.applyCommand(bus, st, commands.Command("skip", "garbage"))
        self.assertIn("usage", out.lower())
        bus.pushOp.assert_not_called()

    def test_abort_mutates_bus(self):
        st = _state("executing")
        bus = mock.Mock()
        commands.applyCommand(bus, st, commands.Command("abort", ""))
        bus.requestAbort.assert_called_once()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv\Scripts\python -m unittest tests.test_commands -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'notifications.commands'`

- [ ] **Step 3: Implement `notifications/commands.py`**

Create `notifications/commands.py`:

```python
"""Pure, discord-free command layer -- the single source of truth for the '!' grammar,
authorization, and active-run policy. Consumed by command_bot (gateway), orchestrator
(in-run poller), work_launcher (/work), and dashboard (footer help). No network, no
discord.py import -> fully unit-testable.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import NamedTuple, Optional

import config
from control import ControlBus
from notifications import discord_bot as discord
from state.task import TaskState

LOG = config.getLogger("commands")

_SKIP_ID_RE = re.compile(r"^st-\d{3}$")
NO_TASK = "No 9TO5 task on record yet."

# Canonical command list. 'arg': none|required|optional. 'mutating' gates owner-only intent.
COMMAND_REGISTRY: dict[str, dict] = {
    "status":  {"arg": "none",     "mutating": False, "help": "current phase, subtask X/Y, elapsed/ETA"},
    "plan":    {"arg": "none",     "mutating": False, "help": "full subtask list with statuses"},
    "log":     {"arg": "none",     "mutating": False, "help": "Obsidian index + web dashboard URL"},
    "help":    {"arg": "none",     "mutating": False, "help": "show this command list"},
    "abort":   {"arg": "none",     "mutating": True,  "help": "graceful stop after the current step"},
    "pause":   {"arg": "none",     "mutating": True,  "help": "hold the run"},
    "resume":  {"arg": "none",     "mutating": True,  "help": "continue a paused run"},
    "approve": {"arg": "none",     "mutating": True,  "help": "approve the pending gate"},
    "reject":  {"arg": "none",     "mutating": True,  "help": "reject the pending gate"},
    "skip":    {"arg": "required", "mutating": True,  "help": "skip a pending subtask: !skip st-00N"},
    "add":     {"arg": "required", "mutating": True,  "help": "queue a new subtask: !add <title>"},
    "retry":   {"arg": "none",     "mutating": True,  "help": "re-run the current subtask"},
}


class Command(NamedTuple):
    name: str
    arg: str


def parseCommand(content: str) -> Optional[Command]:
    """Exact-token parse of a '!' command. None for non-'!' or unknown names."""
    s = (content or "").strip()
    if not s.startswith("!"):
        return None
    parts = s[1:].split(maxsplit=1)
    if not parts:
        return None
    name = parts[0].lower()
    if name not in COMMAND_REGISTRY:
        return None
    arg = parts[1].strip() if len(parts) > 1 else ""
    return Command(name, arg)


def isAuthorized(user_id: Optional[object]) -> bool:
    """True if no owner configured (dev), else only the configured owner. Empty-string safe."""
    raw = (config.DISCORD_HUMAN_USER_ID or "").strip()
    if not raw or not raw.isdigit():
        return True
    try:
        return user_id is not None and int(user_id) == int(raw)
    except (TypeError, ValueError):
        return False


def decide(author_id: Optional[object], is_bot: bool, content: str) -> Optional[Command]:
    """Shared gate for BOTH the gateway and the in-run poller: returns the command to
    apply only if the author is a non-bot AND authorized. Pure -> directly testable."""
    if is_bot:
        return None
    if not isAuthorized(author_id):
        return None
    return parseCommand(content)


# ---- task resolution / active-run policy (one definition reused everywhere) ----
def resolveTargetTask() -> Optional[TaskState]:
    return TaskState.loadLatest()


def isRunActive(state: Optional[TaskState]) -> bool:
    """A run is 'active' iff its status is not terminal. Derived from TaskState._TERMINAL
    so it can never drift from the terminal set."""
    if state is None:
        return False
    return state.meta.get("status") not in TaskState._TERMINAL


def footerHelp() -> str:
    """Short, never-stale command hint derived from the registry (used by the dashboard)."""
    return " ".join(f"!{n}" for n in ("status", "abort", "pause", "help"))


def _fmtDelta(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m{s:02d}s"


def _statusText(bus: ControlBus, state: TaskState) -> str:
    done, total = state.progress()
    try:
        started = datetime.fromisoformat(state.meta["started_at"])
        deadline = datetime.fromisoformat(state.meta["deadline_at"])
        now = datetime.now().astimezone()
        elapsed = _fmtDelta((now - started).total_seconds())
        eta = _fmtDelta((deadline - now).total_seconds())
    except Exception:  # noqa: BLE001
        elapsed = eta = "-"
    cur = next((s for s in state.subtasks if s["status"] == "in_progress"), None) or state.nextActionable()
    cur_txt = f"`{cur['subtask_id']}` {cur['title']}" if cur else "—"
    gate = bus.getPendingGate()
    gate_txt = f"\n⏳ awaiting gate **{gate}** — `!approve` / `!reject`" if gate else ""
    return (f"**`{state.meta['status']}`** · {discord.progressBar(done, total)} · "
            f"mode `{state.meta.get('control_mode', 'watch')}`\n"
            f"Current: {cur_txt}\nElapsed {elapsed} · ETA {eta}{gate_txt}")


def _planText(state: TaskState) -> str:
    lines = [f"{s['subtask_id']} [{s['status']}] {s['title']}" for s in state.subtasks]
    body = ("\n".join(lines) or "(no subtasks)")[:1800]
    return f"{discord.subtaskTracker(state.subtasks)}\n```\n{body}\n```"


def _helpText() -> str:
    rows = [f"`!{n}` — {m['help']}" for n, m in COMMAND_REGISTRY.items()]
    return "**9TO5 commands**\n" + "\n".join(rows)


def applyCommand(bus: ControlBus, state: TaskState, cmd: Command) -> str:
    """Perform the bus mutation and return human markdown text ('' for silent control ops)."""
    n = cmd.name
    if n == "status":
        return _statusText(bus, state)
    if n == "plan":
        return _planText(state)
    if n == "log":
        return (f"Index: `{state.indexNoteRel()}`\n"
                f"Vault: `{state.data['obsidian']['vault_root']}`\n"
                f"Web: http://127.0.0.1:{config.WEB_DASHBOARD_PORT}/")
    if n == "help":
        return _helpText()
    if n == "abort":
        bus.requestAbort()
        return "🛑 Abort requested — run stops after the current step."
    if n == "pause":
        bus.requestPause()
        return "⏸ Paused."
    if n == "resume":
        bus.clearPause()
        return "▶ Resumed."
    if n in ("approve", "reject"):
        gate = bus.getPendingGate()
        if not gate:
            return "No gate is currently pending."
        verdict = "approve" if n == "approve" else "reject"
        bus.decide(gate, verdict)
        return f"Gate **{gate}** → {'approved' if n == 'approve' else 'rejected'}."
    if n == "skip":
        if not _SKIP_ID_RE.match(cmd.arg):
            return "usage: `!skip st-00N` (e.g. `!skip st-003`)"
        bus.pushOp({"op": "skip", "subtask_id": cmd.arg})
        return f"⏭️ Queued skip of `{cmd.arg}`."
    if n == "add":
        if not cmd.arg:
            return "usage: `!add <title>`"
        bus.pushOp({"op": "add", "title": cmd.arg, "description": cmd.arg})
        return f"➕ Queued new subtask: {cmd.arg}"
    if n == "retry":
        bus.pushOp({"op": "retry"})
        return "🔁 Queued retry of the current subtask."
    return _helpText()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `venv\Scripts\python -m unittest tests.test_commands -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add notifications/commands.py tests/test_commands.py
git commit -m "feat(discord): pure commands.py spine (parse/apply/decide/auth/active) + tests"
```

---

## Task 3: discord_bot.py — REST chokepoint, clamping, unpin (+ tests)

**Files:**
- Modify: `notifications/discord_bot.py` (REST plumbing section, lines ~104-202)
- Test: `tests/test_discord_rest.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_discord_rest.py`:

```python
"""Unit tests for the discord_bot REST chokepoint + embed clamping (no real network)."""
import unittest
from unittest import mock

import config
from notifications import discord_bot as d


class _Resp:
    def __init__(self, status_code, body=None, text=""):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.text = text
        self.headers = {}

    def json(self):
        return self._body


def _cfg():
    return mock.patch.multiple(config, DISCORD_BOT_TOKEN="t", DISCORD_CHANNEL_ID=123)


class TestRequest(unittest.TestCase):
    def setUp(self):
        d._DISABLED = False

    def test_429_then_success_retries(self):
        calls = []

        def fake(method, url, **kw):
            calls.append(1)
            return _Resp(429, {"retry_after": 0.0}) if len(calls) == 1 else _Resp(200, {"id": "9"})

        with _cfg(), mock.patch.object(d.requests, "request", side_effect=fake), \
                mock.patch.object(d.time, "sleep"):
            r = d._request("POST", "/x")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(calls), 2)

    def test_401_latches_disabled(self):
        with _cfg(), mock.patch.object(d.requests, "request", return_value=_Resp(401, text="bad")):
            d._request("GET", "/x")
        self.assertTrue(d._DISABLED)
        # subsequent calls short-circuit to None
        with _cfg(), mock.patch.object(d.requests, "request") as m:
            self.assertIsNone(d._request("GET", "/x"))
            m.assert_not_called()

    def test_404_does_not_disable(self):
        with _cfg(), mock.patch.object(d.requests, "request", return_value=_Resp(404, text="gone")):
            d._request("DELETE", "/x")
        self.assertFalse(d._DISABLED)

    def test_control_poll_no_retry(self):
        with _cfg(), mock.patch.object(d.requests, "request", return_value=_Resp(429, {"retry_after": 99})) as m, \
                mock.patch.object(d.time, "sleep") as s:
            d._request("GET", "/x", retries=0)
        self.assertEqual(m.call_count, 1)
        s.assert_not_called()


class TestClampAndTruncate(unittest.TestCase):
    def test_truncate_marks_clip(self):
        self.assertEqual(d.truncate("abcdef", 4), "abc…")
        self.assertEqual(d.truncate("ab", 4), "ab")

    def test_clamp_field_value(self):
        e = {"fields": [{"name": "n", "value": "x" * 5000}]}
        out = d._clampEmbed(e)
        self.assertLessEqual(len(out["fields"][0]["value"]), config.DISCORD_MAX_FIELD_VALUE)

    def test_clamp_drops_beyond_25_fields(self):
        e = {"fields": [{"name": str(i), "value": "v"} for i in range(40)]}
        out = d._clampEmbed(e)
        self.assertEqual(len(out["fields"]), 25)


class TestUnpinAndVerdict(unittest.TestCase):
    def test_unpin_404_is_success(self):
        with _cfg(), mock.patch.object(d, "_request", return_value=_Resp(404)):
            self.assertTrue(d.unpinMessage("5"))

    def test_unpin_none_message(self):
        self.assertFalse(d.unpinMessage(None))

    def test_formatVerdict_unknown(self):
        self.assertEqual(d.formatVerdict("approved"), "✅ APPROVED")
        self.assertEqual(d.formatVerdict("rejected"), "⚔️ CHALLENGED")
        self.assertIn("UNKNOWN", d.formatVerdict(""))
        self.assertIn("UNKNOWN", d.formatVerdict("pending"))


class TestFetch(unittest.TestCase):
    def test_author_id_surfaced(self):
        body = [{"id": "2", "content": "!abort", "author": {"id": "777", "bot": False}}]
        with _cfg(), mock.patch.object(d, "_request", return_value=_Resp(200, body)):
            msgs, latest = d.fetchMessagesAfter("1")
        self.assertEqual(msgs[0]["author_id"], "777")
        self.assertEqual(latest, "2")

    def test_baseline_returns_id_only(self):
        with _cfg(), mock.patch.object(d, "_request", return_value=_Resp(200, [{"id": "9"}])):
            self.assertEqual(d.baselineLatestId(), "9")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv\Scripts\python -m unittest tests.test_discord_rest -v`
Expected: FAIL — `_request`/`truncate`/`_clampEmbed`/`unpinMessage`/`baselineLatestId` not defined; `formatVerdict("")` returns APPROVED.

- [ ] **Step 3: Replace the REST plumbing section**

In `notifications/discord_bot.py`, add `import time` at the top (with the other imports), and **replace the entire `# === REST plumbing ===` section** (from `def _authHeaders()` through `def sendEmbed(...)`, lines ~104-202) with:

```python
# =====================================================================
# REST plumbing -- one chokepoint
# =====================================================================
_DISABLED = False   # latched ON only by a hard 401 (bad token); never by 403/404


def _authHeaders() -> dict:
    return {"Authorization": f"Bot {config.DISCORD_BOT_TOKEN}", "Content-Type": "application/json"}


def _ownerMentions() -> dict:
    """allowed_mentions that can never expand past the configured owner."""
    oid = (config.DISCORD_HUMAN_USER_ID or "").strip()
    return {"parse": [], "users": [int(oid)] if oid.isdigit() else []}


def _request(method: str, path: str, *, json: Optional[dict] = None,
             params: Optional[dict] = None, retries: int = config.DISCORD_RETRY_MAX):
    """Single REST chokepoint. 429 -> sleep(retry_after) up to `retries` (milestone sends);
    pass retries=0 on the control-poll path so it never blocks the run loop. A hard 401 latches
    the whole surface off; 403/404 are logged but NEVER disable (a deleted message is normal)."""
    global _DISABLED
    if _DISABLED or not config.DISCORD_BOT_TOKEN or not config.DISCORD_CHANNEL_ID:
        return None
    url = f"{_API}{path}"
    attempt = 0
    while True:
        try:
            r = requests.request(method, url, headers=_authHeaders(), json=json, params=params,
                                 timeout=config.DISCORD_REST_TIMEOUT)
        except Exception as e:  # noqa: BLE001
            LOG.warning("Discord %s %s failed: %s", method, path, e)
            return None
        if r.status_code == 429 and attempt < retries:
            try:
                retry_after = float((r.json() or {}).get("retry_after",
                                    r.headers.get("Retry-After", 1)))
            except Exception:  # noqa: BLE001
                retry_after = 1.0
            time.sleep(min(retry_after, 10.0))
            attempt += 1
            continue
        if r.status_code == 401:
            _DISABLED = True
            LOG.error("Discord auth failed (401) -> disabling Discord for this process")
        elif not (200 <= r.status_code < 300) and r.status_code != 404:
            LOG.warning("Discord %s %s -> %s: %s", method, path, r.status_code, (r.text or "")[:200])
        return r


def truncate(text, n: int) -> str:
    """Clamp to n chars, marking a clip with a trailing ellipsis."""
    text = str(text if text is not None else "")
    if n <= 1:
        return text[:max(n, 0)]
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def _embedLen(embed: dict) -> int:
    total = len(str(embed.get("title", ""))) + len(str(embed.get("description", "")))
    total += len(str((embed.get("footer") or {}).get("text", "")))
    for f in embed.get("fields", []) or []:
        total += len(str(f.get("name", ""))) + len(str(f.get("value", "")))
    return total


def _clampEmbed(embed: dict) -> dict:
    """Guarantee a sendable embed: per-field clamp (no oversize field can 400 the whole message),
    <=25 fields, and a 6000-total budget enforced by shrinking the LARGEST field value first so the
    dashboard's dynamic tail rows are never silently dropped."""
    if not isinstance(embed, dict):
        return embed
    e = dict(embed)
    if isinstance(e.get("description"), str):
        e["description"] = truncate(e["description"], config.DISCORD_MAX_EMBED_DESC)
    fields = e.get("fields")
    if isinstance(fields, list):
        clamped = []
        for f in fields[:25]:
            if not isinstance(f, dict):
                continue
            nf = dict(f)
            nf["name"] = truncate(nf.get("name", ""), config.DISCORD_MAX_FIELD_NAME)
            nf["value"] = truncate(nf.get("value", ""), config.DISCORD_MAX_FIELD_VALUE) or "—"
            clamped.append(nf)
        e["fields"] = clamped
        guard = 0
        while _embedLen(e) > config.DISCORD_EMBED_TOTAL_MAX and guard < 50:
            guard += 1
            biggest = max(e["fields"], key=lambda f: len(str(f.get("value", ""))), default=None)
            if biggest is None or len(str(biggest.get("value", ""))) <= 8:
                break
            biggest["value"] = truncate(biggest["value"], max(8, len(str(biggest["value"])) // 2))
    return e


def createMessage(embed: dict, content: Optional[str] = None, components: Optional[list] = None) -> Optional[str]:
    payload: dict = {"embeds": [_clampEmbed(embed)]}
    if content:
        payload["content"] = content
        payload["allowed_mentions"] = _ownerMentions()
    if components is not None:
        payload["components"] = components
    r = _request("POST", f"/channels/{config.DISCORD_CHANNEL_ID}/messages", json=payload)
    if r is not None and 200 <= r.status_code < 300:
        try:
            return str(r.json().get("id"))
        except Exception:  # noqa: BLE001
            return None
    return None


def editMessage(message_id: str, embed: dict, content: Optional[str] = None,
                components: Optional[list] = None) -> bool:
    if not message_id:
        return False
    payload: dict = {"embeds": [_clampEmbed(embed)]}
    if content is not None:
        payload["content"] = content
        if content:
            payload["allowed_mentions"] = _ownerMentions()
    if components is not None:
        payload["components"] = components
    r = _request("PATCH", f"/channels/{config.DISCORD_CHANNEL_ID}/messages/{message_id}", json=payload)
    return r is not None and 200 <= r.status_code < 300


def pinMessage(message_id: Optional[str]) -> bool:
    if not message_id:
        return False
    r = _request("PUT", f"/channels/{config.DISCORD_CHANNEL_ID}/pins/{message_id}")
    if r is None:
        return False
    if r.status_code == 400 and "pin" in (r.text or "").lower():
        LOG.error("Discord pin cap likely reached; old dashboards not unpinned")
    return 200 <= r.status_code < 300


def unpinMessage(message_id: Optional[str]) -> bool:
    """Idempotent: 404 (already unpinned / message gone) counts as success."""
    if not message_id:
        return False
    r = _request("DELETE", f"/channels/{config.DISCORD_CHANNEL_ID}/pins/{message_id}")
    if r is None:
        return False
    return (200 <= r.status_code < 300) or r.status_code == 404


def fetchMessagesAfter(after_id: Optional[str], limit: int = 25) -> tuple[list[dict], Optional[str]]:
    """Control-poll path: retries=0 so a 429 returns immediately and never blocks the run loop.
    Surfaces author_id so the poller can authorize. Single page (no burst paging)."""
    params: dict = {"limit": limit}
    if after_id:
        params["after"] = after_id
    r = _request("GET", f"/channels/{config.DISCORD_CHANNEL_ID}/messages", params=params, retries=0)
    if r is None or not (200 <= r.status_code < 300):
        return [], after_id
    try:
        msgs = r.json()
    except Exception:  # noqa: BLE001
        return [], after_id
    out = [{"id": str(m.get("id")), "content": m.get("content") or "",
            "author_is_bot": bool((m.get("author") or {}).get("bot")),
            "author_id": str((m.get("author") or {}).get("id") or "")} for m in reversed(msgs)]
    latest = out[-1]["id"] if out else after_id
    return out, latest


def baselineLatestId() -> Optional[str]:
    """Newest message id (no messages returned) -- used to SEED the control cursor at run start
    so a stale '!abort' from a prior run is never replayed. Best-effort/non-fatal."""
    r = _request("GET", f"/channels/{config.DISCORD_CHANNEL_ID}/messages",
                 params={"limit": 1}, retries=0)
    if r is None or not (200 <= r.status_code < 300):
        return None
    try:
        msgs = r.json()
        return str(msgs[0]["id"]) if msgs else None
    except Exception:  # noqa: BLE001
        return None


def sendEmbed(embed: dict, content: Optional[str] = None, components: Optional[list] = None) -> dict:
    payload: dict = {"embeds": [_clampEmbed(embed)]}
    if content:
        payload["content"] = content
        payload["allowed_mentions"] = _ownerMentions()
    if components:
        payload["components"] = components
    r = _request("POST", f"/channels/{config.DISCORD_CHANNEL_ID}/messages", json=payload)
    return {"ok": r is not None and 200 <= r.status_code < 300,
            "status": getattr(r, "status_code", None)}
```

- [ ] **Step 4: Delete the now-dead `_post` references and color constants**

In `notifications/discord_bot.py`, delete the module-level color constants block `GREEN = ...` through `YELLOW = ...` (lines ~27-32) — ad-hoc embeds will use `statusColor(...)`. (Any builder still referencing them is updated in Task 4.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `venv\Scripts\python -m unittest tests.test_discord_rest -v`
Expected: most PASS. `TestUnpinAndVerdict.test_formatVerdict_unknown` still FAILS (fixed in Task 4) — that's expected; leave it.

- [ ] **Step 6: Commit**

```bash
git add notifications/discord_bot.py tests/test_discord_rest.py
git commit -m "feat(discord): single _request chokepoint (429/401-disable) + clamp/truncate + unpinMessage + author_id/baseline"
```

---

## Task 4: discord_bot.py — verdict allowlist, effortBar, named milestone builders

**Files:**
- Modify: `notifications/discord_bot.py` (UI kit + embed builders)

- [ ] **Step 1: Fix `formatVerdict` to an allowlist**

In `notifications/discord_bot.py`, replace `formatVerdict`:

```python
_APPROVED = {"approved", "approve", "pass", "ok"}
_CHALLENGED = {"challenged", "rejected", "reject", "blocked", "fail"}


def formatVerdict(verdict: Optional[str]) -> str:
    v = (verdict or "").lower().strip()
    if v in _APPROVED:
        return "✅ APPROVED"
    if v in _CHALLENGED:
        return "⚔️ CHALLENGED"
    return "❔ UNKNOWN"
```

- [ ] **Step 2: Point `effortBar` at config.EFFORT_LABELS and delete the private copy**

In `notifications/discord_bot.py`, delete the `_EFFORT_LABELS = {...}` dict (lines ~35-38) and change `effortBar`:

```python
def effortBar(effort: Optional[str]) -> str:
    key = (effort or "default").lower()
    bar = config.EFFORT_BARS.get(key, config.EFFORT_BARS["default"])
    label = config.EFFORT_LABELS.get(key, "Standard")
    return f"{bar}  {label}"
```

- [ ] **Step 3: Make `adversaryTriggeredEmbed` colour UNKNOWN neutral**

In `adversaryTriggeredEmbed`, change the verdict colouring so a non-approved, non-challenged verdict is neutral grey. Replace the `challenged`/`color` lines:

```python
    v = (verdict or "").lower().strip()
    if verdict is None:
        color = statusColor("adversary")
    elif v in _CHALLENGED:
        color = statusColor("blocked")
    elif v in _APPROVED:
        color = statusColor("done")
    else:
        color = 0x95A5A6  # UNKNOWN -> neutral grey, never false-green
```

- [ ] **Step 4: Add the four named milestone builders**

Append to `notifications/discord_bot.py` (embed builders section):

```python
def gateNeededEmbed(gate: str) -> dict:
    return {
        "title": f"⏳ Approval needed — {gate}",
        "color": statusColor("paused"),
        "description": "Reply `!approve` / `!reject`, or use the web dashboard.",
        "timestamp": _nowIso(),
        "fields": [{"name": "Gate", "value": f"`{gate}`", "inline": True}],
    }


def subtaskFailedEmbed(subtask_id: str, title: str, verify_result: Optional[dict], attempts: int) -> dict:
    vr = verify_result or {}
    return {
        "title": "⚠️ Subtask failed verification",
        "color": statusColor("failed"),
        "timestamp": _nowIso(),
        "fields": [
            {"name": "Subtask", "value": truncate(f"`{subtask_id}` {title}", 256), "inline": False},
            {"name": "Attempts", "value": str(attempts), "inline": True},
            {"name": "Verify", "value": truncate(str(vr.get("cmd") or "exit"), 512), "inline": False},
        ],
        "footer": {"text": "task continues with remaining subtasks"},
    }


def abortedEmbed(reason: str, elapsed: str) -> dict:
    return {
        "title": "🛑 Run aborted",
        "color": statusColor("aborted"),
        "timestamp": _nowIso(),
        "fields": [
            {"name": "Reason", "value": truncate(reason, 512), "inline": False},
            {"name": "Elapsed", "value": elapsed or "—", "inline": True},
        ],
    }


def selfRefEmbed(branch: str, protected: tuple) -> dict:
    return {
        "title": "🧬 Self-referential run (9to5 editing 9to5)",
        "color": statusColor("replanning"),
        "timestamp": _nowIso(),
        "fields": [
            {"name": "Isolation branch", "value": f"`{branch}`", "inline": True},
            {"name": "Protected core files", "value": truncate(", ".join(protected), 1024), "inline": False},
        ],
    }
```

- [ ] **Step 5: Run the REST tests again (verdict test now passes) + import-smoke**

Run: `venv\Scripts\python -m unittest tests.test_discord_rest -v`
Expected: ALL PASS.
Run: `venv\Scripts\python -c "from notifications import discord_bot as d; print(d.formatVerdict('x')); print(d.effortBar('high')); print(d.gateNeededEmbed('plan')['title'])"`
Expected: `❔ UNKNOWN` / `▰▰▰▱▱  High` / `⏳ Approval needed — plan`

- [ ] **Step 6: Commit**

```bash
git add notifications/discord_bot.py
git commit -m "feat(discord): verdict allowlist (no false-green), config-driven effortBar, named milestone builders"
```

---

## Task 5: notifications/work_launcher.py — pure launcher core (+ tests)

**Files:**
- Create: `notifications/work_launcher.py`
- Test: `tests/test_work_launcher.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_work_launcher.py`:

```python
"""Unit tests for the pure /work launcher core (no real subprocess)."""
import subprocess
import unittest
from unittest import mock

import config
from notifications import work_launcher as wl


class TestParseHours(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(wl.parseHours("2"), 2.0)

    def test_suffix_h(self):
        self.assertEqual(wl.parseHours("2h"), 2.0)

    def test_float(self):
        self.assertEqual(wl.parseHours("1.5"), 1.5)

    def test_empty_default(self):
        self.assertEqual(wl.parseHours(""), 1.0)
        self.assertEqual(wl.parseHours(None), 1.0)
        self.assertEqual(wl.parseHours("junk"), 1.0)

    def test_clamp(self):
        self.assertEqual(wl.parseHours("999"), wl.HOURS_MAX)
        self.assertEqual(wl.parseHours("0"), wl.HOURS_MIN)

    def test_nan_inf_rejected(self):
        self.assertEqual(wl.parseHours("inf"), 1.0)
        self.assertEqual(wl.parseHours("nan"), 1.0)


class TestValidate(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(wl.validate(wl.WorkRequest(goal="do x")), [])

    def test_empty_goal(self):
        errs = wl.validate(wl.WorkRequest(goal="   "))
        self.assertTrue(any("goal" in e.lower() for e in errs))

    def test_bad_mode(self):
        errs = wl.validate(wl.WorkRequest(goal="x", mode="turbo"))
        self.assertTrue(any("mode" in e.lower() for e in errs))

    def test_parallel_floor(self):
        errs = wl.validate(wl.WorkRequest(goal="x", parallel=0))
        self.assertTrue(any("parallel" in e.lower() for e in errs))

    def test_bad_workdir(self):
        errs = wl.validate(wl.WorkRequest(goal="x", work_dir="C:/nope/zzz/nonexistent"))
        self.assertTrue(any("work" in e.lower() for e in errs))


class TestBuildArgv(unittest.TestCase):
    def test_core(self):
        argv = wl.buildArgv(wl.WorkRequest(goal="do x", hours=2.0, mode="gated", parallel=2))
        self.assertEqual(argv[0], str(config.VENV_PYTHON))
        self.assertEqual(argv[1], str(config.PROJECT_ROOT / "main.py"))
        self.assertIn("--auto-approve", argv)
        self.assertIn("--goal", argv)
        self.assertIn("do x", argv)
        self.assertIn("gated", argv)

    def test_no_pr_only_when_set(self):
        self.assertNotIn("--no-pr", wl.buildArgv(wl.WorkRequest(goal="x")))
        self.assertIn("--no-pr", wl.buildArgv(wl.WorkRequest(goal="x", no_pr=True)))

    def test_workdir_only_when_set(self):
        self.assertNotIn("--work-dir", wl.buildArgv(wl.WorkRequest(goal="x")))


class TestActiveRun(unittest.TestCase):
    def test_none_when_terminal(self):
        from state.task import TaskState
        st = TaskState.create("g", 1.0)
        st.meta["status"] = "done"
        with mock.patch.object(wl.commands, "resolveTargetTask", return_value=st):
            self.assertIsNone(wl.activeRun())

    def test_returns_when_active(self):
        from state.task import TaskState
        st = TaskState.create("g", 1.0)
        st.meta["status"] = "executing"
        with mock.patch.object(wl.commands, "resolveTargetTask", return_value=st):
            self.assertIs(wl.activeRun(), st)


class TestSpawn(unittest.TestCase):
    def test_spawn_uses_argv(self):
        fake = mock.Mock(pid=4321)
        with mock.patch.object(subprocess, "Popen", return_value=fake) as p, \
                mock.patch("builtins.open", mock.mock_open()):
            pid = wl.spawn(wl.WorkRequest(goal="do x"))
        self.assertEqual(pid, 4321)
        args, kwargs = p.call_args
        self.assertEqual(args[0], wl.buildArgv(wl.WorkRequest(goal="do x")))
        self.assertEqual(kwargs["cwd"], str(config.PROJECT_ROOT))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv\Scripts\python -m unittest tests.test_work_launcher -v`
Expected: FAIL — `No module named 'notifications.work_launcher'`.

- [ ] **Step 3: Implement `notifications/work_launcher.py`**

Create `notifications/work_launcher.py`:

```python
"""Pure launcher core for the Discord /work command. No discord import -> unit-testable.
Builds an argv for main.py and spawns it as a detached child so the gateway stays
responsive and a bot restart never kills an in-flight run.
"""
from __future__ import annotations

import math
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import config
from notifications import commands
from state.task import TaskState

LOG = config.getLogger("work_launcher")

HOURS_MIN: float = 0.1
HOURS_MAX: float = 24.0
MAX_PARALLEL: int = 4
MAX_GOAL_CHARS: int = 6000
VALID_MODES = ("watch", "gated")


@dataclass
class WorkRequest:
    goal: str
    hours: float = 1.0
    mode: str = "watch"
    parallel: int = 1
    work_dir: Optional[str] = None
    no_pr: bool = False


def parseHours(raw) -> float:
    """Tolerant parse ('2', '2h', '1.5'); empty/invalid -> 1.0; clamp to [HOURS_MIN, HOURS_MAX]."""
    if raw is None:
        return 1.0
    if isinstance(raw, (int, float)):
        val = float(raw)
    else:
        s = str(raw).strip().lower().rstrip("h").strip()
        try:
            val = float(s)
        except ValueError:
            return 1.0
    if not math.isfinite(val):
        return 1.0
    return max(HOURS_MIN, min(HOURS_MAX, val))


def validate(req: WorkRequest) -> list[str]:
    errs: list[str] = []
    if not (req.goal or "").strip():
        errs.append("Goal is required.")
    if len((req.goal or "")) > MAX_GOAL_CHARS:
        errs.append(f"Goal too long (>{MAX_GOAL_CHARS} chars).")
    if not (HOURS_MIN <= req.hours <= HOURS_MAX):
        errs.append(f"Hours must be between {HOURS_MIN} and {HOURS_MAX}.")
    if req.mode not in VALID_MODES:
        errs.append(f"Mode must be one of {VALID_MODES}.")
    if not (1 <= req.parallel <= MAX_PARALLEL):
        errs.append(f"Parallel must be between 1 and {MAX_PARALLEL}.")
    if req.work_dir and not Path(req.work_dir).is_dir():
        errs.append(f"work_dir does not exist or is not a directory: {req.work_dir}")
    return errs


def buildArgv(req: WorkRequest) -> list[str]:
    argv = [
        str(config.VENV_PYTHON), str(config.PROJECT_ROOT / "main.py"),
        "--goal", req.goal,
        "--hours", str(req.hours),
        "--auto-approve",
        "--mode", req.mode,
        "--parallel", str(req.parallel),
    ]
    if req.no_pr:
        argv.append("--no-pr")
    if req.work_dir:
        argv += ["--work-dir", str(Path(req.work_dir).resolve())]
    return argv


def activeRun() -> Optional[TaskState]:
    """The latest task iff it's still active (delegates to commands.isRunActive -- one policy)."""
    state = commands.resolveTargetTask()
    return state if commands.isRunActive(state) else None


def newestTaskSince(ts: float) -> Optional[str]:
    """task_id of the newest state file created at/after `ts` (used to confirm a launch)."""
    best_id, best_m = None, ts - 1
    try:
        for f in config.STATE_DIR.glob("*.json"):
            m = f.stat().st_mtime
            if m >= ts - 2.0 and m > best_m:
                best_m, best_id = m, f.stem
    except OSError:
        return None
    return best_id


def spawn(req: WorkRequest) -> int:
    """Spawn main.py as a DETACHED child (survives a bot restart). Returns the child PID."""
    config.LOG_PATH.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    logfile = open(config.LOG_PATH / f"work-{stamp}.log", "a", encoding="utf-8", errors="replace")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        buildArgv(req), cwd=str(config.PROJECT_ROOT),
        stdin=subprocess.DEVNULL, stdout=logfile, stderr=subprocess.STDOUT,
        close_fds=True, creationflags=creationflags,
    )
    LOG.info("Spawned /work run pid=%s mode=%s hours=%s", proc.pid, req.mode, req.hours)
    return proc.pid
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `venv\Scripts\python -m unittest tests.test_work_launcher -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add notifications/work_launcher.py tests/test_work_launcher.py
git commit -m "feat(discord): pure work_launcher (parseHours/validate/buildArgv/activeRun/spawn) + tests"
```

---

## Task 6: command_bot.py — delegate, authorize, defer, `/work` slash + modal + view

**Files:**
- Modify: `notifications/command_bot.py` (full rewrite of handlers + gateway; keep `handleButton` behavior)

- [ ] **Step 1: Replace the module with the delegating + slash-enabled version**

Replace the entire contents of `notifications/command_bot.py` with:

```python
"""Gateway command bot -- rich, interactive Discord control + /work launcher.

Runs as its own long-lived process:  venv\\Scripts\\python -m notifications.command_bot

All '!' grammar, authorization, and task resolution live in notifications.commands (the
single source of truth, shared with the orchestrator poller). This module is the thin
discord.py shell: it authorizes, defers, delegates, and renders. It also registers the
/work slash command (optional params; modal+dropdown onboarding when blank) which spawns
a full run via notifications.work_launcher.
"""
from __future__ import annotations

import time

import config
from control import ControlBus
from notifications import commands, work_launcher
from notifications import discord_bot as discord
from state.task import TaskState

LOG = config.getLogger("command_bot")

MAX_REPLY_CHARS = config.DISCORD_MAX_CONTENT - 100


# ---- pure-ish handlers (delegate to commands.py) ---------------------------
def handleCommand(content: str) -> str:
    """Parse + apply a '!' command against the latest task. '' if not a command."""
    cmd = commands.parseCommand(content)
    if cmd is None:
        return ""
    state = commands.resolveTargetTask()
    if state is None:
        return commands.NO_TASK
    return commands.applyCommand(ControlBus(state.task_id), state, cmd)


def handleButton(custom_id: str) -> str:
    state = commands.resolveTargetTask()
    if state is None:
        return commands.NO_TASK
    bus = ControlBus(state.task_id)
    if custom_id == "sc_abort":
        bus.requestAbort()
        return "🛑 Abort requested — run stops after the current step."
    if custom_id == "sc_skip":
        cur = next((s for s in state.subtasks if s["status"] == "in_progress"), None)
        if cur:
            bus.pushOp({"op": "skip", "subtask_id": cur["subtask_id"]})
            return f"⏭️ Skipping `{cur['subtask_id']}`."
        return "Nothing in progress to skip."
    if custom_id == "sc_answer":
        return "✍️ Type your answer as a normal message; the orchestrator will pick it up."
    return "Unknown action."


def _launchOrError(req: "work_launcher.WorkRequest") -> str:
    """Central launch path shared by every entry: validate -> block-if-active -> spawn."""
    errs = work_launcher.validate(req)
    if errs:
        return "❌ " + "  ".join(errs)
    active = work_launcher.activeRun()
    if active is not None:
        return (f"⛔ A run is already active (`{active.task_id[:8]}` · "
                f"`{active.meta.get('status')}`). Abort it first with `!abort`.")
    t0 = time.time()
    try:
        pid = work_launcher.spawn(req)
    except Exception as e:  # noqa: BLE001
        LOG.exception("spawn failed")
        return f"❌ Launch failed: {e}"
    # Confirm the child actually materialized a task (main.py saves it pre-elaboration).
    task_id = None
    for _ in range(20):
        task_id = work_launcher.newestTaskSince(t0)
        if task_id:
            break
        time.sleep(0.5)
    web = f"http://127.0.0.1:{config.WEB_DASHBOARD_PORT}/"
    if task_id:
        return (f"✅ Launched run `{task_id[:8]}` (pid {pid}) · mode `{req.mode}` · "
                f"{req.hours}h · parallel {req.parallel}\n{web}")
    return (f"✅ Launch started (pid {pid}) · mode `{req.mode}` · {req.hours}h. "
            f"If no dashboard appears shortly, check `logs\\work-*.log`.\n{web}")


def runCommandBot() -> None:  # pragma: no cover -- long-lived gateway process
    import discord as dpy
    from discord import app_commands

    if not config.DISCORD_BOT_TOKEN:
        LOG.error("DISCORD_BOT_TOKEN missing; cannot start command bot")
        return

    intents = dpy.Intents.default()
    intents.message_content = True
    client = dpy.Client(intents=intents)
    tree = app_commands.CommandTree(client)
    _synced = {"done": False}

    # ---------- /work onboarding (modal -> dropdown view) ----------
    class WorkSetupView(dpy.ui.View):
        def __init__(self, owner_id: int, goal: str, hours: float, work_dir: str | None):
            super().__init__(timeout=300)
            self.owner_id = owner_id
            self.req = work_launcher.WorkRequest(goal=goal, hours=hours, work_dir=work_dir or None)

        async def interaction_check(self, interaction: "dpy.Interaction") -> bool:
            if not commands.isAuthorized(interaction.user.id):
                await interaction.response.send_message("Not authorized.", ephemeral=True)
                return False
            return True

        @dpy.ui.select(placeholder="Control mode", options=[
            dpy.SelectOption(label="watch (autonomous + abort)", value="watch", default=True),
            dpy.SelectOption(label="gated (approve plan + PR)", value="gated"),
        ])
        async def _mode(self, interaction, select):  # noqa: ANN001
            self.req.mode = select.values[0]
            await interaction.response.defer()

        @dpy.ui.select(placeholder="Parallelism", options=[
            dpy.SelectOption(label=f"{i} concurrent subtask(s)", value=str(i), default=(i == 1))
            for i in range(1, work_launcher.MAX_PARALLEL + 1)
        ])
        async def _parallel(self, interaction, select):  # noqa: ANN001
            self.req.parallel = int(select.values[0])
            await interaction.response.defer()

        @dpy.ui.select(placeholder="Pull request", options=[
            dpy.SelectOption(label="Create a PR when done", value="pr", default=True),
            dpy.SelectOption(label="Skip PR", value="nopr"),
        ])
        async def _pr(self, interaction, select):  # noqa: ANN001
            self.req.no_pr = (select.values[0] == "nopr")
            await interaction.response.defer()

        @dpy.ui.button(label="Launch", style=dpy.ButtonStyle.success)
        async def _launch(self, interaction, button):  # noqa: ANN001
            await interaction.response.defer(ephemeral=True)
            reply = _launchOrError(self.req)
            for c in self.children:
                c.disabled = True
            await interaction.followup.send(reply[:MAX_REPLY_CHARS], ephemeral=True)
            self.stop()

        @dpy.ui.button(label="Cancel", style=dpy.ButtonStyle.secondary)
        async def _cancel(self, interaction, button):  # noqa: ANN001
            for c in self.children:
                c.disabled = True
            await interaction.response.edit_message(content="Cancelled.", view=self)
            self.stop()

    class WorkModal(dpy.ui.Modal, title="Start a 9TO5 run"):
        goal = dpy.ui.TextInput(label="Goal", style=dpy.TextStyle.paragraph, required=True, max_length=4000)
        hours = dpy.ui.TextInput(label="Hours", default="1", required=False, max_length=6)
        work_dir = dpy.ui.TextInput(label="Working directory (optional)", required=False, max_length=300)

        async def on_submit(self, interaction: "dpy.Interaction") -> None:
            view = WorkSetupView(interaction.user.id, str(self.goal),
                                 work_launcher.parseHours(str(self.hours)), str(self.work_dir) or None)
            await interaction.response.send_message(
                "Set options, then **Launch**:", view=view, ephemeral=True)

    @tree.command(name="work", description="Start a 9TO5 run (blank = guided setup)")
    @app_commands.describe(goal="What to work on (blank opens guided setup)",
                           hours="Time horizon in hours", mode="watch or gated",
                           parallel="Concurrent subtasks", no_pr="Skip the PR", work_dir="Working directory")
    @app_commands.choices(mode=[app_commands.Choice(name="watch", value="watch"),
                                app_commands.Choice(name="gated", value="gated")])
    async def work(interaction: "dpy.Interaction", goal: str | None = None, hours: float | None = None,
                   mode: "app_commands.Choice[str] | None" = None, parallel: int | None = None,
                   no_pr: bool | None = None, work_dir: str | None = None):
        if not commands.isAuthorized(interaction.user.id):
            await interaction.response.send_message("Not authorized to launch runs.", ephemeral=True)
            return
        if not goal:
            await interaction.response.send_modal(WorkModal())
            return
        await interaction.response.defer(ephemeral=True)
        req = work_launcher.WorkRequest(
            goal=goal, hours=work_launcher.parseHours(hours),
            mode=(mode.value if mode else "watch"), parallel=parallel or 1,
            no_pr=bool(no_pr), work_dir=work_dir or None)
        await interaction.followup.send(_launchOrError(req)[:MAX_REPLY_CHARS], ephemeral=True)

    @tree.error
    async def _on_app_error(interaction, error):  # noqa: ANN001  pragma: no cover
        LOG.exception("slash command error: %s", error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send("internal error (see logs)", ephemeral=True)
            else:
                await interaction.response.send_message("internal error (see logs)", ephemeral=True)
        except Exception:  # noqa: BLE001
            pass

    @client.event
    async def on_ready() -> None:
        if not _synced["done"]:
            try:
                if config.DISCORD_GUILD_ID:
                    guild = dpy.Object(id=config.DISCORD_GUILD_ID)
                    tree.copy_global_to(guild=guild)
                    synced = await tree.sync(guild=guild)
                else:
                    synced = await tree.sync()
                _synced["done"] = True
                LOG.info("Command bot online as %s; synced %d slash command(s)", client.user, len(synced))
            except Exception as e:  # noqa: BLE001
                LOG.warning("slash sync failed: %s", e)

    @client.event
    async def on_interaction(interaction: "dpy.Interaction") -> None:
        # app_commands are dispatched by the tree; we only handle component buttons here.
        if interaction.type != dpy.InteractionType.component:
            return
        try:
            await interaction.response.defer(ephemeral=True)
            if not commands.isAuthorized(interaction.user.id):
                await interaction.followup.send("Not authorized.", ephemeral=True)
                return
            reply = handleButton((interaction.data or {}).get("custom_id", ""))
            await interaction.followup.send(reply[:MAX_REPLY_CHARS], ephemeral=True)
        except Exception:  # noqa: BLE001
            LOG.exception("button interaction error")

    @client.event
    async def on_message(message: "dpy.Message") -> None:
        if message.author == client.user or not message.content.strip().startswith("!"):
            return
        if not commands.isAuthorized(message.author.id):
            LOG.info("ignored '!' command from unauthorized user %s", message.author.id)
            return
        if config.DISCORD_CHANNEL_ID and message.channel.id != config.DISCORD_CHANNEL_ID:
            return
        try:
            reply = handleCommand(message.content)
        except Exception:  # noqa: BLE001
            LOG.exception("command error")
            reply = "internal error (see logs)"
        if reply:
            await message.channel.send(reply[:MAX_REPLY_CHARS])

    client.run(config.DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    runCommandBot()
```

- [ ] **Step 2: Import-smoke (gateway can't be unit-tested without a token)**

Run: `venv\Scripts\python -c "from notifications import command_bot; print('ok', command_bot.MAX_REPLY_CHARS); print(command_bot.handleCommand('!help')[:20])"`
Expected: `ok 1900` then the start of the help text (works because `handleCommand` is pure and delegates to `commands.py`).

- [ ] **Step 3: Commit**

```bash
git add notifications/command_bot.py
git commit -m "feat(discord): /work slash + modal + dropdown view; authorize/defer/delegate; sync-once + tree.on_error"
```

---

## Task 7: orchestrator.py — seed cursor, authorize poller, named embeds, unpin

**Files:**
- Modify: `orchestrator.py` (imports ~22-35; `_translateDiscord` ~325-359; inline embeds at ~393-397, 615-623, 776-783, 894-897; `runFull` start ~803-808 and `finally` ~920-922)

- [ ] **Step 1: Import commands; delete the local color constants**

In `orchestrator.py`, add to the imports:

```python
from notifications import commands
```

Delete the three module constants `_YELLOW = 0xF1C40F`, `_ORANGE = 0xE67E22`, `_RED = 0xE74C3C` (lines ~33-35).

- [ ] **Step 2: Rewrite `_translateDiscord` to authorize + delegate**

Replace the whole `_translateDiscord` method body with:

```python
    def _translateDiscord(self, bus: ControlBus, state: TaskState) -> None:
        msgs, latest = discord.fetchMessagesAfter(bus.getSeen())
        if latest != bus.getSeen():
            bus.setSeen(latest)
        for m in msgs:
            author_id = m.get("author_id") or None
            cmd = commands.decide(int(author_id) if author_id else None,
                                  m.get("author_is_bot", False), m.get("content", ""))
            if cmd:
                commands.applyCommand(bus, state, cmd)
```

(Note the new `state` parameter.) Then update **every** `self._translateDiscord(bus)` call site to `self._translateDiscord(bus, state)`. There are several: inside `_checkControl` (the initial call, the pause-wait loop, and the gate-wait loop) and inside `_executeSubtask` (the post-attempt call and the pause-wait loop). Both methods already have `state` in scope. Verify none remain with: `grep -n "_translateDiscord(bus)" orchestrator.py` → expect no matches.

- [ ] **Step 3: Seed the cursor once at run start**

In `runFull`, immediately after `bus = ControlBus(state.task_id)` and the `if not resume: bus.clear()` block, add:

```python
        if bus.getSeen() is None:   # seed so a stale '!abort' from a prior run is never replayed
            try:
                bus.setSeen(discord.baselineLatestId())
            except Exception:  # noqa: BLE001
                pass
```

- [ ] **Step 4: Pass the state lock to the dashboard at start**

In `runFull`, change `dashboard.start(state, "resuming" if resume else "starting")` to:

```python
        dashboard.start(state, "resuming" if resume else "starting", state_lock=self._state_lock)
```

- [ ] **Step 5: Replace the four inline embeds with named builders**

5a. Gate-needed embed in `_checkControl` (the `discord.sendEmbed({...})` for `f"Approval needed: {gate}"`): replace with

```python
            discord.sendEmbed(discord.gateNeededEmbed(gate), content=discord.humanPing())
```

5b. Subtask-failed embed in `_executeSubtask` (the `discord.sendEmbed({"title": "Subtask failed verification", ...})`): replace with

```python
            discord.sendEmbed(discord.subtaskFailedEmbed(sid, subtask["title"], vresult, attempt))
```

5c. Self-ref embed in `_prepareSelfReferential` (the `discord.sendEmbed({"title": "🧬 Self-referential run...", ...})`): replace with

```python
        discord.sendEmbed(discord.selfRefEmbed(branch, config.CORE_PROTECTED_FILES),
                          content=discord.humanPing())
```

5d. Aborted embed in the `except (AbortRun, KeyboardInterrupt)` handler (the `discord.sendEmbed({"title": "Run aborted", ...})`): replace with

```python
            discord.sendEmbed(discord.abortedEmbed(reason, _fmtElapsed(elapsed)),
                              content=discord.humanPing())
```

- [ ] **Step 6: Unpin the dashboard in `finally`**

In `runFull`'s `finally:` block, add before/after `stopWebDashboard()`:

```python
            try:
                dashboard.unpin()
            except Exception:  # noqa: BLE001
                LOG.warning("dashboard unpin failed", exc_info=True)
```

- [ ] **Step 7: Verify it imports + compiles**

Run: `venv\Scripts\python -c "import orchestrator; print('ok')"`
Expected: `ok` (no NameError for `_RED`/`_YELLOW`/`_ORANGE`).
Run: `venv\Scripts\python -m unittest tests.test_commands tests.test_discord_rest tests.test_work_launcher -v`
Expected: ALL PASS (no regressions).

- [ ] **Step 8: Commit**

```bash
git add orchestrator.py
git commit -m "feat(discord): seed poll cursor once; authorize+delegate in-run poller; named milestone embeds; dashboard.unpin() in finally"
```

---

## Task 8: dashboard.py — deadlock-free snapshot, recover-once, unpin, polish

**Files:**
- Modify: `notifications/dashboard.py`

- [ ] **Step 1: Add locks + recreate guard + state-lock ref**

In `DiscordDashboard.__init__`, add after `self._lock = threading.Lock()`:

```python
        self._send_lock = threading.Lock()    # serialize network PATCH/POST across workers
        self._state_lock = None                # set by start(); used to snapshot TaskState safely
        self._recreated = False                # at most one 404 recovery (no pin spam)
```

Also `import commands` lazily where needed (footer); add to the top imports:

```python
from notifications import commands
```

- [ ] **Step 2: Snapshot TaskState safely inside `_embed`**

At the very top of `_embed`, replace the direct reads with a locked snapshot, then compute everything from the local copies:

```python
    def _embed(self, state: TaskState, phase: str) -> dict:
        lock = self._state_lock
        if lock:
            lock.acquire()
        try:
            m = dict(state.meta)
            subtasks = [dict(s) for s in state.subtasks]
            notifs = list(state.data.get("notifications", []))
            advs = len(state.data.get("adversary_reviews", []))
        finally:
            if lock:
                lock.release()
        done = sum(1 for s in subtasks if s["status"] == "done")
        total = sum(1 for s in subtasks if s["status"] != "removed") or 1
        replans = sum(1 for n in notifs if n.get("kind") == "replan")

        current = next((s for s in subtasks if s["status"] == "in_progress"), None)
        if current is None:
            current = next((s for s in subtasks if s["status"] == "pending"), None)
        cur_txt = f"`{current['subtask_id']}` {current['title']}" if current else "—"

        last_v = None
        for s in subtasks:
            if s.get("verify_result"):
                last_v = (s["subtask_id"], s["verify_result"])
        if last_v:
            sid, vr = last_v
            mark = "✅" if vr.get("passed") else "❌"
            verify_txt = f"{mark} `{sid}` — `{str(vr.get('cmd') or vr.get('expect'))[:70]}`"
        else:
            verify_txt = "—"
```

Then in the same method, update the `fields`/footer to use the local `m`, `done`, `total`, `replans`, `advs`, drop the redundant Status field + the `L3` placeholder, merge Effort onto the metrics row, and derive the footer help from the registry. Replace the `return {...}` with:

```python
        emoji = _PHASE_EMOJI.get(phase, "🛰")
        paused = m.get("status") == "paused"
        hint = "!resume" if paused else commands.footerHelp()
        return {
            "title": f"{emoji} 9TO5 · {phase}",
            "color": discord.statusColor(m["status"]),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "description": (
                f"**{m['goal_raw'][:240]}**\n"
                f"{discord.progressBar(done, total)}\n"
                f"{discord.subtaskTracker(subtasks)}"
            ),
            "fields": [
                {"name": "Model", "value": f"`{self.model}`", "inline": True},
                {"name": "Mode", "value": f"`{m.get('control_mode', 'watch')}`", "inline": True},
                {"name": "Elapsed", "value": self._elapsed(m.get("started_at")), "inline": True},
                {"name": "🔁 Replans", "value": str(replans), "inline": True},
                {"name": "⚔️ Adversary", "value": str(advs), "inline": True},
                {"name": "Effort", "value": discord.effortBar(self.effort), "inline": True},
                {"name": "Current subtask", "value": cur_txt[:1000], "inline": False},
                {"name": "Last verify", "value": verify_txt, "inline": False},
                {"name": "Recent events", "value": ("\n".join(self._eventsSnapshot()) or "—")[:1000], "inline": False},
            ],
            "footer": {"text": f"task {state.task_id[:8]} · web :{config.WEB_DASHBOARD_PORT} · {hint}"},
        }
```

- [ ] **Step 3: Use tz-aware event timestamps**

In `event`, change `datetime.now().strftime(...)` to `datetime.now().astimezone().strftime('%H:%M:%S')`.

- [ ] **Step 4: Accept the state lock in `start`; serialize sends; recover-once in `update`**

Replace `start` and `update` with:

```python
    def start(self, state: TaskState, phase: str = "starting", state_lock=None) -> None:
        if not config.DISCORD_DASHBOARD:
            return
        self._state_lock = state_lock
        self.event(f"run started · mode `{state.meta.get('control_mode', 'watch')}`")
        embed = self._embed(state, phase)
        with self._send_lock:
            self.message_id = discord.createMessage(embed)
            if self.message_id:
                discord.pinMessage(self.message_id)
                LOG.info("Dashboard message %s created + pinned", self.message_id)

    def update(self, state: TaskState, phase: str, note: Optional[str] = None,
               effort: Optional[str] = None, model: Optional[str] = None) -> None:
        if not config.DISCORD_DASHBOARD:
            return
        with self._lock:
            if effort:
                self.effort = effort
            if model:
                self.model = model
        if note:
            self.event(note)
        embed = self._embed(state, phase)
        with self._send_lock:
            if self.message_id:
                ok = discord.editMessage(self.message_id, embed)
                if not ok and not self._recreated:   # dashboard likely deleted -> recreate ONCE
                    self._recreated = True
                    self.message_id = discord.createMessage(embed)
                    if self.message_id:
                        discord.pinMessage(self.message_id)
            else:
                self.message_id = discord.createMessage(embed)
                if self.message_id:
                    discord.pinMessage(self.message_id)
```

- [ ] **Step 5: Add `unpin`**

Append to the class:

```python
    def unpin(self) -> None:
        """Remove the pinned dashboard when the run ends (idempotent; never raises)."""
        if not config.DISCORD_DASHBOARD or not self.message_id:
            return
        try:
            discord.unpinMessage(self.message_id)
            LOG.info("Dashboard message %s unpinned", self.message_id)
        except Exception:  # noqa: BLE001
            LOG.warning("dashboard unpin failed", exc_info=True)
```

- [ ] **Step 6: Verify import + a fake-render smoke (no network)**

Run:
```
venv\Scripts\python -c "import config; config.DISCORD_DASHBOARD=False; from notifications.dashboard import DiscordDashboard; from state.task import TaskState; d=DiscordDashboard(); s=TaskState.create('g',1.0); print(d._embed(s,'executing')['title']); d.unpin(); print('ok')"
```
Expected: `🛰 9TO5 · executing` then `ok`.

- [ ] **Step 7: Commit**

```bash
git add notifications/dashboard.py
git commit -m "feat(discord): deadlock-free dashboard snapshot + serialized edits, recover-once, unpin(), density/footer/tz polish"
```

---

## Task 9: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Run the whole test suite**

Run: `venv\Scripts\python -m unittest discover -s tests -v`
Expected: ALL tests PASS (test_commands, test_discord_rest, test_work_launcher).

- [ ] **Step 2: Import-smoke every touched module**

Run:
```
venv\Scripts\python -c "import config, orchestrator; from notifications import commands, discord_bot, dashboard, command_bot, work_launcher; print('all import ok')"
```
Expected: `all import ok`.

- [ ] **Step 3: Health check (existing harness)**

Run: `venv\Scripts\python main.py --health`
Expected: exits 0 (or the same result as before this change — no new failures).

- [ ] **Step 4: Manual live smoke (documented; requires a configured channel + owner)**

Do these in the real Discord channel and tick when each passes:
- Start `venv\Scripts\python -m notifications.command_bot`; confirm the log shows `synced N slash command(s)`.
- `/work goal:"create C:\9to5\test-run\hello.py that prints hi" hours:0.2 mode:watch` → ephemeral `✅ Launched run <id8>`; a pinned dashboard appears.
- `/work` (no args) → modal opens → submit → dropdown view → **Launch** → run starts.
- While a run is active, `/work goal:"x"` → `⛔ A run is already active …`.
- From a **non-owner** account, `!abort` → silently ignored (run continues; bot logs "ignored").
- When the run reaches complete/aborted → the pinned dashboard is **unpinned** automatically.

- [ ] **Step 5: Final commit (if any doc/checkbox updates)**

```bash
git add -A
git commit -m "test(discord): full unittest suite green + live smoke checklist for /work + unpin"
```

---

## Self-review notes (author)

- **Spec coverage:** every Addendum-v2 item maps to a task — commands.py spine (T2), `_request`/clamp/unpin/mentions/verdict/author_id/baseline (T3–T4), work_launcher (T5), command_bot auth/defer/`/work` (T6), orchestrator cursor-seed/poller/embeds/unpin (T7), dashboard locking/recover/unpin/polish (T8), config constants (T1). Cut items (embeds.py split, BROADCAST_SEVERE, paging, EFFORT_META rebuild) are intentionally absent. webdash/verifier are out of scope per spec.
- **Risk-fixes verified in code:** control-poll `fetchMessagesAfter(retries=0)`; 401-only `_DISABLED`; cursor seed only `if bus.getSeen() is None`; dashboard snapshots under the passed lock then releases before the `_send_lock` network call (no AB/BA); `!status`/`!plan` returned as text; clamp shrinks largest value (keeps dashboard tail rows); `editMessage` sets `allowed_mentions` only when content is truthy.
- **Type consistency:** `WorkRequest`, `Command`, `parseHours`, `isRunActive`, `decide`, `applyCommand`, `unpinMessage`, `baselineLatestId`, `_clampEmbed`, `truncate` names are used identically across tasks and tests.
