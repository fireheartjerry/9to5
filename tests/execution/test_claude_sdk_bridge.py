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
