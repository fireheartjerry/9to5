"""Automatic adapter promotion -- closes the 'adapters never promote' gap.

Trained LoRA adapters register as CHALLENGERS; this evaluates each against the champion
(and the frozen base as a floor) and promotes the winner through the safety gate
(invariant I4: never on a regression). Needs a per-tag fitness function -- registered by
the orchestrator when a live brain can serve each adapter tag; without it, it skips.

Runs in the weekly maintenance tier. See learning/eval_runner.py + learning/finetune.py.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import config
from learning import eval_runner, finetune
from memory import experience

LOG = config.getLogger("sie.adapter_promotion")


def run(*, db_path: Optional[Path] = None) -> dict[str, Any]:
    """Evaluate challenger adapters and promote the best one that beats the champion."""
    if config.SIE_KILL_SWITCH:
        return {"skipped": "kill_switch"}
    fut = eval_runner.fitness_under_tag()
    if fut is None:
        return {"skipped": "no_evaluator"}   # no brain can serve per-tag fitness here
    challengers = experience.fetch_adapters("challenger", db_path=db_path)
    if not challengers:
        return {"skipped": "no_challenger"}

    champ = experience.get_champion_adapter(db_path=db_path)
    champ_tag = champ["tag"] if champ else config.OLLAMA_MODEL
    try:
        bar = fut(champ_tag)
    except Exception as e:  # noqa: BLE001
        return {"skipped": "champion_eval_failed", "error": str(e)}

    results: dict[str, Any] = {}
    for c in challengers:
        try:
            cf = fut(c["tag"])
        except Exception as e:  # noqa: BLE001
            results[c["tag"]] = {"decision": "error", "error": str(e)}
            continue
        d = finetune.consider_promotion(c["id"], challenger_fitness=cf, champion_fitness=bar,
                                        db_path=db_path)
        results[c["tag"]] = d
        if d["decision"] == "promote":
            bar = cf   # the promoted adapter is the new bar for the rest
            LOG.info("PROMOTED adapter %s (fitness %.3f > %.3f)", c["tag"], cf, d["champion"])
    return results
