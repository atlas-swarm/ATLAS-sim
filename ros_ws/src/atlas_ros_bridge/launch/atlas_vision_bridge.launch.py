"""Launch ATLAS ROS bridge nodes for vision-assisted simulation integration."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    camera_topic = LaunchConfiguration("camera_topic")
    detections_topic = LaunchConfiguration("detections_topic")
    alerts_topic = LaunchConfiguration("alerts_topic")
    commands_topic = LaunchConfiguration("commands_topic")
    status_topic = LaunchConfiguration("status_topic")
    simulation_status_topic = LaunchConfiguration("simulation_status_topic")
    restricted_zone_polygon = LaunchConfiguration("restricted_zone_polygon")
    start_simulation_bridge = LaunchConfiguration("start_simulation_bridge")

    return LaunchDescription([
        DeclareLaunchArgument(
            "camera_topic",
            default_value="/camera/image_raw",
            description="ROS image topic used as the vision pipeline input.",
        ),
        DeclareLaunchArgument(
            "detections_topic",
            default_value="/atlas/vision_detections",
            description="Topic for low-level vision detection JSON messages.",
        ),
        DeclareLaunchArgument(
            "alerts_topic",
            default_value="/atlas/threat_alerts",
            description="Topic for final threat alert JSON messages.",
        ),
        DeclareLaunchArgument(
            "commands_topic",
            default_value="/atlas/operator_commands",
            description="Topic for operator command JSON messages.",
        ),
        DeclareLaunchArgument(
            "status_topic",
            default_value="/atlas/commandcenter/status",
            description="Topic for CommandCenter bridge status JSON messages.",
        ),
        DeclareLaunchArgument(
            "simulation_status_topic",
            default_value="/atlas/simulation/status",
            description="Topic for simulation bridge status JSON messages.",
        ),
        DeclareLaunchArgument(
            "restricted_zone_polygon",
            default_value="[[220,140],[420,140],[420,340],[220,340]]",
            description="Restricted zone polygon as a JSON string in image pixel coordinates.",
        ),
        DeclareLaunchArgument(
            "start_simulation_bridge",
            default_value="true",
            description="Whether to also start the general simulation status bridge node.",
        ),

        Node(
            package="atlas_ros_bridge",
            executable="commandcenter_bridge_node",
            name="commandcenter_bridge_node",
            output="screen",
            parameters=[{
                "alerts_topic": alerts_topic,
                "commands_topic": commands_topic,
                "status_topic": status_topic,
            }],
        ),

        Node(
            package="atlas_ros_bridge",
            executable="vision_node",
            name="vision_node",
            output="screen",
            parameters=[{
                "camera_topic": camera_topic,
                "detections_topic": detections_topic,
                "alerts_topic": alerts_topic,
                "restricted_zone_polygon": ParameterValue(restricted_zone_polygon, value_type=str),
            }],
        ),

        Node(
            package="atlas_ros_bridge",
            executable="simulation_bridge_node",
            name="simulation_bridge_node",
            output="screen",
            condition=IfCondition(start_simulation_bridge),
            parameters=[{
                "simulation_status_topic": simulation_status_topic,
            }],
        ),
    ])
