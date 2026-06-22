"""9TO5 deterministic hook dispatcher.

Claude Code invokes this as:  python agents\hooks.py <hook_name>
with a JSON event object piped on STDIN.

This file MUST be robust: it NEVER crashes Claude Code. Every handler is wrapped
in try/except and exits 0 -- EXCEPT block_destructive, which intentionally exits
2 to block a dangerous tool call.
"""

import sys
import json
import os

# Make "import config" (and other project modules) work regardless of cwd.
sys.path.insert(0, r"C:\supercritical")

# config is safe to import at module load; project sub-modules are imported
# lazily inside handlers so a broken import can never crash the dispatcher.
try:
    import config  # noqa: F401
except Exception:
    config = None


# Patterns that we refuse to let a Bash tool run. Matched case-insensitively
# against the raw command string.
DESTRUCTIVE_PATTERNS = (
    "rm -rf",
    "rm -fr",
    "rmdir /s",
    "del /f",
    "del /s",
    "format ",
    "DROP TABLE",
    "git push --force",
    "git push -f",
    "mkfs",
    ":(){",
    ">/dev/sda",
)

LOG_PATH = r"C:\supercritical\logs\hooks.log"


def _readEvent():
    """Read and parse the JSON event piped on STDIN. Never raises."""
    try:
        raw = sys.stdin.read()
    except Exception:
        return {}
    try:
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def _resolveState():
    """Resolve the ACTIVE task for this hook: prefer the explicit id the executor exported
    (NINE_TO_FIVE_TASK_ID) so under --parallel the guard reads the RIGHT task's boundaries;
    fall back to loadLatest() only for a manual/standalone hook invocation. Never raises."""
    try:
        from state.task import TaskState
    except Exception:
        return None
    tid = os.environ.get("NINE_TO_FIVE_TASK_ID")
    if tid:
        try:
            return TaskState.load(tid)
        except Exception:
            pass
    try:
        return TaskState.loadLatest()
    except Exception:
        return None


def blockDestructive(data):
    """PreToolUse: block destructive Bash commands by exiting 2.

    Exits 0 when the command is safe (or not a Bash command). Exits 2 when a
    destructive pattern is detected, after best-effort Discord alerting.
    """
    try:
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {}) or {}
        command = ""
        if tool_name == "Bash":
            command = tool_input.get("command", "") or ""
    except Exception:
        sys.exit(0)

    if not command:
        sys.exit(0)

    lowered = command.lower()
    matched = None
    for pat in DESTRUCTIVE_PATTERNS:
        if pat.lower() in lowered:
            matched = pat
            break

    if matched is None:
        sys.exit(0)

    reason = (
        f"Blocked destructive command (matched {matched!r}): {command}"
    )

    # (a) best-effort Discord alert (severe: @everyone + human ping + buttons).
    try:
        import notifications.discord_bot as discord
        discord.sendBlocked(reason)
    except Exception:
        pass

    # (b) human-readable reason to STDERR.
    try:
        sys.stderr.write(reason + "\n")
    except Exception:
        pass

    # (c) exit code 2 blocks the tool in Claude Code.
    sys.exit(2)


def writeObsidian(data):
    """PostToolUse: log the edited file path to the in-progress subtask note."""
    try:
        tool_name = data.get("tool_name", "")
        if tool_name not in ("Edit", "Write", "MultiEdit"):
            sys.exit(0)

        tool_input = data.get("tool_input", {}) or {}
        file_path = tool_input.get("file_path", "")

        from datetime import datetime
        from memory.obsidian import ObsidianClient

        state = _resolveState()
        if state is None:
            sys.exit(0)

        try:
            subtasks = state.subtasks or []
        except Exception:
            subtasks = []

        # Prefer the explicit subtask the executor exported; fall back to the first in-progress one.
        sid = os.environ.get("NINE_TO_FIVE_SUBTASK_ID") or None
        if not sid:
            for st in subtasks:
                try:
                    if st.get("status") == "in_progress":
                        sid = st.get("subtask_id")
                        break
                except Exception:
                    continue

        if not sid:
            sys.exit(0)

        ts = datetime.now().isoformat(timespec="seconds")
        line = f"- {ts} | {tool_name} | {file_path}\n"
        ObsidianClient().appendNote(state.subtaskNoteRel(sid), line)
    except Exception:
        pass
    sys.exit(0)


def discordNotify(data):
    """Notification: forward the message to Discord as a compact embed."""
    try:
        message = data.get("message", "") or ""
        import notifications.discord_bot as discord
        discord.sendEmbed(
            {
                "title": "Claude Code notification",
                "color": 3447003,
                "description": message[:1500],
            }
        )
    except Exception:
        pass
    sys.exit(0)


def logAll(data):
    """PostToolUse / any: append one JSON line {time, tool_name} to the log."""
    try:
        from datetime import datetime
        from pathlib import Path

        log_path = Path(LOG_PATH)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        entry = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "tool_name": data.get("tool_name", ""),
        }
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception:
        pass
    sys.exit(0)


def selfModificationGuard(data):
    """PreToolUse: during a SELF-REFERENTIAL task, block edits to the core files
    that run the orchestrator loop (orchestrator.py, main.py, agents/hooks.py, config.py).
    Exits 2 to block; exits 0 otherwise."""
    try:
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {}) or {}
        bash_cmd = ""
        file_path = ""
        if tool_name in ("Edit", "Write", "MultiEdit"):
            file_path = tool_input.get("file_path", "") or ""
        elif tool_name == "Bash":
            # close the Bash write-hole: only inspect commands that WRITE (redirect/sed/mv/cp/tee/git)
            bash_cmd = tool_input.get("command", "") or ""
            low = bash_cmd.lower()
            if not any(w in low for w in (">", "sed -i", "tee ", " mv ", "move ", " cp ", "copy ",
                                          "git checkout", "git reset", "git restore", "rm ")):
                sys.exit(0)
        else:
            sys.exit(0)
        state = _resolveState()
        if state is None:
            sys.exit(0)
        # Hard boundaries are read DYNAMICALLY from the task's universe (set at /goal time).
        universe = state.meta.get("universe") or {}
        boundaries = [str(b) for b in (universe.get("hard_boundaries") or []) if b]
        # ALWAYS enforce the baseline secret/VCS boundaries -- even if the universe is None/empty
        # (legacy or resumed task) so .env/.git/venv/state are never left unprotected.
        for d in (list(getattr(config, "UNIVERSE_DEFAULT_HARD_BOUNDARIES", ()) or ()) if config
                  else [".env", ".git", "venv", "state/tasks"]):
            if d not in boundaries:
                boundaries.append(d)
        # self-referential runs also protect the core files that run the loop.
        if state.meta.get("is_self_referential"):
            for c in (list(getattr(config, "CORE_PROTECTED_FILES", ()) or ()) if config
                      else ["orchestrator.py", "main.py", "agents/hooks.py", "config.py"]):
                if c not in boundaries:
                    boundaries.append(c)
        norm = file_path.replace("/", "\\").lower()
        base = norm.rsplit("\\", 1)[-1]
        cmd_low = bash_cmd.lower()
        for b in boundaries:
            bn = b.replace("/", "\\").lower().strip("\\")
            if not bn:
                continue
            bbase = bn.rsplit("\\", 1)[-1]
            # exact file, a file under a boundary dir, or a path ending in the boundary
            hit = norm == bn or norm.endswith("\\" + bn) or ("\\" + bn + "\\") in norm
            # secret-family: a ".env" boundary also blocks .env.local / .env.production (NOT .envrc)
            if not hit and bbase.startswith(".") and (base == bbase or base.startswith(bbase + ".")):
                hit = True
            # writing Bash command whose target mentions a boundary file (basename token)
            if not hit and bash_cmd and bbase and bbase in cmd_low:
                hit = True
            if hit:
                reason = (f"self_modification_guard: BLOCKED edit to {file_path} -- it is a HARD BOUNDARY "
                          f"of this task's universe. Stay inside the allowed scope.")
                try:
                    import notifications.discord_bot as discord
                    discord.sendBlocked(reason)
                except Exception:
                    pass
                sys.stderr.write(reason + "\n")
                sys.exit(2)
        sys.exit(0)
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)


def main():
    """Dispatch to the requested handler based on argv[1]."""
    hook_name = sys.argv[1] if len(sys.argv) > 1 else ""
    data = _readEvent()

    if hook_name == "block_destructive":
        blockDestructive(data)
    elif hook_name == "write_obsidian":
        writeObsidian(data)
    elif hook_name == "discord_notify":
        discordNotify(data)
    elif hook_name == "log_all":
        logAll(data)
    elif hook_name == "self_modification_guard":
        selfModificationGuard(data)
    else:
        sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # Absolute last-resort guard: never crash Claude Code.
        sys.exit(0)
