from __future__ import annotations

"""CommandCenter bridge node for ATLAS.

This node adapts ROS topics to the ATLAS CommandCenter APIs without adding ROS
logic into core ATLAS packages.

Responsibilities (minimal, extensible):
- Subscribe to threat alerts (String JSON) and forward to CommandCenterInterface.
- Subscribe to operator commands (String JSON) and route a safe subset.
- Publish a periodic status/heartbeat topic for integration visibility.

Future extensions (not implemented here):
- QGroundControl / MAVLink command mapping.
- Typed ROS messages for alerts and commands.
- Telemetry visualization adapters.
"""

from typing import Any

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .bridge_utils import make_status_payload, safe_json_dumps, safe_json_loads


class CommandCenterBridgeNode(Node):
    def __init__(self) -> None:
        super().__init__("commandcenter_bridge_node")

        self.declare_parameter("alerts_topic", "/atlas/threat_alerts")
        self.declare_parameter("commands_topic", "/atlas/operator_commands")
        self.declare_parameter("status_topic", "/atlas/commandcenter/status")

        alerts_topic = self.get_parameter("alerts_topic").get_parameter_value().string_value
        commands_topic = self.get_parameter("commands_topic").get_parameter_value().string_value
        status_topic = self.get_parameter("status_topic").get_parameter_value().string_value

        self._status_pub = self.create_publisher(String, status_topic, 10)
        self._alerts_sub = self.create_subscription(String, alerts_topic, self._on_alert_msg, 10)
        self._commands_sub = self.create_subscription(
            String, commands_topic, self._on_operator_command_msg, 10
        )

        self.alerts_received_count = 0
        self.alerts_forwarded_count = 0
        self.commands_received_count = 0
        self.commands_handled_count = 0
        self.last_error: str | None = None

        self._status_timer = self.create_timer(1.0, self._publish_status)

        self.get_logger().info(
            f"CommandCenter bridge ready. alerts={alerts_topic} commands={commands_topic} status={status_topic}"
        )

    def _publish_status(self) -> None:
        payload = make_status_payload(
            node_name=self.get_name(),
            available_features=[
                "threat_alert_forwarding",
                "operator_command_routing(type-based)",
            ],
            ok=True,
            error=self.last_error,
            extra={
                "alerts_received_count": self.alerts_received_count,
                "alerts_forwarded_count": self.alerts_forwarded_count,
                "commands_received_count": self.commands_received_count,
                "commands_handled_count": self.commands_handled_count,
            },
        )
        self._status_pub.publish(String(data=safe_json_dumps(payload)))

    def _get_command_center(self):
        try:
            from atlas_commandcenter.command_center_interface import CommandCenterInterface

            return CommandCenterInterface.get_instance()
        except Exception as exc:
            self.last_error = f"commandcenter_import_failed: {exc}"
            self.get_logger().error(self.last_error)
            return None

    def _on_alert_msg(self, msg: String) -> None:
        self.alerts_received_count += 1

        alert_dict = safe_json_loads(msg.data, self.get_logger())
        if alert_dict is None:
            self.last_error = "alert_json_parse_failed"
            return

        interface = self._get_command_center()
        if interface is None:
            return

        try:
            interface.on_alert_received(alert_dict)
            self.alerts_forwarded_count += 1
        except Exception as exc:
            self.last_error = f"alert_forward_failed: {exc}"
            self.get_logger().error(f"Failed to forward alert to CommandCenter: {exc}; alert={alert_dict!r}")

    def _on_operator_command_msg(self, msg: String) -> None:
        self.commands_received_count += 1

        cmd = safe_json_loads(msg.data, self.get_logger())
        if cmd is None:
            self.last_error = "command_json_parse_failed"
            return

        interface = self._get_command_center()
        if interface is None:
            return

        try:
            handled = self._route_operator_command(interface, cmd)
            if handled:
                self.commands_handled_count += 1
        except Exception as exc:
            self.last_error = f"command_handle_failed: {exc}"
            self.get_logger().error(f"Failed to handle operator command: {exc}; cmd={cmd!r}")

    def _route_operator_command(self, interface: Any, cmd: dict[str, Any]) -> bool:
        cmd_type = str(cmd.get("type", "")).strip().upper()

        if cmd_type == "PAUSE_MISSION":
            interface.mission_controller.pause_mission()
            return True

        if cmd_type == "RESUME_MISSION":
            interface.mission_controller.resume_mission()
            return True

        if cmd_type == "ABORT_MISSION":
            interface.abort_mission()
            return True

        if cmd_type == "ISSUE_OVERRIDE":
            payload = cmd.get("payload", {})
            interface.issue_override(payload)
            return True

        if cmd_type == "LOAD_AND_START_MISSION":
            file_path = cmd.get("file_path")
            if not file_path:
                self.get_logger().warning(f"LOAD_AND_START_MISSION missing file_path; cmd={cmd!r}")
                return False

            plan = interface.load_mission_plan(str(file_path))
            if interface.upload_mission(plan):
                interface.mission_controller.start_mission(plan)
                return True

            self.get_logger().warning(f"Mission upload failed; file_path={file_path!r}")
            return False

        self.get_logger().warning(f"Unknown operator command type; cmd={cmd!r}")
        self._todo_route_operator_command(cmd)
        return False

    def _todo_route_operator_command(self, cmd: dict[str, Any]) -> None:
        """TODO adapter for future MAVLink/QGroundControl command mapping.

        This placeholder exists to keep the bridge extensible without modifying core ATLAS classes.
        """
        _ = cmd


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = CommandCenterBridgeNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
