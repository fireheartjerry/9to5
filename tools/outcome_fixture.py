"""Create disposable, deterministic repositories for live outcome-evaluation canaries."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def create_bugfix_fixture(root: str | Path) -> tuple[Path, Path]:
    """Seed a git repo whose only valid repair is a small arithmetic bugfix."""
    base = Path(root)
    repo = base / "repo"
    suite = base / "suite"
    repo.mkdir(parents=True, exist_ok=True)
    suite.mkdir(parents=True, exist_ok=True)
    (repo / "calc.py").write_text("def add(left, right):\n    return left - right\n", encoding="utf-8")
    (repo / "test_calc.py").write_text(
        "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8")
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "add", "calc.py", "test_calc.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=9to5", "-c", "user.email=canary@example.invalid",
                    "commit", "-m", "seed arithmetic bug"], check=True, capture_output=True)
    (suite / "bugfix.json").write_text(json.dumps({
        "id": "live-bugfix-add", "family": "bugfix",
        "goal": "In this repository, calc.add incorrectly subtracts. Modify only calc.py so add(2, 3) returns 5. Run the supplied test.",
        "verify": {"cmd": "python -m pytest -q", "expect": "exit_zero"},
        "allowed_paths": ["calc.py"], "forbidden_paths": ["test_calc.py", ".git", ".env"],
        "max_attempts": 3,
    }, indent=2), encoding="utf-8")
    return repo, suite


def create_core_suite_fixture(root: str | Path) -> tuple[Path, Path]:
    """Create four independently repairable code-work tasks from one clean base repo."""
    base = Path(root)
    repo = base / "repo"
    suite = base / "suite"
    repo.mkdir(parents=True, exist_ok=True)
    suite.mkdir(parents=True, exist_ok=True)
    files = {
        "calc.py": "def add(left, right):\n    return left - right\n",
        "clamp.py": "def clamp(value, low, high):\n    return min(low, max(value, high))\n",
        "greeting.py": "def greet(name):\n    raise NotImplementedError('implement greeting')\n",
        "title.py": "def title_for(name):\n    raise NotImplementedError('implement title')\n",
        "slug.py": "def slugify(text):\n    return text.lower().replace(' ', '_')\n",
        "email_normalizer.py": "def normalize_email(value):\n    return value.strip().lower()\n",
        "parity.py": "def is_even(value):\n    return value > 0 and value % 2 == 0\n",
        "range_check.py": "def in_range(value, low, high):\n    return low < value < high\n",
        "test_calc.py": "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        "test_clamp.py": "from clamp import clamp\n\n\ndef test_clamp_keeps_in_range_value():\n    assert clamp(5, 0, 10) == 5\n\n\ndef test_clamp_bounds_out_of_range_values():\n    assert clamp(-1, 0, 10) == 0\n    assert clamp(11, 0, 10) == 10\n",
        "test_greeting.py": "from greeting import greet\n\n\ndef test_greet():\n    assert greet('Ada') == 'Hello, Ada!'\n",
        "test_title.py": "from title import title_for\n\n\ndef test_title_for():\n    assert title_for('ada') == 'Welcome, Ada'\n",
        "test_slug.py": "from slug import slugify\n\n\ndef test_slugify_public_api():\n    assert slugify('Hello, World!') == 'hello-world'\n",
        "test_email.py": "from email_normalizer import normalize_email\n\n\ndef test_normalize_email_preserves_local_part_case_contract():\n    assert normalize_email(' Ada@EXAMPLE.com ') == 'Ada@example.com'\n",
        "test_parity.py": "from parity import is_even\n\n\ndef test_negative_even_is_even():\n    assert is_even(-2) is True\n",
        "test_range_check.py": "from range_check import in_range\n\n\ndef test_range_is_inclusive_at_both_boundaries():\n    assert in_range(0, 0, 10) is True\n    assert in_range(10, 0, 10) is True\n",
    }
    for name, content in files.items():
        (repo / name).write_text(content, encoding="utf-8")
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=9to5", "-c", "user.email=canary@example.invalid",
                    "commit", "-m", "seed outcome suite"], check=True, capture_output=True)
    tasks = [
        ("bugfix-add", "bugfix", "calc.py", "test_calc.py", "Fix calc.add so 2 + 3 equals 5.", 180, 480),
        ("bugfix-clamp", "bugfix", "clamp.py", "test_clamp.py", "Fix clamp.clamp so values inside the inclusive [low, high] interval are unchanged and out-of-range values clamp to the closest bound.", 180, 540),
        ("feature-greeting", "feature", "greeting.py", "test_greeting.py", "Implement greeting.greet so greet('Ada') returns 'Hello, Ada!'.", 150, 480),
        ("feature-title", "feature", "title.py", "test_title.py", "Implement title.title_for so title_for('ada') returns 'Welcome, Ada'.", 150, 480),
        ("refactor-slug", "refactor", "slug.py", "test_slug.py", "Refactor slug.slugify while preserving its public API so punctuation is removed and words use hyphens.", 120, 420),
        ("refactor-email", "refactor", "email_normalizer.py", "test_email.py", "Refactor email_normalizer.normalize_email to preserve local-part case while trimming whitespace and lowercasing only the domain.", 120, 420),
        ("regression-negative-even", "regression", "parity.py", "test_parity.py", "Repair parity.is_even so negative even integers remain even.", 90, 360),
        ("regression-inclusive-range", "regression", "range_check.py", "test_range_check.py", "Repair range_check.in_range so both range boundaries are included.", 90, 360),
    ]
    for task_id, family, allowed, test, goal, executor_seconds, duration_seconds in tasks:
        (suite / f"{task_id}.json").write_text(json.dumps({
            "id": task_id, "family": family,
            "goal": f"{goal} Modify only {allowed}; do not change tests or any other path.",
            "verify": {"cmd": f"python -m pytest {test} -q", "expect": "exit_zero"},
            "allowed_paths": [allowed], "forbidden_paths": [".git", ".env"], "max_attempts": 1,
            "max_cost_usd": 5.0,
            "max_executor_seconds": executor_seconds, "max_duration_seconds": duration_seconds,
        }, indent=2), encoding="utf-8")
    return repo, suite
