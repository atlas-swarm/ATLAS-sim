import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist

class DroneController(Node):

    def __init__(self):
        super().__init__('drone_controller')

        self.publisher_ = self.create_publisher(Twist, '/cmd_vel', 10)

        self.timer = self.create_timer(1.0, self.move_drone)  # 👈 1 saniye yap

        self.get_logger().info("NODE STARTED")  # 🔥 ROS log

    def move_drone(self):
        msg = Twist()
        msg.linear.x = 2.0

        self.publisher_.publish(msg)

        self.get_logger().info("COMMAND SENT")  # 🔥 ROS log


def main(args=None):
    rclpy.init(args=args)

    node = DroneController()

    rclpy.spin(node)

    node.destroy_node()
    rclpy.shutdown()