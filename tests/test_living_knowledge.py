"""Standalone regression tests for the living-knowledge + executor-playbook system.

Runnable WITHOUT pytest (matches 9to5's `python <file>` exit_zero verify style):

    venv\\Scripts\\python tests\\test_living_knowledge.py   # exits 0 on pass, 1 on fail

Side-effect-free: exercises the pure builders, the shared injection cache, the executor
playbook, and dynamic-workflow spec handling -- it never writes claude_code.md or hits the
network (offline only), so it is safe to run any time.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

# repo root on path + stub the one pip dep this throwaway run may lack
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if "ollama" not in sys.modules:
    _m = types.ModuleType("ollama"); _m.Client = lambda *a, **k: None  # type: ignore
    sys.modules["ollama"] = _m

import config           # noqa: E402
import knowledge        # noqa: E402

_FAILS: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        _FAILS.append(name)


def test_local_scan() -> None:
    print("[scanLocalClaude]")
    inv = knowledge.scanLocalClaude()
    check("finds >=1 skill", len(inv["skills"]) >= 1)
    check("finds >=1 subagent", len(inv["agents"]) >= 1)
    check("captures hooks", len(inv["hooks"]) >= 1)


def test_unified_idempotent() -> None:
    print("[buildUnifiedDoc idempotency]")
    local = knowledge.scanLocalClaude()
    empty = {"pages": {}, "ok": [], "failed": []}
    psk = {"found": False, "text": "", "path": None}
    recs = {"found": True, "text": "## Executive Recommendations — Top 20\n1. do x\n", "path": "r"}
    authored = "## Authored\nbody\n"
    d1 = knowledge.buildUnifiedDoc(authored, empty, local, psk, refreshed_at="t1", sources=["a"], recs=recs)
    d2 = knowledge.buildUnifiedDoc(d1, empty, local, psk, refreshed_at="t2", sources=["a"], recs=recs)
    d3 = knowledge.buildUnifiedDoc(d2, empty, local, psk, refreshed_at="t3", sources=["a"], recs=recs)
    check("re-fold does not grow", len(d2) == len(d3))
    check("single Part A", d3.count("# Part A") == 1)
    check("single Part E", d3.count("# Part E") == 1)
    check("authored body survives into Part A", "## Authored" in d3)


def test_compress_injection() -> None:
    print("[compressForInjection]")
    local = knowledge.scanLocalClaude()
    empty = {"pages": {}, "ok": [], "failed": []}
    recs = {"found": True, "text": "## Executive Recommendations — Top 20\n1. always inject exact paths\n", "path": "r"}
    out = knowledge.compressForInjection("## Slash Commands\nx\n", local, empty, recs=recs)
    check("under cap", len(out) <= config.CLAUDE_CAPABILITIES_MAX_CHARS)
    for token in ("Installed skills", "Effort levels", "Scheduling / waiting", "use_workflow",
                  "decision tree".title()[:8].lower()):
        pass
    check("has effort cheatsheet", "Effort levels" in out)
    check("has scheduling/footguns", "Scheduling / waiting" in out and "FOOTGUNS" in out)
    check("has decision tree", "decision tree" in out.lower())
    check("surfaces executive recs", "Expert recommendations" in out)
    check("no scraped-URL noise in index", "https://" not in out.split("Full reference index")[-1]
          if "Full reference index" in out else True)


def test_injection_shared_cache() -> None:
    print("[injectCapabilities shared cache]")
    knowledge.setCapabilities("")                      # clear
    caps = knowledge.ensureCapabilities()              # offline lazy build
    check("ensureCapabilities builds offline", bool(caps))
    inj = knowledge.injectCapabilities("BASE_SYS")
    check("prepends capabilities header", inj.startswith("## CLAUDE CODE CAPABILITIES"))
    check("has the consult directive", "FORBIDDEN" in inj)
    check("preserves base prompt", inj.rstrip().endswith("BASE_SYS"))
    knowledge.setCapabilities("CACHED")
    check("getCapabilities returns cache", knowledge.getCapabilities() == "CACHED")


def test_playbook() -> None:
    print("[executor playbook]")
    from agents import playbook
    cases = {
        "implementer": ({}, {"title": "Add the foo function", "description": "implement it in bar.py"}),
        "architect": ({"subagent": "architect"}, {"title": "design", "description": "x"}),
        "reviewer": ({"subagent": "security-reviewer"}, {"title": "rv", "description": "x"}),
        "pr": ({"skills_to_invoke": ["/create-pr"]}, {"title": "pr", "description": "x"}),
        "tester": ({}, {"title": "add unit tests", "description": "pytest coverage"}),
        "docs": ({}, {"title": "update the README", "description": "documentation"}),
        "generalist": ({}, {"title": "misc", "description": "do a thing"}),
    }
    for want, (spec, st) in cases.items():
        check(f"classify -> {want}", playbook.classifyProfile(spec, st) == want)
    # REGRESSION (audit HIGH): a write-intent subtask must NEVER get a read-only profile,
    # incl. when the text mentions security/architecture/preview (substring traps).
    readonly = ("architect", "reviewer")
    for title, desc in [("implement security hardening", "add input validation"),
                        ("harden the auth flow", "security"),
                        ("implement the architecture from architect.md", "build it"),
                        ("add a live preview pane", "ui"),
                        ("update to the latest version", "bump deps")]:
        got = playbook.classifyProfile({}, {"title": title, "description": desc})
        check(f"write-intent NOT read-only: {title!r} -> {got}", got not in readonly)
    # read-only tasks (no implement verb) still route correctly
    check("pure review -> reviewer", playbook.classifyProfile({}, {"title": "review the auth module", "description": "x"}) == "reviewer")
    check("security audit -> reviewer", playbook.classifyProfile({}, {"title": "security audit of the API", "description": "x"}) == "reviewer")
    check("system design -> architect", playbook.classifyProfile({}, {"title": "design the system architecture", "description": "x"}) == "architect")
    # spec['prompt'] must NOT drive classification (self-ref prompts echo the architecture brief)
    check("prompt ignored for classify", playbook.classifyProfile(
        {"prompt": "review the architecture and security audit everything"}, {"title": "Add foo", "description": "write code"}) == "implementer")
    check("implementer charter has Read-before-Edit", "Read a file BEFORE editing" in playbook.buildCharter("implementer"))
    check("implementer playbook has nitty-gritty", "Implementation discipline" in playbook.buildPlaybook("implementer"))
    check("reviewer charter is read-only", "READ-ONLY" in playbook.buildCharter("reviewer"))


def test_part_d_preserved() -> None:
    print("[Part D preservation on empty/degraded scrape]")
    local = knowledge.scanLocalClaude()
    psk = {"found": False, "text": "", "path": None}
    full = {"pages": {f"https://d/{i}": "x" * 300 for i in range(10)}, "ok": [], "failed": []}
    # build a doc WITH a fresh Part D, then refresh OFFLINE (no pages) -> Part D must survive
    d_full = knowledge.buildUnifiedDoc("## A\nb\n", full, local, psk, refreshed_at="t1", sources=["s"])
    check("fresh scrape emits Part D", "# Part D —" in d_full)
    empty = {"pages": {}, "ok": [], "failed": []}
    d_off = knowledge.buildUnifiedDoc(d_full, empty, local, psk, refreshed_at="t2", sources=["s"])
    check("offline refresh PRESERVES prior Part D (no erase)", "# Part D —" in d_off)
    check("preserved Part D keeps the live pages", d_off.count("## https://d/") >= 10)


def test_dynamic_workflow_spec() -> None:
    print("[dynamic workflow spec + render]")
    import orchestrator as orch
    o = orch.Orchestrator()
    good = {"prompt": "p", "use_workflow": True,
            "workflow_definition": {"name": "wf", "phases": [{"title": "P1", "parallel": True,
                                    "agents": [{"label": "a", "prompt": "x"}]}]}}
    s = o._sanitizeSpec(good, {"description": "d", "title": "t"})
    check("well-formed workflow honored", s["use_workflow"] and s["workflow_definition"]["name"] == "wf")
    bad = o._sanitizeSpec({"use_workflow": True, "workflow_definition": {"name": "nophases"}}, {"title": "t"})
    check("phaseless workflow rejected", bad["use_workflow"] is False and bad["workflow_definition"] is None)
    from agents import executor
    rendered = executor._composePrompt(executor.normalizeSpec(good), None, None)
    check("renders multi-phase workflow", "EXECUTE THIS DYNAMIC WORKFLOW" in rendered and "[PARALLEL]" in rendered)
    flat = executor._composePrompt(executor.normalizeSpec({"prompt": "just X"}), None, None)
    check("flat prompt unaffected", flat == "just X")


def test_spec_nudges_and_budget() -> None:
    print("[effort floor + replanner budget]")
    import orchestrator as orch
    o = orch.Orchestrator()
    strict = {"cmd": "python x.py", "expect": "stdout_contains_all:a||b||c"}
    s1 = o._sanitizeSpec({"effort_level": "default"}, {"title": "t", "description": "d", "verify": strict})
    check("strict verify floors default->high", s1["effort_level"] == "high")
    s2 = o._sanitizeSpec({"effort_level": "xhigh"}, {"title": "t", "description": "d", "verify": strict})
    check("strict verify does NOT lower xhigh", s2["effort_level"] == "xhigh")
    loose = {"cmd": "python x.py", "expect": "exit_zero"}
    s3 = o._sanitizeSpec({"effort_level": "default"}, {"title": "t", "description": "d", "verify": loose})
    check("non-strict verify left at default", s3["effort_level"] == "default")
    # replanner accepts the time budget and stays well-formed even under the ollama stub
    from agents import replanner
    d = replanner.replan("goal", [], {"subtask_id": "s", "title": "t"}, "out", remaining_hours=0.2)
    check("replan accepts remaining_hours, returns well-formed", isinstance(d, dict) and "action" in d)


def test_verifier_runs() -> None:
    print("[verifier Popen rewrite still verifies]")
    import tempfile
    from agents import verifier
    with tempfile.TemporaryDirectory() as td:
        r = verifier.runVerification({"cmd": 'python -c "print(42)"', "expect": "stdout_contains:42"}, td, {})
        check("stdout_contains passes via Popen path", r["passed"] is True)
        r2 = verifier.runVerification({"cmd": "python -c \"import sys; sys.exit(3)\"", "expect": "exit_zero"}, td, {})
        check("nonzero exit fails", r2["passed"] is False)


def test_executor_io() -> None:
    print("[executor JSON envelope + resume + env]")
    import tempfile, subprocess, json as _json
    from agents import executor
    # _parseEnvelope: json -> (text, fields); plain/ malformed -> raw fallback
    text, f = executor._parseEnvelope(_json.dumps(
        {"type": "result", "result": "hello", "is_error": False, "session_id": "s1", "total_cost_usd": 0.02, "num_turns": 3}))
    check("envelope text extracted", text == "hello")
    check("envelope fields extracted", f["session_id"] == "s1" and f["is_error"] is False and f["cost_usd"] == 0.02)
    t2, f2 = executor._parseEnvelope("just plain text")
    check("non-json falls back to raw", t2 == "just plain text" and f2 == {})
    # runClaude builds the right cmd + env (mock subprocess; save/restore the global Popen)
    cap = {}
    class _P:
        def __init__(self, cmd, **kw): cap["cmd"] = cmd; cap["env"] = kw.get("env"); self.pid = 1; self.returncode = 0
        def communicate(self, input=None, timeout=None):
            return (_json.dumps({"type": "result", "result": "did it", "is_error": False, "session_id": "S9"}), "")
    orig_popen, orig_launch = subprocess.Popen, executor._resolveClaudeLauncher
    executor._resolveClaudeLauncher = lambda: ["claude"]
    executor.subprocess.Popen = _P
    try:
        import types as _t
        st = _t.SimpleNamespace(task_id="T1", meta={})
        r = executor.runClaude({"prompt": "x", "effort_level": "high"}, work_dir=tempfile.gettempdir(),
                               task_state=st, subtask={"subtask_id": "st-007", "title": "t", "description": "implement"},
                               resume_session="SESS42")
    finally:
        executor.subprocess.Popen = orig_popen
        executor._resolveClaudeLauncher = orig_launch
    cmd = cap["cmd"]
    check("cmd has --output-format json", "--output-format" in cmd and "json" in cmd)
    check("cmd has --resume SESS42", "--resume" in cmd and "SESS42" in cmd)
    check("env carries task id", (cap["env"] or {}).get("NINE_TO_FIVE_TASK_ID") == "T1")
    check("env carries subtask id", (cap["env"] or {}).get("NINE_TO_FIVE_SUBTASK_ID") == "st-007")
    check("result stdout = assistant text", r["stdout"] == "did it")
    check("result carries session_id", r.get("session_id") == "S9")
    check("ok derived from is_error", r["ok"] is True)


def test_parse_robustness() -> None:
    print("[envelope parse robustness]")
    import json as J
    from agents import executor
    t, f = executor._parseEnvelope("Switching to fallback model\n" +
                                   J.dumps({"type": "result", "result": "42", "is_error": False, "session_id": "x"}))
    check("preamble tolerated", t == "42" and f.get("session_id") == "x")
    t2, f2 = executor._parseEnvelope(J.dumps({"type": "result", "is_error": True, "result": None, "subtype": "error_max_turns"}))
    check("error envelope -> clean marker (not raw json)", t2.startswith("[claude") and "{" not in t2 and f2["is_error"] is True)


def test_executor_resume() -> None:
    print("[resume: fold inject, drop charter, retry-fresh on stale session]")
    import tempfile, subprocess, json as J, types as T
    from agents import executor
    calls = []
    class _SP:
        def __init__(self, cmd, **kw): calls.append({"cmd": cmd, "input": None}); self.pid = 1
        def communicate(self, input=None, timeout=None):
            calls[-1]["input"] = input
            if "--resume" in calls[-1]["cmd"]:        # stale session -> nonzero rc, NO envelope
                self.returncode = 1
                return ("error: session not found", "")
            self.returncode = 0                        # fresh retry succeeds
            return (J.dumps({"type": "result", "result": "fixed it", "is_error": False, "session_id": "NEW"}), "")
    op, ol = subprocess.Popen, executor._resolveClaudeLauncher
    executor._resolveClaudeLauncher = lambda: ["claude"]; executor.subprocess.Popen = _SP
    try:
        st = T.SimpleNamespace(task_id="T", meta={})
        r = executor.runClaude({"prompt": "fix the bug", "claude_md_inject": "IMPORTANT CONTEXT", "effort_level": "high"},
                               work_dir=tempfile.gettempdir(), task_state=st,
                               subtask={"subtask_id": "st-1", "title": "t", "description": "implement"},
                               resume_session="OLD")
    finally:
        executor.subprocess.Popen = op; executor._resolveClaudeLauncher = ol
    check("stale resume triggers a fresh retry (2 launches)", len(calls) == 2)
    check("1st launch used --resume", "--resume" in calls[0]["cmd"])
    check("2nd launch dropped --resume", "--resume" not in calls[1]["cmd"])
    check("resume folded inject into prompt", "Updated context for this retry" in (calls[0]["input"] or "") and "IMPORTANT CONTEXT" in calls[0]["input"])
    check("resume dropped charter flag", "--append-system-prompt" not in calls[0]["cmd"])
    check("fresh retry re-added charter flag", "--append-system-prompt" in calls[1]["cmd"])
    check("final result is the fresh success", r["stdout"] == "fixed it" and r["ok"] is True)


def test_block_destructive_scans_resume_inject() -> None:
    print("[block_destructive scans the resume-folded inject]")
    import tempfile, types as T
    from agents import executor
    st = T.SimpleNamespace(task_id="T", meta={})
    # destructive command lives ONLY in claude_md_inject; on resume it is folded into the prompt
    r = executor.runClaude(
        {"prompt": "do the thing", "claude_md_inject": "rm -rf /tmp/data", "pre_tool_hooks": ["block_destructive"]},
        work_dir=tempfile.gettempdir(), task_state=st,
        subtask={"subtask_id": "st-1", "title": "t", "description": "implement"}, resume_session="OLD")
    check("resume-folded inject is scanned + blocked", r.get("blocked") is True and r["ok"] is False)
    # sanity: same destructive inject is ALSO blocked on a fresh (non-resume) run via full_prompt path
    r2 = executor.runClaude(
        {"prompt": "rm -rf /tmp/data", "pre_tool_hooks": ["block_destructive"]},
        work_dir=tempfile.gettempdir(), task_state=st,
        subtask={"subtask_id": "st-1", "title": "t", "description": "implement"})
    check("fresh run still blocks destructive prompt", r2.get("blocked") is True)


def test_bash_boundary_token_match() -> None:
    print("[hooks boundary path-token match (no substring over-block)]")
    from agents import hooks
    check("rm -rf state/tasks hits 'tasks'", hooks._bashHitsBoundary("rm -rf state/tasks", "tasks") is True)
    check("> config.py hits 'config.py'", hooks._bashHitsBoundary("echo x > config.py", "config.py") is True)
    check("tasks.json does NOT hit 'tasks'", hooks._bashHitsBoundary("echo x > tasks.json", "tasks") is False)
    check("my_config.py does NOT hit 'config.py'", hooks._bashHitsBoundary("printf y > my_config.py", "config.py") is False)
    check(".env hit at token", hooks._bashHitsBoundary("cat foo > .env", ".env") is True)


def test_deadline_idiom() -> None:
    print("[deadline zero/None idiom]")
    import orchestrator as orch, types as T, datetime as D
    o = orch.Orchestrator()
    now = D.datetime.now().astimezone()
    check("past/zero -> passed", o._deadlinePassed(T.SimpleNamespace(meta={"deadline_at": now.isoformat()})) is True)
    check("future -> not passed", o._deadlinePassed(T.SimpleNamespace(meta={"deadline_at": (now + D.timedelta(hours=1)).isoformat()})) is False)
    check("no deadline -> not passed", o._deadlinePassed(T.SimpleNamespace(meta={})) is False)


def main() -> int:
    for t in (test_local_scan, test_unified_idempotent, test_compress_injection,
              test_injection_shared_cache, test_playbook, test_part_d_preserved,
              test_dynamic_workflow_spec, test_spec_nudges_and_budget,
              test_verifier_runs, test_executor_io, test_parse_robustness,
              test_executor_resume, test_block_destructive_scans_resume_inject,
              test_bash_boundary_token_match, test_deadline_idiom):
        t()
    print()
    if _FAILS:
        print(f"FAILED ({len(_FAILS)}): {', '.join(_FAILS)}")
        return 1
    print("ALL LIVING-KNOWLEDGE TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
