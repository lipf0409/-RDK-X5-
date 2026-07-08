#!/usr/bin/env python3
"""
双目视觉跌倒检测核心节点 (RDK X5 + MIPI双目深度摄像头)

技术路线:
  1. 订阅 hobot_dnn BPU推理的人体检测结果 (/person_detections)
  2. 订阅对齐后的深度图 (/camera/aligned_depth_to_color/image_raw)
  3. 对每个人体bbox → 提取头部区域 → 深度查表 → 反投影到3D世界坐标
  4. 卡尔曼滤波平滑头部高度估计
  5. 多条件融合判决: 头部高度 + 人体宽高比 + 时序验证

核心创新点:
  - 3D反投影: 2D bbox中心 + 深度 → 相机3D坐标 → 世界离地高度
  - 卡尔曼滤波: 抑制双目深度噪声，避免抖动误报
  - 多条件融合: 高度<0.5m AND 宽高比>1.2 AND 持续>1.5s → 判决跌倒
  - ROI中值采样: 头部区域多像素深度中值，抗离群噪声
"""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image, CameraInfo, CompressedImage
from vision_msgs.msg import Detection2DArray, Detection2D, BoundingBox2D, ObjectHypothesisWithPose
from std_msgs.msg import String, Float32, Bool, Header
import numpy as np
import cv2
from cv_bridge import CvBridge
import math
import time
import os
from datetime import datetime


# ── 颜色输出 (终端告警醒目) ──
class Colors:
    RED = '\033[91m'
    YELLOW = '\033[93m'
    GREEN = '\033[92m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


class VisionMonitor(Node):
    """双目3D跌倒检测 + 火焰检测节点"""

    def __init__(self):
        super().__init__('vision_monitor')

        # ═══════════════════════════════════════
        # 参数声明 (可通过 yaml 或 launch 覆盖)
        # ═══════════════════════════════════════
        self.declare_parameter('camera_height', 0.35)        # 摄像头离地高度(m)
        self.declare_parameter('camera_pitch_deg', 0.0)      # 俯仰角(度) 上仰为正
        self.declare_parameter('depth_is_float', True)        # 深度图格式: True=32FC1米, False=16UC1毫米
        self.declare_parameter('depth_is_compressed', False) # True=CompressedImage, False=raw Image
        self.declare_parameter('head_height_threshold', 0.45) # 头部<此高度(m)判跌倒
        self.declare_parameter('aspect_ratio_threshold', 1.15)# 宽高比>此值辅助判跌倒
        self.declare_parameter('fall_duration_threshold', 1.2)# 持续秒数才触发报警
        self.declare_parameter('fall_cooldown', 5.0)          # 报警冷却时间(秒)
        self.declare_parameter('kf_process_noise', 0.01)      # 卡尔曼过程噪声
        self.declare_parameter('kf_measure_noise', 0.05)      # 卡尔曼测量噪声
        self.declare_parameter('depth_roi_size', 7)            # 头部ROI采样尺寸(像素)
        self.declare_parameter('depth_min_valid', 300)         # 最小有效深度(mm)
        self.declare_parameter('depth_max_valid', 10000)       # 最大有效深度(mm)
        self.declare_parameter('save_snapshots', True)         # 是否存证拍照
        self.declare_parameter('snapshot_dir', '/home/sunrise/snapshots')
        self.declare_parameter('detection_topic', '/person_detections')
        self.declare_parameter('depth_topic', '/camera/aligned_depth_to_color/image_raw')
        self.declare_parameter('camera_info_topic', '/camera/color/camera_info')
        self.declare_parameter('color_topic', '/camera/color/image_raw')
        self.declare_parameter('publish_debug_image', True)    # 是否发布调试图像

        # 读取参数
        self.camera_height = self.get_parameter('camera_height').value
        self.camera_pitch = math.radians(self.get_parameter('camera_pitch_deg').value)
        self.head_height_threshold = self.get_parameter('head_height_threshold').value
        self.aspect_ratio_threshold = self.get_parameter('aspect_ratio_threshold').value
        self.fall_duration_threshold = self.get_parameter('fall_duration_threshold').value
        self.fall_cooldown = self.get_parameter('fall_cooldown').value
        self.depth_roi_size = self.get_parameter('depth_roi_size').value
        self.depth_min_valid = self.get_parameter('depth_min_valid').value
        self.depth_max_valid = self.get_parameter('depth_max_valid').value
        self.save_snapshots = self.get_parameter('save_snapshots').value
        self.snapshot_dir = self.get_parameter('snapshot_dir').value
        self.publish_debug = self.get_parameter('publish_debug_image').value

        # ═══════════════════════════════════════
        # 订阅
        # ═══════════════════════════════════════
        self.create_subscription(
            Detection2DArray,
            self.get_parameter('detection_topic').value,
            self.detection_callback, 10)

        self.depth_is_compressed = self.get_parameter('depth_is_compressed').value
        if self.depth_is_compressed:
            self.create_subscription(
                CompressedImage,
                self.get_parameter('depth_topic').value,
                self.depth_compressed_callback, 10)
        else:
            self.create_subscription(
                Image,
                self.get_parameter('depth_topic').value,
                self.depth_callback, 10)

        self.create_subscription(
            CameraInfo,
            self.get_parameter('camera_info_topic').value,
            self.camera_info_callback, 10)

        # RGB图像 (用于存证拍照 + 调试可视化)
        self.create_subscription(
            Image,
            self.get_parameter('color_topic').value,
            self.color_callback, 10)

        # ═══════════════════════════════════════
        # 发布
        # ═══════════════════════════════════════
        self.fall_alert_pub = self.create_publisher(Bool, '/fall_alert', 10)
        self.fire_alert_pub = self.create_publisher(Bool, '/fire_alert', 10)
        self.status_pub = self.create_publisher(String, '/monitor_status', 10)
        self.height_pub = self.create_publisher(Float32, '/person_head_height', 10)

        # 调试图像发布
        if self.publish_debug:
            self.debug_pub = self.create_publisher(Image, '/vision_monitor/debug', 10)

        # ═══════════════════════════════════════
        # 内部状态
        # ═══════════════════════════════════════
        self.bridge = CvBridge()
        self.latest_depth = None       # 深度图 (16UC1, mm)
        self.latest_color = None       # RGB图
        self.latest_detections = None  # 人体检测结果
        self.detection_stamp = None    # 检测时间戳
        self.camera_matrix = None      # 相机内参矩阵 3x3
        self.dist_coeffs = None        # 畸变系数

        # 卡尔曼滤波器 (跟踪头部离地高度)
        self.kf_state = 1.7            # 初始假设站立，头高1.7m
        self.kf_P = 0.5                # 初始协方差
        self.kf_Q = self.get_parameter('kf_process_noise').value
        self.kf_R = self.get_parameter('kf_measure_noise').value

        # 跌倒判决状态机
        self.fall_counter = 0.0        # 跌倒帧累计
        self.last_alarm_time = 0.0     # 上次报警时间 (ROS time seconds)
        self.person_history = []       # 最近N帧的人体检测信息 [{height, aspect, timestamp}]
        self.max_history = 30

        # 火焰颜色检测状态
        self.fire_counter = 0.0
        self.fire_alarm_active = False

        # 性能统计
        self.fps_counter = 0
        self.fps_timer = time.time()
        self.current_fps = 0.0

        # 快照目录
        if self.save_snapshots:
            os.makedirs(self.snapshot_dir, exist_ok=True)
            os.makedirs(os.path.join(self.snapshot_dir, 'fall'), exist_ok=True)
            os.makedirs(os.path.join(self.snapshot_dir, 'fire'), exist_ok=True)

        # ═══════════════════════════════════════
        # 定时器 (10Hz主循环)
        # ═══════════════════════════════════════
        self.create_timer(0.1, self.monitor_loop)

        # 状态发布定时器 (2Hz)
        self.create_timer(0.5, self.publish_status)

        self.get_logger().info(
            f'{Colors.BOLD}Vision Monitor initialized{Colors.RESET}')
        self.get_logger().info(
            f'  Camera height: {self.camera_height}m | '
            f'Fall threshold: {self.head_height_threshold}m | '
            f'Duration: {self.fall_duration_threshold}s')
        self.get_logger().info(
            f'  Depth topic: {self.get_parameter("depth_topic").value}')
        self.get_logger().info(
            f'  Detection topic: {self.get_parameter("detection_topic").value}')

    # ═══════════════════════════════════════
    # 回调函数
    # ═══════════════════════════════════════

    def camera_info_callback(self, msg):
        """接收相机内参"""
        if self.camera_matrix is None:
            self.camera_matrix = np.array(msg.k, dtype=np.float32).reshape(3, 3)
            self.dist_coeffs = np.array(msg.d, dtype=np.float32)
            self.get_logger().info(
                f'{Colors.GREEN}Camera intrinsics loaded: '
                f'fx={self.camera_matrix[0,0]:.1f} '
                f'fy={self.camera_matrix[1,1]:.1f} '
                f'cx={self.camera_matrix[0,2]:.1f} '
                f'cy={self.camera_matrix[1,2]:.1f}{Colors.RESET}')

    def depth_callback(self, msg):
        """接收深度图 (兼容 16UC1 mm 和 32FC1 m)"""
        try:
            if self.get_parameter('depth_is_float').value:
                # 32FC1: 浮点米 → 转 16UC1 毫米
                depth_float = self.bridge.imgmsg_to_cv2(msg, "32FC1")
                self.latest_depth = (depth_float * 1000.0).astype(np.uint16)
            else:
                self.latest_depth = self.bridge.imgmsg_to_cv2(msg, "16UC1")
        except Exception as e:
            self.get_logger().warn(f'Depth decode error: {e}')

    def depth_compressed_callback(self, msg):
        """接收压缩深度图 (CompressedImage, PNG格式)"""
        try:
            # PNG 解码 → numpy
            np_arr = np.frombuffer(msg.data, dtype=np.uint8)
            depth_decoded = cv2.imdecode(np_arr, cv2.IMREAD_UNCHANGED)
            if depth_decoded is None:
                return
            # stereonet compresseddepth 通常是 16UC1 mm
            if depth_decoded.dtype == np.uint16:
                self.latest_depth = depth_decoded
            elif depth_decoded.dtype == np.float32:
                self.latest_depth = (depth_decoded * 1000.0).astype(np.uint16)
            else:
                self.latest_depth = depth_decoded.astype(np.uint16)
        except Exception as e:
            self.get_logger().warn(f'CompressedDepth decode error: {e}')

    def color_callback(self, msg):
        """接收RGB图像 (支持 bgr8 / rgb8 / nv12 格式)"""
        # 尝试标准 bgr8 格式
        try:
            self.latest_color = self.bridge.imgmsg_to_cv2(msg, "bgr8")
            return
        except Exception:
            pass

        # 尝试 NV12 格式 (地平线 RDK stereonet 输出格式)
        enc = getattr(msg, 'encoding', '').lower()
        if enc == 'nv12':
            try:
                h, w = msg.height, msg.width
                data = np.frombuffer(msg.data, dtype=np.uint8)
                nv12 = data[:int(h * 1.5) * w].reshape(int(h * 1.5), w)
                self.latest_color = cv2.cvtColor(nv12, cv2.COLOR_YUV2BGR_NV12)
                return
            except Exception:
                pass

        # 尝试 rgb8 格式
        try:
            self.latest_color = self.bridge.imgmsg_to_cv2(msg, "rgb8")
            self.latest_color = cv2.cvtColor(self.latest_color, cv2.COLOR_RGB2BGR)
        except Exception:
            pass

    def detection_callback(self, msg):
        """接收人体检测结果 (来自 hobot_dnn BPU推理)"""
        self.latest_detections = msg
        self.detection_stamp = self.get_clock().now()

    # ═══════════════════════════════════════
    # 主处理循环 (10Hz)
    # ═══════════════════════════════════════

    def monitor_loop(self):
        """每100ms执行一次: 处理检测结果 + 判决"""
        # FPS计数
        self.fps_counter += 1
        elapsed = time.time() - self.fps_timer
        if elapsed > 2.0:
            self.current_fps = self.fps_counter / elapsed
            self.fps_counter = 0
            self.fps_timer = time.time()

        # 检查数据就绪
        if self.latest_depth is None:
            return
        if self.camera_matrix is None:
            now = self.get_clock().now().nanoseconds / 1e9
            if not hasattr(self, '_last_caminfo_warn') or now - self._last_caminfo_warn > 5.0:
                self.get_logger().warn('Waiting for camera_info... Have you set the correct camera_info topic?')
                self._last_caminfo_warn = now
            return

        # 深度自检测人体 (替代外部 person_detector)
        if self.latest_detections is None:
            fallback_dets = self._detect_person_from_depth(self.latest_depth)
            if fallback_dets is None:
                self._fallback_det_ok = False
                self.fall_counter = max(0.0, self.fall_counter - 0.2)
                self.fire_counter = max(0.0, self.fire_counter - 0.15)
                return
            self._fallback_det_ok = True
            dets = fallback_dets
        else:
            dets = self.latest_detections
            # 检测超时检查——只在外部检测模式下
            if self.detection_stamp is not None:
                dt_det = (self.get_clock().now() - self.detection_stamp).nanoseconds / 1e9
                if dt_det > 0.5:
                    self.fall_counter = max(0.0, self.fall_counter - 0.15)
                    return

        depth = self.latest_depth
        dets = dets
        h, w = depth.shape

        # 相机内参简写
        fx = self.camera_matrix[0, 0]
        fy = self.camera_matrix[1, 1]
        cx = self.camera_matrix[0, 2]
        cy = self.camera_matrix[1, 2]

        person_found = False
        min_head_height = 999.0
        best_aspect = 1.0
        best_person = None

        # 准备调试图像
        debug_img = None
        if self.publish_debug and self.latest_color is not None:
            debug_img = self.latest_color.copy()

        # ── 遍历所有检测到的人 ──
        for i, det in enumerate(dets.detections):
            # 兼容两种 Detection2D 格式:
            # 格式1: results[0].hypothesis.class_id (vision_msgs标准)
            # 格式2: id 字段直接存类别名 (hobot_dnn兼容)
            class_name = self._get_class_name(det)

            # ── 人体处理 ──
            if class_name == 'person' or class_name == '人':
                person_found = True

                # 提取 bbox (归一化坐标 → 像素坐标)
                bbox = det.bbox
                bx = int(bbox.center.position.x * w)
                by = int(bbox.center.position.y * h)
                bw = int(bbox.size_x * w)
                bh = int(bbox.size_y * h)

                # 裁剪到图像范围内
                bx = max(0, min(w - 1, bx))
                by = max(0, min(h - 1, by))

                # ── 头部区域: bbox上半部分1/3处 ──
                head_y = int(by - bh * 0.3)  # bbox中心向上30%作为头部
                head_y = max(0, min(h - 1, head_y))

                # ── ROI深度采样 (中值滤波抗噪) ──
                r = self.depth_roi_size // 2
                roi_y1 = max(0, head_y - r)
                roi_y2 = min(h, head_y + r + 1)
                roi_x1 = max(0, bx - r)
                roi_x2 = min(w, bx + r + 1)
                head_roi = depth[roi_y1:roi_y2, roi_x1:roi_x2]

                valid_depths = head_roi[(head_roi > self.depth_min_valid) &
                                        (head_roi < self.depth_max_valid)]

                if len(valid_depths) < 5:
                    continue  # 深度数据不足，跳过此人

                # 中值深度 (mm)，抗飞点和黑洞噪声
                head_depth_mm = float(np.median(valid_depths))
                head_depth_m = head_depth_mm / 1000.0  # 转米

                # ── 反投影到相机3D坐标系 ──
                # 针孔模型: X = (u - cx) * Z / fx, Y = (v - cy) * Z / fy
                X_cam = (bx - cx) * head_depth_m / fx
                Y_cam = (head_y - cy) * head_depth_m / fy
                Z_cam = head_depth_m

                # ── 计算世界离地高度 ──
                # 相机坐标系: X右 Y下 Z前 (OpenCV标准)
                # Y_cam 正值向下, 摄像头安装高度 camera_height
                # 考虑俯仰角: 俯视时相机光轴向下倾斜
                # 简化模型: 头部离地高度 = camera_height - Y_cam(世界)
                # Y_world ≈ Y_cam * cos(pitch) + Z_cam * sin(pitch)
                Y_world = Y_cam * math.cos(self.camera_pitch) + Z_cam * math.sin(self.camera_pitch)
                head_height_ground = self.camera_height - Y_world

                # ── 卡尔曼滤波 ──
                filtered_height = self.kalman_update(head_height_ground)

                # ── 人体宽高比 (辅助判断) ──
                aspect_ratio = bw / max(bh, 1)

                # 记录最优
                if filtered_height < min_head_height:
                    min_head_height = filtered_height
                    best_aspect = aspect_ratio
                    best_person = {
                        'bbox': (bx, by, bw, bh),
                        'head_y': head_y,
                        'head_depth_m': head_depth_m,
                        'height': filtered_height,
                        'aspect': aspect_ratio,
                        'cam_3d': (X_cam, Y_cam, Z_cam),
                    }

                # 发布头部高度 (用于其他节点)
                self.height_pub.publish(Float32(data=filtered_height))

                # ── 绘制调试信息 ──
                if debug_img is not None:
                    # 人体框 (绿色)
                    x1 = max(0, bx - bw // 2)
                    y1 = max(0, by - bh // 2)
                    x2 = min(debug_img.shape[1], bx + bw // 2)
                    y2 = min(debug_img.shape[0], by + bh // 2)
                    cv2.rectangle(debug_img, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    # 头部采样点 (红色)
                    cv2.circle(debug_img, (bx, head_y), 5, (0, 0, 255), -1)
                    # 高度文字
                    label = f'H:{filtered_height:.2f}m AR:{aspect_ratio:.2f}'
                    cv2.putText(debug_img, label, (x1, y1 - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

            # ── 火焰检测 (基于HSV颜色空间) ──
            elif class_name == 'fire' or class_name == '火焰':
                # BPU检测到火焰 → 直接累积
                self.fire_counter += 1.0

        # ── 多条件融合跌倒判决 ──
        if person_found and min_head_height < self.head_height_threshold:
            # 条件1: 头部低于阈值
            # 条件2: 宽高比大 (倒地时人体bbox更宽)
            # 两个条件权重不同
            if best_aspect > self.aspect_ratio_threshold:
                self.fall_counter += 1.0       # 高度+宽高比都符合, 快速累积
            else:
                self.fall_counter += 0.5       # 仅高度符合, 慢速累积 (可能蹲下)
        elif person_found:
            # 头部高度正常 → 衰减
            self.fall_counter = max(0.0, self.fall_counter - 0.5)
        else:
            # 没检测到人 → 慢衰减
            self.fall_counter = max(0.0, self.fall_counter - 0.15)

        # ── 火焰判决 (始终运行, 不依赖人体检测) ──
        if self.latest_color is not None:
            fire_score = self.detect_fire_color(self.latest_color)
            if fire_score > 0.3:
                self.fire_counter += fire_score * 0.5
            else:
                self.fire_counter = max(0.0, self.fire_counter - 0.1)

        # ── 触发报警 ──
        fall_frames_needed = self.fall_duration_threshold * 10.0  # 10Hz → 帧数
        fire_frames_needed = self.fall_duration_threshold * 10.0

        now_sec = self.get_clock().now().nanoseconds / 1e9

        if self.fall_counter >= fall_frames_needed:
            if now_sec - self.last_alarm_time > self.fall_cooldown:
                self.trigger_fall_alarm(min_head_height, best_aspect, best_person)
                self.last_alarm_time = now_sec
                self.fall_counter = 0.0

        if self.fire_counter >= fire_frames_needed:
            if now_sec - self.last_alarm_time > self.fall_cooldown:
                self.trigger_fire_alarm()
                self.last_alarm_time = now_sec
                self.fire_counter = 0.0

        # ── 发布调试图像 ──
        if self.publish_debug and debug_img is not None:
            status_text = f'FPS:{self.current_fps:.1f} Fall:{self.fall_counter:.0f}/{fall_frames_needed:.0f}'
            cv2.putText(debug_img, status_text, (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            if min_head_height < 999.0:
                h_text = f'MinHeight:{min_head_height:.2f}m'
                color = (0, 0, 255) if min_head_height < self.head_height_threshold else (0, 255, 0)
                cv2.putText(debug_img, h_text, (10, 60),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

            debug_msg = self.bridge.cv2_to_imgmsg(debug_img, "bgr8")
            debug_msg.header.stamp = self.get_clock().now().to_msg()
            debug_msg.header.frame_id = 'camera_color_frame'
            self.debug_pub.publish(debug_msg)

    # ═══════════════════════════════════════
    # 卡尔曼滤波器
    # ═══════════════════════════════════════

    def kalman_update(self, measurement):
        """一维卡尔曼滤波: 跟踪头部离地高度"""
        # 预测
        self.kf_P += self.kf_Q
        # 更新
        K = self.kf_P / (self.kf_P + self.kf_R)
        self.kf_state += K * (measurement - self.kf_state)
        self.kf_P *= (1.0 - K)
        return self.kf_state

    # ═══════════════════════════════════════
    # 火焰颜色检测 (CPU后备方案)
    # ═══════════════════════════════════════

    def detect_fire_color(self, bgr_img):
        """
        基于HSV颜色空间的火焰检测 (不需要BPU模型)
        返回值: 0.0 ~ 1.0 火焰置信度
        """
        hsv = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2HSV)

        # 火焰颜色范围 (橙红-黄色, 宽松阈值适配不同光照)
        lower1 = np.array([0, 60, 110])
        upper1 = np.array([30, 255, 255])
        lower2 = np.array([155, 60, 110])
        upper2 = np.array([180, 255, 255])

        mask1 = cv2.inRange(hsv, lower1, upper1)
        mask2 = cv2.inRange(hsv, lower2, upper2)
        mask = cv2.bitwise_or(mask1, mask2)

        # 形态学去噪
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        # 火焰像素占比
        fire_ratio = np.sum(mask > 0) / (mask.shape[0] * mask.shape[1])

        # 检查是否有集中高亮区域 (火焰特征)
        if fire_ratio > 0.01:
            # 统计连通区域
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            large_fire = [c for c in contours if cv2.contourArea(c) > 500]
            if large_fire:
                return min(1.0, fire_ratio * 10.0)  # 归一化到0-1

        return 0.0

    # ═══════════════════════════════════════
    # 报警触发
    # ═══════════════════════════════════════

    def trigger_fall_alarm(self, height, aspect, person_info):
        """触发跌倒报警"""
        msg = Bool(data=True)
        self.fall_alert_pub.publish(msg)

        self.get_logger().error(
            f'{Colors.RED}{Colors.BOLD}'
            f'╔══════════════════════════════╗\n'
            f'║  🚨 跌倒报警触发！           ║\n'
            f'║  头部高度: {height:.2f}m             ║\n'
            f'║  宽高比:   {aspect:.2f}                 ║\n'
            f'║  阈值:     <{self.head_height_threshold}m             ║\n'
            f'╚══════════════════════════════╝'
            f'{Colors.RESET}'
        )

        # 存证拍照
        if self.save_snapshots and self.latest_color is not None:
            self.save_snapshot('fall', person_info)

    def trigger_fire_alarm(self):
        """触发火焰报警"""
        msg = Bool(data=True)
        self.fire_alert_pub.publish(msg)
        self.fire_alarm_active = True

        self.get_logger().error(
            f'{Colors.RED}{Colors.BOLD}'
            f'╔══════════════════════════════╗\n'
            f'║  🔥 火焰报警触发！           ║\n'
            f'╚══════════════════════════════╝'
            f'{Colors.RESET}'
        )

        # 存证拍照
        if self.save_snapshots and self.latest_color is not None:
            self.save_snapshot('fire')

    def save_snapshot(self, alarm_type, person_info=None):
        """保存报警现场快照"""
        if self.latest_color is None:
            return

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
        subdir = os.path.join(self.snapshot_dir, alarm_type)

        # 保存RGB原图
        rgb_path = os.path.join(subdir, f'{timestamp}_rgb.jpg')
        cv2.imwrite(rgb_path, self.latest_color)

        # 如果有人体信息，标注后保存
        if person_info is not None:
            annotated = self.latest_color.copy()
            bx, by, bw, bh = person_info['bbox']
            x1 = max(0, bx - bw // 2)
            y1 = max(0, by - bh // 2)
            x2 = min(annotated.shape[1], bx + bw // 2)
            y2 = min(annotated.shape[0], by + bh // 2)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 0, 255), 3)
            cv2.putText(annotated,
                        f'FALL ALERT! H:{person_info["height"]:.2f}m',
                        (x1, y1 - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            ann_path = os.path.join(subdir, f'{timestamp}_annotated.jpg')
            cv2.imwrite(ann_path, annotated)

        # 保存深度图 (如果有)
        if self.latest_depth is not None:
            depth_norm = cv2.normalize(self.latest_depth, None, 0, 255, cv2.NORM_MINMAX)
            depth_norm = depth_norm.astype(np.uint8)
            depth_path = os.path.join(subdir, f'{timestamp}_depth.jpg')
            cv2.imwrite(depth_path, depth_norm)

        self.get_logger().info(f'Snapshot saved to {subdir}/{timestamp}_*')

    # ═══════════════════════════════════════
    # 状态发布
    # ═══════════════════════════════════════

    def publish_status(self):
        """定期发布系统状态"""
        has_det = (self.latest_detections is not None) or getattr(self, '_fallback_det_ok', False)
        status = (
            f'FPS:{self.current_fps:.1f} '
            f'KF_height:{self.kf_state:.2f}m '
            f'Fall_counter:{self.fall_counter:.0f} '
            f'Fire_counter:{self.fire_counter:.0f} '
            f'Has_depth:{self.latest_depth is not None} '
            f'Has_color:{self.latest_color is not None} '
            f'Has_det:{has_det}'
        )
        self.status_pub.publish(String(data=status))

    # ═══════════════════════════════════════
    # 深度前景人体检测 (不需要外部 person_detector)
    # ═══════════════════════════════════════

    def _detect_person_from_depth(self, depth):
        """最简人体检测: 深度前景像素的包围盒
        不需要 HOG/轮廓/BPU, 纯numpy, <1ms"""
        # 有效深度范围 (0.3~5m = 人在摄像头前)
        fg_mask = (depth > 300) & (depth < 5000)

        # 找前景像素的行列索引
        rows, cols = np.where(fg_mask)
        n_fg = len(rows)

        # 调试计数
        if not hasattr(self, '_fd_count'):
            self._fd_count = 0
            self._fd_last_log = 0
        self._fd_count += 1

        # 每30次打印一次状态
        if self._fd_count - self._fd_last_log >= 30:
            pct = 100.0 * n_fg / depth.size
            self.get_logger().info(
                f'[depth-detect] #{self._fd_count}: fg_pixels={n_fg} ({pct:.1f}%) '
                f'need>=800 area_min=600')
            self._fd_last_log = self._fd_count

        if n_fg < 800:  # 前景像素太少 = 没人
            return None

        # 包围盒
        y1, y2 = rows.min(), rows.max()
        x1, x2 = cols.min(), cols.max()
        bw, bh = x2 - x1, y2 - y1

        # 面积太小 = 噪声
        if bw * bh < 600:
            return None

        # 找到人了
        self.get_logger().info(
            f'  → Person found: {bw}x{bh} @({x1},{y1}) fg={n_fg}px',
            throttle_duration_sec=2.0)

        h, w = depth.shape
        msg = Detection2DArray()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'camera_depth_frame'

        det = Detection2D()
        det.header = msg.header
        det.bbox = BoundingBox2D()
        det.bbox.center.position.x = float(x1 + bw / 2) / w
        det.bbox.center.position.y = float(y1 + bh / 2) / h
        det.bbox.size_x = float(bw) / w
        det.bbox.size_y = float(bh) / h

        hyp = ObjectHypothesisWithPose()
        hyp.hypothesis.class_id = 'person'
        hyp.hypothesis.score = 0.8
        det.results.append(hyp)
        msg.detections.append(det)
        return msg

    # ═══════════════════════════════════════
    # 辅助函数
    # ═══════════════════════════════════════

    @staticmethod
    def _get_class_name(det):
        """兼容多种 Detection2D 类别格式"""
        if det.results and len(det.results) > 0:
            hyp = det.results[0].hypothesis
            if hasattr(hyp, 'class_id') and hyp.class_id:
                return str(hyp.class_id).lower()
        # 兼容 hobot_dnn 格式 (类别名在id字段)
        if hasattr(det, 'id') and det.id:
            return str(det.id).lower()
        return 'unknown'

    def destroy_node(self):
        self.get_logger().info('Vision Monitor shutting down')
        super().destroy_node()


def main(args=None):
    # ★ 不注入 hobot_shm — rclpy 与共享内存 CompressedImage 不兼容
    #    改用标准 DDS 传输，订阅 raw Image 格式的 stereonet_depth
    rclpy.init(args=args)
    node = VisionMonitor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
