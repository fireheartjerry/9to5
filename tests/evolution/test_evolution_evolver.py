import pytest

from learning.evolution import evolver
from memory import experience


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "exp.db"
    experience._reset_schema_cache()
    experience.init(p)
    yield p
    experience._reset_schema_cache()


@pytest.fixture()
def maintenance_authorities(tmp_path):
    from platform_core.runtime.controller_state import issueDiagnosticControllerStateAuthority
    from platform_core.runtime.effect_guard import issueDiagnosticMaintenanceAuthority

    capability = object()
    controller = issueDiagnosticControllerStateAuthority(
        root=tmp_path / "controller",
        repository_id="repo_test",
        controller_generation=1,
        process_capability=capability,
        expires_at="2099-01-01T00:00:00+00:00",
    )
    maintenance = issueDiagnosticMaintenanceAuthority(
        operations={"evolver"},
        controller_generation=1,
        process_capability=capability,
        expires_at="2099-01-01T00:00:00+00:00",
    )
    return {
        "controller_state_authority": controller,
        "maintenance_authority": maintenance,
    }


def test_missing_authority_defers_before_reading_enablement(db, monkeypatch):
    monkeypatch.setattr(evolver.config, "EVOLUTION_ENABLED", False, raising=False)
    assert evolver.propose_candidates(db_path=db)["status"] == "maintenance_deferred"


def test_disabled_by_default_is_noop(db, monkeypatch, maintenance_authorities):
    monkeypatch.setattr(evolver.config, "EVOLUTION_ENABLED", False, raising=False)
    assert evolver.propose_candidates(db_path=db, **maintenance_authorities) == {
        "skipped": "disabled"
    }


def test_reviewer_argv_is_write_only():
    argv = evolver._reviewer_argv("the prompt", r"C:\9to5\state\evolution\candidates")
    joined = " ".join(argv)
    assert "--disallowedTools" in joined
    # Edit/Write outside the candidate dir are blocked; Read/Glob/Grep allowed.
    assert "Edit" in joined and "Write" in joined
    assert "Read" in joined and "Grep" in joined


def test_ollama_path_proposes_without_spawn(db, monkeypatch, maintenance_authorities):
    monkeypatch.setattr(evolver.config, "EVOLUTION_ENABLED", True, raising=False)
    monkeypatch.setattr(evolver.config, "EVOLUTION_ESCALATE", False, raising=False)
    experience.record_insight(scope="family:auth", text="Verify before refresh.",
                              poignancy=0.9, support_count=3, provenance={}, db_path=db)

    def fake_brain(prompt):
        return "### Evolved auth discipline\n- verify token before refresh."

    out = evolver.propose_candidates(
        brain=fake_brain,
        db_path=db,
        **maintenance_authorities,
    )
    assert out.get("proposed")
    cands = experience.fetch_candidates(db_path=db)
    assert cands and cands[0]["provenance_json"]


def test_escalation_uses_spawn_only_for_repeated_failures(
    db,
    monkeypatch,
    maintenance_authorities,
):
    from platform_core.execution import launch_guard
    monkeypatch.setattr(launch_guard, "requireTransactionalKernelActive", lambda: None)
    monkeypatch.setattr(evolver.config, "EVOLUTION_ENABLED", True, raising=False)
    monkeypatch.setattr(evolver.config, "EVOLUTION_ESCALATE", True, raising=False)
    monkeypatch.setattr(evolver.config, "EVOLUTION_ESCALATE_MIN_FAILS", 1, raising=False)
    experience.upsert_failure_mode("family:auth", "ci_failure",
                                   root_cause="x", mitigation="y", db_path=db)
    experience.record_insight(scope="family:auth", text="Verify before refresh.",
                              poignancy=0.9, support_count=3, provenance={}, db_path=db)
    spawned = {"n": 0}

    def fake_spawn(argv):
        spawned["n"] += 1
        return {"candidate_body": "### Reviewer-authored\n- do the disciplined thing."}

    out = evolver.propose_candidates(
        spawn=fake_spawn,
        db_path=db,
        **maintenance_authorities,
    )
    assert spawned["n"] >= 1
    assert out.get("proposed")
def test_evolution_spawn_callback_is_behind_transactional_embargo(monkeypatch, tmp_path):
    import importlib
    guard = importlib.import_module("platform_core.execution.launch_guard")
    monkeypatch.setattr("config.EVOLUTION_CANDIDATE_DIR", tmp_path / "goldstone", raising=False)
    calls = []
    with pytest.raises(guard.TransactionalKernelInactive):
        evolver._claude_body({"kind": "skill", "target": "x"}, [],
                             lambda argv: calls.append(argv))
    assert calls == [] and not (tmp_path / "goldstone").exists()
