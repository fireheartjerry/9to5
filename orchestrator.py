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
import knowledge
from agents import adversary, architect, clarifier, executor, replanner, verifier
from control import AbortRun, ControlBus
from learning import policy, prompts
from memory import experience, retrieval
from memory.obsidian import ObsidianClient
from notifications import audit
from notifications import commands
from notifications import discord_bot as discord
from notifications.dashboard import DiscordDashboard
from notifications.webdash import startWebDashboard, stopWebDashboard
from state.task import TaskState, nowIso

LOG = config.getLogger("orchestrator")

# ============================================================================
# Living Claude Code knowledge -- injected into EVERY Ollama system prompt. The
# compressed summary is cached in knowledge.py (shared by the orchestrator brain
# AND elaborator/replanner/architect). These guards just keep the heavy web
# refresh to once per process.
# ============================================================================
_KNOWLEDGE_REFRESHED: bool = False    # ensures the heavy (web) refresh runs once per process
_KNOWLEDGE_LOCK = threading.Lock()


def _knowledgeFresh(kpath, max_age_hours: float) -> bool:
    """True when the on-disk knowledge doc is younger than max_age_hours."""
    try:
        if not kpath.exists():
            return False
        from datetime import datetime
        age_h = (datetime.now().timestamp() - kpath.stat().st_mtime) / 3600.0
        return age_h < max_age_hours
    except Exception:  # noqa: BLE001
        return False


def refreshClaudeKnowledge(obs: "ObsidianClient | None" = None, *, fetch_web: bool | None = None,
                           log_session: bool = True, force: bool = False) -> str:
    """Living knowledge refresh -- the asymmetry exploit (Python has internet; Ollama
    does not). Runs at the start of every 9to5 session before any Ollama call.

    Steps (all best-effort; never raises out):
      1. Fetch the latest Claude Code docs + changelog from docs.claude.com /
         docs.anthropic.com (CLI, hooks, MCP, skills, subagents, memory, settings ...).
      2. Recursively read every installed ``.claude`` surface off disk
         (skills, subagents, workflows, commands, hooks, settings, MCP).
      3. Read the product-self-knowledge skill if present.
      4. Combine all of the above + the existing ``claude_code.md`` into ONE unified,
         timestamped reference and OVERWRITE ``claude_code.md`` with it.
      5. Compress it into the structured ``CLAUDE CODE CAPABILITIES`` summary and cache
         it module-globally so it is injected into every Ollama system prompt.
      6. Log the refresh to Obsidian under ``sessions/knowledge-refresh-<ts>.md``.

    Returns the compressed capabilities summary (also stored in the module cache)."""
    global _KNOWLEDGE_REFRESHED
    with _KNOWLEDGE_LOCK:
        if _KNOWLEDGE_REFRESHED and not force and knowledge.getCapabilities():
            return knowledge.getCapabilities()
        fetch_web = config.CLAUDE_DOC_FETCH if fetch_web is None else fetch_web
        refreshed_at = nowIso()
        kpath = config.CLAUDE_KNOWLEDGE_PATH
        try:
            kpath.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:  # noqa: BLE001
            LOG.warning("knowledge dir create failed: %s", e)

        # FRESHNESS FAST-PATH: a recent doc skips the web re-scrape entirely -- just recompress
        # the cached reference + a live local scan and prime the injection (instant restarts).
        if not force and fetch_web and _knowledgeFresh(kpath, config.CLAUDE_KNOWLEDGE_MAX_AGE_HOURS):
            try:
                prior = kpath.read_text(encoding="utf-8", errors="replace")
                local = knowledge.scanLocalClaude()
                recs = knowledge.readRecommendations()
                summary = knowledge.compressForInjection(
                    prior, local, {"pages": {}, "ok": [], "failed": []}, recs=recs)
                knowledge.setCapabilities(summary)
                _KNOWLEDGE_REFRESHED = True
                LOG.info("knowledge fast-path: doc fresh (<%.1fh); skipped web scrape, injection=%dch",
                         config.CLAUDE_KNOWLEDGE_MAX_AGE_HOURS, len(summary))
                return summary
            except Exception as e:  # noqa: BLE001
                LOG.warning("knowledge fast-path failed (%s); doing full refresh", e)

        prior_doc = ""
        try:
            if kpath.exists():
                prior_doc = kpath.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            prior_doc = ""

        fetched = knowledge.fetchClaudeDocs(enabled=fetch_web)
        local = knowledge.scanLocalClaude()
        psk = knowledge.readProductSelfKnowledge()
        recs = knowledge.readRecommendations()

        sources: list[str] = []
        sources += fetched.get("ok", [])
        sources += [f"local:{r}" for r in local.get("roots", [])]
        if psk.get("found"):
            sources.append(f"product-self-knowledge:{psk.get('path')}")
        if recs.get("found"):
            sources.append(f"recommendations:{recs.get('path')}")
        if prior_doc.strip():
            sources.append(f"prior:{kpath}")

        unified = knowledge.buildUnifiedDoc(prior_doc, fetched, local, psk,
                                            refreshed_at=refreshed_at, sources=sources, recs=recs)
        try:
            # atomic: write a temp then os.replace, so an interrupt (Ctrl-C / !abort / taskkill /T
            # on timeout) can never leave a half-written ~1MB claude_code.md to be folded back in.
            tmp = kpath.with_suffix(".md.tmp")
            tmp.write_text(unified, encoding="utf-8")
            os.replace(tmp, kpath)
            LOG.info("knowledge: wrote unified claude_code.md (%d chars) to %s", len(unified), kpath)
        except Exception as e:  # noqa: BLE001
            LOG.warning("knowledge write failed (%s); keeping in-memory only", e)

        summary = knowledge.compressForInjection(unified, local, fetched, recs=recs)
        knowledge.setCapabilities(summary)
        _KNOWLEDGE_REFRESHED = True

        delta = knowledge.diffHeadings(prior_doc, unified)
        if log_session:
            try:
                _logKnowledgeRefresh(obs or ObsidianClient(), refreshed_at, fetched, local, psk, delta, summary, recs)
            except Exception as e:  # noqa: BLE001
                LOG.warning("knowledge-refresh session log failed: %s", e)
        LOG.info("knowledge refresh complete: %d skills, %d agents, %d doc pages, +%d/-%d headings, injection=%dch",
                 len(local.get("skills", [])), len(local.get("agents", [])), len(fetched.get("ok", [])),
                 len(delta.get("added", [])), len(delta.get("removed", [])), len(summary))
        return summary


def _logKnowledgeRefresh(obs: "ObsidianClient", at: str, fetched: dict, local: dict,
                         psk: dict, delta: dict, summary: str, recs: "dict | None" = None) -> None:
    """Persist a refresh record to Obsidian sessions/knowledge-refresh-<ts>.md."""
    recs = recs or {"found": False, "path": None}
    slug = at.replace(":", "").replace("-", "").replace("+", "p")
    rel = f"{config.SESSIONS_DIR_REL}/knowledge-refresh-{slug}.md"
    lines = [
        f"# Claude Code knowledge refresh @ {at}", "",
        "## Sources fetched",
        f"- Live doc pages OK: {len(fetched.get('ok', []))}",
        f"- Live doc pages failed: {len(fetched.get('failed', []))}",
        "",
        "### OK URLs",
    ]
    lines += [f"- {u}" for u in fetched.get("ok", [])] or ["- (none -- offline or fetch disabled)"]
    lines += ["", "## Local .claude surface",
              f"- roots: {', '.join(local.get('roots', [])) or '(none)'}",
              f"- skills: {len(local.get('skills', []))}",
              f"- subagents: {len(local.get('agents', []))}",
              f"- workflows: {len(local.get('workflows', []))}",
              f"- commands: {len(local.get('commands', []))}",
              f"- hooks: {len(local.get('hooks', []))}",
              f"- mcp servers: {', '.join(local.get('mcp_servers', [])) or '(none)'}",
              f"- product-self-knowledge: {'found at ' + str(psk.get('path')) if psk.get('found') else 'not found'}",
              f"- expert recommendations: {'folded in (Part E) from ' + str(recs.get('path')) if recs.get('found') else 'not present'}",
              "", "## What changed since last refresh (top-level headings)",
              f"- added: {', '.join(delta.get('added', [])) or '(none)'}",
              f"- removed: {', '.join(delta.get('removed', [])) or '(none)'}",
              "", "## New capabilities discovered (installed skills this refresh)"]
    lines += [f"- {s['name']}: {s['description'][:120]}" for s in local.get("skills", [])[:40]] or ["- (none)"]
    lines += ["", "## Injected CLAUDE CODE CAPABILITIES summary", "", "```", summary, "```", ""]
    obs.writeNote(rel, "\n".join(lines))


# Back-compat alias: the shared implementation lives in knowledge.py so every brain
# caller (orchestrator + elaborator/replanner/architect) shares one cache.
injectCapabilities = knowledge.injectCapabilities

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
    '  "post_tool_hooks": string[],  // subset of: write_obsidian, discord_notify, log_all\n'
    '  "use_workflow": boolean,      // true => run a DYNAMIC WORKFLOW instead of a flat prompt (see rule 7)\n'
    '  "workflow_definition": object|null // when use_workflow=true: {"name","description",'
    '"phases":[{"title","parallel":bool,"agents":[{"label","prompt","effort"}]}],"synthesis"} else null\n'
    "}\n\n"
    "THE SEVEN PRIMITIVES -- when to use each:\n"
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
    "6. MODEL/FALLBACK is handled by the plumbing -- do not set it.\n"
    "7. DYNAMIC WORKFLOW (use_workflow + workflow_definition): when a subtask has MORE THAN 3 internal "
    "steps, touches multiple tools, benefits from PARALLEL reasoning, or needs structured multi-phase "
    "orchestration, DO NOT cram it into one flat prompt. Set use_workflow=true and author a full "
    "workflow_definition: a name, a description, and an ordered list of phases; each phase has a title, a "
    "'parallel' flag, and a list of agents ({label, prompt, effort}); add a final 'synthesis' instruction "
    "that merges the phase outputs. The plumbing runs this as a real Claude Code workflow (fan-out "
    "subagents, parallel where marked, then synthesize). For a simple single-step subtask keep "
    "use_workflow=false and workflow_definition=null.\n\n"
    "RULES: Honor the goal's constraints (e.g. 'standard library only' => never instruct installs). "
    "Consult the injected CLAUDE CODE CAPABILITIES before choosing primitives -- prefer a real installed "
    "skill/subagent/workflow over a generic prompt whenever one fits. Keep prompt self-contained and "
    "imperative. Output ONLY the JSON object, no prose."
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


def _chatText(resp) -> str:
    """Safely pull resp['message']['content'] as text. '' for ANY malformed shape
    (None resp, non-dict message, non-string content) -- the 7B brain emits all of these."""
    try:
        msg = resp.get("message") if isinstance(resp, dict) else None
        content = msg.get("content") if isinstance(msg, dict) else None
        return content if isinstance(content, str) else ""
    except Exception:  # noqa: BLE001
        return ""


def _resultText(result, key: str = "stdout") -> str:
    """Pull a text field from an executor result, '' if the hands layer returned a non-string
    (the executor contract is str, but a fake/buggy/fuzzed one may not honor it)."""
    v = result.get(key) if isinstance(result, dict) else None
    return v if isinstance(v, str) else ""


def _chatJson(resp):
    """Safely parse the JSON body of a chat response. None on ANY shape/parse problem."""
    text = _chatText(resp).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return None


class Orchestrator:
    def __init__(self, *, brain=None, obs=None, run_claude=None, replan=None, review=None) -> None:
        # Dependency seams (defaults = the real Layer-3/Layer-4 wiring). Injecting fakes here lets
        # the whole orchestration loop run with NO Ollama / Claude CLI / Obsidian -- which is what
        # the integration tests and the --dry-run simulation mode use. replanner.replan MUST be
        # seamed because it owns a separate module-level Ollama client of its own.
        self.ollama = brain if brain is not None else ollama.Client(
            host=config.OLLAMA_HOST, timeout=config.OLLAMA_TIMEOUT_SECONDS)
        self.obs = obs if obs is not None else ObsidianClient()
        self._run_claude = run_claude or executor.runClaude
        self._replan = replan or replanner.replan
        self._review = review or adversary.review
        self._state_lock = threading.Lock()
        self._selfref_prompt_cache: dict = {}   # task_id -> self-ref system-prompt prefix (built once)

    # ===================================================================
    # Brain steps (Ollama authors plan + per-subtask invocation specs)
    # ===================================================================
    def _ollamaChat(self, system: str, user: str, *, want_json: bool = False, retries: int = 3):
        """Resilient Ollama call: exponential backoff on timeout/connection failure,
        Discord blocked alert on final failure. Returns the response dict or None.

        Every system prompt is augmented with the live CLAUDE CODE CAPABILITIES block so
        Qwen reasons from the current Claude Code feature set on every single brain call."""
        system = injectCapabilities(system)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        # SIE Layer 5/G: route to the champion adapter tag if one is promoted, else the
        # frozen base. Best-effort -- any error falls back to OLLAMA_MODEL.
        try:
            from learning import finetune
            model = finetune.active_brain_tag()
        except Exception:  # noqa: BLE001
            model = config.OLLAMA_MODEL
        delay = 2.0
        for attempt in range(1, retries + 1):
            try:
                # num_ctx is REQUIRED: the ~2.2k-token capabilities block sits in the system
                # prompt; ollama's small default would silently truncate the JSON-schema tail.
                kwargs = {"options": {"num_ctx": config.OLLAMA_NUM_CTX}}
                if want_json:
                    kwargs["format"] = "json"
                return self.ollama.chat(model=model, messages=messages, **kwargs)
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

    def _resolveClarifications(self, state: TaskState, subtask: dict, claude_output: str,
                              dashboard: "DiscordDashboard | None" = None) -> "str | None":
        """If the executor punted a decision to a human, have the Ollama brain answer it so the
        next attempt proceeds with NO human intervention. Returns the answer text, or None."""
        questions = clarifier.detectClarificationNeeded(claude_output)
        if not questions:
            return None
        answer = clarifier.answerClarifications(
            self._ollamaChat, state.meta.get("goal_elaborated") or state.meta.get("goal_raw", ""),
            subtask, claude_output, questions)
        if answer:
            LOG.info("%s: brain auto-answered %d executor question(s) -- no human needed",
                     subtask.get("subtask_id"), len(questions))
            if dashboard is not None:
                dashboard.update(state, "executing",
                                 f"{subtask.get('subtask_id')} brain answered executor ({len(questions)} q) autonomously")
        return answer

    def _singleDeliverable(self, goal_elaborated: str) -> bool:
        """True when the goal targets at most one distinct file with no multi-deliverable phrasing.
        Used to collapse over-decomposed plans AND to forbid replan-adds that re-pad a trivial goal.

        A goal that ENUMERATES >=2 requirements (``(1).. (2).. (3)..``) is never single -- even when
        all of them live in ONE file. Treating 'N features in one file' as single is what collapsed
        the webdash goal to 1 subtask and let 1-of-3-done pass as done."""
        import re
        if len(verifier.extractRequirements(goal_elaborated)) >= 2:
            return False
        g = (goal_elaborated or "").lower()
        files = set(re.findall(
            r"([A-Za-z0-9_.-]+\.(?:py|md|txt|json|js|ts|tsx|jsx|html|css|csv|ya?ml|cfg|ini|sh|bat|"
            r"go|rs|java|c|cc|cpp|h|hpp|rb|php|swift|kt|sql|toml))\b", g))
        multi_phrase = any(w in g for w in ("multiple files", "several files", "multiple deliverables",
                                            "as well as", "separate "))
        return len(files) <= 1 and not multi_phrase

    def _strengthenPlanVerifies(self, goal_elaborated: str, subtasks: list[dict]) -> list[dict]:
        """Defense against 'partial work passes': for an enumerated multi-deliverable goal, replace
        the verify of any subtask that COVERS >=2 of those requirements with a strict compound
        content-scan that asserts every covered requirement is present in the target file. A subtask
        covering one deliverable keeps its (per-deliverable) brain verify. No-op for non-enumerated
        goals or when no single target file is named -- so a normal single-deliverable run is
        unaffected and correct work is never failed by a guessed multi-assertion."""
        reqs = verifier.extractRequirements(goal_elaborated)
        if len(reqs) < 2:
            return subtasks
        target_rel = verifier.primaryTargetFile(goal_elaborated)
        if not target_rel:
            return subtasks
        target_abs = str((config.PROJECT_ROOT / target_rel).resolve())
        req_markers = [(r, verifier.requirementMarkers(r)) for r in reqs]
        for st in subtasks:
            hay = f"{st.get('title', '')} {st.get('description', '')}".lower()
            covered = [markers for _r, markers in req_markers
                       if markers and any(k in hay for k in markers)]
            if len(covered) >= 2:
                st["verify"] = verifier.buildContentScanVerify(covered, target_abs)
                LOG.info("plan strengthen: subtask '%s' -> strict compound verify over %d requirements",
                         st.get("title"), len(covered))
        return subtasks

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
            "When the goal ENUMERATES several requirements (e.g. '(1)... (2)... (3)...'), EITHER give each "
            "its own subtask (preferred when they are separable) OR keep one subtask but author a COMPOUND "
            "verify that asserts EVERY requirement -- never a verify that checks just one of them.\n"
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
            "  (d) FOR A MULTI-REQUIREMENT SUBTASK: expect = stdout_contains_all:<tok1>||<tok2>||<tok3>  (every "
            "token must appear) -- pair with a cmd that prints the artifact, e.g. "
            "python -c \"import io;print(io.open(r'<ABSOLUTE path>',encoding='utf-8').read())\".\n"
            "- NEVER import a project module or reference an internal function/class/constant name -- a "
            "guessed symbol WILL fail. NEVER use grep/cat/test/ls/findstr/type."
        )
        user = f"Specification:\n{goal_elaborated}\n\nArchitecture:\n{architect_doc[:4000]}\n\nReturn the plan JSON."
        user = retrieval.lessons_block(goal_elaborated) + user  # SIE Layer 1 (best-effort, no-op if empty)
        resp = self._ollamaChat(system, user, want_json=True)
        parsed = _chatJson(resp)
        raw = parsed.get("subtasks") if isinstance(parsed, dict) else None
        # GUARANTEE list[dict]: the brain emits {"subtasks": 5}, [...non-dicts...], etc. Anything
        # that isn't a dict-with-content is dropped so every downstream consumer is safe.
        subs = [s for s in raw if isinstance(s, dict)] if isinstance(raw, list) else []
        if not subs:
            subs = [{"title": "Implement the goal", "description": goal_elaborated, "layer": 3,
                     "verify": None, "effort_level": "high"}]
        return subs

    def critiqueSubtaskPlan(self, goal_elaborated: str, subs: list[dict]) -> list[dict]:
        """Self-check the plan BEFORE committing it: (1) deterministically collapse an
        over-decomposed trivial goal to one subtask (zero token cost), then (2) a brain
        self-critique pass that rewrites every verify into a safe behavioral shape."""
        subs = [s for s in subs if isinstance(s, dict)] if isinstance(subs, list) else []
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
            "'python <abs>' (expect stdout_contains:<a certain string>); "
            "'python -c \"import os; assert os.path.getsize(r'<abs>')>0\"' (expect exit_zero); or, for a "
            "multi-requirement subtask, expect stdout_contains_all:<t1>||<t2>||<t3> asserting EVERY "
            "requirement. PRESERVE any compound (stdout_contains_all) verify -- never reduce it to a "
            "single-fact check. NEVER import a project module or guess an internal symbol; NEVER use "
            "grep/cat/test/findstr. Collapse any over-decomposition into the fewest subtasks. "
            "Preserve titles/descriptions."
        )
        user = f"Goal:\n{goal_elaborated}\n\nPlan to fix:\n{json.dumps({'subtasks': subs})}\n\nReturn corrected JSON."
        resp = self._ollamaChat(system, user, want_json=True)
        parsed = _chatJson(resp)
        fixed = parsed.get("subtasks") if isinstance(parsed, dict) else None
        if isinstance(fixed, list) and fixed and all(isinstance(x, dict) and x.get("title") for x in fixed):
            LOG.info("plan self-check: brain corrected plan -> %d subtasks", len(fixed))
            return fixed
        return subs

    @staticmethod
    def _asList(v) -> list:
        return v if isinstance(v, list) else []

    @staticmethod
    def _asText(v) -> str:
        return v if isinstance(v, str) else ""

    def _sanitizeSpec(self, spec: dict, subtask: dict) -> dict:
        spec = spec if isinstance(spec, dict) else {}
        eff = (self._asText(spec.get("effort_level")) or "default").lower()
        eff = eff if eff in config.EFFORT_FLAG_MAP else "default"
        # Capability-aware effort FLOOR: a strict compound (multi-requirement) verify means partial
        # work fails, so it deserves real reasoning even if the 7B brain emitted 'default'. Floor to
        # 'high'. (We deliberately do NOT auto-add a subagent/skill here: 'security-reviewer' and
        # '/architect-review' both route the executor to a READ-ONLY charter via playbook.classifyProfile,
        # which would make a write-subtask refuse to edit -- the executor can still invoke a review
        # sub-step itself when warranted.)
        if eff in ("low", "default", "medium") and verifier.isStrictVerify(subtask.get("verify")):
            LOG.info("spec nudge: strict compound verify -> effort floored 'high' (brain emitted %s)",
                     spec.get("effort_level"))
            eff = "high"
        # Coerce list/str fields defensively: the brain emits ints, dicts, and nulls here, and a
        # non-iterable or non-string would crash the spec build (fuzz-proven).
        skills = self._asList(spec.get("skills_to_invoke"))
        pre = self._asList(spec.get("pre_tool_hooks"))
        post = self._asList(spec.get("post_tool_hooks"))
        sub = spec.get("subagent")
        wf_def = spec.get("workflow_definition")
        use_wf = bool(spec.get("use_workflow")) and isinstance(wf_def, dict) and bool(wf_def.get("phases"))
        prompt = (self._asText(spec.get("prompt")) or self._asText(subtask.get("description"))
                  or self._asText(subtask.get("title")))
        return {
            "prompt": prompt.strip(),
            "claude_md_inject": self._asText(spec.get("claude_md_inject")).strip(),
            "effort_level": eff,
            "skills_to_invoke": [s for s in skills if isinstance(s, str) and s in config.AVAILABLE_SKILLS],
            "subagent": sub if (isinstance(sub, str) and sub in config.AVAILABLE_SUBAGENTS) else None,
            "pre_tool_hooks": [h for h in pre if isinstance(h, str) and h in config.AVAILABLE_PRE_HOOKS],
            "post_tool_hooks": [h for h in post if isinstance(h, str) and h in config.AVAILABLE_POST_HOOKS],
            "use_workflow": use_wf,
            "workflow_definition": wf_def if use_wf else None,
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
        # SIE Layer 1 + 4: prepend lessons from similar past successes and the learned
        # effort prior (both best-effort, no-op when empty).
        goal_text = state.meta.get("goal_elaborated", "")
        user = (policy.hint(goal_text, subtask.get("title", ""))
                + retrieval.lessons_block(goal_text, subtask.get("title", "")) + user)
        if state.meta.get("is_self_referential"):
            system_prompt = self._selfRefSystemPrompt(state)
        else:
            # SIE Layer 3: source the constitution from the prompt registry. Byte-identical
            # to ORCHESTRATOR_CONSTITUTION until a challenger is promoted; tag the run so
            # the promotion gate has per-variant field metrics. Best-effort.
            system_prompt = prompts.get("orchestrator", ORCHESTRATOR_CONSTITUTION)
            try:
                cid = prompts.champion_id("orchestrator", ORCHESTRATOR_CONSTITUTION)
                if cid is not None:
                    experience.tag_run_prompt(state.task_id, str(cid))
            except Exception:  # noqa: BLE001 -- tagging is best-effort
                pass
        resp = self._ollamaChat(system_prompt, user, want_json=True)
        spec = _chatJson(resp)
        return self._sanitizeSpec(spec if isinstance(spec, dict) else {}, subtask)

    # ===================================================================
    # Control plane (poll Discord + drain ControlBus between steps)
    # ===================================================================
    def _translateDiscord(self, bus: ControlBus, state: TaskState) -> None:
        msgs, latest = discord.fetchMessagesAfter(bus.getSeen())
        if latest != bus.getSeen():
            bus.setSeen(latest)
        for m in msgs:
            author_id = m.get("author_id") or None
            cmd = commands.decide(int(author_id) if author_id else None,
                                  m.get("author_is_bot", False), m.get("content", ""))
            if cmd:
                if commands.COMMAND_REGISTRY.get(cmd.name, {}).get("mutating"):
                    audit.record(author_id, cmd.name, state.task_id, "discord-poll")
                commands.applyCommand(bus, state, cmd)

    def _applyOps(self, state: TaskState, bus: ControlBus, dashboard: DiscordDashboard) -> None:
        for op in bus.drainOps():
            kind = op.get("op")
            with self._state_lock:
                if kind == "skip":
                    sid = op.get("subtask_id")
                    st = state.getSubtask(sid)
                    if st is None:
                        dashboard.event(f"skip ignored: {sid} not found")
                    elif st["status"] == "pending":
                        state.updateSubtask(sid, status="removed")
                        dashboard.event(f"skipped {sid}")
                    else:
                        # in_progress/done/failed/removed can't be skipped between steps -- say so
                        # instead of dropping the request silently (the user is waiting on feedback).
                        dashboard.event(f"skip ignored: {sid} is {st['status']} (only pending can be skipped)")
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
        self._translateDiscord(bus, state)
        self._applyOps(state, bus, dashboard)
        while bus.isPaused() and not bus.isAbort():
            dashboard.update(state, "paused", "paused -- waiting for !resume")
            time.sleep(config.DISCORD_POLL_SECONDS)
            self._translateDiscord(bus, state)
        if bus.isAbort():
            raise AbortRun("abort requested")
        if gate and state.meta.get("control_mode") == "gated":
            bus.clearDecision(gate)
            bus.setPendingGate(gate)
            discord.sendEmbed(discord.gateNeededEmbed(gate), content=discord.humanPing())
            dashboard.update(state, f"awaiting {gate}", f"awaiting approval for gate: {gate}")
            while True:
                self._translateDiscord(bus, state)
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
        wf = spec.get("workflow_definition") if spec.get("use_workflow") else None
        spec_block = (
            f"## Invocation spec\n\n"
            f"- **Effort:** {spec.get('effort_level')}\n"
            f"- **Skills:** {spec.get('skills_to_invoke')}\n"
            f"- **Subagent:** {spec.get('subagent')}\n"
            f"- **Dynamic workflow:** {('yes — ' + str(wf.get('name'))) if wf else 'no'}\n"
            f"- **Pre hooks:** {spec.get('pre_tool_hooks')}  ·  **Post hooks:** {spec.get('post_tool_hooks')}\n\n"
            f"### CLAUDE.md inject\n\n```\n{(spec.get('claude_md_inject') or '')[:1500]}\n```\n\n"
            f"### Prompt\n\n```\n{spec.get('prompt')}\n```\n\n"
        )
        telem = ""
        if result.get("session_id") or result.get("cost_usd") is not None:
            telem = (f"- **Session:** `{result.get('session_id')}`  ·  **is_error:** {result.get('is_error')}"
                     f"  ·  **cost:** ${result.get('cost_usd')}  ·  **turns:** {result.get('num_turns')}\n")
        return (
            f"# {subtask['subtask_id']} -- {subtask['title']}\n\n"
            f"- **Status:** {subtask['status']}\n"
            f"- **Return code:** {result.get('returncode')}\n"
            f"{telem}\n"
            f"{verify_block}{spec_block}"
            f"## Executor (Claude Code CLI) output\n\n```\n{(result.get('stdout') or '').strip()}\n```\n\n"
            + (f"## stderr\n\n```\n{result['stderr'].strip()}\n```\n" if result.get("stderr") else "")
        )

    def _reviewNote(self, subtask: dict, reason: str, review: dict, output: str) -> str:
        concerns = review.get("concerns") or []
        concerns_md = "\n".join(f"- {c}" for c in concerns) if concerns else "_none_"
        return (
            f"# Adversary review -- {subtask['subtask_id']}\n\n"
            f"- **Trigger:** {reason}\n- **Verdict:** {review['verdict']}\n"
            f"- **Stub:** {review.get('stub', False)}\n\n"
            f"## Concerns\n{concerns_md}\n\n## Notes\n{review.get('notes', '')}\n\n"
            f"## Reviewed output (excerpt)\n\n```\n{(output or '')[:1500]}\n```\n"
        )

    # ===================================================================
    # Adversary teeth -- bounded remediation + pre-PR hold
    # ===================================================================
    def _remediate(self, state: TaskState, subtask: dict, architect_doc: str, exec_cwd: str,
                   concerns: list[str]) -> dict:
        """ONE bounded extra executor attempt to address an adversary's concerns on a subtask that
        ALREADY passed verification. Re-verifies; only keeps or improves -- a remediation that fails
        to verify never downgrades the prior pass (the subtask stays done). Returns the verify_result."""
        sid = subtask["subtask_id"]
        feedback = ("The work PASSED its acceptance check, but an adversarial reviewer raised concerns. "
                    "Address these WITHOUT breaking the passing verification:\n- " + "\n- ".join(concerns))
        spec = self.authorInvocationSpec(state, subtask, architect_doc, feedback)
        result = self._run_claude(spec, work_dir=exec_cwd, task_state=state, subtask=subtask)
        vres = verifier.runVerification(subtask.get("verify"), exec_cwd, result)
        with self._state_lock:
            if vres.get("passed"):
                state.recordVerify(sid, vres)   # adopt the still-passing post-remediation evidence
            state.addNotification(
                "adversary_remediation",
                f"{sid}: remediation {'verified' if vres.get('passed') else 'did not verify (prior pass kept)'}")
        LOG.info("Adversary remediation for %s -> %s", sid, "verified" if vres.get("passed") else "kept prior pass")
        return vres

    def _prePrAdversary(self, state: TaskState) -> dict:
        """Pre-PR safety review: the adversary judges the whole run before a PR is opened. Best-effort
        -- any failure approves (the reviewer must never block a run by erroring). Returns the verdict dict."""
        try:
            _t, reason = adversary.shouldTrigger("", 0, pre_pr=True)
            summary = "\n".join(
                f"- {s['subtask_id']} [{s['status']}] {s['title']}"
                + (" (verify PASS)" if (s.get('verify_result') or {}).get('passed') else "")
                for s in state.subtasks if s["status"] != "removed") or "(no subtasks)"
            rv = self._review("Pre-PR safety review", reason, summary, ollama_chat=self._ollamaChat,
                              goal=state.meta.get("goal_elaborated") or state.meta.get("goal_raw", ""))
            with self._state_lock:
                state.addAdversaryReview("pre_pr", reason, rv["verdict"], None)
            discord.sendEmbed(discord.adversaryTriggeredEmbed("Pre-PR review", reason, rv.get("verdict")))
            return rv
        except Exception as e:  # noqa: BLE001 -- never block a run on the reviewer itself
            LOG.warning("pre-PR adversary review failed (%s); approving", e)
            return {"verdict": "approved", "concerns": [], "stub": True}

    @staticmethod
    def _prGate(review: dict, auto_pr: bool) -> "tuple[bool, str]":
        """Decide whether to create the PR. Returns (create, skip_reason)."""
        if not auto_pr:
            return False, "--no-pr"
        if config.ADVERSARY_PR_HOLD_ENABLED and review.get("verdict") == "challenged":
            concerns = "; ".join(review.get("concerns") or ["challenged"])
            return False, f"adversary HOLD: {concerns}"[:300]
        return True, ""

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
        resume_session: str | None = None   # continue the SAME Claude session across retries

        while attempt < config.MAX_SUBTASK_ATTEMPTS and not passed:
            attempt += 1
            with self._state_lock:
                state.updateSubtask(sid, status="in_progress", started_at=subtask.get("started_at") or nowIso())
            spec = self.authorInvocationSpec(state, subtask, architect_doc, failure_feedback)
            with self._state_lock:
                sess = dict(subtask.get("session") or {})
                sess.update({"effort": spec.get("effort_level"), "model": config.PRIMARY_MODEL,
                             "skills": spec.get("skills_to_invoke"), "subagent": spec.get("subagent"),
                             "use_workflow": bool(spec.get("use_workflow")), "attempts": attempt})
                state.updateSubtask(sid, session=sess)
            LOG.info("Subtask %s attempt %d/%d effort=%s", sid, attempt, config.MAX_SUBTASK_ATTEMPTS,
                     spec.get("effort_level"))
            dashboard.update(state, "executing", f"{sid} attempt {attempt} · effort {spec.get('effort_level')}",
                             effort=spec.get("effort_level"))
            attempt_started = time.time()
            result = self._run_claude(spec, work_dir=exec_cwd, task_state=state, subtask=subtask,
                                        resume_session=resume_session)
            if not isinstance(result, dict):   # a hands layer that returns junk must fail cleanly, not crash
                result = {"ok": False, "returncode": -1, "stdout": "",
                          "stderr": f"executor returned non-dict result: {type(result).__name__}"}
            # Carry a HEALTHY session forward so the next retry continues it (fix the failing
            # assertion, don't re-explore). If Claude itself errored, start fresh -- never resume
            # into a broken session. (is_error absent => json envelope off => no resume.)
            resume_session = result.get("session_id") if (
                result.get("session_id") and not result.get("is_error")) else None
            combined = _resultText(result, "stdout")
            stderr_text = _resultText(result, "stderr")
            if stderr_text:
                combined += "\n[stderr]\n" + stderr_text

            vresult = verifier.runVerification(verify_spec, exec_cwd, result)
            passed = bool(vresult["passed"])
            # VERIFY REPAIR: a brittle brain-authored verify must NEVER fail correct work. Re-verify with a
            # robust behavioral fallback (run the actual artifact). NOT gated on the executor exit code --
            # headless claude exits nonzero for benign reasons (fallback-model switch, a non-fatal tool
            # call); the artifact running cleanly is the real correctness signal. Only a genuinely broken
            # program (its own `python <file>` fails) stays failed.
            # A STRICT verify (compound multi-requirement check) must NEVER be rescued: its whole
            # purpose is that partial work fails. Repair only ever rescues a brittle single-fact verify.
            if not passed and not verifier.isStrictVerify(verify_spec):
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
                # If the executor asked a human instead of acting, the Ollama brain answers it now
                # so the NEXT attempt proceeds autonomously (no human intervention -- ever).
                answer = self._resolveClarifications(state, subtask, combined, dashboard)
                if answer:
                    failure_feedback += (
                        "\n\n[ORCHESTRATOR ANSWERS YOUR QUESTIONS -- proceed now, do NOT ask again]\n"
                        + answer
                    )
                    resume_session = None   # approach is changing -> start the next attempt fresh
            self._translateDiscord(bus, state)
            while bus.isPaused() and not bus.isAbort():   # honor !pause mid-subtask, not just between
                dashboard.update(state, "paused", f"{sid} paused -- waiting for !resume")
                time.sleep(config.DISCORD_POLL_SECONDS)
                self._translateDiscord(bus, state)
            if bus.isAbort():
                raise AbortRun("abort requested")
            if (state.getSubtask(sid) or {}).get("status") == "removed":
                return "removed"

        if (state.getSubtask(sid) or {}).get("status") == "removed":
            return "removed"

        # COMMIT the verified outcome FIRST -- it is the source of truth. Everything below
        # (notes, adversary, replan, index) is best-effort enrichment that must never be able to
        # change a verified result: it runs in a guard, because a crash here used to propagate to
        # the caller's handler and flip a PASSED subtask to 'failed' (the poll/replan bug class).
        final = "done" if passed else "failed"
        with self._state_lock:
            state.updateSubtask(sid, status=final, completed_at=nowIso())
            if not passed:
                state.addNotification("subtask_failed", f"{sid} failed verification after {attempt} attempts")
        if not passed:
            discord.sendEmbed(discord.subtaskFailedEmbed(sid, subtask["title"], vresult, attempt))
        dashboard.update(state, "executing", f"{sid} -> {final}")

        try:
            with self._state_lock:
                note = self._subtaskNote(state, subtask, spec, result, vresult)
                written = self.obs.writeNote(state.subtaskNoteRel(sid), note)
                state.updateSubtask(sid, output_ref=written.get("rel_path"))

            # heartbeat off the STABLE terminal-subtask count (this subtask is now committed terminal).
            # Snapshot under the lock: in parallel mode a peer worker may be appending via _applyReplan,
            # and iterating the live list unlocked risks 'list changed size during iteration'.
            with self._state_lock:
                heartbeat_ordinal = sum(1 for s in state.subtasks if s["status"] in ("done", "failed", "removed"))
            triggered, reason = adversary.shouldTrigger(combined, heartbeat_ordinal, attempt)
            if triggered:
                rv = self._review(subtask["title"], reason, combined,
                                  ollama_chat=self._ollamaChat,
                                  goal=state.meta.get("goal_elaborated") or state.meta.get("goal_raw", ""))
                discord.sendEmbed(discord.adversaryTriggeredEmbed(subtask["title"], reason, rv.get("verdict")))
                with self._state_lock:
                    state.addNotification("adversary_triggered", f"{sid}: {reason} -> {rv['verdict']}")
                    self.obs.writeNote(state.subtaskReviewNoteRel(sid), self._reviewNote(subtask, reason, rv, combined))
                    state.addAdversaryReview(sid, reason, rv["verdict"], state.subtaskReviewNoteRel(sid))
                # TEETH: a challenged verdict on a PASSED subtask earns ONE bounded remediation
                # attempt with the concerns injected. Never downgrades the passing result.
                if (config.ADVERSARY_REMEDIATION_ENABLED and final == "done"
                        and rv.get("verdict") == "challenged" and rv.get("concerns")):
                    dashboard.update(state, "executing", f"{sid} adversary remediation (1 attempt)")
                    self._remediate(state, subtask, architect_doc, exec_cwd, rv["concerns"])

            # Replan ONLY after a subtask that PASSED. Replanning after failures is the
            # churn engine (fail -> add remediation -> fail -> add ...) that livelocks runs;
            # the executor already retries failed subtasks up to MAX_SUBTASK_ATTEMPTS.
            if final == "done" and not self._singleDeliverable(state.meta.get("goal_elaborated", "")):
                with self._state_lock:                       # snapshot for the same parallel-safety reason
                    subs_snapshot = list(state.subtasks)
                decision = self._replan(state.meta["goal_elaborated"], subs_snapshot, subtask, combined,
                                        self_referential=bool(state.meta.get("is_self_referential")),
                                        remaining_hours=self._remainingHours(state))
                if decision.get("action") == "mutate" and (decision.get("add") or decision.get("remove")):
                    dashboard.update(state, "replanning", f"replanning after {sid}")
                    with self._state_lock:
                        self._applyReplan(state, decision)
            with self._state_lock:
                self.writeIndex(state)
        except AbortRun:
            raise
        except Exception as e:  # noqa: BLE001 -- enrichment is best-effort; committed status stands
            LOG.warning("post-completion enrichment for %s failed (status %s preserved): %s",
                        sid, final, e, exc_info=True)
        return final

    def _deadlinePassed(self, state: TaskState) -> bool:
        """True once the task's wall-clock deadline_at has passed (time-horizon enforcement).
        None (no/unparseable deadline) => never passes; exactly 0.0 => passed."""
        rem = self._remainingHours(state)
        return rem is not None and rem <= 0.0

    def _remainingHours(self, state: TaskState) -> "float | None":
        """Hours until deadline_at (negative once passed); None if no/!parseable deadline."""
        deadline = state.meta.get("deadline_at")
        if not deadline:
            return None
        try:
            from datetime import datetime
            return (datetime.fromisoformat(deadline) - datetime.now().astimezone()).total_seconds() / 3600.0
        except Exception:  # noqa: BLE001 -- a bad timestamp must never wedge the loop
            return None

    def runExecutionLoop(self, state: TaskState, architect_doc: str, work_dir: str,
                         bus: ControlBus, dashboard: DiscordDashboard, parallelism: int = 1) -> None:
        position = 0
        iters = 0
        no_progress = 0
        prev_terminal = -1
        while True:
            iters += 1
            # TIME HORIZON: stop scheduling new subtasks once the deadline passes (the run is
            # 9am-5pm bounded). deadline_at was always computed but never enforced -- a fat plan
            # would otherwise blow past the horizon unbounded. In-flight subtasks finish; the
            # remaining pending ones stay pending so runFull finalizes the run as 'partial'.
            if self._deadlinePassed(state):
                LOG.warning("time horizon reached (deadline %s); ending execution loop",
                            state.meta.get("deadline_at"))
                try:
                    discord.sendEmbed(discord.blockedEmbed(
                        f"Time horizon reached ({state.meta.get('deadline_at')}) — finalizing as partial"))
                except Exception:  # noqa: BLE001
                    pass
                dashboard.update(state, "executing", "time horizon reached — finalizing")
                break
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
        # The brain may return malformed add/remove (non-list, or items of the wrong type). A crash
        # here would propagate to the caller's handler and flip the just-COMPLETED subtask to failed,
        # so coerce defensively and skip any entry that isn't the expected shape.
        adds = decision.get("add") or []
        for add in (adds if isinstance(adds, list) else []):
            if not isinstance(add, dict):
                continue
            if active >= config.MAX_SUBTASKS:
                LOG.info("replan add skipped: MAX_SUBTASKS (%d) reached", config.MAX_SUBTASKS)
                diff.append(f"(skipped add '{add.get('title')}' -- MAX_SUBTASKS cap)")
                break
            st = state.addSubtask(add.get("title", "untitled"), add.get("description", ""),
                                  layer=add.get("layer", 3), verify=verifier.sanitizeVerify(add.get("verify")))
            active += 1
            diff.append(f"+ {st['subtask_id']} {st['title']}")
        rems = decision.get("remove") or []
        for rid in (rems if isinstance(rems, list) else []):
            if not isinstance(rid, str):
                continue
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
        discord.sendEmbed(discord.selfRefEmbed(branch, config.CORE_PROTECTED_FILES),
                          content=discord.humanPing())
        dashboard.event(f"self-referential · branch {branch}")

    @staticmethod
    def _cleanupScaffolding(work_dir: str) -> None:
        """Remove 9to5's per-subtask scratch dir (.sc-ctx) from the user's project tree at the
        end of a run -- never leave scaffolding behind. Best-effort; never raises."""
        try:
            import shutil
            ctx = os.path.join(str(work_dir), ".sc-ctx")
            if os.path.isdir(ctx):
                shutil.rmtree(ctx, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass

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
        # ABSOLUTE FIRST: refresh the living Claude Code knowledge so every Ollama call
        # in this run reasons from the current feature set (idempotent per process).
        try:
            refreshClaudeKnowledge(self.obs)
        except Exception as e:  # noqa: BLE001 -- knowledge refresh must never block a run
            LOG.warning("refreshClaudeKnowledge failed (non-fatal): %s", e)
        if control_mode:
            state.setControlMode(control_mode)
        state.setWorkDir(work_dir)   # persist the target dir so resume + every surface remember it
        bus = ControlBus(state.task_id)
        if not resume:
            bus.clear()
        if bus.getSeen() is None:   # seed so a stale '!abort' from a prior run is never replayed
            try:
                bus.setSeen(discord.baselineLatestId())
            except Exception:  # noqa: BLE001
                pass
        dashboard = DiscordDashboard()
        web_url = startWebDashboard(state.task_id)
        dashboard.start(state, "resuming" if resume else "starting", state_lock=self._state_lock)
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
                arch_prompt = architect.authorArchitectPrompt(elaborated, chat=self._ollamaChat)

                def _runArchitect(effort: str):
                    res = self._run_claude({"prompt": arch_prompt, "effort_level": effort},
                                           work_dir=self._execCwd(state, "architect", work_dir),
                                           system_prompt=architect.ARCHITECT_SYSTEM_PROMPT, task_state=state)
                    return res if isinstance(res, dict) else {}   # tolerate a junk hands result

                arch_res = _runArchitect("default")
                architect_doc = _resultText(arch_res).strip()
                # GATE: an empty/failed architect phase silently degrades EVERY downstream spec
                # (plan + invocation specs feed architect_doc). Retry once harder before trusting it.
                if arch_res.get("is_error") or len(architect_doc) < 200:
                    LOG.warning("architect output weak (is_error=%s, %d chars) -> retry at xhigh",
                                arch_res.get("is_error"), len(architect_doc))
                    dashboard.update(state, "architecting", "architect output weak -> retrying harder")
                    arch_res = _runArchitect("xhigh")
                    architect_doc = _resultText(arch_res).strip() or architect_doc
                if len(architect_doc) < 200:
                    try:
                        discord.sendEmbed(discord.blockedEmbed(
                            f"Architect phase produced only {len(architect_doc)} chars — planning may be degraded"),
                            content=discord.humanPing())
                    except Exception:  # noqa: BLE001
                        pass
                    architect_doc = architect_doc or "(architect produced no usable output)"
                self.obs.writeNote(state.architectNoteRel(), architect_doc)
                state.setArchitectDoc(state.architectNoteRel())
                discord.sendEmbed(discord.architectDoneEmbed(state.architectNoteRel()))
                state.addNotification("architect_done", state.architectNoteRel())
                dashboard.update(state, "architecting", f"architecture done ({len(architect_doc)} chars)")

                # --- Phase 2: Planning ---
                state.setStatus("planning")
                dashboard.update(state, "planning", "authoring subtask plan")
                plan = self.critiqueSubtaskPlan(elaborated, self.authorSubtaskPlan(elaborated, architect_doc))
                plan = self._strengthenPlanVerifies(elaborated, plan)
                for s in plan[:config.MAX_SUBTASKS]:
                    state.addSubtask(s.get("title", "untitled"), s.get("description", ""),
                                     layer=s.get("layer", 3), verify=verifier.sanitizeVerify(s.get("verify")))
                discord.sendEmbed(discord.planningStartEmbed(state.meta["goal_raw"], state.subtasks))
                state.addNotification("planning_start", f"{len(state.subtasks)} subtasks")
                self.writeIndex(state)
                dashboard.update(state, "planning", f"planned {len(state.subtasks)} subtasks")
                self._checkControl(state, bus, dashboard, gate="plan")

            # --- Phase 3: Execution ---
            state.setStatus("executing")
            self.runExecutionLoop(state, architect_doc, work_dir, bus, dashboard, parallelism=parallelism)

            # --- Phase 4: PR + complete ---
            self._checkControl(state, bus, dashboard, gate="pre_pr")
            pr_review = self._prePrAdversary(state)
            create_pr, skip_reason = self._prGate(pr_review, auto_pr)
            if create_pr:
                pr = self.createPullRequest(state, work_dir)
            else:
                pr = {"skipped": True, "reason": skip_reason}
                if skip_reason.startswith("adversary HOLD"):
                    dashboard.update(state, "executing", f"PR held by adversary: {skip_reason}")
                    state.addNotification("pr_held", skip_reason)
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
            discord.sendEmbed(discord.abortedEmbed(reason, _fmtElapsed(elapsed)),
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
            try:
                dashboard.unpin()
            except Exception:  # noqa: BLE001
                LOG.warning("dashboard unpin failed", exc_info=True)
            stopWebDashboard()
            self._cleanupScaffolding(work_dir)   # never leave 9to5 scratch dirs in the user's project
            # Self-improvement runs itself: the user only starts/aborts/checks. Fire the
            # throttled learning passes off-thread so they never slow teardown.
            if config.SIE_AUTO_MAINTENANCE:
                try:
                    from learning import sie
                    sie.run_maintenance_async(reason="post-run")
                except Exception:  # noqa: BLE001 -- learning is best-effort, never blocks
                    LOG.debug("sie maintenance dispatch failed (ignored)", exc_info=True)
