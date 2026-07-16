"""RED behavioral contracts for a complete sealed controller runtime."""
from __future__ import annotations

import dataclasses
import hashlib
import importlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest


def _mod():
    return importlib.import_module("bootstrap.galaxy_launcher.runtime_manifest")


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sealed_runtime(mod, sealed):
    sealed.mkdir()
    interpreter = sealed / "python.exe"
    shutil.copy2(sys.executable, interpreter)
    dll_name = f"python{sys.version_info.major}{sys.version_info.minor}.dll"
    dll = Path(sys.base_prefix) / dll_name
    shutil.copy2(dll, sealed / dll.name)
    for source in Path(sys.base_prefix).glob("vcruntime*.dll"):
        shutil.copy2(source, sealed / source.name)

    archive = sealed / "runtime.zip"
    stdlib = Path(sys.base_prefix) / "Lib"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for source in sorted((stdlib / "encodings").rglob("*.py")):
            zf.write(source, source.relative_to(stdlib).as_posix())
        zf.writestr("galaxy_launcher/__init__.py", "")
        zf.writestr("galaxy_launcher/capsule.py", "ACTIVATION_STATE='inactive'")
        zf.writestr("galaxy_launcher/activation_verifier.py", "VERIFIER_KIND='generic'")
    pth = sealed / f"python{sys.version_info.major}{sys.version_info.minor}._pth"
    pth.write_text("runtime.zip\n.\n", encoding="ascii")
    asset = sealed / "representative.asset"
    asset.write_text("sealed-asset", encoding="utf-8")
    entrypoint = sealed / "controller_entry.py"
    entrypoint.write_text(
        "import os,sys\n"
        "import galaxy_launcher.capsule as c\n"
        "import galaxy_launcher.activation_verifier as v\n"
        "asset=os.path.join(sys.prefix,'representative.asset')\n"
        "dll=os.path.join(sys.prefix,'python%d%d.dll'%sys.version_info[:2])\n"
        "print(sys.executable)\nprint(sys.prefix)\nprint(c.__file__)\n"
        "print(v.__file__)\nprint(dll)\nprint(asset)\n"
        "print(open(asset,encoding='utf-8').read())\n",
        encoding="utf-8",
    )

    category_paths = {
        "python": (interpreter,),
        "stdlib": (archive, pth),
        "packages": (archive,),
        "native_libraries": tuple(sorted(sealed.glob("*.dll"))),
        "entrypoints": (entrypoint,),
        "schemas": (asset,),
        "prompts": (asset,),
        "templates": (asset,),
        "assets": (asset,),
    }
    leaves = {
        category: tuple(mod.RuntimeLeaf(path=path, sha256=_sha(path)) for path in paths)
        for category, paths in category_paths.items()
    }
    manifest = mod.ControllerRuntimeManifest(
        schema_version=1, leaves=leaves, interpreter=interpreter,
        isolated_flags=("-I", "-S"), network_allowed=False,
        ambient_site_packages_allowed=False,
    )
    return manifest, {path.resolve(): _sha(path) for paths in category_paths.values()
                      for path in paths}


def _create_junction(link, target):
    cp = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
                        text=True, capture_output=True, timeout=10)
    assert cp.returncode == 0, f"junction creation failed\nstdout={cp.stdout}\nstderr={cp.stderr}"


def test_manifest_hashes_every_executed_byte_and_child_resolves_only_beneath_sealed_root(tmp_path):
    mod = _mod()
    sealed = tmp_path / "sealed"
    manifest, expected_hashes = _sealed_runtime(mod, sealed)
    runtime = mod.select_verified_runtime(manifest, no_follow=True)
    assert runtime.interpreter.resolve() != Path(sys.executable).resolve()
    assert set(runtime.resolved_paths) == set(expected_hashes)
    assert runtime.verified_hashes == expected_hashes
    cp = runtime.run_python_file(sealed / "controller_entry.py", cwd=sealed,
                                 env={}, timeout=10)
    assert cp.returncode == 0, f"sealed runtime failed\nstdout={cp.stdout}\nstderr={cp.stderr}"
    lines = cp.stdout.splitlines()
    assert lines[-1] == "sealed-asset"
    reported = [Path(value.split("runtime.zip", 1)[0] or value).resolve()
                for value in lines[:-1]]
    assert all(path.is_relative_to(sealed.resolve()) for path in reported)
    assert Path(cp.args[0]).resolve() == runtime.interpreter.resolve()
    for path, digest in expected_hashes.items():
        assert _sha(path) == digest


def test_missing_mismatch_junction_and_ambient_fallback_refuse(tmp_path):
    mod = _mod()
    manifest, _ = _sealed_runtime(mod, tmp_path / "sealed")
    real_dir = tmp_path / "real-dir"
    real_dir.mkdir()
    real = real_dir / "python.exe"
    real.write_bytes(b"real")
    junction = tmp_path / "junction"
    _create_junction(junction, real_dir)
    try:
        attacks = [
            mod.RuntimeLeaf(path=tmp_path / "missing", sha256="0" * 64),
            mod.RuntimeLeaf(path=real, sha256="0" * 64),
            mod.RuntimeLeaf(path=junction / real.name, sha256=_sha(real)),
        ]
        for leaf in attacks:
            leaves = dict(manifest.leaves)
            leaves["python"] = (leaf,)
            attacked = dataclasses.replace(manifest, leaves=leaves, interpreter=leaf.path)
            with pytest.raises(mod.RuntimeClosureUnavailable):
                mod.select_verified_runtime(attacked, no_follow=True)
    finally:
        if junction.exists():
            os.rmdir(junction)


def test_missing_offline_oci_closure_is_typed_and_never_builds_or_pulls(tmp_path):
    mod = _mod()
    calls = []
    with pytest.raises(mod.OfflineActivationArtifactsUnavailable):
        mod.require_offline_activation_artifacts([], builder=lambda: calls.append("build"),
                                                 puller=lambda: calls.append("pull"))
    assert calls == []


def test_ambient_site_poison_cannot_enter_selected_sealed_runtime(tmp_path):
    mod = _mod()
    poison = tmp_path / "ambient"
    poison.mkdir()
    goldstone = tmp_path / "poison-ran"
    (poison / "sitecustomize.py").write_text(
        f"open(r'{goldstone}','w').write('x')", encoding="utf-8")
    sealed = tmp_path / "sealed"
    manifest, _ = _sealed_runtime(mod, sealed)
    runtime = mod.select_verified_runtime(manifest, no_follow=True)
    cp = runtime.run_python_file(
        sealed / "controller_entry.py", cwd=sealed,
        env={"PYTHONPATH": str(poison)}, timeout=10,
    )
    assert cp.returncode == 0, f"stdout={cp.stdout}\nstderr={cp.stderr}"
    assert cp.stdout.splitlines()[-1] == "sealed-asset"
    assert not goldstone.exists()
