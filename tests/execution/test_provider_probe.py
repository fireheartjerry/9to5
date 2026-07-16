"""RED behavioral contracts for the sole neutral provider diagnostic process."""
from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _mod():
    return importlib.import_module("platform_core.execution.provider_probe")


def test_probe_kind_is_closed_to_version_and_auth_status():
    mod = _mod()
    assert {member.value for member in mod.ProviderProbe} == {
        "claude_version", "claude_auth_status",
    }


def test_real_probe_runs_from_fresh_empty_cwd_closed_env_no_stdin_or_prompt(tmp_path):
    mod = _mod()
    script = tmp_path / "probe.py"
    script.write_text(
        "import json,os,sys,pathlib; print(json.dumps({"
        "'cwd':os.getcwd(),'files':list(pathlib.Path('.').iterdir()),"
        "'env':dict(os.environ),'stdin':sys.stdin.read(),'argv':sys.argv[1:]}))",
        encoding="utf-8",
    )
    result = mod.runProviderProbe(mod.ProviderProbe.CLAUDE_VERSION,
                                  executable=[sys.executable, str(script)],
                                  inherited_env={"PYTHONPATH": str(ROOT),
                                                 "CLAUDE_PROJECT_DIR": str(ROOT),
                                                 "SECRET": "goldstone"})
    observed = json.loads(result.stdout)
    assert observed["files"] == []
    assert observed["stdin"] == ""
    assert observed["argv"] == ["--version"]
    assert "SECRET" not in observed["env"] and "PYTHONPATH" not in observed["env"]
    assert observed["env"].get("CLAUDE_CODE_DISABLE_PROJECT_DISCOVERY") == "1"
    assert Path(observed["cwd"]) != ROOT
    assert result.prompt_bytes_sent == 0


@pytest.mark.parametrize("argv", [
    ["claude", "--print", "hello"], ["codex", "exec", "hello"],
    ["cmd", "/c", "claude --print hello"],
    ["powershell", "-Command", "claude --print hello"],
    ["python", "-c", "import subprocess; subprocess.run(['claude'])"],
    ["wrapper.bat", "claude"],
])
def test_neutral_probe_rejects_inference_and_transitive_wrappers_before_runner(argv):
    mod = _mod()
    calls = []
    with pytest.raises(mod.InvalidProviderProbe):
        mod.runProviderProbe(argv, runner=lambda **kw: calls.append(kw))
    assert calls == []


def test_provider_spawn_inventory_allows_only_neutral_probe_and_guarded_executor():
    allowed_subprocess = {
        "platform_core/execution/provider_probe.py",
        "agents/execution/executor_stream.py",
    }
    provider_modules = {
        "agents/execution/claude_sdk_bridge.py",
        "platform_core/ops/health.py",
    }
    offenders = []
    for top in ("agents", "platform_core", "learning", "notifications"):
        for path in (ROOT / top).rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            tree = ast.parse(path.read_text("utf-8"), filename=rel)
            imports_subprocess = any(
                isinstance(node, ast.Import) and any(a.name == "subprocess" for a in node.names)
                or isinstance(node, ast.ImportFrom) and node.module == "subprocess"
                for node in ast.walk(tree)
            )
            literals = {node.value.lower() for node in ast.walk(tree)
                        if isinstance(node, ast.Constant) and isinstance(node.value, str)}
            constructs_provider = any("claude" in value or "codex" in value for value in literals)
            if imports_subprocess and constructs_provider and rel not in allowed_subprocess:
                # Generic git/test subprocess modules are permitted only if they do not resolve a provider.
                resolves_provider = any("which" in value or value in {"claude", "codex"}
                                        for value in literals)
                if resolves_provider:
                    offenders.append(rel)
            if rel in provider_modules:
                names = {node.module for node in ast.walk(tree)
                         if isinstance(node, ast.ImportFrom)}
                assert "platform_core.execution.provider_probe" in names
                assert not imports_subprocess
    assert offenders == []
