FROM --platform=linux/amd64 osrf/ros:jazzy-desktop

SHELL ["/bin/bash", "-c"]

ENV DEBIAN_FRONTEND=noninteractive
ENV ROS_DISTRO=jazzy

RUN apt-get update && apt-get install -y \
    python3-colcon-common-extensions \
    python3-rosdep \
    python3-vcstool \
    python3-pip \
    git \
    curl \
    nano \
    vim \
    iputils-ping \
    net-tools \
    ros-jazzy-ros-gz \
    ros-jazzy-ros-gz-bridge \
    ros-jazzy-ros-gz-image \
    ros-jazzy-ros-gz-interfaces \
    ros-jazzy-ros-gz-sim \
    \
    # GUI / OpenGL / X11 runtime libs for Gazebo (Qt) inside Docker \
    mesa-utils \
    libgl1-mesa-dri \
    libglx-mesa0 \
    libegl1 \
    libegl-mesa0 \
    libglu1-mesa \
    libx11-xcb1 \
    libxcb-glx0 \
    libxcb-xinerama0 \
    libxcb-cursor0 \
    libxcb-xinput0 \
    libxkbcommon-x11-0 \
    libqt5opengl5 \
    \
    # Virtual desktop / VNC for GUI access without host X11 \
    xvfb \
    x11vnc \
    fluxbox \
    novnc \
    websockify \
    && rm -rf /var/lib/apt/lists/*

# pymavlink is a runtime dependency for QGroundControl/MAVLink bridge demos.
RUN python3 -m pip install --break-system-packages --no-cache-dir pymavlink

RUN rosdep init || true
RUN rosdep update || true

WORKDIR /ros_ws

COPY docker/ros/entrypoint.sh /entrypoint.sh
COPY docker/ros/start_sim.sh /start_sim.sh
COPY docker/ros/start_vnc_gazebo.sh /start_vnc_gazebo.sh

RUN chmod +x /entrypoint.sh /start_sim.sh /start_vnc_gazebo.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["bash"]
