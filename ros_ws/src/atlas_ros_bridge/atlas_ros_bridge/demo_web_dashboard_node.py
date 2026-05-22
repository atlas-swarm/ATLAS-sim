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


_HTML = """<!doctype html>
<html>
<head>
  <meta charset=
    "utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ATLAS Final Demo</title>
  <style>
    :root {
      --bg: #0b1020;
      --panel: #111a33;
      --panel2: #0f1730;
      --text: #e9eefc;
      --muted: #aeb7d6;
      --ok: #27d07d;
      --warn: #ffcc66;
      --bad: #ff5c6c;
      --accent: #69a7ff;
    }
    body { margin:0; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; background: var(--bg); color: var(--text); }
    header { padding: 14px 16px; background: linear-gradient(90deg, #121b36, #0b1020); border-bottom: 1px solid #22305f; }
    header h1 { margin: 0; font-size: 18px; letter-spacing: 0.4px; }
    header .sub { margin-top: 4px; color: var(--muted); font-size: 12px; }
    .grid { display: grid; grid-template-columns: 1.2fr 1fr; gap: 12px; padding: 12px; }
    .panel { background: var(--panel); border: 1px solid #22305f; border-radius: 10px; padding: 12px; }
    .panel h2 { margin: 0 0 10px 0; font-size: 14px; color: #d9e4ff; }
    .row { display:flex; gap: 10px; flex-wrap: wrap; }
    .k { color: var(--muted); }
    .v { color: var(--text); }
    .pill { display:inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; border:1px solid #2a3a77; background: var(--panel2); }
    .pill.ok { border-color: #1b7a4a; color: var(--ok); }
    .pill.warn { border-color: #a77f1b; color: var(--warn); }
    .pill.bad { border-color: #8a1f2d; color: var(--bad); }
    .cards { display:grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
    .card { background: var(--panel2); border: 1px solid #22305f; border-radius: 10px; padding: 10px; }
    .card h3 { margin: 0 0 8px 0; font-size: 13px; }
    .kv { display:grid; grid-template-columns: 110px 1fr; gap: 4px 10px; font-size: 12px; }
    button { background: #1b2b57; border: 1px solid #2a3a77; color: var(--text); padding: 8px 10px; border-radius: 10px; cursor:pointer; font-size: 12px; }
    button:hover { border-color: #4d69d7; }
    button.primary { background: #22408a; }
    button.danger { background: #6a1f2d; border-color: #8a1f2d; }
    button.good { background: #1b5a3b; border-color: #1b7a4a; }
    .cmdgrid { display:grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
    .flex { display:flex; gap:10px; align-items:center; }
    input[type=number] { background: var(--panel2); border:1px solid #22305f; color: var(--text); padding: 7px 8px; border-radius: 10px; width: 90px; }
    canvas { width: 100%; height: 260px; background: #0a0f22; border: 1px solid #22305f; border-radius: 10px; }
    img.cam { width: 100%; height: 260px; object-fit: cover; background: #0a0f22; border: 1px solid #22305f; border-radius: 10px; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; color: #cfe0ff; }
    .small { font-size: 12px; color: var(--muted); }
    .split { display:grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    @media (max-width: 1000px) {
      .grid { grid-template-columns: 1fr; }
      .cards { grid-template-columns: 1fr; }
      .cmdgrid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .split { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <h1>ATLAS Final Demo — Unified Dashboard</h1>
    <div class="sub">Single-screen observe + control: telemetry, threat, vision, commands, logs.</div>
  </header>

  <div class="grid">
    <div class="panel">
      <h2>Mission Overview</h2>
      <div class="row">
        <span class="pill" id="pillMission">MISSION</span>
        <span class="pill" id="pillMode">MODE</span>
        <span class="pill" id="pillThreat">THREAT</span>
        <span class="pill" id="pillCamera">CAMERA</span>
      </div>
      <div style="height:10px"></div>
      <div class="split">
        <div>
          <div class="small">Swarm / UAV Cards</div>
          <div style="height:8px"></div>
          <div class="cards" id="uavCards"></div>
        </div>
        <div>
          <div class="small">Map View (local x/y)</div>
          <div style="height:8px"></div>
          <canvas id="map" width="600" height="320"></canvas>
        </div>
      </div>
      <div style="height:10px"></div>
      <div class="small">Telemetry Table</div>
      <div class="mono" id="telTable">-</div>
    </div>

    <div class="panel">
      <h2>Camera View</h2>
      <img class="cam" id="cam" src="/camera.mjpg" alt="camera" />
      <div class="small" id="camHint" style="margin-top:6px"></div>
    </div>

    <div class="panel">
      <h2>Threat / Scoring</h2>
      <div class="kv" style="grid-template-columns: 140px 1fr">
        <div class="k">Level</div><div class="v" id="threatLevel">NONE</div>
        <div class="k">Object</div><div class="v" id="threatObject">-</div>
        <div class="k">Final score</div><div class="v" id="threatScore">-</div>
        <div class="k">Affiliation</div><div class="v" id="threatAff">-</div>
        <div class="k">Behavior</div><div class="v" id="threatBeh">-</div>
        <div class="k">Action</div><div class="v" id="threatAction">-</div>
        <div class="k">Source</div><div class="v" id="threatSource">-</div>
      </div>
      <div style="height:8px"></div>
      <div class="small">Reason</div>
      <div class="mono" id="threatReason">-</div>
    </div>

    <div class="panel">
      <h2>Command Panel</h2>
      <div class="cmdgrid">
        <button class="good" onclick="sendCmd({command:'resume'})">Resume</button>
        <button onclick="sendCmd({command:'pause'})">Pause</button>
        <button class="danger" onclick="sendCmd({command:'rtl'})">RTL</button>
        <button class="primary" onclick="sendCmd({command:'reset_demo'})">Reset Demo</button>

        <button class="danger" onclick="sendCmd({command:'trigger_threat', level:'HIGH', object_type:'person', reason:'dashboard trigger'})">Trigger HIGH Threat</button>
        <button onclick="sendCmd({command:'clear_threat'})">Clear Threat</button>

        <button onclick="bumpSpeed(-1.0)">Speed -</button>
        <button onclick="bumpSpeed(+1.0)">Speed +</button>
      </div>
      <div style="height:10px"></div>
      <div class="flex">
        <div class="small">Speed:</div>
        <input id="speed" type="number" step="0.5" value="4.0" />
        <button onclick="sendCmd({command:'set_speed', value: parseFloat(document.getElementById('speed').value)})">Set Speed</button>

        <div style="width:10px"></div>
        <div class="small">Patrol scale:</div>
        <input id="scale" type="number" step="0.25" value="1.0" />
        <button onclick="sendCmd({command:'set_patrol_scale', value: parseFloat(document.getElementById('scale').value)})">Set Scale</button>
      </div>
      <div style="height:8px"></div>
      <div class="small" id="cmdResult"></div>
    </div>

    <div class="panel">
      <h2>System Status</h2>
      <div class="kv" style="grid-template-columns: 170px 1fr">
        <div class="k">CommandCenter bridge</div><div class="v" id="cc">-</div>
        <div class="k">Simulation bridge</div><div class="v" id="sim">-</div>
        <div class="k">Last command</div><div class="v" id="lastCmd">-</div>
        <div class="k">Vision detections</div><div class="v" id="vision">-</div>
      </div>
    </div>

    <div class="panel">
      <h2>Logs / Events</h2>
      <div class="small">Log directory</div>
      <div class="mono" id="logDir">-</div>
      <div style="height:8px"></div>

      <div class="small">Log file status</div>
      <div class="mono" id="logFiles">-</div>
      <div style="height:8px"></div>

      <div class="small">Recent Commands</div>
      <div class="mono" id="cmdHist">-</div>
      <div style="height:8px"></div>

      <div class="small">Recent Threats</div>
      <div class="mono" id="thrHist">-</div>
      <div style="height:8px"></div>

      <div class="small">Recent Incidents</div>
      <div class="mono" id="incHist">-</div>

      <div style="height:8px"></div>
      <details>
        <summary class="small">Raw JSON (tail)</summary>
        <div class="mono" id="rawLogs">-</div>
      </details>
    </div>
  </div>

<script>
let lastState = null;

function pill(el, text, cls) {
  el.textContent = text;
  el.className = 'pill ' + cls;
}

function fmt(n, digits) {
  if (typeof n !== 'number' || !isFinite(n)) return '-';
  return n.toFixed(digits);
}

function fmtTime(ms) {
  if (typeof ms !== 'number' || !isFinite(ms)) return '';
  try {
    return new Date(ms).toLocaleTimeString();
  } catch (_) {
    return String(ms);
  }
}

function shortPayload(p) {
  if (!p || typeof p !== 'object') return '';
  const keep = ['value','level','object_type','reason','mode','target_uav'];
  const parts = [];
  for (const k of keep) {
    if (p[k] !== undefined) parts.push(`${k}=${String(p[k])}`);
  }
  if (!parts.length) return '';
  return parts.join(' ');
}

function renderCommands(entries) {
  return entries.map(e => {
    const t = fmtTime(e.timestamp);
    const cmd = e.command || '';
    const src = e.source || '';
    const pay = shortPayload(e.payload);
    return `${t}  ${cmd}  (${src})${pay ? '  ' + pay : ''}`;
  }).join('\n');
}

function renderThreats(entries) {
  const out = [];
  for (const e of entries) {
    const t = fmtTime(e.timestamp);
    const assessments = Array.isArray(e.assessments) ? e.assessments : [];
    if (!assessments.length) {
      out.push(`${t}  NONE  (cleared)`);
      continue;
    }
    for (const a of assessments.slice(0,3)) {
      const lvl = a.threat_level || 'UNKNOWN';
      const obj = a.object_type || '-';
      const score = (typeof a.final_threat_score === 'number') ? a.final_threat_score.toFixed(2) : '-';
      const reason = a.reason || '';
      const act = a.recommended_action || e.recommendedAction || '';
      out.push(`${t}  ${lvl}  ${obj}  score=${score}${act ? '  action=' + act : ''}${reason ? '  ' + reason : ''}`);
    }
  }
  return out.join('\n');
}

function renderIncidents(entries) {
  return entries.map(e => {
    const t = fmtTime(e.timestamp);
    const cat = e.category || e.type || '';
    const msg = e.message || '';
    return `${t}  ${cat}  ${msg}`;
  }).join('\n');
}

async function sendCmd(payload) {
  const box = document.getElementById('cmdResult');
  box.textContent = 'sending...';
  try {
    const res = await fetch('/api/command', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
    const txt = await res.text();
    if (!res.ok) {
      box.textContent = 'ERROR ' + res.status + ': ' + txt;
    } else {
      const c = payload && payload.command ? String(payload.command) : 'command';
      box.textContent = 'Command sent: ' + c;
    }
  } catch (e) {
    box.textContent = 'ERROR: ' + e;
  }
}

function bumpSpeed(delta) {
  let v = parseFloat(document.getElementById('speed').value || '4.0');
  v = Math.max(0.5, Math.min(20.0, v + delta));
  document.getElementById('speed').value = v.toFixed(1);
  sendCmd({command:'set_speed', value:v});
}

function drawMap(state) {
  const canvas = document.getElementById('map');
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0,0,canvas.width,canvas.height);

  // Background grid
  ctx.strokeStyle = '#1b2b57';
  ctx.lineWidth = 1;
  for (let x=0; x<canvas.width; x+=50) { ctx.beginPath(); ctx.moveTo(x,0); ctx.lineTo(x,canvas.height); ctx.stroke(); }
  for (let y=0; y<canvas.height; y+=50) { ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(canvas.width,y); ctx.stroke(); }

  const vehicles = Array.isArray(state.vehicles) ? state.vehicles : [];
  if (!vehicles.length) return;

  // Scale around current extents
  let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
  for (const v of vehicles) {
    if (typeof v.x === 'number' && typeof v.y === 'number') {
      minX = Math.min(minX, v.x); maxX = Math.max(maxX, v.x);
      minY = Math.min(minY, v.y); maxY = Math.max(maxY, v.y);
    }
  }
  if (!isFinite(minX)) return;

  const pad = 10;
  const spanX = Math.max(10, maxX-minX);
  const spanY = Math.max(10, maxY-minY);
  const sx = (canvas.width - 2*pad) / spanX;
  const sy = (canvas.height - 2*pad) / spanY;
  const s = Math.min(sx, sy);

  function mapPt(x,y) {
    const px = pad + (x - minX) * s;
    const py = canvas.height - (pad + (y - minY) * s);
    return [px, py];
  }

  const colors = {'uav_1':'#69a7ff','uav_2':'#35e38c','uav_3':'#ff5c6c'};

  for (const v of vehicles) {
    const [px,py] = mapPt(v.x||0, v.y||0);
    ctx.fillStyle = colors[v.uav_id] || '#ffffff';
    ctx.beginPath(); ctx.arc(px,py,7,0,Math.PI*2); ctx.fill();

    // heading marker
    const hd = (typeof v.heading_deg === 'number') ? v.heading_deg : 0;
    const rad = (hd/180.0)*Math.PI;
    ctx.strokeStyle = ctx.fillStyle;
    ctx.beginPath();
    ctx.moveTo(px,py);
    ctx.lineTo(px + Math.cos(rad)*14, py - Math.sin(rad)*14);
    ctx.stroke();

    ctx.fillStyle = '#cfe0ff';
    ctx.font = '12px ui-monospace, monospace';
    ctx.fillText(v.uav_id || 'uav', px+10, py-10);
  }
}

function updateUI(state) {
  lastState = state;

  const tel = state.telemetry || {};
  const missionState = (tel.mission_state || '-');
  const flightMode = (tel.flight_mode || '-');

  const pillMission = document.getElementById('pillMission');
  const pillMode = document.getElementById('pillMode');
  const pillThreat = document.getElementById('pillThreat');
  const pillCamera = document.getElementById('pillCamera');

  const threat = state.threat || {};
  const assessments = Array.isArray(threat.assessments) ? threat.assessments : [];
  const top = assessments.length ? assessments[0] : null;
  const threatLevel = top ? (top.threat_level || 'NONE') : 'NONE';

  pill(pillMission, 'Mission: ' + missionState, (missionState==='RUNNING') ? 'ok' : (missionState==='PAUSED' ? 'warn' : 'warn'));
  pill(pillMode, 'Mode: ' + flightMode, (flightMode==='AUTO') ? 'ok' : (flightMode==='RTL' ? 'warn' : 'warn'));
  pill(pillThreat, 'Threat: ' + threatLevel, (threatLevel==='HIGH') ? 'bad' : (threatLevel==='MEDIUM' ? 'warn' : 'ok'));

  const camStatus = (typeof state.camera_status === 'string') ? state.camera_status : '';
  if (state.gazebo_enabled === false) {
    pill(pillCamera, 'Camera: Gazebo off', 'warn');
  } else {
    pill(pillCamera, camStatus ? ('Camera: ' + camStatus) : 'Camera: enabled', 'ok');
  }

  // UAV cards
  const cards = document.getElementById('uavCards');
  cards.innerHTML = '';
  const vehicles = Array.isArray(state.vehicles) ? state.vehicles : [];
  if (!vehicles.length) {
    cards.innerHTML = '<div class="card"><h3>No telemetry received yet</h3><div class="small">Waiting for /atlas/demo/telemetry...</div></div>';
  }
  for (const v of vehicles) {
    const div = document.createElement('div');
    div.className = 'card';
    div.innerHTML = `
      <h3>${v.uav_id || 'uav'}</h3>
      <div class="kv">
        <div class="k">Mission</div><div class="v">${v.mission_state || missionState}</div>
        <div class="k">Mode</div><div class="v">${v.flight_mode || flightMode}</div>
        <div class="k">Lat/Lon</div><div class="v">${fmt(v.lat,5)}, ${fmt(v.lon,5)}</div>
        <div class="k">Alt</div><div class="v">${fmt(v.alt,1)} m</div>
        <div class="k">Local</div><div class="v">x=${fmt(v.x,1)} y=${fmt(v.y,1)} z=${fmt(v.z,1)}</div>
        <div class="k">Battery</div><div class="v">${fmt(v.battery_pct,1)} %</div>
      </div>`;
    cards.appendChild(div);
  }

  // Threat panel (presentation-friendly)
  const threatLevelEl = document.getElementById('threatLevel');
  const threatObjectEl = document.getElementById('threatObject');
  const threatScoreEl = document.getElementById('threatScore');
  const threatAffEl = document.getElementById('threatAff');
  const threatBehEl = document.getElementById('threatBeh');
  const threatActionEl = document.getElementById('threatAction');
  const threatSourceEl = document.getElementById('threatSource');
  const threatReasonEl = document.getElementById('threatReason');

  const topA = (assessments && assessments.length) ? assessments[0] : null;
  threatLevelEl.textContent = topA ? (topA.threat_level || 'NONE') : 'NONE';
  threatObjectEl.textContent = topA ? (topA.object_type || '-') : '-';
  threatScoreEl.textContent = topA && typeof topA.final_threat_score === 'number' ? topA.final_threat_score.toFixed(2) : '-';
  threatAffEl.textContent = topA ? `${topA.affiliation || '-'} (${fmt(topA.affiliation_score,2)})` : '-';
  threatBehEl.textContent = topA ? fmt(topA.behavior_score,2) : '-';
  threatActionEl.textContent = topA ? (topA.recommended_action || threat.recommendedAction || '-') : (threat.recommendedAction || '-');
  threatSourceEl.textContent = threat.source || '-';
  threatReasonEl.textContent = topA ? (topA.reason || '-') : '-';

  // System status
  document.getElementById('cc').textContent = JSON.stringify(state.commandcenter_status || {}, null, 0);
  document.getElementById('sim').textContent = JSON.stringify(state.simulation_status || {}, null, 0);
  document.getElementById('lastCmd').textContent = state.last_command || '-';
  document.getElementById('vision').textContent = state.vision_summary || '-';

  // Logs/events panel (human-friendly rendering)
  const logs = state.logs || {};
  document.getElementById('logDir').textContent = logs.log_dir || '-';

  const files = logs.files || {};
  const fileOrder = ['telemetry_log.jsonl','threat_log.jsonl','command_log.jsonl','incident_log.jsonl'];
  const fileLines = fileOrder.map(name => `${name}: ${files[name] ? 'OK' : 'missing'}`);
  document.getElementById('logFiles').textContent = fileLines.join('\n');

  const cmdTail = (logs.tail && Array.isArray(logs.tail.command)) ? logs.tail.command : [];
  const thrTail = (logs.tail && Array.isArray(logs.tail.threat)) ? logs.tail.threat : [];
  const incTail = (logs.tail && Array.isArray(logs.tail.incident)) ? logs.tail.incident : [];

  document.getElementById('cmdHist').textContent = renderCommands(cmdTail) || '-';
  document.getElementById('thrHist').textContent = renderThreats(thrTail) || '-';
  document.getElementById('incHist').textContent = renderIncidents(incTail) || '-';
  document.getElementById('rawLogs').textContent = JSON.stringify(logs.tail || {}, null, 2) || '-';

  // Camera hint (stable mode: no probing, no diagnostics)
  const camHint = document.getElementById('camHint');
  const camImg = document.getElementById('cam');
  const camStatusText = (typeof state.camera_status === 'string') ? state.camera_status : '';
  if (state.gazebo_enabled === false) {
    camHint.textContent = 'Gazebo disabled in stable dashboard mode.';
    camImg.style.display = 'none';
  } else {
    camHint.textContent = camStatusText || 'Gazebo enabled (camera optional).';
    camImg.style.display = 'block';
    if (!camImg.getAttribute('src')) camImg.setAttribute('src','/camera.mjpg');
  }

  // Telemetry table (readable)
  const telTable = document.getElementById('telTable');
  if (vehicles.length) {
    const lines = [];
    lines.push('uav_id sysid mode state batt% alt(m) spd(m/s) hdg(deg) x y lat lon');
    for (const v of vehicles) {
      const sysid = (v.uav_id === 'uav_1') ? 1 : (v.uav_id === 'uav_2') ? 2 : (v.uav_id === 'uav_3') ? 3 : '-';
      const spd = Math.hypot((v.vx||0),(v.vy||0));
      lines.push(`${v.uav_id||'-'} ${sysid} ${(v.flight_mode||flightMode)} ${(v.mission_state||missionState)} ${fmt(v.battery_pct,1)} ${fmt(v.alt,1)} ${fmt(spd,1)} ${fmt(v.heading_deg,0)} ${fmt(v.x,1)} ${fmt(v.y,1)} ${fmt(v.lat,5)} ${fmt(v.lon,5)}`);
    }
    telTable.textContent = lines.join('\n');
  } else {
    telTable.textContent = 'No telemetry received yet.';
  }

  drawMap(state);

  // Keep form defaults in sync if possible.
  if (typeof state.speed_mps === 'number') {
    document.getElementById('speed').value = state.speed_mps.toFixed(1);
  }
  if (typeof state.patrol_scale === 'number') {
    document.getElementById('scale').value = state.patrol_scale.toFixed(2);
  }
}

async function poll() {
  try {
    const res = await fetch('/api/state');
    const state = await res.json();
    updateUI(state);
  } catch (e) {
    // Don’t spam; leave last UI.
  }
}

setInterval(poll, 1000);
poll();
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
