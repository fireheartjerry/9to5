"""End-to-end proof the fix kills the reload storm: fire several real _ollamaChat calls with
WILDLY varying prompt sizes and confirm the ollama server does NOT reload the brain runner
between them (constant num_ctx) and every call returns non-empty content."""
import sys, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from unittest import mock
import config, orchestrator as O
from orchestrator import Orchestrator
from orchestrator import _chatText

SRV = Path.home() / "AppData/Local/Ollama/server.log"
def brain_load_count():
    try:
        data = SRV.read_bytes().decode("utf-8", "ignore")
    except Exception:
        return -1
    return len(re.findall(r'starting llama-server.*60e05f', data))

orch = Orchestrator(brain=None, obs=mock.MagicMock(), run_claude=lambda *a, **k: {},
                    replan=lambda *a, **k: {"action": "keep"}, review=lambda *a, **k: {})

prompts = [("tiny", "hi"), ("HUGE", "Z" * 180_000), ("medium", "Q" * 30_000),
           ("tiny2", "hello again"), ("HUGE2", "W" * 150_000)]
# settle: first call may reload once to the new constant 8192
print("settling (first call may reload once to the constant window)...")
orch._ollamaChat("You are the planner. Output JSON.", "warm up", want_json=True)
base = brain_load_count()
print(f"brain reloads baseline after settle = {base}")

empties = 0
for label, body in prompts:
    resp = orch._ollamaChat("You are the planner. Output ONLY a JSON object.", body, want_json=True)
    txt = _chatText(resp).strip()
    if not txt:
        empties += 1
    print(f"  {label:6} ({len(body):>7} ch) -> {'EMPTY' if not txt else f'OK({len(txt)} ch)'}")

after = brain_load_count()
print(f"\nbrain reloads after 5 varied-size calls = {after}  (delta = {after - base})")
print("RESULT:", "PASS — no reload storm, no empties"
      if after == base and empties == 0 else
      f"CHECK — reload_delta={after-base} empties={empties}")
