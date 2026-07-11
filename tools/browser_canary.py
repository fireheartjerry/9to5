"""Gated live-CDP canary against a local, secret-free browser fixture.

Run only with ``NINE_TO_FIVE_ALLOW_BROWSER_CANARY=1``.  The canary deliberately
uses localhost and a temporary artifact directory; it proves the same Playwright
path as production without signing into, modifying, or disclosing any external service.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys


_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def run() -> dict:
    if os.getenv("NINE_TO_FIVE_ALLOW_BROWSER_CANARY") != "1":
        return {"status": "skipped", "reason": "set NINE_TO_FIVE_ALLOW_BROWSER_CANARY=1"}
    from agents.execution.browser_executor import runBrowser
    from tools.browser_fixture import write_browser_fixture
    artifact_dir = Path(os.getenv("NINE_TO_FIVE_BROWSER_CANARY_ARTIFACT_DIR", "state/browser_canaries")) / str(int(time.time()))
    artifact_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="9to5-browser-canary-") as raw:
        root = Path(raw)
        write_browser_fixture(root)
        handler = lambda *args, **kwargs: SimpleHTTPRequestHandler(*args, directory=str(root), **kwargs)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/index.html"
            result = runBrowser({"surface": "browser", "browser_actions": [
                {"action": "goto", "url": url}, {"action": "type", "selector": "#name", "text": "canary"},
                {"action": "click", "selector": "#go"}, {"action": "assert", "selector": "#status", "contains": "done"},
                {"action": "screenshot", "path": "canary.png"},
            ], "browser_policy": {"allowed_origins": [f"http://127.0.0.1:{server.server_port}"], "max_retries": 1}}, work_dir=str(artifact_dir))
            return {"status": "ok" if result.get("ok") else "failed", "surface_receipt": result.get("surface_receipt"),
                    "artifacts": result.get("surface_receipt", {}).get("artifacts", []), "stderr": result.get("stderr", "")}
        finally:
            server.shutdown()
            thread.join(timeout=5)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    payload = run()
    print(json.dumps(payload, indent=2, sort_keys=True))
    raise SystemExit(0 if payload["status"] in {"ok", "skipped"} else 1)
