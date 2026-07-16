"""User-bound trust-material protection tests for the installed controller."""

from __future__ import annotations

import importlib

import pytest


def _module():
    return importlib.import_module("bootstrap.galaxy_launcher.activation_dpapi")


def test_user_bound_dpapi_round_trip_requires_exact_entropy():
    mod = _module()
    secret = bytes(range(32))
    protected = mod.protect_for_current_user(secret, entropy=b"generation-1")
    assert protected != secret
    assert mod.unprotect_for_current_user(protected, entropy=b"generation-1") == secret
    with pytest.raises(mod.DpapiRefused):
        mod.unprotect_for_current_user(protected, entropy=b"generation-2")
