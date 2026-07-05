# Pattern: SCC + Dominator Blast-Radius Scoring

## Core Mechanism
Estimate how risky a change is from the import/call graph, not from line counts. Build the
module dependency graph, collapse cycles with Tarjan SCC into a condensation DAG, and (if
entrypoints are known) compute a dominator tree. Blast radius = touched SCCs + downstream
reachable SCCs + entrypoint-dominator weight + public-API-touch bonus. A leaf helper scores
low; a core module that dominates many paths scores high.

## When It Applies
Risk is currently guessed from diff size; you need a principled, cheap, deterministic
blast-radius signal to gate autonomy and rank portfolio cost.

## Transfer Recipe
Parse import edges, run Tarjan SCC → condensation, compute downstream reachability. Feed
blast_radius into the QD risk_bin, the autonomy gate, the innovation report's risk/scope, the
QD fitness penalty, and the portfolio node cost. Fail open (unknown ⇒ medium) if graph
extraction fails.

## Anti-Patterns
Equating diff size with risk. Ignoring cycles (double-counts). Hard-failing the run when the
graph can't be built.

## Example Candidate Shape
A `code_graph` module exposing blast_radius(touched_files) via SCC condensation + dominator
analysis, consumed by the gate/report/optimizer.

## Verification
A leaf helper change scores low; an orchestration-core change scores high; circular imports
collapse into one SCC; graph-extraction failure falls open to medium.
