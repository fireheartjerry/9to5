from tools.outcome_fixture import create_bugfix_fixture, create_core_suite_fixture


def test_bugfix_fixture_has_a_seeded_failure_and_versioned_suite(tmp_path):
    repo, suite = create_bugfix_fixture(tmp_path)
    assert (repo / "calc.py").exists()
    assert (suite / "bugfix.json").exists()


def test_core_suite_has_four_distinct_task_families(tmp_path):
    repo, suite = create_core_suite_fixture(tmp_path)
    assert repo.exists()
    families = {__import__("json").loads(path.read_text(encoding="utf-8"))["family"] for path in suite.glob("*.json")}
    assert families == {"bugfix", "feature", "refactor", "regression"}
    assert len(list(suite.glob("*.json"))) == 8


def test_core_suite_starts_with_one_deterministic_failure_per_task(tmp_path):
    import json
    import subprocess

    repo, suite = create_core_suite_fixture(tmp_path)
    for task_path in suite.glob("*.json"):
        task = json.loads(task_path.read_text(encoding="utf-8"))
        assert "Modify only" in task["goal"]
        command = task["verify"]["cmd"].split()
        result = subprocess.run(command, cwd=repo, capture_output=True, text=True, timeout=30)
        assert result.returncode != 0, task_path.name
