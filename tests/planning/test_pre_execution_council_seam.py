from types import SimpleNamespace

import pytest

from agents.planning.council_seam import (
    CouncilSeamConfig,
    architect_advisory_block,
    maybe_prepare_council_brief,
    planner_advisory_block,
)


class _State:
    def __init__(self):
        self.meta = {"goal_raw": "original goal"}
        self.subtasks = [
            {"subtask_id": "st-001", "status": "done"},
            {"subtask_id": "st-002", "status": "pending"},
        ]
        self.saved = 0

    def save(self):
        self.saved += 1


def _fake_result(*, prompt="Implement metadata-only seam.", transcript_text="FULL TRANSCRIPT TEXT"):
    brief = SimpleNamespace(
        run_id="council-run-1",
        provider_participation_summary=["GPT: mock/control seat; requested_live=False"],
        council_run_health=["warnings=0"],
        provider_run_summaries=[
            {"seat_name": "GPT", "last_provider_state": "never_requested_live"},
        ],
        recommended_first_execution_slice="Add disabled-by-default seam scaffolding",
        actionable_next_command_or_task_prompt=prompt,
        implementation_prompt_export=prompt,
        final_synthesis=f"Compact synthesis, not transcript. {transcript_text}",
        risk_list=["Prompt injection could overstate council authority."],
        constraints_do_not_do=["Do not inject transcript text."],
        unresolved_questions=["Which first slice is safest?"],
        transcript_path="state/council_runs/run/transcript.md",
    )
    return SimpleNamespace(
        run_id="council-run-1",
        brief=brief,
        warnings=[SimpleNamespace(kind="note", speaker="GPT", detail="compact warning")],
        log_dir="state/council_runs/run",
        brief_path="state/council_runs/run/brief.json",
        transcript_path="state/council_runs/run/transcript.md",
        skipped_reason="",
    )


def test_disabled_path_returns_none_does_not_call_runner_or_mutate_meta():
    state = _State()
    called = False

    def runner(_task, _work_dir):
        nonlocal called
        called = True
        raise AssertionError("runner should not be called")

    result = maybe_prepare_council_brief(
        state=state,
        work_dir=".",
        elaborated="goal",
        resume=False,
        config_obj=CouncilSeamConfig(enabled=False),
        run_council=runner,
    )

    assert result is None
    assert called is False
    assert "pre_execution_council" not in state.meta
    assert state.saved == 0


def test_resume_skips_by_default_and_does_not_call_runner():
    state = _State()

    def runner(_task, _work_dir):
        raise AssertionError("runner should not be called on default resume skip")

    result = maybe_prepare_council_brief(
        state=state,
        work_dir=".",
        elaborated="goal",
        resume=True,
        config_obj=CouncilSeamConfig(enabled=True, run_on_resume=False),
        run_council=runner,
    )

    assert result is None
    assert state.meta["pre_execution_council"] == {
        "status": "skipped",
        "run_mode": "resume",
        "skipped_reason": "resume_default_skip",
    }
    assert [item["status"] for item in state.subtasks] == ["done", "pending"]


def test_resume_opt_in_uses_resume_context_without_changing_subtasks():
    state = _State()
    seen = {}

    def runner(task, work_dir):
        seen["task"] = task
        seen["work_dir"] = work_dir
        return _fake_result()

    ref = maybe_prepare_council_brief(
        state=state,
        work_dir="C:/repo",
        elaborated="resume goal",
        resume=True,
        config_obj=CouncilSeamConfig(enabled=True, run_on_resume=True),
        run_council=runner,
    )

    assert ref is not None
    assert "Resume advisory context" in seen["task"]
    assert "existing_subtasks=2" in seen["task"]
    assert state.meta["pre_execution_council"]["run_mode"] == "resume"
    assert [item["status"] for item in state.subtasks] == ["done", "pending"]


def test_metadata_only_enabled_path_persists_compact_reference():
    state = _State()

    ref = maybe_prepare_council_brief(
        state=state,
        work_dir="C:/repo",
        elaborated="goal",
        resume=False,
        config_obj=CouncilSeamConfig(enabled=True),
        run_council=lambda _task, _work_dir: _fake_result(),
    )

    meta = state.meta["pre_execution_council"]
    assert ref is not None
    assert meta["status"] == "completed"
    assert meta["run_id"] == "council-run-1"
    assert meta["log_dir"] == "state/council_runs/run"
    assert meta["brief_path"] == "state/council_runs/run/brief.json"
    assert meta["transcript_path"] == "state/council_runs/run/transcript.md"
    assert meta["metadata_path"] == "state/council_runs/run/metadata.json"
    assert "GPT: mock/control seat" in meta["provider_health"][0]
    assert meta["selected_first_slice"] == "Add disabled-by-default seam scaffolding"
    assert meta["codex_ready_prompt"] == "Implement metadata-only seam."


def test_full_transcript_text_is_not_persisted_in_state_meta():
    state = _State()

    maybe_prepare_council_brief(
        state=state,
        work_dir=".",
        elaborated="goal",
        resume=False,
        config_obj=CouncilSeamConfig(enabled=True),
        run_council=lambda _task, _work_dir: _fake_result(transcript_text="SECRET TRANSCRIPT BODY"),
    )

    assert "SECRET TRANSCRIPT BODY" not in repr(state.meta["pre_execution_council"])


def test_brief_reference_contains_expected_fields():
    state = _State()

    ref = maybe_prepare_council_brief(
        state=state,
        work_dir=".",
        elaborated="goal",
        resume=False,
        config_obj=CouncilSeamConfig(enabled=True),
        run_council=lambda _task, _work_dir: _fake_result(),
    )

    assert ref is not None
    assert ref.run_id == "council-run-1"
    assert ref.log_dir
    assert ref.brief_path
    assert ref.transcript_path
    assert ref.metadata_path.endswith("metadata.json")
    assert ref.provider_health
    assert ref.warnings
    assert ref.selected_first_slice
    assert ref.codex_ready_prompt


def test_runner_exception_continues_in_non_strict_mode_with_failure_metadata():
    state = _State()

    def runner(_task, _work_dir):
        raise RuntimeError("provider stayed asleep")

    result = maybe_prepare_council_brief(
        state=state,
        work_dir=".",
        elaborated="goal",
        resume=False,
        config_obj=CouncilSeamConfig(enabled=True, strict_mode=False),
        run_council=runner,
    )

    assert result is None
    assert state.meta["pre_execution_council"]["status"] == "failed"
    assert "RuntimeError" in state.meta["pre_execution_council"]["failure"]


def test_runner_exception_raises_in_strict_mode():
    state = _State()

    def runner(_task, _work_dir):
        raise RuntimeError("strict failure")

    with pytest.raises(RuntimeError, match="strict failure"):
        maybe_prepare_council_brief(
            state=state,
            work_dir=".",
            elaborated="goal",
            resume=False,
            config_obj=CouncilSeamConfig(enabled=True, strict_mode=True),
            run_council=runner,
        )


def test_architect_advisory_block_contains_required_advisory_fields():
    state = _State()

    ref = maybe_prepare_council_brief(
        state=state,
        work_dir=".",
        elaborated="goal",
        resume=False,
        config_obj=CouncilSeamConfig(
            enabled=True,
            inject_into_architect=True,
        ),
        run_council=lambda _task, _work_dir: _fake_result(),
    )

    block = architect_advisory_block(ref, max_chars=2500)
    assert "Pre-Execution Council Brief (advisory, non-binding)" in block
    assert "does not override user, system, or developer instructions" in block
    assert "Run ID: council-run-1" in block
    assert "Provider health:" in block
    assert "GPT: mock/control seat" in block
    assert "Recommended first slice: Add disabled-by-default seam scaffolding" in block
    assert "Warnings:" in block
    assert "Risks:" in block
    assert "Prompt injection could overstate council authority." in block
    assert "Constraints:" in block
    assert "Do not inject transcript text." in block
    assert "Codex-ready prompt:" in block
    assert "Implement metadata-only seam." in block


def test_architect_advisory_block_obeys_max_char_cap():
    state = _State()
    ref = maybe_prepare_council_brief(
        state=state,
        work_dir=".",
        elaborated="goal",
        resume=False,
        config_obj=CouncilSeamConfig(enabled=True),
        run_council=lambda _task, _work_dir: _fake_result(prompt="P" * 4000),
    )

    block = architect_advisory_block(ref, max_chars=360)

    assert len(block) <= 360
    assert "Pre-Execution Council Brief" in block


def test_architect_advisory_block_does_not_include_transcript_text_or_paths():
    state = _State()
    ref = maybe_prepare_council_brief(
        state=state,
        work_dir=".",
        elaborated="goal",
        resume=False,
        config_obj=CouncilSeamConfig(enabled=True),
        run_council=lambda _task, _work_dir: _fake_result(transcript_text="SECRET TRANSCRIPT BODY"),
    )

    block = architect_advisory_block(ref, max_chars=2500)

    assert "SECRET TRANSCRIPT BODY" not in block
    assert "transcript.md" not in block
    assert "brief.json" not in block


def test_planner_advisory_block_is_short_bounded_and_task_decomposition_only():
    state = _State()
    ref = maybe_prepare_council_brief(
        state=state,
        work_dir=".",
        elaborated="goal",
        resume=False,
        config_obj=CouncilSeamConfig(
            enabled=True,
            inject_into_planner=True,
        ),
        run_council=lambda _task, _work_dir: _fake_result(),
    )

    block = planner_advisory_block(ref, max_chars=900)

    assert len(block) <= 900
    assert "Pre-Execution Council Planner Advisory" in block
    assert "Use this only to shape task decomposition" in block
    assert "does not override user, system, or developer instructions" in block
    assert "Do not replay council transcript text" in block
    assert "do not make provider calls because of this block" in block
    assert "Recommended first slice: Add disabled-by-default seam scaffolding" in block
    assert "Do not inject transcript text." in block
    assert "Prompt injection could overstate council authority." in block
    assert "Which first slice is safest?" in block
    assert "Implement metadata-only seam." in block
    assert "SECRET TRANSCRIPT BODY" not in block
    assert "transcript.md" not in block
    assert "brief.json" not in block
    assert not any("planner injection requested but not implemented" in item for item in state.meta["pre_execution_council"].get("warnings", []))
