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
from concurrent.futures import ThreadPoolExecutor

import ollama

import config
from agents import adversary, architect, executor, replanner, verifier
from control import AbortRun, ControlBus
from memory.obsidian import ObsidianClient
from notifications import discord_bot as discord
from notifications.dashboard import DiscordDashboard
from notifications.webdash import startWebDashboard
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


class Orchestrator:
    def __init__(self) -> None:
        self.ollama = ollama.Client(host=config.OLLAMA_HOST)
        self.obs = ObsidianClient()
        self._state_lock = threading.Lock()

    # ===================================================================
    # Brain steps (Ollama authors plan + per-subtask invocation specs)
    # ===================================================================
    def authorSubtaskPlan(self, goal_elaborated: str, architect_doc: str) -> list[dict]:
        system = (
            "You are the Planner for 9TO5. Break the specification into an ordered list of "
            "concrete, independently-executable subtasks for a coding agent. Honor the goal's "
            "constraints (e.g. 'standard library only' => never add dependency-install steps). "
            'Respond with JSON ONLY: {"subtasks": [{"title": "...", "description": "...", "layer": 3, '
            '"effort_level": "default|high|xhigh|ultracode", "verify": {"cmd": "<portable shell command, '
            'prefer python -c, run in the work dir, that proves this subtask is done>", '
            '"expect": "exit_zero"}}]}. Use 2-6 subtasks. expect is one of exit_zero | '
            "stdout_contains:<text> | stdout_regex:<pattern>. Every subtask MUST include a verify block. "
            "Verify commands MUST use ONLY the Python standard library and tools that already exist; "
            "NEVER import third-party packages (no pycodestyle, pytest, numpy, requests). "
            "Verify OBSERVABLE BEHAVIOR by RUNNING the program -- e.g. cmd 'python <absolute file path>' "
            "with expect exit_zero, or expect stdout_contains:<a short string you are CERTAIN it prints>. "
            "NEVER author a verify that imports internal names, functions, or constants -- you do not know "
            "the implementation and guessed symbols will not exist. Never use bash-only syntax like <(...) "
            "or echo -n (host shell is Windows cmd.exe). Keep the plan minimal -- this IS the complete plan."
        )
        user = f"Specification:\n{goal_elaborated}\n\nArchitecture:\n{architect_doc[:4000]}\n\nReturn the plan JSON."
        try:
            resp = self.ollama.chat(
                model=config.OLLAMA_MODEL,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                format="json",
            )
            subs = (json.loads(resp["message"]["content"]) or {}).get("subtasks") or []
        except Exception as e:  # noqa: BLE001
            LOG.warning("plan parse failed (%s); single fallback subtask", e)
            subs = []
        if not subs:
            subs = [{"title": "Implement the goal", "description": goal_elaborated, "layer": 3,
                     "verify": None, "effort_level": "high"}]
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
        try:
            resp = self.ollama.chat(
                model=config.OLLAMA_MODEL,
                messages=[{"role": "system", "content": ORCHESTRATOR_CONSTITUTION},
                          {"role": "user", "content": user}],
                format="json",
            )
            spec = json.loads(resp["message"]["content"])
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
        exec_cwd = exec_cwd or work_dir
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
            result = executor.runClaude(spec, work_dir=exec_cwd, task_state=state, subtask=subtask)
            combined = result.get("stdout") or ""
            if result.get("stderr"):
                combined += "\n[stderr]\n" + result["stderr"]

            vresult = verifier.runVerification(verify_spec, work_dir, result)
            with self._state_lock:
                state.recordVerify(sid, vresult)
            passed = bool(vresult["passed"])
            dashboard.update(state, "verifying",
                             f"{sid} verify {'PASS' if passed else 'FAIL'} ({vresult.get('cmd') or 'exit'})")
            if not passed:
                failure_feedback = (
                    f"cmd: {vresult.get('cmd')}\nexpect: {vresult.get('expect')}\n"
                    f"rc: {vresult.get('returncode')}\nstdout:\n{vresult.get('stdout')}\n"
                    f"stderr:\n{vresult.get('stderr')}"
                )
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

        triggered, reason = adversary.shouldTrigger(combined, position, attempt)
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
        if final == "done":
            decision = replanner.replan(state.meta["goal_elaborated"], state.subtasks, subtask, combined)
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
        guard = 0
        while True:
            guard += 1
            if guard > 100:
                LOG.warning("execution loop guard hit; stopping")
                break
            self._checkControl(state, bus, dashboard)
            if parallelism <= 1:
                subtask = state.nextActionable()
                if subtask is None:
                    break
                position += 1
                self._executeSubtask(state, subtask, architect_doc, work_dir, bus, dashboard, position)
                continue
            # parallel: run the ready set (deps satisfied) concurrently
            ready = self._readySet(state)
            if not ready:
                if state.nextActionable() is None:
                    break
                ready = [state.nextActionable()]
            batch = ready[:parallelism]
            with ThreadPoolExecutor(max_workers=parallelism) as pool:
                futures = []
                for st in batch:
                    position += 1
                    ctx = os.path.join(work_dir, ".sc-ctx", st["subtask_id"])
                    futures.append(pool.submit(self._executeSubtask, state, st, architect_doc,
                                               work_dir, bus, dashboard, position, ctx))
                abort = None
                for f in futures:
                    try:
                        f.result()
                    except AbortRun as e:
                        abort = e
                    except Exception as e:  # noqa: BLE001
                        LOG.warning("parallel subtask error: %s", e)
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
                                  layer=add.get("layer", 3), verify=add.get("verify"))
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
            if resume and state.subtasks:
                architect_doc = self.obs.readNote(state.architectNoteRel()) or "(resumed; architect doc unavailable)"
                dashboard.update(state, "executing", f"resuming at {sum(1 for s in state.subtasks if s['status']=='done')}/{len(state.subtasks)} done")
                LOG.info("Resuming task %s", state.task_id)
            else:
                # --- Phase 1: Architect ---
                state.setStatus("architecting")
                self._checkControl(state, bus, dashboard)
                dashboard.update(state, "architecting", "authoring architecture")
                arch_prompt = architect.authorArchitectPrompt(elaborated)
                arch_res = executor.runClaude(arch_prompt, work_dir=work_dir,
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
                for s in self.authorSubtaskPlan(elaborated, architect_doc)[:config.MAX_SUBTASKS]:
                    state.addSubtask(s.get("title", "untitled"), s.get("description", ""),
                                     layer=s.get("layer", 3), verify=s.get("verify"))
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
            elapsed = time.time() - started
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
            elapsed = time.time() - started
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
        finally:
            bus.setPendingGate(None)
