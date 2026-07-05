# Pattern: Darwin Gödel Machine — Open-Ended Archive

## Core Mechanism
Maintain an ever-growing archive of agents/solutions with traceable lineage. Crucially,
branch new candidates from DIVERSE ancestors, not only the current best. Lower-performing
"stepping stone" ancestors often unlock breakthroughs a greedy hill-climb would discard.
Every self-modification is empirically validated before adoption.

## When It Applies
Improvement has plateaued because search greedily exploits the current champion; you suspect
better regions exist but need intermediate, non-optimal stepping stones to reach them.

## Transfer Recipe
Persist candidates with parent lineage + emitter + generation. Parent selection samples across
diverse archive cells weighted by novelty/curiosity, not just top fitness. Keep lineage so a
reward-hacked or hallucinated "win" is auditable and reversible.

## Anti-Patterns
Sampling only the champion (premature convergence). Adopting a self-modification without
empirical re-verification (reward hacking). Losing lineage (can't debug regressions).

## Example Candidate Shape
An open-ended parent-selection function for generational forking that draws from diverse QD
cells + non-champion Pareto elites, with full lineage recorded per QDElite.

## Verification
Generation-2 branches provably originate from diverse elites (not only gen-1 winner); an
ablation that forces greedy top-only selection reaches a worse plateau on a fixture.
