from __future__ import annotations

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    alerts_topic = LaunchConfiguration("alerts_topic")
    commands_topic = LaunchConfiguration("commands_topic")
    status_topic = LaunchConfiguration("status_topic")
    simulation_status_topic = LaunchConfiguration("simulation_status_topic")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "alerts_topic",
                default_value="/atlas/threat_alerts",
                description="Threat alerts topic (String JSON).",
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
            Node(
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
            ),
            Node(
                package="atlas_ros_bridge",
                executable="simulation_bridge_node",
                name="simulation_bridge_node",
                output="screen",
                parameters=[
                    {
                        "simulation_status_topic": simulation_status_topic,
                    }
                ],
            ),
        ]
    )
