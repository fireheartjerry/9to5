"""Zero-touch environment bootstrap -- so the user only ever presses start.

The deep layers need a training stack (transformers/peft/trl/torch) and local Ollama
models (the embedder + the base brain). Rather than make the user run setup commands, the
engine provisions them itself, once, best-effort: it pip-installs the training deps on a
GPU host and pulls the required Ollama models if absent. Everything is guarded, throttled,
and degrades silently when offline -- it never blocks a run.

See the spec (meta-loop) -- this is what makes "only start/abort/status" literally true.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Optional

import config

LOG = config.getLogger("sie.bootstrap")

_TRAINING_DEPS = ("torch", "transformers", "peft", "trl", "datasets", "accelerate")
_done = {"deps": False, "models": False}


def _have(mod: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(mod) is not None


def ensure_training_deps() -> dict:
    """Install the LoRA training stack if a GPU host lacks it (best-effort, once)."""
    if _done["deps"]:
        return {"skipped": "already"}
    from learning import compute
    if not (compute.training_enabled() and compute.should_use_gpu()):
        return {"skipped": "no_gpu"}            # no point installing torch-cuda without a GPU
    missing = [d for d in _TRAINING_DEPS if not _have(d.split("==")[0])]
    if not missing:
        _done["deps"] = True
        return {"present": True}
    try:
        LOG.info("bootstrap: installing training deps %s", missing)
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", *missing],
                       capture_output=True, text=True, timeout=1800)
        _done["deps"] = True
        return {"installed": missing}
    except Exception as e:  # noqa: BLE001 -- never block on a failed install
        LOG.warning("bootstrap deps failed (ignored): %s", e)
        return {"error": str(e)}


def ensure_models() -> dict:
    """Pull the embedder + base brain into Ollama if missing (best-effort, once)."""
    if _done["models"]:
        return {"skipped": "already"}
    if not shutil.which("ollama"):
        return {"skipped": "no_ollama"}
    pulled = []
    for model in (config.EMBED_MODEL, config.OLLAMA_MODEL):
        try:
            have = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=30)
            if model.split(":")[0] in (have.stdout or ""):
                continue
            LOG.info("bootstrap: pulling Ollama model %s", model)
            subprocess.run(["ollama", "pull", model], capture_output=True, text=True, timeout=3600)
            pulled.append(model)
        except Exception as e:  # noqa: BLE001
            LOG.warning("bootstrap pull %s failed (ignored): %s", model, e)
    _done["models"] = True
    return {"pulled": pulled}


def ensure_all() -> dict:
    """Run the full bootstrap once. Called automatically by the maintenance loop."""
    return {"deps": ensure_training_deps(), "models": ensure_models()}
