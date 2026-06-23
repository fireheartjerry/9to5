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
import surfaces
from agents import adversary, architect, clarifier, executor, replanner, verifier
from control import AbortRun, ControlBus
from learning import (confidence, knowledge_graph, policy, postmortem, prompts,
                      reflection, solution_cache)
from memory import experience, retrieval
from memory.obsidian import ObsidianClient
from notifications import audit
from notifications import commands
from notifications import discord_bot as discord
from notifications.dashboard import DiscordDashboard
from notifications.webdash import startWebDashboard, stopWebDashboard
from state.task import TaskState, nowIso

LOG = config.getLogger("orchestrator")

# A CONCRETE example verify path handed to the brain so it never copies a literal "<ABSOLUTE
# path>" placeholder (which cmd.exe parses as redirection -> spurious verify failures). See
# verifier.sanitizeVerify, which now rejects any cmd containing angle brackets.
_VERIFY_EXAMPLE_PATH: str = str(config.PROJECT_ROOT / "tests" / "test_example.py")

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
    '  "workflow_definition": object|null, // when use_workflow=true: {"name","description",'
    '"phases":[{"title","parallel":bool,"agents":[{"label","prompt","effort"}]}],"synthesis"} else null\n'
    '  "surface": string,            // "terminal" (default) or "browser" -- pick the RIGHT surface\n'
    '  "browser_actions": object[]   // when surface="browser": steps like {"action":"goto","url":...},'
    '{"action":"click","selector":...},{"action":"type","selector":...,"text":...},{"action":"extract","selector":...}\n'
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
    """Safely parse the JSON body of a chat response. None on ANY shape/parse problem.

    Salvages the two ways a 7B model commonly breaks strict JSON: wrapping it in a ```json
    fence, and emitting prose around the object. We strip a fence, then fall back to extracting
    the first balanced {...} -- so a recoverable response no longer collapses to the degenerate
    single-subtask plan fallback."""
    import re as _re
    text = _chatText(resp).strip()
    if not text:
        return None
    if text.startswith("```"):
        text = _re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=_re.IGNORECASE).strip()
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        pass
    m = _re.search(r"\{.*\}", text, _re.DOTALL)   # salvage: first balanced-looking JSON object
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:  # noqa: BLE001
            return None
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
        self._poll_lock = threading.Lock()      # serialize Discord poll cursor across parallel workers (CB-7)
        self._selfref_prompt_cache: dict = {}   # task_id -> self-ref system-prompt prefix (built once)
        self._brain_tag_override: str | None = None   # force a model tag (adapter A/B eval)
        # SIE: register a per-adapter fitness evaluator so adapter promotion is autonomous.
        # The brain authors a spec for each golden goal under the candidate tag; the held-out
        # verify scores it. Best-effort registration; skips cleanly if the brain is offline.
        try:
            from learning import eval_runner
            eval_runner.register(fitness_under_tag=self._fitnessUnderTag)
        except Exception:  # noqa: BLE001
            pass

    def _fitnessUnderTag(self, tag: str) -> float:
        """Run the golden eval suite with the brain forced to ``tag`` and return fitness.
        Used by automatic adapter promotion to A/B a challenger vs the champion."""
        from learning import eval_harness
        prev = self._brain_tag_override
        self._brain_tag_override = None if tag == config.OLLAMA_MODEL else tag
        try:
            out = eval_harness.run_suite(runner=self._evalGoal, record=False)
            return float(out.get("fitness", 0.0))
        finally:
            self._brain_tag_override = prev

    def _selectExecutor(self, spec: dict):
        """Pick the hands layer for a spec's requested surface. Default: Claude CLI (L3).
        Routes to the browser backend (L1) when the brain asks for it AND it's enabled;
        falls back to Claude on any import problem so a run is never blocked by routing."""
        if spec.get("surface") == "browser" and config.BROWSER_LAYER_ENABLED:
            try:
                from agents import browser_executor
                return browser_executor.runBrowser
            except Exception:  # noqa: BLE001
                LOG.warning("browser surface requested but backend unavailable; using terminal")
        return self._run_claude

    def _evalGoal(self, goal: dict) -> dict:
        """Execute ONE golden goal as a bounded single subtask (brain authors under the
        current tag -> Claude runs -> held-out verify scores it). Used by the live eval
        runner and per-adapter fitness."""
        verify = goal.get("verify") or {}
        subtask = {"subtask_id": "eval", "title": goal.get("goal", "")[:80],
                   "description": goal.get("goal", ""), "verify": verify,
                   "effort_level": goal.get("effort_level", "default")}
        try:
            state = TaskState.create(goal.get("goal", ""), 1.0)
            state.meta["goal_elaborated"] = goal.get("goal", "")
            spec = self.authorInvocationSpec(state, subtask, "")
            result = self._run_claude(spec, work_dir=str(config.PROJECT_ROOT))
            vres = verifier.runVerification(
                verify, str(config.PROJECT_ROOT), result if isinstance(result, dict) else {})
            return {"passed": bool(vres.get("passed")), "attempts": 1,
                    "challenged": not bool(vres.get("passed"))}
        except Exception:  # noqa: BLE001
            return {"passed": False, "attempts": 1, "challenged": True}

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
        # SIE Layer 5/G: route to a forced tag (adapter A/B eval), else the champion
        # adapter, else the frozen base. Best-effort -- any error falls back to OLLAMA_MODEL.
        try:
            from learning import finetune
            model = getattr(self, "_brain_tag_override", None) or finetune.active_brain_tag()
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
                resp = self.ollama.chat(model=model, messages=messages, **kwargs)
                # qwen2.5 can dead-end to an EMPTY completion under format=json on markdown-heavy
                # prompts. Do ONE fast salvage WITHOUT the json grammar (free-form JSON is recovered by
                # _chatJson's fence/object extraction) -- but NO backoff loop: an empty here is usually
                # deterministic for this prompt, and looping would burn minutes per brain call for no
                # gain (the caller has a fallback). If still empty, return it and let the caller fall back.
                if want_json and not _chatText(resp).strip():
                    kwargs.pop("format", None)
                    salvage = self.ollama.chat(model=model, messages=messages, **kwargs)
                    return salvage if _chatText(salvage).strip() else resp
                return resp
            except Exception as e:  # noqa: BLE001
                LOG.warning("Ollama call failed/empty (attempt %d/%d): %s", attempt, retries, e)
                if attempt >= retries:
                    try:
                        discord.sendEmbed(discord.noticeEmbed(f"Brain (Ollama) unavailable after {retries} attempts; falling back: {e}"))
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

        orig = subtask.get("verify") or {}
        orig_expect = orig.get("expect")
        # FX-4: PRESERVE the original behavioral assertion (stdout_contains/regex) so repair re-checks
        # the REAL needle on the fresh artifact instead of degrading to "it exits 0" -- which would
        # flip genuinely-broken work to PASS. Only fall back to exit_zero when there was no output check.
        keep_expect = orig_expect if (isinstance(orig_expect, str) and orig_expect.startswith(
            ("stdout_contains:", "stdout_regex:"))) else "exit_zero"
        text = (orig.get("cmd") or "") + "  " + (subtask.get("description") or "")
        # 1) absolute .py referenced by the verify/description that THIS attempt wrote
        for m in re.findall(r"([A-Za-z]:\\[^\s\"'`]+\.py|/[^\s\"'`]+\.py)", text):
            if _fresh(m):
                return {"cmd": f'python "{m}"', "expect": keep_expect}
        # 2) relative .py token resolved against exec_cwd (preserve any subpath), written this attempt
        for cand in re.findall(r"([\w./\\-]+\.py)\b", text):
            if os.path.isabs(cand):
                continue
            p = os.path.normpath(os.path.join(exec_cwd, cand))
            if _fresh(p):
                return {"cmd": f'python "{p}"', "expect": keep_expect}
        # FX-4/17: do NOT rescue with an ARBITRARY newest .py in cwd -- it is often an unrelated scratch
        # /helper file (especially under .sc-ctx) and would false-PASS partial/broken work. Only files
        # the verify or description ACTUALLY reference (steps 1-2) qualify for a behavioral repair.
        # 4) a NON-.py artifact REFERENCED by the verify/description -> non-empty check (never mask a broken .py)
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
            "- Use EXACTLY ONE of these shapes. Substitute a REAL, EXISTING absolute path (resolve it "
            "yourself under " + str(config.PROJECT_ROOT) + "); e.g. " + _VERIFY_EXAMPLE_PATH + ".\n"
            "  CRITICAL: NEVER emit angle brackets or the words 'ABSOLUTE path'. A cmd containing '<' or "
            "'>' is REJECTED (it breaks the shell) and your verify is discarded. On Windows never use a "
            ".sh/bash verify.\n"
            "  (a) cmd = python " + _VERIFY_EXAMPLE_PATH + " ; expect = exit_zero            (the program runs cleanly)\n"
            "  (b) cmd = python " + _VERIFY_EXAMPLE_PATH + " ; expect = stdout_contains:<a short string you are CERTAIN it prints>\n"
            '  (c) cmd = python -c "import os; assert os.path.getsize(r\'' + _VERIFY_EXAMPLE_PATH + '\')>0" ; expect = exit_zero   (file exists, non-empty)\n'
            "  (d) FOR A MULTI-REQUIREMENT SUBTASK: expect = stdout_contains_all:tok1||tok2||tok3  (every "
            "token must appear) -- pair with a cmd that prints the artifact, e.g. "
            "python -c \"import io;print(io.open(r'" + _VERIFY_EXAMPLE_PATH + "',encoding='utf-8').read())\".\n"
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
            # The planner JSON was unparseable/empty. This is NOT a normal 1-subtask plan -- alert
            # (it silently degraded every downstream spec before) and, for an enumerated
            # multi-deliverable goal, DECOMPOSE per requirement instead of collapsing the whole
            # 8-hour goal into one unverified "Implement the goal" mega-subtask.
            LOG.error("planner produced no usable subtasks (JSON unparseable/empty) -> fallback plan")
            try:
                discord.sendEmbed(discord.noticeEmbed(
                    "Planner returned no usable JSON — auto-using a decomposed fallback plan (no action needed)"))
            except Exception:  # noqa: BLE001
                pass
            reqs = verifier.extractRequirements(goal_elaborated)
            if len(reqs) >= 2:
                target_rel = verifier.primaryTargetFile(goal_elaborated)
                target_abs = str((config.PROJECT_ROOT / target_rel).resolve()) if target_rel else None
                subs = []
                for i, req in enumerate(reqs, 1):
                    v = None
                    markers = verifier.requirementMarkers(req)
                    if target_abs and markers:
                        v = verifier.buildContentScanVerify([markers], target_abs)
                    subs.append({"title": f"Deliverable {i}: {req[:60]}", "description": req,
                                 "layer": 3, "verify": v, "effort_level": "high"})
                LOG.info("fallback plan: decomposed goal into %d per-requirement subtasks", len(subs))
            else:
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
        # SIE: prepend everything the engine has learned for this kind of subtask
        # (lessons, policy prior, failure modes, codebase notes, a prior solution, and a
        # low-confidence escalation nudge). All best-effort + no-op when empty.
        user = self._sieAuthoringContext(state, subtask) + user
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
        spec = self._sanitizeSpec(spec if isinstance(spec, dict) else {}, subtask)
        # FX-6: the brain frequently returns EMPTY, so failure_feedback (and the clarifier answer it
        # carries) -- which was only interpolated into the brain's USER prompt -- is LOST: the sanitized
        # spec is just the bare description and the executor repeats the same mistake. Fold the feedback
        # DETERMINISTICALLY into the spec (both the living CLAUDE.md and the prompt body, the latter so a
        # --resume retry carries it too) so the executor always sees WHY the last attempt failed.
        if failure_feedback:
            block = "## PREVIOUS ATTEMPT FAILED THE VERIFICATION — fix this\n" + failure_feedback.strip()[:1500]
            spec["claude_md_inject"] = ((spec.get("claude_md_inject") or "") + "\n\n" + block).strip()
            spec["prompt"] = block + "\n\n" + (spec.get("prompt") or "")
        # SIE subsystem I: ask the executor (the strong teacher) for a learning summary so
        # we can distill its reasoning. Best-effort + only if it produced a prompt.
        try:
            if config.SIE_REFLECTION_ENABLED and spec.get("prompt"):
                spec["prompt"] = f"{spec['prompt']}\n\n{reflection.REQUEST}"
        except Exception:  # noqa: BLE001
            pass
        return spec

    def _sieAuthoringContext(self, state: TaskState, subtask: dict) -> str:
        """Everything the Self-Improvement Engine has learned for this subtask, folded into
        one best-effort prompt prefix. Each piece independently degrades to "" so a cold
        ledger (or any error) changes nothing."""
        if not config.SIE_AUTHORING_CONTEXT:
            return ""
        goal = state.meta.get("goal_elaborated", "") or state.meta.get("goal_raw", "")
        title = subtask.get("title", "")
        parts: list[str] = []
        for fn in (
            surfaces.catalog_block,                       # rich cross-surface routing
            lambda: policy.hint(goal, title),
            lambda: retrieval.lessons_block(goal, title),
            lambda: postmortem.guidance_for(title),
            lambda: knowledge_graph.context_for(title),
            lambda: self._confidenceNudge(title),
            lambda: self._warmStartHint(title),
        ):
            try:
                parts.append(fn() or "")
            except Exception:  # noqa: BLE001 -- learning never blocks authoring
                pass
        return "".join(parts)

    def _confidenceNudge(self, title: str) -> str:
        """SIE subsystem K: if this family historically struggles, tell the brain to
        escalate effort and slow down."""
        prior = confidence.prior_success(title)
        if prior is not None and prior < config.CONFIDENCE_DEFER_THRESHOLD:
            return (f"## LOW-CONFIDENCE ({prior:.0%} historical first-pass): use HIGHER effort "
                    "(high/xhigh), be extra careful, and verify thoroughly.\n\n")
        return ""

    def _warmStartHint(self, title: str) -> str:
        """SIE subsystem O: surface a prior PASSING spec for a near-duplicate subtask."""
        prior = solution_cache.warm_start(title)
        if prior:
            return ("## PRIOR WORKING SOLUTION for a near-identical subtask (adapt, don't "
                    f"blindly copy):\n{prior[:600]}\n\n")
        return ""

    # ===================================================================
    # Control plane (poll Discord + drain ControlBus between steps)
    # ===================================================================
    def _translateDiscord(self, bus: ControlBus, state: TaskState) -> None:
        # Serialize the getSeen->fetch->apply->setSeen sequence: with parallelism>1 several worker
        # threads poll on the same cadence, and an unsynchronized cursor lets two threads fetch the
        # SAME message batch and apply each command TWICE (e.g. a !add creating duplicate subtasks),
        # while setSeen races backward and re-delivers (CB-7). The lock makes polling atomic.
        if not self._poll_lock.acquire(blocking=False):
            return   # another worker is already polling this tick; skip (it covers our messages)
        try:
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
        finally:
            self._poll_lock.release()

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

    def _waitWhilePaused(self, state: TaskState, bus: ControlBus, dashboard: DiscordDashboard,
                         label: str = "paused") -> None:
        """Block while the bus is paused, but ALWAYS escapable: returns on resume, on abort, on the
        night-mode pause timeout, or once the work-horizon deadline passes. Shared by _checkControl
        and the mid-subtask pause loop so a !pause can never wedge an unattended run forever (CB-1)."""
        if not bus.isPaused():
            return
        pause_start = time.time()
        while bus.isPaused() and not bus.isAbort():
            if config.NIGHT_MODE and (time.time() - pause_start) > config.NIGHT_MODE_PAUSE_TIMEOUT:
                bus.clearPause()
                dashboard.event(f"night mode: auto-resumed after {config.NIGHT_MODE_PAUSE_TIMEOUT}s pause timeout")
                LOG.info("night mode: auto-resumed after pause timeout")
                break
            if self._deadlinePassed(state):   # never park past the 5pm horizon
                bus.clearPause()
                LOG.warning("deadline reached while paused -- auto-resuming to finalize")
                break
            dashboard.update(state, "paused", f"{label} -- waiting for !resume")
            time.sleep(config.DISCORD_POLL_SECONDS)
            self._translateDiscord(bus, state)

    def _autoApprovePlan(self, state: TaskState) -> "tuple[str, str]":
        """Ollama is the plan gatekeeper -- a human never approves plans (design: zero human
        interaction). The plan is already brain-authored + self-critiqued, so this is a final sanity
        check: approve unless the plan is clearly broken. Any failure approves, and a soft reject is
        recorded but never wedges or aborts the autonomous run."""
        subs = [{"title": s.get("title"), "expect": (s.get("verify") or {}).get("expect")}
                for s in state.subtasks if s.get("status") != "removed"]
        if not subs:
            return "reject", "empty plan"
        goal = state.meta.get("goal_elaborated") or state.meta.get("goal_raw", "")
        system = (
            "You are the PLAN GATEKEEPER for an autonomous agent (no human is available to approve). "
            "Given the goal and the proposed subtask plan, decide if it is sane and ready to execute. "
            "Approve unless it is clearly broken (off-goal, or missing obviously-required work). "
            'Respond with JSON ONLY: {"approve": true|false, "reason": "..."}.'
        )
        user = (f"GOAL:\n{goal[:1500]}\n\nPLAN ({len(subs)} subtasks):\n"
                f"{json.dumps(subs, indent=2)[:2000]}\n\nReturn the verdict JSON.")
        try:
            data = _chatJson(self._ollamaChat(system, user, want_json=True)) or {}
            approve = data.get("approve", True) if isinstance(data, dict) else True
            reason = str((data or {}).get("reason") or "")[:200]
            return ("approve" if approve else "reject"), reason
        except Exception as e:  # noqa: BLE001 -- the gate must never block the autonomous run
            return "approve", f"auto-approve (gate review failed: {e})"

    def _checkControl(self, state: TaskState, bus: ControlBus, dashboard: DiscordDashboard,
                      gate: str | None = None) -> None:
        self._translateDiscord(bus, state)
        self._applyOps(state, bus, dashboard)
        self._waitWhilePaused(state, bus, dashboard)
        if bus.isAbort():
            raise AbortRun("abort requested")
        # PLAN gate auto-approves through Ollama -- a human is NEVER required to approve plans. A
        # watching human may still !abort / !reject / !skip / !add during a brief window; if no human
        # decision arrives, the brain approves and the run proceeds autonomously. (watch mode has no
        # gate at all; abort is always honored.)
        if gate == "plan" and state.meta.get("control_mode") == "gated":
            bus.clearDecision("plan")
            bus.setPendingGate("plan")
            dashboard.update(state, "awaiting plan", "plan gate — ollama auto-approves shortly")
            auto_at = time.time() + config.PLAN_GATE_AUTO_APPROVE_SECONDS
            while True:
                self._translateDiscord(bus, state)
                self._applyOps(state, bus, dashboard)   # honor !skip/!add while parked at the gate
                if bus.isAbort():
                    bus.setPendingGate(None)
                    raise AbortRun("aborted at plan gate")
                decision = bus.getDecision("plan")
                if decision == "approve":
                    dashboard.event("plan gate: approved (human)")
                    break
                if decision == "reject":
                    bus.setPendingGate(None)
                    raise AbortRun("plan rejected")
                if time.time() >= auto_at or self._deadlinePassed(state):
                    verdict, reason = self._autoApprovePlan(state)
                    dashboard.event(f"plan gate: ollama auto-{verdict} — {reason[:50]}")
                    with self._state_lock:
                        state.addNotification("plan_gate", f"ollama auto-{verdict}: {reason}")
                    if verdict == "reject":
                        LOG.warning("plan gate: ollama auto-rejected (%s) -- proceeding autonomously", reason)
                    break
                time.sleep(config.DISCORD_POLL_SECONDS)
            bus.setPendingGate(None)
            return
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
                # CB-6: never park a gate past the horizon. In night mode the safe default for a
                # pre-PR gate is to NOT auto-ship; either way finalize the run instead of hanging.
                if self._deadlinePassed(state):
                    bus.setPendingGate(None)
                    LOG.warning("gate '%s' timed out at deadline -- aborting to finalize", gate)
                    raise AbortRun(f"gate '{gate}' timed out at deadline")
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
        # FX-10: snapshot the work tree BEFORE remediation. A remediation edit that breaks the artifact
        # (fails re-verify) must be REVERTED -- otherwise the broken files stay on disk and get committed
        # while the subtask still reports the prior pass (verify_result no longer matches disk).
        snap = self._gitSnapshot(exec_cwd)
        spec = self.authorInvocationSpec(state, subtask, architect_doc, feedback)
        result = self._run_claude(spec, work_dir=exec_cwd, task_state=state, subtask=subtask)
        vres = verifier.runVerification(subtask.get("verify"), exec_cwd, result)
        with self._state_lock:
            if vres.get("passed"):
                state.recordVerify(sid, vres)   # adopt the still-passing post-remediation evidence
            else:
                self._gitRestore(exec_cwd, snap)   # revert broken remediation edits so disk == kept pass
            state.addNotification(
                "adversary_remediation",
                f"{sid}: remediation {'verified' if vres.get('passed') else 'did not verify (reverted, prior pass kept)'}")
        LOG.info("Adversary remediation for %s -> %s", sid,
                 "verified" if vres.get("passed") else "reverted (kept prior pass)")
        return vres

    @staticmethod
    def _gitSnapshot(cwd: str) -> "str | None":
        """Capture the current (dirty) tree as a throwaway stash commit WITHOUT touching the tree;
        returns its SHA, or None if cwd isn't a git repo / nothing to snapshot. (FX-10)"""
        try:
            r = subprocess.run(["git", "stash", "create"], cwd=cwd, capture_output=True, text=True, timeout=30)
            return (r.stdout or "").strip() or None
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _gitRestore(cwd: str, sha: "str | None") -> None:
        """Restore tracked files in cwd to a snapshot SHA from _gitSnapshot (revert edits since)."""
        if not sha:
            return
        try:
            subprocess.run(["git", "checkout", sha, "--", "."], cwd=cwd, capture_output=True, text=True, timeout=30)
        except Exception as e:  # noqa: BLE001
            LOG.warning("remediation revert failed: %s", e)

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

    def _runIsDegraded(self, state: TaskState) -> bool:
        """A run is degraded if its self-mod gate reverted core changes, or fewer than half its
        subtasks passed. Such a run must never auto-ship -- not even in night mode."""
        notes = state.data.get("notifications", []) if isinstance(state.data, dict) else []
        # FX-11: key off the STRUCTURED `reverted` flag, not a "REVERTED" substring. A gate that KEPT
        # a change on a pre-existing-red baseline must NOT be classified degraded (it deliberately kept).
        if any(isinstance(n, dict) and n.get("kind") == "selfmod_gate" and n.get("reverted") for n in notes):
            return True
        done, total = state.progress()
        return total > 0 and done * 2 < total

    def _prGate(self, review: dict, auto_pr: bool, state: TaskState) -> "tuple[bool, str]":
        """Decide whether to create the PR. Returns (create, skip_reason)."""
        if not auto_pr:
            return False, "--no-pr"
        # FX-18: a DEGRADED run (most subtasks failed, or core changes reverted) must NEVER open a PR,
        # INDEPENDENT of the adversary verdict. The brain frequently auto-approves/stubs (empty
        # completions), so gating the degraded check behind a 'challenged' verdict made it dead code.
        if self._runIsDegraded(state):
            return False, "degraded run (majority failed / core reverted) — PR held for review"
        if config.ADVERSARY_PR_HOLD_ENABLED and review.get("verdict") == "challenged":
            # Night mode normally suppresses an advisory challenge hold (hands-off); the degraded
            # check above already covers the must-never-ship cases regardless of night mode.
            if not config.NIGHT_MODE:
                concerns = "; ".join(review.get("concerns") or ["challenged"])
                return False, f"adversary HOLD: {concerns}"[:300]
        return True, ""

    def _prePrSuiteGate(self, state: TaskState, work_dir: str) -> "tuple[bool, str]":
        """For a self-improvement run, run the FULL test suite before opening a PR so 9to5 NEVER ships
        a PR whose own tests are broken. The selfmod gate only runs the suite when CORE files change;
        a run that edits non-core files or adds tests (e.g. test dirs that shadow a real package) could
        otherwise open a red PR. Returns (ok, detail). Best-effort: a gate-internal error does NOT
        block the PR (we don't want the gate itself to wedge the run)."""
        if not state.meta.get("is_self_referential"):
            return True, ""
        try:
            import selfmod
            passed, tail = selfmod._default_test_runner(work_dir)
            return bool(passed), (tail or "")[-400:]
        except Exception as e:  # noqa: BLE001
            LOG.warning("pre-PR suite gate errored (%s); not blocking PR", e)
            return True, f"gate-error: {e}"

    # ===================================================================
    # Phase 4 -- PR creation (best effort; skips gracefully)
    # ===================================================================
    def createPullRequest(self, state: TaskState, work_dir: str) -> dict:
        # Hard timeout + DEVNULL stdin + GIT_TERMINAL_PROMPT=0 so a credential/auth/network prompt
        # at the very end can NEVER hang the run forever (work is already committed locally) -- the
        # run must always reach finalization (CB-14). A timeout degrades to a clean "skipped".
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"   # git never blocks on a credential prompt

        def _runp(cmd: list[str]) -> subprocess.CompletedProcess:
            return subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True,
                                  stdin=subprocess.DEVNULL, env=env,
                                  timeout=config.GIT_TIMEOUT_SECONDS)

        def git(*args: str) -> subprocess.CompletedProcess:
            return _runp(["git", *args])

        try:
            chk = git("rev-parse", "--is-inside-work-tree")
            if chk.returncode != 0 or "true" not in (chk.stdout or "").lower():
                LOG.info("PR skipped: %s is not a git repository", work_dir)
                return {"skipped": True, "reason": "not a git repository"}
            # FX-23: a self-ref run already works on `sc/<id>`; reuse it as the PR head so the announced
            # branch IS the PR branch (no divergent `9to5/<id>` the user can't find).
            branch = state.meta.get("self_ref_branch") or f"9to5/{state.task_id[:8]}"
            git("checkout", "-B", branch)
            git("add", "-A")
            commit = git("commit", "-m", f"9TO5: {state.meta['goal_raw'][:60]}")
            # FX-16: if nothing was staged, the work never reached the tracked tree (e.g. the executor
            # wrote only into the gitignored .sc-ctx scratch). Do NOT open an empty/misleading PR --
            # report it honestly so the run finalizes 'partial', not a green "PR created".
            if commit.returncode != 0 and "nothing to commit" in ((commit.stdout or "") + (commit.stderr or "")).lower():
                LOG.warning("PR skipped: no tracked changes to commit (work may have landed in .sc-ctx)")
                return {"skipped": True, "reason": "no tracked changes produced"}
            push = git("push", "-u", "origin", branch)
            if push.returncode != 0:
                return {"skipped": True, "reason": f"git push failed: {(push.stderr or '')[:200]}"}
            pr = _runp(["gh", "pr", "create", "--fill", "--head", branch])
            if pr.returncode != 0:
                return {"skipped": True, "reason": f"gh pr create failed: {(pr.stderr or '')[:200]}"}
            return {"ok": True, "url": (pr.stdout or "").strip()}
        except subprocess.TimeoutExpired as e:
            LOG.error("PR creation timed out (%ss) on %s -- finalizing without a PR", config.GIT_TIMEOUT_SECONDS, e.cmd)
            return {"skipped": True, "reason": f"git/gh timed out after {config.GIT_TIMEOUT_SECONDS}s"}
        except Exception as e:  # noqa: BLE001 -- PR is best-effort; never block finalization
            LOG.warning("PR creation failed (%s) -- finalizing without a PR", e)
            return {"skipped": True, "reason": f"PR error: {e}"[:200]}

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
                # FX-20: record the model the executor will ACTUALLY route to by effort (low->haiku,
                # default/high->sonnet, xhigh/ultracode->opus) -- not a hardcoded opus. State/Obsidian/
                # dashboards/SIE attribution read session.model and were wrong for most subtasks.
                routed_model = config.MODEL_BY_EFFORT.get(
                    (spec.get("effort_level") or "default").lower(), config.PRIMARY_MODEL)
                sess.update({"effort": spec.get("effort_level"), "model": routed_model,
                             "skills": spec.get("skills_to_invoke"), "subagent": spec.get("subagent"),
                             "surfaces": surfaces.surfaces_used(spec),   # SIE surface learning
                             "use_workflow": bool(spec.get("use_workflow")), "attempts": attempt})
                state.updateSubtask(sid, session=sess)
            LOG.info("Subtask %s attempt %d/%d effort=%s", sid, attempt, config.MAX_SUBTASK_ATTEMPTS,
                     spec.get("effort_level"))
            dashboard.update(state, "executing", f"{sid} attempt {attempt} · effort {spec.get('effort_level')}",
                             effort=spec.get("effort_level"))
            attempt_started = time.time()
            hands = self._selectExecutor(spec)   # route to the right surface (terminal | browser)
            # cancel_check lets a long in-hands wait (the session-token-limit pause) break early on
            # an abort or the work-horizon deadline instead of wedging the run for hours (CB-9).
            result = hands(spec, work_dir=exec_cwd, task_state=state, subtask=subtask,
                           resume_session=resume_session,
                           cancel_check=lambda: bus.isAbort() or self._deadlinePassed(state))
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

            # FX-1: an ABSENT verify must not be a blind "the CLI didn't crash = PASS". If the subtask
            # references a fresh artifact this attempt produced, synthesize a behavioral check (run it)
            # so broken/partial work can actually FAIL. Only when nothing is referenceable do we fall
            # back to the executor-exit-zero signal -- and we then mark the result `unverified` so
            # status/embeds (and the pre-PR gate) don't treat it as a real verification.
            effective_verify = verify_spec
            if not (verify_spec or {}).get("cmd"):
                synth = self._repairVerify(subtask, exec_cwd, attempt_started)
                if synth:
                    effective_verify = synth
                    LOG.info("%s: no verify authored -> synthesized behavioral check %s", sid, synth["cmd"])
            vresult = verifier.runVerification(effective_verify, exec_cwd, result)
            passed = bool(vresult["passed"])
            if not (effective_verify or {}).get("cmd"):
                vresult["unverified"] = True   # exit-zero fallback only; no behavioral assertion ran
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
            # honor !pause mid-subtask via the SHARED escapable wait (abort / night-mode timeout /
            # deadline) -- the inline loop here previously ignored all three and could wedge an
            # unattended night run forever (CB-1).
            self._waitWhilePaused(state, bus, dashboard, label=f"{sid} paused")
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
            _adv_verdict = None
            triggered, reason = adversary.shouldTrigger(combined, heartbeat_ordinal, attempt)
            if triggered:
                rv = self._review(subtask["title"], reason, combined,
                                  ollama_chat=self._ollamaChat,
                                  goal=state.meta.get("goal_elaborated") or state.meta.get("goal_raw", ""))
                _adv_verdict = rv.get("verdict")
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

            # SIE subsystem I: capture the executor's learning summary (trust-checked against
            # the real verify + adversary verdict) and memoize a passing spec. Best-effort.
            try:
                reflection.capture(run_id=state.task_id, subtask_id=sid, executor_output=combined,
                                   verify_passed=passed, adversary_verdict=_adv_verdict)
                if passed and spec.get("prompt"):
                    import json as _json
                    solution_cache_spec = _json.dumps({k: spec.get(k) for k in
                        ("prompt", "effort_level", "skills_to_invoke", "subagent") if spec.get(k)})
                    experience.upsert_solution(solution_cache.signature_of(subtask.get("title", "")),
                                               solution_cache_spec, verify_passed=True)
            except Exception:  # noqa: BLE001 -- learning never affects the run
                pass

            # Replan after a PASSED subtask always; after a FAILED one ONLY on a self-improvement
            # run, where the pump must keep finding the next highest-impact work instead of dying on
            # the first failed wave. The churn risk (fail -> re-add -> fail) is contained by: the
            # replanner is told NOT to re-add the same failed work, the pending-only cap bounds the
            # live queue, and the no-progress livelock guard still trips. A normal bounded goal keeps
            # the conservative done-only gate, so a never-succeeding executor still degrades to partial.
            self_ref = bool(state.meta.get("is_self_referential"))
            replan_ok = final == "done" or (self_ref and final == "failed")
            if replan_ok and not self._singleDeliverable(state.meta.get("goal_elaborated", "")):
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

    def _pendingCount(self, state: TaskState) -> int:
        """Subtasks still in the live queue (pending or running). The replan/backfill cap counts
        THIS, not the all-time total, so a long self-improvement run can churn through many
        subtasks over the horizon while never letting the in-flight queue explode."""
        return sum(1 for s in state.subtasks if s["status"] in ("pending", "in_progress"))

    def authorBackfillBatch(self, goal_elaborated: str, architect_doc: str, done_titles: list[str],
                            failed_titles: list[str], remaining_hours: float, room: int) -> list[dict]:
        """Ollama authors the NEXT batch of highest-impact improvement subtasks for a self-improvement
        run whose queue has drained with time still on the clock. Returns list[dict] (maybe empty)."""
        system = (
            config.SELF_IMPROVEMENT_PHILOSOPHY + "\n\n"
            "You are the HORIZON-FILL planner for 9TO5 running ON ITSELF. The subtask queue is now EMPTY "
            "but time remains in the work window. Author the NEXT small batch of the HIGHEST-IMPACT "
            "improvement subtasks the codebase needs right now (bug hunts, error handling, missing tests, "
            "refactors of weak areas, reliability). Do NOT repeat work already done and do NOT re-attempt "
            "the same FAILED work -- choose NEW, different, valuable work. "
            f"Return AT MOST {room} subtasks that realistically fit ~{remaining_hours:.1f}h.\n"
            '_RESPOND WITH JSON ONLY_: {"subtasks":[{"title":"...","description":"...","layer":3,'
            '"effort_level":"default|high","verify":{"cmd":"python ' + _VERIFY_EXAMPLE_PATH +
            '","expect":"exit_zero"}}]}.\n'
            "Every verify must use a REAL existing absolute path -- NEVER angle brackets or the words "
            "'ABSOLUTE path' (a cmd containing '<' or '>' is rejected); on Windows never a .sh/bash verify."
        )
        user = (
            f"Goal / standing mandate:\n{goal_elaborated}\n\n"
            f"Already DONE: {done_titles or '(none)'}\n"
            f"Already FAILED (do NOT retry these): {failed_titles or '(none)'}\n"
            f"Time remaining: ~{remaining_hours:.1f}h. Author up to {room} NEW subtasks.\n"
            f"Architecture:\n{(architect_doc or '')[:2000]}\n\nReturn the plan JSON."
        )
        resp = self._ollamaChat(system, user, want_json=True)
        parsed = _chatJson(resp)
        raw = parsed.get("subtasks") if isinstance(parsed, dict) else None
        return [s for s in raw if isinstance(s, dict)] if isinstance(raw, list) else []

    def _backfill(self, state: TaskState, architect_doc: str, dashboard: DiscordDashboard) -> int:
        """Horizon-fill: when a self-improvement run's queue drains with time left, author + enqueue
        the next batch of improvement subtasks. Returns the number added (0 => nothing more to do)."""
        remaining = self._remainingHours(state)
        if remaining is None or remaining <= 0:
            return 0
        room = config.MAX_SUBTASKS - self._pendingCount(state)
        if room <= 0:
            return 0
        goal = state.meta.get("goal_elaborated") or state.meta.get("goal_raw", "")
        done = [s.get("title", "") for s in state.subtasks if s["status"] == "done"]
        failed = [s.get("title", "") for s in state.subtasks if s["status"] == "failed"]
        try:
            batch = self.authorBackfillBatch(goal, architect_doc, done, failed, remaining, room)
        except Exception as e:  # noqa: BLE001 -- backfill must never crash the run
            LOG.warning("backfill authoring failed (%s); using open-ended fallback", e)
            batch = []
        batch = [s for s in (batch or []) if isinstance(s, dict)]
        if batch:
            # A brain-authored batch IS tied to the goal's requirements, so requirement-aware
            # strengthening is correct here.
            batch = self._strengthenPlanVerifies(goal, batch)
        else:
            # CONTINUITY FIX (found in the live test): the local 7B brain's JSON is unreliable, so
            # authorBackfillBatch frequently returns empty -- horizon-fill would then silently no-op
            # and a self-improvement run would finalize at ~30% of its horizon (18/60 min observed).
            # Fall back to ONE open-ended improvement subtask and let the capable executor (Claude)
            # choose the work, so the run keeps producing value until the deadline. Bounded by the
            # deadline and the pending-queue cap; each subtask is a real multi-minute run (no spin).
            # IMPORTANT (LIVE BUG #2a): do NOT run _strengthenPlanVerifies on this OPEN-ENDED subtask
            # -- it isn't tied to the goal's enumerated requirements, so a strict compound verify over
            # all of them is wrong (it would spuriously fail, or pass trivially on bloated markers).
            # Leave verify=None so it gates on the executor exiting cleanly.
            LOG.info("backfill: brain authored no batch -> enqueuing 1 open-ended improvement subtask")
            recent = "\n- ".join(done[-8:]) if done else "(none yet)"
            batch = [{
                "title": "Autonomous improvement (horizon-fill)",
                "description": (
                    "The planned work is complete but time remains in the work window. Per the 9to5 "
                    "self-improvement mandate, make ONE surgical, high-impact, VERIFIED improvement now: "
                    "fix a robustness/continuity bug, add missing test coverage for an under-tested "
                    "module, or strengthen error handling in a weak NON-CORE module. Keep it on-scope "
                    f"and do NOT repeat recently-completed work:\n- {recent}"),
                "layer": 3, "effort_level": "high", "verify": None,
            }]
        added = 0
        with self._state_lock:
            for s in batch[:room]:
                state.addSubtask(s.get("title", "improvement"), s.get("description", ""),
                                 layer=s.get("layer", 3), verify=verifier.sanitizeVerify(s.get("verify")))
                added += 1
            if added:
                state.addNotification("backfill", f"+{added} improvement subtasks ({remaining:.1f}h left)")
                self.writeIndex(state)
        if added:
            LOG.info("horizon-fill: +%d improvement subtasks (%.1fh remaining)", added, remaining)
            dashboard.update(state, "planning", f"horizon-fill: +{added} subtasks ({remaining:.1f}h left)")
        return added

    def _continueAfterDrain(self, state: TaskState, architect_doc: str,
                            dashboard: DiscordDashboard, dry: int) -> "tuple[bool, int]":
        """The subtask queue is empty. Decide whether to keep the run alive (returns (continue, dry)).

        A NORMAL bounded goal is DONE when its queue drains -- break. A SELF-IMPROVEMENT run with time
        left should keep going (CLAUDE.md: 'keep going instrumentally until the time horizon ends'):
        author a fresh batch via _backfill. Break only when the deadline is reached, <15 min remain, or
        backfill comes up empty twice in a row (nothing left worth doing)."""
        if not state.meta.get("is_self_referential"):
            LOG.info("queue drained on a bounded run -> finalizing")
            return False, dry
        if self._deadlinePassed(state):
            LOG.info("queue drained, deadline passed -> finalizing")
            return False, dry
        remaining = self._remainingHours(state)
        if remaining is None or remaining <= 0.25:   # don't start new work in the last 15 minutes
            LOG.info("queue drained, <15 min left (%.2fh) -> finalizing", remaining or 0.0)
            return False, dry
        LOG.info("queue drained with %.2fh left -> horizon-fill backfill (dry=%d)", remaining, dry)
        added = self._backfill(state, architect_doc, dashboard)
        if added > 0:
            return True, 0
        # With the open-ended fallback in _backfill, this is reached only when the pending cap is
        # full; allow one retry then finalize so we never spin.
        LOG.warning("horizon-fill backfill added nothing (dry=%d) -> %s", dry + 1,
                    "retry" if dry + 1 < 2 else "finalize")
        return (dry + 1 < 2), dry + 1

    def runExecutionLoop(self, state: TaskState, architect_doc: str, work_dir: str,
                         bus: ControlBus, dashboard: DiscordDashboard, parallelism: int = 1) -> None:
        position = 0
        iters = 0
        no_progress = 0
        prev_terminal = -1
        dry_backfills = 0     # consecutive empty horizon-fill attempts (self-improvement runs)
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
                    discord.sendEmbed(discord.noticeEmbed(
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
                    discord.sendEmbed(discord.noticeEmbed("Execution loop guard tripped (possible livelock) — auto-aborting"))
                except Exception:  # noqa: BLE001
                    pass
                raise AbortRun("execution loop guard tripped (livelock)")
            self._checkControl(state, bus, dashboard)
            if parallelism <= 1:
                subtask = state.nextActionable()
                if subtask is None:
                    cont, dry_backfills = self._continueAfterDrain(state, architect_doc, dashboard, dry_backfills)
                    if cont:
                        continue
                    break
                position += 1
                try:
                    self._executeSubtask(state, subtask, architect_doc, work_dir, bus, dashboard, position)
                except AbortRun:
                    raise
                except Exception as e:  # noqa: BLE001 -- one bad subtask must not kill the run
                    LOG.error("Subtask %s crashed: %s", subtask.get("subtask_id"), e, exc_info=True)
                    try:
                        discord.sendEmbed(discord.noticeEmbed(f"Subtask {subtask.get('subtask_id')} crashed (marked failed, run continues): {e}"))
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
                    cont, dry_backfills = self._continueAfterDrain(state, architect_doc, dashboard, dry_backfills)
                    if cont:
                        continue
                    break
                ready = [state.nextActionable()]
            batch = ready[:parallelism]
            with ThreadPoolExecutor(max_workers=parallelism) as pool:
                futures = {}
                for st in batch:
                    position += 1
                    # FX-8: derive the cwd via the SAME helper as the sequential path so parallel and
                    # sequential behave identically (the old hardcoded .sc-ctx broke non-self-ref
                    # parallel runs -- wrong cwd, work lost, or FileNotFoundError on a missing dir).
                    ctx = self._execCwd(state, st["subtask_id"], work_dir)
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
            # This batch's worker threads have exited; their thread-local SQLite connections are now
            # dead weight pinned in the experience pool's global registry. Close them so connections
            # (and WAL/SHM handles) don't accumulate unboundedly across hundreds of batches (CB-3).
            try:
                experience.close_pool()
            except Exception:  # noqa: BLE001 -- best-effort cleanup, never affects the run
                pass
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
        # Cap the LIVE queue (pending + in-progress), not the all-time total: a long self-improvement
        # run churns through many subtasks over the horizon, so counting terminal ones would freeze
        # the plan after MAX_SUBTASKS and kill horizon-fill (RC-2).
        active = self._pendingCount(state)
        # The brain may return malformed add/remove (non-list, or items of the wrong type). A crash
        # here would propagate to the caller's handler and flip the just-COMPLETED subtask to failed,
        # so coerce defensively and skip any entry that isn't the expected shape.
        # FX-24: de-dup adds against the live (pending/in-progress) queue so two parallel workers that
        # both propose the same backfill title (their replan decisions race lock-free) don't enqueue
        # duplicate subtasks that both run (wasted horizon / conflicting edits to the same file).
        live_titles = {(s.get("title") or "").strip().lower()
                       for s in state.subtasks if s["status"] in ("pending", "in_progress")}
        adds = decision.get("add") or []
        for add in (adds if isinstance(adds, list) else []):
            if not isinstance(add, dict):
                continue
            title = (add.get("title") or "untitled").strip()
            if title.lower() in live_titles:
                diff.append(f"(skipped duplicate add '{title}')")
                continue
            if active >= config.MAX_SUBTASKS:
                LOG.info("replan add skipped: MAX_SUBTASKS (%d) reached", config.MAX_SUBTASKS)
                diff.append(f"(skipped add '{title}' -- MAX_SUBTASKS cap)")
                break
            st = state.addSubtask(title, add.get("description", ""),
                                  layer=add.get("layer", 3), verify=verifier.sanitizeVerify(add.get("verify")))
            live_titles.add(title.lower())
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
                # FX-19: the BRAIN dropped a planned, never-completed subtask. For a bounded goal that
                # means a deliverable was silently dropped -> the run is not a clean "done". Record it
                # so finalization reports 'partial' rather than "done N/N" on the shrunken denominator.
                state.addNotification("replan_removed", f"{rid} {st.get('title', '')}"[:200])
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
        # appears in any goal that writes a file under C:\9to5\... .
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
        discord.sendEmbed(discord.selfRefEmbed(branch, config.CORE_PROTECTED_FILES))
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
        """ALWAYS give the executor an isolated `.sc-ctx/<sid>` cwd (FX-7). The living CLAUDE.md is
        written into the cwd, so without isolation a run targeting an EXTERNAL repo (`--work-dir`)
        would clobber/leak that repo's own CLAUDE.md into the PR. work_dir stays an ancestor (auto-read
        for context); the executor edits the target via ABSOLUTE paths (per its charter/playbook).
        The scratch dir is removed by _cleanupScaffolding at the end of the run."""
        ctx = os.path.join(str(work_dir), ".sc-ctx", sid or "architect")
        os.makedirs(ctx, exist_ok=True)
        return ctx

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
                        discord.sendEmbed(discord.noticeEmbed(
                            f"Architect phase produced only {len(architect_doc)} chars — proceeding (planning may be degraded)"))
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

            # --- Phase 3.5: self-modification safety gate ---
            # If this self-ref run changed its OWN core loop files, run the test suite in a
            # fresh interpreter and REVERT any change that breaks the build before we PR it.
            if state.meta.get("is_self_referential"):
                try:
                    import selfmod
                    gate = selfmod.safety_gate(work_dir, is_self_referential=True)
                    if gate.get("ran"):
                        # FX-11: label from the ACTUAL outcome. safety_gate may KEEP a core change when
                        # the baseline is also red (kept_despite_failure) -- calling that "REVERTED" is
                        # factually wrong AND trips _runIsDegraded's "REVERTED" match, holding a PR the
                        # gate deliberately chose to keep. Record a structured `reverted` flag too.
                        if gate.get("passed"):
                            verdict = "PASSED"
                        elif gate.get("reverted"):
                            verdict = "REVERTED (tests failed)"
                        else:
                            verdict = "KEPT (pre-existing test failure)"
                        dashboard.update(state, "executing", f"core self-mod gate: {verdict}")
                        state.addNotification("selfmod_gate", f"{verdict}: {gate.get('changed')}",
                                              reverted=bool(gate.get("reverted")))
                except Exception:  # noqa: BLE001 -- safety gate is best-effort, never blocks
                    LOG.warning("selfmod safety gate failed (ignored)", exc_info=True)

            # --- Phase 4: PR + complete ---
            self._checkControl(state, bus, dashboard, gate="pre_pr")
            pr_review = self._prePrAdversary(state)
            create_pr, skip_reason = self._prGate(pr_review, auto_pr, state)
            if create_pr:
                # Final gate: never open a PR whose own test suite is red (a self-improvement run can
                # otherwise ship structurally-broken work the weak per-subtask verify missed, e.g. a
                # tests/<pkg>/ dir that shadows a real package). The work stays on the branch for review.
                suite_ok, suite_detail = self._prePrSuiteGate(state, work_dir)
                if not suite_ok:
                    create_pr = False
                    skip_reason = "test suite failing — PR held for review"
                    dashboard.update(state, "executing", "PR held: test suite failing")
                    state.addNotification("pr_held", f"test suite failing: {suite_detail[:160]}")
                    try:
                        discord.sendEmbed(discord.noticeEmbed(
                            "PR held: the run's own test suite is failing — work left on the branch for review.",
                            title="🛡️ 9TO5 — PR held (red suite)"))
                    except Exception:  # noqa: BLE001
                        pass
            if create_pr:
                pr = self.createPullRequest(state, work_dir)
            else:
                pr = {"skipped": True, "reason": skip_reason}
                if skip_reason.startswith("adversary HOLD"):
                    dashboard.update(state, "executing", f"PR held by adversary: {skip_reason}")
                    state.addNotification("pr_held", skip_reason)
            elapsed = _elapsedSince(state.meta["started_at"])
            done, total = state.progress()
            # FX-9: status must reflect REALITY. A PR HELD because the work is BROKEN (red suite) or
            # DEGRADED (majority failed / core reverted) is NOT "done" -- report 'partial' so the
            # complete embed can't claim success on broken work. An advisory adversary-challenge hold
            # on otherwise all-done work stays "done" (the work completed; the PR is flagged for review).
            reason = str(pr.get("reason", ""))
            held_broken = bool(pr.get("skipped")) and any(
                s in reason for s in ("test suite failing", "degraded run", "no tracked changes"))
            # FX-19: for a BOUNDED (non-self-ref) goal, a planned subtask the brain removed without
            # completing is a dropped deliverable -> not a clean "done" (self-ref runs have no fixed
            # deliverable list, so their replan-removes are fine).
            dropped_planned = (not state.meta.get("is_self_referential")) and any(
                isinstance(n, dict) and n.get("kind") == "replan_removed"
                for n in (state.data.get("notifications", []) or []))
            all_done = total > 0 and done == total
            final_status = "done" if (all_done and not held_broken and not dropped_planned) else "partial"
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
            discord.sendEmbed(discord.abortedEmbed(reason, _fmtElapsed(elapsed)))
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
                discord.sendEmbed(discord.noticeEmbed(f"9to5 run crashed: {e} — supervisor will auto-recover if time remains"))
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
                    _mt = sie.run_maintenance_async(reason="post-run")
                    # Join with a bounded timeout so the pass DURABLY finishes (writes last_full_at)
                    # before the process exits; a bare daemon would be killed mid-write at shutdown,
                    # leaving the throttle stuck so the next run re-runs the full pass forever (CB-11).
                    # When not due it returns ~instantly, so this adds no latency on most runs.
                    if _mt is not None:
                        _mt.join(timeout=config.SIE_MAINTENANCE_JOIN_SECONDS)
                except Exception:  # noqa: BLE001 -- learning is best-effort, never blocks
                    LOG.debug("sie maintenance dispatch failed (ignored)", exc_info=True)
