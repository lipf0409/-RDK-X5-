#!/usr/bin/env python3
"""
深度图人体检测节点 (替代HOG, 基于深度前景分割)

原理:
  1. 接收压缩深度图 (CompressedImage, PNG, 352x640 uint16 mm)
  2. 阈值分割: 300~4000mm 范围内为前景 (人体)
  3. 找最大连通区域 → 作为人体bbox
  4. 发布 Detection2DArray 给 vision_monitor

优势:
  - 不需要BPU, 不需要HOG
  - 纯numpy+cv2基础操作, ~5ms/帧
  - 不受光照影响, 对低角度摄像头同样有效
"""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage, Image
from vision_msgs.msg import Detection2DArray, Detection2D, BoundingBox2D, ObjectHypothesisWithPose
import cv2
import numpy as np


class PersonDetector(Node):
    """深度前景分割人体检测器"""

    def __init__(self):
        super().__init__('person_detector')

        self.declare_parameter('image_topic', '/StereoNetNode/rectified_image')
        self.declare_parameter('depth_topic', '/StereoNetNode/stereonet_compresseddepth')
        self.declare_parameter('publish_topic', '/person_detections')
        self.declare_parameter('detect_interval', 0.15)  # ~6.7Hz

        # ROI: 只关心画面中央区域 (深度图 352×640)
        self.declare_parameter('roi_top_ratio', 0.0)    # 顶部裁切比例
        self.declare_parameter('roi_bottom_ratio', 0.2)  # 底部裁切比例 (避开地面)
        self.declare_parameter('depth_min', 300)          # 最小有效深度 mm
        self.declare_parameter('depth_max', 5000)         # 最大有效深度 mm
        self.declare_parameter('min_blob_area', 800)      # 最小人体区域面积 (像素)

        self.latest_depth = None
        self.latest_color = None

        # 订阅深度图
        self.create_subscription(
            CompressedImage,
            self.get_parameter('depth_topic').value,
            self.depth_callback, 10)

        # 订阅RGB (用于标注, 可选)
        self.create_subscription(
            Image,
            self.get_parameter('image_topic').value,
            self.image_callback, 10)

        # 发布检测结果
        self.det_pub = self.create_publisher(
            Detection2DArray,
            self.get_parameter('publish_topic').value, 10)

        # 定时检测
        self.create_timer(self.get_parameter('detect_interval').value, self.detect)

        self.get_logger().info('Person Detector (depth-based) initialized')

    def depth_callback(self, msg):
        """解码压缩深度图"""
        try:
            np_arr = np.frombuffer(msg.data, dtype=np.uint8)
            depth = cv2.imdecode(np_arr, cv2.IMREAD_UNCHANGED)
            if depth is not None:
                self.latest_depth = depth
        except Exception:
            pass

    def image_callback(self, msg):
        """保存最新RGB帧 (用于可能的可视化)"""
        try:
            h, w = msg.height, msg.width
            data = np.frombuffer(msg.data, dtype=np.uint8)
            nv12 = data[:int(h * 1.5) * w].reshape(int(h * 1.5), w)
            self.latest_color = cv2.cvtColor(nv12, cv2.COLOR_YUV2BGR_NV12)
        except Exception:
            pass

    def detect(self):
        if self.latest_depth is None:
            if not hasattr(self, '_noimg_count'):
                self._noimg_count = 0
            self._noimg_count += 1
            if self._noimg_count <= 3 or self._noimg_count % 30 == 0:
                self.get_logger().warn(f'No depth yet (x{self._noimg_count})')
            return

        depth = self.latest_depth
        h, w = depth.shape
        depth_min = self.get_parameter('depth_min').value
        depth_max = self.get_parameter('depth_max').value
        min_area = self.get_parameter('min_blob_area').value

        # ── 1. ROI 裁切 ──
        top_cut = int(h * self.get_parameter('roi_top_ratio').value)
        bot_cut = int(h * (1.0 - self.get_parameter('roi_bottom_ratio').value))
        roi = depth[top_cut:bot_cut, :]

        # ── 2. 深度阈值分割 (前景=人体) ──
        fg_mask = ((roi > depth_min) & (roi < depth_max)).astype(np.uint8) * 255

        # ── 3. 形态学处理 (去噪+填洞) ──
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)

        # ── 4. 找连通区域 → 最大区域 = 人体 ──
        contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        valid = [c for c in contours if cv2.contourArea(c) >= min_area]

        # 调试日志
        if not hasattr(self, '_detect_count'):
            self._detect_count = 0
        self._detect_count += 1
        if self._detect_count % 20 == 1:
            fg_pct = 100.0 * fg_mask.sum() / (255 * fg_mask.size) if fg_mask.size else 0
            self.get_logger().info(
                f'#{self._detect_count}: fg={fg_pct:.1f}% '
                f'contours={len(contours)} valid={len(valid)} '
                f'area={max([cv2.contourArea(c) for c in valid]) if valid else 0:.0f}px')

        if not valid:
            return

        # ── 5. 发布检测结果 ──
        best = max(valid, key=cv2.contourArea)
        x, y, bw, bh = cv2.boundingRect(best)
        area = cv2.contourArea(best)

        self.get_logger().info(f'  → Person: {bw}x{bh} @({x},{y}) area={area:.0f}px', throttle_duration_sec=1.0)

        # 坐标映射回原深度图 (补偿ROI偏移)
        y += top_cut

        msg = Detection2DArray()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'camera_depth_frame'

        det = Detection2D()
        det.header = msg.header
        det.bbox = BoundingBox2D()
        det.bbox.center.position.x = float(x + bw / 2) / w
        det.bbox.center.position.y = float(y + bh / 2) / h
        det.bbox.size_x = float(bw) / w
        det.bbox.size_y = float(bh) / h

        hyp = ObjectHypothesisWithPose()
        hyp.hypothesis.class_id = 'person'
        hyp.hypothesis.score = 0.85  # 深度检测置信度固定较高
        det.results.append(hyp)
        msg.detections.append(det)

        self.det_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = PersonDetector()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
