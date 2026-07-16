"""Fail-closed tests for the credentialless live-probe worker."""

from __future__ import annotations

import importlib

import pytest


def _module():
    return importlib.import_module("bootstrap.galaxy_launcher.activation_verifier")


@pytest.mark.parametrize(
    "raw",
    (
        b'{"schema":1,"schema":1}',
        b'{"value":1.25}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b" {}",
    ),
)
def test_probe_specification_rejects_noncanonical_or_ambiguous_json(tmp_path, raw):
    mod = _module()
    path = tmp_path / "probe.json"
    path.write_bytes(raw)
    with pytest.raises(mod.ProbeRefused):
        mod._load_canonical(path)


def test_probe_arguments_are_bound_before_any_broker_effect(tmp_path, monkeypatch):
    mod = _module()
    path = tmp_path / "probe.json"
    value = {"probe_id": "p", "probe_digest": "1" * 64}
    path.write_bytes(mod._canonical_json(value))

    def must_not_run(_path):
        raise AssertionError("broker effect happened before argument binding")

    monkeypatch.setattr(mod, "run_probe", must_not_run)
    assert (
        mod.main(
            [
                "--probe-worker",
                "wrong",
                "1" * 64,
                "--spec",
                str(path),
            ]
        )
        == 78
    )
