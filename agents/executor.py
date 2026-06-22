"""Executor (the hands) -- run Claude Code CLI from an Orchestrator invocation spec.

The Orchestrator (Ollama) no longer hands us a plain prompt; it hands a JSON
INVOCATION SPEC that weaponizes Claude Code's six native primitives:

    {
      "claude_md_inject": "<full per-subtask context -> written to CLAUDE.md>",
      "skills_to_invoke": ["/architect-review"],
      "effort_level": "default|high|xhigh|ultracode",
      "subagent": null | "architect" | "security-reviewer",
      "prompt": "<the instruction>",
      "pre_tool_hooks": ["block_destructive","log_all"],
      "post_tool_hooks": ["write_obsidian","discord_notify"]
    }

This module is the plumbing that ACTIVATES those primitives:
  * CLAUDE.md   -- writes the living per-subtask context to the work dir
  * skills      -- names them in the prompt (Claude invokes /skill natively)
  * subagent    -- instructs delegation to the named read-only subagent
  * hooks       -- loaded from .claude/settings.json via --settings (deterministic)
  * effort      -- effort_level -> --effort {low|medium|high|xhigh|max}
  * model       -- --fallback-model for automatic rate-limit failover

Prompts are delivered over stdin to avoid Windows argv quoting limits; on Windows
the ``claude`` launcher is a ``.cmd`` shim invoked via ``cmd /c``.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Union

import config
from memory.obsidian import writeClaudioMd

LOG = config.getLogger("executor")


def _killProcessTree(pid: int) -> None:
    """Kill a process AND all its descendants.

    The real Windows defect: ``subprocess`` timeout kills only the direct child (the
    ``cmd.exe`` / ``claude.cmd`` launcher). The ``node.exe`` grandchildren that do the
    actual agent work survive as orphans -- they leak, keep running (which is why the
    artifact still lands "after" a timeout), and hold the inherited stdout pipe open so
    the parent's drain blocks ~200s. ``taskkill /T`` walks the whole tree."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=20)
        else:  # posix: kill the process group
            import signal
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    except Exception as e:  # noqa: BLE001
        LOG.warning("process-tree kill of pid %s failed: %s", pid, e)


def _resolveClaudeLauncher() -> list[str]:
    exe = shutil.which("claude")
    if not exe:
        raise FileNotFoundError("claude CLI not found on PATH")
    if os.name == "nt" and exe.lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", exe]
    return [exe]


def normalizeSpec(spec_or_prompt: Union[dict, str, None]) -> dict:
    """Accept a full invocation spec dict OR a bare prompt string; return a full spec."""
    base = {
        "prompt": "", "claude_md_inject": "", "skills_to_invoke": [],
        "effort_level": "default", "subagent": None,
        "pre_tool_hooks": [], "post_tool_hooks": [],
    }
    if isinstance(spec_or_prompt, str):
        base["prompt"] = spec_or_prompt
        return base
    if isinstance(spec_or_prompt, dict):
        for k, v in spec_or_prompt.items():
            base[k] = v
    return base


def _composePrompt(spec: dict, system_prompt: Optional[str], extra: Optional[str]) -> str:
    parts: list[str] = []
    if system_prompt:
        parts.append(system_prompt + "\n\n---\n")
    skills = [s for s in (spec.get("skills_to_invoke") or []) if s]
    if skills:
        parts.append("Invoke these skills as appropriate: " + " ".join(skills))
    subagent = spec.get("subagent")
    if subagent:
        parts.append(f"Use the '{subagent}' subagent for the analysis portion of this task.")
    parts.append(spec.get("prompt") or "")
    if extra:
        parts.append("\n" + extra)
    return "\n\n".join(p for p in parts if p).strip()


def effortFlag(effort_level: str) -> Optional[str]:
    return config.EFFORT_FLAG_MAP.get((effort_level or "default").lower())


# Headless `claude --print --dangerously-skip-permissions` does NOT run .claude
# hooks or permissions, so 9TO5 enforces the block_destructive guardrail
# here, in plumbing we control (deterministic, always-on in autonomous mode).
# Match destructive commands at a COMMAND POSITION (start of line, or after a shell separator)
# with word boundaries -- so benign prose like "format the output" or "run rm later" never blocks.
_DESTRUCTIVE_RE = re.compile(
    r"(?:^|[\n;&|`]\s*)(rm\s+-[rf]{2}\b|rmdir\s+/s\b|del\s+/[fsq]\b|format\s+[a-z]:|drop\s+table\b|"
    r"git\s+push\s+(?:--force\b|-f\b)|mkfs\b|:\(\)\s*\{|>\s*/dev/sd[a-z])",
    re.IGNORECASE | re.MULTILINE,
)


def scanDestructive(text: str) -> list[str]:
    return [m.group(1).strip() for m in _DESTRUCTIVE_RE.finditer(text or "")]


def _alertBlocked(reason: str) -> None:
    try:
        from notifications import discord_bot as discord
        discord.sendBlocked(reason)
    except Exception as e:  # noqa: BLE001
        LOG.warning("blocked-alert failed: %s", e)


def runClaude(spec_or_prompt: Union[dict, str], *, work_dir: Optional[str] = None,
              task_state=None, subtask: Optional[dict] = None,
              system_prompt: Optional[str] = None, extra: Optional[str] = None,
              timeout: Optional[int] = None) -> dict:
    """Prepare the environment from the invocation spec, then fire one Claude run.

    Returns ``{ok, returncode, stdout, stderr, effort, effort_flag, spec, claude_md_path}``.
    """
    spec = normalizeSpec(spec_or_prompt)
    timeout = timeout or config.CLAUDE_CLI_TIMEOUT_SECONDS
    work = str(work_dir) if work_dir else str(config.PROJECT_ROOT)
    Path(work).mkdir(parents=True, exist_ok=True)

    effort = (spec.get("effort_level") or "default").lower()
    flag = effortFlag(effort)

    # 1. living CLAUDE.md (only when we have task context)
    claude_md_path = None
    if task_state is not None:
        try:
            claude_md_path = str(writeClaudioMd(task_state, subtask, spec.get("claude_md_inject", ""), work))
        except Exception as e:  # noqa: BLE001
            LOG.warning("writeClaudioMd failed: %s", e)

    full_prompt = _composePrompt(spec, system_prompt, extra)

    # deterministic block_destructive guardrail (headless mode bypasses Claude hooks)
    if "block_destructive" in (spec.get("pre_tool_hooks") or []):
        hits = scanDestructive(full_prompt)
        if hits:
            reason = f"block_destructive refused subtask -- prompt contains {hits}"
            LOG.warning(reason)
            _alertBlocked(reason)
            return {"ok": False, "returncode": -1, "stdout": "", "stderr": reason, "blocked": True,
                    "effort": effort, "effort_flag": flag, "spec": spec, "claude_md_path": claude_md_path}

    try:
        launcher = _resolveClaudeLauncher()
    except FileNotFoundError as e:
        LOG.error("%s", e)
        return {"ok": False, "returncode": -1, "stdout": "", "stderr": str(e),
                "effort": effort, "effort_flag": flag, "spec": spec, "claude_md_path": claude_md_path}

    cmd = launcher + ["--print", "--dangerously-skip-permissions"]
    # hooks + permissions (deterministic guardrails) load from our settings file
    if config.CLAUDE_SETTINGS_PATH.exists():
        cmd += ["--settings", str(config.CLAUDE_SETTINGS_PATH)]
    # automatic model failover on rate-limit
    cmd += ["--fallback-model", config.FALLBACK_MODEL]
    # reasoning effort selected by the brain
    if flag:
        cmd += ["--effort", flag]
    # make the project's .claude (skills/agents/settings) discoverable from a sub-work-dir
    cmd += ["--add-dir", str(config.PROJECT_ROOT)]
    # self-referential safety: forbid edits to the core files that run the loop
    if task_state is not None and getattr(task_state, "meta", {}).get("is_self_referential"):
        for core in config.CORE_PROTECTED_FILES:
            core_abs = str(config.PROJECT_ROOT / core)
            cmd += ["--disallowedTools", f"Edit({core_abs})", f"Write({core_abs})"]

    LOG.info("Claude run (cwd=%s effort=%s skills=%s subagent=%s hooks=%s/%s prompt=%dch)",
             work, flag or "default", spec.get("skills_to_invoke"), spec.get("subagent"),
             spec.get("pre_tool_hooks"), spec.get("post_tool_hooks"), len(full_prompt))
    # New process group so the timeout path can kill the WHOLE tree (launcher + node grandchildren),
    # not just the direct child -- otherwise orphans leak and block the drain (the real root cause).
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                errors="replace", cwd=work, creationflags=creationflags)
    except Exception as e:  # noqa: BLE001
        LOG.error("Claude launch failed: %s", e)
        return {"ok": False, "returncode": -1, "stdout": "", "stderr": str(e),
                "effort": effort, "effort_flag": flag, "spec": spec, "claude_md_path": claude_md_path}
    try:
        out, err = proc.communicate(input=full_prompt, timeout=timeout)
        out = out or ""
        if "block_destructive" in (spec.get("pre_tool_hooks") or []):
            out_hits = scanDestructive(out)
            if out_hits:
                _alertBlocked(f"block_destructive: executor output shows destructive command(s) {out_hits}")
        return {"ok": proc.returncode == 0, "returncode": proc.returncode,
                "stdout": out, "stderr": err or "",
                "effort": effort, "effort_flag": flag, "spec": spec, "claude_md_path": claude_md_path}
    except subprocess.TimeoutExpired:
        # Kill the entire tree so the work actually stops, procs don't leak, and the drain below
        # returns immediately instead of blocking ~200s on the orphans' inherited stdout pipe.
        _killProcessTree(proc.pid)
        try:
            out, err = proc.communicate(timeout=15)
        except Exception:  # noqa: BLE001
            out, err = "", ""
        LOG.error("Claude timed out after %ss -- process tree killed (captured %d stdout chars)",
                  timeout, len(out or ""))
        return {"ok": False, "returncode": -1, "stdout": out or "",
                "stderr": (err or "") + f"\nTIMEOUT after {timeout}s",
                "effort": effort, "effort_flag": flag, "spec": spec, "claude_md_path": claude_md_path}
    except Exception as e:  # noqa: BLE001
        try:
            _killProcessTree(proc.pid)
        except Exception:  # noqa: BLE001
            pass
        LOG.error("Claude failed: %s", e)
        return {"ok": False, "returncode": -1, "stdout": "", "stderr": str(e),
                "effort": effort, "effort_flag": flag, "spec": spec, "claude_md_path": claude_md_path}
