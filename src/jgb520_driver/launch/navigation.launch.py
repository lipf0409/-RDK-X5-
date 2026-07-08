#!/usr/bin/env python3
"""Nav2 导航启动：电机 + 雷达 + TF + Nav2"""

import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.conditions import IfCondition
from launch_ros.substitutions import FindPackageShare
from launch_ros.actions import Node


def generate_launch_description():
    # Nav2 参数文件路径
    nav2_config_path = PathJoinSubstitution(
        [FindPackageShare('jgb520_driver'), 'config', 'navigation.yaml']
    )

    # Nav2 bringup launch 路径
    nav2_launch_path = PathJoinSubstitution(
        [FindPackageShare('nav2_bringup'), 'launch', 'bringup_launch.py']
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            name='map',
            default_value='/home/sunrise/maps/my_map.yaml',
            description='地图文件路径'
        ),

        DeclareLaunchArgument(
            name='rviz',
            default_value='false',
            description='启动 RViz2 可视化'
        ),

        # JGB520 电机驱动（★ 串口使用 /dev/motor）
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
                'encoder_resolution': 330,           # ★ 从 330 改为 11
            }],
            output='screen',
        ),

        # RPLidar A2M6
        Node(
            package='rplidar_ros',
            executable='rplidar_node',
            name='rplidar_node',
            parameters=[{
                'serial_port': '/dev/rplidar',
                'serial_baudrate': 115200,
                'frame_id': 'laser',
                'scan_mode': 'Standard',
                'min_range': 0.2,
                'max_range': 16.0,
            }],
            output='screen',
        ),

        # TF: base_link -> laser
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            arguments=['0.15', '0.0', '0.1', '0', '0', '0', 'base_link', 'laser'],
        ),

        # Nav2 Bringup (AMCL + Planner + Controller + Costmaps + BehaviorTree)
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(nav2_launch_path),
            launch_arguments={
                'map': LaunchConfiguration('map'),
                'use_sim_time': 'False',
                'params_file': nav2_config_path,
            }.items()
        ),

        # RViz2 (可选)
        Node(
            package='rviz2',
            executable='rviz2',
            name='rviz2',
            output='screen',
            arguments=['-d', PathJoinSubstitution(
                [FindPackageShare('nav2_bringup'), 'rviz', 'nav2_default_view.rviz']
            )],
            condition=IfCondition(LaunchConfiguration('rviz')),
        ),
    ])
