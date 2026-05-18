#!/bin/bash
set -euo pipefail

# Starts a virtual X server + lightweight WM + VNC + noVNC.
# Intended for running GUI apps (e.g., Gazebo) inside Docker without host X11.
#
# Usage (inside container):
#   /start_vnc_gazebo.sh
#   export DISPLAY=:1
#   ros2 launch atlas_ros_bridge atlas_gazebo_demo.launch.py gui:=true
#
# noVNC will be available on: http://localhost:6080

DISPLAY_NUM=${DISPLAY_NUM:-1}
DISPLAY=":${DISPLAY_NUM}"
RESOLUTION=${RESOLUTION:-1280x720x24}
VNC_PORT=${VNC_PORT:-5900}
NOVNC_PORT=${NOVNC_PORT:-6080}

mkdir -p /tmp/runtime-root
chmod 700 /tmp/runtime-root
export XDG_RUNTIME_DIR=/tmp/runtime-root

if pgrep -a Xvfb >/dev/null 2>&1; then
  echo "[VNC] Xvfb already running"
else
  echo "[VNC] Starting Xvfb on ${DISPLAY} (${RESOLUTION})"
  Xvfb "${DISPLAY}" -screen 0 "${RESOLUTION}" -ac +extension GLX +render -noreset &
fi

# Wait for X server socket.
for _ in $(seq 1 50); do
  if [ -S "/tmp/.X11-unix/X${DISPLAY_NUM}" ]; then
    break
  fi
  sleep 0.1
done

export DISPLAY

if pgrep -a fluxbox >/dev/null 2>&1; then
  echo "[VNC] fluxbox already running"
else
  echo "[VNC] Starting fluxbox"
  fluxbox -display "${DISPLAY}" >/tmp/fluxbox.log 2>&1 &
fi

if pgrep -a x11vnc >/dev/null 2>&1; then
  echo "[VNC] x11vnc already running"
else
  echo "[VNC] Starting x11vnc on port ${VNC_PORT}"
  x11vnc -display "${DISPLAY}" -nopw -forever -shared -rfbport "${VNC_PORT}" >/tmp/x11vnc.log 2>&1 &
fi

# Debian novnc package ships web UI under /usr/share/novnc
NOVNC_WEB_DIR=/usr/share/novnc
if [ ! -d "${NOVNC_WEB_DIR}" ]; then
  echo "[VNC] WARNING: ${NOVNC_WEB_DIR} not found; noVNC web may be missing"
fi

if pgrep -a websockify >/dev/null 2>&1; then
  echo "[VNC] websockify already running"
else
  echo "[VNC] Starting noVNC/websockify on port ${NOVNC_PORT}"
  websockify --web="${NOVNC_WEB_DIR}" "${NOVNC_PORT}" "localhost:${VNC_PORT}" >/tmp/websockify.log 2>&1 &
fi

echo "[VNC] Ready. DISPLAY=${DISPLAY}"
echo "[VNC] Open in browser: http://localhost:${NOVNC_PORT}/vnc.html"
echo "[VNC] To run Gazebo on this display: export DISPLAY=${DISPLAY}"

exec bash
