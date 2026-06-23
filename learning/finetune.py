"""Local LoRA distillation -- Layer 5 of the Self-Improvement Engine.

The deepest, slowest loop: fine-tune a LoRA adapter over the FROZEN base model on the
gold dataset, register it as a challenger, and (gated through the eval harness) promote
it. The base weights never change, so rollback is repointing a tag -- O(1) and total.

Training and ``ollama create`` are the only non-zero-cost-of-correctness pieces and are
isolated behind injectable seams (``trainer``, ``ollama_runner``) so this module is fully
offline-testable and so a host without a GPU simply skips ("no_trainer") instead of
failing. Everything obeys the kill switch and invariant I1 (base immutability).

See the spec (Layer 5 + governance).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

import config
from learning import distill
from memory import experience

LOG = config.getLogger("sie.finetune")

# Seams: a trainer turns a dataset into an adapter dir; a runner builds the Ollama model.
Trainer = Callable[[str, str], str]            # (dataset_path, out_dir) -> lora_path
OllamaRunner = Callable[[str, str], Any]       # (tag, modelfile_path) -> Any


def modelfile_text(base_model: str, lora_path: str) -> str:
    """An Ollama Modelfile that layers a LoRA adapter over the frozen base."""
    return f"FROM {base_model}\nADAPTER {lora_path}\n"


def write_modelfile(path: Path, base_model: str, lora_path: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(modelfile_text(base_model, lora_path), encoding="utf-8")
    return path


def default_trainer() -> Optional[Trainer]:
    """Resolve a local LoRA trainer if one is installed; else None (skip training).

    Kept as a stub seam here: a host with a GPU + PEFT/unsloth provides a real trainer
    (passed into ``run_finetune_cycle``); without one we degrade to L0-L4 cleanly."""
    return None


def active_brain_tag(role: str = "all", db_path: Optional[Path] = None) -> str:
    """The model tag the orchestrator should call NOW for a brain ``role`` (per-role MoE).
    Always one step from stock: the frozen base under the kill switch, when no adapter is
    promoted for the role, or on any error."""
    try:
        if config.SIE_KILL_SWITCH:
            return config.OLLAMA_MODEL
        champ = experience.get_champion_adapter(role, db_path=db_path)
        if champ:
            return champ["tag"]
        if role != "all":   # fall back to a general adapter if no role-specific one
            champ = experience.get_champion_adapter("all", db_path=db_path)
            if champ:
                return champ["tag"]
    except Exception as e:  # noqa: BLE001 -- routing must never break a brain call
        LOG.debug("active_brain_tag fell back to base: %s", e)
    return config.OLLAMA_MODEL


def rollback_to_base(role: Optional[str] = None, db_path: Optional[Path] = None) -> bool:
    """Retire the champion adapter (of ``role``, or all) -> active tag falls back to base."""
    return experience.retire_champion_adapter(role, db_path=db_path)


def _next_version(db_path: Optional[Path]) -> int:
    return len(experience.fetch_adapters(db_path=db_path)) + 1


def run_finetune_cycle(*, trainer: Optional[Trainer] = None,
                       ollama_runner: Optional[OllamaRunner] = None,
                       out_dir: Optional[Path] = None, min_examples: Optional[int] = None,
                       suite: Optional[list[dict[str, Any]]] = None,
                       db_path: Optional[Path] = None) -> dict[str, Any]:
    """One automatic distillation cycle: build gold dataset -> (if enough) train LoRA ->
    build the Ollama model -> register the adapter as a CHALLENGER. Best-effort; never
    promotes here (promotion is gated separately through the harness)."""
    if config.SIE_KILL_SWITCH:
        return {"skipped": "kill_switch"}
    out_dir = Path(out_dir or config.LORA_OUTPUT_DIR)
    ds = distill.build(db_path=db_path, out_path=out_dir / "dataset.jsonl", suite=suite)
    n = ds["examples"]
    need = config.LORA_MIN_EXAMPLES if min_examples is None else min_examples
    if n < need:
        return {"skipped": "not_enough", "examples": n, "need": need}
    trainer = trainer or default_trainer()
    if trainer is None:
        return {"skipped": "no_trainer", "examples": n}   # no GPU/backend on this host

    try:
        lora_path = trainer(ds["path"], str(out_dir))
        ver = _next_version(db_path)
        tag = f"{config.BRAIN_MODEL_TAG}:v{ver}"
        mf = write_modelfile(out_dir / f"Modelfile.v{ver}", config.OLLAMA_MODEL, lora_path)
        if ollama_runner is not None:
            ollama_runner(tag, str(mf))   # e.g. `ollama create <tag> -f <mf>`
        aid = experience.register_adapter(
            base_model=config.OLLAMA_MODEL, tag=tag, lora_path=lora_path,
            modelfile_path=str(mf), n_train_examples=n, state="challenger", db_path=db_path)
        LOG.info("trained adapter %s (%d examples)", tag, n)
        return {"status": "trained", "tag": tag, "adapter_id": aid, "examples": n}
    except Exception as e:  # noqa: BLE001 -- training failure must not crash maintenance
        LOG.warning("finetune cycle failed (ignored): %s", e)
        return {"skipped": "error", "error": str(e)}


def run_dpo_cycle(*, trainer: Optional[Callable[[str, str, float], str]] = None,
                  ollama_runner: Optional[OllamaRunner] = None,
                  out_dir: Optional[Path] = None, min_pairs: Optional[int] = None,
                  suite: Optional[list[dict[str, Any]]] = None,
                  db_path: Optional[Path] = None) -> dict[str, Any]:
    """One automatic DPO cycle: build preference pairs -> (if enough) train a DPO LoRA with
    a KL anchor -> build the Ollama model -> register a CHALLENGER. The DPO trainer seam
    takes ``(pairs_path, out_dir, kl_beta)``. Best-effort; never promotes here."""
    if config.SIE_KILL_SWITCH:
        return {"skipped": "kill_switch"}
    from learning import preferences
    out_dir = Path(out_dir or config.LORA_OUTPUT_DIR)
    ds = preferences.build(db_path=db_path, out_path=out_dir / "preferences.jsonl", suite=suite)
    n = ds["pairs"]
    need = config.DPO_MIN_PAIRS if min_pairs is None else min_pairs
    if n < need:
        return {"skipped": "not_enough", "pairs": n, "need": need}
    if trainer is None:
        return {"skipped": "no_trainer", "pairs": n}
    try:
        lora_path = trainer(ds["path"], str(out_dir), config.DPO_KL_BETA)
        ver = _next_version(db_path)
        tag = f"{config.BRAIN_MODEL_TAG}:dpo-v{ver}"
        mf = write_modelfile(out_dir / f"Modelfile.dpo-v{ver}", config.OLLAMA_MODEL, lora_path)
        if ollama_runner is not None:
            ollama_runner(tag, str(mf))
        aid = experience.register_adapter(
            base_model=config.OLLAMA_MODEL, tag=tag, lora_path=lora_path,
            modelfile_path=str(mf), n_train_examples=n, state="challenger", db_path=db_path)
        LOG.info("trained DPO adapter %s (%d pairs, beta=%.3f)", tag, n, config.DPO_KL_BETA)
        return {"status": "trained", "tag": tag, "adapter_id": aid, "pairs": n}
    except Exception as e:  # noqa: BLE001
        LOG.warning("dpo cycle failed (ignored): %s", e)
        return {"skipped": "error", "error": str(e)}


def consider_promotion(adapter_id: int, *, challenger_fitness: float, champion_fitness: float,
                       replay_ok: bool = True, db_path: Optional[Path] = None) -> dict[str, Any]:
    """Gate an adapter through the harness result + replay set (invariant I4: never promote
    on a regression). Live fitness is supplied by the eval harness; the decision is pure."""
    if challenger_fitness >= champion_fitness and replay_ok:
        experience.promote_adapter(adapter_id, db_path=db_path)
        return {"decision": "promote", "challenger": challenger_fitness, "champion": champion_fitness}
    return {"decision": "reject", "challenger": challenger_fitness, "champion": champion_fitness,
            "replay_ok": replay_ok}
