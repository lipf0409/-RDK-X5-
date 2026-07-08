#!/usr/bin/env python3
"""
ROS2 Bridge — Thread-safe data bridge between ROS2 and Qt GUI.

Architecture:
  - Runs rclpy.spin() in a dedicated QThread
  - Each subscriber callback stores latest data with QMutex protection
  - Qt signals emitted to notify GUI of new data (no copying of large buffers)
  - Singleton pattern; shared by all widget modules

Subscribers:
  /scan                              → LaserScan (point cloud for LIDAR view)
  /odom                              → Odometry (robot pose)
  /map                               → OccupancyGrid (SLAM map)
  /StereoNetNode/rectified_image     → Image (RGB camera)
  /StereoNetNode/stereonet_compresseddepth → CompressedImage (PNG depth)
  /StereoNetNode/camera_info         → CameraInfo (intrinsics)
  /monitor_status                    → String (person detection status)
  /person_head_height                → Float32 (head height in meters)
  /fall_alert                        → Bool (fall alarm trigger)
  /fire_alert                        → Bool (fire alarm trigger)

Publisher:
  /cmd_vel                           → Twist (chassis velocity)
"""

import sys
import threading
import numpy as np
import cv2
from typing import Optional

from PySide6.QtCore import QObject, Signal, QMutex, QMutexLocker

import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor

from sensor_msgs.msg import LaserScan, Image, CameraInfo, CompressedImage
from nav_msgs.msg import Odometry, OccupancyGrid
from geometry_msgs.msg import Twist
from std_msgs.msg import String, Float32, Bool


class ROS2Bridge(QObject):
    """
    Thread-safe bridge between ROS2 and Qt.

    All subscriber callbacks store latest data under mutex and emit
    Qt signals so the GUI thread can refresh displays safely.
    """

    # ── Qt Signals (emitted from ROS2 thread, received by GUI thread) ──
    scan_updated = Signal()              # /scan data refreshed
    odom_updated = Signal()              # /odom data refreshed
    map_updated = Signal()               # /map data refreshed
    rgb_image_updated = Signal()         # /rectified_image refreshed
    depth_image_updated = Signal()       # /compresseddepth refreshed
    camera_info_updated = Signal()       # /camera_info refreshed
    monitor_status_updated = Signal()    # /monitor_status refreshed
    head_height_updated = Signal()       # /person_head_height refreshed
    fall_alert_triggered = Signal(bool)  # /fall_alert changed
    fire_alert_triggered = Signal(bool)  # /fire_alert changed
    hardware_status_updated = Signal()   # sensor connectivity changed
    voice_wakeup_updated = Signal(str)   # /voice/wakeup JSON
    voice_question_updated = Signal(str) # /voice/question text
    voice_answer_updated = Signal(str)   # /voice/answer text
    voice_command_updated = Signal(str)  # /voice/command JSON

    def __init__(self):
        super().__init__()

        # ── Thread-safe data cache ──
        self._mutex = QMutex()

        # Latest scan data
        self._scan_ranges: list = []
        self._scan_angle_min: float = 0.0
        self._scan_angle_max: float = 0.0
        self._scan_angle_increment: float = 0.0
        self._scan_range_min: float = 0.0
        self._scan_range_max: float = 0.0
        self._scan_timestamp: float = 0.0
        self._scan_frame_id: str = "laser"

        # Latest odometry
        self._odom_x: float = 0.0
        self._odom_y: float = 0.0
        self._odom_theta: float = 0.0
        self._odom_vx: float = 0.0
        self._odom_va: float = 0.0

        # Latest map
        self._map_data: Optional[np.ndarray] = None
        self._map_width: int = 0
        self._map_height: int = 0
        self._map_resolution: float = 0.05
        self._map_origin_x: float = 0.0
        self._map_origin_y: float = 0.0

        # Latest RGB image (QImage compatible raw bytes)
        self._rgb_image: Optional[np.ndarray] = None  # BGR numpy array
        self._rgb_timestamp: float = 0.0

        # Latest depth image (pseudo-color RGB ready)
        self._depth_image: Optional[np.ndarray] = None  # RGB pseudo-color numpy
        self._depth_raw: Optional[np.ndarray] = None     # uint16 raw depth (mm)
        self._depth_timestamp: float = 0.0

        # Camera info
        self._fx: float = 469.2
        self._fy: float = 469.2
        self._cx: float = 580.6
        self._cy: float = 358.9
        self._cam_width: int = 640
        self._cam_height: int = 480

        # Monitor status
        self._monitor_status: str = "IDLE"
        self._head_height: float = 0.0

        # Alert states
        self._fall_alert_active: bool = False
        self._fire_alert_active: bool = False

        # Hardware connectivity
        self._lidar_connected: bool = False
        self._camera_connected: bool = False
        self._camera_fps: float = 0.0
        self._motor_ready: bool = False

        # Voice assistant
        self._voice_wakeup: str = ""
        self._voice_question: str = ""
        self._voice_answer: str = ""
        self._voice_command: str = ""
        self._voice_active: bool = False

        # ROS2 internals
        self._node: Optional[Node] = None
        self._executor: Optional[MultiThreadedExecutor] = None
        self._spin_thread: Optional[threading.Thread] = None
        self._running: bool = False

        # Publisher
        self._cmd_vel_pub = None

        # Frame rate tracking
        self._rgb_frame_count: int = 0
        self._depth_frame_count: int = 0
        self._fps_last_check: float = 0.0

    # ═══════════════════════════════════════════════════════════
    # Public API — thread-safe data access
    # ═══════════════════════════════════════════════════════════

    def start(self):
        """Initialize ROS2 node and start spin thread."""
        if self._running:
            return

        # Ensure rclpy is initialized (may already be from main)
        if not rclpy.ok():
            rclpy.init(args=sys.argv)

        self._node = Node('qt_monitor_bridge')
        self._running = True

        # ── Create subscribers ──
        self._node.create_subscription(
            LaserScan, '/scan', self._scan_callback, 10)
        self._node.create_subscription(
            Odometry, '/odom', self._odom_callback, 10)
        self._node.create_subscription(
            OccupancyGrid, '/map', self._map_callback, 10)
        self._node.create_subscription(
            Image, '/StereoNetNode/rectified_image', self._rgb_callback, 10)
        self._node.create_subscription(
            CompressedImage, '/StereoNetNode/stereonet_compresseddepth',
            self._depth_callback, 10)
        self._node.create_subscription(
            CameraInfo, '/StereoNetNode/camera_info', self._camera_info_callback, 10)
        self._node.create_subscription(
            String, '/monitor_status', self._monitor_status_callback, 10)
        self._node.create_subscription(
            Float32, '/person_head_height', self._head_height_callback, 10)
        self._node.create_subscription(
            Bool, '/fall_alert', self._fall_alert_callback, 10)
        self._node.create_subscription(
            Bool, '/fire_alert', self._fire_alert_callback, 10)
        self._node.create_subscription(
            String, '/voice/wakeup', self._voice_wakeup_callback, 10)
        self._node.create_subscription(
            String, '/voice/question', self._voice_question_callback, 10)
        self._node.create_subscription(
            String, '/voice/answer', self._voice_answer_callback, 10)
        self._node.create_subscription(
            String, '/voice/command', self._voice_command_callback, 10)

        # ── Create publisher ──
        self._cmd_vel_pub = self._node.create_publisher(Twist, '/cmd_vel', 10)

        # ── Start spin thread ──
        self._executor = MultiThreadedExecutor()
        self._executor.add_node(self._node)
        self._spin_thread = threading.Thread(
            target=self._spin_loop, daemon=True)
        self._spin_thread.start()

        self._node.get_logger().info(
            'ROS2Bridge started — 10 subscribers, 1 publisher')

    def stop(self):
        """Shutdown ROS2 node and stop spin thread."""
        self._running = False
        if self._executor:
            self._executor.remove_node(self._node)
        if self._node:
            self._node.destroy_node()
        if self._spin_thread and self._spin_thread.is_alive():
            self._spin_thread.join(timeout=2.0)

    def publish_cmd_vel(self, linear_x: float, angular_z: float):
        """Publish Twist message on /cmd_vel."""
        if self._cmd_vel_pub is None or not self._running:
            return
        msg = Twist()
        msg.linear.x = float(linear_x)
        msg.angular.z = float(angular_z)
        self._cmd_vel_pub.publish(msg)

    # ── Thread-safe getters ──

    def get_scan_data(self) -> dict:
        """Return latest scan data as a dict (thread-safe)."""
        lock = QMutexLocker(self._mutex)
        return {
            'ranges': list(self._scan_ranges),
            'angle_min': self._scan_angle_min,
            'angle_max': self._scan_angle_max,
            'angle_increment': self._scan_angle_increment,
            'range_min': self._scan_range_min,
            'range_max': self._scan_range_max,
            'timestamp': self._scan_timestamp,
            'frame_id': self._scan_frame_id,
        }

    def get_odom_data(self) -> dict:
        """Return latest odometry data (thread-safe)."""
        lock = QMutexLocker(self._mutex)
        return {
            'x': self._odom_x, 'y': self._odom_y,
            'theta': self._odom_theta,
            'vx': self._odom_vx, 'va': self._odom_va,
        }

    def get_map_data(self) -> dict:
        """Return latest SLAM map data (thread-safe)."""
        lock = QMutexLocker(self._mutex)
        return {
            'data': self._map_data.copy() if self._map_data is not None else None,
            'width': self._map_width,
            'height': self._map_height,
            'resolution': self._map_resolution,
            'origin_x': self._map_origin_x,
            'origin_y': self._map_origin_y,
        }

    def get_rgb_image(self) -> Optional[np.ndarray]:
        """Return latest RGB image as BGR numpy array (thread-safe)."""
        lock = QMutexLocker(self._mutex)
        if self._rgb_image is not None:
            return self._rgb_image.copy()
        return None

    def get_depth_image(self) -> Optional[np.ndarray]:
        """Return latest pseudo-color depth image as RGB numpy array (thread-safe)."""
        lock = QMutexLocker(self._mutex)
        if self._depth_image is not None:
            return self._depth_image.copy()
        return None

    def get_depth_raw(self) -> Optional[np.ndarray]:
        """Return latest raw depth (uint16 mm) numpy array (thread-safe)."""
        lock = QMutexLocker(self._mutex)
        if self._depth_raw is not None:
            return self._depth_raw.copy()
        return None

    def get_camera_info(self) -> dict:
        """Return camera intrinsics (thread-safe)."""
        lock = QMutexLocker(self._mutex)
        return {
            'fx': self._fx, 'fy': self._fy,
            'cx': self._cx, 'cy': self._cy,
            'width': self._cam_width, 'height': self._cam_height,
        }

    def get_monitor_status(self) -> dict:
        """Return monitor status (thread-safe)."""
        lock = QMutexLocker(self._mutex)
        return {
            'status': self._monitor_status,
            'head_height': self._head_height,
        }

    def get_alert_states(self) -> dict:
        """Return alert states (thread-safe)."""
        lock = QMutexLocker(self._mutex)
        return {
            'fall_active': self._fall_alert_active,
            'fire_active': self._fire_alert_active,
        }

    def get_voice_data(self) -> dict:
        """Return latest voice assistant data (thread-safe)."""
        lock = QMutexLocker(self._mutex)
        return {
            'wakeup': self._voice_wakeup,
            'question': self._voice_question,
            'answer': self._voice_answer,
            'command': self._voice_command,
            'active': self._voice_active,
        }

    def get_hardware_status(self) -> dict:
        """Return hardware connectivity status (thread-safe)."""
        lock = QMutexLocker(self._mutex)
        return {
            'lidar_connected': self._lidar_connected,
            'camera_connected': self._camera_connected,
            'camera_fps': self._camera_fps,
            'motor_ready': self._motor_ready,
        }

    # ═══════════════════════════════════════════════════════════
    # ROS2 Subscriber Callbacks (called from executor thread)
    # ═══════════════════════════════════════════════════════════

    def _spin_loop(self):
        """Spin ROS2 executor in dedicated thread."""
        try:
            while self._running and rclpy.ok():
                self._executor.spin_once(timeout_sec=0.05)
        except Exception as e:
            if self._node:
                self._node.get_logger().error(f'Spin error: {e}')

    def _scan_callback(self, msg: LaserScan):
        lock = QMutexLocker(self._mutex)
        self._scan_ranges = list(msg.ranges)
        self._scan_angle_min = msg.angle_min
        self._scan_angle_max = msg.angle_max
        self._scan_angle_increment = msg.angle_increment
        self._scan_range_min = msg.range_min
        self._scan_range_max = msg.range_max
        sec = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        self._scan_timestamp = sec
        self._scan_frame_id = msg.header.frame_id
        self._lidar_connected = len(msg.ranges) > 0
        lock.unlock()
        self.scan_updated.emit()

    def _odom_callback(self, msg: Odometry):
        lock = QMutexLocker(self._mutex)
        self._odom_x = msg.pose.pose.position.x
        self._odom_y = msg.pose.pose.position.y
        # Quaternion → yaw
        q = msg.pose.pose.orientation
        siny = 2.0 * (q.w * q.z + q.x * q.y)
        cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        self._odom_theta = np.arctan2(siny, cosy)
        self._odom_vx = msg.twist.twist.linear.x
        self._odom_va = msg.twist.twist.angular.z
        lock.unlock()
        self.odom_updated.emit()

    def _map_callback(self, msg: OccupancyGrid):
        lock = QMutexLocker(self._mutex)
        self._map_width = msg.info.width
        self._map_height = msg.info.height
        self._map_resolution = msg.info.resolution
        self._map_origin_x = msg.info.origin.position.x
        self._map_origin_y = msg.info.origin.position.y
        try:
            self._map_data = np.array(msg.data, dtype=np.int8).reshape(
                (self._map_height, self._map_width))
        except Exception:
            self._map_data = None
        lock.unlock()
        self.map_updated.emit()

    def _rgb_callback(self, msg: Image):
        """Convert ROS Image (raw sensor_msgs/Image) to numpy BGR array."""
        try:
            if msg.encoding == 'rgb8':
                arr = np.frombuffer(msg.data, dtype=np.uint8).reshape(
                    (msg.height, msg.width, 3))
                bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
            elif msg.encoding == 'bgr8':
                bgr = np.frombuffer(msg.data, dtype=np.uint8).reshape(
                    (msg.height, msg.width, 3))
            elif msg.encoding == 'bgra8':
                arr = np.frombuffer(msg.data, dtype=np.uint8).reshape(
                    (msg.height, msg.width, 4))
                bgr = cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
            elif msg.encoding == 'nv12':
                # NV12 → BGR (RDK X5 mipi_cam format)
                yuv = np.frombuffer(msg.data, dtype=np.uint8).reshape(
                    (msg.height * 3 // 2, msg.width))
                bgr = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_NV12)
            else:
                # Attempt generic conversion via raw bytes
                arr = np.frombuffer(msg.data, dtype=np.uint8)
                if len(arr) == msg.height * msg.width * 3:
                    bgr = arr.reshape((msg.height, msg.width, 3))
                else:
                    return
        except Exception:
            return

        lock = QMutexLocker(self._mutex)
        self._rgb_image = bgr
        sec = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        self._rgb_timestamp = sec
        self._camera_connected = True

        # FPS tracking
        self._rgb_frame_count += 1
        now = sec
        if self._fps_last_check == 0.0:
            self._fps_last_check = now
        elif now - self._fps_last_check >= 2.0:
            self._camera_fps = self._rgb_frame_count / (now - self._fps_last_check)
            self._rgb_frame_count = 0
            self._fps_last_check = now
        lock.unlock()
        self.rgb_image_updated.emit()

    def _depth_callback(self, msg: CompressedImage):
        """Decode PNG-compressed depth (352x640 uint16) to pseudo-color RGB.

        This is the critical path — stereonet_compresseddepth sends PNG-encoded
        uint16 depth images that must be decoded with cv2.imdecode.
        """
        try:
            arr = np.frombuffer(msg.data, dtype=np.uint8)
            raw_depth = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
            if raw_depth is None:
                return
            # raw_depth is uint16 in mm, shape (H, W) e.g., (352, 640)

            # Normalize to 0-255 for color mapping
            valid = (raw_depth > 300) & (raw_depth < 8000)
            depth_vis = raw_depth.astype(np.float32)
            depth_vis[~valid] = 0
            depth_vis[valid] = np.clip(
                (depth_vis[valid] - 300) / (8000 - 300) * 255, 0, 255)
            depth_vis = depth_vis.astype(np.uint8)

            # Apply JET colormap
            pseudo_color = cv2.applyColorMap(depth_vis, cv2.COLORMAP_JET)
            # Mark invalid regions as dark
            pseudo_color[~valid] = [16, 16, 32]

        except Exception:
            return

        lock = QMutexLocker(self._mutex)
        self._depth_image = pseudo_color
        self._depth_raw = raw_depth
        sec = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        self._depth_timestamp = sec

        # Depth FPS tracking
        self._depth_frame_count += 1
        lock.unlock()
        self.depth_image_updated.emit()

    def _camera_info_callback(self, msg: CameraInfo):
        lock = QMutexLocker(self._mutex)
        self._fx = msg.k[0]
        self._fy = msg.k[4]
        self._cx = msg.k[2]
        self._cy = msg.k[5]
        self._cam_width = msg.width
        self._cam_height = msg.height
        lock.unlock()
        self.camera_info_updated.emit()

    def _monitor_status_callback(self, msg: String):
        lock = QMutexLocker(self._mutex)
        self._monitor_status = msg.data
        lock.unlock()
        self.monitor_status_updated.emit()

    def _head_height_callback(self, msg: Float32):
        lock = QMutexLocker(self._mutex)
        self._head_height = msg.data
        lock.unlock()
        self.head_height_updated.emit()

    def _fall_alert_callback(self, msg: Bool):
        lock = QMutexLocker(self._mutex)
        changed = (self._fall_alert_active != msg.data)
        self._fall_alert_active = msg.data
        lock.unlock()
        if changed:
            self.fall_alert_triggered.emit(msg.data)

    def _voice_wakeup_callback(self, msg: String):
        lock = QMutexLocker(self._mutex)
        self._voice_wakeup = msg.data
        self._voice_active = True
        lock.unlock()
        self.voice_wakeup_updated.emit(msg.data)

    def _voice_question_callback(self, msg: String):
        lock = QMutexLocker(self._mutex)
        self._voice_question = msg.data
        self._voice_active = True
        lock.unlock()
        self.voice_question_updated.emit(msg.data)

    def _voice_command_callback(self, msg: String):
        lock = QMutexLocker(self._mutex)
        self._voice_command = msg.data
        self._voice_active = True
        lock.unlock()
        self.voice_command_updated.emit(msg.data)

    def _voice_answer_callback(self, msg: String):
        lock = QMutexLocker(self._mutex)
        self._voice_answer = msg.data
        self._voice_active = True
        lock.unlock()
        self.voice_answer_updated.emit(msg.data)

    def _fire_alert_callback(self, msg: Bool):
        lock = QMutexLocker(self._mutex)
        changed = (self._fire_alert_active != msg.data)
        self._fire_alert_active = msg.data
        lock.unlock()
        if changed:
            self.fire_alert_triggered.emit(msg.data)


# ── Module-level singleton ──
_bridge_instance: Optional[ROS2Bridge] = None


def get_bridge() -> ROS2Bridge:
    """Return the singleton ROS2Bridge instance, creating it if necessary."""
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = ROS2Bridge()
    return _bridge_instance
