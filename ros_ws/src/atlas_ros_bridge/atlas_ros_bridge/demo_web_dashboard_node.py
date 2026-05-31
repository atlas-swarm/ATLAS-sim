from __future__ import annotations

"""Unified web dashboard node for the ATLAS final demo.

Serves a self-contained dashboard at:
  http://localhost:<port>

Endpoints:
- GET /            : HTML UI
- GET /api/state   : latest ROS state as JSON
- POST /api/command: publish runtime command JSON to /atlas/demo/runtime_commands
- GET /camera.mjpg : optional MJPEG stream sourced from /camera/image_raw

Design constraints:
- No external web dependencies (no Flask/FastAPI/CDN).
- Must be resilient: invalid JSON or missing camera conversion never crashes demo.
- Must reflect shared source-of-truth topics (no fake state).
"""

import json
import os
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String

from .bridge_utils import safe_json_loads


def _now_ms() -> int:
    return int(time.time() * 1000)


def _tail_lines(path: str, max_lines: int) -> list[str]:
    try:
        with open(path, "rb") as fp:
            fp.seek(0, os.SEEK_END)
            size = fp.tell()
            block = 4096
            data = b""
            while size > 0 and data.count(b"\n") <= max_lines:
                read_size = min(block, size)
                size -= read_size
                fp.seek(size)
                data = fp.read(read_size) + data
                if size == 0:
                    break
        lines = data.decode("utf-8", errors="replace").splitlines()
        return lines[-max_lines:]
    except Exception:
        return []


def _tail_jsonl(path: str, max_records: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in _tail_lines(path, max_records * 4):
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            records.append(obj)
    return records[-max_records:]


def _normalize_vehicles(tel: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(tel, dict) or not tel:
        return []

    mission_state = tel.get("mission_state")
    flight_mode = tel.get("flight_mode")

    def _fill_defaults(v: dict[str, Any]) -> dict[str, Any]:
        # Only keep fields the dashboard expects.
        out: dict[str, Any] = {}
        for k in (
            "uav_id",
            "lat",
            "lon",
            "alt",
            "x",
            "y",
            "z",
            "vx",
            "vy",
            "vz",
            "heading_deg",
            "battery_pct",
            "mission_state",
            "flight_mode",
        ):
            if k in v:
                out[k] = v.get(k)
        if "mission_state" not in out and mission_state is not None:
            out["mission_state"] = mission_state
        if "flight_mode" not in out and flight_mode is not None:
            out["flight_mode"] = flight_mode
        return out

    vehicles = tel.get("vehicles")
    if isinstance(vehicles, list) and vehicles:
        norm: list[dict[str, Any]] = []
        for idx, item in enumerate(vehicles, start=1):
            if not isinstance(item, dict):
                continue
            vv = _fill_defaults(item)
            if not vv.get("uav_id"):
                vv["uav_id"] = f"uav_{idx}"
            norm.append(vv)
        return norm

    # Legacy single-UAV telemetry (top-level fields represent the lead UAV).
    legacy = _fill_defaults(tel)
    if not legacy.get("uav_id"):
        legacy["uav_id"] = "uav_1"
    return [legacy]


_HTML = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ATLAS Final Demo</title>
  <style>
    body { margin: 0; font-family: Arial, sans-serif; background: #061326; color: #e8f4ff; }
    header { padding: 14px 18px; background: #09264d; border-bottom: 1px solid #1c7ed6; }
    h1 { margin: 0; font-size: 22px; }
    .sub { color: #9bd0ff; margin-top: 4px; font-size: 13px; }
    .grid { display: grid; grid-template-columns: 1.2fr 1fr; gap: 12px; padding: 12px; }
    .panel { background: #0b1f3d; border: 1px solid #1c7ed6; border-radius: 10px; padding: 12px; box-shadow: 0 0 12px rgba(0, 140, 255, 0.18); }
    .row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    .badge { background: #083b75; border: 1px solid #30a8ff; border-radius: 999px; padding: 4px 9px; font-size: 12px; color: #cdefff; }
    .ok { background: #063; border-color: #0f8; }
    .warn { background: #5a3100; border-color: #fa0; }
    .danger { background: #700; border-color: #f55; }
    .cards { display: grid; grid-template-columns: repeat(3, minmax(160px, 1fr)); gap: 10px; margin-top: 10px; }
    .card { background: #102d55; border: 1px solid #2e9cff; border-radius: 8px; padding: 10px; }
    .card h3 { margin: 0 0 8px 0; color: #6ee7ff; }
    .kv { display: grid; grid-template-columns: 90px 1fr; gap: 4px; font-size: 13px; }
    .k { color: #94caff; }
    canvas { width: 100%; height: 360px; background: #07182f; border: 1px solid #1c7ed6; border-radius: 8px; }
    button { border: none; border-radius: 7px; padding: 10px 14px; color: white; background: #1264d8; cursor: pointer; font-weight: bold; }
    button:hover { filter: brightness(1.15); }
    .red { background: #d6336c; }
    .green { background: #099268; }
    .yellow { background: #e67700; }
    input { background: #061326; border: 1px solid #1c7ed6; color: #e8f4ff; border-radius: 6px; padding: 8px; width: 80px; }
    table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 13px; }
    th, td { border-bottom: 1px solid #24496f; padding: 6px; text-align: left; }
    th { color: #9bd0ff; background: rgba(9, 38, 77, 0.55); position: sticky; top: 0; }
    table.telemetry tbody tr:nth-child(even) { background: rgba(16, 45, 85, 0.35); }
    table.telemetry tbody tr:hover { background: rgba(46, 156, 255, 0.12); }
    .tag { display:inline-block; padding: 2px 7px; border-radius: 999px; border: 1px solid #30a8ff; font-size: 11px; color: #cdefff; background: rgba(8,59,117,0.7); }
    .tag.ok { border-color: #0f8; color: #b7ffd7; background: rgba(0,102,51,0.55); }
    .tag.warn { border-color: #fa0; color: #ffe3b0; background: rgba(90,49,0,0.55); }
    .tag.danger { border-color: #f55; color: #ffd0d6; background: rgba(112,0,0,0.55); }
    .tag.dim { border-color: #24496f; color: #9bd0ff; background: rgba(6,19,38,0.6); }
    .btnlink { display:inline-block; margin: 3px 6px 3px 0; padding: 8px 10px; border-radius: 7px; border: 1px solid #30a8ff; color: #e8f4ff; background: rgba(8,59,117,0.55); text-decoration: none; font-weight: bold; font-size: 12px; }
    .btnlink:hover { filter: brightness(1.15); }
    pre { white-space: pre-wrap; background: #061326; border-radius: 8px; padding: 8px; max-height: 220px; overflow: auto; }
    .smallerr { color: #ffb6c1; margin-top: 6px; }
  </style>
</head>
<body>
<header>
  <h1>ATLAS Final Demo — Official Operator Dashboard</h1>
  <div class="sub">Official UI on <b>localhost:8088</b>. Uses <b>/api/state</b> + <b>/api/command</b>. QGC is a separate native app.</div>
  <div id="fatal" class="smallerr"></div>
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

    <h2>Telemetry Table</h2>
    <table class="telemetry">
      <thead>
        <tr>
          <th>UAV</th>
          <th>SysID</th>
          <th>Mission</th>
          <th>Mode</th>
          <th>Battery</th>
          <th>Alt</th>
          <th>Heading</th>
          <th>Speed</th>
          <th>Local X/Y/Z</th>
          <th>Lat/Lon</th>
          <th>Age</th>
        </tr>
      </thead>
      <tbody id="table"></tbody>
    </table>

    <h2>Live Telemetry Feed</h2>
    <pre id="feed">waiting...</pre>
  </section>

  <section class="panel">
    <h2>Runtime Commands</h2>

    <div class="sub"><b>Mission controls</b></div>
    <div class="row">
      <button class="green" onclick="sendCmd({command:'resume'})">Resume</button>
      <button class="yellow" onclick="sendCmd({command:'pause'})">Pause</button>
      <button class="red" onclick="sendCmd({command:'rtl'})">RTL</button>
      <button onclick="sendCmd({command:'reset_demo'})">Reset Demo</button>
    </div>

    <div style="height:8px"></div>
    <div class="sub"><b>Threat controls</b></div>
    <div class="row">
      <button class="red" onclick="sendCmd({command:'trigger_threat', level:'HIGH', object_type:'person', reason:'dashboard trigger'})">Trigger HIGH Threat</button>
      <button onclick="sendCmd({command:'clear_threat'})">Clear Threat</button>
    </div>

    <div style="height:8px"></div>
    <div class="sub"><b>Tuning</b></div>
    <div class="row">
      <label>Speed</label>
      <input id="speed" type="number" value="6.0" step="0.5">
      <button onclick="sendCmd({command:'set_speed', value:Number(document.getElementById('speed').value)})">Set Speed</button>
      <label>Patrol Scale</label>
      <input id="scale" type="number" value="2.0" step="0.5">
      <button onclick="sendCmd({command:'set_patrol_scale', value:Number(document.getElementById('scale').value)})">Set Scale</button>
    </div>
    <p id="cmdStatus" class="sub">No command sent yet.</p>

    <h2>System Health</h2>
    <div id="system"></div>

    <h2>Gazebo</h2>
    <div id="gazebo"></div>

    <h2>Threat</h2>
    <div id="threat"></div>

    <h2>Raw Vehicles Fallback</h2>
    <pre id="vehiclesRaw">waiting...</pre>

    <h2>Logs / Evidence</h2>
    <div class="sub">Downloads</div>
    <div class="row">
      <a class="btnlink" href="/api/logs/telemetry_log.jsonl">telemetry_log.jsonl</a>
      <a class="btnlink" href="/api/logs/telemetry_log.csv">telemetry_log.csv</a>
      <a class="btnlink" href="/api/logs/threat_log.jsonl">threat_log.jsonl</a>
      <a class="btnlink" href="/api/logs/command_log.jsonl">command_log.jsonl</a>
      <a class="btnlink" href="/api/logs/incident_log.jsonl">incident_log.jsonl</a>
    </div>
    <div class="sub">Log directory</div>
    <pre id="logDir">-</pre>
    <div class="sub">Files</div>
    <pre id="logFiles">-</pre>
    <div class="sub">Recent commands</div>
    <pre id="cmdLog">-</pre>
    <div class="sub">Recent threats</div>
    <pre id="thrLog">-</pre>
    <div class="sub">Recent incidents</div>
    <pre id="incLog">-</pre>

    <h2>Raw State (debug)</h2>
    <details>
      <summary class="sub">Show raw /api/state JSON</summary>
      <pre id="raw">waiting...</pre>
    </details>
  </section>
</div>

<script>
let lastState = null;
let feedLines = [];

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

function badge(textValue, cls) {
  const c = cls ? String(cls) : 'dim';
  return `<span class="tag ${c}">${esc(textValue)}</span>`;
}

function batteryClass(pct) {
  const p = num(pct, NaN);
  if (!Number.isFinite(p)) return 'dim';
  if (p > 60) return 'ok';
  if (p >= 30) return 'warn';
  return 'danger';
}

function modeClass(mode) {
  const m = String(mode || '').toUpperCase();
  if (m === 'AUTO') return 'ok';
  if (m === 'RTL') return 'warn';
  if (!m) return 'dim';
  return 'warn';
}

function missionClass(state) {
  const s = String(state || '').toUpperCase();
  if (s === 'RUNNING') return 'ok';
  if (s === 'PAUSED') return 'warn';
  if (!s) return 'dim';
  return 'warn';
}

function fmtTimeMs(ms) {
  const n = num(ms, NaN);
  if (!Number.isFinite(n)) return '--:--:--';
  try {
    return new Date(n).toLocaleTimeString();
  } catch (_) {
    return String(n);
  }
}

function safeParseJsonText(raw, fallback=null) {
  if (raw === undefined || raw === null) return fallback;
  if (typeof raw !== 'string') return raw;
  const s = raw.trim();
  if (!s.length) return fallback;
  try { return JSON.parse(s); } catch (_) { return fallback; }
}

function showFatal(msg) {
  const el = document.getElementById('fatal');
  if (el) el.textContent = String(msg || '');
}

window.onerror = function(message, source, lineno, colno, error) {
  showFatal(error || message);
  return false;
};
window.addEventListener('unhandledrejection', function(ev) {
  showFatal(ev && ev.reason ? ev.reason : 'Unhandled promise rejection');
});

async function fetchState() {
  try {
    const r = await fetch('/api/state', {cache:'no-store'});
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const raw = await r.text();
    const state = safeParseJsonText(raw, null);
    if (!state || typeof state !== 'object') throw new Error('Invalid JSON from /api/state');

    lastState = state;
    render(state);
    document.getElementById('apiBadge').textContent = 'API: OK';
    document.getElementById('apiBadge').className = 'badge ok';
    showFatal('');
  } catch (e) {
    document.getElementById('apiBadge').textContent = 'API: ERROR';
    document.getElementById('apiBadge').className = 'badge danger';
    showFatal('API error: ' + e);
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
  const tel = (state && typeof state.telemetry === 'object' && state.telemetry) ? state.telemetry : {};
  const mission = txt(tel.mission_state || (vehicles[0] && vehicles[0].mission_state), '-');
  const mode = txt(tel.flight_mode || (vehicles[0] && vehicles[0].flight_mode), '-');

  const nowMs = num(state.timestamp_ms, Date.now());
  const lastTelMs = num(state.last_updates_ms && state.last_updates_ms.telemetry, 0);
  const ageSec = (lastTelMs > 0) ? Math.max(0, (nowMs - lastTelMs) / 1000.0) : NaN;

  let threatActive = false;
  let threatLevel = 'NONE';
  try {
    const t = state.threat || {};
    const assessments = Array.isArray(t.assessments) ? t.assessments : [];
    const top = assessments.length ? assessments[0] : null;
    threatActive = assessments.length > 0;
    threatLevel = top ? txt(top.threat_level, 'UNKNOWN') : 'NONE';
  } catch (_) {}

  document.getElementById('vehicleBadge').textContent = 'Vehicles: ' + vehicles.length;
  document.getElementById('missionBadge').textContent = 'Mission: ' + mission;
  document.getElementById('modeBadge').textContent = 'Mode: ' + mode;
  document.getElementById('threatBadge').textContent = 'Threat: ' + (threatActive ? threatLevel : 'none');
  document.getElementById('threatBadge').className = threatActive ? 'badge danger' : 'badge';

  // Always-visible raw vehicles fallback
  try {
    document.getElementById('vehiclesRaw').textContent = JSON.stringify(vehicles, null, 2).slice(0, 6000);
  } catch (_) {
    document.getElementById('vehiclesRaw').textContent = String(vehicles);
  }

  // Live telemetry feed (frontend only; keep last 20 lines)
  try {
    const t = fmtTimeMs(nowMs);
    for (const v of vehicles) {
      const spd = Math.hypot(num(v.vx, 0), num(v.vy, 0));
      const line = `[${t}] ${txt(v.uav_id,'uav')} ${txt(v.flight_mode,'-')}/${txt(v.mission_state,'-')} alt=${fixed(v.alt,1)}m battery=${fixed(v.battery_pct,0)}% x=${fixed(v.x,1)} y=${fixed(v.y,1)} spd=${fixed(spd,1)}m/s`;
      feedLines.push(line);
    }
    while (feedLines.length > 20) feedLines.shift();
    const feedEl = document.getElementById('feed');
    if (feedEl) feedEl.textContent = feedLines.join('\n');
  } catch (_) {}

  // Each section must be non-fatal
  try { renderCards(vehicles); } catch (e) { showFatal('cards render error: ' + e); }
  try { renderTable(vehicles, {mission, mode, ageSec}); } catch (e) { showFatal('table render error: ' + e); }
  try { drawMap(vehicles); } catch (e) { showFatal('map render error: ' + e); }
  try { renderSystem(state, {mission, mode, ageSec}); } catch (e) { showFatal('system render error: ' + e); }
  try { renderGazebo(state); } catch (e) {}
  try { renderThreat(state); } catch (e) {}
  try { renderLogs(state); } catch (e) {}

  document.getElementById('raw').textContent = JSON.stringify(state, null, 2).slice(0, 6000);
}

function renderCards(vehicles) {
  const el = document.getElementById('cards');
  if (!vehicles.length) {
    el.innerHTML = '<div class="card"><h3>No telemetry received yet</h3><p>Waiting for /atlas/demo/telemetry...</p></div>';
    return;
  }

  el.innerHTML = vehicles.map(v => {
    const uav = esc(txt(v.uav_id, 'uav'));
    const ms = txt(v.mission_state, '-');
    const fm = txt(v.flight_mode, '-');
    const batt = num(v.battery_pct, NaN);
    return `
      <div class="card">
        <h3>${uav}</h3>
        <div class="kv">
          <div class="k">Mission</div><div>${badge(ms, missionClass(ms))}</div>
          <div class="k">Mode</div><div>${badge(fm, modeClass(fm))}</div>
          <div class="k">Battery</div><div>${badge(fixed(batt,0) + '%', batteryClass(batt))}</div>
          <div class="k">Alt</div><div>${fixed(v.alt, 1)} m</div>
          <div class="k">Heading</div><div>${fixed(v.heading_deg, 0)}°</div>
          <div class="k">Local</div><div>x=${fixed(v.x,1)}, y=${fixed(v.y,1)}, z=${fixed(v.z,1)}</div>
          <div class="k">Global</div><div>${fixed(v.lat,5)}, ${fixed(v.lon,5)}</div>
        </div>
      </div>
    `;
  }).join('');
}

function renderTable(vehicles, meta) {
  const el = document.getElementById('table');
  const mission = meta && meta.mission ? String(meta.mission) : '-';
  const mode = meta && meta.mode ? String(meta.mode) : '-';
  const ageSec = meta && typeof meta.ageSec === 'number' ? meta.ageSec : NaN;

  if (!vehicles.length) {
    el.innerHTML = '<tr><td colspan="11">No telemetry received yet.</td></tr>';
    return;
  }

  el.innerHTML = vehicles.map(v => {
    const uav = esc(txt(v.uav_id, 'uav'));
    const sysid = (v.sysid !== undefined && v.sysid !== null)
      ? esc(txt(v.sysid))
      : (txt(v.uav_id) === 'uav_1') ? '1' : (txt(v.uav_id) === 'uav_2') ? '2' : (txt(v.uav_id) === 'uav_3') ? '3' : '-';

    const ms = txt(v.mission_state, mission);
    const fm = txt(v.flight_mode, mode);
    const batt = num(v.battery_pct, NaN);
    const spd = Math.hypot(num(v.vx, 0), num(v.vy, 0));

    const ageTxt = Number.isFinite(ageSec) ? fixed(ageSec, 1) + 's' : '-';
    const ageCls = !Number.isFinite(ageSec) ? 'dim' : (ageSec < 2.0 ? 'ok' : (ageSec < 5.0 ? 'warn' : 'danger'));

    return `
      <tr>
        <td>${uav}</td>
        <td>${sysid}</td>
        <td>${badge(ms, missionClass(ms))}</td>
        <td>${badge(fm, modeClass(fm))}</td>
        <td>${badge(fixed(batt,0) + '%', batteryClass(batt))}</td>
        <td>${fixed(v.alt,1)} m</td>
        <td>${fixed(v.heading_deg,0)}°</td>
        <td>${fixed(spd,1)} m/s</td>
        <td>${fixed(v.x,1)} / ${fixed(v.y,1)} / ${fixed(v.z,1)}</td>
        <td>${fixed(v.lat,6)} / ${fixed(v.lon,6)}</td>
        <td>${badge(ageTxt, ageCls)}</td>
      </tr>
    `;
  }).join('');
}

function drawMap(vehicles) {
  const c = document.getElementById('map');
  const ctx = c.getContext('2d');
  ctx.clearRect(0,0,c.width,c.height);

  // Dark operator grid
  ctx.strokeStyle = '#113a68';
  ctx.lineWidth = 1;
  for (let x=0; x<c.width; x+=50) { ctx.beginPath(); ctx.moveTo(x,0); ctx.lineTo(x,c.height); ctx.stroke(); }
  for (let y=0; y<c.height; y+=50) { ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(c.width,y); ctx.stroke(); }

  // Major grid
  ctx.strokeStyle = '#1c6db3';
  ctx.globalAlpha = 0.35;
  for (let x=0; x<c.width; x+=250) { ctx.beginPath(); ctx.moveTo(x,0); ctx.lineTo(x,c.height); ctx.stroke(); }
  for (let y=0; y<c.height; y+=250) { ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(c.width,y); ctx.stroke(); }
  ctx.globalAlpha = 1.0;

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

  // HOME marker at (0,0)
  const hx = px(0);
  const hy = py(0);
  ctx.fillStyle = '#ff4d6d';
  ctx.beginPath(); ctx.arc(hx, hy, 7, 0, Math.PI*2); ctx.fill();
  ctx.fillStyle = '#e8f4ff';
  ctx.font = '14px Arial';
  ctx.fillText('HOME (0,0)', hx + 10, hy - 10);

  const colorsById = {'uav_1':'#00e5ff','uav_2':'#ffd43b','uav_3':'#69db7c'};

  vehicles.forEach((v, i) => {
    const x = num(v.x,0), y = num(v.y,0);
    const id = txt(v.uav_id, 'uav');
    const color = colorsById[id] || ['#00e5ff','#ffd43b','#69db7c','#ff922b'][i % 4];

    ctx.fillStyle = color;
    ctx.beginPath(); ctx.arc(px(x), py(y), 10, 0, Math.PI*2); ctx.fill();

    // Outline for contrast
    ctx.strokeStyle = '#061326';
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(px(x), py(y), 10, 0, Math.PI*2); ctx.stroke();

    ctx.fillStyle = '#e8f4ff';
    ctx.font = '16px Arial';
    ctx.fillText(id, px(x)+12, py(y)-12);

    // Heading arrow
    const hdg = num(v.heading_deg,0) * Math.PI / 180;
    ctx.strokeStyle = color;
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(px(x), py(y));
    ctx.lineTo(px(x) + Math.sin(hdg)*28, py(y) - Math.cos(hdg)*28);
    ctx.stroke();
  });

  // Coordinate scale hint
  ctx.fillStyle = '#9bd0ff';
  ctx.font = '12px Arial';
  ctx.fillText(`x:[${fixed(minX,0)},${fixed(maxX,0)}]  y:[${fixed(minY,0)},${fixed(maxY,0)}]`, 18, c.height - 14);
}

function renderSystem(state, meta) {
  const cc = state.commandcenter_status || {};
  const sim = state.simulation_status || {};

  const ageSec = meta && typeof meta.ageSec === 'number' ? meta.ageSec : NaN;
  const freshCls = !Number.isFinite(ageSec) ? 'dim' : (ageSec < 2.0 ? 'ok' : (ageSec < 5.0 ? 'warn' : 'danger'));
  const freshTxt = !Number.isFinite(ageSec) ? '-' : fixed(ageSec, 1) + 's';

  const vision = txt(state.vision_summary, '-');
  const visionCls = (vision !== '-' && vision !== '0') ? 'ok' : 'warn';

  const gazeboCls = state.gazebo_enabled ? 'warn' : 'ok';
  const gazeboTxt = state.gazebo_enabled ? 'ENABLED (optional)' : 'DISABLED (stable)';

  document.getElementById('system').innerHTML = `
    <div class="kv">
      <div class="k">Telemetry age</div><div>${badge(freshTxt, freshCls)}</div>
      <div class="k">Vehicle count</div><div>${esc(txt((Array.isArray(state.vehicles) ? state.vehicles.length : 0)))}</div>
      <div class="k">CommandCenter</div><div>${badge(txt(cc.bridge_status || cc.status || '-'), (cc.bridge_status || cc.status) ? 'ok' : 'dim')}</div>
      <div class="k">Simulation</div><div>${badge(txt(sim.bridge_status || sim.status || '-'), (sim.bridge_status || sim.status) ? 'ok' : 'dim')}</div>
      <div class="k">Gazebo</div><div>${badge(gazeboTxt, gazeboCls)}</div>
      <div class="k">Vision/YOLO</div><div>${badge((vision !== '-' ? ('detections=' + vision) : 'IDLE/UNAVAILABLE'), visionCls)}</div>
      <div class="k">Last cmd</div><div>${esc(txt(state.last_command || '-'))}</div>
    </div>
  `;
}

function renderLogs(state) {
  const logs = state.logs || {};
  const files = logs.files || {};
  const tail = logs.tail || {};

  const logDirEl = document.getElementById('logDir');
  if (logDirEl) logDirEl.textContent = txt(logs.log_dir, '-');

  const fileLines = [];
  for (const name of ['telemetry_log.jsonl','telemetry_log.csv','threat_log.jsonl','command_log.jsonl','incident_log.jsonl']) {
    const ok = !!files[name];
    fileLines.push(`${name}: ${ok ? 'OK' : 'missing'}`);
  }
  const logFilesEl = document.getElementById('logFiles');
  if (logFilesEl) logFilesEl.textContent = fileLines.join('\n');

  function fmtEntry(e) {
    if (!e || typeof e !== 'object') return '';
    const t = fmtTimeMs(e.timestamp || e.timestamp_ms);
    const cmd = txt(e.command || e.type || e.category || e.message, '-');
    const src = txt(e.source, '-');
    return `[${t}] ${src} ${cmd}`;
  }

  const cmdLogEl = document.getElementById('cmdLog');
  const thrLogEl = document.getElementById('thrLog');
  const incLogEl = document.getElementById('incLog');

  const cmds = Array.isArray(tail.command) ? tail.command : [];
  const thrs = Array.isArray(tail.threat) ? tail.threat : [];
  const incs = Array.isArray(tail.incident) ? tail.incident : [];

  if (cmdLogEl) cmdLogEl.textContent = cmds.slice(-12).map(fmtEntry).filter(Boolean).join('\n') || '-';
  if (thrLogEl) thrLogEl.textContent = thrs.slice(-8).map(fmtEntry).filter(Boolean).join('\n') || '-';
  if (incLogEl) incLogEl.textContent = incs.slice(-8).map(fmtEntry).filter(Boolean).join('\n') || '-';
}

function renderGazebo(state) {
  const msg = (state.gazebo_enabled === false)
    ? 'Gazebo disabled in stable dashboard mode. Native Gazebo can be launched separately.'
    : 'Gazebo enabled (optional/experimental).';
  document.getElementById('gazebo').innerHTML = '<p>' + esc(msg) + '</p>';
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



class _SharedState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.telemetry: dict[str, Any] | None = None
        self.vehicles: list[dict[str, Any]] = []
        self.threat: dict[str, Any] | None = None
        self.operator_command: dict[str, Any] | None = None
        self.runtime_command: dict[str, Any] | None = None
        self.commandcenter_status: dict[str, Any] | None = None
        self.simulation_status: dict[str, Any] | None = None
        self.vision_detections: dict[str, Any] | None = None
        self.last_update_ms: dict[str, int] = {}

        # Cached log snapshot for /api/state (updated on a timer).
        self.logs: dict[str, Any] = {"log_dir": "", "files": {}, "tail": {}}

        self.latest_jpeg: bytes | None = None
        self.mjpeg_available: bool = False
        self.camera_error: str | None = None
        self.last_ros_frame_ms: int | None = None
        self.camera_width: int | None = None
        self.camera_height: int | None = None
        self.camera_encoding: str | None = None

        self.speed_mps: float | None = None
        self.patrol_scale: float | None = None


class DemoWebDashboardNode(Node):
    def __init__(self) -> None:
        super().__init__("demo_web_dashboard_node")

        self.declare_parameter("host", "0.0.0.0")
        self.declare_parameter("port", 8088)
        self.declare_parameter("log_dir", "/ros_ws/log/atlas_demo")
        self.declare_parameter("gazebo_enabled", False)

        self.declare_parameter("telemetry_topic", "/atlas/demo/telemetry")
        self.declare_parameter("alerts_topic", "/atlas/threat_alerts")
        self.declare_parameter("operator_commands_topic", "/atlas/operator_commands")
        self.declare_parameter("runtime_commands_topic", "/atlas/demo/runtime_commands")
        self.declare_parameter("commandcenter_status_topic", "/atlas/commandcenter/status")
        self.declare_parameter("simulation_status_topic", "/atlas/simulation/status")
        self.declare_parameter("vision_detections_topic", "/atlas/vision_detections")
        self.declare_parameter("camera_topic", "/camera/image_raw")
        self.declare_parameter(
            "gz_camera_topic",
            "/world/atlas_demo_world/model/fixed_camera/link/link/sensor/demo_camera/image",
        )

        self._host = self.get_parameter("host").get_parameter_value().string_value
        self._port = int(self.get_parameter("port").value)
        self._log_dir = self.get_parameter("log_dir").get_parameter_value().string_value
        self._gazebo_enabled = bool(self.get_parameter("gazebo_enabled").value)

        self._runtime_commands_topic = (
            self.get_parameter("runtime_commands_topic").get_parameter_value().string_value
        )

        self._state = _SharedState()
        with self._state.lock:
            self._state.logs["log_dir"] = self._log_dir

        # Keep disk IO out of /api/state.
        self._logs_timer = self.create_timer(1.0, self._update_logs_snapshot)
        self._update_logs_snapshot()

        self._cmd_pub = self.create_publisher(String, self._runtime_commands_topic, 10)

        self.create_subscription(
            String,
            self.get_parameter("telemetry_topic").get_parameter_value().string_value,
            self._on_telemetry,
            50,
        )
        self.create_subscription(
            String,
            self.get_parameter("alerts_topic").get_parameter_value().string_value,
            self._on_threat,
            50,
        )
        self.create_subscription(
            String,
            self.get_parameter("operator_commands_topic").get_parameter_value().string_value,
            self._on_operator_command,
            50,
        )
        self.create_subscription(
            String,
            self._runtime_commands_topic,
            self._on_runtime_command,
            50,
        )
        self.create_subscription(
            String,
            self.get_parameter("commandcenter_status_topic").get_parameter_value().string_value,
            self._on_commandcenter_status,
            10,
        )
        self.create_subscription(
            String,
            self.get_parameter("simulation_status_topic").get_parameter_value().string_value,
            self._on_simulation_status,
            10,
        )
        self.create_subscription(
            String,
            self.get_parameter("vision_detections_topic").get_parameter_value().string_value,
            self._on_vision_detections,
            10,
        )

        self._camera_topic = self.get_parameter("camera_topic").get_parameter_value().string_value
        self._gz_camera_topic = self.get_parameter("gz_camera_topic").get_parameter_value().string_value
        self.create_subscription(Image, self._camera_topic, self._on_camera_image, 5)


        self._cv_bridge = None
        self._cv2 = None
        self._warned_camera_unavailable = False
        try:
            from cv_bridge import CvBridge

            self._cv_bridge = CvBridge()
            import cv2  # type: ignore

            self._cv2 = cv2
            with self._state.lock:
                self._state.mjpeg_available = True
        except Exception as exc:
            with self._state.lock:
                self._state.mjpeg_available = False
                self._state.camera_error = str(exc)

        self._server = _make_server(self, self._state, host=self._host, port=self._port)
        self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._server_thread.start()

        self.get_logger().info(f"Web dashboard ready on http://localhost:{self._port}")

    def publish_runtime_command(self, payload: dict[str, Any]) -> None:
        self._cmd_pub.publish(String(data=json.dumps(payload)))

    def _on_telemetry(self, msg: String) -> None:
        tel = safe_json_loads(msg.data, self.get_logger())
        if tel is None:
            return
        vehicles_norm = _normalize_vehicles(tel)
        with self._state.lock:
            self._state.telemetry = tel
            self._state.vehicles = vehicles_norm
            self._state.last_update_ms["telemetry"] = _now_ms()

    def _on_threat(self, msg: String) -> None:
        alert = safe_json_loads(msg.data, self.get_logger())
        if alert is None:
            return
        with self._state.lock:
            self._state.threat = alert
            self._state.last_update_ms["threat"] = _now_ms()

    def _on_operator_command(self, msg: String) -> None:
        cmd = safe_json_loads(msg.data, self.get_logger())
        if cmd is None:
            return
        with self._state.lock:
            self._state.operator_command = cmd
            self._state.last_update_ms["operator_command"] = _now_ms()

    def _on_runtime_command(self, msg: String) -> None:
        cmd = safe_json_loads(msg.data, self.get_logger())
        if cmd is None:
            return
        with self._state.lock:
            self._state.runtime_command = cmd
            self._state.last_update_ms["runtime_command"] = _now_ms()
            if cmd.get("command") == "set_speed":
                try:
                    self._state.speed_mps = float(cmd.get("value"))
                except Exception:
                    pass
            if cmd.get("command") == "set_patrol_scale":
                try:
                    self._state.patrol_scale = float(cmd.get("value"))
                except Exception:
                    pass

    def _on_commandcenter_status(self, msg: String) -> None:
        st = safe_json_loads(msg.data, self.get_logger())
        if st is None:
            return
        with self._state.lock:
            self._state.commandcenter_status = st
            self._state.last_update_ms["commandcenter_status"] = _now_ms()

    def _on_simulation_status(self, msg: String) -> None:
        st = safe_json_loads(msg.data, self.get_logger())
        if st is None:
            return
        with self._state.lock:
            self._state.simulation_status = st
            self._state.last_update_ms["simulation_status"] = _now_ms()

    def _on_vision_detections(self, msg: String) -> None:
        det = safe_json_loads(msg.data, self.get_logger())
        if det is None:
            return
        with self._state.lock:
            self._state.vision_detections = det
            self._state.last_update_ms["vision_detections"] = _now_ms()

    def _on_camera_image(self, msg: Image) -> None:
        now_ms = _now_ms()
        with self._state.lock:
            self._state.last_ros_frame_ms = now_ms
            self._state.camera_width = int(getattr(msg, "width", 0) or 0)
            self._state.camera_height = int(getattr(msg, "height", 0) or 0)
            self._state.camera_encoding = str(getattr(msg, "encoding", ""))
            self._state.last_update_ms["camera_ros"] = now_ms

        # MJPEG is best-effort (dashboard must not fake frames).
        if self._cv_bridge is None or self._cv2 is None:
            if not self._warned_camera_unavailable:
                self.get_logger().warning(
                    "Camera MJPEG unavailable (cv_bridge/OpenCV missing). Use rqt_image_view as fallback."
                )
                self._warned_camera_unavailable = True
            return

        try:
            frame = self._cv_bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
            ok, jpg = self._cv2.imencode(".jpg", frame, [int(self._cv2.IMWRITE_JPEG_QUALITY), 70])
            if not ok:
                return
            with self._state.lock:
                self._state.latest_jpeg = bytes(jpg)
                self._state.last_update_ms["camera_mjpeg"] = now_ms
        except Exception as exc:
            with self._state.lock:
                self._state.camera_error = str(exc)


    def _update_logs_snapshot(self) -> None:
        tel_path = os.path.join(self._log_dir, "telemetry_log.jsonl")
        thr_path = os.path.join(self._log_dir, "threat_log.jsonl")
        cmd_path = os.path.join(self._log_dir, "command_log.jsonl")
        inc_path = os.path.join(self._log_dir, "incident_log.jsonl")

        files = {
            "telemetry_log.jsonl": os.path.exists(tel_path),
            "threat_log.jsonl": os.path.exists(thr_path),
            "command_log.jsonl": os.path.exists(cmd_path),
            "incident_log.jsonl": os.path.exists(inc_path),
        }

        tail = {
            "telemetry": _tail_jsonl(tel_path, 8) if files["telemetry_log.jsonl"] else [],
            "threat": _tail_jsonl(thr_path, 8) if files["threat_log.jsonl"] else [],
            "command": _tail_jsonl(cmd_path, 12) if files["command_log.jsonl"] else [],
            "incident": _tail_jsonl(inc_path, 12) if files["incident_log.jsonl"] else [],
        }

        with self._state.lock:
            self._state.logs = {
                "log_dir": self._log_dir,
                "files": files,
                "tail": tail,
            }
            self._state.last_update_ms["logs"] = _now_ms()

    def destroy_node(self) -> bool:
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception:
            pass
        return super().destroy_node()


def _make_server(node: DemoWebDashboardNode, state: _SharedState, host: str, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        server_version = "ATLASDemoWeb/1.0"

        def _send_json(self, payload: Any, status: int = 200) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_text(self, text: str, status: int = 200, content_type: str = "text/plain") -> None:
            data = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except Exception as exc:
                raise ValueError(f"Invalid JSON: {exc}")
            if not isinstance(parsed, dict):
                raise ValueError("JSON payload must be an object")
            return parsed

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/" or self.path.startswith("/?"):
                self._send_text(_HTML, status=200, content_type="text/html; charset=utf-8")
                return

            if self.path == "/favicon.ico":
                # Ignore favicon requests (avoid noisy browser warnings).
                self.send_response(204)
                self.end_headers()
                return

            if self.path == "/api/state":
                # /api/state must be fast and non-blocking:
                # - return only cached in-memory state
                # - no subprocess/gz/camera probing
                # - no synchronous log tailing
                with state.lock:
                    tel = state.telemetry
                    vehicles = list(state.vehicles)
                    threat = state.threat
                    cc = state.commandcenter_status
                    sim = state.simulation_status
                    op = state.operator_command
                    rt = state.runtime_command
                    det = state.vision_detections
                    mjpeg_ok = state.mjpeg_available
                    cam_err = state.camera_error
                    last_updates = dict(state.last_update_ms)
                    speed_mps = state.speed_mps
                    patrol_scale = state.patrol_scale
                    logs = dict(state.logs)


                last_command = "-"
                if isinstance(rt, dict) and rt.get("command"):
                    last_command = "runtime:" + str(rt.get("command"))
                elif isinstance(op, dict) and op.get("type"):
                    last_command = str(op.get("type"))

                vision_summary = "-"
                if isinstance(det, dict):
                    dc = det.get("detection_count")
                    if isinstance(dc, int):
                        vision_summary = str(dc)

                now_ms = _now_ms()

                if bool(node._gazebo_enabled) is False:
                    camera_status = "Gazebo disabled in stable dashboard mode"
                else:
                    if bool(mjpeg_ok):
                        camera_status = "Camera MJPEG available"
                    elif cam_err:
                        camera_status = f"Camera unavailable: {cam_err}"
                    else:
                        camera_status = "Camera unavailable"


                payload = {
                    "timestamp_ms": now_ms,
                    "note": "QGC shows global MAVLink coordinates; Gazebo uses local simulation coordinates. Both are driven by /atlas/demo/telemetry.",
                    "telemetry": tel,
                    "vehicles": vehicles,
                    "gazebo_enabled": bool(node._gazebo_enabled),
                    "threat": threat,
                    "operator_command": op,
                    "runtime_command": rt,
                    "commandcenter_status": cc,
                    "simulation_status": sim,
                    "vision_detections": det,
                    "vision_summary": vision_summary,
                    "last_command": last_command,
                    "logs": logs,
                    "camera_status": camera_status,
                    "last_updates_ms": last_updates,
                    "speed_mps": speed_mps,
                    "patrol_scale": patrol_scale,
                }
                self._send_json(payload)
                return

            if self.path.startswith("/api/logs/"):
                # Simple log download endpoint (operator evidence export).
                name = self.path[len("/api/logs/") :]
                name = name.split("?", 1)[0]

                allowed = {
                    "telemetry_log.jsonl",
                    "threat_log.jsonl",
                    "command_log.jsonl",
                    "incident_log.jsonl",
                    "telemetry_log.csv",
                }
                if name not in allowed:
                    self._send_text("forbidden", status=403)
                    return

                base = os.path.abspath(node._log_dir)
                path = os.path.abspath(os.path.join(base, name))
                if not path.startswith(base + os.sep):
                    self._send_text("forbidden", status=403)
                    return

                try:
                    with open(path, "rb") as fp:
                        data = fp.read()
                except FileNotFoundError:
                    self._send_text("not found", status=404)
                    return
                except Exception as exc:
                    self._send_text(f"error: {exc}", status=500)
                    return

                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Content-Disposition", f"attachment; filename=\"{name}\"")
                self.end_headers()
                self.wfile.write(data)
                return

            if self.path == "/camera.mjpg":
                # MJPEG multipart stream.
                with state.lock:
                    mjpeg_ok = state.mjpeg_available
                if not mjpeg_ok:
                    self._send_text("camera unavailable", status=503)
                    return

                self.send_response(200)
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Pragma", "no-cache")
                self.send_header("Connection", "close")
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.end_headers()

                try:
                    while True:
                        with state.lock:
                            jpg = state.latest_jpeg
                        if jpg is not None:
                            self.wfile.write(b"--frame\r\n")
                            self.wfile.write(b"Content-Type: image/jpeg\r\n")
                            self.wfile.write(f"Content-Length: {len(jpg)}\r\n\r\n".encode("utf-8"))
                            self.wfile.write(jpg)
                            self.wfile.write(b"\r\n")
                        time.sleep(0.2)
                except BrokenPipeError:
                    return
                except ConnectionResetError:
                    return
                except Exception:
                    return

            self._send_text("not found", status=404)

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/command":
                self._send_text("not found", status=404)
                return

            try:
                payload = self._read_json()
            except ValueError as exc:
                self._send_text(str(exc), status=400)
                return

            command = payload.get("command")
            if not isinstance(command, str) or not command.strip():
                self._send_text("Missing/invalid 'command'", status=400)
                return

            # Publish as-is (demo_mission_state_node validates/ignores unknown commands).
            try:
                node.publish_runtime_command(payload)
            except Exception as exc:
                self._send_text(f"Failed to publish command: {exc}", status=500)
                return

            self._send_text("published", status=200)

        def log_message(self, format: str, *args: Any) -> None:
            # Keep HTTP logs quiet; ROS logs already show system state.
            return

    return ThreadingHTTPServer((host, port), Handler)


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = DemoWebDashboardNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
