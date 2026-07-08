#!/usr/bin/env python3
"""修正 scan 点数波动 + QoS 匹配 slam_toolbox (BEST_EFFORT)"""
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from sensor_msgs.msg import LaserScan

# ★ slam_toolbox 用 BEST_EFFORT 订阅，发布端必须匹配，否则消息积压后被 DDS 丢弃
SENSOR_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)


class ScanFixer(Node):
    def __init__(self):
        super().__init__('scan_fixer')
        self.sub = self.create_subscription(LaserScan, '/scan_raw', self.cb, 10)
        self.pub = self.create_publisher(LaserScan, '/scan', SENSOR_QOS)
        self.fixed_n = None
        self.warn_count = 0

    def cb(self, msg):
        n = len(msg.ranges)
        if n < 2:
            return

        # 首次锁定点数
        if self.fixed_n is None:
            self.fixed_n = n
            self.get_logger().info(
                f'Locking scan points to {self.fixed_n} '
                f'(angle_inc={msg.angle_increment:.6f} → '
                f'{(msg.angle_max - msg.angle_min)/(self.fixed_n - 1):.6f})'
            )

        # 截断或填充到固定点数
        if n > self.fixed_n:
            msg.ranges = msg.ranges[:self.fixed_n]
            msg.intensities = msg.intensities[:self.fixed_n] if msg.intensities else []
        elif n < self.fixed_n:
            pad_val = msg.ranges[-1] if msg.ranges else msg.range_max
            msg.ranges = list(msg.ranges) + [pad_val] * (self.fixed_n - n)
            if msg.intensities:
                msg.intensities = list(msg.intensities) + [0.0] * (self.fixed_n - n)

        # 修正元数据匹配固定点数
        msg.angle_increment = (msg.angle_max - msg.angle_min) / (self.fixed_n - 1)
        msg.time_increment = msg.scan_time / self.fixed_n if msg.scan_time > 0 else 0.0

        self.pub.publish(msg)

        # 偶发的点数变化打印警告
        if n != self.fixed_n and self.warn_count < 5:
            self.get_logger().warn(f'Scan points {n} ≠ {self.fixed_n} (adjusted)')
            self.warn_count += 1


def main():
    rclpy.init()
    rclpy.spin(ScanFixer())
    rclpy.shutdown()
