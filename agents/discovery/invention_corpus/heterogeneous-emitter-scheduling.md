# Pattern: Heterogeneous Emitters + Bandit Scheduling

## Core Mechanism
Use multiple generators with DIFFERENT inductive biases as distinct "emitters" (not redundant
copies): a cheap wide explorer, a deep implementer, a recombiner that grafts compatible elites,
and a random emitter that fills empty niches. A UCB bandit estimates each emitter's recent value
per niche; a flow allocator spends a hard budget on the highest expected quality-diversity gain.

## When It Applies
You have >1 model/strategy available (e.g. a local model and a strong hosted model) and a
limited fork/token budget; different emitters win in different regions of the search.

## Transfer Recipe
Make Ollama the cheap divergent emitter and Claude the deep implement/verify emitter. Add
recombination (graft two elites) and random (empty-cell) emitters. Score emitters with UCB,
then allocate branch budget via min-cost/max-cost flow under hard caps so expensive emitters
run only when their expected value justifies the cost.

## Anti-Patterns
Treating both models as interchangeable (wasted diversity). Ignoring cost (blowing budget on
the expensive emitter). Allocating without hard caps (runaway forks).

## Example Candidate Shape
A `qd_emitters` module (ollama/claude/recombination/random) + an `emitter_scheduler` that
UCB-scores then flow-allocates a fixed branch budget across target cells.

## Verification
Scarce budget flows to highest expected QD gain; rare cells get an exploration bonus; the
expensive emitter is selected only when justified; allocation is deterministic under seed.
