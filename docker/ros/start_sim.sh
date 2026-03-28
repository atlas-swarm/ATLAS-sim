#!/bin/bash
set -e

source /opt/ros/jazzy/setup.bash

cd /ros_ws

rosdep update || true
rosdep install --from-paths src --ignore-src -r -y

colcon build --symlink-install

source /ros_ws/install/setup.bash

# Burayı kendi launch dosyana göre değiştir
ros2 launch atlas_simulation main_sim.launch.py
