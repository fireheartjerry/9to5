# References Harvest — Design Spec

**Date:** 2026-06-30
**Status:** Approved (brainstorming), pending spec review
**Owner:** Terminal A
**Type:** Research / knowledge-harvest (NO 9to5 source code changes)

## Goal

`./references/` holds 23 cloned open-source repos about multi-agent and
long-horizon AI (~350k files, ~21k Python, ~50k+ TS). Mine them for technology
worth leveraging in 9TO5. Deliverable is a **catalog only** — no integration
specs, no 9to5 code edits this phase. The user decides integrations afterward.

**Two lenses, equal weight and equal thoroughness ("100-100"):**
1. **9to5-fit** — techniques that fill a known 9to5 gap or beat what 9to5 does today.
2. **Standout-tech** — notable multi-agent / long-horizon techniques regardless of
   current fit (inspiration / future).

Every repo is mined for both. Neither lens is a lesser tier.

## Non-Goals

- No editing of 9to5 source, config, or behavior.
- No copying code from references into 9to5 (cataloging ideas only; licenses
  recorded for later).
- No committing `./references/` itself to git (see Git Hygiene).
- No integration specs or implementation plans for the harvested techniques
  (that is a future, separate phase).

## Repos in scope (23)

`agentscope, agx, autogen, bernstein, claude-code, crewai, dify, eliza,
generative-agents, gnap, guild, hermes, langgraph, loki-mode, loom, metagpt,
ms-agent-framework, openclaw, openhands, owl, pydantic-ai, swarmclaw, warp`

Famous frameworks (autogen, crewai, langgraph, metagpt, dify, pydantic-ai,
eliza, openhands, agentscope, ms-agent-framework, generative-agents) and
unusual / unknown ones (bernstein, hermes, loom, agx, warp, guild, owl, gnap,
loki-mode, openclaw, swarmclaw, claude-code). Agents must identify what the
unknown ones actually are; "low value / not relevant" is a valid finding.

## Architecture (4 phases)

### P0 — Ground truth (1 agent)
Read 9to5's own architecture: `docs/ARCHITECTURE.md`, `LLM_MAP.md`, `AGENTS.md`,
`CLAUDE.md`, and core domains (`orchestrator.py` + `platform_core/orchestration`,
`agents/executor.py`, `memory/`, `learning/`, `workflows/`, `state/`,
verification path, `notifications/`). Output a compact **9to5 Capability Map +
Known Gaps brief** (`docs/references-harvest/_9to5-brief.md`): for each domain,
what 9to5 does today and where it is thin. This brief is injected into every P1
and P2 agent so "fit" is grounded, not guessed.

### P1 — Per-repo harvest (23 parallel agents, 1 per repo)
Each agent receives the P0 brief + the fixed Digest Schema below. It explores its
assigned repo only (READMEs, architecture docs, core modules), skipping
`node_modules/`, `.git/`, virtualenvs, build output, and bulk test fixtures.
Writes `docs/references-harvest/<repo>.md`.

**Digest Schema (every per-repo digest):**
- **Repo:** name, one-line what-it-is, maturity, primary language, **license**.
- **Architecture sketch:** 3–8 bullets on how it is built.
- **Techniques table** — one row per notable technique:
  - `name` — short label
  - `what` — what it does
  - `where` — path(s) in the repo
  - `lens` — `9to5-fit` | `standout` | `both`
  - `maps-to-9to5` — which 9to5 domain it touches and how (fill a gap / beat current / future idea)
  - `steal-effort` — `idea-only` | `port-code` | `heavy`
  - `rank` — 1 (skip) … 5 (high priority)
- **Top 3 takeaways** for this repo.

### P2 — Theme cross-cuts (9 parallel agents, 1 per theme)
Run after P1 digests exist. Each agent owns one theme, reads all 23 digests
(+ dives into repos where needed), and writes
`docs/references-harvest/themes/<theme>.md` = the best techniques for that theme
across all repos, ranked, with 9to5 fit and a recommended "if we adopt one thing"
pick.

**Themes (9):**
1. `orchestration-planning` — planning, replanning, task decomposition
2. `long-horizon-durability` — checkpoint/resume, step state, crash-safety
3. `memory-knowledge` — memory schemes, retrieval, knowledge bases
4. `agent-comms-topology` — multi-agent communication, roles, topologies
5. `verification-self-correction` — verify, critique, self-repair loops
6. `tool-use-env` — tool calling, environment/computer interaction, sandboxing
7. `observability` — telemetry, tracing, cost/latency, dashboards
8. `human-loop-control-safety` — human-in-loop, control bus, guardrails
9. `prompt-context-engineering` — prompt/context construction, compression

### P3 — Master index (Terminal A synthesis)
`docs/references-harvest/MASTER.md` = ranked table of all techniques across repos
and themes, the top-N picks for 9to5 (with pointers), and links to every digest
and theme doc.

## On-disk layout

```
docs/references-harvest/
  _9to5-brief.md          # P0
  MASTER.md               # P3
  <repo>.md               # P1  x23
  themes/<theme>.md       # P2  x9
```

## Concurrency & cost

~33 agents total (1 + 23 + 9). Runtime runs up to 16 concurrent, queues the rest;
all complete. Agents are read-only on `references/` and write distinct filenames,
so no file conflicts and no git-worktree isolation needed. Token spend is large
and expected; user has opted into dispatch-freely.

## Git hygiene

- `./references/` must NOT be committed (it is huge external code). Verify it is
  gitignored; add an ignore entry if missing. The existing dirty `.gitignore`
  change must be preserved.
- Only `docs/references-harvest/**` is the keepable, committable artifact.
- Preserve all pre-existing dirty files (control_mixin.py, notifications/jerry_client.py,
  wef_* scratch files, etc.) — do not touch them.

## Success criteria

- 23 per-repo digests, 9 theme cross-cuts, 1 master index, 1 9to5 brief — all
  present and following the schema.
- Every digest records a license and at least the top techniques with the full
  schema fields.
- MASTER.md gives a clear ranked shortlist of what is worth integrating into 9to5,
  separable into "fits now" vs "standout / future."
- Unknown repos are positively identified (or explicitly marked low-value).

## Risks / open issues

- Unknown repos may be junk or unrelated → acceptable; record the finding.
- License variety → record per repo; copying code is out of scope this phase.
- Quality variance across 23 agents → mitigated by fixed schema + P0 brief + P3
  synthesis pass that can flag thin digests for a re-run.
