"""webdash -- a zero-dependency local web dashboard for a running task.

Stdlib ``http.server`` only. Serves a dark, auto-refreshing glass-box view of the
latest/!named task plus control buttons (abort / pause / resume / approve / reject
/ skip) that write straight to the ControlBus. Runs in a daemon thread started by
the orchestrator; dies with the process.

Routes:
  GET  /              -> HTML page (polls /api/state)
  GET  /api/state     -> JSON snapshot {meta, subtasks, progress, control}
  POST /api/control   -> {action, arg} -> ControlBus mutation
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

import config
from control import ControlBus
from state.task import TaskState

LOG = config.getLogger("webdash")

_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>9TO5</title><style>
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:#0b0e14;color:#c8d3e0;font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}
header{padding:16px 20px;border-bottom:1px solid #1c2330;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
h1{font-size:15px;margin:0;color:#e6edf3;letter-spacing:.5px}
.pill{padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600}
.wrap{padding:20px;max-width:980px;margin:0 auto}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:18px}
.card{background:#11161f;border:1px solid #1c2330;border-radius:10px;padding:12px 14px}
.card .k{font-size:11px;text-transform:uppercase;letter-spacing:.6px;color:#6b7686}
.card .v{font-size:18px;color:#e6edf3;margin-top:4px}
.bar{height:8px;background:#1c2330;border-radius:6px;overflow:hidden;margin-top:8px}
.bar>i{display:block;height:100%;background:#3b82f6}
table{width:100%;border-collapse:collapse;margin-top:8px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #161c27;font-size:13px}
th{color:#6b7686;font-weight:600;text-transform:uppercase;font-size:11px;letter-spacing:.5px}
.s{padding:1px 8px;border-radius:6px;font-size:12px;font-weight:600}
.btn{background:#1c2330;color:#c8d3e0;border:1px solid #2a3444;border-radius:8px;padding:8px 14px;cursor:pointer;font:inherit}
.btn:hover{background:#27303f}
.btn.danger{background:#3b1717;border-color:#5b2424;color:#ffb4b4}
.btn.go{background:#13311f;border-color:#235437;color:#9be6b4}
.controls{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}
.gate{background:#2a1f08;border:1px solid #5b4413;border-radius:10px;padding:10px 14px;margin-bottom:14px;color:#ffd98a}
.muted{color:#6b7686}
h3{color:#9aa7b8;font-size:12px;text-transform:uppercase;letter-spacing:.6px;margin:22px 0 6px}
.log{background:#0e131b;border:1px solid #1c2330;border-radius:10px;padding:10px 14px;max-height:240px;overflow:auto}
.log div{padding:2px 0;border-bottom:1px solid #141a24}
</style></head><body>
<header><h1>🛰 9TO5</h1><span id="status" class="pill"></span><span id="mode" class="muted"></span>
<span id="goal" class="muted" style="flex:1;min-width:200px"></span></header>
<div class="wrap">
<div id="gate"></div>
<div class="grid">
  <div class="card"><div class="k">Progress</div><div class="v" id="prog">-</div><div class="bar"><i id="barfill" style="width:0%"></i></div></div>
  <div class="card"><div class="k">Phase</div><div class="v" id="phase">-</div></div>
  <div class="card"><div class="k">Elapsed</div><div class="v" id="elapsed">-</div></div>
  <div class="card"><div class="k">ETA (deadline)</div><div class="v" id="eta">-</div></div>
</div>
<div class="controls">
  <button class="btn danger" onclick="ctl('abort')">■ Abort</button>
  <button class="btn" onclick="ctl('pause')">⏸ Pause</button>
  <button class="btn" onclick="ctl('resume')">▶ Resume</button>
  <button class="btn go" onclick="ctl('approve')">✓ Approve gate</button>
  <button class="btn danger" onclick="ctl('reject')">✗ Reject gate</button>
</div>
<h3>Subtasks</h3>
<table><thead><tr><th>id</th><th>title</th><th>status</th><th>verify</th><th></th></tr></thead><tbody id="subs"></tbody></table>
<h3>Event log</h3><div class="log" id="log"></div>
</div>
<script>
const COL={pending:'#6b7686',in_progress:'#3b82f6',done:'#2ecc71',failed:'#e74c3c',removed:'#4b5563',
created:'#6b7686',planning:'#3b82f6',executing:'#3b82f6',complete:'#2ecc71',partial:'#e67e22',aborted:'#e74c3c'};
function fmt(s){s=Math.max(0,s|0);let h=s/3600|0,m=(s%3600)/60|0,x=s%60;return h+'h'+String(m).padStart(2,'0')+'m'+String(x).padStart(2,'0')+'s'}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]});}
async function ctl(action,arg){await fetch('/api/control',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({action,arg})});setTimeout(load,200)}
async function load(){
 let r; try{r=await (await fetch('/api/state')).json()}catch(e){return}
 if(r.empty){document.getElementById('status').textContent='no task';return}
 const m=r.meta, st=m.status;
 const sp=document.getElementById('status'); sp.textContent=st; sp.style.background=(COL[st]||'#6b7686'); sp.style.color='#0b0e14';
 document.getElementById('mode').textContent='mode: '+(m.control_mode||'watch');
 document.getElementById('goal').textContent=m.goal_raw||'';
 document.getElementById('prog').textContent=r.progress.done+' / '+r.progress.total;
 document.getElementById('barfill').style.width=(r.progress.total? 100*r.progress.done/r.progress.total:0)+'%';
 document.getElementById('phase').textContent=st;
 document.getElementById('elapsed').textContent=fmt(r.elapsed_s);
 document.getElementById('eta').textContent=fmt(r.eta_s);
 const g=r.control.pending_gate;
 document.getElementById('gate').innerHTML = g ? '<div class="gate">⏳ Awaiting decision for gate <b>'+esc(g)+'</b> — Approve / Reject above (or <code>!approve</code>)</div>' : '';
 document.getElementById('subs').innerHTML = r.subtasks.map(s=>{
   const c=COL[s.status]||'#6b7686';
   const v = s.verify==null?'—':(s.verify? '✅':'❌');
   const skip = (s.status==='pending')? '<button class="btn" style="padding:2px 8px" onclick="ctl(\\'skip\\',\\''+s.subtask_id+'\\')">skip</button>':'';
   return '<tr><td>'+esc(s.subtask_id)+'</td><td>'+esc(s.title)+'</td><td><span class="s" style="background:'+c+'22;color:'+c+'">'+esc(s.status)+'</span></td><td>'+v+'</td><td>'+skip+'</td></tr>';
 }).join('');
 document.getElementById('log').innerHTML = (r.events||[]).slice().reverse().map(e=>'<div><span class="muted">'+esc(e.at)+'</span> · '+esc(e.kind)+': '+esc(e.detail)+'</div>').join('') || '<div class="muted">—</div>';
}
load();setInterval(load,1500);
</script></body></html>"""


def _snapshot(task_id: str) -> dict:
    try:
        state = TaskState.load(task_id)
    except Exception:  # noqa: BLE001
        return {"empty": True}
    bus = ControlBus(task_id).load()
    done, total = state.progress()
    from datetime import datetime
    try:
        started = datetime.fromisoformat(state.meta["started_at"])
        deadline = datetime.fromisoformat(state.meta["deadline_at"])
        now = datetime.now().astimezone()
        elapsed_s = (now - started).total_seconds()
        eta_s = (deadline - now).total_seconds()
    except Exception:  # noqa: BLE001
        elapsed_s = eta_s = 0
    return {
        "empty": False,
        "meta": state.meta,
        "progress": {"done": done, "total": total},
        "elapsed_s": elapsed_s,
        "eta_s": eta_s,
        "subtasks": [
            {
                "subtask_id": s["subtask_id"],
                "title": s["title"],
                "status": s["status"],
                "verify": (s.get("verify_result") or {}).get("passed") if s.get("verify_result") else None,
            }
            for s in state.subtasks
        ],
        "events": state.data.get("notifications", []),
        "control": {"abort": bus["abort"], "pause": bus["pause"], "pending_gate": bus.get("pending_gate")},
    }


def _applyControl(task_id: str, action: str, arg: Optional[str]) -> dict:
    bus = ControlBus(task_id)
    if action == "abort":
        bus.requestAbort()
    elif action == "pause":
        bus.requestPause()
    elif action == "resume":
        bus.clearPause()
    elif action == "approve":
        gate = arg or bus.getPendingGate()
        if gate:
            bus.decide(gate, "approve")
    elif action == "reject":
        gate = arg or bus.getPendingGate()
        if gate:
            bus.decide(gate, "reject")
    elif action == "skip" and arg:
        bus.pushOp({"op": "skip", "subtask_id": arg})
    elif action == "add" and arg:
        bus.pushOp({"op": "add", "title": arg, "description": arg})
    return {"ok": True}


def _makeHandler(task_id: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_a):  # silence default stderr noise
            return

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            if self.path.startswith("/api/state"):
                self._send(200, json.dumps(_snapshot(task_id)).encode("utf-8"), "application/json")
            else:
                self._send(200, _PAGE.encode("utf-8"), "text/html; charset=utf-8")

        def do_POST(self):  # noqa: N802
            if not self.path.startswith("/api/control"):
                self._send(404, b"{}", "application/json")
                return
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except Exception:  # noqa: BLE001
                payload = {}
            result = _applyControl(task_id, payload.get("action", ""), payload.get("arg"))
            self._send(200, json.dumps(result).encode("utf-8"), "application/json")

    return Handler


def startWebDashboard(task_id: str, port: Optional[int] = None) -> Optional[str]:
    """Start the dashboard in a daemon thread; return its URL (or None if disabled/failed)."""
    if not config.WEB_DASHBOARD:
        return None
    port = port or config.WEB_DASHBOARD_PORT
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), _makeHandler(task_id))
    except OSError as e:
        LOG.warning("web dashboard could not bind :%s (%s)", port, e)
        return None
    thread = threading.Thread(target=server.serve_forever, name="webdash", daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}/"
    LOG.info("Web dashboard at %s", url)
    return url
