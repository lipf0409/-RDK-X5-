#!/usr/bin/env python3
"""真实机器人启动：电机 + 雷达 + TF"""

from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    return LaunchDescription([
        # JGB520 电机驱动 → /dev/motor
        Node(
            package='jgb520_driver',
            executable='motor_driver',
            name='jgb520_driver',
            parameters=[{
                'serial_port': '/dev/motor',
                'baudrate': 115200,
                'motor_type': 1,
                'wheel_diameter': 0.067,
                'wheel_base': 0.25,
                'encoder_resolution': 11,
            }],
            output='screen',
        ),

        # RPLidar A2M6 → /dev/rplidar
        Node(
            package='rplidar_ros',
            executable='rplidar_node',
            name='rplidar_node',
            parameters=[{
                'serial_port': '/dev/rplidar',
                'serial_baudrate': 115200,
                'frame_id': 'laser',
                'scan_mode': 'Express',
            }],
            output='screen',
        ),

        # TF: base_link -> laser
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            arguments=['0.15', '0.0', '0.1', '0', '0', '0', 'base_link', 'laser'],
        ),
    ])
