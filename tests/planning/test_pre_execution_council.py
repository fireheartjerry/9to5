import json
import re
import urllib.error
from pathlib import Path

import config
from agents.planning.council_context import CouncilContextPack
from agents.planning.council_logging import redact_council_text
from agents.planning.pre_execution_council import (
    CouncilConfig,
    CouncilMessage,
    CouncilQualityWarning,
    CouncilRunner,
    RunCompositionSummary,
    evaluate_message_quality,
    run_pre_execution_council,
)
from tools.pre_execution_council_compare import _config as _compare_config
from tools.pre_execution_council_compare import _metric_line, _parse_args as _compare_parse_args
from tools.pre_execution_council_quality_report import build_report, load_run


def _last_continuity_line(prompt: str) -> str:
    matches = re.findall(r"(\[CONTINUITY\]\s*\{[^\n\r]*\})", prompt)
    return matches[-1] if matches else ""


def _enabled_config(tmp_path, **overrides):
    data = {
        "enabled": True,
        "messages_per_seat": 12,
        "total_target_messages": 48,
        "output_dir": str(tmp_path),
        "logging_enabled": True,
    }
    data.update(overrides)
    return CouncilConfig(**data)


class _RecordingSeat:
    def __init__(self, name):
        self.name = name
        self.prompts = []
        self.contexts = []

    def ask(self, prompt, context):
        self.prompts.append(prompt)
        self.contexts.append(dict(context))
        phase = context.get("selector_phase", "round_robin")
        if phase == "independent_memo":
            return f"[CLAIM] {self.name} independent memo preserves a unique {self.name} claim."
        if phase == "selected_debate":
            return f"[RISK] {self.name} selected debate sharpens the unresolved risk."
        if phase == "critique_pair":
            return f"[DISAGREE] {self.name} critique pair tests the strongest candidate plan."
        return f"[PLAN] {self.name} round-robin response."

    def provider_metadata(self):
        return {
            "provider": "mock",
            "requested_live": False,
            "actual_live": False,
            "live_provider_invoked": False,
            "fallback": False,
        }


class _RateLimitedGroqSeat(_RecordingSeat):
    def __init__(self):
        super().__init__("Groq")

    def ask(self, prompt, context):
        self.prompts.append(prompt)
        self.contexts.append(dict(context))
        return "[RISK] Groq live seat unavailable; falling back to mock Groq. [DATA] fallback_reason=Groq rate limited (429)."

    def provider_metadata(self):
        return {
            "provider": "mock",
            "requested_live": True,
            "actual_live": False,
            "live_provider_invoked": True,
            "fallback": True,
            "fallback_from": "groq",
            "fallback_reason": "Groq rate limited (429)",
        }


class _LiveThenFallbackSeat(_RecordingSeat):
    def __init__(self, name, *, provider, model, fallback_reason):
        super().__init__(name)
        self.provider = provider
        self.model = model
        self.fallback_reason = fallback_reason
        self.turns = 0

    def ask(self, prompt, context):
        self.turns += 1
        self.prompts.append(prompt)
        self.contexts.append(dict(context))
        if self.turns == 1:
            return f"[CLAIM] {self.name} live turn contributes provider evidence. [DATA] live provider metadata is present."
        return f"[RISK] {self.name} live seat unavailable; falling back to mock. [DATA] fallback_reason={self.fallback_reason}."

    def provider_metadata(self):
        if self.turns == 1:
            return {
                "provider": self.provider,
                "requested_live": True,
                "actual_live": True,
                "live_provider_invoked": True,
                "fallback": False,
                "model": self.model,
            }
        return {
            "provider": "mock",
            "requested_live": True,
            "actual_live": False,
            "live_provider_invoked": True,
            "fallback": True,
            "fallback_from": self.provider,
            "fallback_reason": self.fallback_reason,
            "model": self.model,
        }


class _ContinuityOkGptSeat(_RecordingSeat):
    def __init__(self):
        super().__init__("GPT")

    def ask(self, prompt, context):
        self.prompts.append(prompt)
        self.contexts.append(dict(context))
        return "[CLAIM] GPT browser live turn preserved continuity. [DATA] continuity marker was accepted."

    def provider_metadata(self):
        return {
            "provider": "gpt-browser",
            "requested_live": True,
            "actual_live": True,
            "live_provider_invoked": True,
            "fallback": False,
            "model": "GPT-5.5",
            "continuity": {"ok": True, "status": "ok", "detail": "ok"},
        }


def test_council_disabled_by_default(tmp_path):
    ctx = CouncilContextPack.for_task("plan a thing", work_dir=Path.cwd())
    result = CouncilRunner(CouncilConfig(output_dir=str(tmp_path))).run(ctx)
    assert result.brief is None
    assert result.messages == []
    assert result.skipped_reason == "pre-execution council disabled"


def test_from_config_respects_enable_flag(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_PRE_EXECUTION_COUNCIL", False, raising=False)
    assert CouncilConfig.from_config().enabled is False
    monkeypatch.setattr(config, "ENABLE_PRE_EXECUTION_COUNCIL", True, raising=False)
    assert CouncilConfig.from_config().enabled is True


def test_mock_runner_calls_all_four_seats_and_produces_48_messages(tmp_path):
    result = run_pre_execution_council("mock council task", council_config=_enabled_config(tmp_path))
    assert result.brief is not None
    assert len(result.messages) == 48
    counts = {}
    for msg in result.messages:
        counts[msg.speaker] = counts.get(msg.speaker, 0) + 1
    assert counts == {"GPT": 12, "Gemini": 12, "Claude": 12, "Local LLM": 12}
    assert all(msg.provider_metadata["provider"] == "mock" for msg in result.messages)
    assert all(msg.provider_metadata["live_provider_invoked"] is False for msg in result.messages)


def test_transcript_is_multi_turn_not_one_answer_per_model(tmp_path):
    result = run_pre_execution_council("multi turn task", council_config=_enabled_config(tmp_path))
    by_speaker = {}
    for msg in result.messages:
        by_speaker.setdefault(msg.speaker, []).append(msg.turn_index)
    assert all(len(turns) > 1 for turns in by_speaker.values())
    assert [msg.speaker for msg in result.messages[:8]] == [
        "GPT",
        "Gemini",
        "Claude",
        "Local LLM",
        "GPT",
        "Gemini",
        "Claude",
        "Local LLM",
    ]


def test_round_robin_remains_default_conversation_policy(tmp_path):
    cfg = _enabled_config(tmp_path, messages_per_seat=1, total_target_messages=4)
    result = run_pre_execution_council("default policy task", council_config=cfg)
    assert result.config.conversation_policy == "round_robin"
    assert [m.provider_metadata["selector_phase"] for m in result.messages] == ["round_robin"] * 4


def test_selector_mode_must_be_explicitly_enabled(tmp_path):
    default_result = run_pre_execution_council(
        "selector not implicit task",
        council_config=_enabled_config(tmp_path / "default", messages_per_seat=1, total_target_messages=4),
    )
    selector_result = run_pre_execution_council(
        "selector explicit task",
        council_config=_enabled_config(
            tmp_path / "selector",
            conversation_policy="selector",
            selector_debate_rounds=1,
            messages_per_seat=1,
            total_target_messages=4,
        ),
    )
    assert {m.provider_metadata["selector_phase"] for m in default_result.messages} == {"round_robin"}
    assert "independent_memo" in {m.provider_metadata["selector_phase"] for m in selector_result.messages}


def test_selector_mode_runs_memos_subset_debate_and_critique_pair(tmp_path):
    seats = [_RecordingSeat(name) for name in ("GPT", "Gemini", "Claude", "Local LLM")]
    cfg = _enabled_config(
        tmp_path,
        conversation_policy="selector",
        selector_debate_rounds=1,
        messages_per_seat=9,
        total_target_messages=99,
    )
    ctx = CouncilContextPack.for_task("selector phase task", work_dir=Path.cwd())
    result = CouncilRunner(cfg, seats=seats).run(ctx)
    phases = [m.provider_metadata["selector_phase"] for m in result.messages]
    assert phases[:4] == ["independent_memo"] * 4
    assert phases.count("selected_debate") == 2
    assert phases.count("critique_pair") == 2
    assert len(result.messages) == 8
    assert {m.speaker for m in result.messages[4:6]} != {seat.name for seat in seats}
    assert result.brief is not None
    result.brief.validate_required_fields()


def test_selector_prompts_are_targeted_not_full_raw_transcript(tmp_path):
    seats = [_RecordingSeat(name) for name in ("GPT", "Gemini", "Claude", "Local LLM")]
    cfg = _enabled_config(tmp_path, conversation_policy="selector", selector_debate_rounds=1)
    ctx = CouncilContextPack.for_task("selector prompt task", work_dir=Path.cwd())
    CouncilRunner(cfg, seats=seats).run(ctx)
    all_prompts = "\n\n---PROMPT---\n\n".join(prompt for seat in seats for prompt in seat.prompts)
    assert "Conversation policy: selector_v1" in all_prompts
    assert "Targeted challenge:" in all_prompts
    assert "Current compact council state:" in all_prompts
    assert "Do not assume you have the full raw transcript" in all_prompts
    debate_prompts = [
        prompt
        for seat in seats
        for prompt, ctx in zip(seat.prompts, seat.contexts)
        if ctx.get("selector_phase") == "selected_debate"
    ]
    assert debate_prompts
    for prompt in debate_prompts:
        recent = prompt.split("Recent transcript:", 1)[1].split("Current compact council state:", 1)[0]
        assert recent.count("independent memo preserves a unique") < 4


def test_selector_logs_policy_metadata(tmp_path):
    cfg = _enabled_config(
        tmp_path,
        conversation_policy="selector",
        selector_debate_rounds=1,
        messages_per_seat=1,
        total_target_messages=4,
    )
    result = run_pre_execution_council("selector metadata task", council_config=cfg)
    metadata = json.loads((Path(result.log_dir) / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["conversation_policy"] == "selector"
    assert metadata["selector_debate_rounds"] == 1
    assert metadata["selector_phases"] == [
        "independent_memo",
        "compression",
        "selected_debate",
        "critique_pair",
        "final_brief",
    ]


def test_selector_avoids_groq_for_critique_pair_after_recent_429(tmp_path):
    seats = [_RecordingSeat("GPT"), _RecordingSeat("Gemini"), _RecordingSeat("Claude"), _RecordingSeat("Local LLM"), _RateLimitedGroqSeat()]
    cfg = _enabled_config(
        tmp_path,
        conversation_policy="selector",
        selector_debate_rounds=1,
        messages_per_seat=1,
        total_target_messages=5,
    )
    ctx = CouncilContextPack.for_task("selector groq budget task", work_dir=Path.cwd())
    result = CouncilRunner(cfg, seats=seats).run(ctx)
    critique = [m for m in result.messages if m.provider_metadata["selector_phase"] == "critique_pair"]
    assert critique
    assert not any(m.speaker == "Groq" for m in critique)
    metadata = json.loads((Path(result.log_dir) / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["provider_budget_state"]["groq"]["recent_429"] is True
    assert metadata["provider_budget_state"]["groq"]["preferred_for_next_turn"] is False


def test_compare_metric_line_reports_artifact_quality_fields(tmp_path):
    result = run_pre_execution_council(
        "compare helper task",
        council_config=_enabled_config(tmp_path, messages_per_seat=1, total_target_messages=4),
    )
    line = _metric_line("round_robin", result)
    assert line.startswith("round_robin\t")
    assert "messages=" in line
    assert "warnings=" in line
    assert "disagreements=" in line
    assert "prompt_chars=" in line
    assert "brief_chars=" in line
    assert "first_slice=" in line


def _write_quality_report_run(tmp_path, name, *, policy, first_slice, provider_summaries=None, warnings=None, messages=None):
    run_dir = tmp_path / name
    run_dir.mkdir()
    (run_dir / "metadata.json").write_text(
        json.dumps(
            {
                "conversation_policy": policy,
                "warnings": warnings or [],
            }
        ),
        encoding="utf-8",
    )
    brief = {
        "recommended_first_execution_slice": first_slice,
        "implementation_prompt_export": first_slice,
        "disagreements_between_agents": ["[DISAGREE] one"] if "selector" in policy else [],
        "provider_run_summaries": provider_summaries or [],
    }
    (run_dir / "brief.json").write_text(json.dumps(brief), encoding="utf-8")
    (run_dir / "brief.md").write_text(f"# Brief\n{first_slice}\n", encoding="utf-8")
    rows = messages or [
        {
            "speaker": "GPT",
            "prompt_excerpt": "x" * 10,
            "content": "[CLAIM] compact",
        }
    ]
    (run_dir / "transcript.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    return run_dir


def test_quality_report_summarizes_comparison_and_live_diversity(tmp_path):
    mock_round = _write_quality_report_run(tmp_path, "mock_round", policy="round_robin", first_slice="Mock core")
    mock_selector = _write_quality_report_run(tmp_path, "mock_selector", policy="selector", first_slice="Mock core")
    live_selector = _write_quality_report_run(
        tmp_path,
        "live_selector",
        policy="selector",
        first_slice="Tighten CouncilBrief synthesis for mixed live/mock runs",
        provider_summaries=[
            {
                "seat_name": "Cloudflare",
                "last_provider_state": "fully_live",
                "actual_live_any": True,
                "actual_live_turn_count": 1,
                "fallback_turn_count": 0,
                "models_used": ["@cf/meta/llama-3.1-8b-instruct-fp8-fast"],
            }
        ],
        messages=[
            {
                "speaker": "Cloudflare",
                "prompt_excerpt": "x" * 20,
                "content": "[RISK] Cloudflare adds latency and cost critique.",
            }
        ],
    )
    report = build_report(
        [
            type("Comparison", (), {"label": "mock", "round_robin": load_run("mock_round", mock_round), "selector": load_run("mock_selector", mock_selector)})(),
            type("Comparison", (), {"label": "live", "round_robin": load_run("live_round", mock_round), "selector": load_run("live_selector", live_selector)})(),
        ],
        [],
    )
    assert "Council Quality Evaluation Report v1" in report
    assert "live_diversity_helped: yes" in report
    assert "Cloudflare participated live" in report
    assert "recommended_next_slice" in report


def test_compare_defaults_to_mock_only_even_when_env_live_flags_are_set(monkeypatch):
    monkeypatch.setattr(config, "PRE_EXECUTION_COUNCIL_LIVE_GEMINI_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "PRE_EXECUTION_COUNCIL_LIVE_GROQ_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "PRE_EXECUTION_COUNCIL_LIVE_GPT_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "PRE_EXECUTION_COUNCIL_LIVE_LOCAL_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "PRE_EXECUTION_COUNCIL_LIVE_CLOUDFLARE_ENABLED", True, raising=False)
    args = _compare_parse_args(["--task", "compare safety"])
    cfg = _compare_config(args, policy="selector")
    assert cfg.live_gpt_enabled is False
    assert cfg.live_gemini_enabled is False
    assert cfg.live_groq_enabled is False
    assert cfg.live_local_enabled is False
    assert cfg.live_cloudflare_enabled is False


def test_compare_allows_only_explicit_live_provider_flags(monkeypatch):
    monkeypatch.setattr(config, "PRE_EXECUTION_COUNCIL_LIVE_GPT_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "PRE_EXECUTION_COUNCIL_LIVE_LOCAL_ENABLED", True, raising=False)
    args = _compare_parse_args(["--task", "compare live", "--live-gemini", "--live-groq", "--live-cloudflare"])
    cfg = _compare_config(args, policy="selector")
    assert cfg.live_gpt_enabled is False
    assert cfg.live_gemini_enabled is True
    assert cfg.live_groq_enabled is True
    assert cfg.live_local_enabled is False
    assert cfg.live_cloudflare_enabled is True


def test_compare_mock_only_overrides_explicit_live_flags():
    args = _compare_parse_args(["--task", "compare mock", "--mock-only", "--live-gemini", "--live-groq", "--live-cloudflare"])
    cfg = _compare_config(args, policy="selector")
    assert cfg.live_gemini_enabled is False
    assert cfg.live_groq_enabled is False
    assert cfg.live_cloudflare_enabled is False


def test_prompt_hierarchy_context_version_and_compact_protocol_are_included(tmp_path):
    result = run_pre_execution_council("prompt hierarchy task", council_config=_enabled_config(tmp_path))
    prompt = result.messages[0].prompt_excerpt
    assert "Prompt version: pre_execution_council_v0" in prompt
    assert "You are participating in a pre-execution council" in prompt
    assert "Run composition:" in prompt
    assert "Pre-execution means no implementation or orchestration mutation. It does not mean providers are mocked." in prompt
    assert "Run type: mock-only council." in prompt
    assert "Live requested seats: (none)." in prompt
    assert "live providers disabled in v0" not in prompt
    assert "You are the GPT seat" in prompt
    assert "Context pack summary:" in prompt
    assert "Current compact council state:" in prompt
    assert "Unresolved disagreements:" in prompt
    assert "[CLAIM]" in prompt
    assert "Do not be polite" in prompt
    assert "Do not write filler" in prompt


def test_gpt_live_prompt_includes_structured_continuity_instruction(tmp_path):
    captured = {}

    def fake_send(**kwargs):
        captured.update(kwargs)
        line = _last_continuity_line(kwargs["prompt"])
        return (
            f"{line}\n"
            "[CLAIM] GPT acknowledges the structured continuity marker. "
            "[PLAN] Keep the same chat thread for the whole council run."
        )

    cfg = _enabled_config(
        tmp_path,
        live_gpt_enabled=True,
        gpt_project_url="https://chatgpt.com/g/example/project",
        gpt_model="GPT-5.5",
        gpt_reasoning="Medium",
        messages_per_seat=1,
        total_target_messages=4,
    )
    ctx = CouncilContextPack.for_task("continuity prompt task", work_dir=Path.cwd())
    CouncilRunner(cfg, gpt_send_fn=fake_send).run(ctx)
    assert "Required structured continuity line" in captured["prompt"]
    assert "[CONTINUITY]" in captured["prompt"]
    assert '"seat":"GPT"' in captured["prompt"]


def test_temporary_hats_are_deterministic(tmp_path):
    ctx = CouncilContextPack.for_task("mock v0 prompt test gate", work_dir=Path.cwd())
    first = CouncilRunner(_enabled_config(tmp_path)).run(ctx)
    second = CouncilRunner(_enabled_config(tmp_path)).run(ctx)
    first_hats = {m.speaker: m.temporary_hats for m in first.messages[:4]}
    second_hats = {m.speaker: m.temporary_hats for m in second.messages[:4]}
    assert first_hats == second_hats
    assert all(hats for hats in first_hats.values())


def test_compact_state_updates_during_run(tmp_path):
    result = run_pre_execution_council("compact state task", council_config=_enabled_config(tmp_path))
    assert result.compact_state["claims"]
    assert result.compact_state["risks"]
    assert result.compact_state["plans"]
    assert result.compact_state["actions"]


def test_mock_output_is_not_repeating_after_first_round(tmp_path):
    result = run_pre_execution_council("quality review task", council_config=_enabled_config(tmp_path))
    repetition_warnings = [w for w in result.warnings if w.kind == "repetition"]
    assert repetition_warnings == []
    gpt_messages = [m.content for m in result.messages if m.speaker == "GPT"]
    assert len(set(gpt_messages)) == 12


def test_filler_like_messages_record_quality_warnings():
    msg = CouncilMessage(
        run_id="r",
        speaker="GPT",
        model_name="mock-gpt",
        permanent_seat="GPT",
        temporary_hats=[],
        turn_index=1,
        content="I agree.",
        compact_tags=[],
        timestamp="now",
    )
    warnings = evaluate_message_quality(msg)
    kinds = {w.kind for w in warnings}
    assert "filler" in kinds
    assert "too_short" in kinds
    assert "missing_tags" in kinds


def test_final_brief_contains_required_fields_and_implementation_prompt_export(tmp_path):
    result = run_pre_execution_council("brief schema task", council_config=_enabled_config(tmp_path))
    brief = result.brief
    assert brief is not None
    brief.validate_required_fields()
    assert brief.implementation_prompt_export
    assert "mock-only Pre-Execution Council v0" in brief.implementation_prompt_export
    assert brief.actionable_next_command_or_task_prompt == brief.implementation_prompt_export
    assert brief.transcript_path == result.transcript_path


def test_logging_writes_redacted_json_and_markdown_artifacts(tmp_path):
    task = "task with api_key=supersecret and --user-data-dir C:\\9to5\\state\\chatgpt_profile_recon"
    result = run_pre_execution_council(task, council_config=_enabled_config(tmp_path))
    assert result.log_dir
    log_dir = Path(result.log_dir)
    for name in ("context_pack.json", "config.json", "metadata.json", "transcript.jsonl", "transcript.md", "brief.json", "brief.md"):
        assert (log_dir / name).exists()
    blob = "\n".join(p.read_text(encoding="utf-8") for p in log_dir.iterdir() if p.is_file())
    assert "supersecret" not in blob
    assert "--user-data-dir" not in blob
    assert "chatgpt_profile_recon" not in blob
    metadata = json.loads((log_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["prompt_version"] == "pre_execution_council_v0"
    assert metadata["mock_only"] is True
    assert metadata["run_composition_summary"]["run_type"] == "mock-only council"
    assert metadata["run_composition_summary"]["live_requested_seats"] == []


def test_run_composition_summary_formats_mixed_runs_without_mock_only_run_label():
    summary = RunCompositionSummary(
        execution_mode="pre-execution",
        conversation_policy="selector",
        run_type="mixed/live-capable council",
        enabled_seats=["GPT", "Gemini", "Claude"],
        live_requested_seats=["GPT"],
        pending_live_seats=[],
        actual_live_seats=["GPT"],
        fallback_seats=["Gemini"],
        mock_only_seats=["Claude"],
        quota_limited_seats=[],
        rate_limited_seats=["Gemini"],
        unavailable_seats=[],
        provider_health_summary=["Fully live seats: GPT.", "Rate limit observed: Gemini."],
    )
    block = summary.to_prompt_block()
    assert "pre-execution council" in block
    assert "It does not mean providers are mocked." in block
    assert "Run type: mixed/live-capable council." in block
    assert "Run type: mock-only council." not in block
    assert "Live requested seats: GPT." in block
    assert "Live requested but not yet called seats: (none)." in block
    assert "Actual live seats so far: GPT." in block
    assert "Mocked/control seats in this run: Claude." in block


def test_live_requested_provider_forbidden_actions_are_filtered_from_prompt_context(tmp_path):
    seats = [
        _RecordingSeat("GPT"),
        _RecordingSeat("Gemini"),
        _RecordingSeat("Claude"),
        _RecordingSeat("Local LLM"),
        _RecordingSeat("Groq"),
        _RecordingSeat("Cloudflare"),
    ]
    cfg = _enabled_config(
        tmp_path,
        live_groq_enabled=True,
        live_cloudflare_enabled=True,
        messages_per_seat=1,
        total_target_messages=6,
    )
    result = CouncilRunner(cfg, seats=seats).run(
        CouncilContextPack.for_task(
            "filter live requested provider constraints",
            work_dir=Path.cwd(),
            forbidden_actions=[
                "Do not call ChatGPT browser driver.",
                "Do not call Gemini.",
                "Do not call Claude Code.",
                "Do not call local LLM/Ollama.",
                "Do not call Groq.",
                "Do not call Cloudflare Workers AI.",
                "Do not wire into orchestration.",
            ],
        )
    )
    prompt = result.messages[0].prompt_excerpt
    assert "Do not call Groq." not in prompt
    assert "Do not call Cloudflare Workers AI." not in prompt
    assert "Do not wire into orchestration." in prompt
    assert "explicitly requested live council seats: Cloudflare, Groq" in prompt


def test_redactor_removes_secrets_and_sensitive_runtime_details():
    text = "api_key=abc123 --remote-debugging-port=9222 C:\\9to5\\state\\chatgpt_profile_recon"
    out = redact_council_text(text)
    assert "abc123" not in out
    assert "--remote-debugging-port" not in out
    assert "chatgpt_profile_recon" not in out


def test_no_live_provider_flags_are_enabled_by_default(tmp_path):
    cfg = _enabled_config(tmp_path)
    assert cfg.live_gpt_enabled is False
    assert cfg.live_gemini_enabled is False
    assert cfg.live_claude_enabled is False
    assert cfg.live_local_enabled is False
    assert cfg.live_groq_enabled is False
    assert cfg.live_cloudflare_enabled is False
    result = run_pre_execution_council("provider safety task", council_config=cfg)
    assert all(m.provider_metadata["live_provider_invoked"] is False for m in result.messages)


def test_gpt_browser_seat_remains_disabled_unless_later_live_flag_enabled(tmp_path):
    cfg = _enabled_config(tmp_path, live_gpt_enabled=False)
    result = run_pre_execution_council("browser seat should remain mocked", council_config=cfg)
    assert result.config.live_gpt_enabled is False
    assert all(m.model_name != "chatgpt-browser" for m in result.messages)
    assert all(m.provider_metadata["provider"] == "mock" for m in result.messages)
    assert all(m.provider_metadata["requested_live"] is False for m in result.messages)


def test_gpt_metadata_is_explicit_for_mock_seat(tmp_path):
    result = run_pre_execution_council("mock metadata task", council_config=_enabled_config(tmp_path, messages_per_seat=1, total_target_messages=4))
    gpt = next(m for m in result.messages if m.speaker == "GPT")
    assert gpt.provider_metadata["provider"] == "mock"
    assert gpt.provider_metadata["requested_live"] is False
    assert gpt.provider_metadata["actual_live"] is False
    assert gpt.provider_metadata["fallback"] is False


def test_gemini_live_missing_key_falls_back_to_mock_with_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "", raising=False)
    cfg = _enabled_config(tmp_path, live_gemini_enabled=True, messages_per_seat=1, total_target_messages=4)
    result = run_pre_execution_council("gemini fallback task", council_config=cfg)
    gemini = next(m for m in result.messages if m.speaker == "Gemini")
    assert gemini.provider_metadata["provider"] == "mock"
    assert gemini.provider_metadata["requested_live"] is True
    assert gemini.provider_metadata["actual_live"] is False
    assert gemini.provider_metadata["fallback_from"] == "gemini"
    assert gemini.provider_metadata["fallback"] is True
    assert "GEMINI_API_KEY missing" in gemini.provider_metadata["fallback_reason"]
    assert "falling back to mock Gemini" in gemini.content


class _FakeGeminiSession:
    def __init__(self):
        self.started = False
        self.prompts = []

    def start_run_conversation(self, goal, task_id):
        self.started = True
        self.goal = goal
        self.task_id = task_id

    def ask(self, prompt, expect_json=False):
        self.prompts.append(prompt)
        return "[CLAIM] Live Gemini adds an alternative option. [RISK] Keep only Gemini live in this mixed council."


def test_gemini_live_seat_can_run_with_fake_session(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "AIzaFAKEKEY_FOR_TEST_ONLY_1234567890", raising=False)
    fake = _FakeGeminiSession()
    cfg = _enabled_config(tmp_path, live_gemini_enabled=True, messages_per_seat=1, total_target_messages=4)
    ctx = CouncilContextPack.for_task("gemini live task", work_dir=Path.cwd())
    result = CouncilRunner(cfg, gemini_session_factory=lambda: fake).run(ctx)
    gemini = next(m for m in result.messages if m.speaker == "Gemini")
    assert fake.started is True
    assert fake.prompts
    assert gemini.provider_metadata["provider"] == "gemini"
    assert gemini.provider_metadata["fallback"] is False
    assert gemini.provider_metadata["live_provider_invoked"] is True
    assert "Live Gemini adds an alternative option" in gemini.content
    assert all(m.provider_metadata["provider"] == "mock" for m in result.messages if m.speaker != "Gemini")


def test_gemini_live_logs_redact_key_on_provider_error(tmp_path, monkeypatch):
    class BadSession(_FakeGeminiSession):
        def ask(self, prompt, expect_json=False):
            raise RuntimeError("API key AIzaSHOULD_NOT_LEAK_12345678901234567890 quota exhausted")

    monkeypatch.setattr(config, "GEMINI_API_KEY", "AIzaSHOULD_NOT_LEAK_12345678901234567890", raising=False)
    cfg = _enabled_config(tmp_path, live_gemini_enabled=True, messages_per_seat=1, total_target_messages=4)
    ctx = CouncilContextPack.for_task("gemini redaction task", work_dir=Path.cwd())
    result = CouncilRunner(cfg, gemini_session_factory=BadSession).run(ctx)
    blob = "\n".join(p.read_text(encoding="utf-8") for p in Path(result.log_dir).iterdir() if p.is_file())
    assert "AIzaSHOULD_NOT_LEAK" not in blob
    gemini = next(m for m in result.messages if m.speaker == "Gemini")
    assert gemini.provider_metadata["fallback"] is True


def test_local_env_alias_enables_local_flag(monkeypatch):
    monkeypatch.setattr(config, "PRE_EXECUTION_COUNCIL_LIVE_LOCAL_ENABLED", True, raising=False)
    assert CouncilConfig.from_config().live_local_enabled is True


def test_gpt_env_alias_enables_gpt_browser_flag(monkeypatch):
    monkeypatch.setattr(config, "PRE_EXECUTION_COUNCIL_LIVE_GPT_ENABLED", True, raising=False)
    assert CouncilConfig.from_config().live_gpt_enabled is True


def test_local_live_unavailable_endpoint_falls_back_to_mock(tmp_path):
    def unavailable(_prompt, _model):
        raise RuntimeError("connection refused")

    cfg = _enabled_config(
        tmp_path,
        live_local_enabled=True,
        local_model="test-local-model",
        messages_per_seat=1,
        total_target_messages=4,
    )
    ctx = CouncilContextPack.for_task("local fallback task", work_dir=Path.cwd())
    result = CouncilRunner(cfg, local_transport=unavailable).run(ctx)
    local = next(m for m in result.messages if m.speaker == "Local LLM")
    assert local.provider_metadata["provider"] == "mock"
    assert local.provider_metadata["requested_live"] is True
    assert local.provider_metadata["actual_live"] is False
    assert local.provider_metadata["fallback_from"] == "local"
    assert local.provider_metadata["fallback"] is True
    assert "connection refused" in local.provider_metadata["fallback_reason"]
    assert "falling back to mock Local LLM" in local.content


def test_local_live_seat_can_run_with_fake_transport(tmp_path):
    calls = []

    def fake_transport(prompt, model):
        calls.append((prompt, model))
        return "[DISAGREE] Local live critique catches overbuilt provider sequencing. [RISK] Endpoint failures must degrade."

    cfg = _enabled_config(
        tmp_path,
        live_local_enabled=True,
        local_model="local-test",
        messages_per_seat=1,
        total_target_messages=4,
    )
    ctx = CouncilContextPack.for_task("local live task", work_dir=Path.cwd())
    result = CouncilRunner(cfg, local_transport=fake_transport).run(ctx)
    local = next(m for m in result.messages if m.speaker == "Local LLM")
    assert calls and calls[0][1] == "local-test"
    assert local.provider_metadata["provider"] == "local"
    assert local.provider_metadata["runtime"] == "ollama-compatible-http"
    assert local.provider_metadata["fallback"] is False
    assert local.provider_metadata["live_provider_invoked"] is True
    assert "Local live critique catches overbuilt" in local.content
    assert all(m.provider_metadata["provider"] == "mock" for m in result.messages if m.speaker != "Local LLM")


def test_groq_env_alias_enables_groq_flag(monkeypatch):
    monkeypatch.setattr(config, "PRE_EXECUTION_COUNCIL_LIVE_GROQ_ENABLED", True, raising=False)
    assert CouncilConfig.from_config().live_groq_enabled is True


def test_groq_disabled_by_default_in_seat_set(tmp_path):
    result = run_pre_execution_council("groq disabled task", council_config=_enabled_config(tmp_path))
    assert {m.speaker for m in result.messages} == {"GPT", "Gemini", "Claude", "Local LLM"}
    assert len(result.messages) == 48


def test_groq_enabled_uses_five_seats_and_sixty_message_target(tmp_path):
    cfg = _enabled_config(tmp_path, live_groq_enabled=True, messages_per_seat=12, total_target_messages=48)
    result = run_pre_execution_council("groq five-seat task", council_config=cfg)
    assert len(result.messages) == 60
    assert {m.speaker for m in result.messages} == {"GPT", "Gemini", "Claude", "Local LLM", "Groq"}


def test_groq_live_missing_key_falls_back_to_mock_with_safe_metadata(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    cfg = _enabled_config(tmp_path, live_groq_enabled=True, messages_per_seat=1, total_target_messages=5)
    result = run_pre_execution_council("groq fallback task", council_config=cfg)
    groq = next(m for m in result.messages if m.speaker == "Groq")
    assert groq.provider_metadata["provider"] == "mock"
    assert groq.provider_metadata["requested_live"] is True
    assert groq.provider_metadata["actual_live"] is False
    assert groq.provider_metadata["fallback_from"] == "groq"
    assert groq.provider_metadata["fallback"] is True
    assert "GROQ_API_KEY missing" in groq.provider_metadata["fallback_reason"]
    assert "groq-test-key" not in groq.content
    assert "GROQ_API_KEY" not in groq.provider_metadata


class _FakeGroqClient:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def urlopen(self, req, timeout=0):
        self.calls.append((req, timeout))
        class _Resp:
            def __init__(self, body):
                self._body = body
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return self._body
        return _Resp(json.dumps({"choices": [{"message": {"content": self.reply}}]}).encode("utf-8"))


class _FallbackGroqClient:
    def __init__(self):
        self.models = []

    def urlopen(self, req, timeout=0):
        payload = json.loads(req.data.decode("utf-8"))
        model = payload["model"]
        self.models.append(model)
        if model == "qwen/qwen3-32b":
            raise urllib.error.HTTPError("https://api.groq.com", 403, "permission", {}, None)

        class _Resp:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": "[CLAIM] Fallback Groq model is live. [RISK] Primary model access can vary by org."
                                }
                            }
                        ]
                    }
                ).encode("utf-8")

        return _Resp()


def test_groq_live_seat_can_run_with_fake_response(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "groq-test-key")
    fake = _FakeGroqClient("[CLAIM] Groq adds a distinct open-model critique. [RISK] Keep it gated.")
    monkeypatch.setattr("agents.planning.pre_execution_council.urllib.request.urlopen", fake.urlopen)
    cfg = _enabled_config(tmp_path, live_groq_enabled=True, groq_model="qwen/qwen3-32b", messages_per_seat=1, total_target_messages=5)
    result = CouncilRunner(cfg).run(CouncilContextPack.for_task("groq live task", work_dir=Path.cwd()))
    groq = next(m for m in result.messages if m.speaker == "Groq")
    assert groq.provider_metadata["provider"] == "groq"
    assert groq.provider_metadata["actual_live"] is True
    assert groq.provider_metadata["fallback"] is False
    assert groq.provider_metadata["model"] == "qwen/qwen3-32b"
    assert "distinct open-model critique" in groq.content
    blob = "\n".join(p.read_text(encoding="utf-8") for p in Path(result.log_dir).iterdir() if p.is_file())
    assert "groq-test-key" not in blob
    assert "Authorization" not in blob


def test_groq_permission_failure_tries_fallback_model_before_mock(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "groq-test-key")
    fake = _FallbackGroqClient()
    monkeypatch.setattr("agents.planning.pre_execution_council.urllib.request.urlopen", fake.urlopen)
    cfg = _enabled_config(
        tmp_path,
        live_groq_enabled=True,
        groq_model="qwen/qwen3-32b",
        groq_fallback_models="llama-3.1-8b-instant,openai/gpt-oss-20b",
        messages_per_seat=1,
        total_target_messages=5,
    )
    result = CouncilRunner(cfg).run(CouncilContextPack.for_task("groq fallback chain task", work_dir=Path.cwd()))
    groq = next(m for m in result.messages if m.speaker == "Groq")
    assert fake.models == ["qwen/qwen3-32b", "llama-3.1-8b-instant"]
    assert groq.provider_metadata["provider"] == "groq"
    assert groq.provider_metadata["actual_live"] is True
    assert groq.provider_metadata["model"] == "llama-3.1-8b-instant"
    assert groq.provider_metadata["attempted_models"] == "qwen/qwen3-32b,llama-3.1-8b-instant"
    assert "Fallback Groq model is live" in groq.content


def test_groq_rate_limit_falls_back_safely(tmp_path, monkeypatch):
    def boom(*_args, **_kwargs):
        raise urllib.error.HTTPError("https://api.groq.com", 429, "rate limit", {}, None)

    monkeypatch.setenv("GROQ_API_KEY", "groq-test-key")
    monkeypatch.setattr("agents.planning.pre_execution_council.urllib.request.urlopen", boom)
    cfg = _enabled_config(tmp_path, live_groq_enabled=True, messages_per_seat=1, total_target_messages=5)
    result = CouncilRunner(cfg).run(CouncilContextPack.for_task("groq rate limit task", work_dir=Path.cwd()))
    groq = next(m for m in result.messages if m.speaker == "Groq")
    assert groq.provider_metadata["provider"] == "mock"
    assert groq.provider_metadata["fallback_from"] == "groq"
    assert groq.provider_metadata["actual_live"] is False
    assert "429" in groq.provider_metadata["fallback_reason"]
    assert groq.provider_metadata["attempted_models"] == "qwen/qwen3-32b"


def test_groq_empty_response_falls_back_safely(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "groq-test-key")
    fake = _FakeGroqClient("")
    monkeypatch.setattr("agents.planning.pre_execution_council.urllib.request.urlopen", fake.urlopen)
    cfg = _enabled_config(tmp_path, live_groq_enabled=True, messages_per_seat=1, total_target_messages=5)
    result = CouncilRunner(cfg).run(CouncilContextPack.for_task("groq empty response task", work_dir=Path.cwd()))
    groq = next(m for m in result.messages if m.speaker == "Groq")
    assert groq.provider_metadata["provider"] == "mock"
    assert groq.provider_metadata["actual_live"] is False
    assert "returned no text" in groq.provider_metadata["fallback_reason"]
    assert "groq-test-key" not in groq.content


def test_groq_malformed_response_falls_back_safely(tmp_path, monkeypatch):
    class BadGroqClient:
        def urlopen(self, req, timeout=0):
            class _Resp:
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    return False
                def read(self):
                    return b'{"unexpected": true}'
            return _Resp()

    monkeypatch.setenv("GROQ_API_KEY", "groq-test-key")
    monkeypatch.setattr("agents.planning.pre_execution_council.urllib.request.urlopen", BadGroqClient().urlopen)
    cfg = _enabled_config(tmp_path, live_groq_enabled=True, messages_per_seat=1, total_target_messages=5)
    result = CouncilRunner(cfg).run(CouncilContextPack.for_task("groq malformed response task", work_dir=Path.cwd()))
    groq = next(m for m in result.messages if m.speaker == "Groq")
    assert groq.provider_metadata["provider"] == "mock"
    assert groq.provider_metadata["actual_live"] is False
    assert "malformed response" in groq.provider_metadata["fallback_reason"]
    blob = "\n".join(p.read_text(encoding="utf-8") for p in Path(result.log_dir).iterdir() if p.is_file())
    assert "groq-test-key" not in blob


def test_cloudflare_env_alias_enables_cloudflare_flag(monkeypatch):
    monkeypatch.setattr(config, "PRE_EXECUTION_COUNCIL_LIVE_CLOUDFLARE_ENABLED", True, raising=False)
    assert CouncilConfig.from_config().live_cloudflare_enabled is True


def test_cloudflare_disabled_by_default_in_seat_set(tmp_path):
    result = run_pre_execution_council("cloudflare disabled task", council_config=_enabled_config(tmp_path))
    assert {m.speaker for m in result.messages} == {"GPT", "Gemini", "Claude", "Local LLM"}
    assert len(result.messages) == 48


def test_cloudflare_enabled_uses_extra_seat_and_message_target(tmp_path):
    cfg = _enabled_config(tmp_path, live_cloudflare_enabled=True, messages_per_seat=12, total_target_messages=48)
    result = run_pre_execution_council("cloudflare five-seat task", council_config=cfg)
    assert len(result.messages) == 60
    assert {m.speaker for m in result.messages} == {"GPT", "Gemini", "Claude", "Local LLM", "Cloudflare"}


def test_cloudflare_live_missing_key_falls_back_to_mock_with_safe_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account-test-id")
    monkeypatch.delenv("CLOUDFLARE_WORKER_AI_API_KEY", raising=False)
    cfg = _enabled_config(tmp_path, live_cloudflare_enabled=True, messages_per_seat=1, total_target_messages=5)
    result = run_pre_execution_council("cloudflare fallback task", council_config=cfg)
    cloudflare = next(m for m in result.messages if m.speaker == "Cloudflare")
    assert cloudflare.provider_metadata["provider"] == "mock"
    assert cloudflare.provider_metadata["requested_live"] is True
    assert cloudflare.provider_metadata["actual_live"] is False
    assert cloudflare.provider_metadata["fallback_from"] == "cloudflare"
    assert cloudflare.provider_metadata["fallback"] is True
    assert "CLOUDFLARE_WORKER_AI_API_KEY missing" in cloudflare.provider_metadata["fallback_reason"]
    assert "account-test-id" not in cloudflare.content
    assert "CLOUDFLARE_WORKER_AI_API_KEY" not in cloudflare.provider_metadata


class _FakeCloudflareClient:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def urlopen(self, req, timeout=0):
        self.calls.append((req, timeout))

        class _Resp:
            def __init__(self, body):
                self._body = body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return self._body

        return _Resp(json.dumps({"success": True, "result": {"response": self.reply}}).encode("utf-8"))


def test_cloudflare_live_seat_can_run_with_fake_response(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account-test-id")
    monkeypatch.setenv("CLOUDFLARE_WORKER_AI_API_KEY", "cloudflare-test-key")
    fake = _FakeCloudflareClient(
        "[CLAIM] Cloudflare adds an edge-hosted cost and latency critique. [RISK] Keep it gated."
    )
    monkeypatch.setattr("agents.planning.pre_execution_council.urllib.request.urlopen", fake.urlopen)
    cfg = _enabled_config(
        tmp_path,
        live_cloudflare_enabled=True,
        cloudflare_model="@cf/meta/llama-3.1-8b-instruct-fp8-fast",
        messages_per_seat=1,
        total_target_messages=5,
    )
    result = CouncilRunner(cfg).run(CouncilContextPack.for_task("cloudflare live task", work_dir=Path.cwd()))
    cloudflare = next(m for m in result.messages if m.speaker == "Cloudflare")
    assert cloudflare.provider_metadata["provider"] == "cloudflare"
    assert cloudflare.provider_metadata["actual_live"] is True
    assert cloudflare.provider_metadata["fallback"] is False
    assert cloudflare.provider_metadata["model"] == "@cf/meta/llama-3.1-8b-instruct-fp8-fast"
    assert cloudflare.provider_metadata["runtime"] == "cloudflare-workers-ai"
    assert "edge-hosted cost and latency critique" in cloudflare.content
    req, timeout = fake.calls[0]
    assert timeout == 60.0
    assert "/accounts/account-test-id/ai/run/@cf/meta/llama-3.1-8b-instruct-fp8-fast" in req.full_url
    payload = json.loads(req.data.decode("utf-8"))
    assert payload["messages"][0]["role"] == "system"
    blob = "\n".join(p.read_text(encoding="utf-8") for p in Path(result.log_dir).iterdir() if p.is_file())
    assert "cloudflare-test-key" not in blob
    assert "Authorization" not in blob


def test_cloudflare_rate_limit_falls_back_without_groq_cooldown(tmp_path, monkeypatch):
    def boom(*_args, **_kwargs):
        raise urllib.error.HTTPError("https://api.cloudflare.com", 429, "rate limit", {}, None)

    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account-test-id")
    monkeypatch.setenv("CLOUDFLARE_WORKER_AI_API_KEY", "cloudflare-test-key")
    monkeypatch.setattr("agents.planning.pre_execution_council.urllib.request.urlopen", boom)
    cfg = _enabled_config(
        tmp_path,
        live_cloudflare_enabled=True,
        conversation_policy="selector",
        messages_per_seat=1,
        total_target_messages=5,
    )
    result = CouncilRunner(cfg).run(CouncilContextPack.for_task("cloudflare rate limit task", work_dir=Path.cwd()))
    cloudflare = next(m for m in result.messages if m.speaker == "Cloudflare")
    assert cloudflare.provider_metadata["provider"] == "mock"
    assert cloudflare.provider_metadata["fallback_from"] == "cloudflare"
    assert cloudflare.provider_metadata["actual_live"] is False
    assert "429" in cloudflare.provider_metadata["fallback_reason"]
    metadata = json.loads((Path(result.log_dir) / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["provider_budget_state"]["groq"]["recent_429"] is False


def test_cloudflare_malformed_response_falls_back_safely(tmp_path, monkeypatch):
    class BadCloudflareClient:
        def urlopen(self, req, timeout=0):
            class _Resp:
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def read(self):
                    return b'{"success": true, "result": {}}'

            return _Resp()

    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account-test-id")
    monkeypatch.setenv("CLOUDFLARE_WORKER_AI_API_KEY", "cloudflare-test-key")
    monkeypatch.setattr("agents.planning.pre_execution_council.urllib.request.urlopen", BadCloudflareClient().urlopen)
    cfg = _enabled_config(tmp_path, live_cloudflare_enabled=True, messages_per_seat=1, total_target_messages=5)
    result = CouncilRunner(cfg).run(CouncilContextPack.for_task("cloudflare malformed response task", work_dir=Path.cwd()))
    cloudflare = next(m for m in result.messages if m.speaker == "Cloudflare")
    assert cloudflare.provider_metadata["provider"] == "mock"
    assert cloudflare.provider_metadata["actual_live"] is False
    assert "malformed response" in cloudflare.provider_metadata["fallback_reason"]
    blob = "\n".join(p.read_text(encoding="utf-8") for p in Path(result.log_dir).iterdir() if p.is_file())
    assert "cloudflare-test-key" not in blob


def test_future_provider_roadmap_note_does_not_create_live_behavior():
    note = Path("agents/planning/pre_execution_council_provider_roadmap.md").read_text(encoding="utf-8")
    assert "Cloudflare Workers AI" in note
    assert "GitHub Models or Cerebras" in note
    assert "xAI Grok browser" in note
    assert "Claude live" in note


def test_gemini_and_local_can_be_live_while_gpt_and_claude_stay_mocked(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "AIzaFAKEKEY_FOR_TEST_ONLY_1234567890", raising=False)
    fake_gemini = _FakeGeminiSession()

    def fake_local(_prompt, _model):
        return "[RISK] Local live dissent says keep GPT browser and Claude Code disabled."

    cfg = _enabled_config(
        tmp_path,
        live_gemini_enabled=True,
        live_local_enabled=True,
        local_model="local-test",
        messages_per_seat=1,
        total_target_messages=4,
    )
    ctx = CouncilContextPack.for_task("two live seat council", work_dir=Path.cwd())
    result = CouncilRunner(
        cfg,
        gemini_session_factory=lambda: fake_gemini,
        local_transport=fake_local,
    ).run(ctx)
    providers = {m.speaker: m.provider_metadata["provider"] for m in result.messages}
    assert providers == {"GPT": "mock", "Gemini": "gemini", "Claude": "mock", "Local LLM": "local"}
    assert result.brief is not None
    assert "Improve CouncilBrief synthesis for mixed live/mock councils" in result.brief.implementation_prompt_export
    assert any("Gemini: live via gemini" in item for item in result.brief.important_context_gathered)
    assert "Do not call Gemini." not in result.brief.constraints_do_not_do
    assert "Do not call local LLM/Ollama." not in result.brief.constraints_do_not_do


def test_gpt_browser_missing_project_url_falls_back_to_mock(tmp_path):
    cfg = _enabled_config(
        tmp_path,
        live_gpt_enabled=True,
        gpt_project_url="",
        messages_per_seat=1,
        total_target_messages=4,
    )
    ctx = CouncilContextPack.for_task("gpt browser fallback task", work_dir=Path.cwd())
    result = CouncilRunner(cfg).run(ctx)
    gpt = next(m for m in result.messages if m.speaker == "GPT")
    assert gpt.provider_metadata["provider"] == "mock"
    assert gpt.provider_metadata["requested_live"] is True
    assert gpt.provider_metadata["actual_live"] is False
    assert gpt.provider_metadata["fallback_from"] == "gpt-browser"
    assert "project URL missing" in gpt.provider_metadata["fallback_reason"]
    assert "falling back to mock GPT" in gpt.content


def test_gpt_browser_live_uses_injected_send_function(tmp_path):
    calls = []

    def fake_send(**kwargs):
        calls.append(kwargs)
        line = _last_continuity_line(kwargs["prompt"])
        return (
            f"{line}\n"
            "[CLAIM] Browser project context adds task-specific critique. "
            "[PLAN] Keep the browser seat gated and long enough to clear short-message checks."
        )

    cfg = _enabled_config(
        tmp_path,
        live_gpt_enabled=True,
        gpt_project_url="https://chatgpt.com/g/example/project",
        gpt_model="GPT-5.5",
        gpt_reasoning="Medium",
        messages_per_seat=1,
        total_target_messages=4,
    )
    ctx = CouncilContextPack.for_task("gpt browser live task", work_dir=Path.cwd())
    result = CouncilRunner(cfg, gpt_send_fn=fake_send).run(ctx)
    gpt = next(m for m in result.messages if m.speaker == "GPT")
    assert calls and calls[0]["project_url"] == "https://chatgpt.com/g/example/project"
    assert calls[0]["model"] == "GPT-5.5"
    assert calls[0]["reasoning"] == "Medium"
    assert calls[0]["new_chat"] is True
    assert calls[0]["turn"] == 1
    assert calls[0]["session_id"]
    assert gpt.provider_metadata["provider"] == "gpt-browser"
    assert gpt.provider_metadata["requested_live"] is True
    assert gpt.provider_metadata["actual_live"] is True
    assert gpt.provider_metadata["fallback"] is False
    assert gpt.provider_metadata["chat_session_id"] == calls[0]["session_id"]
    assert gpt.provider_metadata["continuity"]["ok"] is True
    assert "Browser project context adds task-specific critique" in gpt.content
    assert not any(w.kind == "continuity_degraded" for w in gpt.warnings)


def test_gpt_browser_reuses_one_chat_session_within_run(tmp_path):
    calls = []

    def fake_send(**kwargs):
        calls.append(kwargs)
        line = _last_continuity_line(kwargs["prompt"])
        return (
            f"{line}\n"
            f"[CLAIM] GPT turn {kwargs['turn']} reuses the same project chat thread. "
            "[PLAN] Keep continuity checks structural rather than free-text canaries."
        )

    cfg = _enabled_config(
        tmp_path,
        live_gpt_enabled=True,
        gpt_project_url="https://chatgpt.com/g/example/project",
        gpt_model="GPT-5.5",
        gpt_reasoning="Medium",
        messages_per_seat=2,
        total_target_messages=8,
    )
    ctx = CouncilContextPack.for_task("gpt session reuse task", work_dir=Path.cwd())
    result = CouncilRunner(cfg, gpt_send_fn=fake_send).run(ctx)
    gpt_msgs = [m for m in result.messages if m.speaker == "GPT"]
    assert len(gpt_msgs) == 2
    assert len(calls) == 2
    assert calls[0]["session_id"] == calls[1]["session_id"]
    assert calls[0]["new_chat"] is True
    assert calls[1]["new_chat"] is False
    assert [c["turn"] for c in calls] == [1, 2]
    assert gpt_msgs[0].provider_metadata["chat_session_id"] == calls[0]["session_id"]
    assert gpt_msgs[1].provider_metadata["chat_session_id"] == calls[0]["session_id"]
    assert all(m.provider_metadata["continuity"]["ok"] is True for m in gpt_msgs)


def test_gpt_browser_missing_continuity_marks_degraded_not_hallucination(tmp_path):
    def fake_send(**_kwargs):
        return (
            "[CLAIM] Browser seat replied without the structured continuity marker. "
            "[RISK] Treat this as continuity degraded, not proof the model hallucinated."
        )

    cfg = _enabled_config(
        tmp_path,
        live_gpt_enabled=True,
        gpt_project_url="https://chatgpt.com/g/example/project",
        gpt_model="GPT-5.5",
        gpt_reasoning="Medium",
        messages_per_seat=1,
        total_target_messages=4,
    )
    ctx = CouncilContextPack.for_task("gpt continuity degraded task", work_dir=Path.cwd())
    result = CouncilRunner(cfg, gpt_send_fn=fake_send).run(ctx)
    gpt = next(m for m in result.messages if m.speaker == "GPT")
    assert gpt.provider_metadata["provider"] == "gpt-browser"
    assert gpt.provider_metadata["continuity"]["ok"] is False
    assert gpt.provider_metadata["continuity"]["status"] == "degraded"
    assert any(w.kind == "continuity_degraded" for w in gpt.warnings)


def test_gpt_browser_failure_falls_back_with_safe_metadata(tmp_path):
    def boom(**_kwargs):
        raise RuntimeError("browser failed while using --remote-debugging-port=9222")

    cfg = _enabled_config(
        tmp_path,
        live_gpt_enabled=True,
        gpt_project_url="https://chatgpt.com/g/example/project",
        gpt_model="GPT-5.5",
        gpt_reasoning="Medium",
        messages_per_seat=1,
        total_target_messages=4,
    )
    ctx = CouncilContextPack.for_task("gpt browser error task", work_dir=Path.cwd())
    result = CouncilRunner(cfg, gpt_send_fn=boom).run(ctx)
    gpt = next(m for m in result.messages if m.speaker == "GPT")
    assert gpt.provider_metadata["provider"] == "mock"
    assert gpt.provider_metadata["requested_live"] is True
    assert gpt.provider_metadata["actual_live"] is False
    assert gpt.provider_metadata["fallback_from"] == "gpt-browser"
    assert "--remote-debugging-port" not in gpt.provider_metadata["fallback_reason"]
    assert "falling back to mock GPT" in gpt.content


def test_gpt_browser_local_and_gemini_can_run_together_while_claude_stays_mocked(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "AIzaFAKEKEY_FOR_TEST_ONLY_1234567890", raising=False)
    fake_gemini = _FakeGeminiSession()

    def fake_local(_prompt, _model):
        return "[RISK] Local live dissent says the browser seat must stay flag-gated."

    def fake_gpt(**kwargs):
        line = _last_continuity_line(kwargs.get("prompt", ""))
        return (
            f"{line}\n"
            "[CLAIM] Browser project context confirms the task lives in the 9to5 project. "
            "[PLAN] Keep multi-seat live tests long enough for quality checks."
        )

    cfg = _enabled_config(
        tmp_path,
        live_gpt_enabled=True,
        gpt_project_url="https://chatgpt.com/g/example/project",
        gpt_model="GPT-5.5",
        gpt_reasoning="Medium",
        live_gemini_enabled=True,
        live_local_enabled=True,
        local_model="local-test",
        messages_per_seat=1,
        total_target_messages=4,
    )
    ctx = CouncilContextPack.for_task("three live seat council", work_dir=Path.cwd())
    result = CouncilRunner(
        cfg,
        gpt_send_fn=fake_gpt,
        gemini_session_factory=lambda: fake_gemini,
        local_transport=fake_local,
    ).run(ctx)
    providers = {m.speaker: m.provider_metadata["provider"] for m in result.messages}
    assert providers == {"GPT": "gpt-browser", "Gemini": "gemini", "Claude": "mock", "Local LLM": "local"}
    assert next(m for m in result.messages if m.speaker == "Claude").provider_metadata["requested_live"] is False
    assert "Improve CouncilBrief synthesis for mixed live/mock councils" in result.brief.implementation_prompt_export
    assert any("GPT: live via gpt-browser; continuity=ok" in item for item in result.brief.important_context_gathered)
    assert "Do not call ChatGPT browser driver." not in result.brief.constraints_do_not_do
    assert "Do not call Gemini." not in result.brief.constraints_do_not_do
    assert "Do not call local LLM/Ollama." not in result.brief.constraints_do_not_do


def test_live_brief_calls_out_fallbacks_without_forbidding_requested_live_seat(tmp_path):
    def boom(**_kwargs):
        raise RuntimeError("browser failed")

    cfg = _enabled_config(
        tmp_path,
        live_gpt_enabled=True,
        gpt_project_url="https://chatgpt.com/g/example/project",
        gpt_model="GPT-5.5",
        gpt_reasoning="Medium",
        messages_per_seat=1,
        total_target_messages=4,
    )
    ctx = CouncilContextPack.for_task("gpt fallback brief task", work_dir=Path.cwd())
    result = CouncilRunner(cfg, gpt_send_fn=boom).run(ctx)
    assert any("Fallbacks observed during this run: GPT." in item for item in result.brief.important_context_gathered)
    assert any("successful GPT browser actual_live=true run" in item for item in result.brief.missing_information)
    assert "Do not call ChatGPT browser driver." not in result.brief.constraints_do_not_do


def test_provider_summary_reports_groq_partial_live_then_429_fallback(tmp_path):
    seats = [
        _RecordingSeat("GPT"),
        _RecordingSeat("Gemini"),
        _RecordingSeat("Claude"),
        _RecordingSeat("Local LLM"),
        _LiveThenFallbackSeat(
            "Groq",
            provider="groq",
            model="qwen/qwen3-32b",
            fallback_reason="qwen/qwen3-32b:rate_limit:Groq rate limited (429)",
        ),
    ]
    cfg = _enabled_config(tmp_path, live_groq_enabled=True, messages_per_seat=2, total_target_messages=10)
    result = CouncilRunner(cfg, seats=seats).run(CouncilContextPack.for_task("groq partial live summary", work_dir=Path.cwd()))
    groq = next(item for item in result.brief.provider_run_summaries if item["seat_name"] == "Groq")
    assert groq["last_provider_state"] == "partially_live_then_fallback"
    assert groq["actual_live_any"] is True
    assert groq["actual_live_all"] is False
    assert groq["actual_live_turn_count"] == 1
    assert groq["fallback_turn_count"] == 1
    assert groq["rate_limit_seen"] is True
    assert any("partially live via groq" in line for line in result.brief.provider_participation_summary)
    assert not any("Groq: requested live but all fallback" in line for line in result.brief.provider_participation_summary)


def test_provider_summary_reports_gemini_live_then_quota_fallback(tmp_path):
    seats = [
        _RecordingSeat("GPT"),
        _LiveThenFallbackSeat(
            "Gemini",
            provider="gemini",
            model="gemini-2.5-flash",
            fallback_reason="GeminiRateLimited: 429 RESOURCE_EXHAUSTED quota exceeded",
        ),
        _RecordingSeat("Claude"),
        _RecordingSeat("Local LLM"),
    ]
    cfg = _enabled_config(tmp_path, live_gemini_enabled=True, messages_per_seat=2, total_target_messages=8)
    result = CouncilRunner(cfg, seats=seats).run(CouncilContextPack.for_task("gemini quota partial summary", work_dir=Path.cwd()))
    gemini = next(item for item in result.brief.provider_run_summaries if item["seat_name"] == "Gemini")
    assert gemini["last_provider_state"] == "partially_live_then_fallback"
    assert gemini["actual_live_turn_count"] == 1
    assert gemini["fallback_turn_count"] == 1
    assert gemini["rate_limit_seen"] is True
    assert gemini["quota_limit_seen"] is True
    assert any("Quota limit observed: Gemini." in line for line in result.brief.council_run_health)


def test_provider_summary_reports_gpt_continuity_and_claude_mock(tmp_path):
    seats = [
        _ContinuityOkGptSeat(),
        _RecordingSeat("Gemini"),
        _RecordingSeat("Claude"),
        _RecordingSeat("Local LLM"),
    ]
    cfg = _enabled_config(tmp_path, live_gpt_enabled=True, messages_per_seat=1, total_target_messages=4)
    result = CouncilRunner(cfg, seats=seats).run(CouncilContextPack.for_task("gpt health summary", work_dir=Path.cwd()))
    gpt = next(item for item in result.brief.provider_run_summaries if item["seat_name"] == "GPT")
    claude = next(item for item in result.brief.provider_run_summaries if item["seat_name"] == "Claude")
    assert gpt["continuity_status"] == "ok"
    assert any("GPT continuity: ok." in line for line in result.brief.council_run_health)
    assert claude["last_provider_state"] == "mock_only"
    assert claude["requested_live"] is False
    assert any("Claude: mock-only" in line for line in result.brief.provider_participation_summary)


def test_run_composition_prompt_and_metadata_update_after_live_turn(tmp_path):
    seats = [
        _ContinuityOkGptSeat(),
        _RecordingSeat("Gemini"),
        _RecordingSeat("Claude"),
        _RecordingSeat("Local LLM"),
    ]
    cfg = _enabled_config(tmp_path, live_gpt_enabled=True, messages_per_seat=1, total_target_messages=4)
    result = CouncilRunner(cfg, seats=seats).run(CouncilContextPack.for_task("composition live update", work_dir=Path.cwd()))
    first_prompt = result.messages[0].prompt_excerpt
    second_prompt = result.messages[1].prompt_excerpt
    assert "Run type: mixed/live-capable council." in first_prompt
    assert "Live requested seats: GPT." in first_prompt
    assert "Live requested but not yet called seats: GPT." in first_prompt
    assert "Actual live seats so far: (none)." in first_prompt
    assert "Unavailable seats: (none)." in first_prompt
    assert "pending, not unavailable" in first_prompt
    assert "If your own seat is live-requested" in first_prompt
    assert "expected planning calls, not production execution" in first_prompt
    assert "Actual live seats so far: GPT." in second_prompt
    assert "Live requested but not yet called seats: (none)." in second_prompt
    assert "Mocked/control seats in this run: Gemini, Claude, Local LLM." in second_prompt

    metadata = json.loads((Path(result.log_dir) / "metadata.json").read_text(encoding="utf-8"))
    summary = metadata["run_composition_summary"]
    assert metadata["mock_only"] is False
    assert summary["run_type"] == "mixed/live-capable council"
    assert summary["live_requested_seats"] == ["GPT"]
    assert summary["pending_live_seats"] == []
    assert summary["actual_live_seats"] == ["GPT"]
    assert summary["mock_only_seats"] == ["Gemini", "Claude", "Local LLM"]


def test_mixed_live_mock_brief_has_current_provider_summary_and_no_stale_mock_only_language(tmp_path):
    seats = [
        _ContinuityOkGptSeat(),
        _LiveThenFallbackSeat(
            "Gemini",
            provider="gemini",
            model="gemini-2.5-flash",
            fallback_reason="GeminiRateLimited: 429 RESOURCE_EXHAUSTED quota exceeded",
        ),
        _RecordingSeat("Claude"),
        _RecordingSeat("Local LLM"),
    ]
    cfg = _enabled_config(tmp_path, live_gpt_enabled=True, live_gemini_enabled=True, messages_per_seat=2, total_target_messages=8)
    result = CouncilRunner(cfg, seats=seats).run(CouncilContextPack.for_task("mixed live mock current brief", work_dir=Path.cwd()))
    markdown = result.brief.to_markdown()
    assert "## Provider Participation Summary" in markdown
    assert "## Council Run Health" in markdown
    assert "## Known Limitations" in markdown
    assert "partially live" in markdown
    assert "mock-only Pre-Execution Council v0" not in result.brief.implementation_prompt_export
    assert "live providers disabled in v0" not in markdown
    assert result.brief.actionable_next_command_or_task_prompt == result.brief.implementation_prompt_export
    assert result.brief.actionable_next_command_or_task_prompt.startswith(
        "Improve CouncilBrief synthesis for mixed live/mock councils."
    )


def test_brief_artifacts_include_provider_summary_run_health_and_redactions(tmp_path):
    seats = [
        _ContinuityOkGptSeat(),
        _LiveThenFallbackSeat(
            "Gemini",
            provider="gemini",
            model="gemini-2.5-flash",
            fallback_reason=(
                "GeminiRateLimited: 429 RESOURCE_EXHAUSTED quota exceeded "
                "api_key=SECRET .env=SECRET --remote-debugging-port=9222 "
                "C:\\9to5\\state\\chatgpt_profile_recon"
            ),
        ),
        _RecordingSeat("Claude"),
        _RecordingSeat("Local LLM"),
    ]
    cfg = _enabled_config(tmp_path, live_gpt_enabled=True, live_gemini_enabled=True, messages_per_seat=2, total_target_messages=8)
    result = CouncilRunner(cfg, seats=seats).run(CouncilContextPack.for_task("artifact safety summary", work_dir=Path.cwd()))
    brief_json = json.loads((Path(result.log_dir) / "brief.json").read_text(encoding="utf-8"))
    brief_md = (Path(result.log_dir) / "brief.md").read_text(encoding="utf-8")
    assert brief_json["provider_run_summaries"]
    assert brief_json["provider_participation_summary"]
    assert brief_json["council_run_health"]
    assert "Provider Participation Summary" in brief_md
    assert "Council Run Health" in brief_md
    blob = "\n".join(p.read_text(encoding="utf-8") for p in Path(result.log_dir).iterdir() if p.is_file())
    assert "api_key=SECRET" not in blob
    assert ".env=SECRET" not in blob
    assert "--remote-debugging-port" not in blob
    assert "chatgpt_profile_recon" not in blob
    assert "api_key=" not in blob
