from __future__ import annotations

"""Launch a minimal visible Gazebo demo for ATLAS bridge validation.

Starts:
- Gazebo (ros_gz_sim) with a lightweight demo world
- ros_gz_bridge parameter_bridge for /camera/image_raw
- atlas_ros_bridge nodes:
  - commandcenter_bridge_node
  - simulation_bridge_node
  - vision_node

GUI note:
- If running inside Docker, Gazebo GUI may require host X11/Wayland forwarding.
- If GUI does not open, launch with `gui:=false` for headless mode.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition, UnlessCondition
from launch.actions import ExecuteProcess
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    gui = LaunchConfiguration("gui")

    camera_topic = LaunchConfiguration("camera_topic")
    detections_topic = LaunchConfiguration("detections_topic")
    alerts_topic = LaunchConfiguration("alerts_topic")
    restricted_zone_polygon = LaunchConfiguration("restricted_zone_polygon")

    simulation_status_topic = LaunchConfiguration("simulation_status_topic")
    commands_topic = LaunchConfiguration("commands_topic")
    status_topic = LaunchConfiguration("status_topic")

    world_path = PathJoinSubstitution(
        [FindPackageShare("atlas_ros_bridge"), "worlds", "atlas_demo_world.sdf"]
    )

    # Gazebo Sim launcher.
    # Uses the `gz sim` CLI directly so the world file is loaded reliably.
    # GUI note: inside Docker, consider running via VNC/noVNC.
    gazebo_gui = ExecuteProcess(
        cmd=["gz", "sim", "-r", "-v", "3", world_path],
        output="screen",
        condition=IfCondition(gui),
    )

    gazebo_headless = ExecuteProcess(
        cmd=["gz", "sim", "-r", "-v", "3", "-s", world_path],
        output="screen",
        condition=UnlessCondition(gui),
    )

    # Bridge Gazebo Transport camera topic -> ROS2 sensor_msgs/Image.
    # Gazebo Sim namespaces sensors under /world/.../sensor/... by default.
    # We bridge the *Gazebo* topic and remap the *ROS* side to /camera/image_raw.
    gz_camera_topic = "/world/atlas_demo_world/model/fixed_camera/link/link/sensor/demo_camera/image"

    camera_bridge = Node(
        package="ros_gz_bridge",
        executable="parameter_bridge",
        name="camera_parameter_bridge",
        output="screen",
        arguments=[
            gz_camera_topic + "@sensor_msgs/msg/Image@gz.msgs.Image",
        ],
        remappings=[
            (gz_camera_topic, camera_topic),
        ],
    )

    commandcenter_bridge = Node(
        package="atlas_ros_bridge",
        executable="commandcenter_bridge_node",
        name="commandcenter_bridge_node",
        output="screen",
        parameters=[
            {
                "alerts_topic": alerts_topic,
                "commands_topic": commands_topic,
                "status_topic": status_topic,
            }
        ],
    )

    simulation_bridge = Node(
        package="atlas_ros_bridge",
        executable="simulation_bridge_node",
        name="simulation_bridge_node",
        output="screen",
        parameters=[
            {
                "simulation_status_topic": simulation_status_topic,
            }
        ],
    )

    vision_node = Node(
        package="atlas_ros_bridge",
        executable="vision_node",
        name="vision_node",
        output="screen",
        parameters=[
            {
                "camera_topic": camera_topic,
                "detections_topic": detections_topic,
                "alerts_topic": alerts_topic,
                "restricted_zone_polygon": ParameterValue(restricted_zone_polygon, value_type=str),
            }
        ],
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "gui",
                default_value="true",
                description="Start Gazebo GUI (may require X11 forwarding in Docker).",
            ),
            DeclareLaunchArgument(
                "camera_topic",
                default_value="/camera/image_raw",
                description="Camera topic to bridge/subscribe to.",
            ),
            DeclareLaunchArgument(
                "detections_topic",
                default_value="/atlas/vision_detections",
                description="Vision detections topic (String JSON).",
            ),
            DeclareLaunchArgument(
                "alerts_topic",
                default_value="/atlas/threat_alerts",
                description="Threat alerts topic (String JSON).",
            ),
            DeclareLaunchArgument(
                "restricted_zone_polygon",
                default_value="[[220,140],[420,140],[420,340],[220,340]]",
                description="Restricted zone polygon in image pixel coordinates (JSON string).",
            ),
            DeclareLaunchArgument(
                "commands_topic",
                default_value="/atlas/operator_commands",
                description="Operator commands topic (String JSON).",
            ),
            DeclareLaunchArgument(
                "status_topic",
                default_value="/atlas/commandcenter/status",
                description="CommandCenter bridge status topic (String JSON).",
            ),
            DeclareLaunchArgument(
                "simulation_status_topic",
                default_value="/atlas/simulation/status",
                description="Simulation bridge status topic (String JSON).",
            ),
            gazebo_gui,
            gazebo_headless,
            camera_bridge,
            commandcenter_bridge,
            simulation_bridge,
            vision_node,
        ]
    )
