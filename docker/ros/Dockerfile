FROM osrf/ros:jazzy-desktop

SHELL ["/bin/bash", "-c"]

ENV DEBIAN_FRONTEND=noninteractive
ENV ROS_DISTRO=jazzy

RUN apt-get update && apt-get install -y \
    python3-colcon-common-extensions \
    python3-rosdep \
    python3-vcstool \
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
    && rm -rf /var/lib/apt/lists/*

RUN rosdep init || true
RUN rosdep update || true

WORKDIR /ros_ws

COPY docker/ros/entrypoint.sh /entrypoint.sh
COPY docker/ros/start_sim.sh /start_sim.sh

RUN chmod +x /entrypoint.sh /start_sim.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["bash"]
