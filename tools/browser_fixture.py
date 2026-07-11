"""Hermetic browser fixture application used by CDP tests and the live canary."""
from __future__ import annotations

from pathlib import Path


def write_browser_fixture(root: str | Path) -> Path:
    """Create deterministic form, navigation, retry, download, and timeout targets."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text("""<!doctype html><title>9to5 browser fixture</title>
<label>Name <input id='name'></label><button id='go' onclick="document.querySelector('#status').textContent='done'">Go</button>
<a id='next' href='next.html'>Next</a><a id='download' href='proof.txt' download>Download proof</a>
<button id='delayed-host' onclick="setTimeout(()=>{const b=document.createElement('button');b.id='delayed';b.textContent='ready';document.body.append(b)},100)">Create delayed selector</button>
<p id='status'>waiting</p>""", encoding="utf-8")
    (root / "next.html").write_text("<!doctype html><title>Next</title><p id='next-status'>navigated</p>", encoding="utf-8")
    (root / "proof.txt").write_text("browser-download-proof\n", encoding="utf-8")
    (root / "timeout.html").write_text("<!doctype html><title>Timeout</title><p id='never'>no delayed target</p>", encoding="utf-8")
    return root
