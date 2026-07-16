"""RED behavioral tests for the deterministic plan **Files** parser."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "galaxy_plan_manifest.py"


def _run(plan: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), "--plan", str(plan), *args],
                          text=True, capture_output=True, cwd=ROOT)


def test_parser_emits_stable_requested_task_union_and_kind(tmp_path):
    assert TOOL.is_file(), "Task 1 plan-manifest parser is absent"
    plan = tmp_path / "plan.md"
    plan.write_text("""## Task 1 - one
**Files**
- Add: `pkg/a.py`
- Add: `tests/test_a.py`
- Test: `tests/existing.py`
## Task 2 - two
**Files**
- Modify: `pkg/a.py`
- Create: `pkg/b.py`
""", encoding="utf-8")
    result = _run(plan, "--task", "1", "--kind", "red-tests")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["tests/test_a.py"]
    union = _run(plan, "--task", "1", "--task", "2", "--kind", "all")
    assert union.returncode == 0, union.stderr
    assert union.stdout.splitlines() == ["pkg/a.py", "tests/test_a.py",
                                         "tests/existing.py", "pkg/b.py"]


def test_parser_rejects_conflict_traversal_and_empty_selection(tmp_path):
    assert TOOL.is_file(), "Task 1 plan-manifest parser is absent"
    for body in (
        "- Add: `pkg/a.py`\n- Modify: `pkg/a.py`\n",
        "- Add: `../escape.py`\n",
        "- Surprise: `pkg/a.py`\n",
    ):
        plan = tmp_path / "bad.md"
        plan.write_text("## Task 1 - bad\n**Files**\n" + body, encoding="utf-8")
        result = _run(plan, "--task", "1", "--kind", "all")
        assert result.returncode != 0


def test_parser_rejects_a_valid_task_with_empty_requested_kind(tmp_path):
    assert TOOL.is_file(), "Task 1 plan-manifest parser is absent"
    plan = tmp_path / "empty.md"
    plan.write_text("## Task 1 - only production\n**Files**\n- Add: `pkg/a.py`\n",
                    encoding="utf-8")
    result = _run(plan, "--task", "1", "--kind", "red-tests")
    assert result.returncode != 0
    assert "empty selection" in result.stderr.lower()
