# References Harvest — Implementation Plan

> **For agentic workers:** This plan is executed by dispatching read-only research
> subagents (Agent tool) from Terminal A. There is NO 9to5 source code change, so
> no TDD steps. Each phase gates the next. Steps use checkbox (`- [ ]`) tracking.

**Goal:** Mine 23 cloned repos in `./references/` for stealable multi-agent /
long-horizon AI technology and produce a catalog (per-repo digests + theme
cross-cuts + master index) under `docs/references-harvest/`.

**Architecture:** 4 phases — P0 ground-truth brief (1 agent) → P1 per-repo
digests (23 parallel agents) → P2 theme cross-cuts (9 parallel agents) → P3
master synthesis (Terminal A). All agents read-only on `references/`; each writes
a distinct output file so there are no conflicts.

**Spec:** `docs/superpowers/specs/2026-06-30-references-harvest-design.md`

---

## File structure (outputs)

```
docs/references-harvest/
  _9to5-brief.md          # P0  (ground truth)
  <repo>.md               # P1  x23 per-repo digests
  themes/<theme>.md       # P2  x9 cross-cuts
  MASTER.md               # P3  ranked index
```

Repos (23): `agentscope, agx, autogen, bernstein, claude-code, crewai, dify,
eliza, generative-agents, gnap, guild, hermes, langgraph, loki-mode, loom,
metagpt, ms-agent-framework, openclaw, openhands, owl, pydantic-ai, swarmclaw,
warp`.

Themes (9): `orchestration-planning, long-horizon-durability, memory-knowledge,
agent-comms-topology, verification-self-correction, tool-use-env, observability,
human-loop-control-safety, prompt-context-engineering`.

---

## Task P0: Ground-truth brief (1 agent, general-purpose)

**Files:** Create `docs/references-harvest/_9to5-brief.md`

- [ ] **Step 1: Dispatch ground-truth agent** with this prompt:

```
You are mapping the 9TO5 codebase so other agents can judge whether external
techniques fill a real gap. Repo root: C:\9to5. READ-ONLY — do not edit code.

Read: CLAUDE.md, docs/ARCHITECTURE.md, LLM_MAP.md, AGENTS.md, then skim the core
domains: orchestrator.py + platform_core/orchestration/, agents/executor.py +
agents/hooks.py, memory/, learning/, workflows/, state/, knowledge.py, the
verification path, and notifications/. Use Glob/Grep/Read; do not read tests in bulk.

Write docs/references-harvest/_9to5-brief.md with these sections:
1. One-paragraph system overview (orchestrator = local Ollama brain; executor =
   Claude Code; Nightclaw = Discord surface).
2. Per-domain capability map. For EACH of these domains give: "Today" (what 9to5
   does) and "Thin/Gap" (where it is weak or missing):
   orchestration/planning, long-horizon durability (checkpoint/resume/step-state),
   memory/knowledge, agent-comms/topology, verification/self-correction,
   tool-use/env, observability, human-loop/control-safety, prompt/context-engineering.
3. "What would most help 9to5" — your top 8 capability gaps, ranked.

Keep it dense and concrete (cite file paths). Target 400-700 lines max. Your final
message = confirmation + the 8 ranked gaps (these get reused).
```

- [ ] **Step 2:** Confirm `_9to5-brief.md` exists and capture the 8 ranked gaps for reuse in P1/P2 prompts.

---

## Task P1: Per-repo digests (23 parallel agents, general-purpose)

Dispatch all 23 at once (runtime runs 16, queues 7). Each agent gets the SAME
template with `<REPO>` substituted and the P0 brief contents pasted in.

- [ ] **Step 1: Dispatch one agent per repo** with this template:

```
You are harvesting ONE repo for techniques worth stealing into 9TO5. READ-ONLY.

Target repo: C:\9to5\references\<REPO>   (stay inside this dir only)
9to5 context brief (use this to judge "fit"):
<<PASTE _9to5-brief.md CONTENTS>>

Explore the repo: read its README/docs, identify what it is and its architecture,
then read the CORE modules. SKIP node_modules/, .git/, virtualenvs, build output,
and bulk test fixtures. You will not read every file — be strategic: find the
ideas, not full coverage.

Apply TWO lenses with EQUAL weight and thoroughness:
  - 9to5-fit: techniques that fill a 9to5 gap or beat what 9to5 does today.
  - standout: notable multi-agent / long-horizon techniques regardless of fit.

Write docs/references-harvest/<REPO>.md with EXACTLY these sections:
1. Repo: name, one-line what-it-is, maturity, primary language, LICENSE (find it).
2. Architecture sketch: 3-8 bullets.
3. Techniques table (markdown). Columns:
   name | what | where (repo path) | lens (9to5-fit/standout/both) |
   maps-to-9to5 (which domain + how) | steal-effort (idea-only/port-code/heavy) |
   rank (1 skip .. 5 high)
   Include EVERY notable technique under both lenses; do not stop at the first few.
4. Top 3 takeaways.

If the repo turns out low-value or unrelated, say so explicitly and keep it short.
Your final message = one-line summary + your highest-ranked technique.
```

- [ ] **Step 2:** Verify 23 files exist in `docs/references-harvest/`. Re-dispatch any agent whose digest is missing or obviously thin.

---

## Task P2: Theme cross-cuts (9 parallel agents, general-purpose)

Run only after P1 digests exist. Dispatch all 9 at once.

- [ ] **Step 1: Dispatch one agent per theme** with this template:

```
You are writing a cross-repo synthesis for ONE theme of an agent-tech harvest.
READ-ONLY.

Theme: <THEME>  (one of: orchestration-planning, long-horizon-durability,
memory-knowledge, agent-comms-topology, verification-self-correction,
tool-use-env, observability, human-loop-control-safety, prompt-context-engineering)

9to5 brief: read docs/references-harvest/_9to5-brief.md
Per-repo digests: read ALL of docs/references-harvest/*.md (the 23 digests).

For your theme, gather the best techniques across ALL repos. Where a digest is
thin on your theme but the repo clearly has relevant code, dive into that repo
(C:\9to5\references\<repo>) to confirm. READ-ONLY.

Write docs/references-harvest/themes/<THEME>.md:
1. One-paragraph theme intro + how 9to5 handles this today (from the brief).
2. Ranked technique table across repos: technique | source repo | what |
   9to5-fit (fills gap / beats current / future) | steal-effort | rank.
3. "If 9to5 adopts ONE thing for this theme" — your single top recommendation
   with a 3-5 sentence justification.

Your final message = your single top recommendation for this theme.
```

- [ ] **Step 2:** Verify 9 files in `docs/references-harvest/themes/`.

---

## Task P3: Master index (Terminal A synthesis, no subagent)

- [ ] **Step 1:** Read all 23 digests + 9 theme docs + the brief.
- [ ] **Step 2:** Write `docs/references-harvest/MASTER.md`:
  - Ranked master table of all techniques (technique | repo | theme | lens |
    9to5-fit | steal-effort | rank), sorted by rank.
  - "Top picks for 9to5 — fits now" shortlist (with links to digest + theme).
  - "Standout / future" shortlist.
  - Links to every digest and theme doc.
- [ ] **Step 3:** Report summary to user. (Commit only if user asks.)

---

## Self-review (against spec)

- Spec coverage: P0 brief ✓, 23 digests ✓ (P1), 9 themes ✓ (P2), MASTER ✓ (P3),
  dual-lens equal weight ✓ (in P1+P2 templates), license capture ✓ (P1 schema),
  git hygiene — references/ already gitignored+untracked, nothing to do.
- Placeholders: none — every agent prompt is complete and copy-pasteable.
- Consistency: repo list (23) and theme list (9) identical across spec and plan;
  output paths identical to spec layout.

## Execution note

Executed inline from Terminal A by dispatching the agents above (the harvest is
inherently subagent-driven). Phases gate sequentially; agents within a phase run
in parallel.
