#!/usr/bin/env python3
"""SLAM 建图启动：电机 + 雷达 + TF + slam_toolbox"""

import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.conditions import IfCondition
from launch_ros.substitutions import FindPackageShare
from launch_ros.actions import Node


def generate_launch_description():
    # SLAM 参数文件路径
    slam_config_path = PathJoinSubstitution(
        [FindPackageShare('jgb520_driver'), 'config', 'slam.yaml']
    )

    # slam_toolbox launch 路径
    slam_toolbox_launch = PathJoinSubstitution(
        [FindPackageShare('slam_toolbox'), 'launch', 'online_async_launch.py']
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            name='rviz',
            default_value='false',
            description='启动 RViz2 可视化'
        ),

        # JGB520 电机驱动
        Node(
            package='jgb520_driver',
            executable='motor_driver',
            name='jgb520_driver',
            parameters=[{
                'serial_port': '/dev/ttyS1',
                'baudrate': 115200,
                'motor_type': 1,
                'wheel_diameter': 0.067,
                'wheel_base': 0.25,
                'encoder_resolution': 330,
            }],
            output='screen',
        ),

        # RPLidar A2M6 (发布到 /scan_raw)
        Node(
            package='rplidar_ros',
            executable='rplidar_node',
            name='rplidar_node',
            parameters=[{
                'serial_port': '/dev/rplidar',
                'serial_baudrate': 115200,
                'frame_id': 'laser',
                'scan_mode': 'Express',
                'min_range': 0.2,
                'max_range': 16.0,
            }],
            remappings=[('scan', 'scan_raw')],
            output='screen',
        ),

        # 扫描修正：修正 Express 模式 angle_increment 与实际点数不匹配
        Node(
            package='jgb520_driver',
            executable='scan_fixer',
            name='scan_fixer',
            output='screen',
        ),

        # TF: base_link -> laser (雷达在车体前方 0.15m，上方 0.1m)
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            arguments=['0.15', '0.0', '0.1', '0', '0', '0', 'base_link', 'laser'],
        ),

        # SLAM Toolbox (online async) — 订阅修正后的 /scan
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(slam_toolbox_launch),
            launch_arguments={
                'use_sim_time': 'False',
                'slam_params_file': slam_config_path,
            }.items()
        ),

        # RViz2 (可选)
        Node(
            package='rviz2',
            executable='rviz2',
            name='rviz2',
            output='screen',
            arguments=['-d', PathJoinSubstitution(
                [FindPackageShare('rplidar_ros'), 'rviz', 'rplidar_ros.rviz']
            )],
            condition=IfCondition(LaunchConfiguration('rviz')),
        ),
    ])
