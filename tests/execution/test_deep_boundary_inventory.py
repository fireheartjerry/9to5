"""RED contracts for the deny-by-default production boundary inventory."""

from __future__ import annotations

import importlib
from pathlib import Path


def _pre_execution():
    return importlib.import_module("platform_core.execution.pre_execution")


def test_inventory_detects_raw_provider_process_network_and_repository_io(tmp_path: Path) -> None:
    mod = _pre_execution()
    module = tmp_path / "unsafe.py"
    module.write_text(
        """
import ollama
import subprocess
from pathlib import Path

def unsafe():
    Path('README.md').read_text()
    subprocess.run(['git', 'status'])
    return ollama.Client(host='http://example.com')
""".lstrip(),
        encoding="utf-8",
    )

    findings = mod.auditProductionBoundaries((module,), allowed_boundaries={})

    assert {finding.category for finding in findings} >= {
        "raw_local_model",
        "repository_process",
        "raw_repository_read",
    }


def test_inventory_does_not_treat_subprocess_exception_construction_as_process_launch(
    tmp_path: Path,
) -> None:
    mod = _pre_execution()
    module = tmp_path / "exception_only.py"
    module.write_text(
        """
import subprocess

def timeout():
    return subprocess.TimeoutExpired(['git', 'status'], 1.0)
""".lstrip(),
        encoding="utf-8",
    )

    assert mod.auditProductionBoundaries((module,), allowed_boundaries={}) == ()


def test_inventory_does_not_confuse_an_object_open_method_with_file_io(tmp_path: Path) -> None:
    mod = _pre_execution()
    module = tmp_path / "driver.py"
    module.write_text(
        """
class Driver:
    def open(self, conversation_id):
        return conversation_id

    def resume(self, conversation_id):
        return self.open(conversation_id)
""".lstrip(),
        encoding="utf-8",
    )

    assert mod.auditProductionBoundaries((module,), allowed_boundaries={}) == ()


def test_inventory_detects_metadata_mutation_network_native_and_effect_boundaries(
    tmp_path: Path,
) -> None:
    mod = _pre_execution()
    module = tmp_path / "deeper_unsafe.py"
    module.write_text(
        """
import shutil
import socket
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

async def unsafe(interaction):
    Path('README.md').exists()
    Path('out.txt').write_text('unsafe')
    shutil.rmtree('target')
    urllib.request.urlopen('https://example.invalid')
    socket.create_connection(('example.invalid', 443))
    sync_playwright().start()
    await interaction.response.send_message('unsafe')
""".lstrip(),
        encoding="utf-8",
    )

    findings = mod.auditProductionBoundaries((module,), allowed_boundaries={})

    assert {finding.category for finding in findings} >= {
        "raw_browser_native",
        "raw_effect",
        "raw_filesystem_mutation",
        "raw_filesystem_observation",
        "raw_network",
    }


def test_inventory_does_not_confuse_ast_walk_or_string_replace_with_host_io(
    tmp_path: Path,
) -> None:
    mod = _pre_execution()
    module = tmp_path / "pure.py"
    module.write_text(
        """
import ast

def pure(tree, text):
    return list(ast.walk(tree)), text.replace('a', 'b')
""".lstrip(),
        encoding="utf-8",
    )

    assert mod.auditProductionBoundaries((module,), allowed_boundaries={}) == ()


def test_task3_production_manifest_has_no_unclassified_deep_boundary() -> None:
    mod = _pre_execution()
    root = Path.cwd()
    findings = mod.auditProductionBoundaries(
        mod.task3ProductionInventory(root),
        allowed_boundaries=mod.reviewedTask3BoundaryAllowlist(root),
    )
    assert findings == ()
