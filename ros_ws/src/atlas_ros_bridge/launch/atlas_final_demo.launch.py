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
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution, PythonExpression
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    start_gazebo = LaunchConfiguration("start_gazebo")
    gazebo_render_mode = LaunchConfiguration("gazebo_render_mode")

    start_rqt_image_view = LaunchConfiguration("start_rqt_image_view")
    start_data_logger = LaunchConfiguration("start_data_logger")

    auto_demo_threat = LaunchConfiguration("auto_demo_threat")
    threat_delay_s = LaunchConfiguration("threat_delay_s")
    auto_rtl_on_threat = LaunchConfiguration("auto_rtl_on_threat")

    start_vision_node = LaunchConfiguration("start_vision_node")
    start_gazebo_swarm_visualizer = LaunchConfiguration("start_gazebo_swarm_visualizer")

    start_web_dashboard = LaunchConfiguration("start_web_dashboard")
    web_dashboard_port = LaunchConfiguration("web_dashboard_port")

    log_dir = LaunchConfiguration("log_dir")

    qgc_host = LaunchConfiguration("qgc_host")
    qgc_port = LaunchConfiguration("qgc_port")

    camera_topic = LaunchConfiguration("camera_topic")
    detections_topic = LaunchConfiguration("detections_topic")
    alerts_topic = LaunchConfiguration("alerts_topic")
    restricted_zone_polygon = LaunchConfiguration("restricted_zone_polygon")

    world_path_xvfb = PathJoinSubstitution(
        [FindPackageShare("atlas_ros_bridge"), "worlds", "atlas_demo_world.sdf"]
    )
    world_path_headless = PathJoinSubstitution(
        [FindPackageShare("atlas_ros_bridge"), "worlds", "atlas_demo_world_ogre2.sdf"]
    )

    use_xvfb = PythonExpression(["'", gazebo_render_mode, "' == 'xvfb'"])
    use_headless = PythonExpression(["'", gazebo_render_mode, "' != 'xvfb'"])

    xvfb = ExecuteProcess(
        cmd=[
            "Xvfb",
            ":1",
            "-screen",
            "0",
            "1280x720x24",
            "-ac",
            "+extension",
            "GLX",
            "+render",
            "-noreset",
        ],
        output="screen",
        condition=IfCondition(
            PythonExpression(["'", start_gazebo, "' == 'true' and '", gazebo_render_mode, "' == 'xvfb'"])
        ),
    )

    gazebo_headless = ExecuteProcess(
        cmd=["gz", "sim", "-r", "-v", "3", "-s", "--headless-rendering", world_path_headless],
        output="screen",
        condition=IfCondition(
            PythonExpression(
                ["'", start_gazebo, "' == 'true' and '", gazebo_render_mode, "' != 'xvfb'"]
            )
        ),
    )

    gazebo_xvfb = ExecuteProcess(
        cmd=["gz", "sim", "-r", "-v", "3", world_path_xvfb],
        output="screen",
        condition=IfCondition(
            PythonExpression(["'", start_gazebo, "' == 'true' and '", gazebo_render_mode, "' == 'xvfb'"])
        ),
        additional_env={"DISPLAY": ":1"},
    )

    # Bridge camera image transport topic to ROS camera_topic.
    gz_camera_topic = "/world/atlas_demo_world/model/fixed_camera/link/link/sensor/demo_camera/image"
    camera_bridge = Node(
        package="ros_gz_bridge",
        executable="parameter_bridge",
        name="camera_parameter_bridge",
        output="screen",
        condition=IfCondition(start_gazebo),
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

    gazebo_swarm_visualizer = Node(
        package="atlas_ros_bridge",
        executable="gazebo_swarm_visualizer_node",
        name="gazebo_swarm_visualizer_node",
        output="screen",
        condition=IfCondition(
            PythonExpression(["'", start_gazebo, "' == 'true' and '", start_gazebo_swarm_visualizer, "' == 'true'"])
        ),
        parameters=[
            {
                "telemetry_topic": "/atlas/demo/telemetry",
                "world_name": "atlas_demo_world",
                "update_rate_hz": 2.0,
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

    demo_mission_state = Node(
        package="atlas_ros_bridge",
        executable="demo_mission_state_node",
        name="demo_mission_state_node",
        output="screen",
        parameters=[
            {
                "auto_rtl_on_threat": auto_rtl_on_threat,
                "auto_demo_threat": auto_demo_threat,
                "threat_delay_s": threat_delay_s,
            }
        ],
    )

    demo_dashboard = Node(
        package="atlas_ros_bridge",
        executable="demo_dashboard_node",
        name="demo_dashboard_node",
        output="screen",
        parameters=[
            {
                "detections_topic": detections_topic,
                "runtime_commands_topic": "/atlas/demo/runtime_commands",
                "log_dir": log_dir,
            }
        ],
    )

    data_logger = Node(
        package="atlas_ros_bridge",
        executable="demo_data_logger_node",
        name="demo_data_logger_node",
        output="screen",
        condition=IfCondition(start_data_logger),
        parameters=[
            {
                "log_dir": log_dir,
                "telemetry_topic": "/atlas/demo/telemetry",
                "alerts_topic": alerts_topic,
                "operator_commands_topic": "/atlas/operator_commands",
                "runtime_commands_topic": "/atlas/demo/runtime_commands",
                "vision_detections_topic": detections_topic,
                "camera_topic": camera_topic,
            }
        ],
    )

    web_dashboard = Node(
        package="atlas_ros_bridge",
        executable="demo_web_dashboard_node",
        name="demo_web_dashboard_node",
        output="screen",
        condition=IfCondition(start_web_dashboard),
        parameters=[
            {
                "port": web_dashboard_port,
                "log_dir": log_dir,
                "telemetry_topic": "/atlas/demo/telemetry",
                "alerts_topic": alerts_topic,
                "operator_commands_topic": "/atlas/operator_commands",
                "runtime_commands_topic": "/atlas/demo/runtime_commands",
                "commandcenter_status_topic": "/atlas/commandcenter/status",
                "simulation_status_topic": "/atlas/simulation/status",
                "vision_detections_topic": detections_topic,
                "camera_topic": camera_topic,
                "gz_camera_topic": gz_camera_topic,
                "gazebo_enabled": ParameterValue(start_gazebo, value_type=bool),
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
                "start_gazebo",
                default_value="false",
                description="Start Gazebo world (experimental; stable demo works without it).",
            ),
             DeclareLaunchArgument(
                 "gazebo_render_mode",
                 default_value="headless",
                 description="Gazebo render mode: headless|xvfb (xvfb is more reliable for camera sensors).",
             ),
            DeclareLaunchArgument(
                "start_rqt_image_view",
                default_value="false",
                description="Start rqt_image_view for /camera/image_raw.",
            ),
            DeclareLaunchArgument(
                "start_data_logger",
                default_value="true",
                description="Start demo_data_logger_node to write JSONL logs.",
            ),
            DeclareLaunchArgument(
                "log_dir",
                default_value="/ros_ws/log/atlas_demo",
                description="Directory for demo JSONL/CSV logs.",
            ),
            DeclareLaunchArgument(
                "auto_demo_threat",
                default_value="false",
                description="Publish one demo threat after threat_delay_s.",
            ),
            DeclareLaunchArgument(
                "threat_delay_s",
                default_value="120.0",
                description="Auto demo threat delay in seconds.",
            ),
            DeclareLaunchArgument(
                "auto_rtl_on_threat",
                default_value="true",
                description="Auto RTL when threat detected.",
            ),
            DeclareLaunchArgument(
                "start_vision_node",
                default_value="true",
                description="Start vision pipeline node (if deps missing, logs warning and idles).",
            ),
            DeclareLaunchArgument(
                "start_gazebo_swarm_visualizer",
                default_value="true",
                description="Start telemetry-driven Gazebo swarm visualizer.",
            ),
            DeclareLaunchArgument(
                "start_web_dashboard",
                default_value="true",
                description="Start unified web dashboard server.",
            ),
            DeclareLaunchArgument(
                "web_dashboard_port",
                default_value="8088",
                description="Web dashboard port (http://localhost:PORT).",
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
            xvfb,
            gazebo_headless,
            gazebo_xvfb,
            camera_bridge,
            commandcenter_bridge,
            simulation_bridge,
            gazebo_swarm_visualizer,
            demo_mission_state,
            demo_dashboard,
            data_logger,
            web_dashboard,
            qgc_bridge,
            vision_node,
            rqt,
        ]
    )
