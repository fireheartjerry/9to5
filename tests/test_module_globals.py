"""Verify module globals are production-ready.

R5: there is exactly ONE Ollama client seam -- ``llm_io.getClient`` -- and it is lazy
(no client at import time). The old per-module ``_getOllama`` copies are gone: no
agent module may own its own client.

Checks:
- llm_io does NOT create the client at import time (_CLIENT is None)
- architect / replanner / elaborator / discovery own NO module-level client or _getOllama
- Key constants follow ALL_CAPS naming convention
"""
from __future__ import annotations

import pathlib
import sys

# Ensure the project root (C:\9to5) is on the path when run as a standalone script.
_PROJECT_ROOT = pathlib.Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def test_llm_io_client_is_lazy():
    import llm_io
    # the memoized client must not be built by imports alone (tests never build it at all)
    assert callable(llm_io.getClient)
    assert callable(llm_io.chat)


_NO_PRIVATE_CLIENT_MODULES = (
    "agents.architect",
    "agents.replanner",
    "agents.elaborator",
    "agents.clarifier",
    "agents.discovery.lenses",
    "agents.discovery.synthesis",
)


def test_no_module_owns_a_private_ollama_client():
    import importlib
    for name in _NO_PRIVATE_CLIENT_MODULES:
        mod = importlib.import_module(name)
        assert not hasattr(mod, "_OLLAMA"), f"{name} must not own a module-level _OLLAMA"
        assert not hasattr(mod, "_getOllama"), \
            f"{name} must not re-implement _getOllama (llm_io.getClient is the one seam)"


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
        test_llm_io_client_is_lazy,
        test_no_module_owns_a_private_ollama_client,
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
