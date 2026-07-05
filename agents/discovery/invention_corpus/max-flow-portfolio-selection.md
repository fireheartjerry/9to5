# Pattern: Max-Closure / Min-Cut Portfolio Selection

## Core Mechanism
Selecting which inventions to pursue is not a ranked list — candidates have dependencies,
conflicts, cost, and value. Model it as maximum-weight closure of a directed graph, solved by
s-t min-cut / max-flow: positive node weight = expected utility, negative = cost/risk, a
dependency edge A→B (infinite capacity) forces "pick A ⇒ must pick B". The selected side of the
min cut is the provably optimal closed set — a weak foundation gets chosen when it unlocks a
high-value dependent.

## When It Applies
Many candidate improvements with prerequisites and mutual conflicts; greedy top-N picks
shiny items but strands their prerequisites or double-books conflicting work.

## Transfer Recipe
Build a candidate graph: node weight = +impact +novelty +rarity +confidence −cost −risk
−blast_radius −uncertainty; edges candidate→prerequisite. Solve max-closure. Repair conflicts
deterministically (keep higher adjusted utility, demote the other to proposal, record it).
Use the selected set for the proposal portfolio and safe auto-run bundles.

## Anti-Patterns
Greedy ranking that ignores dependencies. Letting a negative-utility node in just because a
dependent wanted it without the dependent's value covering it. Non-deterministic conflict
resolution.

## Example Candidate Shape
A `portfolio_optimizer` that runs max-closure over discovered candidates and returns a
PortfolioSelection with selected/demoted ids, dependency edges, and repaired conflicts.

## Verification
A dependency is selected alongside its dependent; a standalone negative-utility node is
rejected; a weak foundation is chosen when it unlocks a high-value feature; conflicts repair
deterministically.
