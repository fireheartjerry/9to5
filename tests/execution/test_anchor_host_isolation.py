"""RED behavioral tests for protected-record and host isolation at the anchor."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess

import pytest


def _mod():
    return importlib.import_module("bootstrap.galaxy_launcher.anchor")


@dataclass
class AnchorArtifacts:
    record: object
    original_record: object
    record_path: Path
    capsule: Path
    manifest: Path
    generation: Path


def _fixture(mod, root, *, generation=1, activation_state="inactive"):
    root.mkdir()
    capsule_dir = root / "capsule"
    capsule_dir.mkdir()
    capsule = capsule_dir / "controller.pyz"
    capsule.write_bytes(b"sealed controller capsule")
    manifest = root / "runtime-manifest.json"
    manifest.write_text('{"schema":1,"closed":true}', encoding="utf-8")
    generation_path = root / "generation"
    generation_path.write_text(str(generation), encoding="ascii")
    record_path = root / "anchor-record.json"
    mapping = {
        "schema": 1,
        "capsule_path": str(capsule),
        "capsule_sha256": hashlib.sha256(capsule.read_bytes()).hexdigest(),
        "runtime_manifest_path": str(manifest),
        "runtime_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "generation_path": str(generation_path),
        "generation": generation,
        "activation_state": activation_state,
    }
    record_path.write_text(json.dumps(mapping, sort_keys=True, separators=(",", ":")),
                           encoding="utf-8")
    record = mod.ProtectedAnchorRecord.load(record_path, no_follow=True)
    return AnchorArtifacts(record, record, record_path, capsule, manifest, generation_path)


def _create_junction(link, target):
    cp = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
                        text=True, capture_output=True, timeout=10)
    assert cp.returncode == 0, f"junction creation failed\nstdout={cp.stdout}\nstderr={cp.stderr}"


def _attack(fixture, attack, tmp_path):
    if attack == "capsule":
        fixture.capsule.write_bytes(b"replaced")
    elif attack == "manifest":
        fixture.manifest.write_bytes(b"replaced")
    elif attack == "generation":
        fixture.generation.write_text("999", encoding="ascii")
    else:
        original_dir = fixture.capsule.parent
        displaced = tmp_path / "displaced-capsule"
        original_dir.rename(displaced)
        outside = tmp_path / "outside-capsule"
        outside.mkdir()
        (outside / fixture.capsule.name).write_bytes(b"sealed controller capsule")
        _create_junction(original_dir, outside)
        return original_dir
    return None


def test_anchor_verifies_digest_generation_and_inactive_state_before_start(tmp_path):
    mod = _mod()
    fixture = _fixture(mod, tmp_path / "anchor", generation=3)
    starts = []
    with pytest.raises(mod.TransactionalKernelInactive):
        mod.SingularityAnchor(fixture.record).launch("fresh", starter=lambda **kw: starts.append(kw))
    assert starts == []


@pytest.mark.parametrize("attack", ["capsule", "manifest", "generation", "junction"])
def test_simultaneous_replacement_generation_and_reparse_attacks_never_start(attack, tmp_path):
    mod = _mod()
    fixture = _fixture(mod, tmp_path / "anchor", generation=5, activation_state="active")
    junction = _attack(fixture, attack, tmp_path)
    starts = []
    try:
        with pytest.raises(mod.AnchorIntegrityRefused):
            mod.SingularityAnchor(fixture.record).launch(
                "resume", starter=lambda **kw: starts.append(kw))
        assert starts == []
    finally:
        if junction is not None and junction.exists():
            os.rmdir(junction)


def test_poisoned_cwd_env_profiles_and_import_paths_are_not_inherited(tmp_path):
    mod = _mod()
    fixture = _fixture(mod, tmp_path / "anchor", activation_state="active")
    captured = []
    mod.SingularityAnchor(fixture.record).launch(
        "diagnostic", inherited_env={"PYTHONPATH": "poison", "PATH": "poison",
                                     "PROMPT": "poison", "HOME": str(tmp_path)},
        inherited_cwd=tmp_path, starter=lambda **kw: captured.append(kw))
    launch = captured[0]
    assert launch["cwd"] != tmp_path and list(launch["cwd"].iterdir()) == []
    assert "PYTHONPATH" not in launch["env"] and launch["env"].get("PATH") != "poison"
    assert launch["flags"] == ["-I", "-S"]
    assert launch["stdin"] == launch["stdout"] == launch["stderr"] == "DEVNULL"


def test_combined_capsule_sidecar_generation_attack_and_preanchor_readiness_refuse(tmp_path):
    mod = _mod()
    fixture = _fixture(mod, tmp_path / "anchor", generation=7, activation_state="active")
    fixture.capsule.write_bytes(b"replaced")
    fixture.manifest.write_bytes(b"replaced")
    fixture.generation.write_text("8", encoding="ascii")
    starts = []
    with pytest.raises(mod.AnchorIntegrityRefused):
        mod.SingularityAnchor(fixture.record).launch("fresh", starter=lambda **kw: starts.append(kw))
    assert starts == []
    legacy = mod.PreAnchorLegacyReadiness(processes=[123], listeners=["discord"])
    with pytest.raises(mod.PreAnchorGenerationRefused):
        mod.SingularityAnchor(fixture.original_record).accept_readiness(legacy)
