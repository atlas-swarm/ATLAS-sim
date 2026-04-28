# ATLAS-sim

Dockerized simulation environment for the ATLAS project.

## Scope
- ROS 2 Jazzy
- Gazebo / ros_gz integration
- ATLAS simulation packages
- Containerized development environment

## Structure
- docker/ros: Docker environment files
- ros_ws: ROS 2 workspace
- docker-compose.yml: container orchestration

## Simulation Demo
- Default mission config: `ros_ws/src/atlas_simulation/missions/mission_demo.json`
- Run locally: `PYTHONPATH=ros_ws/src/atlas_simulation python3 -m atlas_simulation.demo_scenario`
- Simulation final report: `docs/final_report_simulation.md`
