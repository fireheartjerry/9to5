"""Hermetic CDP lifecycle proof for the production browser action contract."""
from __future__ import annotations

import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agents.execution.browser_executor import runBrowser
from tools.browser_fixture import write_browser_fixture


@pytest.fixture
def browser_fixture(tmp_path):
    write_browser_fixture(tmp_path)
    handler = lambda *args, **kwargs: SimpleHTTPRequestHandler(*args, directory=str(tmp_path), **kwargs)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        yield base, tmp_path / "artifacts"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_fixture_proves_form_navigation_download_and_failure_evidence(browser_fixture):
    base, artifacts = browser_fixture
    result = runBrowser({"browser_actions": [
        {"action": "goto", "url": f"{base}/index.html"},
        {"action": "type", "selector": "#name", "text": "Ada"},
        {"action": "click", "selector": "#go"},
        {"action": "assert", "selector": "#status", "contains": "done"},
        {"action": "download", "selector": "#download", "path": "proof.txt"},
        {"action": "screenshot", "path": "proof.png"},
    ], "browser_policy": {"allowed_origins": [base], "max_retries": 0}}, work_dir=str(artifacts))
    if result["surface_receipt"]["actual_mode"] == "unavailable":
        pytest.skip(result["stderr"])
    assert result["ok"], result["stderr"]
    assert (artifacts / "proof.txt").read_text(encoding="utf-8") == "browser-download-proof\n"
    assert (artifacts / "proof.png").exists()
    assert len(result["browser_evidence"]) == 6

    failed = runBrowser({"browser_actions": [
        {"action": "goto", "url": f"{base}/index.html"},
        {"action": "screenshot", "path": "failed-proof.png"},
        {"action": "assert", "selector": "#status", "contains": "not present"},
    ], "browser_policy": {"allowed_origins": [base], "max_retries": 0}}, work_dir=str(artifacts))
    assert not failed["ok"]
    assert (artifacts / "failed-proof.png").exists()
    assert str(artifacts / "failed-proof.png") in failed["surface_receipt"]["artifacts"]
