#!/usr/bin/env python3
"""
板端背景差分人体检测 — ROS2 节点
══════════════════════════════════
部署到 RDK X5，与 vision_monitor 配合使用。

算法: 深度图背景差分
  - 启动后前 bg_init_frames 帧建立背景
  - 之后每帧与背景比较 → |diff| > threshold → 前景(人)
  - 背景缓慢更新，适应环境变化
  - 发布 /person_detections → vision_monitor 自动接收

与 vision_monitor 的配合:
  vision_monitor 订阅 /person_detections，收到后走外部检测模式
  (不再使用内置的 _detect_person_from_depth)

使用方法:
  # 先启动摄像头 + stereonet (终端1,2)
  # 终端3: 启动本节点
  source /opt/tros/humble/setup.bash
  source ~/ucar_01/install/setup.bash
  unset RMW_FASTRTPS_USE_QOS_FROM_XML
  unset FASTRTPS_DEFAULT_PROFILES_FILE

  python3 board_person_detector_node.py --ros-args \
      -p camera_height:=0.20 \
      -p bg_diff_threshold:=200 \
      -p bg_init_frames:=10

  启动后等 ~2-3 秒让背景建立(终端会打印 "Background ready")，
  然后人走进画面即可检测。

话题:
  订阅: /StereoNetNode/stereonet_compresseddepth
        /StereoNetNode/camera_info
  发布: /person_detections (Detection2DArray)
        /board_person_detector/debug (Image, 可在Foxglove查看)
"""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage, Image, CameraInfo
from vision_msgs.msg import Detection2DArray, Detection2D, BoundingBox2D, ObjectHypothesisWithPose
from cv_bridge import CvBridge
import numpy as np
import cv2
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from depth_person_detector import (
    DepthPersonDetector, CameraParams, DetectParams
)


class BoardPersonDetectorNode(Node):
    """背景差分人体检测 ROS2 节点"""

    def __init__(self):
        super().__init__('board_person_detector')

        # ── ROS 参数 ──
        self.declare_parameter('camera_height', 0.20)
        self.declare_parameter('camera_pitch_deg', -2.0)
        self.declare_parameter('bg_diff_threshold', 200)
        self.declare_parameter('bg_init_frames', 10)
        self.declare_parameter('bg_alpha', 0.05)
        self.declare_parameter('min_foreground_pixels', 500)
        self.declare_parameter('min_bbox_area', 600)
        self.declare_parameter('min_aspect_ratio', 1.5)
        self.declare_parameter('max_aspect_ratio', 8.0)
        self.declare_parameter('depth_min', 300)
        self.declare_parameter('depth_max', 8000)
        self.declare_parameter('publish_debug', True)
        self.declare_parameter('detect_interval', 0.15)

        # ── 默认相机参数 (会被 camera_info 覆盖) ──
        camera = CameraParams(
            fx=469.2, fy=469.2, cx=580.6, cy=358.9,
            height=self.get_parameter('camera_height').value,
            pitch_deg=self.get_parameter('camera_pitch_deg').value)

        params = DetectParams(
            depth_min=self.get_parameter('depth_min').value,
            depth_max=self.get_parameter('depth_max').value,
            bg_diff_threshold=self.get_parameter('bg_diff_threshold').value,
            bg_init_frames=self.get_parameter('bg_init_frames').value,
            bg_alpha=self.get_parameter('bg_alpha').value,
            min_foreground_pixels=self.get_parameter('min_foreground_pixels').value,
            min_bbox_area=self.get_parameter('min_bbox_area').value,
            min_aspect_ratio=self.get_parameter('min_aspect_ratio').value,
            max_aspect_ratio=self.get_parameter('max_aspect_ratio').value)

        self.detector = DepthPersonDetector(camera, params)
        self.latest_depth = None
        self.camera_info_updated = False
        self.bridge = CvBridge()

        # ── 订阅 ──
        self.create_subscription(
            CompressedImage,
            '/StereoNetNode/stereonet_compresseddepth',
            self.depth_callback, 10)

        self.create_subscription(
            CameraInfo,
            '/StereoNetNode/camera_info',
            self.camera_info_callback, 10)

        # ── 发布 ──
        self.det_pub = self.create_publisher(
            Detection2DArray, '/person_detections', 10)

        self.debug_pub = None
        if self.get_parameter('publish_debug').value:
            self.debug_pub = self.create_publisher(
                Image, '/board_person_detector/debug', 10)

        # ── 定时器 ──
        self.create_timer(
            self.get_parameter('detect_interval').value,
            self.detect_timer_callback)

        # 状态发布定时器
        self.create_timer(1.0, self.status_timer_callback)

        self._log_count = 0
        self.get_logger().info(
            f'Board Person Detector ready.\n'
            f'  Camera height: {camera.height:.2f}m\n'
            f'  BG init frames: {params.bg_init_frames}\n'
            f'  BG diff threshold: {params.bg_diff_threshold}mm\n'
            f'  Waiting for depth frames to build background...')

    def camera_info_callback(self, msg):
        """更新相机内参"""
        if self.camera_info_updated:
            return
        K = np.array(msg.k, dtype=np.float32).reshape(3, 3)
        self.detector.camera.fx = float(K[0, 0])
        self.detector.camera.fy = float(K[1, 1])
        self.detector.camera.cx = float(K[0, 2])
        self.detector.camera.cy = float(K[1, 2])
        self.camera_info_updated = True
        self.get_logger().info(
            f'Camera info: fx={K[0,0]:.1f} fy={K[1,1]:.1f} '
            f'cx={K[0,2]:.1f} cy={K[1,2]:.1f}')

    def depth_callback(self, msg):
        """接收深度帧"""
        try:
            arr = np.frombuffer(msg.data, dtype=np.uint8)
            depth = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
            if depth is not None:
                self.latest_depth = depth
        except Exception as e:
            self.get_logger().warn(f'Depth decode: {e}')

    def detect_timer_callback(self):
        """定时检测"""
        if self.latest_depth is None:
            return

        # 同步ROS参数(允许运行时动态调参)
        p = self.detector.params
        p.bg_diff_threshold = self.get_parameter('bg_diff_threshold').value
        p.bg_init_frames = self.get_parameter('bg_init_frames').value
        p.min_foreground_pixels = self.get_parameter('min_foreground_pixels').value
        p.min_bbox_area = self.get_parameter('min_bbox_area').value
        p.min_aspect_ratio = self.get_parameter('min_aspect_ratio').value
        p.max_aspect_ratio = self.get_parameter('max_aspect_ratio').value
        p.depth_min = self.get_parameter('depth_min').value
        p.depth_max = self.get_parameter('depth_max').value
        self.detector.camera.height = self.get_parameter('camera_height').value

        # 背景就绪状态变化时打印
        was_ready = self.detector.bg_ready
        result = self.detector.detect(self.latest_depth, return_debug=True)
        if not was_ready and self.detector.bg_ready:
            self.get_logger().info('=== Background model ready! Detection active. ===')

        # ── 发布检测结果 ──
        if result.found and result.bbox_normalized:
            self._publish_detection(result)

        # ── 发布调试图像 ──
        if self.debug_pub is not None:
            self._publish_debug(result)

        # ── 周期性日志 ──
        self._log_count += 1
        if self._log_count % 30 == 1:
            if result.bg_ready:
                status = f'PERSON bbox={result.bbox}' if result.found else 'no person'
                self.get_logger().info(
                    f'[{self._log_count}] {status} fg={result.foreground_pixels}px',
                    throttle_duration_sec=2.0)
            else:
                self.get_logger().info(
                    f'[{self._log_count}] Building background... '
                    f'({len(self.detector._bg_buffer)}/{p.bg_init_frames})')

    def status_timer_callback(self):
        """每秒发布状态"""
        if self.detector.bg_ready:
            p = self.detector.params
            self.get_logger().info(
                f'Status: bg_ready=True '
                f'diff_thr={p.bg_diff_threshold}mm '
                f'height={self.detector.camera.height:.2f}m',
                throttle_duration_sec=5.0)

    def _publish_detection(self, result):
        """发布 Detection2DArray"""
        cx_n, cy_n, bw_n, bh_n = result.bbox_normalized
        msg = Detection2DArray()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'camera_depth_frame'

        det = Detection2D()
        det.header = msg.header
        det.bbox = BoundingBox2D()
        det.bbox.center.position.x = float(cx_n)
        det.bbox.center.position.y = float(cy_n)
        det.bbox.size_x = float(bw_n)
        det.bbox.size_y = float(bh_n)

        hyp = ObjectHypothesisWithPose()
        hyp.hypothesis.class_id = 'person'
        hyp.hypothesis.score = 0.8
        det.results.append(hyp)
        msg.detections.append(det)
        self.det_pub.publish(msg)

    def _publish_debug(self, result):
        """发布调试图像 (背景、前景mask、bbox)"""
        depth = self.latest_depth
        h, w = depth.shape

        # 伪彩色深度图
        d_clip = np.clip(depth.astype(np.float32), 300, 8000)
        d_norm = ((d_clip - 300) / 7700 * 255).astype(np.uint8)
        debug = cv2.applyColorMap(d_norm, cv2.COLORMAP_TURBO)

        # 前景红色覆盖
        if result.person_mask is not None:
            debug[result.person_mask] = (0, 0, 255)

        # bbox
        if result.found and result.bbox:
            x, y, bw, bh = result.bbox
            cv2.rectangle(debug, (x, y), (x + bw, y + bh), (0, 255, 0), 3)

        # 状态文字
        if result.bg_ready:
            txt = f'PERSON fg={result.foreground_pixels}' if result.found else 'CLEAR'
            color = (0, 255, 0) if result.found else (200, 200, 200)
        else:
            txt = 'BUILDING BG...'
            color = (0, 200, 255)
        cv2.putText(debug, txt, (5, 15), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, color, 1)

        msg = self.bridge.cv2_to_imgmsg(debug, 'bgr8')
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'camera_depth_frame'
        self.debug_pub.publish(msg)


def main():
    rclpy.init()
    node = BoardPersonDetectorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
