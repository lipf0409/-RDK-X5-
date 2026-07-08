#!/usr/bin/env python3
"""
视觉监护系统启动文件
启动: 跌倒检测核心 + 报警控制器 (=M260C USB音频 + GPIO LED)

硬件要求:
  - RDK X5 开发板
  - RDK Stereo Camera Module (MIPI)
  - 讯飞 M260C USB音频 (报警音播报)
  - GPIO23 → 220Ω → LED → GND (灯光报警)

前置条件 (需单独终端启动):
  终端1: 摄像头驱动
  终端2: BPU人体检测 (或CPU后备)

使用方式:
  # 先模拟模式测试:
  ros2 launch ucar_vision vision_bringup.launch.py sim_mode:=true

  # 真机运行:
  ros2 launch ucar_vision vision_bringup.launch.py
"""

import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo, TimerAction, SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    params_path = PathJoinSubstitution(
        [FindPackageShare('ucar_vision'), 'config', 'vision_params.yaml']
    )

    sim_mode = LaunchConfiguration('sim_mode', default='false')

    return LaunchDescription([
        # ★ 不注入 hobot_shm — rclpy 无法接收共享内存中的 CompressedImage
        #    如需性能优化，后续用 C++ bridge 节点中转
        # SetEnvironmentVariable('RMW_FASTRTPS_USE_QOS_FROM_XML', '1'),
        # SetEnvironmentVariable('FASTRTPS_DEFAULT_PROFILES_FILE',
        #                        '/opt/tros/humble/lib/hobot_shm/config/shm_fastdds.xml'),

        DeclareLaunchArgument('sim_mode', default_value='false',
                              description='模拟模式: true=不操作硬件仅打日志, false=真实GPIO+音频'),

        LogInfo(msg='════════════════════════════════════'),
        LogInfo(msg='  ucar_vision 视觉监护系统'),
        LogInfo(msg='  hobot_shm 已注入'),
        LogInfo(msg='════════════════════════════════════'),

        # ═══════════════════════════════════════
        # 1. 跌倒检测核心节点 (vision_monitor)
        # ═══════════════════════════════════════
        Node(
            package='ucar_vision',
            executable='vision_monitor',
            name='vision_monitor',
            parameters=[params_path],
            output='screen',
        ),

        # ═══════════════════════════════════════
        # 2. 报警控制器 (alarm_controller)
        # ═══════════════════════════════════════
        TimerAction(
            period=2.0,
            actions=[
                Node(
                    package='ucar_vision',
                    executable='alarm_controller',
                    name='alarm_controller',
                    parameters=[params_path, {'sim_mode': sim_mode}],
                    output='screen',
                ),
            ],
        ),

        LogInfo(msg='──────────────────────────────'),
        LogInfo(msg='  话题列表:'),
        LogInfo(msg='    深度: /StereoNetNode/stereonet_compresseddepth (CompressedImage)'),
        LogInfo(msg='    图像: /StereoNetNode/rectified_image'),
        LogInfo(msg='    发布: /fall_alert, /fire_alert, /alarm_status'),
        LogInfo(msg='──────────────────────────────'),
    ])
