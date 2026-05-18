"""ROS 2 / Gazebo integration bridge for ATLAS.

`atlas_ros_bridge` is intended to be the general adapter layer between a ROS 2 / Gazebo
simulation environment and the core ATLAS backend packages.

Design intent:
- Keep ROS/Gazebo-specific code out of core ATLAS modules (simulation, UAV, threat, command center).
- Host bridge nodes/adapters here (camera/vision, world-state/telemetry, command/control, etc.).
- Allow incremental integration: start with simple String(JSON) topics, evolve to typed ROS messages later.

Current included bridge use-cases:
- Command-center adapter for threat alerts + operator commands.
- Simulation status surface topic.
- Camera-to-vision pipeline feeding threat assessments.
"""

__all__ = []
