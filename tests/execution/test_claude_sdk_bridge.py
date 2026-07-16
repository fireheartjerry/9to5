from agents.execution import claude_sdk_bridge


def test_sdk_snapshot_rejects_dontask_and_missing_question_tool(monkeypatch):
    monkeypatch.setattr("config.CLARIFICATION_EXECUTOR_BACKEND", "sdk_preferred", raising=False)
    snap = claude_sdk_bridge.sdkCapabilitySnapshot(
        permission_mode="dontAsk", tools=["Read", "Grep"])
    assert snap["can_use_tool_reachable"] is False
    assert "restricted tools must include AskUserQuestion" in snap["warnings"]
    assert any("dontAsk" in w for w in snap["warnings"])


def test_sdk_snapshot_allows_restricted_tools_with_ask_user_question():
    snap = claude_sdk_bridge.sdkCapabilitySnapshot(
        permission_mode="default", tools=["Read", "AskUserQuestion"])
    assert snap["tools_contains_AskUserQuestion"] is True
    assert snap["can_use_tool_reachable"] is True


def test_build_ask_user_question_allow_fallback_shape():
    out = claude_sdk_bridge.buildAskUserQuestionAllow(
        {"questions": [{"question": "Q?", "options": [{"label": "A"}]}]},
        {"Q?": "A"},
    )
    if isinstance(out, dict):
        assert out["updated_input"]["answers"] == {"Q?": "A"}
    else:
        assert out.updated_input["answers"] == {"Q?": "A"}
def test_claude_version_uses_only_shared_neutral_probe(monkeypatch):
    from platform_core.execution import provider_probe
    calls = []
    monkeypatch.setattr(provider_probe, "runProviderProbe", lambda kind: (
        calls.append(kind), type("R", (), {"stdout": "Claude 9.9"})())[1])
    assert claude_sdk_bridge._claudeVersion() == "Claude 9.9"
    assert calls == [provider_probe.ProviderProbe.CLAUDE_VERSION]


def test_claude_version_real_delegation_runs_shared_probe_process(tmp_path):
    import json
    import sys
    probe = tmp_path / "provider.py"
    probe.write_text("import json,os,sys; print(json.dumps({'cwd':os.getcwd(),'argv':sys.argv[1:]}))", encoding="utf-8")
    result = claude_sdk_bridge._claudeVersion(probe_executable=[sys.executable, str(probe)])
    observed = json.loads(result)
    assert observed["argv"] == ["--version"]
    assert observed["cwd"] != str(tmp_path)
