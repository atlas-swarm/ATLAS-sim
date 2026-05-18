from __future__ import annotations

"""Final integrated ATLAS demo launch.

One-command demo bringing together:
- Gazebo headless world + camera topic
- ros_gz_bridge camera bridge -> /camera/image_raw
- atlas_ros_bridge core integration nodes
- mission state simulation -> /atlas/demo/telemetry
- QGroundControl MAVLink bridge mirroring demo state
- deterministic threat event injection
- compact dashboard output

Run:
  ros2 launch atlas_ros_bridge atlas_final_demo.launch.py start_rqt_image_view:=true
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import ExecuteProcess
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    start_rqt_image_view = LaunchConfiguration("start_rqt_image_view")
    auto_rtl_on_threat = LaunchConfiguration("auto_rtl_on_threat")
    start_vision_node = LaunchConfiguration("start_vision_node")

    qgc_host = LaunchConfiguration("qgc_host")
    qgc_port = LaunchConfiguration("qgc_port")

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

    # Bridge camera image transport topic to ROS camera_topic.
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
    )

    simulation_bridge = Node(
        package="atlas_ros_bridge",
        executable="simulation_bridge_node",
        name="simulation_bridge_node",
        output="screen",
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

    demo_mission_state = Node(
        package="atlas_ros_bridge",
        executable="demo_mission_state_node",
        name="demo_mission_state_node",
        output="screen",
        parameters=[
            {
                "auto_rtl_on_threat": auto_rtl_on_threat,
            }
        ],
    )

    demo_threat_event = Node(
        package="atlas_ros_bridge",
        executable="demo_threat_event_node",
        name="demo_threat_event_node",
        output="screen",
        parameters=[
            {
                "alerts_topic": alerts_topic,
            }
        ],
    )

    demo_dashboard = Node(
        package="atlas_ros_bridge",
        executable="demo_dashboard_node",
        name="demo_dashboard_node",
        output="screen",
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
            }
        ],
    )

    rqt = ExecuteProcess(
        cmd=["rqt_image_view", camera_topic],
        output="screen",
        condition=IfCondition(start_rqt_image_view),
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "start_rqt_image_view",
                default_value="false",
                description="Start rqt_image_view for /camera/image_raw.",
            ),
            DeclareLaunchArgument(
                "auto_rtl_on_threat",
                default_value="true",
                description="Auto RTL when threat detected.",
            ),
            DeclareLaunchArgument(
                "start_vision_node",
                default_value="true",
                description="Start vision pipeline node (may require ultralytics/opencv).",
            ),
            DeclareLaunchArgument(
                "qgc_host",
                default_value="127.0.0.1",
                description="QGroundControl host for MAVLink UDP out.",
            ),
            DeclareLaunchArgument(
                "qgc_port",
                default_value="14550",
                description="QGroundControl UDP port for MAVLink.",
            ),
            DeclareLaunchArgument(
                "camera_topic",
                default_value="/camera/image_raw",
                description="ROS camera topic.",
            ),
            DeclareLaunchArgument(
                "detections_topic",
                default_value="/atlas/vision_detections",
                description="Vision detections topic.",
            ),
            DeclareLaunchArgument(
                "alerts_topic",
                default_value="/atlas/threat_alerts",
                description="Threat alerts topic.",
            ),
            DeclareLaunchArgument(
                "restricted_zone_polygon",
                default_value="[[220,140],[420,140],[420,340],[220,340]]",
                description="Restricted zone polygon (JSON string).",
            ),
            gazebo_headless,
            camera_bridge,
            commandcenter_bridge,
            simulation_bridge,
            demo_mission_state,
            demo_threat_event,
            demo_dashboard,
            qgc_bridge,
            vision_node,
            rqt,
        ]
    )
