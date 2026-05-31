#!/usr/bin/env bash
set -eo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
ATLAS integrated final demo launcher.

Usage:
  ./scripts/run_atlas_final_demo.sh [options]

Stable defaults:
  - Gazebo OFF (stable in Docker/NixOS)
  - Web dashboard ON (http://localhost:8088)
  - 3-UAV telemetry + QGC MAVLink bridge ON

Options:
  --gazebo            Start Gazebo (experimental; may be unstable)
  --qgc               Attempt to start QGroundControl (host, if available)
  --tmux              Force tmux workspace (if available)
  --no-tmux           Disable tmux workspace
  --no-build          Skip colcon build step
  --port PORT         Dashboard port (default: 8088)
  --no-open           Do not attempt to open browser
  -h, --help          Show this help

Stop:
  - tmux: Ctrl-b then type ':kill-session' (or just close terminals)
  - non-tmux: Ctrl-C in the running terminal
EOF
}

want_gazebo=false
want_qgc=false
want_tmux=auto
want_build=true
want_open=true
web_port=8088

while [[ $# -gt 0 ]]; do
  case "$1" in
    --gazebo) want_gazebo=true; shift ;;
    --qgc) want_qgc=true; shift ;;
    --tmux) want_tmux=true; shift ;;
    --no-tmux) want_tmux=false; shift ;;
    --no-build) want_build=false; shift ;;
    --no-open) want_open=false; shift ;;
    --port) web_port="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1"; usage; exit 2 ;;
  esac
done

if [[ -z "${web_port}" ]]; then
  echo "Missing --port value" >&2
  exit 2
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose is required" >&2
  exit 1
fi

if [[ "$want_tmux" == "auto" ]]; then
  if command -v tmux >/dev/null 2>&1 && [[ -t 1 ]]; then
    want_tmux=true
  else
    want_tmux=false
  fi
fi

launch_args=(
  "start_web_dashboard:=true"
  "start_gazebo:=${want_gazebo}"
  "start_rqt_image_view:=false"
  "start_vision_node:=true"
  "auto_demo_threat:=false"
  "web_dashboard_port:=${web_port}"
)

build_snippet=""
if [[ "$want_build" == "true" ]]; then
  build_snippet=$'colcon build --packages-select atlas_ros_bridge >/dev/null || exit 1\n'
fi

ros_cmd=$(cat <<EOF
set -eo pipefail
source /opt/ros/jazzy/setup.bash
cd /ros_ws
${build_snippet}source install/setup.bash
ros2 launch atlas_ros_bridge atlas_final_demo.launch.py ${launch_args[*]}
EOF
)

print_header() {
  cat <<EOF
ATLAS Final Demo (stable mode)

Official dashboard (main UI):
  http://localhost:${web_port}
Backend API (debug):
  http://localhost:${web_port}/api/state

QGroundControl (host, native app):
  - NixOS:   nix shell nixpkgs#qgroundcontrol -c QGroundControl
  - Ubuntu:  download/run QGroundControl AppImage (or 'qgroundcontrol' if installed)
  QGC listens on UDP port 14550

Runtime commands (from container):
  docker compose exec atlas-ros bash -lc 'source /opt/ros/jazzy/setup.bash; source /ros_ws/install/setup.bash; ros2 topic pub -1 /atlas/demo/runtime_commands std_msgs/msg/String "{data: \"{\\\"command\\\":\\\"rtl\\\"}\"}"'
  docker compose exec atlas-ros bash -lc 'source /opt/ros/jazzy/setup.bash; source /ros_ws/install/setup.bash; ros2 topic pub -1 /atlas/demo/runtime_commands std_msgs/msg/String "{data: \"{\\\"command\\\":\\\"pause\\\"}\"}"'
  docker compose exec atlas-ros bash -lc 'source /opt/ros/jazzy/setup.bash; source /ros_ws/install/setup.bash; ros2 topic pub -1 /atlas/demo/runtime_commands std_msgs/msg/String "{data: \"{\\\"command\\\":\\\"resume\\\"}\"}"'

Stop:
  Ctrl-C in the ROS launch pane/terminal
EOF
}

health_cmd=$(cat <<EOF
set -eo pipefail
url="http://localhost:${web_port}/api/state"
echo "Polling dashboard state: $url"
while true; do
  ts="$(date +%H:%M:%S)"
  if curl -fsS "$url" >/dev/null 2>&1; then
    echo "[$ts] dashboard: OK"
  else
    echo "[$ts] dashboard: not ready"
  fi
  sleep 2
done
EOF
)

runtime_help=$(cat <<'EOF'
Runtime commands quick reference:

- Return-to-launch (RTL):
  ros2 topic pub -1 /atlas/demo/runtime_commands std_msgs/msg/String '{data: "{\"command\":\"rtl\"}"}'

- Pause/resume mission:
  ros2 topic pub -1 /atlas/demo/runtime_commands std_msgs/msg/String '{data: "{\"command\":\"pause\"}"}'
  ros2 topic pub -1 /atlas/demo/runtime_commands std_msgs/msg/String '{data: "{\"command\":\"resume\"}"}'

- Trigger threat (no Gazebo required):
  ros2 topic pub -1 /atlas/demo/runtime_commands std_msgs/msg/String '{data: "{\"command\":\"trigger_threat\",\"level\":\"HIGH\"}"}'

- Clear threat:
  ros2 topic pub -1 /atlas/demo/runtime_commands std_msgs/msg/String '{data: "{\"command\":\"clear_threat\"}"}'
EOF
)

qgc_cmd_nix=$'nix shell nixpkgs#qgroundcontrol -c QGroundControl'
qgc_cmd_generic=$'QGroundControl'

mkdir -p "$ROOT_DIR/ros_ws/log" >/dev/null 2>&1 || true

echo "Starting container (atlas-ros)…"
docker compose up -d atlas-ros >/dev/null

print_header

if [[ "$want_open" == "true" ]] && command -v xdg-open >/dev/null 2>&1; then
  (xdg-open "http://localhost:${web_port}" >/dev/null 2>&1 || true) &
fi

if [[ "$want_qgc" == "true" ]]; then
  echo "Launching QGroundControl (host)…"
  if command -v QGroundControl >/dev/null 2>&1; then
    (QGroundControl >/dev/null 2>&1 || true) &
  elif command -v qgroundcontrol >/dev/null 2>&1; then
    (qgroundcontrol >/dev/null 2>&1 || true) &
  elif command -v nix >/dev/null 2>&1; then
    (bash -lc "$qgc_cmd_nix" >/dev/null 2>&1 || true) &
  else
    echo "QGC not found. Install/run QGroundControl (AppImage on Ubuntu), or on NixOS run: $qgc_cmd_nix"
  fi
fi

if [[ "$want_tmux" == "true" ]]; then
  session="atlas-final-demo"
  if tmux has-session -t "$session" >/dev/null 2>&1; then
    echo "tmux session '$session' already exists; attaching"
    tmux attach -t "$session"
    exit 0
  fi

  tmux new-session -d -s "$session" -n demo
  tmux send-keys -t "$session":0.0 "docker compose exec atlas-ros bash -lc $(printf %q "$ros_cmd")" C-m

  tmux split-window -h -t "$session":0
  tmux send-keys -t "$session":0.1 "docker compose exec atlas-ros bash -lc $(printf %q "$health_cmd")" C-m

  tmux split-window -v -t "$session":0.0
  tmux send-keys -t "$session":0.2 "docker compose exec atlas-ros bash -lc $(printf %q "echo '$runtime_help'; bash")" C-m

  tmux split-window -v -t "$session":0.1
  tmux send-keys -t "$session":0.3 "bash -lc $(printf %q "echo 'QGC:'; echo '  NixOS:  nix shell nixpkgs#qgroundcontrol -c QGroundControl'; echo '  Ubuntu: run QGroundControl AppImage (or qgroundcontrol)'; echo '  UDP:    14550'; echo; echo 'Gazebo:'; echo '  re-run with --gazebo (experimental)'; echo; echo 'Dashboard:'; echo '  http://localhost:${web_port}'; bash")" C-m

  tmux select-layout -t "$session":0 tiled >/dev/null
  echo "Attaching tmux session '$session'…"
  tmux attach -t "$session"
  exit 0
fi

echo "Running ROS demo in foreground…"
docker compose exec atlas-ros bash -lc "$ros_cmd"
