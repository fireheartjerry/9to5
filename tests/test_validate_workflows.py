"""test_validate_workflows.py -- CI integration tests for validate_workflows.py.

Acceptance shim: python tests/test_validate_workflows.py  (exit 0 on pass)

Covers:
  - main() returns 0 when all shipped definitions are valid.
  - main() returns 1 when the definitions directory is empty.
  - main() returns 1 when a definition directory is missing entirely.
  - main() returns 1 when at least one definition is invalid.
  - CI integration: validate_workflows.py is a runnable script (subprocess check).
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure repo root on sys.path so validate_workflows is importable.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import platform_core.ops.validate_workflows as validate_workflows  # noqa: E402


def _write_json(directory: Path, filename: str, data: object) -> Path:
    p = directory / filename
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _valid_wf(name: str) -> dict:
    return {
        "name": name,
        "description": f"desc of {name}",
        "phases": [{"title": "P", "parallel": False, "agents": [
            {"label": "a", "prompt": "do x", "effort": "default"},
        ]}],
        "synthesis": "done",
    }


# ---------------------------------------------------------------------------
# Unit: main() return-code behaviour
# ---------------------------------------------------------------------------

class TestValidateWorkflowsMain(unittest.TestCase):
    def test_returns_zero_for_shipped_definitions(self):
        """main() must exit 0 against the real shipped definitions directory."""
        exit_code = validate_workflows.main()
        self.assertEqual(exit_code, 0, "platform_core.ops.validate_workflows.main() must return 0 for all shipped definitions")

    def test_returns_one_when_directory_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            defs_dir = Path(tmp)
            with patch.object(validate_workflows, "DEFINITIONS_DIR", defs_dir):
                # Reload so DEFINITIONS_DIR is picked up by main()
                exit_code = validate_workflows.main()
            self.assertEqual(exit_code, 1)

    def test_returns_one_when_directory_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_dir = Path(tmp) / "does_not_exist"
            with patch.object(validate_workflows, "DEFINITIONS_DIR", missing_dir):
                exit_code = validate_workflows.main()
            self.assertEqual(exit_code, 1)

    def test_returns_zero_for_single_valid_definition(self):
        with tempfile.TemporaryDirectory() as tmp:
            defs_dir = Path(tmp)
            _write_json(defs_dir, "alpha.json", _valid_wf("alpha"))
            with patch.object(validate_workflows, "DEFINITIONS_DIR", defs_dir):
                exit_code = validate_workflows.main()
            self.assertEqual(exit_code, 0)

    def test_returns_one_when_any_definition_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            defs_dir = Path(tmp)
            _write_json(defs_dir, "valid.json", _valid_wf("valid"))
            _write_json(defs_dir, "bad.json", {"unknown_key": True})
            with patch.object(validate_workflows, "DEFINITIONS_DIR", defs_dir):
                exit_code = validate_workflows.main()
            self.assertEqual(exit_code, 1)

    def test_returns_one_for_malformed_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            defs_dir = Path(tmp)
            (defs_dir / "broken.json").write_text("NOT JSON {{{{", encoding="utf-8")
            with patch.object(validate_workflows, "DEFINITIONS_DIR", defs_dir):
                exit_code = validate_workflows.main()
            self.assertEqual(exit_code, 1)

    def test_returns_zero_for_multiple_valid_definitions(self):
        with tempfile.TemporaryDirectory() as tmp:
            defs_dir = Path(tmp)
            for name in ("a", "b", "c"):
                _write_json(defs_dir, f"{name}.json", _valid_wf(name))
            with patch.object(validate_workflows, "DEFINITIONS_DIR", defs_dir):
                exit_code = validate_workflows.main()
            self.assertEqual(exit_code, 0)


# ---------------------------------------------------------------------------
# CI integration: script is runnable as a subprocess
# ---------------------------------------------------------------------------

class TestValidateWorkflowsCIIntegration(unittest.TestCase):
    def test_script_exits_zero_as_subprocess(self):
        """Ensure validate_workflows.py exits 0 when run as a CI step."""
        script = _REPO_ROOT / "validate_workflows.py"
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode, 0,
            f"validate_workflows.py exited {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}",
        )

    def test_script_prints_pass_for_each_definition(self):
        """validate_workflows.py output must mention PASS for every shipped definition."""
        script = _REPO_ROOT / "validate_workflows.py"
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
        )
        self.assertIn("PASS", result.stdout)
        self.assertNotIn("FAIL", result.stdout)

    def test_script_prints_summary_line(self):
        """Output must include the N/M summary line."""
        script = _REPO_ROOT / "validate_workflows.py"
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
        )
        # Summary line looks like "3/3 workflow definition(s) valid."
        self.assertIn("workflow definition(s) valid", result.stdout)
