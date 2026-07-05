# Pattern: Novelty-Search / Measured-Novelty Pressure

## Core Mechanism
Reward behavioral novelty measured against an archive of what has already been tried, instead
of trusting a self-reported "this is innovative" score. Novelty = distance to nearest prior
behavior. This drives exploration into genuinely new territory and exposes fake novelty.

## When It Applies
"Innovation" is self-assessed by the generator (gameable); the system keeps re-proposing
variants of past ideas; you need an objective, hard-to-fake novelty signal.

## Transfer Recipe
Embed each finding/approach and store it. Score a new candidate's novelty as 1 - max cosine to
history (optionally blended with archive-cell rarity + corpus-transfer distance). Let MEASURED
novelty dominate the finder score; treat the LLM's self-rating as a weak prior only. Enforce a
measured-novelty floor before something counts as an "invention".

## Anti-Patterns
Using only self-reported innovation (reward hacking). Novelty without a usefulness gate
(novel-but-useless). No history persistence (every run looks novel).

## Example Candidate Shape
A `novelty_index` over a vector store of prior findings that yields measured_novelty and
history_similarity_max, wired into finder scoring and a routing floor.

## Verification
Exact + paraphrase duplicates score low novelty; unrelated features score high; a vague
high-distance nonsense candidate is still rejected by the usefulness/specificity gate.
