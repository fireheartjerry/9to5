# Pattern: Evidence-Grounded Reporting (Facts vs Assessments)

## Core Mechanism
Split every "we improved X" claim into re-derivable FACTS (test exit codes, diff shas, gate
verdicts, measured novelty, benchmark numbers) versus LLM ASSESSMENTS (prose). A claim goes
"green" only from facts. The model may phrase the report, but every entry must cite mechanically
extracted evidence, and unsupported claims are dropped.

## When It Applies
Reports drift into self-congratulation; a run claims success that verification doesn't support;
you need stakeholders to trust the "innovative changes" summary.

## Transfer Recipe
Add a deterministic evidence extractor (multi-pattern scan for test-pass markers, factsGate
receipts, diff summaries, module names, TODO/FIXME). Compile innovation entries that derive
only from facts (verified diff + QD cell + measured novelty + rollback). Separate SHIPPED from
PROPOSED from REJECTED. Never call a failed-verify candidate a shipped win.

## Anti-Patterns
LLM inventing evidence. Presenting proposals as shipped. High novelty presented as success
without a usefulness/verify fact.

## Example Candidate Shape
An `innovation_report.compileInnovativeChanges(state)` that emits fact-referenced entries and a
Discord "Innovative Changes" embed, backed by an Aho-Corasick evidence extractor.

## Verification
A claim with no evidence ref is dropped; a verified change appears with refs; a failed
high-novelty candidate never appears as shipped.
