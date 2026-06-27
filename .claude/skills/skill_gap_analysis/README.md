# skill-gap-analysis

Surface what you don't know before starting a hard task. Prevents confident-but-wrong execution.

## What it does

Before tackling a multi-file feature or unfamiliar codebase, this skill forces a structured
inventory of your current knowledge vs. what the task requires. It classifies domains as
SOLID / FUZZY / BLANK, ranks gaps by blast radius × dependency weight, and produces a
go/no-go decision with specific remediation steps and actionable development recommendations.

## How to invoke

```
/skill-gap-analysis
analyze my skill gaps
what do I need to know before starting this
```

Auto-triggers: starting a multi-file feature, two consecutive wrong attempts, task mentions
unfamiliar libraries/tools/protocols, after a code review that exposed knowledge gaps.

## Quick protocol (6 phases)

1. **Scope** — list every domain the task touches
2. **Inventory** — rate each domain: SOLID / FUZZY / BLANK
3. **Prioritize** — rank by `blast_radius × dependency_weight`
4. **Remediate** — grep codebase first, then fetch versioned docs, then ask
5. **Coverage analysis** — check horizontal coverage, depth, and conflicts
6. **Report** — emit gap report with recommendations; set `Proceed: YES / NO`

**Key rule:** FUZZY + high blast radius → treat as BLANK.

## Output format

```
SKILL GAP REPORT
================
Task: <one-line task description>

SOLID:  <comma-separated list>
FUZZY:  <list with specific uncertainty noted>
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

## Coverage analysis (Phase 5)

Coverage analysis goes beyond per-gap ratings to catch systemic issues:

| Check | What to look for |
|-------|-----------------|
| Horizontal coverage | Multiple BLANK domains that compound (one gap blocks another) |
| Coverage depth | Knowledge age > 3 months → re-verify; > 12 months → treat as BLANK |
| Coverage conflicts | Two domains with conflicting conventions (sync vs async, ORM vs SQL) |

Coverage percentage: `max(0, 100 × (1 − gap_score / demand))`  
— 0% = no coverage · 50% = one skill (partial) · 100% = saturated (2+ skills)

## Blast radius quick reference

| HIGH                        | MED                        | LOW                    |
|-----------------------------|----------------------------|------------------------|
| Auth / session management   | Core library API           | CLI flags              |
| DB schema / migrations      | HTTP routing / middleware  | Log formatting         |
| State machine transitions   |                            | Test helper utilities  |
| IPC / protocol contracts    |                            |                        |

## Remediation best practices

- Time-box: 2 min (LOW), 5 min (MED), 10 min (HIGH); escalate if exceeded
- Grep codebase before fetching external docs — existing patterns are most reliable
- Write a one-line note of what you learned before proceeding
- After remediation, apply the verified API in a scratch test first
- Check version-pinned docs (`requirements.txt`, `pyproject.toml`) before fetching external docs

## Example (condensed)

```
SKILL GAP REPORT
Task: add paginated endpoint to Django REST Framework API

SOLID:  Python, HTTP, JSON, Django ORM, pytest
FUZZY:  DRF serializer many=True with custom fields (used 8 months ago)
BLANK:  DRF CursorPagination — never used

Priority gaps:
1. CursorPagination — blast_radius: HIGH — coverage: 0% — remediation: fetch context7 docs
2. Serializer many=True — blast_radius: MED — coverage: 0% — remediation: grep codebase

Actionable recommendations:
1. testing: existing skill covers (100%) — no action needed
2. documentation: no skill — consider adding docstring-standards skill

Estimated knowledge-fetch time: 5 min
Proceed: NO (fetch docs for gap #1 first)
```

## Rules

- Never skip because "the task looks simple."
- FUZZY + high blast radius → treat as BLANK. Verify before using.
- Report honestly. 2-minute doc check beats a wrong implementation.
- After remediation, re-rate and update Proceed before coding.
- Grep codebase before fetching external docs.
- Flag coverage conflicts explicitly — do not silently resolve them.
- Time-box remediations; escalate if the gap doesn't resolve within the allotted time.

## Automated scoring

```sh
python C:\9to5\.claude\skills\skill-gap-analysis.py
```

Scores domain coverage across the full skill inventory vs. historical task demand.
Output: ranked table with Demand, Cov%, Covered By, Gap Score, plus Priority Actions.
Domains with `NONE` coverage and nonzero demand are critical gaps.

## See also

- [`../skill_gap_analysis.md`](../skill_gap_analysis.md) — full LLM-facing protocol with examples and exercises
- `../systematic_debugging/README.md` — use after gap analysis if bug persists
- `../dependency_audit/README.md` — use for version-uncertainty gaps across packages
- `../architect-review.md` — use when coverage conflicts affect system-level design
