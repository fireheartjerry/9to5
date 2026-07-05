# Pattern: MAP-Elites Quality-Diversity Archive

## Core Mechanism
Instead of keeping only the single best solution, discretize a space of behavioral
descriptors into a grid of cells and keep the highest-performing "elite" in each cell.
Search fills diverse niches (coverage) while raising quality per niche (QD-score), so it
resists collapsing onto one safe local optimum. New candidates compete only against the
current occupant of THEIR cell.

## When It Applies
A generator keeps producing similar, low-variety outputs; a selector rewards one narrow
kind of win; you want a portfolio of meaningfully different high-quality solutions rather
than N near-duplicates of the current champion.

## Transfer Recipe
Define product-first descriptors for a change (capability_type, innovation_mechanism,
subsystem, novelty_bin, risk_bin). Assign each verified implementation to its cell; keep a
champion + a capped Pareto frontier per cell. Report coverage and QD-score so "did we get
more DIVERSE wins" is measurable, not vibes. Seed later search from diverse cells.

## Anti-Patterns
Don't pick descriptors that are just genotype knobs (line counts) — use behaviorally
meaningful axes. Don't let one cell's champion dominate parent selection (that reintroduces
mode collapse).

## Example Candidate Shape
A `qd_archive` that stores verified 9to5 subtask solutions by (capability, subsystem,
novelty) cell, exposes coverage()/qd_score(), and feeds diverse elites back into forking.

## Verification
On a fixture goal, coverage and qd_score strictly increase across generations vs a
one-shot baseline; two structurally different valid solutions land in different cells.
