"""_execCwd: self-ref still uses .sc-ctx today; a non-local fabric backend subsumes that scratch."""
import os
from unittest import mock

import config
from platform_core.orchestration import run_loop


class _State:
    def __init__(self, self_ref):
        self.meta = {"is_self_referential": self_ref}


def test_self_ref_uses_sc_ctx_when_fabric_off():
    state = _State(True)
    root = str(config.PROJECT_ROOT)
    with mock.patch.object(config, "EXECUTION_FABRIC_ENABLED", False):
        out = run_loop._execCwd(state, "st-001", root)
    assert out.endswith(os.path.join(".sc-ctx", "st-001"))


def test_non_local_backend_skips_sc_ctx():
    state = _State(True)
    root = str(config.PROJECT_ROOT)
    with mock.patch.object(config, "EXECUTION_FABRIC_ENABLED", True), \
         mock.patch.object(config, "EXECUTION_BACKEND", "worktree"):
        out = run_loop._execCwd(state, "st-001", root)
    assert out == root          # worktree provision (not .sc-ctx) governs isolation


def test_local_backend_keeps_sc_ctx():
    state = _State(True)
    root = str(config.PROJECT_ROOT)
    with mock.patch.object(config, "EXECUTION_FABRIC_ENABLED", True), \
         mock.patch.object(config, "EXECUTION_BACKEND", "local"):
        out = run_loop._execCwd(state, "st-001", root)
    assert out.endswith(os.path.join(".sc-ctx", "st-001"))
