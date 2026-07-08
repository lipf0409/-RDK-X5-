#!/usr/bin/env python3
"""
板端深度图录制 — 用于导出深度帧到PC分析
══════════════════════════════════════════════════
在 RDK X5 上运行此脚本，将深度图保存为 PNG 文件。
之后拷贝到 PC 用 depth_analyzer.py 分析调参。

用法 (在板端):
  cd ~/ucar_01
  source /opt/tros/humble/setup.bash
  unset RMW_FASTRTPS_USE_QOS_FROM_XML
  unset FASTRTPS_DEFAULT_PROFILES_FILE

  # 保存 50 帧深度图
  python3 save_depth_frames.py --count 50

  # 保存到指定目录
  python3 save_depth_frames.py --count 100 --output ~/depth_samples/

  # 全部使用默认值
  python3 save_depth_frames.py

前提: MIPI 摄像头 + stereonet 已在其他终端运行
  终端1: taskset -c 0,1 ros2 launch mipi_cam mipi_cam_dual_channel.launch.py
  终端2: taskset -c 2,3 ros2 launch hobot_stereonet stereonet_model.launch.py ...
"""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
import numpy as np
import cv2
import os
import sys
import time
from datetime import datetime


class DepthFrameSaver(Node):
    """订阅压缩深度图并保存为PNG"""

    def __init__(self, output_dir, max_frames):
        super().__init__('depth_frame_saver')

        self.output_dir = output_dir
        self.max_frames = max_frames
        self.saved_count = 0
        self.last_save_time = 0.0
        self.save_interval = 0.5  # 每0.5秒保存一帧（避免重复）

        os.makedirs(self.output_dir, exist_ok=True)

        # 订阅压缩深度图
        self.create_subscription(
            CompressedImage,
            '/StereoNetNode/stereonet_compresseddepth',
            self.depth_callback,
            10)

        self.get_logger().info(
            f'Depth Frame Saver ready.\n'
            f'  Saving to: {self.output_dir}\n'
            f'  Max frames: {max_frames}\n'
            f'  Interval: {self.save_interval}s\n'
            f'  Waiting for depth frames...')

    def depth_callback(self, msg):
        """收到深度帧"""
        now = time.time()
        if now - self.last_save_time < self.save_interval:
            return
        if self.saved_count >= self.max_frames:
            return

        try:
            # 解码 PNG 压缩深度图
            np_arr = np.frombuffer(msg.data, dtype=np.uint8)
            depth = cv2.imdecode(np_arr, cv2.IMREAD_UNCHANGED)

            if depth is None:
                self.get_logger().warn('Failed to decode depth image')
                return

            # 保存为 16-bit PNG
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
            filename = f'depth_{self.saved_count:04d}_{depth.shape[1]}x{depth.shape[0]}_{timestamp}.png'
            filepath = os.path.join(self.output_dir, filename)

            cv2.imwrite(filepath, depth)
            self.saved_count += 1
            self.last_save_time = now

            self.get_logger().info(
                f'[{self.saved_count}/{self.max_frames}] Saved: {filename} '
                f'shape={depth.shape} dtype={depth.dtype} '
                f'range=[{depth.min()}, {depth.max()}]')

            # 检查是否完成
            if self.saved_count >= self.max_frames:
                self.get_logger().info(
                    f'\n{"="*50}\n'
                    f'  Done! {self.max_frames} frames saved to:\n'
                    f'  {self.output_dir}\n'
                    f'\n'
                    f'  Copy to PC and run:\n'
                    f'  python depth_analyzer.py --folder {self.output_dir} --interactive\n'
                    f'{"="*50}')
                # 不退出，让用户手动 Ctrl+C

        except Exception as e:
            self.get_logger().error(f'Error saving depth frame: {e}')


def main():
    # 解析简单命令行参数 (不依赖 argparse — 板端可能没有)
    import argparse
    parser = argparse.ArgumentParser(description='Save depth frames for PC analysis')
    parser.add_argument('--count', type=int, default=50,
                        help='Number of frames to save (default: 50)')
    parser.add_argument('--output', type=str, default=None,
                        help='Output directory (default: ~/depth_samples_TIMESTAMP)')
    parser.add_argument('--interval', type=float, default=0.5,
                        help='Save interval in seconds (default: 0.5)')
    args = parser.parse_args()

    if args.output is None:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        args.output = os.path.expanduser(f'~/depth_samples_{ts}')

    rclpy.init()
    node = DepthFrameSaver(args.output, args.count)
    node.save_interval = args.interval

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
