"""Orchestrator -- the brain (Ollama qwen2.5:7b) + the core autonomous loop.

The Orchestrator authors a JSON INVOCATION SPEC per subtask that weaponizes
Claude Code's six native primitives (CLAUDE.md, skills, subagents, hooks, effort,
model fallback). Python is the plumbing that activates them (agents/executor.py);
Claude Code is the hands.

Phases: Architect -> Plan -> (gate) -> Execute(spec -> verify -> retry) ->
(gate) -> PR/Complete. Supports --resume and parallel subtask execution.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import ollama

import config
from agents import adversary, architect, executor, replanner, verifier
from control import AbortRun, ControlBus
from memory.obsidian import ObsidianClient
from notifications import discord_bot as discord
from notifications.dashboard import DiscordDashboard
from notifications.webdash import startWebDashboard, stopWebDashboard
from state.task import TaskState, nowIso

LOG = config.getLogger("orchestrator")

_YELLOW = 0xF1C40F
_ORANGE = 0xE67E22
_RED = 0xE74C3C


ORCHESTRATOR_CONSTITUTION = (
    "You are the ORCHESTRATOR BRAIN of 9TO5 -- an elite controller that drives Claude "
    "Code (the hands) to maximum capability. You NEVER write code yourself. For each subtask you "
    "author a single JSON INVOCATION SPEC that weaponizes Claude Code's six native primitives.\n\n"
    "Output ONLY one valid JSON object with EXACTLY these keys:\n"
    "{\n"
    '  "claude_md_inject": string,   // full context written to CLAUDE.md and auto-read by Claude '
    "Code: the relevant slice of the elaborated goal, architect decisions, prior outputs, naming "
    "conventions, EXACT absolute file paths to touch, and what to NEVER touch.\n"
    '  "skills_to_invoke": string[], // zero or more of: /architect-review, /write-obsidian-note, /create-pr\n'
    '  "effort_level": string,       // one of: default, high, xhigh, ultracode\n'
    '  "subagent": string|null,      // one of: architect, security-reviewer, or null\n'
    '  "prompt": string,             // the precise, self-contained instruction to execute this subtask\n'
    '  "pre_tool_hooks": string[],   // subset of: block_destructive, log_all\n'
    '  "post_tool_hooks": string[]   // subset of: write_obsidian, discord_notify, log_all\n'
    "}\n\n"
    "THE SIX PRIMITIVES -- when to use each:\n"
    "1. CLAUDE.md (claude_md_inject): ALWAYS fill richly -- this is how the hands get context. "
    "Include exact absolute file paths, the acceptance/verify command, conventions, forbidden files.\n"
    "2. SKILLS: reusable playbooks. /architect-review for design-heavy subtasks; /write-obsidian-note "
    "to persist findings; /create-pr ONLY for a final PR subtask.\n"
    "3. SUBAGENTS: isolation. 'architect' (read-only) for design analysis; 'security-reviewer' "
    "(read-only) before a PR or for security-sensitive code; null for ordinary edits.\n"
    "4. HOOKS: deterministic guardrails. Include 'block_destructive' in pre_tool_hooks for any "
    "subtask that may run Bash. Include 'write_obsidian' and 'log_all' in post_tool_hooks so outputs "
    "are persisted. Add 'discord_notify' for long or important subtasks.\n"
    "5. EFFORT: pick by complexity. Simple file ops => default. Everyday coding => high. Complex "
    "algorithmic/architectural work => xhigh. The hardest, deepest-reasoning subtasks => ultracode.\n"
    "6. MODEL/FALLBACK is handled by the plumbing -- do not set it.\n\n"
    "RULES: Honor the goal's constraints (e.g. 'standard library only' => never instruct installs). "
    "Keep prompt self-contained and imperative. Output ONLY the JSON object, no prose."
)


def _fmtElapsed(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m{s:02d}s"


def _elapsedSince(started_at_iso: str) -> float:
    """Total wall-clock seconds since the task's ORIGINAL start (correct across resumes)."""
    try:
        from datetime import datetime
        return max(0.0, (datetime.now().astimezone() - datetime.fromisoformat(started_at_iso)).total_seconds())
    except Exception:  # noqa: BLE001
        return 0.0


class Orchestrator:
    def __init__(self) -> None:
        self.ollama = ollama.Client(host=config.OLLAMA_HOST, timeout=config.OLLAMA_TIMEOUT_SECONDS)
        self.obs = ObsidianClient()
        self._state_lock = threading.Lock()
        self._selfref_prompt_cache: dict = {}   # task_id -> self-ref system-prompt prefix (built once)

    # ===================================================================
    # Brain steps (Ollama authors plan + per-subtask invocation specs)
    # ===================================================================
    def _ollamaChat(self, system: str, user: str, *, want_json: bool = False, retries: int = 3):
        """Resilient Ollama call: exponential backoff on timeout/connection failure,
        Discord blocked alert on final failure. Returns the response dict or None."""
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        delay = 2.0
        for attempt in range(1, retries + 1):
            try:
                kwargs = {"format": "json"} if want_json else {}
                return self.ollama.chat(model=config.OLLAMA_MODEL, messages=messages, **kwargs)
            except Exception as e:  # noqa: BLE001
                LOG.warning("Ollama call failed (attempt %d/%d): %s", attempt, retries, e)
                if attempt >= retries:
                    try:
                        discord.sendEmbed(discord.blockedEmbed(f"Ollama failed after {retries} attempts: {e}"))
                    except Exception:  # noqa: BLE001
                        pass
                    return None
                time.sleep(delay)
                delay *= 2
        return None

    def _singleDeliverable(self, goal_elaborated: str) -> bool:
        """True when the goal targets at most one distinct file with no multi-deliverable phrasing.
        Used to collapse over-decomposed plans AND to forbid replan-adds that re-pad a trivial goal."""
        import re
        g = (goal_elaborated or "").lower()
        files = set(re.findall(
            r"([A-Za-z0-9_.-]+\.(?:py|md|txt|json|js|ts|tsx|jsx|html|css|csv|ya?ml|cfg|ini|sh|bat|"
            r"go|rs|java|c|cc|cpp|h|hpp|rb|php|swift|kt|sql|toml))\b", g))
        multi_phrase = any(w in g for w in ("multiple files", "several files", "multiple deliverables",
                                            "as well as", "separate "))
        return len(files) <= 1 and not multi_phrase

    def _repairVerify(self, subtask: dict, exec_cwd: str, t0: float = 0.0):
        """SOUND behavioral fallback: find an artifact THIS attempt produced (modified at/after t0) and
        run it (exit_zero), else assert a NON-.py artifact is non-empty. The mtime>=t0 gate means a
        pre-existing input file, an unrelated repo file, or a stale artifact can never false-pass broken
        work. Returns None (=> the subtask stays failed) when no qualifying fresh artifact exists."""
        import re
        import os

        def _fresh(p: str) -> bool:
            try:
                # 2s epsilon absorbs coarse filesystem mtime granularity (FAT/network mounts)
                return os.path.exists(p) and os.path.getmtime(p) >= t0 - 2.0
            except Exception:  # noqa: BLE001
                return False

        text = ((subtask.get("verify") or {}).get("cmd") or "") + "  " + (subtask.get("description") or "")
        # 1) absolute .py referenced by the verify/description that THIS attempt wrote
        for m in re.findall(r"([A-Za-z]:\\[^\s\"'`]+\.py|/[^\s\"'`]+\.py)", text):
            if _fresh(m):
                return {"cmd": f'python "{m}"', "expect": "exit_zero"}
        # 2) relative .py token resolved against exec_cwd (preserve any subpath), written this attempt
        for cand in re.findall(r"([\w./\\-]+\.py)\b", text):
            if os.path.isabs(cand):
                continue
            p = os.path.normpath(os.path.join(exec_cwd, cand))
            if _fresh(p):
                return {"cmd": f'python "{p}"', "expect": "exit_zero"}
        # 3) newest .py written into the work dir DURING this attempt
        try:
            fresh = [os.path.join(exec_cwd, f) for f in os.listdir(exec_cwd)
                     if f.endswith(".py") and _fresh(os.path.join(exec_cwd, f))]
            if fresh:
                return {"cmd": f'python "{max(fresh, key=os.path.getmtime)}"', "expect": "exit_zero"}
        except Exception:  # noqa: BLE001
            pass
        # 4) a NON-.py artifact written this attempt -> non-empty check (never mask a broken .py)
        for m in re.findall(r"([A-Za-z]:\\[^\s\"'`]+\.[A-Za-z0-9]{1,5}|/[^\s\"'`]+\.[A-Za-z0-9]{1,5})", text):
            if m.lower().endswith(".py") or not _fresh(m):
                continue
            return {"cmd": f"python -c \"import os,sys; sys.exit(0 if os.path.getsize(r'{m}')>0 else 1)\"",
                    "expect": "exit_zero"}
        return None

    def authorSubtaskPlan(self, goal_elaborated: str, architect_doc: str) -> list[dict]:
        system = (
            "You are the Planner for 9TO5. Break the specification into the MINIMAL ordered list of "
            "concrete subtasks. For a trivial single-artifact goal (one script/file/function), use EXACTLY "
            "ONE subtask -- never pad to a quota. Use more ONLY for genuinely independent deliverables. "
            "Honor the goal's constraints (e.g. 'standard library only' => no dependency installs).\n"
            'Respond with JSON ONLY: {"subtasks": [{"title": "...", "description": "...", "layer": 3, '
            '"effort_level": "default|high|xhigh|ultracode", "verify": {"cmd": "...", "expect": "..."}}]}. '
            "1-4 subtasks total. Every subtask MUST include a verify block.\n"
            "VERIFY RULES (a bad verify fails correct work -- follow EXACTLY):\n"
            "- Check OBSERVABLE BEHAVIOR only, never implementation details.\n"
            "- Use EXACTLY ONE of these shapes, always with ABSOLUTE file paths under "
            + str(config.PROJECT_ROOT) + ":\n"
            "  (a) cmd = python <ABSOLUTE path> ; expect = exit_zero            (the program runs cleanly)\n"
            "  (b) cmd = python <ABSOLUTE path> ; expect = stdout_contains:<a short string you are CERTAIN it prints>\n"
            '  (c) cmd = python -c "import os; assert os.path.getsize(r\'<ABSOLUTE path>\')>0" ; expect = exit_zero   (file exists, non-empty)\n'
            "- NEVER import a project module or reference an internal function/class/constant name -- a "
            "guessed symbol WILL fail. NEVER use grep/cat/test/ls/findstr/type."
        )
        user = f"Specification:\n{goal_elaborated}\n\nArchitecture:\n{architect_doc[:4000]}\n\nReturn the plan JSON."
        resp = self._ollamaChat(system, user, want_json=True)
        try:
            subs = ((json.loads(resp["message"]["content"]) or {}).get("subtasks") or []) if resp else []
        except Exception as e:  # noqa: BLE001
            LOG.warning("plan parse failed (%s); single fallback subtask", e)
            subs = []
        if not subs:
            subs = [{"title": "Implement the goal", "description": goal_elaborated, "layer": 3,
                     "verify": None, "effort_level": "high"}]
        return subs

    def critiqueSubtaskPlan(self, goal_elaborated: str, subs: list[dict]) -> list[dict]:
        """Self-check the plan BEFORE committing it: (1) deterministically collapse an
        over-decomposed trivial goal to one subtask (zero token cost), then (2) a brain
        self-critique pass that rewrites every verify into a safe behavioral shape."""
        if not subs:
            return subs
        if self._singleDeliverable(goal_elaborated) and len(subs) > 1:
            LOG.info("plan self-check: collapsing %d subtasks -> 1 (single deliverable)", len(subs))
            subs = [{"title": subs[0].get("title", "Implement the goal"),
                     "description": goal_elaborated,
                     "layer": max((s.get("layer", 3) for s in subs), default=3),
                     "effort_level": subs[0].get("effort_level", "high"),
                     "verify": subs[0].get("verify")}]
        system = (
            "You are a strict reviewer of a 9TO5 subtask plan. Return a CORRECTED plan, JSON only, same "
            'schema {"subtasks":[...]}. Make every verify RELIABLE: each verify.cmd must use ABSOLUTE paths '
            "under " + str(config.PROJECT_ROOT) + " and be ONE of: 'python <abs>' (expect exit_zero); "
            "'python <abs>' (expect stdout_contains:<a certain string>); or "
            "'python -c \"import os; assert os.path.getsize(r'<abs>')>0\"' (expect exit_zero). "
            "NEVER import a project module or guess an internal symbol; NEVER use grep/cat/test/findstr. "
            "Collapse any over-decomposition into the fewest subtasks. Preserve titles/descriptions."
        )
        user = f"Goal:\n{goal_elaborated}\n\nPlan to fix:\n{json.dumps({'subtasks': subs})}\n\nReturn corrected JSON."
        resp = self._ollamaChat(system, user, want_json=True)
        try:
            fixed = (json.loads(resp["message"]["content"]) or {}).get("subtasks") if resp else None
            if fixed and isinstance(fixed, list) and all(isinstance(x, dict) and x.get("title") for x in fixed):
                LOG.info("plan self-check: brain corrected plan -> %d subtasks", len(fixed))
                return fixed
        except Exception as e:  # noqa: BLE001
            LOG.warning("plan self-check parse failed (%s); keeping pre-critique plan", e)
        return subs

    def _sanitizeSpec(self, spec: dict, subtask: dict) -> dict:
        spec = spec if isinstance(spec, dict) else {}
        eff = (spec.get("effort_level") or "default").lower()
        skills = spec.get("skills_to_invoke") or []
        pre = spec.get("pre_tool_hooks") or []
        post = spec.get("post_tool_hooks") or []
        sub = spec.get("subagent")
        return {
            "prompt": (spec.get("prompt") or subtask.get("description") or subtask.get("title") or "").strip(),
            "claude_md_inject": (spec.get("claude_md_inject") or "").strip(),
            "effort_level": eff if eff in config.EFFORT_FLAG_MAP else "default",
            "skills_to_invoke": [s for s in skills if s in config.AVAILABLE_SKILLS],
            "subagent": sub if sub in config.AVAILABLE_SUBAGENTS else None,
            "pre_tool_hooks": [h for h in pre if h in config.AVAILABLE_PRE_HOOKS],
            "post_tool_hooks": [h for h in post if h in config.AVAILABLE_POST_HOOKS],
        }

    def _selfRefSystemPrompt(self, state: TaskState) -> str:
        """Cached self-ref system prompt (philosophy + TRIMMED universe + constitution), built once
        per task instead of rebuilt + str()-dumped on every subtask/retry (7B context pressure)."""
        cached = self._selfref_prompt_cache.get(state.task_id)
        if cached:
            return cached
        uni = state.meta.get("universe") or {}

        def _trim(lst, n=10):
            items = [str(x) for x in (lst or [])]
            shown = ", ".join(items[:n]) + (f" (+{len(items) - n} more)" if len(items) > n else "")
            return shown or "(none)"

        prompt = (
            config.SELF_IMPROVEMENT_PHILOSOPHY
            + "\n\nOPERATING UNIVERSE -- allowed: " + _trim(uni.get("allowed_paths"))
            + "; may expand to: " + _trim(uni.get("allowed_to_expand_to"))
            + "; NEVER touch (hard boundaries): " + _trim(uni.get("hard_boundaries"))
            + ". Operate with full intensity INSIDE this universe; never step outside it.\n\n"
            + ORCHESTRATOR_CONSTITUTION
        )
        self._selfref_prompt_cache[state.task_id] = prompt
        return prompt

    def authorInvocationSpec(self, state: TaskState, subtask: dict, architect_doc: str,
                             failure_feedback: str | None = None) -> dict:
        """Ollama authors the JSON invocation spec for ONE subtask (the brain's core act)."""
        verify = subtask.get("verify") or {}
        user = (
            f"Overall goal (elaborated):\n{state.meta['goal_elaborated']}\n\n"
            f"Architecture (excerpt):\n{architect_doc[:1500]}\n\n"
            f"Subtask {subtask['subtask_id']}: {subtask['title']}\n{subtask['description']}\n\n"
            f"Acceptance verify command: {verify.get('cmd')} (expect: {verify.get('expect')})\n"
            f"Suggested effort: {subtask.get('effort_level', 'default')}\n"
            f"Working directory: {config.PROJECT_ROOT}\n\n"
        )
        if failure_feedback:
            user += f"PREVIOUS ATTEMPT FAILED THE VERIFICATION:\n{failure_feedback[:1200]}\n\n"
        user += "Output ONLY the JSON invocation spec for THIS subtask."
        system_prompt = self._selfRefSystemPrompt(state) if state.meta.get("is_self_referential") \
            else ORCHESTRATOR_CONSTITUTION
        resp = self._ollamaChat(system_prompt, user, want_json=True)
        try:
            spec = json.loads(resp["message"]["content"]) if resp else {}
        except Exception as e:  # noqa: BLE001
            LOG.warning("invocation-spec parse failed (%s); using minimal spec", e)
            spec = {}
        return self._sanitizeSpec(spec, subtask)

    # ===================================================================
    # Control plane (poll Discord + drain ControlBus between steps)
    # ===================================================================
    def _translateDiscord(self, bus: ControlBus) -> None:
        msgs, latest = discord.fetchMessagesAfter(bus.getSeen())
        if latest != bus.getSeen():
            bus.setSeen(latest)
        for m in msgs:
            if m["author_is_bot"]:
                continue
            raw = m["content"].strip()
            c = raw.lower()
            if not c.startswith("!"):
                continue
            if c.startswith("!abort"):
                bus.requestAbort()
            elif c.startswith("!pause"):
                bus.requestPause()
            elif c.startswith("!resume"):
                bus.clearPause()
            elif c.startswith("!approve"):
                gate = bus.getPendingGate()
                if gate:
                    bus.decide(gate, "approve")
            elif c.startswith("!reject"):
                gate = bus.getPendingGate()
                if gate:
                    bus.decide(gate, "reject")
            elif c.startswith("!skip"):
                parts = raw.split()
                if len(parts) > 1:
                    bus.pushOp({"op": "skip", "subtask_id": parts[1]})
            elif c.startswith("!add"):
                title = raw[4:].strip()
                if title:
                    bus.pushOp({"op": "add", "title": title, "description": title})
            elif c.startswith("!retry"):
                bus.pushOp({"op": "retry"})

    def _applyOps(self, state: TaskState, bus: ControlBus, dashboard: DiscordDashboard) -> None:
        for op in bus.drainOps():
            kind = op.get("op")
            with self._state_lock:
                if kind == "skip":
                    sid = op.get("subtask_id")
                    st = state.getSubtask(sid)
                    if st and st["status"] == "pending":
                        state.updateSubtask(sid, status="removed")
                        dashboard.event(f"skipped {sid}")
                elif kind == "add":
                    st = state.addSubtask(op.get("title", "untitled"), op.get("description", ""))
                    dashboard.event(f"added {st['subtask_id']}")
                elif kind == "retry":
                    cur = next((s for s in state.subtasks if s["status"] == "in_progress"), None)
                    if cur:
                        state.updateSubtask(cur["subtask_id"], status="pending")
                        dashboard.event(f"retry {cur['subtask_id']}")

    def _checkControl(self, state: TaskState, bus: ControlBus, dashboard: DiscordDashboard,
                      gate: str | None = None) -> None:
        self._translateDiscord(bus)
        self._applyOps(state, bus, dashboard)
        while bus.isPaused() and not bus.isAbort():
            dashboard.update(state, "paused", "paused -- waiting for !resume")
            time.sleep(config.DISCORD_POLL_SECONDS)
            self._translateDiscord(bus)
        if bus.isAbort():
            raise AbortRun("abort requested")
        if gate and state.meta.get("control_mode") == "gated":
            bus.clearDecision(gate)
            bus.setPendingGate(gate)
            discord.sendEmbed({
                "title": f"Approval needed: {gate}",
                "color": _YELLOW,
                "fields": [{"name": "Action", "value": "reply `!approve` / `!reject` or use the web dashboard"}],
            }, content=discord.humanPing())
            dashboard.update(state, f"awaiting {gate}", f"awaiting approval for gate: {gate}")
            while True:
                self._translateDiscord(bus)
                self._applyOps(state, bus, dashboard)   # apply queued !add/!skip live while parked
                if bus.isAbort():
                    bus.setPendingGate(None)
                    raise AbortRun("aborted at gate")
                decision = bus.getDecision(gate)
                if decision == "approve":
                    dashboard.event(f"gate {gate}: approved")
                    break
                if decision == "reject":
                    bus.setPendingGate(None)
                    raise AbortRun(f"gate '{gate}' rejected")
                time.sleep(config.DISCORD_POLL_SECONDS)
            bus.setPendingGate(None)

    # ===================================================================
    # Obsidian note builders
    # ===================================================================
    def writeIndex(self, state: TaskState) -> None:
        m = state.meta
        done, total = state.progress()
        lines = [
            f"# 9TO5 task {state.task_id}",
            "",
            f"- **Status:** {m['status']}  ·  mode `{m.get('control_mode', 'watch')}`",
            f"- **Goal (raw):** {m['goal_raw']}",
            f"- **Started:** {m['started_at']}  ·  **Deadline:** {m['deadline_at']}",
            f"- **Progress:** {done}/{total} subtasks done",
            f"- **Architect doc:** {state.data['plan']['architect_design_doc'] or '-'}",
            "",
            "## Subtasks",
        ]
        for s in state.subtasks:
            vr = s.get("verify_result")
            mark = "" if vr is None else (" ✅" if vr.get("passed") else " ❌")
            eff = (s.get("session") or {}).get("effort") or ""
            lines.append(f"- `{s['subtask_id']}` [{s['status']}]{mark} {s['title']} "
                         f"{('· ' + eff) if eff else ''} -> {s.get('output_ref') or '-'}")
        lines += ["", "## Adversary reviews"]
        for r in state.data["adversary_reviews"]:
            lines.append(f"- {r['subtask_id']}: {r['verdict']} ({r['trigger_reason']})")
        lines += ["", "## Notifications"]
        for n in state.data["notifications"]:
            lines.append(f"- {n['at']} {n['kind']}: {n['detail']}")
        self.obs.writeNote(state.indexNoteRel(), "\n".join(lines) + "\n")

    def _subtaskNote(self, state: TaskState, subtask: dict, spec: dict, result: dict,
                     vresult: dict | None) -> str:
        verify_block = ""
        if vresult:
            verify_block = (
                f"## Verification\n\n- **Passed:** {vresult.get('passed')}\n"
                f"- **Command:** `{vresult.get('cmd')}`  (expect: {vresult.get('expect')})\n"
                f"- **Return code:** {vresult.get('returncode')}\n\n"
                f"```\n{(vresult.get('stdout') or '').strip()}\n{(vresult.get('stderr') or '').strip()}\n```\n\n"
            )
        spec_block = (
            f"## Invocation spec\n\n"
            f"- **Effort:** {spec.get('effort_level')}\n"
            f"- **Skills:** {spec.get('skills_to_invoke')}\n"
            f"- **Subagent:** {spec.get('subagent')}\n"
            f"- **Pre hooks:** {spec.get('pre_tool_hooks')}  ·  **Post hooks:** {spec.get('post_tool_hooks')}\n\n"
            f"### CLAUDE.md inject\n\n```\n{(spec.get('claude_md_inject') or '')[:1500]}\n```\n\n"
            f"### Prompt\n\n```\n{spec.get('prompt')}\n```\n\n"
        )
        return (
            f"# {subtask['subtask_id']} -- {subtask['title']}\n\n"
            f"- **Status:** {subtask['status']}\n"
            f"- **Return code:** {result.get('returncode')}\n\n"
            f"{verify_block}{spec_block}"
            f"## Executor (Claude Code CLI) output\n\n```\n{(result.get('stdout') or '').strip()}\n```\n\n"
            + (f"## stderr\n\n```\n{result['stderr'].strip()}\n```\n" if result.get("stderr") else "")
        )

    def _reviewNote(self, subtask: dict, reason: str, review: dict, output: str) -> str:
        return (
            f"# Adversary review -- {subtask['subtask_id']}\n\n"
            f"- **Trigger:** {reason}\n- **Verdict:** {review['verdict']}\n"
            f"- **Stub:** {review.get('stub', False)}\n\n## Notes\n{review.get('notes', '')}\n\n"
            f"## Reviewed output (excerpt)\n\n```\n{(output or '')[:1500]}\n```\n"
        )

    # ===================================================================
    # Phase 4 -- PR creation (best effort; skips gracefully)
    # ===================================================================
    def createPullRequest(self, state: TaskState, work_dir: str) -> dict:
        def git(*args: str) -> subprocess.CompletedProcess:
            return subprocess.run(["git", *args], cwd=work_dir, capture_output=True, text=True)

        chk = git("rev-parse", "--is-inside-work-tree")
        if chk.returncode != 0 or "true" not in (chk.stdout or "").lower():
            LOG.info("PR skipped: %s is not a git repository", work_dir)
            return {"skipped": True, "reason": "not a git repository"}
        branch = f"9to5/{state.task_id[:8]}"
        git("checkout", "-B", branch)
        git("add", "-A")
        git("commit", "-m", f"9TO5: {state.meta['goal_raw'][:60]}")
        push = git("push", "-u", "origin", branch)
        if push.returncode != 0:
            return {"skipped": True, "reason": f"git push failed: {(push.stderr or '')[:200]}"}
        pr = subprocess.run(["gh", "pr", "create", "--fill", "--head", branch],
                            cwd=work_dir, capture_output=True, text=True)
        if pr.returncode != 0:
            return {"skipped": True, "reason": f"gh pr create failed: {(pr.stderr or '')[:200]}"}
        return {"ok": True, "url": (pr.stdout or "").strip()}

    # ===================================================================
    # Phase 3 -- execution (per-subtask unit + serial / parallel loops)
    # ===================================================================
    def _executeSubtask(self, state: TaskState, subtask: dict, architect_doc: str, work_dir: str,
                        bus: ControlBus, dashboard: DiscordDashboard, position: int,
                        exec_cwd: str | None = None) -> str:
        sid = subtask["subtask_id"]
        verify_spec = subtask.get("verify")
        exec_cwd = exec_cwd or self._execCwd(state, sid, work_dir)
        dashboard.update(state, "executing", f"-> {sid} {subtask['title']}")

        attempt = 0
        passed = False
        failure_feedback = None
        spec: dict = {}
        result = {"ok": False, "stdout": "", "stderr": "", "returncode": None}
        vresult: dict | None = None
        combined = ""

        while attempt < config.MAX_SUBTASK_ATTEMPTS and not passed:
            attempt += 1
            with self._state_lock:
                state.updateSubtask(sid, status="in_progress", started_at=subtask.get("started_at") or nowIso())
            spec = self.authorInvocationSpec(state, subtask, architect_doc, failure_feedback)
            with self._state_lock:
                sess = dict(subtask.get("session") or {})
                sess.update({"effort": spec.get("effort_level"), "model": config.PRIMARY_MODEL,
                             "skills": spec.get("skills_to_invoke"), "subagent": spec.get("subagent"),
                             "attempts": attempt})
                state.updateSubtask(sid, session=sess)
            LOG.info("Subtask %s attempt %d/%d effort=%s", sid, attempt, config.MAX_SUBTASK_ATTEMPTS,
                     spec.get("effort_level"))
            dashboard.update(state, "executing", f"{sid} attempt {attempt} · effort {spec.get('effort_level')}",
                             effort=spec.get("effort_level"))
            attempt_started = time.time()
            result = executor.runClaude(spec, work_dir=exec_cwd, task_state=state, subtask=subtask)
            combined = result.get("stdout") or ""
            if result.get("stderr"):
                combined += "\n[stderr]\n" + result["stderr"]

            vresult = verifier.runVerification(verify_spec, exec_cwd, result)
            passed = bool(vresult["passed"])
            # VERIFY REPAIR: a brittle brain-authored verify must NEVER fail correct work. Re-verify with a
            # robust behavioral fallback (run the actual artifact). NOT gated on the executor exit code --
            # headless claude exits nonzero for benign reasons (fallback-model switch, a non-fatal tool
            # call); the artifact running cleanly is the real correctness signal. Only a genuinely broken
            # program (its own `python <file>` fails) stays failed.
            if not passed:
                repaired = self._repairVerify(subtask, exec_cwd, attempt_started)
                same = bool(repaired) and (repaired.get("cmd"), repaired.get("expect")) == \
                    ((verify_spec or {}).get("cmd"), (verify_spec or {}).get("expect"))
                if repaired and not same:
                    rv = verifier.runVerification(repaired, exec_cwd, result)
                    if rv.get("passed"):
                        LOG.info("%s: brittle verify repaired -> PASS via %s", sid, repaired["cmd"])
                        vresult, passed = rv, True
            with self._state_lock:
                state.recordVerify(sid, vresult)
            dashboard.update(state, "verifying",
                             f"{sid} verify {'PASS' if passed else 'FAIL'} ({vresult.get('cmd') or 'exit'})")
            if not passed:
                failure_feedback = (
                    f"cmd: {vresult.get('cmd')}\nexpect: {vresult.get('expect')}\n"
                    f"rc: {vresult.get('returncode')}\nstdout:\n{vresult.get('stdout')}\n"
                    f"stderr:\n{vresult.get('stderr')}"
                )
            self._translateDiscord(bus)
            while bus.isPaused() and not bus.isAbort():   # honor !pause mid-subtask, not just between
                dashboard.update(state, "paused", f"{sid} paused -- waiting for !resume")
                time.sleep(config.DISCORD_POLL_SECONDS)
                self._translateDiscord(bus)
            if bus.isAbort():
                raise AbortRun("abort requested")
            if (state.getSubtask(sid) or {}).get("status") == "removed":
                return "removed"

        with self._state_lock:
            note = self._subtaskNote(state, subtask, spec, result, vresult)
            written = self.obs.writeNote(state.subtaskNoteRel(sid), note)
            state.updateSubtask(sid, output_ref=written.get("rel_path"))

        if (state.getSubtask(sid) or {}).get("status") == "removed":
            return "removed"

        # heartbeat off a STABLE terminal-subtask count, not the mutable loop/scheduler position
        heartbeat_ordinal = sum(1 for s in state.subtasks if s["status"] in ("done", "failed", "removed")) + 1
        triggered, reason = adversary.shouldTrigger(combined, heartbeat_ordinal, attempt)
        if triggered:
            discord.sendEmbed(discord.adversaryTriggeredEmbed(subtask["title"], reason))
            rv = adversary.review(subtask["title"], reason, combined)
            with self._state_lock:
                state.addNotification("adversary_triggered", f"{sid}: {reason}")
                self.obs.writeNote(state.subtaskReviewNoteRel(sid), self._reviewNote(subtask, reason, rv, combined))
                state.addAdversaryReview(sid, reason, rv["verdict"], state.subtaskReviewNoteRel(sid))

        final = "done" if passed else "failed"
        with self._state_lock:
            state.updateSubtask(sid, status=final, completed_at=nowIso())
            if not passed:
                state.addNotification("subtask_failed", f"{sid} failed verification after {attempt} attempts")
        if not passed:
            discord.sendEmbed({
                "title": "Subtask failed verification",
                "color": _ORANGE,
                "fields": [
                    {"name": "Subtask", "value": f"{sid} {subtask['title']}"[:200]},
                    {"name": "Attempts", "value": str(attempt)},
                    {"name": "Verify", "value": (str(vresult.get("cmd")) if vresult else "-")[:200]},
                ],
            })
        dashboard.update(state, "executing", f"{sid} -> {final}")

        # Replan ONLY after a subtask that PASSED. Replanning after failures is the
        # churn engine (fail -> add remediation -> fail -> add ...) that livelocks runs;
        # the executor already retries failed subtasks up to MAX_SUBTASK_ATTEMPTS.
        if final == "done" and not self._singleDeliverable(state.meta.get("goal_elaborated", "")):
            decision = replanner.replan(state.meta["goal_elaborated"], state.subtasks, subtask, combined,
                                        self_referential=bool(state.meta.get("is_self_referential")))
            if decision.get("action") == "mutate" and (decision.get("add") or decision.get("remove")):
                dashboard.update(state, "replanning", f"replanning after {sid}")
                with self._state_lock:
                    self._applyReplan(state, decision)
        with self._state_lock:
            self.writeIndex(state)
        return final

    def runExecutionLoop(self, state: TaskState, architect_doc: str, work_dir: str,
                         bus: ControlBus, dashboard: DiscordDashboard, parallelism: int = 1) -> None:
        position = 0
        iters = 0
        no_progress = 0
        prev_terminal = -1
        while True:
            iters += 1
            # Guard on NO PROGRESS (subtasks reaching a terminal state), not raw iteration count,
            # so a legitimately long 8-hour run with many subtasks is never false-aborted; only a
            # true livelock (status churning with nothing completing) trips it.
            terminal = sum(1 for s in state.subtasks if s["status"] in ("done", "failed", "removed"))
            no_progress = no_progress + 1 if terminal == prev_terminal else 0
            prev_terminal = terminal
            if no_progress > 40 or iters > 2000:
                LOG.error("execution loop livelock (no progress in %d iters); aborting", no_progress)
                try:
                    discord.sendEmbed(discord.blockedEmbed("Execution loop guard tripped (possible livelock) — aborting"),
                                      content=discord.humanPing())
                except Exception:  # noqa: BLE001
                    pass
                raise AbortRun("execution loop guard tripped (livelock)")
            self._checkControl(state, bus, dashboard)
            if parallelism <= 1:
                subtask = state.nextActionable()
                if subtask is None:
                    break
                position += 1
                try:
                    self._executeSubtask(state, subtask, architect_doc, work_dir, bus, dashboard, position)
                except AbortRun:
                    raise
                except Exception as e:  # noqa: BLE001 -- one bad subtask must not kill the run
                    LOG.error("Subtask %s crashed: %s", subtask.get("subtask_id"), e, exc_info=True)
                    try:
                        discord.sendEmbed(discord.blockedEmbed(f"Subtask {subtask.get('subtask_id')} crashed: {e}"))
                    except Exception:  # noqa: BLE001
                        pass
                    with self._state_lock:
                        state.updateSubtask(subtask["subtask_id"], status="failed", completed_at=nowIso())
                        state.addNotification("subtask_crashed", f"{subtask.get('subtask_id')}: {e}")
                continue
            # parallel: run the ready set (deps satisfied) concurrently
            ready = self._readySet(state)
            if not ready:
                if state.nextActionable() is None:
                    break
                ready = [state.nextActionable()]
            batch = ready[:parallelism]
            with ThreadPoolExecutor(max_workers=parallelism) as pool:
                futures = {}
                for st in batch:
                    position += 1
                    ctx = os.path.join(work_dir, ".sc-ctx", st["subtask_id"])
                    futures[pool.submit(self._executeSubtask, state, st, architect_doc,
                                        work_dir, bus, dashboard, position, ctx)] = st
                abort = None
                for f in as_completed(futures):
                    st = futures[f]
                    try:
                        f.result()
                    except AbortRun as e:
                        abort = e
                        for pending in futures:   # stop scheduling the rest of the batch promptly
                            pending.cancel()
                        break
                    except Exception as e:  # noqa: BLE001 -- a crashed worker must not strand the subtask
                        LOG.error("parallel subtask %s crashed: %s", st.get("subtask_id"), e, exc_info=True)
                        with self._state_lock:
                            state.updateSubtask(st["subtask_id"], status="failed", completed_at=nowIso())
                            state.addNotification("subtask_crashed", f"{st.get('subtask_id')}: {e}")
                if abort is not None:
                    raise abort

    def _readySet(self, state: TaskState) -> list[dict]:
        out = []
        for s in state.subtasks:
            if s["status"] != "pending":
                continue
            deps = s.get("depends_on") or []
            if all((state.getSubtask(d) or {}).get("status") == "done" for d in deps):
                out.append(s)
        return out

    def _applyReplan(self, state: TaskState, decision: dict) -> None:
        diff = [f"## Replan @ {nowIso()}", f"Reason: {decision.get('reason', '')}", ""]
        active = sum(1 for s in state.subtasks if s["status"] != "removed")
        for add in decision.get("add", []) or []:
            if active >= config.MAX_SUBTASKS:
                LOG.info("replan add skipped: MAX_SUBTASKS (%d) reached", config.MAX_SUBTASKS)
                diff.append(f"(skipped add '{add.get('title')}' -- MAX_SUBTASKS cap)")
                break
            st = state.addSubtask(add.get("title", "untitled"), add.get("description", ""),
                                  layer=add.get("layer", 3), verify=verifier.sanitizeVerify(add.get("verify")))
            active += 1
            diff.append(f"+ {st['subtask_id']} {st['title']}")
        for rid in decision.get("remove", []) or []:
            st = state.getSubtask(rid)
            if st and st["status"] == "pending":
                state.updateSubtask(rid, status="removed")
                diff.append(f"- {rid} {st['title']}")
        diff.append("")
        state.addNotification("replan", decision.get("reason", "")[:200])
        self.obs.appendNote(state.replanLogRel(), "\n".join(diff) + "\n")
        LOG.info("Replan applied: %s", decision.get("reason", ""))

    # ===================================================================
    # Self-referential support (9to5 modifying itself)
    # ===================================================================
    def _detectSelfReferential(self, state: TaskState, work_dir: str) -> bool:
        text = f"{state.meta.get('goal_raw', '')} {state.meta.get('goal_elaborated', '')}".lower()
        root = str(config.PROJECT_ROOT).lower()
        # Explicit self-targeting keywords only -- NOT the bare install path, which
        # appears in any goal that writes a file under C:\supercritical\... .
        markers = ["9to5", "itself", "self-referential", "self-modify", "self modify",
                   "self-improve", "its own code"]
        same_dir = os.path.abspath(work_dir).lower() == root
        return same_dir or any(m in text for m in markers)

    def _prepareSelfReferential(self, state: TaskState, work_dir: str,
                                bus: ControlBus, dashboard: DiscordDashboard) -> None:
        branch = f"{config.SELF_REF_BRANCH_PREFIX}{state.task_id[:8]}"
        state.markSelfReferential(branch)
        try:
            chk = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                                 cwd=work_dir, capture_output=True, text=True)
            if chk.returncode == 0 and "true" in (chk.stdout or "").lower():
                exists = subprocess.run(["git", "rev-parse", "--verify", branch],
                                        cwd=work_dir, capture_output=True, text=True).returncode == 0
                subprocess.run(["git", "checkout", branch] if exists else ["git", "checkout", "-B", branch],
                               cwd=work_dir, capture_output=True, text=True)
                LOG.info("Self-referential task -> %s branch %s", "resumed" if exists else "created", branch)
            else:
                LOG.warning("Self-ref task but %s is not a git repo; no isolation branch", work_dir)
        except Exception as e:  # noqa: BLE001
            LOG.warning("self-ref branch creation failed: %s", e)
        discord.sendEmbed({
            "title": "🧬 Self-referential run (9to5 editing 9to5)",
            "color": 0x9B59B6,
            "fields": [
                {"name": "Isolation branch", "value": f"`{branch}`"},
                {"name": "Protected core files", "value": ", ".join(config.CORE_PROTECTED_FILES)},
            ],
        }, content=discord.humanPing())
        dashboard.event(f"self-referential · branch {branch}")

    def _execCwd(self, state: TaskState, sid: str | None, work_dir: str) -> str:
        """For self-referential runs, give the executor an isolated cwd so the living
        CLAUDE.md never clobbers the project's own CLAUDE.md. The project root remains
        an ancestor (auto-read for architecture); edits/verify use absolute paths."""
        if state.meta.get("is_self_referential") and os.path.abspath(work_dir) == os.path.abspath(str(config.PROJECT_ROOT)):
            ctx = os.path.join(str(config.PROJECT_ROOT), ".sc-ctx", sid or "architect")
            os.makedirs(ctx, exist_ok=True)
            return ctx
        return work_dir

    # ===================================================================
    # Full pipeline (with resume + parallelism)
    # ===================================================================
    def runFull(self, state: TaskState, work_dir: str, auto_pr: bool = True,
                control_mode: str | None = None, resume: bool = False, parallelism: int = 1) -> dict:
        if control_mode:
            state.setControlMode(control_mode)
        bus = ControlBus(state.task_id)
        if not resume:
            bus.clear()
        dashboard = DiscordDashboard()
        web_url = startWebDashboard(state.task_id)
        dashboard.start(state, "resuming" if resume else "starting")
        started = time.time()
        elaborated = state.meta["goal_elaborated"] or state.meta["goal_raw"]
        self.writeIndex(state)

        try:
            if not resume and self._detectSelfReferential(state, work_dir):
                self._prepareSelfReferential(state, work_dir, bus, dashboard)
            if resume and state.subtasks:
                for s in state.subtasks:   # un-strand subtasks left mid-flight by a prior crash
                    if s["status"] == "in_progress":
                        state.updateSubtask(s["subtask_id"], status="pending")
                architect_doc = self.obs.readNote(state.architectNoteRel()) or "(resumed; architect doc unavailable)"
                prior = "\n".join(
                    f"- {s['subtask_id']} [{s['status']}] {s['title']}"
                    + (" (verify PASS)" if (s.get('verify_result') or {}).get('passed') else "")
                    for s in state.subtasks if s['status'] in ('done', 'failed', 'removed'))
                architect_doc += f"\n\n## Prior progress (resumed task)\n{prior or '(none)'}"
                if state.meta.get("is_self_referential"):
                    self._prepareSelfReferential(state, work_dir, bus, dashboard)
                done_n = sum(1 for s in state.subtasks if s['status'] == 'done')
                dashboard.update(state, "executing", f"resuming at {done_n}/{len(state.subtasks)} done")
                LOG.info("Resuming task %s (%d/%d done)", state.task_id, done_n, len(state.subtasks))
            else:
                # --- Phase 1: Architect ---
                state.setStatus("architecting")
                self._checkControl(state, bus, dashboard)
                dashboard.update(state, "architecting", "authoring architecture")
                arch_prompt = architect.authorArchitectPrompt(elaborated)
                arch_res = executor.runClaude(arch_prompt, work_dir=self._execCwd(state, "architect", work_dir),
                                              system_prompt=architect.ARCHITECT_SYSTEM_PROMPT, task_state=state)
                architect_doc = (arch_res.get("stdout") or "").strip() or "(architect produced no output)"
                self.obs.writeNote(state.architectNoteRel(), architect_doc)
                state.setArchitectDoc(state.architectNoteRel())
                discord.sendEmbed(discord.architectDoneEmbed(state.architectNoteRel()))
                state.addNotification("architect_done", state.architectNoteRel())
                dashboard.update(state, "architecting", f"architecture done ({len(architect_doc)} chars)")

                # --- Phase 2: Planning ---
                state.setStatus("planning")
                dashboard.update(state, "planning", "authoring subtask plan")
                plan = self.critiqueSubtaskPlan(elaborated, self.authorSubtaskPlan(elaborated, architect_doc))
                for s in plan[:config.MAX_SUBTASKS]:
                    state.addSubtask(s.get("title", "untitled"), s.get("description", ""),
                                     layer=s.get("layer", 3), verify=verifier.sanitizeVerify(s.get("verify")))
                discord.sendEmbed(discord.planningStartEmbed(state.meta["goal_raw"], len(state.subtasks)))
                state.addNotification("planning_start", f"{len(state.subtasks)} subtasks")
                self.writeIndex(state)
                dashboard.update(state, "planning", f"planned {len(state.subtasks)} subtasks")
                self._checkControl(state, bus, dashboard, gate="plan")

            # --- Phase 3: Execution ---
            state.setStatus("executing")
            self.runExecutionLoop(state, architect_doc, work_dir, bus, dashboard, parallelism=parallelism)

            # --- Phase 4: PR + complete ---
            self._checkControl(state, bus, dashboard, gate="pre_pr")
            pr = self.createPullRequest(state, work_dir) if auto_pr else {"skipped": True, "reason": "--no-pr"}
            elapsed = _elapsedSince(state.meta["started_at"])
            done, total = state.progress()
            final_status = "done" if (total > 0 and done == total) else "partial"
            state.setStatus(final_status)
            self.writeIndex(state)
            pr_link = pr.get("url") or f"skipped: {pr.get('reason', '')}"
            discord.sendEmbed(discord.completeEmbed(state, pr_link, _fmtElapsed(elapsed)))
            state.addNotification("complete", pr_link)
            dashboard.update(state, "complete", f"done {done}/{total} · {_fmtElapsed(elapsed)}")
            LOG.info("Run complete: status=%s subtasks=%d/%d elapsed=%s",
                     final_status, done, total, _fmtElapsed(elapsed))
            return {
                "task_id": state.task_id, "status": final_status, "elapsed_seconds": round(elapsed, 1),
                "web_dashboard": web_url,
                "subtasks": [
                    {"subtask_id": s["subtask_id"], "title": s["title"], "status": s["status"],
                     "effort": (s.get("session") or {}).get("effort"),
                     "verified": (s.get("verify_result") or {}).get("passed") if s.get("verify_result") else None}
                    for s in state.subtasks
                ],
                "pr": pr, "obsidian": state.data["obsidian"],
            }

        except (AbortRun, KeyboardInterrupt) as e:
            reason = "ctrl-c" if isinstance(e, KeyboardInterrupt) else str(e)
            elapsed = _elapsedSince(state.meta["started_at"])
            state.setStatus("aborted", blocked_reason=reason)
            self.writeIndex(state)
            discord.sendEmbed({"title": "Run aborted", "color": _RED,
                               "fields": [{"name": "Reason", "value": reason[:500]},
                                          {"name": "Elapsed", "value": _fmtElapsed(elapsed)}]},
                              content=discord.humanPing())
            state.addNotification("aborted", reason)
            dashboard.update(state, "aborted", f"aborted: {reason}")
            LOG.warning("Run aborted: %s", reason)
            return {"task_id": state.task_id, "status": "aborted", "reason": reason,
                    "elapsed_seconds": round(elapsed, 1), "web_dashboard": web_url,
                    "subtasks": [{"subtask_id": s["subtask_id"], "status": s["status"]} for s in state.subtasks]}
        except Exception as e:  # noqa: BLE001 -- the core loop must NEVER crash silently
            elapsed = _elapsedSince(state.meta["started_at"])
            LOG.error("Run crashed: %s", e, exc_info=True)
            try:
                state.setStatus("blocked", blocked_reason=str(e))
                self.writeIndex(state)
            except Exception:  # noqa: BLE001
                pass
            try:
                discord.sendEmbed(discord.blockedEmbed(f"9to5 run crashed: {e}"), content=discord.humanPing())
                dashboard.update(state, "blocked", f"crashed: {e}")
            except Exception:  # noqa: BLE001
                pass
            return {"task_id": state.task_id, "status": "blocked", "reason": str(e),
                    "elapsed_seconds": round(elapsed, 1), "web_dashboard": web_url,
                    "subtasks": [{"subtask_id": s["subtask_id"], "status": s["status"]} for s in state.subtasks]}
        finally:
            bus.setPendingGate(None)
            stopWebDashboard()
