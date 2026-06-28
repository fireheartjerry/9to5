# Proactive Discovery Engine — Design Spec

**Date:** 2026-06-28
**Status:** Approved for implementation
**Goal:** Give 9TO5 intern-level initiative — it finds its own work, prioritizes boldly, and produces transformative PRs rather than waiting for instructions.

---

## Vision

The current system is a reactive PR dispenser: give it a goal, it executes. This spec replaces that with a system that wakes up, reads the entire codebase with fresh eyes, and asks: *"What would make this dramatically better?"*

The discovery engine is not a bug-finder. It is an ambitious engineer who reads everything, synthesizes across layers, and proposes changes that matter — new capabilities, architectural reimaginings, structural improvements that compound. Incremental cleanup is the floor, not the ceiling.

---

## Trigger Logic

Discovery always runs in two modes:

**Lightweight (every run):** Digest compilation always runs. Even for specific goals, the digest is injected into the architect as background codebase context.

**Full discovery (vague or absent goal):** When the goal is absent or matches a vague pattern, the full lens panel + synthesis runs. The resulting report *replaces* the raw goal as the architect's input.

```python
VAGUE_PATTERNS = [
    "improve", "fix everything", "do your best", "make it better",
    "optimize", "clean up", "work on the codebase", "improve everything",
    "do something good", "surprise me", ""
]

def shouldRunFullDiscovery(goal_raw: str) -> bool:
    if not goal_raw or not goal_raw.strip():
        return True
    return any(p in goal_raw.lower() for p in VAGUE_PATTERNS)
```

---

## Architecture

```
[Trigger: vague/absent goal OR every run]
        │
        ▼
[Phase 0: Digest Compilation]          ~5-10s, no LLM, pure tool calls
  deterministic, fast, shared by all agents
        │
        ▼
[Phase 1: Parallel Lens Panel]         ~30-60s, 5 agents concurrent
  ┌─ Lens 1: Code Health
  ├─ Lens 2: Institutional Memory
  ├─ Lens 3: Architectural Reimagining     ← primary innovation lens
  ├─ Lens 4: Missing Capabilities          ← primary innovation lens
  └─ Lens 5: Adversarial Pair
  each → max 3 findings, structured JSON
        │
        ▼
[Phase 2: Synthesis]                   ~15s, 1 agent
  deduplicate → score → filter trivial → rank
  → discovery report (top 8-10 findings)
        │
        ▼
[Architect]  ← existing phase, unchanged interface
  receives discovery report instead of raw goal
  picks coherent theme → one architectural narrative
        │
        ▼
[Planner → Executor]  ← unchanged
```

---

## Phase 0: Digest Compilation

Pure tool calls — `git`, `gh`, `grep`, `python tools/size_audit.py`, `pytest --collect-only`. No LLM. Compiled once, shared by all lens agents. Target size: 8-15k tokens.

```json
{
  "repo_map": "<.repo-map.json>",
  "architecture": "<docs/ARCHITECTURE.md>",
  "module_signatures": "<exports + deps per module, not full source>",
  "dependency_graph": "<which modules import which — coupling map>",
  "dead_code_signals": "<exported symbols with zero internal callers>",

  "static_signals": {
    "size_violations": "<size_audit.py output>",
    "todos": "<TODO/FIXME/HACK/XXX/DEPRECATED — top 30 by file recency>",
    "docs_drift": "<stale AGENTS.md, missing @AI-MAP headers, PARKED plan docs>",
    "test_gaps": "<public functions with no test counterpart>",
    "test_isolation_violations": "<tests that import discord/ollama/requests without mock patches — grep for missing @pytest.mark.unit or direct client instantiation in test files>",
    "deep_nesting": "<functions with cyclomatic complexity > 10 (radon cc threshold)>",
    "long_functions": "<functions > 70 lines not flagged by size_audit>",
    "security_signals": "<hardcoded strings matching secret patterns, unsafe evals>"
  },

  "quality": {
    "coverage": "<pytest-cov report if available — uncovered lines by module>",
    "slow_tests": "<logs/slow-test-report.md if exists>",
    "workflow_registry": "<validate_workflows.py output>",
    "flaky_history": "<test names that failed > 1x in last 10 runs>"
  },

  "git_signals": {
    "churn": "<files changed most frequently in last 30 commits>",
    "bug_fix_hotspots": "<files most touched by fix commits>",
    "recent_touches": "<modules edited in last 3 runs>",
    "stale_branches": "<branches > 2 weeks old not merged>"
  },

  "github": {
    "open_issues": "<gh issue list — title + label + age>",
    "stale_prs": "<open PRs > 1 week>",
    "ci_failure_patterns": "<which check names fail most across recent commits>",
    "recent_pr_review_comments": "<actionable reviewer feedback>"
  },

  "institutional_memory": {
    "recent_lessons": "<SIE ledger: last 15 trusted reflections>",
    "recent_failures": "<adversary rejections + CI failures last 5 runs>",
    "open_postmortems": "<unresolved postmortem guidance>",
    "policy_hints": "<learning/policy.py hints for common subtask types>",
    "knowledge_graph": "<knowledge_graph.context_for top concepts>",
    "discord_feedback": "<user feedback captured via Nightclaw>"
  },

  "innovation_seeds": {
    "vision_vs_reality": "<ARCHITECTURE.md goals vs current module exports — what was planned but not built>",
    "rejected_ideas": "<PR descriptions + issue comments where things were proposed but not merged>",
    "parked_plans": "<docs/plans/ files with PARKED status>",
    "underutilized_capabilities": "<skills/hooks/MCP tools installed but rarely invoked>",
    "prompt_quality_signals": "<Ollama prompt templates — naive? verbose? missing context?>"
  },

  "leverage_signals": {
    "slowest_phases": "<which run phases take longest from run logs>",
    "highest_token_cost": "<which executor steps burn most tokens>",
    "most_retried": "<which subtask types fail and retry most often>",
    "abstraction_gaps": "<low-level code patterns that repeat 3+ times>"
  },

  "skills_hooks": "<installed skills + hooks — any broken or outdated>",
  "config_signals": "<undocumented config keys, suspicious values>"
}
```

---

## Phase 1: Parallel Lens Panel

All 5 agents run concurrently on the shared digest. Each returns at most 3 findings in this structure:

```json
{
  "title": "short imperative title",
  "type": "new_capability | reimagining | health | memory | ux",
  "impact": 1-5,
  "specificity": 1-5,
  "innovation": 1-5,
  "rationale": "why this matters, not just what it is",
  "affected_files": ["..."],
  "source_lens": "lens_N"
}
```

---

### Lens 1 — Code Health
**Focus:** What is measurably broken, decaying, or dangerously untested?
**Reads:** static_signals, quality, security_signals, flaky_history
**Constraint:** Must name specific files. No "add more tests generally."

---

### Lens 2 — Institutional Memory
**Focus:** What does the system already know it should fix, but hasn't acted on?
**Reads:** recent_lessons, open_postmortems, failed subtasks, rejected PRs, parked_plans
**Constraint:** Every finding must reference a specific past event or lesson. No generic observations.

---

### Lens 3 — Architectural Reimagining ⚡ INNOVATION LENS
**Focus:** What should work *completely differently*? What assumptions are wrong?
**Reads:** dependency_graph, abstraction_gaps, slowest_phases, highest_token_cost, vision_vs_reality, module_signatures
**Mandatory provocative seeds injected into prompt:**
- *"What would you rewrite from scratch if you had a week?"*
- *"What assumption does this system make that might be fundamentally wrong?"*
- *"Where is complexity hiding that users never asked for?"*
- *"What would this look like if it were 10x simpler?"*
- *"What is the most expensive mistake baked into the current architecture?"*

**Constraint:** Must explain WHY current approach is wrong, not just that it could be different. Surface patches do not qualify — must propose structural change.

---

### Lens 4 — Missing Capabilities ⚡ INNOVATION LENS
**Focus:** What should this system obviously be able to do, but can't?
**Reads:** vision_vs_reality, underutilized_capabilities, discord_feedback, open_issues, rejected_ideas
**Mandatory provocative seeds injected into prompt:**
- *"What feature would make a new user immediately say 'this is serious software'?"*
- *"What would 10x the system's capability look like?"*
- *"What does every comparable system have that this one is missing?"*
- *"What would the user wish for if they could have anything?"*
- *"What workflow is impossible today but would be trivial if one abstraction existed?"*

**Constraint:** Must be specific enough that an engineer could start building tomorrow. "Better observability" is rejected; "a live run dashboard that edits a single Discord message" is accepted.

---

### Lens 5 — Adversarial Pair
Two sub-prompts, one agent each, both read the full digest:

**Confused Newcomer:** *"You just read this codebase for the first time. You are intelligent but have no prior context. What is confusing, inconsistent, or embarrassing? What made you lose confidence in the system? What looks like it was bolted on?"*
Mandatory seed: *"What is the most embarrassing thing about this codebase right now?"*

**Blocked Power User:** *"You have used this system every day for 3 months. You hit the same walls repeatedly. What can you not do that you desperately need? What forces you to do things manually that should be automatic? What makes you distrust the output?"*
Mandatory seed: *"What does this system assume about you that is wrong?"*

---

## Phase 2: Synthesis

One agent reads all findings (~15 total) and produces the final discovery report.

**Scoring:**
- **Impact (1-5):** How much does this change capability or quality?
- **Specificity (1-5):** Can an engineer start tomorrow without further research?
- **Innovation (1-5):** Transformative restructuring (5) vs incremental cleanup (1)

**Filter rules (strict):**
1. Drop specificity < 2 — too vague to act on
2. Drop pure cosmetic changes
3. Deduplicate near-identical findings across lenses
4. **Innovation floor:** At least 40% of surviving findings must score ≥ 3 on innovation. If the report would fail this, re-rank to elevate innovative findings. The discovery engine must not degrade into a glorified TODO scanner.
5. Prefer findings that **compose** — items that could be part of one coherent PR score a bonus

**Output:**
```json
{
  "theme_suggestion": "one coherent narrative the architect could adopt",
  "innovation_ratio": 0.0-1.0,
  "findings": [
    {
      "rank": 1,
      "title": "...",
      "type": "new_capability | reimagining | health | memory | ux",
      "impact": 5,
      "specificity": 4,
      "innovation": 5,
      "rationale": "...",
      "affected_files": ["..."],
      "source_lens": "lens_4",
      "composes_with": [3, 5]
    }
  ]
}
```

Top 8-10 findings passed to architect.

---

## Architect Handoff

When discovery ran, the architect prompt is augmented:

```
DISCOVERY REPORT (auto-generated, {N} findings, innovation ratio: {X}%):
{ranked findings JSON}

Suggested theme: "{theme_suggestion}"

You may adopt this theme or choose a different one. Your job:
1. Select a coherent set of the highest-impact findings
2. Synthesize them into ONE architectural narrative — a single story this PR will tell
3. Prioritize transformative findings over incremental ones
4. The resulting work should feel like something an ambitious engineer chose to do,
   not a list of chores

Avoid picking unrelated items. A PR that does one bold thing well is better than
five safe things loosely grouped.
```

When discovery did not run (specific goal), the digest is still injected as background context only — architect uses it to make better-informed decisions but is not driven by it.

---

## New Module: `agents/discovery/`

```
agents/discovery/
  __init__.py          — public facade: run_discovery(work_dir, goal_raw) -> DiscoveryReport
  digest.py            — Phase 0: compile_digest(work_dir) -> dict
  lenses.py            — Phase 1: run_lens_panel(digest) -> list[Finding]
  synthesis.py         — Phase 2: synthesize(findings) -> DiscoveryReport
  models.py            — Finding, DiscoveryReport dataclasses
```

All files must stay within size thresholds (≤300 lines ideal).

---

## Changes to Existing Files

| File | Change |
|---|---|
| `agents/elaborator.py` | Call `run_discovery()` before `elaborate()`; pass digest into elaboration context |
| `agents/architect.py` | Accept optional `discovery_report` param; inject into architect prompt when present |
| `platform_core/orchestration/run_phase_mixin.py` | Add Phase 0 (discovery) before `_freshRunPhase()`; store report in `state.meta["discovery_report"]` |
| `state/task_schema.py` | Add `discovery_report` field to TaskState meta |

---

## Token Budget

| Phase | Agents | Input | Output | Total |
|---|---|---|---|---|
| Digest compilation | 0 (tool calls) | — | — | ~0 |
| Lens panel (×5 parallel) | 5 | ~10k each | ~500 each | ~52.5k |
| Synthesis | 1 | ~5k | ~2k | ~7k |
| **Total per discovery run** | | | | **~60k** |

Acceptable for runs where goal is vague. For specific-goal runs, only digest is compiled (~0 LLM tokens).

---

## Success Criteria

- Running `--goal "improve everything"` produces a PR with a coherent narrative theme, not a list of unrelated fixes
- At least one finding per discovery run scores ≥ 4 on innovation — the system always proposes something non-obvious
- Digest compilation completes in < 15 seconds
- Full discovery (lens panel + synthesis) completes in < 90 seconds
- The architect's chosen theme is traceable to a specific lens finding
- A human reading the final PR description should feel "I wouldn't have thought to do that" at least once
