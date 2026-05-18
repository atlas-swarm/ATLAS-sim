from setuptools import find_packages, setup

package_name = "atlas_ros_bridge"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        (
            "share/ament_index/resource_index/packages",
            [f"resource/{package_name}"],
        ),
        (f"share/{package_name}", ["package.xml"]),
        (
            f"share/{package_name}/launch",
            [
                "launch/atlas_sim_bridge.launch.py",
                "launch/atlas_vision_bridge.launch.py",
                "launch/atlas_gazebo_demo.launch.py",
                "launch/atlas_qgc_demo.launch.py",
                "launch/atlas_final_demo.launch.py",
            ],
        ),
        (
            f"share/{package_name}/worlds",
            [
                "worlds/atlas_demo_world.sdf",
            ],
        ),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="ATLAS Team",
    maintainer_email="atlas@example.com",
    description=(
        "ROS 2 bridge package for ATLAS simulation, telemetry, command-center, and vision integration."
    ),
    license="MIT",
    extras_require={"test": ["pytest"]},
    entry_points={
        "console_scripts": [
            "commandcenter_bridge_node = atlas_ros_bridge.commandcenter_bridge_node:main",
            "simulation_bridge_node = atlas_ros_bridge.simulation_bridge_node:main",
            "vision_node = atlas_ros_bridge.vision_node:main",
            "qgc_mavlink_bridge_node = atlas_ros_bridge.qgc_mavlink_bridge_node:main",
            "demo_mission_state_node = atlas_ros_bridge.demo_mission_state_node:main",
            "demo_threat_event_node = atlas_ros_bridge.demo_threat_event_node:main",
            "demo_dashboard_node = atlas_ros_bridge.demo_dashboard_node:main",
        ]
    },
)
