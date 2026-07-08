#!/usr/bin/env python3
"""
视觉+巡逻 联合启动 (一页终端搞定所有)
启动: 电机 + 雷达 + TF + 视觉监护
(摄像头驱动和BPU检测需单独启动)

使用方式:
  # 仅电机+雷达+视觉:
  ros2 launch ucar_vision vision_patrol.launch.py

  # 加 SLAM:
  ros2 launch ucar_vision vision_patrol.launch.py mode:=slam

  # 模拟模式 (无GPIO/LED时):
  ros2 launch ucar_vision vision_patrol.launch.py sim_mode:=true
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo, TimerAction
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    mode = LaunchConfiguration('mode', default='basic')
    sim_mode = LaunchConfiguration('sim_mode', default='false')

    vision_params = PathJoinSubstitution(
        [FindPackageShare('ucar_vision'), 'config', 'vision_params.yaml'])

    return LaunchDescription([
        DeclareLaunchArgument('mode', default_value='basic',
                              description='运行模式: basic | slam | nav'),
        DeclareLaunchArgument('sim_mode', default_value='false',
                              description='模拟模式: true=仅日志不操作硬件'),

        LogInfo(msg=f'启动模式: {mode}  |  声光报警: M260C USB + GPIO LED'),

        # ═══════════════════════════════════════
        # 1. JGB520 电机驱动
        # ═══════════════════════════════════════
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

        # ═══════════════════════════════════════
        # 2. 激光雷达 RPLidar A2M6
        # ═══════════════════════════════════════
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

        # ═══════════════════════════════════════
        # 3. 扫描修正
        # ═══════════════════════════════════════
        Node(
            package='jgb520_driver',
            executable='scan_fixer',
            name='scan_fixer',
            output='screen',
        ),

        # ═══════════════════════════════════════
        # 4. TF: base_link → laser
        # ═══════════════════════════════════════
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            arguments=['0.15', '0.0', '0.1', '0', '0', '0', 'base_link', 'laser'],
        ),

        # ═══════════════════════════════════════
        # 5. 视觉监护 (延迟等电机+雷达稳定)
        #    摄像头驱动 + BPU检测需单独终端启动!
        # ═══════════════════════════════════════
        TimerAction(
            period=3.0,
            actions=[
                Node(
                    package='ucar_vision',
                    executable='vision_monitor',
                    name='vision_monitor',
                    parameters=[vision_params],
                    output='screen',
                ),
            ],
        ),
        TimerAction(
            period=5.0,
            actions=[
                Node(
                    package='ucar_vision',
                    executable='alarm_controller',
                    name='alarm_controller',
                    parameters=[vision_params, {'sim_mode': sim_mode}],
                    output='screen',
                ),
            ],
        ),

        LogInfo(msg='════════════════════════════════════'),
        LogInfo(msg='  巡逻+监护 启动完成'),
        LogInfo(msg='  另需终端: 摄像头驱动 + BPU检测'),
        LogInfo(msg='  报警: M260C USB音频 + GPIO23 LED'),
        LogInfo(msg='════════════════════════════════════'),
    ])
