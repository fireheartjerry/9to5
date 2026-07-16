"""RED subprocess contracts for the pinned external mypy bootstrap."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "bootstrap" / "galaxy_launcher" / "dev_tools.lock.json"
TOOL = ROOT / "tools" / "bootstrap_galaxy_dev_tools.py"


def _run(root, *args, env=None):
    return subprocess.run([sys.executable, str(TOOL), "--lock", str(LOCK), "--root", str(root),
                           *args], cwd=ROOT, env=env, text=True, capture_output=True)


def test_lock_validation_requires_exact_mypy_230_pure_wheel_hash_closure(tmp_path):
    assert TOOL.is_file() and LOCK.is_file()
    cp = _run(tmp_path / "tools", "--validate-lock-only")
    assert cp.returncode == 0, cp.stderr
    report = json.loads(cp.stdout)
    assert report["mypy_version"] == "2.3.0"
    assert report["closure_complete"] and report["all_artifacts_are_wheels"]
    assert report["hashes_sizes_licenses_compatibility_complete"]


def test_offline_bootstrap_prints_external_interpreter_and_runs_exact_mypy(tmp_path):
    assert TOOL.is_file() and LOCK.is_file()
    cp = _run(tmp_path / "tools", "--offline", "--only-binary", "--require-hashes",
              "--print-python-only", env={})
    assert cp.returncode == 0, cp.stderr
    python = Path(cp.stdout.strip())
    assert python.is_file() and tmp_path in python.parents
    version = subprocess.run([str(python), "-m", "mypy", "--version"],
                             text=True, capture_output=True, env={})
    assert version.returncode == 0 and version.stdout.startswith("mypy 2.3.0")
    replay = _run(tmp_path / "tools", "--offline", "--only-binary", "--require-hashes",
                  "--print-python-only", env={})
    assert replay.returncode == 0 and replay.stdout == cp.stdout
    target = tmp_path / "typed.py"
    target.write_text("value: int = 1\n", encoding="utf-8")
    checked = subprocess.run([str(python), str(ROOT / "tools" / "dev.py"),
                              "typecheck", str(target)],
                             cwd=ROOT, env={}, text=True, capture_output=True)
    assert checked.returncode == 0, checked.stderr
    assert Path(checked.args[0]).resolve() == python.resolve()


def test_poisoned_pip_index_proxy_sdist_hash_version_and_target_all_refuse(tmp_path):
    assert TOOL.is_file() and LOCK.is_file()
    poison = tmp_path / "poison"
    poison.mkdir()
    (poison / "pip.conf").write_text("[global]\nindex-url=https://evil.invalid\n", encoding="utf-8")
    env = {
        "PIP_CONFIG_FILE": str(poison / "pip.conf"), "PIP_INDEX_URL": "https://evil.invalid",
        "HTTPS_PROXY": "http://evil.invalid", "PYTHONPATH": str(ROOT),
    }
    baseline = json.loads(LOCK.read_text("utf-8"))
    attacks = []
    wrong_hash = json.loads(json.dumps(baseline))
    wrong_hash["wheels"][0]["sha256"] = "0" * 64
    attacks.append(("wrong-hash", wrong_hash))
    wrong_version = json.loads(json.dumps(baseline))
    wrong_version["mypy_version"] = "2.2.0"
    attacks.append(("wrong-version", wrong_version))
    sdist = json.loads(json.dumps(baseline))
    sdist["wheels"][0]["filename"] = "mypy-2.3.0.tar.gz"
    attacks.append(("sdist", sdist))
    for name, poisoned_lock in attacks:
        lock = tmp_path / f"{name}.lock.json"
        lock.write_text(json.dumps(poisoned_lock), encoding="utf-8")
        target = tmp_path / name
        cp = subprocess.run([sys.executable, str(TOOL), "--lock", str(lock),
            "--root", str(target), "--offline", "--only-binary", "--require-hashes"],
            cwd=ROOT, env=env, text=True, capture_output=True)
        assert cp.returncode != 0
        assert not (target / "bin" / "mypy").exists()
    target_cp = subprocess.run([sys.executable, str(TOOL), "--lock", str(LOCK),
        "--root", str(ROOT), "--offline", "--only-binary", "--require-hashes"],
        cwd=ROOT, env=env, text=True, capture_output=True)
    assert target_cp.returncode != 0


def test_valid_lock_refuses_poisoned_ambient_pip_config_index_and_proxy(tmp_path):
    assert TOOL.is_file() and LOCK.is_file()
    poison = tmp_path / "pip.ini"
    poison.write_text("[global]\nindex-url=https://evil.invalid\n", encoding="utf-8")
    env = {"PIP_CONFIG_FILE": str(poison), "PIP_INDEX_URL": "https://evil.invalid/simple",
           "PIP_EXTRA_INDEX_URL": "https://evil2.invalid/simple",
           "HTTPS_PROXY": "http://evil.invalid:8080"}
    cp = _run(tmp_path / "valid-lock-poisoned", "--offline", "--only-binary",
              "--require-hashes", env=env)
    assert cp.returncode != 0
    assert "ambient pip configuration" in cp.stderr.lower()
