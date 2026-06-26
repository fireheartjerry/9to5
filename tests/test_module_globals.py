"""Verify module globals are production-ready.

Checks:
- architect and replanner do NOT create an Ollama client at import time (_OLLAMA is None)
- clarifier has no module-level Ollama client (by design)
- Key constants follow ALL_CAPS naming convention
"""
from __future__ import annotations

import pathlib
import sys

# Ensure the project root (C:\9to5) is on the path when run as a standalone script.
_PROJECT_ROOT = pathlib.Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _fresh_import(module_name: str):
    """Drop a module from sys.modules so the next import re-runs module-level code."""
    sys.modules.pop(module_name, None)
    import importlib
    return importlib.import_module(module_name)


def test_architect_lazy_ollama():
    arch = _fresh_import("agents.architect")
    assert arch._OLLAMA is None, f"Expected None at import, got {type(arch._OLLAMA)}"


def test_replanner_lazy_ollama():
    rp = _fresh_import("agents.replanner")
    assert rp._OLLAMA is None, f"Expected None at import, got {type(rp._OLLAMA)}"


def test_architect_get_ollama_helper_exists():
    import agents.architect as arch
    assert callable(getattr(arch, "_getOllama", None)), "_getOllama must be a callable in architect"


def test_replanner_get_ollama_helper_exists():
    import agents.replanner as rp
    assert callable(getattr(rp, "_getOllama", None)), "_getOllama must be a callable in replanner"


def test_clarifier_no_module_level_client():
    import agents.clarifier as cl
    assert not hasattr(cl, "_OLLAMA"), "clarifier must not have a module-level _OLLAMA"


def test_architect_constants_naming():
    import agents.architect as arch
    assert hasattr(arch, "ARCHITECT_SYSTEM_PROMPT"), "ARCHITECT_SYSTEM_PROMPT must exist"
    assert isinstance(arch.ARCHITECT_SYSTEM_PROMPT, str)


def test_replanner_constants_naming():
    import agents.replanner as rp
    assert hasattr(rp, "REPLANNER_SYSTEM"), "REPLANNER_SYSTEM must exist"
    assert isinstance(rp.REPLANNER_SYSTEM, str)


if __name__ == "__main__":
    tests = [
        test_architect_lazy_ollama,
        test_replanner_lazy_ollama,
        test_architect_get_ollama_helper_exists,
        test_replanner_get_ollama_helper_exists,
        test_clarifier_no_module_level_client,
        test_architect_constants_naming,
        test_replanner_constants_naming,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    if failed:
        raise SystemExit(1)
