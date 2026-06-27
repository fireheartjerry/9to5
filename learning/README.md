# `learning/` — the Self-Improvement Engine (SIE), **downstream only**

32 modules that *consume traces and propose improvements*. Module index: `learning/AGENTS.md`.

## Role (recommended)
trace recorder · failure taxonomy · playbook miner · eval generator · prompt/router optimizer ·
small LoRA/adapter experiment harness. Layers: experience ledger → retrieval → consolidation/
policy → prompt evolution → distillation → reward/DPO → rollout/counterfactual → curriculum.

## Hard boundary (the one rule)
Learning **must NOT mutate the live execution path during a run.** It runs post-run, off-thread,
throttled, file-locked. It may never bypass: the verifier, the adversary, the guard hooks, the
universe hard boundaries, configured human gates, or source-of-truth ownership. Adapter promotion
requires eval gates. See `docs/DANGER_MAP.md` (`promotion.py`/`finetune.py`/`rollout.py`) and
CLAUDE.md §30.

## Key files
`experience` consumers, `retrieval.py`, `policy.py`, `prompts.py`, `promotion.py`, `finetune.py`,
`rollout.py`, `reward.py`, `sie.py` (cadence ladder), `safety.py` (invariants + kill switch).

## Tests
`tests/test_*` for each module; learning changes should also assert "consumes trace without
mutating live run" (a target scenario in `docs/TESTING.md`).
