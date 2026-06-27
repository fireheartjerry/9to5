# Skill Gap Analysis

**Location:** `.claude/skills/skill_gap_analysis.md`  
**Companion README:** `.claude/skills/skill_gap_analysis/README.md`  
**Automated scorer:** `.claude/skills/skill-gap-analysis.py`

---

## What it does

The `skill-gap-analysis` skill forces a structured inventory of current knowledge against task
requirements before writing a single line of code. It classifies each domain as
**SOLID / FUZZY / BLANK**, ranks gaps by blast radius × dependency weight, and emits a
go/no-go decision (`Proceed: YES / NO`) with specific remediation steps.

**Core insight:** a 2-minute gap analysis before coding beats a 2-hour debugging session after
an overconfident wrong implementation.

---

## When to invoke

| Trigger | Example |
|---------|---------|
| Starting a multi-file feature in an unfamiliar codebase | "add a new Discord cog that queries the state machine" |
| Two consecutive wrong attempts at the same problem | keep hitting the same failure after two fixes |
| Task spec mentions libraries or protocols not used recently | task uses `sqlalchemy[asyncio]`, last used 8+ months ago |
| Explicit invocation | `/skill-gap-analysis`, "analyze my skill gaps", "what do I need to know" |
| Onboarding to a new repo or technology stack | first session in a new project |
| After a code review that exposed knowledge gaps | reviewer catches a wrong API assumption |

---

## Protocol overview (6 phases)

### Phase 1 — Scope the task

Read the full task description. List every **domain** it touches: language features, frameworks,
APIs, infrastructure, protocols, data formats, security models. Note where your knowledge
cutoff or training coverage is uncertain. Identify the blast-radius of each domain.

### Phase 2 — Inventory current capability

Rate each domain:

| Rating | Meaning |
|--------|---------|
| **SOLID** | Used confidently this session; syntax/API already verified |
| **FUZZY** | Know the concept but may misremember exact syntax or API contract |
| **BLANK** | Not used recently enough to trust — must verify before coding |

**Key rule:** FUZZY + high blast radius → treat as BLANK.

### Phase 3 — Prioritize gaps

Rank open gaps by: `blast_radius × task_dependency_weight`

1. Foundational plumbing first (auth, state transitions, DB schema, IPC contracts)
2. Transitive dependencies second (libraries whose API the plumbing calls)
3. Peripheral tooling last (CLI flags, output formatting, optional config)

### Phase 4 — Remediate before coding

For each BLANK or high-risk FUZZY, in this order:

1. **Grep the codebase first** — find existing usage patterns
2. **Check version-pinned docs** — read `requirements.txt` / `pyproject.toml` to confirm exact version, then fetch docs
3. **Read authoritative source** — official docs, RFC, or type stubs (not a blog post)
4. **Ask** — if docs are ambiguous and blast radius is HIGH, surface the uncertainty

**Time-box:** 2 min (LOW) · 5 min (MED) · 10 min (HIGH). Escalate if exceeded.

Do not start coding until every BLANK and high-blast-radius FUZZY is resolved.

### Phase 5 — Coverage analysis

| Check | What to look for |
|-------|-----------------|
| Horizontal coverage | Multiple BLANK domains that compound (one gap blocks another) |
| Coverage depth | Knowledge age > 3 months → re-verify; > 12 months → treat as BLANK |
| Coverage conflicts | Two domains with conflicting conventions (sync vs async, ORM vs raw SQL) |

Coverage formula: `coverage% = max(0, 100 × (1 − gap_score / demand))`

- 0% = no coverage, full gap
- 50% = one skill partially covers it
- 100% = two or more skills saturate coverage

### Phase 6 — Output gap report

```
SKILL GAP REPORT
================
Task: <one-line task description>

SOLID:  <comma-separated list>
FUZZY:  <list with specific uncertainty per item>
BLANK:  <list>

Priority gaps (fix before coding):
1. <gap> — blast_radius: <HIGH|MED|LOW> — coverage: <pct>% — remediation: <read X / grep for Y / ask>
2. ...

Coverage analysis:
  - <dependency/conflict notes>

Actionable recommendations:
1. <domain>: create/strengthen skill — suggested resource: <URL or file>

Estimated knowledge-fetch time: <N min>
Proceed: YES / NO (blocked on gap #N)
```

If `Proceed: NO`, do not write any code until the blocking gap is resolved.

---

## Blast radius reference

| HIGH | MED | LOW |
|------|-----|-----|
| Auth / session management | Core library API (serializer, ORM) | CLI flag parsing |
| Database schema / migrations | HTTP routing / middleware | Log / output formatting |
| State machine transitions | | Test helper utilities |
| IPC / protocol contracts | | |

---

## Examples

### Example A — Django REST API, uncertain pagination

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

Coverage analysis:
  - Gap #1 is independent of #2; both can be remediated in parallel

Actionable recommendations:
1. testing: existing pytest skill covers this (100%) — no action needed
2. documentation: no skill for docstring standards — consider adding one

Estimated knowledge-fetch time: 5 min
Proceed: NO (fetch docs for gap #1 first)
```

**What to do next:** fetch DRF CursorPagination docs via context7, confirm `ordering` field is required, then re-rate gap #1 as SOLID before writing the view.

---

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

**What to do next:** proceed directly to coding.

---

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
1. state: no skill file — after this task, write a state-machine-patterns skill
2. contracts: no skill file — ControlBus contract reading is reusable; document it

Estimated knowledge-fetch time: 8 min
Proceed: NO (blocked on gap #1 and #2)
```

**What to do next:** read `docs/STATE.md`, grep for `ControlBus` in the codebase, then re-rate both gaps before touching `state/task.py`.

---

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
1. Create skill: 'sqlalchemy-async' documenting session factory, scoped_session async patterns
2. Strengthen 'testing' skill: add async fixture examples using pytest-asyncio

Estimated knowledge-fetch time: 12 min
Proceed: NO (coverage conflicts must be resolved before mixing sync/async)
```

**What to do next:** fetch SQLAlchemy async docs, write a scratch test to confirm the async session factory works, then re-rate gap #1 before touching the handler.

---

## Rules

- **Never skip because "the task looks simple."** Simple-looking tasks regularly touch BLANK domains that invalidate the implementation.
- **FUZZY + high blast radius = treat as BLANK.** The cost is 5 minutes; the cost of getting it wrong is hours.
- **Report honestly.** Overconfidence wastes more time than a 2-minute doc check.
- **After each remediation, re-rate and update Proceed.** Don't carry stale ratings through multiple coding steps.
- **Grep codebase before fetching docs.** Existing patterns are the most reliable guide to how a library is actually used in this project.
- **Flag coverage conflicts explicitly.** Don't silently resolve domain convention mismatches.
- **Time-box remediations.** If a gap isn't resolved in the allotted time, escalate.

---

## Integration with other skills

| Skill | When to use it alongside gap analysis |
|-------|--------------------------------------|
| `systematic-debugging` | Switch to this if a bug survives one fix attempt after gap analysis |
| `dependency-audit` | Use when BLANK gaps involve version uncertainty across multiple packages |
| `test-coverage-triage` | Use after implementation to catch test coverage gaps in newly-BLANK domains |
| `architect-review` | Use when coverage conflicts affect system-level design decisions |

---

## Automated gap scoring

The companion script scores domain coverage across the full skill inventory against historical
task demand:

```sh
python C:\9to5\.claude\skills\skill-gap-analysis.py
```

Output columns: `# | Domain | Demand | Cov% | Covered By | Gap Score`

- **Demand**: total token frequency in task history for this domain's keywords
- **Cov%**: percentage of demand covered by existing skills
- **Covered By**: skill names that match this domain
- **Gap Score**: `demand × (1 − coverage_fraction)` — 0.0 = fully covered

The **Priority Actions** section lists the top-5 highest-gap domains:
- `"Create new skill for 'X'"` — no existing skill covers this domain
- `"Strengthen 'X' coverage (existing: Y)"` — partial coverage; improve the existing skill

Domains with `NONE` coverage and nonzero demand are critical gaps worth addressing immediately.

---

## Practical exercises

Run one of these before every non-trivial task to build the gap-analysis habit.

**Exercise 1 — Cold-start rating:** Pick a library you haven't used in >6 months. Without looking
it up, list 3 SOLID things, 2 FUZZY things (with specific uncertainty), and 1 BLANK thing.
Fetch docs and check your accuracy. Calibrate your FUZZY/BLANK threshold.

**Exercise 2 — Blast radius mapping:** For the current 9to5 codebase, map 5 files to blast-radius
levels. Which file, if broken, causes the most cascading failures?
(Hint: `orchestrator.py`, `state/task.py`)

**Exercise 3 — Coverage conflict detection:** Find two domains in the current task with
conflicting conventions (e.g., sync vs async, REST vs gRPC, ORM vs raw SQL). Write a one-line
conflict note before coding.

**Exercise 4 — Remediation speed drill:** Take a BLANK gap. Time yourself reaching SOLID.
If >10 min, the gap is HIGH complexity — escalate or simplify the task scope.

**Exercise 5 — Retrospective rating:** After completing a task, revisit the pre-task gap report.
Which FUZZY items caused bugs? Which BLANK items were harder than expected?
Adjust your calibration accordingly.

---

## Quick reference card

```
/skill-gap-analysis          invoke the skill
blast_radius HIGH   →  auth, DB schema, state machines, IPC contracts
blast_radius MED    →  core library API, HTTP routing/middleware
blast_radius LOW    →  CLI flags, log formatting, test helpers

FUZZY + HIGH blast radius  →  treat as BLANK, remediate before coding
Proceed: NO                →  do NOT write code until blocking gap is resolved
remediation order          →  grep codebase → version-pinned docs → authoritative source → ask
time-box                   →  LOW: 2 min · MED: 5 min · HIGH: 10 min → escalate
```

---

*See also: `.claude/skills/skill_gap_analysis.md` (full LLM-facing protocol), `.claude/skills/skill_gap_analysis/README.md` (quick reference)*
