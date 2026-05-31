#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.request import Request, urlopen
from urllib.error import URLError
import json
import time

UPSTREAM = "http://localhost:8088"
PORT = 8090

HTML = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>ATLAS Emergency Demo Dashboard</title>
<style>
  body {
    margin: 0;
    font-family: Arial, sans-serif;
    background: #061326;
    color: #e8f4ff;
  }
  header {
    padding: 14px 18px;
    background: #09264d;
    border-bottom: 1px solid #1c7ed6;
  }
  h1 { margin: 0; font-size: 22px; }
  .sub { color: #9bd0ff; margin-top: 4px; }
  .grid {
    display: grid;
    grid-template-columns: 1.2fr 1fr;
    gap: 12px;
    padding: 12px;
  }
  .panel {
    background: #0b1f3d;
    border: 1px solid #1c7ed6;
    border-radius: 10px;
    padding: 12px;
    box-shadow: 0 0 12px rgba(0, 140, 255, 0.18);
  }
  .row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .badge {
    background: #083b75;
    border: 1px solid #30a8ff;
    border-radius: 999px;
    padding: 4px 9px;
    font-size: 12px;
    color: #cdefff;
  }
  .ok { background: #063; border-color: #0f8; }
  .warn { background: #5a3100; border-color: #fa0; }
  .danger { background: #700; border-color: #f55; }
  .cards {
    display: grid;
    grid-template-columns: repeat(3, minmax(160px, 1fr));
    gap: 10px;
    margin-top: 10px;
  }
  .card {
    background: #102d55;
    border: 1px solid #2e9cff;
    border-radius: 8px;
    padding: 10px;
  }
  .card h3 { margin: 0 0 8px 0; color: #6ee7ff; }
  .kv { display: grid; grid-template-columns: 90px 1fr; gap: 4px; font-size: 13px; }
  .k { color: #94caff; }
  canvas {
    width: 100%;
    height: 360px;
    background: #07182f;
    border: 1px solid #1c7ed6;
    border-radius: 8px;
  }
  button {
    border: none;
    border-radius: 7px;
    padding: 10px 14px;
    color: white;
    background: #1264d8;
    cursor: pointer;
    font-weight: bold;
  }
  button:hover { filter: brightness(1.15); }
  .red { background: #d6336c; }
  .green { background: #099268; }
  .yellow { background: #e67700; }
  input {
    background: #061326;
    border: 1px solid #1c7ed6;
    color: #e8f4ff;
    border-radius: 6px;
    padding: 8px;
    width: 80px;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 8px;
    font-size: 13px;
  }
  th, td {
    border-bottom: 1px solid #24496f;
    padding: 6px;
    text-align: left;
  }
  th { color: #9bd0ff; }
  pre {
    white-space: pre-wrap;
    background: #061326;
    border-radius: 8px;
    padding: 8px;
    max-height: 220px;
    overflow: auto;
  }
</style>
</head>
<body>
<header>
  <h1>ATLAS Final Demo — Emergency Stable Dashboard</h1>
  <div class="sub">Reads live data from <b>localhost:8088/api/state</b> and sends runtime commands to the real ATLAS demo.</div>
</header>

<div class="grid">
  <section class="panel">
    <div class="row">
      <span id="apiBadge" class="badge warn">API: waiting</span>
      <span id="vehicleBadge" class="badge">Vehicles: -</span>
      <span id="missionBadge" class="badge">Mission: -</span>
      <span id="modeBadge" class="badge">Mode: -</span>
      <span id="threatBadge" class="badge">Threat: none</span>
    </div>

    <h2>Swarm / UAV Cards</h2>
    <div id="cards" class="cards"></div>

    <h2>Map View (local x/y)</h2>
    <canvas id="map" width="900" height="360"></canvas>
  </section>

  <section class="panel">
    <h2>Runtime Commands</h2>
    <div class="row">
      <button class="green" onclick="sendCmd({command:'resume'})">Resume</button>
      <button class="yellow" onclick="sendCmd({command:'pause'})">Pause</button>
      <button class="red" onclick="sendCmd({command:'rtl'})">RTL</button>
      <button onclick="sendCmd({command:'reset_demo'})">Reset Demo</button>
      <button class="red" onclick="sendCmd({command:'trigger_threat', level:'HIGH', object_type:'person', reason:'dashboard trigger'})">Trigger HIGH Threat</button>
      <button onclick="sendCmd({command:'clear_threat'})">Clear Threat</button>
    </div>
    <br>
    <div class="row">
      <label>Speed</label>
      <input id="speed" type="number" value="6.0" step="0.5">
      <button onclick="sendCmd({command:'set_speed', value:Number(document.getElementById('speed').value)})">Set Speed</button>
      <label>Patrol Scale</label>
      <input id="scale" type="number" value="2.0" step="0.5">
      <button onclick="sendCmd({command:'set_patrol_scale', value:Number(document.getElementById('scale').value)})">Set Scale</button>
    </div>
    <p id="cmdStatus" class="sub">No command sent yet.</p>

    <h2>System Status</h2>
    <div id="system"></div>

    <h2>Threat / Event</h2>
    <div id="threat"></div>

    <h2>Logs / Raw State</h2>
    <pre id="raw">waiting...</pre>
  </section>

  <section class="panel" style="grid-column: 1 / span 2">
    <h2>Telemetry Table</h2>
    <table>
      <thead>
        <tr>
          <th>UAV</th><th>State</th><th>Mode</th><th>Battery</th><th>Alt</th><th>Heading</th><th>Local X/Y/Z</th><th>Lat/Lon</th>
        </tr>
      </thead>
      <tbody id="table"></tbody>
    </table>
  </section>
</div>

<script>
let lastState = null;

function txt(v, fb='-') {
  return (v === undefined || v === null || Number.isNaN(v)) ? fb : String(v);
}
function num(v, fb=0) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fb;
}
function fixed(v, d=1, fb='-') {
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(d) : fb;
}
function esc(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

async function fetchState() {
  try {
    const r = await fetch('/api/state', {cache:'no-store'});
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const state = await r.json();
    lastState = state;
    render(state);
    document.getElementById('apiBadge').textContent = 'API: OK';
    document.getElementById('apiBadge').className = 'badge ok';
  } catch (e) {
    document.getElementById('apiBadge').textContent = 'API: ERROR';
    document.getElementById('apiBadge').className = 'badge danger';
    document.getElementById('raw').textContent = 'API error: ' + e;
  }
}

async function sendCmd(payload) {
  try {
    const r = await fetch('/api/command', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    const text = await r.text();
    document.getElementById('cmdStatus').textContent = 'Command sent: ' + JSON.stringify(payload) + ' | ' + text;
    setTimeout(fetchState, 300);
  } catch (e) {
    document.getElementById('cmdStatus').textContent = 'Command failed: ' + e;
  }
}

function render(state) {
  const vehicles = Array.isArray(state.vehicles) ? state.vehicles : [];
  const tel = state.telemetry || {};
  const mission = txt(tel.mission_state || (vehicles[0] && vehicles[0].mission_state), '-');
  const mode = txt(tel.flight_mode || (vehicles[0] && vehicles[0].flight_mode), '-');
  const threat = state.threat || null;

  document.getElementById('vehicleBadge').textContent = 'Vehicles: ' + vehicles.length;
  document.getElementById('missionBadge').textContent = 'Mission: ' + mission;
  document.getElementById('modeBadge').textContent = 'Mode: ' + mode;
  document.getElementById('threatBadge').textContent = 'Threat: ' + (threat ? 'ACTIVE' : 'none');
  document.getElementById('threatBadge').className = threat ? 'badge danger' : 'badge';

  renderCards(vehicles);
  renderTable(vehicles);
  drawMap(vehicles);
  renderSystem(state);
  renderThreat(state);
  document.getElementById('raw').textContent = JSON.stringify(state, null, 2).slice(0, 6000);
}

function renderCards(vehicles) {
  const el = document.getElementById('cards');
  if (!vehicles.length) {
    el.innerHTML = '<div class="card"><h3>No telemetry received yet</h3><p>Waiting for /atlas/demo/telemetry...</p></div>';
    return;
  }
  el.innerHTML = vehicles.map(v => `
    <div class="card">
      <h3>${esc(txt(v.uav_id, 'uav'))}</h3>
      <div class="kv">
        <div class="k">State</div><div>${esc(txt(v.mission_state))}</div>
        <div class="k">Mode</div><div>${esc(txt(v.flight_mode))}</div>
        <div class="k">Battery</div><div>${fixed(v.battery_pct, 1)}%</div>
        <div class="k">Alt</div><div>${fixed(v.alt, 1)} m</div>
        <div class="k">Heading</div><div>${fixed(v.heading_deg, 0)}°</div>
        <div class="k">Local</div><div>x=${fixed(v.x,1)}, y=${fixed(v.y,1)}, z=${fixed(v.z,1)}</div>
        <div class="k">Global</div><div>${fixed(v.lat,5)}, ${fixed(v.lon,5)}</div>
      </div>
    </div>
  `).join('');
}

function renderTable(vehicles) {
  const el = document.getElementById('table');
  el.innerHTML = vehicles.map(v => `
    <tr>
      <td>${esc(txt(v.uav_id, 'uav'))}</td>
      <td>${esc(txt(v.mission_state))}</td>
      <td>${esc(txt(v.flight_mode))}</td>
      <td>${fixed(v.battery_pct,1)}%</td>
      <td>${fixed(v.alt,1)} m</td>
      <td>${fixed(v.heading_deg,0)}°</td>
      <td>${fixed(v.x,1)} / ${fixed(v.y,1)} / ${fixed(v.z,1)}</td>
      <td>${fixed(v.lat,6)} / ${fixed(v.lon,6)}</td>
    </tr>
  `).join('');
}

function drawMap(vehicles) {
  const c = document.getElementById('map');
  const ctx = c.getContext('2d');
  ctx.clearRect(0,0,c.width,c.height);

  ctx.strokeStyle = '#164f92';
  ctx.lineWidth = 1;
  for (let x=0; x<c.width; x+=50) { ctx.beginPath(); ctx.moveTo(x,0); ctx.lineTo(x,c.height); ctx.stroke(); }
  for (let y=0; y<c.height; y+=50) { ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(c.width,y); ctx.stroke(); }

  if (!vehicles.length) {
    ctx.fillStyle = '#9bd0ff';
    ctx.font = '20px Arial';
    ctx.fillText('No telemetry received yet', 30, 50);
    return;
  }

  const xs = vehicles.map(v => num(v.x,0));
  const ys = vehicles.map(v => num(v.y,0));
  const minX = Math.min(...xs, -500), maxX = Math.max(...xs, 500);
  const minY = Math.min(...ys, -500), maxY = Math.max(...ys, 500);
  const pad = 60;

  function px(x) { return pad + (x-minX)/(maxX-minX || 1)*(c.width-2*pad); }
  function py(y) { return c.height - (pad + (y-minY)/(maxY-minY || 1)*(c.height-2*pad)); }

  ctx.fillStyle = '#ff4d6d';
  ctx.beginPath(); ctx.arc(px(0), py(0), 8, 0, Math.PI*2); ctx.fill();
  ctx.fillText('HOME', px(0)+10, py(0)-10);

  const colors = ['#00e5ff','#ffd43b','#69db7c','#ff922b'];
  vehicles.forEach((v, i) => {
    const x = num(v.x,0), y = num(v.y,0);
    ctx.fillStyle = colors[i % colors.length];
    ctx.beginPath(); ctx.arc(px(x), py(y), 10, 0, Math.PI*2); ctx.fill();
    ctx.fillStyle = '#e8f4ff';
    ctx.font = '16px Arial';
    ctx.fillText(txt(v.uav_id, 'uav'), px(x)+12, py(y)-12);

    const hdg = num(v.heading_deg,0) * Math.PI / 180;
    ctx.strokeStyle = colors[i % colors.length];
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(px(x), py(y));
    ctx.lineTo(px(x) + Math.sin(hdg)*28, py(y) - Math.cos(hdg)*28);
    ctx.stroke();
  });
}

function renderSystem(state) {
  const cc = state.commandcenter_status || {};
  const sim = state.simulation_status || {};
  document.getElementById('system').innerHTML = `
    <div class="kv">
      <div class="k">CommandCenter</div><div>${esc(txt(cc.bridge_status))}</div>
      <div class="k">Simulation</div><div>${esc(txt(sim.bridge_status))}</div>
      <div class="k">Gazebo</div><div>${state.gazebo_enabled ? 'enabled/optional' : 'disabled in stable mode'}</div>
      <div class="k">Note</div><div>${esc(txt(state.note))}</div>
    </div>
  `;
}

function renderThreat(state) {
  const t = state.threat;
  if (!t) {
    document.getElementById('threat').innerHTML = '<p>No active threat.</p>';
    return;
  }
  document.getElementById('threat').innerHTML = '<pre>' + esc(JSON.stringify(t, null, 2)) + '</pre>';
}

setInterval(fetchState, 700);
fetchState();
</script>
</body>
</html>
"""

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, content_type="text/plain"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            self._send(200, HTML, "text/html; charset=utf-8")
            return
        if self.path.startswith("/api/state"):
            try:
                with urlopen(f"{UPSTREAM}/api/state", timeout=2) as r:
                    body = r.read()
                self._send(200, body, "application/json")
            except Exception as e:
                self._send(502, json.dumps({"error": str(e)}), "application/json")
            return
        self._send(404, "not found")

    def do_POST(self):
        if self.path.startswith("/api/command"):
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            try:
                req = Request(
                    f"{UPSTREAM}/api/command",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(req, timeout=2) as r:
                    resp = r.read()
                self._send(200, resp or b"OK", "application/json")
            except Exception as e:
                self._send(502, json.dumps({"error": str(e)}), "application/json")
            return
        self._send(404, "not found")

    def log_message(self, fmt, *args):
        return

if __name__ == "__main__":
    print(f"ATLAS Emergency Dashboard: http://localhost:{PORT}")
    print(f"Proxying live state from: {UPSTREAM}/api/state")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
