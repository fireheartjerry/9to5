# Pattern: ADAS Meta-Agent Search

## Core Mechanism
A meta-agent programs NEW agent designs in code, learning from an archive of previously
discovered designs. Discovery is self-referential: the meta-agent improves by mining what
already worked and composing novel combinations, rather than hand-designing each agent.

## When It Applies
You have a growing store of past solutions/approaches and want the system to invent new
capability designs by recombining and extending prior discoveries automatically.

## Transfer Recipe
Feed the finders an archive of prior findings/approaches (via the novelty index) as context,
and prompt them to compose NEW capabilities that extend or recombine those, citing which prior
discoveries they build on. Capture each accepted invention as a reusable design-knowledge card.

## Anti-Patterns
Re-deriving the same idea every run (needs novelty-vs-history memory). Proposing designs with
no concrete implementation sketch (unbuildable).

## Example Candidate Shape
A finder lens that retrieves the top prior findings for the current repo state and proposes a
new capability that explicitly composes two of them, with a design sketch + verification plan.

## Verification
A proposed capability references specific prior discoveries; disabling archive context measurably
reduces the compositional novelty of proposals.
