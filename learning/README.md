# `learning/` -- feedback, evaluation, and evolution loops

Most implementation modules live in subpackages:

- `model/`: datasets, eval harness/runner, distillation, and fine-tuning.
- `feedback/`: human feedback, lessons, reflections, preferences, insight, and wisdom.
- `evolution/`: curriculum, SIE, promotion, policy, safety, self-play, and release mechanics.
- `eval_suite/`: structured evaluation assets.

Top-level modules such as `learning.eval_runner`, `learning.human_feedback`, and
`learning.sie` remain compatibility aliases.

