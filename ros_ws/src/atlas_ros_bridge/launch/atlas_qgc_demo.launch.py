from __future__ import annotations

"""QGroundControl / MAVLink demo launch for ATLAS.

Starts a minimal, real MAVLink telemetry bridge so QGroundControl can act as the
operator-side Command Center (LLD alignment).

Components:
- Gazebo headless server using atlas_demo_world.sdf
- ros_gz_bridge camera bridge -> /camera/image_raw
- atlas_ros_bridge nodes:
  - commandcenter_bridge_node
  - simulation_bridge_node
  - vision_node (optional)
  - qgc_mavlink_bridge_node

Networking assumptions:
- Container uses host networking (network_mode: host) so QGroundControl running
  on the host can receive UDP 14550.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.actions import ExecuteProcess
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    qgc_host = LaunchConfiguration("qgc_host")
    qgc_port = LaunchConfiguration("qgc_port")
    auto_rtl_on_threat = LaunchConfiguration("auto_rtl_on_threat")
    start_vision_node = LaunchConfiguration("start_vision_node")

    camera_topic = LaunchConfiguration("camera_topic")
    detections_topic = LaunchConfiguration("detections_topic")
    alerts_topic = LaunchConfiguration("alerts_topic")
    restricted_zone_polygon = LaunchConfiguration("restricted_zone_polygon")

    world_path = PathJoinSubstitution(
        [FindPackageShare("atlas_ros_bridge"), "worlds", "atlas_demo_world.sdf"]
    )

    gazebo_headless = ExecuteProcess(
        cmd=["gz", "sim", "-r", "-v", "3", "-s", world_path],
        output="screen",
    )

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
                "commands_topic": "/atlas/operator_commands",
                "status_topic": "/atlas/commandcenter/status",
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
                "simulation_status_topic": "/atlas/simulation/status",
            }
        ],
    )

    vision_node = Node(
        package="atlas_ros_bridge",
        executable="vision_node",
        name="vision_node",
        output="screen",
        condition=IfCondition(start_vision_node),
        parameters=[
            {
                "camera_topic": camera_topic,
                "detections_topic": detections_topic,
                "alerts_topic": alerts_topic,
                "restricted_zone_polygon": ParameterValue(restricted_zone_polygon, value_type=str),
            }
        ],
    )

    qgc_bridge = Node(
        package="atlas_ros_bridge",
        executable="qgc_mavlink_bridge_node",
        name="qgc_mavlink_bridge_node",
        output="screen",
        parameters=[
            {
                "qgc_host": qgc_host,
                "qgc_port": qgc_port,
                "auto_rtl_on_threat": auto_rtl_on_threat,
                "alerts_topic": alerts_topic,
                "operator_commands_topic": "/atlas/operator_commands",
            }
        ],
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "qgc_host",
                default_value="127.0.0.1",
                description="QGroundControl host to send MAVLink UDP packets to.",
            ),
            DeclareLaunchArgument(
                "qgc_port",
                default_value="14550",
                description="QGroundControl UDP port to send MAVLink packets to.",
            ),
            DeclareLaunchArgument(
                "auto_rtl_on_threat",
                default_value="true",
                description="Auto-switch simulated vehicle state to RTL on threat alerts.",
            ),
            DeclareLaunchArgument(
                "start_vision_node",
                default_value="true",
                description="Start vision_node (camera->detections->threat alerts).",
            ),
            DeclareLaunchArgument(
                "camera_topic",
                default_value="/camera/image_raw",
                description="ROS camera topic bridged from Gazebo.",
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
            gazebo_headless,
            camera_bridge,
            commandcenter_bridge,
            simulation_bridge,
            vision_node,
            qgc_bridge,
        ]
    )
