# Discord Bot Elevation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Elevate the 9TO5 Discord bot to a state-of-the-art run-control surface: a full slash-command suite with autocomplete, a persistent interactive control panel, a design system + branding + live presence, observability (`/ping /diagnostics /metrics` + audit log), safety (cooldowns/confirm/pagination/perms), and multi-run lifecycle (`/runs /run /resume`).

**Architecture:** New focused modules layer on the shipped spine — `branding.py` (design system + all rich embeds, pure), `audit.py`/`metrics.py` (pure, file-backed), `views.py` (discord.py persistent views + confirm + paginator + work modal), `slash.py` (all slash commands, thin over the spine). `command_bot.py` becomes a slim gateway. Slash-first; `!` kept as an alias via the same `commands.py` spine. File-backed, zero new deps.

**Tech Stack:** Python 3.11 stdlib (`unittest`, `subprocess`, `json`, `asyncio`), `requests`, `discord.py` 2.7.1 (`app_commands`, `ui.View`/`Modal`, persistent views). Tests: `venv\Scripts\python -m unittest`.

**Spec:** `docs/superpowers/specs/2026-06-22-discord-bot-elevation-design.md`. **Branch:** `feat/discord-work-hardening` (continue).

---

## File map

| File | New? | Responsibility |
|------|------|----------------|
| `config.py` | modify | VERSION, BRAND_COLOR, BRAND_ICON_URL, COOLDOWN_RATE/PER, PRESENCE_INTERVAL, AUDIT_LOG_PATH/AUDIT_MAX_BYTES |
| `notifications/audit.py` | **new** | file-backed audit log: `record`/`recent` + rotation |
| `notifications/metrics.py` | **new** | aggregate `state/tasks/*.json` → metrics dict |
| `state/task.py` | modify | `listRecent(n)` summaries |
| `health.py` | modify | `collectHealth() -> list[dict]`; `runHealthChecks()` prints from it |
| `notifications/work_launcher.py` | modify | `_spawnArgv`, `spawnResume`, `buildResumeArgv`, `taskExists`, `launchOrError`, `resumeOrError` |
| `notifications/branding.py` | **new** | design system + all rich embeds + `controlPanelRow` + `CONTROL_PANEL_IDS` |
| `notifications/views.py` | **new** | `ControlPanelView`/`BlockedView` (persistent), `ConfirmView`, `Paginator`, `WorkModal`/`WorkSetupView` |
| `notifications/slash.py` | **new** | `registerSlashCommands(tree, client, started_at)` |
| `notifications/command_bot.py` | modify | slim gateway: sync-once, add_view, presence loop, `!` legacy, tree.error; remove on_interaction + old `/work` |
| `notifications/dashboard.py` | modify | attach `controlPanelRow()` components to the pinned embed |
| `orchestrator.py` | modify | poller records audit on mutating commands |
| `tests/test_audit.py`, `test_metrics.py`, `test_task_listrecent.py`, `test_health_collect.py`, `test_branding.py` | **new** | unit tests |
| `tests/test_work_launcher.py` | modify | resume + launch/resume glue tests |

---

## Task 1: config.py — branding/UX/audit constants

**Files:** Modify `config.py`

- [ ] **Step 1: Add the constants**

In `config.py`, after the `# --- Discord ---` block (after the new `DISCORD_RETRY_MAX` line from the prior cycle), add:

```python
# --- Bot identity / branding ---
VERSION: str = "1.0.0"
BRAND_COLOR: int = 0x5865F2                      # 9TO5 brand (Discord blurple)
BRAND_ICON_URL: str = os.getenv("BRAND_ICON_URL", "")

# --- Bot UX behaviour ---
COOLDOWN_RATE: int = 3                            # max mutating-command uses ...
COOLDOWN_PER: float = 10.0                        # ... per this many seconds, per user
PRESENCE_INTERVAL: int = 30                       # seconds between bot presence refreshes

# --- Audit log (who issued which control command) ---
AUDIT_LOG_PATH: Path = PROJECT_ROOT / "state" / "audit.jsonl"
AUDIT_MAX_BYTES: int = 1_000_000                  # rotate audit.jsonl past ~1 MB
```

- [ ] **Step 2: Verify**

Run: `venv\Scripts\python -c "import config; print(config.VERSION, hex(config.BRAND_COLOR), config.COOLDOWN_RATE, config.AUDIT_LOG_PATH.name)"`
Expected: `1.0.0 0x5865f2 3 audit.jsonl`

- [ ] **Step 3: Commit**

```bash
git add config.py
git commit -m "config: bot branding/UX/audit constants (VERSION, BRAND_COLOR, cooldowns, presence, audit)"
```

---

## Task 2: notifications/audit.py — file-backed audit log (+ tests)

**Files:** Create `notifications/audit.py`; Create `tests/test_audit.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_audit.py`:

```python
"""Unit tests for the file-backed audit log."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from notifications import audit


class TestAudit(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "audit.jsonl"

    def tearDown(self):
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def test_record_and_recent(self):
        with mock.patch.object(config, "AUDIT_LOG_PATH", self.path):
            audit.record(777, "abort", "task-1")
            audit.record(777, "pause", "task-1", "button")
            entries = audit.recent(10)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[-1]["action"], "pause")
        self.assertEqual(entries[-1]["detail"], "button")
        self.assertEqual(entries[0]["user_id"], "777")

    def test_recent_empty_when_no_file(self):
        with mock.patch.object(config, "AUDIT_LOG_PATH", self.dir / "nope.jsonl"):
            self.assertEqual(audit.recent(), [])

    def test_rotation(self):
        with mock.patch.object(config, "AUDIT_LOG_PATH", self.path), \
                mock.patch.object(config, "AUDIT_MAX_BYTES", 50):
            for i in range(30):
                audit.record(1, f"act{i}", "t")
            self.assertTrue((self.dir / "audit.jsonl.1").exists())
            self.assertTrue(audit.recent(5))   # still works after rotation


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run, expect fail** — `venv\Scripts\python -m unittest tests.test_audit -v` → `ModuleNotFoundError: notifications.audit`.

- [ ] **Step 3: Implement** — `notifications/audit.py`:

```python
"""File-backed audit log: who issued which control command. JSON-lines at
config.AUDIT_LOG_PATH, size-rotated. Best-effort -- never raises into a command."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

import config

LOG = config.getLogger("audit")


def record(user_id, action: str, task_id: Optional[str] = None, detail: str = "") -> None:
    """Append one audit entry. Swallows all errors (audit must never break a command)."""
    try:
        path = config.AUDIT_LOG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > config.AUDIT_MAX_BYTES:
            path.replace(path.with_name(path.name + ".1"))   # rotate (overwrites prior .1)
        entry = {
            "at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "user_id": str(user_id) if user_id is not None else None,
            "action": action,
            "task_id": task_id,
            "detail": detail,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001
        LOG.warning("audit record failed: %s", e)


def recent(n: int = 20) -> list[dict]:
    """The last n audit entries (oldest-first within the window). [] on any error."""
    try:
        path = config.AUDIT_LOG_PATH
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        out: list[dict] = []
        for ln in lines[-n:]:
            try:
                out.append(json.loads(ln))
            except Exception:  # noqa: BLE001
                continue
        return out
    except Exception as e:  # noqa: BLE001
        LOG.warning("audit recent failed: %s", e)
        return []
```

- [ ] **Step 4: Run, expect pass** — `venv\Scripts\python -m unittest tests.test_audit -v` → all pass.

- [ ] **Step 5: Commit**

```bash
git add notifications/audit.py tests/test_audit.py
git commit -m "feat(discord): file-backed audit log (record/recent + rotation) + tests"
```

---

## Task 3: notifications/metrics.py — run metrics aggregation (+ tests)

**Files:** Create `notifications/metrics.py`; Create `tests/test_metrics.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_metrics.py`:

```python
"""Unit tests for run-metrics aggregation."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from notifications import metrics


def _task(status, subs):
    return {"meta": {"status": status, "started_at": "2026-06-22T09:00:00+00:00"},
            "plan": {"subtasks": subs}}


class TestMetrics(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def _write(self, name, obj):
        (self.dir / name).write_text(json.dumps(obj), encoding="utf-8")

    def test_aggregation(self):
        self._write("a.json", _task("done", [
            {"status": "done", "verify_result": {"passed": True},
             "completed_at": "2026-06-22T09:10:00+00:00"}]))
        self._write("b.json", _task("failed", [
            {"status": "failed", "verify_result": {"passed": False},
             "completed_at": "2026-06-22T09:05:00+00:00"}]))
        self._write("c.json", _task("executing", [{"status": "pending"}]))
        with mock.patch.object(config, "STATE_DIR", self.dir):
            m = metrics.compute()
        self.assertEqual(m["total_runs"], 3)
        self.assertEqual(m["terminal_runs"], 2)
        self.assertEqual(m["success_runs"], 1)
        self.assertEqual(m["success_rate"], 0.5)
        self.assertEqual(m["subtasks_total"], 3)
        self.assertEqual(m["subtasks_passed"], 1)
        self.assertIsNotNone(m["avg_duration_seconds"])

    def test_empty(self):
        with mock.patch.object(config, "STATE_DIR", self.dir):
            m = metrics.compute()
        self.assertEqual(m["total_runs"], 0)
        self.assertIsNone(m["success_rate"])
        self.assertIsNone(m["avg_duration_seconds"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run, expect fail** — `venv\Scripts\python -m unittest tests.test_metrics -v`.

- [ ] **Step 3: Implement** — `notifications/metrics.py`:

```python
"""Aggregate run metrics from the task-state JSON store. Pure (reads files only)."""
from __future__ import annotations

import json
from datetime import datetime

import config
from state.task import TaskState

LOG = config.getLogger("metrics")
_TERMINAL = TaskState._TERMINAL
_SUCCESS = ("done", "complete")


def _duration(meta: dict, subs: list) -> "float | None":
    try:
        start = datetime.fromisoformat(meta["started_at"])
    except Exception:  # noqa: BLE001
        return None
    ends = []
    for s in subs:
        c = s.get("completed_at")
        if c:
            try:
                ends.append(datetime.fromisoformat(c))
            except Exception:  # noqa: BLE001
                pass
    if not ends:
        return None
    return max(0.0, (max(ends) - start).total_seconds())


def compute() -> dict:
    total = 0
    by_status: dict[str, int] = {}
    durations: list[float] = []
    subtasks_total = subtasks_passed = 0
    try:
        files = list(config.STATE_DIR.glob("*.json"))
    except Exception:  # noqa: BLE001
        files = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        meta = data.get("meta", {})
        status = meta.get("status", "unknown")
        total += 1
        by_status[status] = by_status.get(status, 0) + 1
        subs = (data.get("plan", {}) or {}).get("subtasks", []) or []
        subtasks_total += sum(1 for s in subs if s.get("status") != "removed")
        subtasks_passed += sum(1 for s in subs if (s.get("verify_result") or {}).get("passed"))
        dur = _duration(meta, subs)
        if dur is not None:
            durations.append(dur)
    terminal = sum(v for k, v in by_status.items() if k in _TERMINAL)
    success = sum(v for k, v in by_status.items() if k in _SUCCESS)
    return {
        "total_runs": total,
        "by_status": by_status,
        "terminal_runs": terminal,
        "success_runs": success,
        "success_rate": round(success / terminal, 3) if terminal else None,
        "avg_duration_seconds": round(sum(durations) / len(durations), 1) if durations else None,
        "subtasks_total": subtasks_total,
        "subtasks_passed": subtasks_passed,
    }
```

- [ ] **Step 4: Run, expect pass.** **Step 5: Commit**

```bash
git add notifications/metrics.py tests/test_metrics.py
git commit -m "feat(discord): run-metrics aggregation over task store + tests"
```

---

## Task 4: state/task.py — `listRecent` (+ tests)

**Files:** Modify `state/task.py`; Create `tests/test_task_listrecent.py`

- [ ] **Step 1: Write the failing test** — `tests/test_task_listrecent.py`:

```python
"""Unit tests for TaskState.listRecent."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from state.task import TaskState


class TestListRecent(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def _w(self, name, tid, status, started, subs):
        (self.dir / name).write_text(json.dumps({
            "task_id": tid,
            "meta": {"status": status, "goal_raw": "goal " + tid, "started_at": started},
            "plan": {"subtasks": subs}}), encoding="utf-8")

    def test_sorted_desc_with_progress(self):
        self._w("a.json", "aaa", "done", "2026-06-22T08:00:00+00:00", [{"status": "done"}])
        self._w("b.json", "bbb", "executing", "2026-06-22T10:00:00+00:00",
                 [{"status": "done"}, {"status": "pending"}])
        with mock.patch.object(config, "STATE_DIR", self.dir):
            rec = TaskState.listRecent(5)
        self.assertEqual(len(rec), 2)
        self.assertEqual(rec[0]["task_id"], "bbb")          # most recent first
        self.assertEqual((rec[0]["done"], rec[0]["total"]), (1, 2))
        self.assertEqual(rec[0]["status"], "executing")

    def test_limit(self):
        for i in range(5):
            self._w(f"{i}.json", f"t{i}", "done", f"2026-06-22T0{i}:00:00+00:00", [])
        with mock.patch.object(config, "STATE_DIR", self.dir):
            self.assertEqual(len(TaskState.listRecent(3)), 3)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run, expect fail** (`AttributeError: ... has no attribute 'listRecent'`).

- [ ] **Step 3: Implement** — add this classmethod to `TaskState` in `state/task.py`, right after the existing `loadLatest` classmethod:

```python
    @classmethod
    def listRecent(cls, n: int = 10) -> list[dict[str, Any]]:
        """Lightweight summaries of recent tasks, newest first. Reads the JSON store directly."""
        out: list[dict[str, Any]] = []
        for f in config.STATE_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            meta = data.get("meta", {})
            subs = (data.get("plan", {}) or {}).get("subtasks", []) or []
            done = sum(1 for s in subs if s.get("status") == "done")
            total = sum(1 for s in subs if s.get("status") != "removed")
            out.append({
                "task_id": data.get("task_id", f.stem),
                "status": meta.get("status", "unknown"),
                "goal": meta.get("goal_raw", ""),
                "done": done,
                "total": total,
                "started_at": meta.get("started_at", ""),
            })
        out.sort(key=lambda d: d["started_at"], reverse=True)
        return out[:n]
```

- [ ] **Step 4: Run, expect pass.** **Step 5: Commit**

```bash
git add state/task.py tests/test_task_listrecent.py
git commit -m "feat(discord): TaskState.listRecent summaries for /runs + tests"
```

---

## Task 5: health.py — `collectHealth()` refactor (+ tests)

**Files:** Modify `health.py`; Create `tests/test_health_collect.py`

- [ ] **Step 1: Write the failing test** — `tests/test_health_collect.py`:

```python
"""Unit tests for health.collectHealth (structured results)."""
import unittest
from unittest import mock

import health


class TestCollectHealth(unittest.TestCase):
    def test_shape(self):
        fake = [("x", lambda: (True, "ok", "")), ("y", lambda: (False, "bad", "fixit"))]
        with mock.patch.object(health, "CHECKS", fake):
            checks = health.collectHealth()
        self.assertEqual(len(checks), 2)
        for c in checks:
            self.assertEqual(set(c), {"name", "ok", "detail", "fix"})
            self.assertIsInstance(c["ok"], bool)
        self.assertFalse(checks[1]["ok"])
        self.assertEqual(checks[1]["fix"], "fixit")

    def test_check_exception_captured(self):
        def boom():
            raise RuntimeError("nope")
        with mock.patch.object(health, "CHECKS", [("z", boom)]):
            checks = health.collectHealth()
        self.assertFalse(checks[0]["ok"])
        self.assertIn("errored", checks[0]["detail"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run, expect fail** (`AttributeError: collectHealth`).

- [ ] **Step 3: Implement** — in `health.py`, REPLACE `runHealthChecks` with these two functions:

```python
def collectHealth() -> list[dict]:
    """Run every check and return structured results (used by the bot's /diagnostics)."""
    config.ensureDirs()
    results: list[dict] = []
    for name, fn in CHECKS:
        try:
            ok, detail, fix = fn()
        except Exception as e:  # noqa: BLE001
            ok, detail, fix = False, f"check errored: {e}", "see traceback"
        results.append({"name": name, "ok": bool(ok), "detail": detail, "fix": fix})
    return results


def runHealthChecks() -> bool:
    checks = collectHealth()
    print(f"\n  9to5 /health  —  {len(checks)} checks\n  " + "=" * 52)
    all_ok = True
    for c in checks:
        all_ok = all_ok and c["ok"]
        tag = f"{GREEN}PASS{RST}" if c["ok"] else f"{RED}FAIL{RST}"
        print(f"  [{tag}] {c['name']:30s} {c['detail']}")
        if not c["ok"] and c["fix"]:
            print(f"         {YEL}fix:{RST} {c['fix']}")
    print("  " + "=" * 52)
    print(f"  {'ALL SYSTEMS GO' if all_ok else 'NOT READY — see fixes above'}\n")
    return all_ok
```

- [ ] **Step 4: Run, expect pass** — `venv\Scripts\python -m unittest tests.test_health_collect -v`. Also sanity: `venv\Scripts\python -c "import health; print(callable(health.collectHealth))"` → `True`.

- [ ] **Step 5: Commit**

```bash
git add health.py tests/test_health_collect.py
git commit -m "feat(discord): health.collectHealth structured results for /diagnostics + tests"
```

---

## Task 6: work_launcher.py — resume + launch/resume glue (+ tests)

**Files:** Modify `notifications/work_launcher.py`; Modify `tests/test_work_launcher.py`

- [ ] **Step 1: Add the failing tests** — append these classes to `tests/test_work_launcher.py` (before the `if __name__` line):

```python
class TestResume(unittest.TestCase):
    def test_build_resume_argv(self):
        argv = wl.buildResumeArgv("abc-123")
        self.assertEqual(argv[0], str(config.VENV_PYTHON))
        self.assertEqual(argv[1], str(config.PROJECT_ROOT / "main.py"))
        self.assertIn("--resume", argv)
        self.assertIn("abc-123", argv)

    def test_task_exists(self):
        import tempfile
        from pathlib import Path
        d = Path(tempfile.mkdtemp())
        (d / "tid.json").write_text("{}", encoding="utf-8")
        with mock.patch.object(config, "STATE_DIR", d):
            self.assertTrue(wl.taskExists("tid"))
            self.assertFalse(wl.taskExists("nope"))

    def test_spawn_resume_uses_argv(self):
        fake = mock.Mock(pid=99)
        with mock.patch.object(subprocess, "Popen", return_value=fake) as p, \
                mock.patch("builtins.open", mock.mock_open()):
            pid = wl.spawnResume("abc-123")
        self.assertEqual(pid, 99)
        self.assertEqual(p.call_args.args[0], wl.buildResumeArgv("abc-123"))


class TestLaunchGlue(unittest.TestCase):
    def test_validate_errors(self):
        self.assertIn("❌", wl.launchOrError(wl.WorkRequest(goal="")))

    def test_blocks_when_active(self):
        from state.task import TaskState
        st = TaskState.create("g", 1.0)
        st.meta["status"] = "executing"
        with mock.patch.object(wl, "activeRun", return_value=st):
            self.assertIn("already active", wl.launchOrError(wl.WorkRequest(goal="x")))

    def test_launch_confirms(self):
        with mock.patch.object(wl, "activeRun", return_value=None), \
                mock.patch.object(wl, "spawn", return_value=123), \
                mock.patch.object(wl, "newestTaskSince", return_value="abcdef12"):
            out = wl.launchOrError(wl.WorkRequest(goal="x"))
        self.assertIn("Launched", out)
        self.assertIn("abcdef12", out)

    def test_resume_no_task(self):
        with mock.patch.object(wl, "taskExists", return_value=False):
            self.assertIn("No such task", wl.resumeOrError("nope"))

    def test_resume_blocks_when_active(self):
        from state.task import TaskState
        st = TaskState.create("g", 1.0)
        st.meta["status"] = "executing"
        with mock.patch.object(wl, "taskExists", return_value=True), \
                mock.patch.object(wl, "activeRun", return_value=st):
            self.assertIn("already active", wl.resumeOrError("abc"))

    def test_resume_spawns(self):
        with mock.patch.object(wl, "taskExists", return_value=True), \
                mock.patch.object(wl, "activeRun", return_value=None), \
                mock.patch.object(wl, "spawnResume", return_value=5):
            self.assertIn("Resuming", wl.resumeOrError("abc"))
```

- [ ] **Step 2: Run, expect fail** (`AttributeError` for `buildResumeArgv`/`launchOrError`/etc.).

- [ ] **Step 3: Implement** — in `notifications/work_launcher.py`: add `import time` to the imports, then REPLACE the existing `spawn` function with the following block (it factors out `_spawnArgv` and adds resume + glue):

```python
def _spawnArgv(argv: list[str], tag: str) -> int:
    """Spawn argv as a DETACHED child (survives a bot restart). Returns the child PID."""
    config.LOG_PATH.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    logfile = open(config.LOG_PATH / f"{tag}-{stamp}.log", "a", encoding="utf-8", errors="replace")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        argv, cwd=str(config.PROJECT_ROOT),
        stdin=subprocess.DEVNULL, stdout=logfile, stderr=subprocess.STDOUT,
        close_fds=True, creationflags=creationflags,
    )
    logfile.close()   # child keeps its own duplicated handle; release the parent's copy
    LOG.info("Spawned %s pid=%s", tag, proc.pid)
    return proc.pid


def spawn(req: WorkRequest) -> int:
    return _spawnArgv(buildArgv(req), "work")


def buildResumeArgv(task_id: str) -> list[str]:
    return [str(config.VENV_PYTHON), str(config.PROJECT_ROOT / "main.py"), "--resume", task_id]


def taskExists(task_id: str) -> bool:
    return (config.STATE_DIR / f"{task_id}.json").exists()


def spawnResume(task_id: str) -> int:
    return _spawnArgv(buildResumeArgv(task_id), "resume")


def launchOrError(req: WorkRequest) -> str:
    """Validate -> block-if-active -> spawn -> confirm. Returns the user-facing message.
    BLOCKING (Popen + up to ~10s poll); async callers must run via asyncio.to_thread."""
    errs = validate(req)
    if errs:
        return "❌ " + "  ".join(errs)
    active = activeRun()
    if active is not None:
        return (f"⛔ A run is already active (`{active.task_id[:8]}` · "
                f"`{active.meta.get('status')}`). Abort it first.")
    t0 = time.time()
    try:
        pid = spawn(req)
    except Exception as e:  # noqa: BLE001
        LOG.exception("spawn failed")
        return f"❌ Launch failed: {e}"
    task_id = None
    for _ in range(20):
        task_id = newestTaskSince(t0)
        if task_id:
            break
        time.sleep(0.5)
    web = f"http://127.0.0.1:{config.WEB_DASHBOARD_PORT}/"
    if task_id:
        return (f"✅ Launched run `{task_id[:8]}` (pid {pid}) · mode `{req.mode}` · "
                f"{req.hours}h · parallel {req.parallel}\n{web}")
    return (f"✅ Launch started (pid {pid}) · mode `{req.mode}` · {req.hours}h. "
            f"If no dashboard appears shortly, check `logs\\work-*.log`.\n{web}")


def resumeOrError(task_id: str) -> str:
    """Resume an existing task by id (block if a run is active). Returns the user message."""
    if not taskExists(task_id):
        return f"❌ No such task `{task_id}`."
    active = activeRun()
    if active is not None:
        return f"⛔ A run is already active (`{active.task_id[:8]}`). Abort it first."
    try:
        pid = spawnResume(task_id)
    except Exception as e:  # noqa: BLE001
        LOG.exception("resume spawn failed")
        return f"❌ Resume failed: {e}"
    web = f"http://127.0.0.1:{config.WEB_DASHBOARD_PORT}/"
    return f"♻️ Resuming `{task_id[:8]}` (pid {pid})\n{web}"
```

- [ ] **Step 4: Run, expect pass** — `venv\Scripts\python -m unittest tests.test_work_launcher -v` (now ~23 tests). The existing `test_spawn_uses_argv` still passes (spawn still calls Popen with `buildArgv(req)`).

- [ ] **Step 5: Commit**

```bash
git add notifications/work_launcher.py tests/test_work_launcher.py
git commit -m "feat(discord): work_launcher resume (_spawnArgv/spawnResume/taskExists) + launchOrError/resumeOrError glue + tests"
```

---

## Task 7: notifications/branding.py — design system + rich embeds (+ tests)

**Files:** Create `notifications/branding.py`; Create `tests/test_branding.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_branding.py`:

```python
"""Unit tests for the branding design system + embed builders."""
import unittest

import config
from notifications import branding, commands
from notifications import discord_bot as discord
from state.task import TaskState


class _Bus:
    def getPendingGate(self):
        return None


def _state():
    st = TaskState.create("build a thing", 1.0)
    st.addSubtask("first", "d")
    st.addSubtask("second", "d")
    return st


class TestBranding(unittest.TestCase):
    def test_brand_embed_defaults(self):
        e = branding.brandEmbed("Title")
        self.assertEqual(e["title"], "Title")
        self.assertEqual(e["color"], config.BRAND_COLOR)
        self.assertIn("author", e)
        self.assertIn("footer", e)

    def test_help_lists_all_registry_commands(self):
        e = branding.helpEmbed()
        blob = (e.get("description", "") + " " +
                " ".join(f["value"] for f in e["fields"]))
        for name in commands.COMMAND_REGISTRY:
            self.assertIn(f"/{name}", blob, name)

    def test_status_embed_within_limits(self):
        e = discord._clampEmbed(branding.statusEmbed(_state(), _Bus()))
        self.assertTrue(e["title"])
        for f in e["fields"]:
            self.assertLessEqual(len(f["value"]), config.DISCORD_MAX_FIELD_VALUE)

    def test_plan_pagination_math(self):
        st = TaskState.create("g", 1.0)
        for i in range(25):
            st.addSubtask(f"t{i}", "d")
        _, pages = branding.planEmbed(st, page=0, per=10)
        self.assertEqual(pages, 3)
        e2, _ = branding.planEmbed(st, page=99, per=10)   # clamps to last page
        self.assertIn("3/3", e2["title"])

    def test_runs_pagination(self):
        sums = [{"task_id": f"id{i:02d}aaaa", "status": "done", "done": 1, "total": 1,
                 "goal": "g"} for i in range(20)]
        _, pages = branding.runsEmbed(sums, 0, 8)
        self.assertEqual(pages, 3)

    def test_metrics_embed_handles_none(self):
        e = branding.metricsEmbed({"total_runs": 0, "by_status": {}, "terminal_runs": 0,
                                   "success_runs": 0, "success_rate": None,
                                   "avg_duration_seconds": None, "subtasks_total": 0,
                                   "subtasks_passed": 0})
        self.assertTrue(e["fields"])

    def test_diagnostics_embed(self):
        e = branding.diagnosticsEmbed([{"name": "x", "ok": True, "detail": "ok", "fix": ""},
                                       {"name": "y", "ok": False, "detail": "bad", "fix": "do z"}])
        self.assertIn("1/2", e["title"])

    def test_control_panel_row_ids(self):
        rows = branding.controlPanelRow()
        ids = [c["custom_id"] for row in rows for c in row["components"]]
        self.assertEqual(set(ids), set(branding.CONTROL_PANEL_IDS.values()))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run, expect fail** (`ModuleNotFoundError: notifications.branding`).

- [ ] **Step 3: Implement** — `notifications/branding.py`:

```python
"""9TO5 Discord design system + rich embed builders. Pure (no network, no discord.py).
Central brand identity, the polished /command surfaces, and the control-panel component
row. Builds plain dicts; the transport layer (discord_bot._clampEmbed) guarantees limits."""
from __future__ import annotations

from typing import Optional

import config
from notifications import commands
from notifications import discord_bot as discord

BRAND = config.BRAND_COLOR

# ---- control-panel components (raw dicts for REST; custom_ids shared with views.py) ----
CONTROL_PANEL_IDS = {
    "pause": "cp_pause", "resume": "cp_resume", "abort": "cp_abort",
    "approve": "cp_approve", "reject": "cp_reject", "skip": "cp_skip",
}


def controlPanelRow() -> list:
    """Two action rows of control buttons (<=5/row). Handled by views.ControlPanelView."""
    return [
        {"type": 1, "components": [
            {"type": 2, "style": 1, "label": "Pause", "custom_id": "cp_pause", "emoji": {"name": "⏸️"}},
            {"type": 2, "style": 3, "label": "Resume", "custom_id": "cp_resume", "emoji": {"name": "▶️"}},
            {"type": 2, "style": 4, "label": "Abort", "custom_id": "cp_abort", "emoji": {"name": "🛑"}},
        ]},
        {"type": 1, "components": [
            {"type": 2, "style": 3, "label": "Approve", "custom_id": "cp_approve", "emoji": {"name": "✅"}},
            {"type": 2, "style": 2, "label": "Reject", "custom_id": "cp_reject", "emoji": {"name": "⚔️"}},
            {"type": 2, "style": 2, "label": "Skip", "custom_id": "cp_skip", "emoji": {"name": "⏭️"}},
        ]},
    ]


def brandEmbed(title: str, *, description: Optional[str] = None, color: Optional[int] = None,
               fields: Optional[list] = None, uptime: Optional[str] = None) -> dict:
    e: dict = {
        "title": title,
        "color": color if color is not None else BRAND,
        "timestamp": discord._nowIso(),
        "author": {"name": f"9TO5 v{config.VERSION}"},
        "footer": {"text": f"9TO5 v{config.VERSION}" + (f" · up {uptime}" if uptime else "")},
    }
    if config.BRAND_ICON_URL:
        e["author"]["icon_url"] = config.BRAND_ICON_URL
    if description is not None:
        e["description"] = description
    if fields:
        e["fields"] = fields
    return e


_CATEGORIES = {
    "Control": ["abort", "pause", "resume", "approve", "reject", "skip", "add", "retry"],
    "Info": ["status", "plan", "log", "help"],
    "Run": ["work", "runs", "run", "resume"],
}
_EXTRA_HELP = {
    "work": "launch a new run (blank = guided setup)",
    "runs": "list recent runs", "run": "inspect a run by id", "resume": "resume a run by id",
    "ping": "latency, uptime, version", "diagnostics": "environment health checks",
    "metrics": "aggregate run metrics", "audit": "recent control actions",
}


def _help(name: str) -> str:
    if name in commands.COMMAND_REGISTRY:
        return commands.COMMAND_REGISTRY[name]["help"]
    return _EXTRA_HELP.get(name, "")


def helpEmbed() -> dict:
    fields = []
    for cat, names in _CATEGORIES.items():
        fields.append({"name": cat, "value": "\n".join(f"`/{n}` — {_help(n)}" for n in names),
                       "inline": False})
    fields.append({"name": "Observability",
                   "value": "\n".join(f"`/{n}` — {_EXTRA_HELP[n]}"
                                      for n in ("ping", "diagnostics", "metrics", "audit")),
                   "inline": False})
    return brandEmbed("📖 9TO5 — commands",
                      description="Slash-first. `!`-prefixed text commands also work.",
                      fields=fields)


def statusEmbed(state, bus, uptime: Optional[str] = None) -> dict:
    m = state.meta
    done, total = state.progress()
    cur = next((s for s in state.subtasks if s["status"] == "in_progress"), None) or state.nextActionable()
    cur_txt = f"`{cur['subtask_id']}` {cur['title']}" if cur else "—"
    gate = bus.getPendingGate() if bus else None
    fields = [
        {"name": "Status", "value": f"`{m.get('status', '?')}`", "inline": True},
        {"name": "Mode", "value": f"`{m.get('control_mode', 'watch')}`", "inline": True},
        {"name": "Progress", "value": f"{done}/{total}", "inline": True},
        {"name": "Current", "value": discord.truncate(cur_txt, 1024), "inline": False},
    ]
    if gate:
        fields.append({"name": "⏳ Gate", "value": f"`{gate}` — /approve or /reject", "inline": False})
    return brandEmbed("📊 Run status",
                      description=f"**{discord.truncate(m.get('goal_raw', ''), 300)}**\n"
                                  f"{discord.progressBar(done, total)}\n"
                                  f"{discord.subtaskTracker(state.subtasks)}",
                      color=discord.statusColor(m.get("status")), fields=fields, uptime=uptime)


_PLAN_ICON = {"done": "✅", "in_progress": "⚡", "failed": "❌", "pending": "⬜"}


def _planLines(subtasks) -> list[str]:
    return [f"{_PLAN_ICON.get(s['status'], '⬜')} `{s['subtask_id']}` {s['title']}"
            for s in subtasks if s["status"] != "removed"]


def planEmbed(state, page: int = 0, per: int = 10):
    lines = _planLines(state.subtasks)
    total_pages = max(1, (len(lines) + per - 1) // per)
    page = max(0, min(page, total_pages - 1))
    chunk = lines[page * per:(page + 1) * per] or ["(no subtasks)"]
    e = brandEmbed(f"🗺️ Plan ({page + 1}/{total_pages})", description="\n".join(chunk),
                   color=discord.statusColor(state.meta.get("status")))
    return e, total_pages


def runsEmbed(summaries, page: int = 0, per: int = 8):
    total_pages = max(1, (len(summaries) + per - 1) // per)
    page = max(0, min(page, total_pages - 1))
    chunk = summaries[page * per:(page + 1) * per]
    lines = [f"`{s['task_id'][:8]}` [{s['status']}] {s['done']}/{s['total']} — "
             f"{discord.truncate(s['goal'], 60)}" for s in chunk] or ["(no runs yet)"]
    e = brandEmbed(f"🗂️ Recent runs ({page + 1}/{total_pages})", description="\n".join(lines))
    return e, total_pages


def runEmbed(state) -> dict:
    m = state.meta
    done, total = state.progress()
    fields = [
        {"name": "Task", "value": f"`{state.task_id[:8]}`", "inline": True},
        {"name": "Status", "value": f"`{m.get('status', '?')}`", "inline": True},
        {"name": "Progress", "value": f"{done}/{total}", "inline": True},
        {"name": "Started", "value": discord.relTime(m.get("started_at")), "inline": True},
        {"name": "Mode", "value": f"`{m.get('control_mode', 'watch')}`", "inline": True},
    ]
    return brandEmbed("🔎 Run detail",
                      description=f"**{discord.truncate(m.get('goal_raw', ''), 400)}**\n"
                                  f"{discord.progressBar(done, total)}",
                      color=discord.statusColor(m.get("status")), fields=fields)


def diagnosticsEmbed(checks) -> dict:
    lines = []
    for c in checks:
        mark = "🟢" if c["ok"] else "🔴"
        line = f"{mark} **{c['name']}** — {discord.truncate(c['detail'], 120)}"
        if not c["ok"] and c.get("fix"):
            line += f"\n  ↳ _{discord.truncate(c['fix'], 120)}_"
        lines.append(line)
    n_ok = sum(1 for c in checks if c["ok"])
    color = discord.statusColor("done") if n_ok == len(checks) else discord.statusColor("blocked")
    return brandEmbed(f"🩺 Diagnostics — {n_ok}/{len(checks)} healthy",
                      description="\n".join(lines) or "—", color=color)


def metricsEmbed(m) -> dict:
    sr, avg = m["success_rate"], m["avg_duration_seconds"]
    fields = [
        {"name": "Total runs", "value": str(m["total_runs"]), "inline": True},
        {"name": "Success rate", "value": (f"{round(sr * 100)}%" if sr is not None else "—"), "inline": True},
        {"name": "Avg duration",
         "value": (f"{int(avg // 60)}m{int(avg % 60):02d}s" if avg is not None else "—"), "inline": True},
        {"name": "Subtasks passed", "value": f"{m['subtasks_passed']}/{m['subtasks_total']}", "inline": True},
        {"name": "By status",
         "value": (", ".join(f"{k}:{v}" for k, v in sorted(m["by_status"].items())) or "—"), "inline": False},
    ]
    return brandEmbed("📈 Run metrics", fields=fields)


def pingEmbed(latency_ms, uptime, version) -> dict:
    return brandEmbed("🏓 Pong", uptime=uptime, fields=[
        {"name": "Gateway latency", "value": f"{latency_ms} ms", "inline": True},
        {"name": "Uptime", "value": uptime, "inline": True},
        {"name": "Version", "value": f"v{version}", "inline": True},
    ])


def auditEmbed(entries) -> dict:
    if not entries:
        return brandEmbed("📋 Audit log", description="_no actions recorded yet_")
    lines = []
    for e in entries[-15:]:
        tid = f" · {e['task_id'][:8]}" if e.get("task_id") else ""
        lines.append(f"`{(e.get('at') or '')[:19]}` <@{e.get('user_id', '?')}> "
                     f"**{e.get('action', '?')}**{tid}")
    return brandEmbed("📋 Audit log", description="\n".join(lines))
```

- [ ] **Step 4: Run, expect pass** — `venv\Scripts\python -m unittest tests.test_branding -v` (8 tests).

- [ ] **Step 5: Commit**

```bash
git add notifications/branding.py tests/test_branding.py
git commit -m "feat(discord): branding design system + rich embeds (help/status/plan/runs/run/diagnostics/metrics/ping/audit) + control-panel row + tests"
```

---

## Task 8: notifications/views.py — persistent views, confirm, paginator, work modal

**Files:** Create `notifications/views.py`

This is discord.py (gateway) code — verified by `py_compile` + import-smoke (a live token isn't needed to import it).

- [ ] **Step 1: Implement** — `notifications/views.py`:

```python
"""discord.py UI components for the 9TO5 gateway: persistent control-panel + blocked
views, a confirm dialog, a paginator, and the /work onboarding modal+view. Imports
discord.py (gateway-only) but is import-safe without a live connection."""
from __future__ import annotations

import discord

import config
from control import ControlBus
from notifications import audit, commands, work_launcher

LOG = config.getLogger("views")
MAX_REPLY = config.DISCORD_MAX_CONTENT - 100


def _ownerOk(interaction: "discord.Interaction") -> bool:
    return commands.isAuthorized(interaction.user.id)


async def _applyControl(interaction: "discord.Interaction", name: str, arg: str = "",
                        *, already_responded: bool = False) -> None:
    """Shared path for control-panel + blocked buttons: authorize -> audit -> spine."""
    meta = commands.COMMAND_REGISTRY.get(name, {})
    if meta.get("mutating") and not _ownerOk(interaction):
        return await _send(interaction, "⛔ Not authorized.", already_responded)
    state = commands.resolveTargetTask()
    if state is None:
        return await _send(interaction, commands.NO_TASK, already_responded)
    if meta.get("mutating"):
        audit.record(interaction.user.id, name, state.task_id, "button")
    msg = commands.applyCommand(ControlBus(state.task_id), state, commands.Command(name, arg))
    await _send(interaction, msg[:MAX_REPLY], already_responded)


async def _send(interaction: "discord.Interaction", msg: str, already_responded: bool) -> None:
    if already_responded:
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


async def _skipCurrent(interaction: "discord.Interaction", source: str) -> None:
    if not _ownerOk(interaction):
        return await interaction.response.send_message("⛔ Not authorized.", ephemeral=True)
    state = commands.resolveTargetTask()
    if state is None:
        return await interaction.response.send_message(commands.NO_TASK, ephemeral=True)
    cur = next((s for s in state.subtasks if s["status"] == "in_progress"), None)
    if not cur:
        return await interaction.response.send_message("Nothing in progress to skip.", ephemeral=True)
    audit.record(interaction.user.id, "skip", state.task_id, source)
    msg = commands.applyCommand(ControlBus(state.task_id), state,
                                commands.Command("skip", cur["subtask_id"]))
    await interaction.response.send_message(msg[:MAX_REPLY], ephemeral=True)


class ConfirmView(discord.ui.View):
    """Ephemeral Confirm/Cancel; caller awaits .wait() then checks .value."""
    def __init__(self, owner_id: int):
        super().__init__(timeout=30)
        self.owner_id = owner_id
        self.value = False

    async def interaction_check(self, interaction: "discord.Interaction") -> bool:
        return interaction.user.id == self.owner_id

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction, button):  # noqa: ANN001
        self.value = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):  # noqa: ANN001
        self.value = False
        await interaction.response.defer()
        self.stop()


async def confirmDestructive(interaction: "discord.Interaction", label: str) -> bool:
    """Send an ephemeral confirm dialog (this consumes the initial response). True if confirmed."""
    view = ConfirmView(interaction.user.id)
    await interaction.response.send_message(f"⚠️ Confirm **{label}**?", view=view, ephemeral=True)
    await view.wait()
    return view.value


class ControlPanelView(discord.ui.View):
    """Persistent (timeout=None). Matched to the dashboard message by custom_id;
    add_view'd on startup so clicks work across restarts and cross-process messages."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.primary, custom_id="cp_pause", emoji="⏸️")
    async def pause(self, interaction, button):  # noqa: ANN001
        await _applyControl(interaction, "pause")

    @discord.ui.button(label="Resume", style=discord.ButtonStyle.success, custom_id="cp_resume", emoji="▶️")
    async def resume(self, interaction, button):  # noqa: ANN001
        await _applyControl(interaction, "resume")

    @discord.ui.button(label="Abort", style=discord.ButtonStyle.danger, custom_id="cp_abort", emoji="🛑")
    async def abort(self, interaction, button):  # noqa: ANN001
        if not _ownerOk(interaction):
            return await interaction.response.send_message("⛔ Not authorized.", ephemeral=True)
        if await confirmDestructive(interaction, "abort the run"):
            await _applyControl(interaction, "abort", already_responded=True)

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, custom_id="cp_approve", emoji="✅")
    async def approve(self, interaction, button):  # noqa: ANN001
        await _applyControl(interaction, "approve")

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.secondary, custom_id="cp_reject", emoji="⚔️")
    async def reject(self, interaction, button):  # noqa: ANN001
        await _applyControl(interaction, "reject")

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary, custom_id="cp_skip", emoji="⏭️")
    async def skip(self, interaction, button):  # noqa: ANN001
        await _skipCurrent(interaction, "control-panel")


class BlockedView(discord.ui.View):
    """Persistent view for the BLOCKED embed's Answer/Skip/Abort buttons (custom_ids sc_*)."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Answer", style=discord.ButtonStyle.primary, custom_id="sc_answer", emoji="✍️")
    async def answer(self, interaction, button):  # noqa: ANN001
        await interaction.response.send_message(
            "✍️ Type your answer as a normal message; the orchestrator will pick it up.", ephemeral=True)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary, custom_id="sc_skip", emoji="⏭️")
    async def skip(self, interaction, button):  # noqa: ANN001
        await _skipCurrent(interaction, "blocked")

    @discord.ui.button(label="Abort", style=discord.ButtonStyle.danger, custom_id="sc_abort", emoji="🛑")
    async def abort(self, interaction, button):  # noqa: ANN001
        if not _ownerOk(interaction):
            return await interaction.response.send_message("⛔ Not authorized.", ephemeral=True)
        if await confirmDestructive(interaction, "abort the run"):
            await _applyControl(interaction, "abort", already_responded=True)


class Paginator(discord.ui.View):
    """Prev/Next over pre-built discord.Embed pages, bound to the invoking user."""
    def __init__(self, owner_id: int, pages: list, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        self.pages = pages or [discord.Embed(description="(empty)")]
        self.i = 0
        self._sync()

    def _sync(self) -> None:
        self.prev.disabled = self.i <= 0
        self.next.disabled = self.i >= len(self.pages) - 1

    async def interaction_check(self, interaction: "discord.Interaction") -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Not your paginator.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction, button):  # noqa: ANN001
        self.i = max(0, self.i - 1)
        self._sync()
        await interaction.response.edit_message(embed=self.pages[self.i], view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction, button):  # noqa: ANN001
        self.i = min(len(self.pages) - 1, self.i + 1)
        self._sync()
        await interaction.response.edit_message(embed=self.pages[self.i], view=self)


class WorkSetupView(discord.ui.View):
    """Dropdowns + Launch/Cancel for the /work guided setup (used after WorkModal)."""
    def __init__(self, owner_id: int, goal: str, hours: float, work_dir: "str | None"):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.req = work_launcher.WorkRequest(goal=goal, hours=hours, work_dir=work_dir or None)

    async def interaction_check(self, interaction: "discord.Interaction") -> bool:
        if not commands.isAuthorized(interaction.user.id):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return False
        return True

    @discord.ui.select(placeholder="Control mode", options=[
        discord.SelectOption(label="watch (autonomous + abort)", value="watch", default=True),
        discord.SelectOption(label="gated (approve plan + PR)", value="gated"),
    ])
    async def _mode(self, interaction, select):  # noqa: ANN001
        self.req.mode = select.values[0]
        await interaction.response.defer()

    @discord.ui.select(placeholder="Parallelism", options=[
        discord.SelectOption(label=f"{i} concurrent subtask(s)", value=str(i), default=(i == 1))
        for i in range(1, work_launcher.MAX_PARALLEL + 1)
    ])
    async def _parallel(self, interaction, select):  # noqa: ANN001
        self.req.parallel = int(select.values[0])
        await interaction.response.defer()

    @discord.ui.select(placeholder="Pull request", options=[
        discord.SelectOption(label="Create a PR when done", value="pr", default=True),
        discord.SelectOption(label="Skip PR", value="nopr"),
    ])
    async def _pr(self, interaction, select):  # noqa: ANN001
        self.req.no_pr = (select.values[0] == "nopr")
        await interaction.response.defer()

    @discord.ui.button(label="Launch", style=discord.ButtonStyle.success)
    async def _launch(self, interaction, button):  # noqa: ANN001
        import asyncio
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(content="🚀 Launching…", view=self)
        audit.record(interaction.user.id, "work", None, "modal")
        reply = await asyncio.to_thread(work_launcher.launchOrError, self.req)
        await interaction.followup.send(reply[:MAX_REPLY], ephemeral=True)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def _cancel(self, interaction, button):  # noqa: ANN001
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(content="Cancelled.", view=self)
        self.stop()


class WorkModal(discord.ui.Modal, title="Start a 9TO5 run"):
    goal = discord.ui.TextInput(label="Goal", style=discord.TextStyle.paragraph,
                                required=True, max_length=4000)
    hours = discord.ui.TextInput(label="Hours", default="1", required=False, max_length=6)
    work_dir = discord.ui.TextInput(label="Working directory (optional)", required=False, max_length=300)

    async def on_submit(self, interaction: "discord.Interaction") -> None:
        view = WorkSetupView(interaction.user.id, str(self.goal),
                             work_launcher.parseHours(str(self.hours)), str(self.work_dir) or None)
        await interaction.response.send_message("Set options, then **Launch**:", view=view, ephemeral=True)
```

- [ ] **Step 2: Verify** — `venv\Scripts\python -m py_compile notifications/views.py` then
  `venv\Scripts\python -c "from notifications import views; print(bool(views.ControlPanelView()), bool(views.BlockedView()), bool(views.WorkModal()))"` → `True True True`.
  Also confirm persistence: `venv\Scripts\python -c "from notifications import views; v=views.ControlPanelView(); print(v.timeout is None, [c.custom_id for c in v.children])"` → `True ['cp_pause', 'cp_resume', 'cp_abort', 'cp_approve', 'cp_reject', 'cp_skip']`.

- [ ] **Step 3: Confirm the suite still green** — `venv\Scripts\python -m unittest discover -s tests` (all prior tests pass; views.py adds no tests but must not break imports).

- [ ] **Step 4: Commit**

```bash
git add notifications/views.py
git commit -m "feat(discord): persistent ControlPanel/Blocked views, ConfirmView, Paginator, Work modal/view"
```

---

## Task 9: notifications/slash.py — the slash command suite + autocomplete

**Files:** Create `notifications/slash.py`

- [ ] **Step 1: Implement** — `notifications/slash.py`:

```python
"""All 9TO5 slash commands, registered onto a CommandTree. Thin shells over the
commands.py spine / work_launcher / branding builders. Read commands are open;
mutating commands require owner + cooldown. Autocomplete for subtask/task ids."""
from __future__ import annotations

import asyncio
import time

import discord
from discord import app_commands

import config
import health
from control import ControlBus
from notifications import audit, branding, commands, metrics, work_launcher
from state.task import TaskState

LOG = config.getLogger("slash")
MAX_REPLY = config.DISCORD_MAX_CONTENT - 100


def _fmtUptime(started_at: float) -> str:
    secs = max(0, int(time.time() - started_at))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m{s:02d}s"


def _embed(d: dict) -> discord.Embed:
    return discord.Embed.from_dict(d)


def registerSlashCommands(tree: "app_commands.CommandTree", client: "discord.Client",
                          started_at: float) -> None:
    cooldown = app_commands.checks.cooldown(config.COOLDOWN_RATE, config.COOLDOWN_PER,
                                            key=lambda i: i.user.id)

    def _ownerOk(interaction) -> bool:
        return commands.isAuthorized(interaction.user.id)

    async def _runControl(interaction, name: str, arg: str = "") -> None:
        await interaction.response.defer(ephemeral=True)
        state = commands.resolveTargetTask()
        if state is None:
            return await interaction.followup.send(commands.NO_TASK, ephemeral=True)
        audit.record(interaction.user.id, name, state.task_id, "slash")
        msg = commands.applyCommand(ControlBus(state.task_id), state, commands.Command(name, arg))
        await interaction.followup.send(msg[:MAX_REPLY], ephemeral=True)

    # ---------- read commands (open to all) ----------
    @tree.command(name="status", description="Current run status")
    async def status(interaction):  # noqa: ANN001
        await interaction.response.defer(ephemeral=True)
        state = commands.resolveTargetTask()
        if state is None:
            return await interaction.followup.send(commands.NO_TASK, ephemeral=True)
        e = branding.statusEmbed(state, ControlBus(state.task_id), uptime=_fmtUptime(started_at))
        await interaction.followup.send(embed=_embed(e), ephemeral=True)

    @tree.command(name="plan", description="The subtask plan")
    async def plan(interaction):  # noqa: ANN001
        await interaction.response.defer(ephemeral=True)
        state = commands.resolveTargetTask()
        if state is None:
            return await interaction.followup.send(commands.NO_TASK, ephemeral=True)
        _, total = branding.planEmbed(state, 0)
        pages = [_embed(branding.planEmbed(state, p)[0]) for p in range(total)]
        from notifications.views import Paginator
        if total > 1:
            await interaction.followup.send(embed=pages[0], view=Paginator(interaction.user.id, pages),
                                            ephemeral=True)
        else:
            await interaction.followup.send(embed=pages[0], ephemeral=True)

    @tree.command(name="log", description="Obsidian index + web dashboard URL")
    async def log(interaction):  # noqa: ANN001
        await _runControl(interaction, "log")

    @tree.command(name="help", description="Show the command list")
    async def help_(interaction):  # noqa: ANN001
        await interaction.response.send_message(embed=_embed(branding.helpEmbed()), ephemeral=True)

    @tree.command(name="ping", description="Bot latency, uptime, version")
    async def ping(interaction):  # noqa: ANN001
        ms = round(client.latency * 1000) if client.latency else 0
        e = branding.pingEmbed(ms, _fmtUptime(started_at), config.VERSION)
        await interaction.response.send_message(embed=_embed(e), ephemeral=True)

    @tree.command(name="diagnostics", description="Environment health checks")
    async def diagnostics(interaction):  # noqa: ANN001
        await interaction.response.defer(ephemeral=True)
        checks = await asyncio.to_thread(health.collectHealth)
        await interaction.followup.send(embed=_embed(branding.diagnosticsEmbed(checks)), ephemeral=True)

    @tree.command(name="metrics", description="Aggregate run metrics")
    async def metrics_(interaction):  # noqa: ANN001
        await interaction.response.defer(ephemeral=True)
        m = await asyncio.to_thread(metrics.compute)
        await interaction.followup.send(embed=_embed(branding.metricsEmbed(m)), ephemeral=True)

    @tree.command(name="audit", description="Recent control actions")
    async def audit_(interaction):  # noqa: ANN001
        await interaction.response.send_message(
            embed=_embed(branding.auditEmbed(audit.recent(20))), ephemeral=True)

    # ---------- mutating commands (owner + cooldown) ----------
    async def _guard(interaction) -> bool:
        if not _ownerOk(interaction):
            await interaction.response.send_message("⛔ Not authorized to control runs.", ephemeral=True)
            return False
        return True

    @tree.command(name="pause", description="Pause the run")
    @cooldown
    async def pause(interaction):  # noqa: ANN001
        if await _guard(interaction):
            await _runControl(interaction, "pause")

    @tree.command(name="resume", description="Resume the run")
    @cooldown
    async def resume(interaction):  # noqa: ANN001
        if await _guard(interaction):
            await _runControl(interaction, "resume")

    @tree.command(name="approve", description="Approve the pending gate")
    @cooldown
    async def approve(interaction):  # noqa: ANN001
        if await _guard(interaction):
            await _runControl(interaction, "approve")

    @tree.command(name="reject", description="Reject the pending gate")
    @cooldown
    async def reject(interaction):  # noqa: ANN001
        if await _guard(interaction):
            await _runControl(interaction, "reject")

    @tree.command(name="retry", description="Re-run the current subtask")
    @cooldown
    async def retry(interaction):  # noqa: ANN001
        if await _guard(interaction):
            await _runControl(interaction, "retry")

    @tree.command(name="add", description="Queue a new subtask")
    @app_commands.describe(title="Subtask title")
    @cooldown
    async def add(interaction, title: str):  # noqa: ANN001
        if await _guard(interaction):
            await _runControl(interaction, "add", title)

    async def _subtaskAutocomplete(interaction, current: str):  # noqa: ANN001
        state = commands.resolveTargetTask()
        if state is None:
            return []
        out = []
        for s in state.subtasks:
            if s["status"] in ("pending", "in_progress") and current.lower() in s["subtask_id"].lower():
                out.append(app_commands.Choice(name=f"{s['subtask_id']} — {s['title'][:60]}",
                                               value=s["subtask_id"]))
        return out[:25]

    @tree.command(name="skip", description="Skip a pending subtask")
    @app_commands.describe(subtask="Subtask id (e.g. st-003)")
    @app_commands.autocomplete(subtask=_subtaskAutocomplete)
    @cooldown
    async def skip(interaction, subtask: str):  # noqa: ANN001
        if await _guard(interaction):
            await _runControl(interaction, "skip", subtask)

    @tree.command(name="abort", description="Abort the run (asks for confirmation)")
    @cooldown
    async def abort(interaction):  # noqa: ANN001
        if not await _guard(interaction):
            return
        from notifications.views import confirmDestructive
        if await confirmDestructive(interaction, "abort the run"):
            state = commands.resolveTargetTask()
            if state is None:
                return await interaction.followup.send(commands.NO_TASK, ephemeral=True)
            audit.record(interaction.user.id, "abort", state.task_id, "slash")
            msg = commands.applyCommand(ControlBus(state.task_id), state, commands.Command("abort", ""))
            await interaction.followup.send(msg[:MAX_REPLY], ephemeral=True)

    # ---------- run lifecycle ----------
    async def _taskAutocomplete(interaction, current: str):  # noqa: ANN001
        out = []
        for s in TaskState.listRecent(25):
            if current.lower() in s["task_id"].lower():
                out.append(app_commands.Choice(
                    name=f"{s['task_id'][:8]} — [{s['status']}] {s['goal'][:50]}",
                    value=s["task_id"]))
        return out[:25]

    @tree.command(name="work", description="Start a 9TO5 run (blank = guided setup)")
    @app_commands.describe(goal="What to work on (blank opens guided setup)",
                           hours="Time horizon in hours", mode="watch or gated",
                           parallel="Concurrent subtasks", no_pr="Skip the PR", work_dir="Working directory")
    @app_commands.choices(mode=[app_commands.Choice(name="watch", value="watch"),
                                app_commands.Choice(name="gated", value="gated")])
    @cooldown
    async def work(interaction, goal: "str | None" = None, hours: "float | None" = None,
                   mode: "app_commands.Choice[str] | None" = None, parallel: "int | None" = None,
                   no_pr: "bool | None" = None, work_dir: "str | None" = None):  # noqa: ANN001
        if not _ownerOk(interaction):
            return await interaction.response.send_message("⛔ Not authorized to launch runs.", ephemeral=True)
        if not goal:
            from notifications.views import WorkModal
            return await interaction.response.send_modal(WorkModal())
        await interaction.response.defer(ephemeral=True)
        req = work_launcher.WorkRequest(
            goal=goal, hours=work_launcher.parseHours(hours),
            mode=(mode.value if mode else "watch"), parallel=parallel or 1,
            no_pr=bool(no_pr), work_dir=work_dir or None)
        audit.record(interaction.user.id, "work", None, "slash")
        reply = await asyncio.to_thread(work_launcher.launchOrError, req)
        await interaction.followup.send(reply[:MAX_REPLY], ephemeral=True)

    @tree.command(name="runs", description="List recent runs")
    async def runs(interaction):  # noqa: ANN001
        await interaction.response.defer(ephemeral=True)
        summaries = TaskState.listRecent(40)
        _, total = branding.runsEmbed(summaries, 0)
        pages = [_embed(branding.runsEmbed(summaries, p)[0]) for p in range(total)]
        from notifications.views import Paginator
        if total > 1:
            await interaction.followup.send(embed=pages[0], view=Paginator(interaction.user.id, pages),
                                            ephemeral=True)
        else:
            await interaction.followup.send(embed=pages[0], ephemeral=True)

    @tree.command(name="run", description="Inspect a run by id")
    @app_commands.describe(task_id="Task id")
    @app_commands.autocomplete(task_id=_taskAutocomplete)
    async def run(interaction, task_id: str):  # noqa: ANN001
        await interaction.response.defer(ephemeral=True)
        if not work_launcher.taskExists(task_id):
            return await interaction.followup.send(f"❌ No such task `{task_id}`.", ephemeral=True)
        state = TaskState.load(task_id)
        await interaction.followup.send(embed=_embed(branding.runEmbed(state)), ephemeral=True)

    @tree.command(name="resume", description="Resume a run by id")
    @app_commands.describe(task_id="Task id to resume")
    @app_commands.autocomplete(task_id=_taskAutocomplete)
    @cooldown
    async def resume_run(interaction, task_id: str):  # noqa: ANN001
        if not _ownerOk(interaction):
            return await interaction.response.send_message("⛔ Not authorized.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        audit.record(interaction.user.id, "resume", task_id, "slash")
        reply = await asyncio.to_thread(work_launcher.resumeOrError, task_id)
        await interaction.followup.send(reply[:MAX_REPLY], ephemeral=True)
```

- [ ] **Step 2: Verify** — `venv\Scripts\python -m py_compile notifications/slash.py` then
  `venv\Scripts\python -c "from notifications import slash; print(callable(slash.registerSlashCommands))"` → `True`.
  Then prove registration adds all commands:
  ```
  venv\Scripts\python -c "import discord; from discord import app_commands; from notifications import slash; c=discord.Client(intents=discord.Intents.none()); t=app_commands.CommandTree(c); slash.registerSlashCommands(t,c,0.0); print(sorted(cmd.name for cmd in t.get_commands()))"
  ```
  Expected (19): `['abort', 'add', 'approve', 'audit', 'diagnostics', 'help', 'log', 'metrics', 'pause', 'ping', 'plan', 'reject', 'resume', 'retry', 'run', 'runs', 'skip', 'status', 'work']` — note `help`/`metrics`/`resume` come from `help_`/`metrics_`/`resume_run` (the `name=` overrides the function name). Confirm `work`, `runs`, `run`, `resume` are present.

- [ ] **Step 3: Suite still green** — `venv\Scripts\python -m unittest discover -s tests`.

- [ ] **Step 4: Commit**

```bash
git add notifications/slash.py
git commit -m "feat(discord): full slash command suite + autocomplete (control/info/run) over the spine"
```

---

## Task 10: command_bot.py — slim gateway rewire

**Files:** Modify `notifications/command_bot.py`

- [ ] **Step 1: Replace the module** with EXACTLY:

```python
"""Gateway command bot -- slim shell. Registers the slash command suite (slash.py),
persistent component views (views.py), a presence loop, and the legacy '!' text path
(via the commands.py spine). Run:  venv\\Scripts\\python -m notifications.command_bot
"""
from __future__ import annotations

import asyncio
import time

import config
from control import ControlBus
from notifications import commands
from state.task import TaskState  # noqa: F401  (kept for parity / external imports)

LOG = config.getLogger("command_bot")

MAX_REPLY_CHARS = config.DISCORD_MAX_CONTENT - 100


def handleCommand(content: str) -> str:
    """Parse + apply a '!' command against the latest task. '' if not a command."""
    cmd = commands.parseCommand(content)
    if cmd is None:
        return ""
    state = commands.resolveTargetTask()
    if state is None:
        return commands.NO_TASK
    return commands.applyCommand(ControlBus(state.task_id), state, cmd)


def runCommandBot() -> None:  # pragma: no cover -- long-lived gateway process
    import discord as dpy
    from discord import app_commands
    from notifications import audit, slash, views

    if not config.DISCORD_BOT_TOKEN:
        LOG.error("DISCORD_BOT_TOKEN missing; cannot start command bot")
        return

    started_at = time.time()
    intents = dpy.Intents.default()
    intents.message_content = True
    client = dpy.Client(intents=intents)
    tree = app_commands.CommandTree(client)
    slash.registerSlashCommands(tree, client, started_at)
    _state = {"synced": False, "presence": False}

    @tree.error
    async def _on_app_error(interaction, error):  # noqa: ANN001
        if isinstance(error, app_commands.CommandOnCooldown):
            msg = f"⏳ Slow down — try again in {error.retry_after:.0f}s."
        else:
            LOG.exception("slash error: %s", error)
            msg = "internal error (see logs)"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:  # noqa: BLE001
            pass

    async def _presenceLoop():
        await client.wait_until_ready()
        while not client.is_closed():
            try:
                state = commands.resolveTargetTask()
                if state is not None and commands.isRunActive(state):
                    done, total = state.progress()
                    name = f"{done}/{total} · {state.meta.get('status', 'run')}"
                else:
                    name = "idle · /help"
                await client.change_presence(
                    activity=dpy.Activity(type=dpy.ActivityType.watching, name=name))
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(config.PRESENCE_INTERVAL)

    @client.event
    async def on_ready() -> None:
        if not _state["synced"]:
            try:
                if config.DISCORD_GUILD_ID:
                    guild = dpy.Object(id=config.DISCORD_GUILD_ID)
                    tree.copy_global_to(guild=guild)
                    synced = await tree.sync(guild=guild)
                else:
                    synced = await tree.sync()
                _state["synced"] = True
                LOG.info("Command bot online as %s; synced %d slash command(s)", client.user, len(synced))
            except Exception as e:  # noqa: BLE001
                LOG.warning("slash sync failed: %s", e)
        client.add_view(views.ControlPanelView())   # persistent: matches cp_* on any message
        client.add_view(views.BlockedView())        # persistent: matches sc_*
        if not _state["presence"]:
            _state["presence"] = True
            client.loop.create_task(_presenceLoop())

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

(Note: `on_interaction`, the old inline `/work`/`WorkModal`/`WorkSetupView`, `handleButton`, and `_launchOrError` are intentionally gone — slash commands route via the tree and component clicks via the persistent views.)

- [ ] **Step 2: Verify** — `venv\Scripts\python -m py_compile notifications/command_bot.py` then
  `venv\Scripts\python -c "from notifications import command_bot as c; print('ok', c.MAX_REPLY_CHARS, bool(c.handleCommand('!help')))"` → `ok 1900 True`. Whole-package import:
  `venv\Scripts\python -c "import notifications.command_bot, notifications.slash, notifications.views, notifications.branding, notifications.audit, notifications.metrics; print('all import ok')"` → `all import ok`.

- [ ] **Step 3: Suite still green** — `venv\Scripts\python -m unittest discover -s tests`.

- [ ] **Step 4: Commit**

```bash
git add notifications/command_bot.py
git commit -m "feat(discord): slim gateway — register slash suite + persistent views + presence loop + cooldown error UX; '!' legacy via spine"
```

---

## Task 11: dashboard.py — attach control-panel components

**Files:** Modify `notifications/dashboard.py`

- [ ] **Step 1: Import branding** — add to the top imports of `notifications/dashboard.py`:

```python
from notifications import branding
```

- [ ] **Step 2: Attach components on create + edit** — in `start`, change the `createMessage` call to pass components; in `update`, pass components to both `editMessage` and the recreate `createMessage`. Concretely:

In `start`, replace `self.message_id = discord.createMessage(embed)` with:
```python
            self.message_id = discord.createMessage(embed, components=branding.controlPanelRow())
```

In `update`, replace the `editMessage`/`createMessage` block inside `with self._send_lock:` with:
```python
            row = branding.controlPanelRow()
            if self.message_id:
                ok = discord.editMessage(self.message_id, embed, components=row)
                if not ok and not self._recreated:
                    self._recreated = True
                    self.message_id = discord.createMessage(embed, components=row)
                    if self.message_id:
                        discord.pinMessage(self.message_id)
            else:
                self.message_id = discord.createMessage(embed, components=row)
                if self.message_id:
                    discord.pinMessage(self.message_id)
```

- [ ] **Step 3: Verify** — `venv\Scripts\python -m py_compile notifications/dashboard.py` then the fake-render smoke (no network):
  ```
  venv\Scripts\python -c "import config; config.DISCORD_DASHBOARD=False; from notifications.dashboard import DiscordDashboard; from state.task import TaskState; d=DiscordDashboard(); s=TaskState.create('g',1.0); print(d._embed(s,'executing')['title']); print('ok')"
  ```
  Expected: `⚙️ 9TO5 · executing` then `ok` (DISCORD_DASHBOARD off → start/update no-op, so components aren't actually sent here; this just proves the import + embed build still work).
  Confirm no import cycle: `venv\Scripts\python -c "import notifications.dashboard, notifications.branding, notifications.commands; print('ok')"` → `ok`.

- [ ] **Step 4: Suite still green** — `venv\Scripts\python -m unittest discover -s tests`.

- [ ] **Step 5: Commit**

```bash
git add notifications/dashboard.py
git commit -m "feat(discord): attach persistent control-panel buttons to the live dashboard embed"
```

---

## Task 12: orchestrator.py — poller records audit

**Files:** Modify `orchestrator.py`

- [ ] **Step 1: Import audit** — add to the `from notifications import ...` imports in `orchestrator.py`:

```python
from notifications import audit
```

- [ ] **Step 2: Record audit in the poller** — in `_translateDiscord`, replace the loop body so a mutating command is audited before it's applied:

```python
        for m in msgs:
            author_id = m.get("author_id") or None
            cmd = commands.decide(int(author_id) if author_id else None,
                                  m.get("author_is_bot", False), m.get("content", ""))
            if cmd:
                if commands.COMMAND_REGISTRY.get(cmd.name, {}).get("mutating"):
                    audit.record(author_id, cmd.name, state.task_id, "discord-poll")
                commands.applyCommand(bus, state, cmd)
```

- [ ] **Step 3: Verify** — `venv\Scripts\python -c "import orchestrator; print('ok')"` → `ok`. Full suite green: `venv\Scripts\python -m unittest discover -s tests`.

- [ ] **Step 4: Commit**

```bash
git add orchestrator.py
git commit -m "feat(discord): in-run poller records audit on mutating control commands"
```

---

## Task 13: Final verification

**Files:** none

- [ ] **Step 1: Full test suite** — `venv\Scripts\python -m unittest discover -s tests -v` → ALL pass (test_commands, test_discord_rest, test_work_launcher, test_audit, test_metrics, test_task_listrecent, test_health_collect, test_branding).

- [ ] **Step 2: Whole-package import-smoke**
  ```
  venv\Scripts\python -c "import config, orchestrator, main, health; from notifications import commands, discord_bot, dashboard, command_bot, work_launcher, branding, audit, metrics, views, slash; print('all import ok')"
  ```
  Expected: `all import ok`.

- [ ] **Step 3: Slash registration count** — re-run the Task 9 Step 2 registration command; confirm 19 commands registered (the 12 control/info + ping/diagnostics/metrics/audit + work/runs/run/resume).

- [ ] **Step 4: Health** — `venv\Scripts\python main.py --health` (the Discord check should PASS; Obsidian/git/hooks fails are pre-existing/environmental, unrelated to this change).

- [ ] **Step 5: Manual live checklist (requires the gateway running in a configured channel)**
  - `python -m notifications.command_bot` → log shows `synced 19 slash command(s)`; bot presence shows `idle · /help`.
  - `/help` renders categorized; `/ping` shows latency/uptime/version.
  - `/work` (no args) → modal → dropdowns → Launch → run starts; presence flips to `0/N · planning`.
  - Dashboard appears pinned WITH the control-panel buttons; **restart the gateway bot**, then click Pause/Resume/Abort → still handled (persistent views).
  - `/abort` and the Abort button both show a confirm dialog.
  - `/skip` autocompletes pending subtasks; `/runs` paginates; `/run <id>` and `/resume <id>` autocomplete task ids.
  - `/diagnostics` and `/metrics` render; `/audit` shows the actions you just took.
  - A non-owner can `/status` but is refused `/abort`.
  - On run completion the dashboard auto-unpins (from the prior cycle).

- [ ] **Step 6: Final commit (if any checklist tweaks)**

```bash
git add -A
git commit -m "test(discord): full elevation suite green + live SOTA checklist"
```

---

## Self-review notes (author)

- **Spec coverage:** Pillar 1 (slash suite + autocomplete) → T9; Pillar 2 (persistent control panel) → T7 (row) + T8 (views) + T10 (add_view) + T11 (attach); Pillar 3 (design system/branding/presence) → T7 + T10 (presence loop); Pillar 4 (observability) → T2 (audit) + T3 (metrics) + T5 (collectHealth) + T9 (`/ping /diagnostics /metrics /audit`) + T12 (poller audit); Pillar 5 (safety) → T8 (Confirm/Paginator) + T9 (cooldown/guard) + T10 (tree.error); Pillar 6 (multi-run) → T4 (listRecent) + T6 (resume glue) + T9 (`/runs /run /resume`). All covered.
- **Async-safety:** every blocking call from an async handler (`work_launcher.launchOrError/resumeOrError`, `health.collectHealth`, `metrics.compute`) is run via `asyncio.to_thread` so the gateway event loop never blocks. Slash handlers `defer(ephemeral=True)` before slow work (3s ack).
- **Interaction-lifecycle:** persistent views (cp_*/sc_*) auto-route to view callbacks — `command_bot` defines NO custom `on_interaction` (avoids the double-response bug fixed last cycle). The `/abort` + Abort-button confirm consumes the initial response, then uses `followup`.
- **Type consistency:** `WorkRequest`, `Command`, `controlPanelRow`/`CONTROL_PANEL_IDS`, `launchOrError`/`resumeOrError`, `collectHealth`, `listRecent`, all `*Embed` builders, and the `cp_*`/`sc_*` custom_ids are used identically across tasks.
- **No cycles:** `discord_bot`(leaf) ← `branding` ← {`views`,`slash`,`dashboard`}; `commands`/`audit`/`metrics`/`work_launcher` ← {`views`,`slash`}; nothing imports `views`/`slash`/`command_bot`.
```
