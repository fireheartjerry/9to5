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
        "implementer": ({"prompt": "implement foo in bar.py"}, {"title": "Add foo", "description": "write code"}),
        "architect": ({"subagent": "architect"}, {"title": "design", "description": "x"}),
        "reviewer": ({"subagent": "security-reviewer"}, {"title": "rv", "description": "x"}),
        "pr": ({"skills_to_invoke": ["/create-pr"]}, {"title": "pr", "description": "x"}),
        "tester": ({"prompt": "add pytest tests"}, {"title": "test it", "description": "coverage"}),
        "docs": ({"prompt": "update the readme"}, {"title": "document", "description": "docs"}),
        "generalist": ({"prompt": "x"}, {"title": "misc", "description": "thing"}),
    }
    for want, (spec, st) in cases.items():
        check(f"classify -> {want}", playbook.classifyProfile(spec, st) == want)
    check("implementer charter has Read-before-Edit", "Read a file BEFORE editing" in playbook.buildCharter("implementer"))
    check("implementer playbook has nitty-gritty", "Implementation discipline" in playbook.buildPlaybook("implementer"))
    check("reviewer charter is read-only", "READ-ONLY" in playbook.buildCharter("reviewer"))


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


def main() -> int:
    for t in (test_local_scan, test_unified_idempotent, test_compress_injection,
              test_injection_shared_cache, test_playbook, test_dynamic_workflow_spec):
        t()
    print()
    if _FAILS:
        print(f"FAILED ({len(_FAILS)}): {', '.join(_FAILS)}")
        return 1
    print("ALL LIVING-KNOWLEDGE TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
