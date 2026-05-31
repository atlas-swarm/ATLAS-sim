# ATLAS Integrated Final Demo

This document describes the **one-command** integrated ATLAS demo workspace (stable mode) and how it ties together the Web Dashboard + 3-UAV telemetry + QGroundControl (MAVLink).

## Quick Start (Stable)

From the repo root:

```bash
cd ~/projects/atlas
./scripts/run_atlas_final_demo.sh
```

Then open:

- Official dashboard (main UI): `http://localhost:8088`
- Backend API (debug): `http://localhost:8088/api/state`

Open QGroundControl natively on the host (listens on UDP `14550`):

- NixOS:

```bash
nix shell nixpkgs#qgroundcontrol -c QGroundControl
```

- Ubuntu/Linux (no Nix required):
  - Download/run the official **QGroundControl AppImage**, or
  - Run `qgroundcontrol` / `QGroundControl` if installed

What you should see:

- **Web dashboard**: 3 UAV cards, map positions, commands, and readable logs
- **QGC**: 3 vehicles with clearly separated tracks (telemetry stays stable; no “Communication Lost”; “Not Ready” may remain)
- **Threat → RTL**: trigger a threat from the dashboard, vehicles RTL (demo mission state)

Known limitation:

- Gazebo camera/render is **optional/experimental** in Docker on NixOS (Xvfb/Ogre/EGL instability). Stable mode does **not** require Gazebo.

## One Command Launcher

The stable orchestrator is:

- `scripts/run_atlas_final_demo.sh`

Defaults (stable):

- `start_gazebo=false`
- `start_web_dashboard=true` on port `8088`
- `start_vision_node=true` (idles safely if optional deps are missing)

Optional flags:

```bash
./scripts/run_atlas_final_demo.sh --tmux        # tmux workspace (auto if available)
./scripts/run_atlas_final_demo.sh --no-build    # skip colcon build (faster restarts)
./scripts/run_atlas_final_demo.sh --qgc         # try to launch QGC (host, if installed)
./scripts/run_atlas_final_demo.sh --gazebo      # EXPERIMENTAL Gazebo mode
./scripts/run_atlas_final_demo.sh --port 8089   # dashboard port override
```

Stop:

- **tmux mode**: `Ctrl-b` then `:kill-session` (session `atlas-final-demo`)
- **non-tmux mode**: `Ctrl-C` in the running terminal

## Architecture Summary

Stable demo dataflow:

- `atlas_ros_bridge/demo_mission_state_node.py`
  - Publishes coherent 3-UAV telemetry on `/atlas/demo/telemetry`
  - Accepts runtime commands on `/atlas/demo/runtime_commands`
  - Can auto-RTL on threat alerts
- `atlas_ros_bridge/qgc_mavlink_bridge_node.py`
  - Mirrors `/atlas/demo/telemetry` into MAVLink UDP to QGC (`127.0.0.1:14550`)
- `atlas_ros_bridge/demo_web_dashboard_node.py`
  - Serves the **official** dashboard UI on `http://localhost:8088` + `/api/state` JSON
  - Renders defensively from `state.vehicles[]` (won’t blank if optional fields are missing)
  - In stable mode (`start_gazebo=false`), replaces the camera panel with a Simulation/Gazebo status panel

Launch entrypoint:

- `ros_ws/src/atlas_ros_bridge/launch/atlas_final_demo.launch.py`

Stable launch arguments used by the one-command script:

```bash
ros2 launch atlas_ros_bridge atlas_final_demo.launch.py \
  start_web_dashboard:=true \
  start_gazebo:=false \
  start_rqt_image_view:=false \
  start_vision_node:=true \
  auto_demo_threat:=false
```

## Dashboard

Open `http://localhost:8088`.

Key sections:

- **UAV cards**: vehicle status, modes, battery
- **Map**: live lat/lon positions for all 3 UAVs
- **Commands**: pause/resume/RTL, trigger/clear threat
- **Logs**: tail of JSONL runtime logs

Stable mode behavior:

- Gazebo/camera is not required.
- The camera panel shows a clear “Gazebo disabled …” message.

## QGroundControl Notes

How to run:

```bash
nix shell nixpkgs#qgroundcontrol -c QGroundControl
```

Expected behavior:

- You may see **“Not Ready”** because this is a lightweight MAVLink demo bridge (not full PX4/ArduPilot).
- Telemetry should remain stable (no “Communication Lost”).
- The demo mission state publishes a wide patrol + spaced formation so that 3 vehicles are visually separated.

## Runtime Commands

The easiest way is using the dashboard buttons.

CLI examples (from the host):

```bash
docker compose exec atlas-ros bash -lc \
  'source /opt/ros/jazzy/setup.bash; source /ros_ws/install/setup.bash; \
   ros2 topic pub -1 /atlas/demo/runtime_commands std_msgs/msg/String "{data: \"{\\\"command\\\":\\\"rtl\\\"}\"}"'
```

Other commands:

- Pause: `{"command":"pause"}`
- Resume: `{"command":"resume"}`
- Trigger threat: `{"command":"trigger_threat","level":"HIGH"}`
- Clear threat: `{"command":"clear_threat"}`

## Logs

Default log directory (inside container):

- `/ros_ws/log/atlas_demo`

Because `docker-compose.yml` mounts `./ros_ws` into the container, logs will appear on the host under:

- `ros_ws/log/atlas_demo`

## Optional Gazebo Mode (Experimental)

Enable with:

```bash
./scripts/run_atlas_final_demo.sh --gazebo
```

Notes:

- This may fail or be unstable depending on your host graphics stack / drivers.
- Stable demo (dashboard + QGC + telemetry + threat→RTL) does not depend on Gazebo.

## Troubleshooting

- Dashboard not reachable:
  - Ensure container is running: `docker compose ps`
  - Check for the dashboard log line in the ROS launch pane.
  - If the port is in use, run `./scripts/run_atlas_final_demo.sh --port 8089`.

- QGC doesn’t show vehicles:
  - Verify MAVLink UDP is enabled (bridge node running).
  - Check you don’t have a firewall blocking UDP on `14550`.

- Emergency fallback dashboard (debug only):
  - `scripts/emergency_dashboard.py` can be run to serve a minimal UI on `http://localhost:8090` that reads the same upstream API at `http://localhost:8088/api/state`.
  - This is for troubleshooting only; the official demo dashboard is `http://localhost:8088`.

- Gazebo crashes:
  - Use stable mode (default, no `--gazebo`).
  - If you must try Gazebo, prefer `gazebo_render_mode:=xvfb` from a manual launch.
