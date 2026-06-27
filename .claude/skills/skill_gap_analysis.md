---
name: skill-gap-analysis
description: >
  Systematically identify gaps between current agent/LLM capabilities and task requirements.
  Produces a prioritized list of missing skills, knowledge areas, or workflow patterns,
  with actionable recommendations for skill development. Use when onboarding to a new
  codebase, before a complex task, or when repeated failures hint at a missing capability.
---

## Purpose

Surface what you don't know before starting a hard task. Prevents confident-but-wrong execution.

A 2-minute gap analysis before coding beats a 2-hour debugging session after an overconfident
wrong implementation.

## When to invoke

- Starting a multi-file feature in an unfamiliar codebase
- After two consecutive wrong attempts at the same problem
- When the task spec mentions libraries, tools, or patterns not used recently
- Explicitly invoked: `/skill-gap-analysis`, "analyze my skill gaps", "what do I need to know"
- Onboarding to a new repo or technology stack
- After receiving a code review that exposed knowledge gaps

## Protocol

### Phase 1 — Scope the task (read, don't act)

1. Read the full task description without skipping.
2. List every **domain** the task touches: language features, frameworks, APIs, infrastructure,
   protocols, data formats, security models.
3. Note any domain where your knowledge cutoff or training coverage is uncertain.
4. Identify the blast-radius of each domain: foundational plumbing (auth, DB schema, state
   machine) has higher blast radius than peripheral tooling (CLI flags, log formatting).

### Phase 2 — Inventory current capability

For each domain, assign a rating:

| Rating | Meaning                                                             |
|--------|---------------------------------------------------------------------|
| SOLID  | Used confidently in prior steps this session; syntax/API verified  |
| FUZZY  | Know the concept but may misremember exact syntax or API contract  |
| BLANK  | Haven't used this recently enough to trust — must verify first     |

**Key rule:** FUZZY + high blast radius → treat as BLANK and remediate before coding.

### Phase 3 — Prioritize gaps

Rank open gaps by: `blast_radius × task_dependency_weight`

- Foundational plumbing first (auth, state transitions, DB schema, IPC contracts)
- Transitive dependencies second (libraries whose API you must call correctly for the plumbing to work)
- Peripheral tooling last (CLI flags, output formatting, optional config)

### Phase 4 — Remediate before coding

For each BLANK or high-risk FUZZY, remediate in this order:

1. **Grep the codebase first** — find existing usage patterns; don't reinvent what's already there.
2. **Check version-pinned docs** — read `requirements.txt` / `package.json` / `pyproject.toml`
   to confirm the exact library version, then fetch docs for that version via context7 or web search.
3. **Read authoritative source** — official docs, RFC, or type stubs — not a blog post.
4. **Ask** — if docs are ambiguous and the blast radius is high, surface the uncertainty rather
   than guessing.

Do not start coding until every BLANK and high-blast-radius FUZZY has been resolved.

**Best practices for remediation:**
- Time-box each remediation: 2 min for LOW, 5 min for MED, 10 min for HIGH.
- If the authoritative source is unclear after 10 min, escalate rather than guess.
- Write a one-line note of what you learned: "DRF CursorPagination requires explicit `ordering` field."
- After remediation, immediately apply the verified API in a scratch test before the real code.

### Phase 5 — Coverage analysis

Before finalizing the gap report, check domain coverage breadth:

1. **Horizontal coverage** — does this task touch multiple domains simultaneously?
   If so, are the gaps in different domains independent or do they compound (one gap blocks another)?
2. **Coverage depth** — for domains rated FUZZY, how stale is the knowledge?
   >3 months: re-verify. >12 months: treat as BLANK.
3. **Coverage conflicts** — do two domains use tools with conflicting conventions?
   (e.g., Django ORM patterns vs. raw SQL; synchronous vs. async patterns.)
   Flag conflicts explicitly; don't silently resolve them.

Coverage percentage formula (for automated scoring):
```
coverage% = max(0, 100 × (1 − gap_score / demand))
```
- 0% = no coverage, full gap
- 50% = one skill covers it (partial)
- 100% = two or more skills saturate coverage

### Phase 6 — Output gap report with recommendations

```
SKILL GAP REPORT
================
Task: <one-line task description>

SOLID:  <comma-separated list>
FUZZY:  <list with specific uncertainty noted per item>
BLANK:  <list>

Priority gaps (fix before coding):
1. <gap> — blast_radius: <HIGH|MED|LOW> — coverage: <pct>% — remediation: <read X / grep for Y / ask>
2. ...

Actionable recommendations:
1. <domain>: create/strengthen skill — suggested resource: <URL or file>
2. ...

Estimated knowledge-fetch time: <N min>
Proceed: YES / NO (blocked on gap #N)
```

If `Proceed: NO`, do not write any code until the blocking gap is resolved. Update the report
after each remediation and re-check the proceed decision.

## Rating guide

Use this quick heuristic to calibrate ratings consistently:

| Situation                                                          | Rating |
|--------------------------------------------------------------------|--------|
| You already called this API or ran this command earlier this session | SOLID  |
| You used this library 6+ months ago and haven't checked since       | FUZZY  |
| You've heard of the library but never used it                       | BLANK  |
| You're unsure which version is installed                            | FUZZY  |
| The task mentions a protocol/standard you haven't implemented       | BLANK  |
| You wrote tests for this behavior earlier in the same session       | SOLID  |
| Docs were fetched and verified earlier in this session              | SOLID  |

## Blast radius guide

| Domain category                         | Typical blast radius |
|-----------------------------------------|----------------------|
| Auth / session management               | HIGH                 |
| Database schema / migrations            | HIGH                 |
| State machine transitions               | HIGH                 |
| IPC / protocol contracts                | HIGH                 |
| Core library API (serializer, ORM)      | MED–HIGH             |
| HTTP routing / middleware               | MED                  |
| CLI flag parsing                        | LOW                  |
| Logging / output formatting             | LOW                  |
| Test helper utilities                   | LOW                  |

## Examples

### Example A — Django REST API endpoint, uncertain pagination

```
SKILL GAP REPORT
================
Task: add paginated endpoint to Django REST Framework API

SOLID:  Python, HTTP status codes, JSON, Django ORM, pytest
FUZZY:  DRF serializer many=True with custom fields (used 8 months ago)
BLANK:  DRF CursorPagination — never used, don't know default ordering behavior

Priority gaps (fix before coding):
1. CursorPagination — blast_radius: HIGH — coverage: 0% — remediation: fetch context7 docs for djangorestframework
2. Serializer many=True with custom field — blast_radius: MED — coverage: 0% — remediation: grep codebase for existing serializers

Actionable recommendations:
1. testing: existing pytest skill covers this (coverage: 100%) — no action needed
2. documentation: no skill exists — consider adding a docstring-standards skill

Estimated knowledge-fetch time: 5 min
Proceed: NO (fetch docs for gap #1 first)
```

### Example B — Shell scripting, all domains familiar

```
SKILL GAP REPORT
================
Task: add retry logic to bash deploy script

SOLID:  bash, exit codes, loops, sleep, curl, trap
FUZZY:  none
BLANK:  none

Coverage analysis: all domains 100% covered for this task scope.

Proceed: YES
```

### Example C — Unfamiliar internal module with unknown state schema

```
SKILL GAP REPORT
================
Task: add a new lifecycle state to the task state machine in state/task.py

SOLID:  Python dataclasses, JSON serialization, pathlib
FUZZY:  task lifecycle transitions (read the file 2 sessions ago, may be stale)
BLANK:  ControlBus signal contract for state changes — never touched this subsystem

Priority gaps (fix before coding):
1. ControlBus signal contract — blast_radius: HIGH — coverage: 0% — remediation: read docs/STATE.md + grep ControlBus
2. Task lifecycle transitions — blast_radius: HIGH — coverage: 30% — remediation: re-read state/task.py + docs/STATE.md

Coverage analysis:
  - Gap #1 blocks #2: understanding ControlBus is prerequisite for safe state transitions
  - Compounding risk: wrong state name cascades to dashboard, notifier, replanner

Actionable recommendations:
1. state: no skill file exists — after this task, write a state-machine-patterns skill
2. contracts: no skill file exists — ControlBus contract reading is reusable; document it

Estimated knowledge-fetch time: 8 min
Proceed: NO (blocked on gap #1 and #2)
```

### Example D — Multi-domain task with coverage conflicts

```
SKILL GAP REPORT
================
Task: migrate synchronous database calls to async in FastAPI handler

SOLID:  FastAPI basics, SQLAlchemy ORM (sync)
FUZZY:  SQLAlchemy async session management (read docs 4 months ago)
BLANK:  asyncio event loop interaction with pytest-asyncio fixtures

Priority gaps (fix before coding):
1. SQLAlchemy async sessions — blast_radius: HIGH — coverage: 0% — remediation: fetch context7 docs for sqlalchemy[asyncio]
2. pytest-asyncio fixtures — blast_radius: MED — coverage: 0% — remediation: grep existing async test files

Coverage conflicts detected:
  - Sync SQLAlchemy patterns (SOLID) conflict with async patterns (BLANK) — do NOT mix
  - FastAPI sync route → async route migration changes the WSGI/ASGI boundary

Actionable recommendations:
1. Create skill: 'sqlalchemy-async' documenting session factory, scoped_session patterns
2. Strengthen 'testing' skill: add async fixture examples using pytest-asyncio

Estimated knowledge-fetch time: 12 min
Proceed: NO (coverage conflicts must be resolved before mixing sync/async)
```

## Practical exercises

These exercises build the gap-analysis habit. Run one before every non-trivial task.

### Exercise 1 — Cold-start rating
Pick a library you haven't used in >6 months. Without looking it up:
1. List 3 things you're SOLID on.
2. List 2 things you're FUZZY on (specific uncertainty).
3. List 1 thing you're BLANK on.
Then fetch docs and check your accuracy. Calibrate your FUZZY/BLANK threshold.

### Exercise 2 — Blast radius mapping
For the current 9to5 codebase, map 5 files to blast-radius levels.
Which file, if broken, causes the most cascading failures? (Hint: orchestrator.py, state/task.py)

### Exercise 3 — Coverage conflict detection
Find two domains in the current task that use patterns with conflicting conventions
(e.g., sync vs async, REST vs gRPC, ORM vs raw SQL). Write a one-line conflict note.

### Exercise 4 — Remediation speed drill
Take a BLANK gap. Time yourself: how long does it take to reach SOLID?
If >10 min: the gap is HIGH complexity — escalate or simplify the task scope.

### Exercise 5 — Retrospective rating
After completing a task, revisit your pre-task gap report:
1. Which FUZZY items actually caused bugs?
2. Which BLANK items were harder than expected?
3. Adjust your FUZZY/BLANK calibration accordingly.

## Rules

- **Never skip Phase 1–2 because "the task looks simple."** Simple-looking tasks regularly touch
  BLANK domains that invalidate the implementation.
- **FUZZY + high blast radius = treat as BLANK.** Verify before using; the cost is minutes,
  the cost of getting it wrong is hours.
- **Report honestly.** Overconfidence wastes more time than a 2-minute doc check.
- **After each remediation, re-rate the gap and update Proceed.** Don't carry stale ratings
  through multiple coding steps.
- **Grep codebase before fetching docs.** Existing usage patterns are the most reliable guide
  to how the library is actually used in this project.
- **Flag coverage conflicts explicitly.** Don't silently resolve domain convention mismatches.
- **Time-box remediations.** If a gap isn't resolved in the allotted time, escalate.

## Integration with other skills

- Run **skill-gap-analysis** before starting any multi-file feature.
- If a bug survives one fix attempt after gap analysis, switch to **systematic-debugging**.
- Use **dependency-audit** when BLANK gaps involve version uncertainty across multiple packages.
- Use **test-coverage-triage** after implementation to catch gaps in test coverage introduced
  by new code in domains that were BLANK during analysis.
- Use **architect-review** when coverage conflicts affect system-level design decisions.

## Automated gap scoring

The companion script `C:\9to5\.claude\skills\skill-gap-analysis.py` scores domain coverage
across the full skill inventory against historical task demand. Run it to get an objective
inventory-vs-demand report:

```sh
python C:\9to5\.claude\skills\skill-gap-analysis.py
```

Output columns: # | Domain | Demand | Cov% | Covered By | Gap Score

- **Demand**: total token frequency in task history for this domain's keywords
- **Cov%**: percentage of demand covered by existing skills (0% = no coverage)
- **Covered By**: skill names that match this domain (by name and content tokens)
- **Gap Score**: `demand × (1 − coverage_fraction)`; 0.0 = fully covered

**Priority Actions section** lists the top-5 highest-gap domains with specific recommendations:
- "Create new skill for 'X'" — no existing skill covers this domain
- "Strengthen 'X' coverage (existing: Y)" — partial coverage exists; improve it

Domains with `NONE` coverage and nonzero demand are critical gaps worth adding new skills for.
