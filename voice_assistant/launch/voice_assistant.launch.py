"""
启动语音助手 ROS2 节点
用法: ros2 launch voice_assistant voice_assistant.launch.py
"""
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package="voice_assistant",
            executable="voice_assistant_node",
            name="voice_assistant_node",
            output="screen",
            parameters=[],
        ),
    ])
