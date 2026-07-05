# Pattern: AlphaEvolve Diff-Based LLM Mutation

## Core Mechanism
Treat an LLM as a mutation engine over an implementation artifact. Give it the current best
program plus a few high-performing "inspiration" programs and evaluation feedback; ask for a
targeted DIFF, not a rewrite. Score each mutant with an automated evaluator; retain/recombine
winners in a population. Evolution happens over real, runnable artifacts.

## When It Applies
You already have execution-grounded verification (tests/receipts) and want to evolve
solutions rather than one-shot them; the search space is wide and a directed LLM edit beats
random mutation.

## Transfer Recipe
9to5 already forks branches and verifies with factsGate. Add: (1) inject 1-3 inspiration
snippets (prior elites) into the mutation prompt, (2) prefer diff-shaped edits, (3) cascade
evaluators cheap→expensive so nonviable mutants die early, (4) feed verified winners back as
next-generation inspiration.

## Anti-Patterns
No automated evaluator ⇒ this degenerates into unguided churn. Don't evolve prose specs;
evolve artifacts that can be objectively scored.

## Example Candidate Shape
A generational fork loop where each generation's mutation prompt cites the previous winner +
top runner-up as inspiration, and a cheap static gate culls branches before expensive verify.

## Verification
Later generations show higher verified fitness than gen-0; the inspiration injection measurably
changes candidate content (ablation: remove it, quality drops).
