#!/usr/bin/env python3
"""
Mock ROS2 Bridge — Simulates all data sources for testing the Qt GUI on Windows.

No rclpy dependency. Generates:
  - Synthetic LIDAR scan (circular room)
  - Moving RGB image (animated gradient + detection boxes)
  - Synthetic depth map (radial + person silhouette)
  - Odometry (circular path)
  - Periodic person detection with head height
  - Manual alarm triggers
"""
import math
import time
import random
import numpy as np
import cv2

from PySide6.QtCore import QObject, Signal, QTimer, QMutex, QMutexLocker


class MockBridge(QObject):
    """Drop-in replacement for ROS2Bridge that generates synthetic data."""

    # Same signals as ROS2Bridge
    scan_updated = Signal()
    odom_updated = Signal()
    map_updated = Signal()
    rgb_image_updated = Signal()
    depth_image_updated = Signal()
    camera_info_updated = Signal()
    monitor_status_updated = Signal()
    head_height_updated = Signal()
    fall_alert_triggered = Signal(bool)
    fire_alert_triggered = Signal(bool)
    hardware_status_updated = Signal()

    RGB_W = 640
    RGB_H = 480
    DEPTH_W = 640
    DEPTH_H = 352

    def __init__(self):
        super().__init__()
        self._mutex = QMutex()
        self._running = False
        self._t = 0.0  # simulation time

        # ── Data buffers ──
        self._scan_ranges = []
        self._scan_angle_min = -math.pi
        self._scan_angle_max = math.pi
        self._scan_angle_increment = math.pi / 180  # 1 degree
        self._scan_range_min = 0.15
        self._scan_range_max = 12.0

        self._odom_x = 0.0
        self._odom_y = 0.0
        self._odom_theta = 0.0
        self._odom_vx = 0.0
        self._odom_va = 0.0

        self._map_data = None
        self._map_width = 200
        self._map_height = 200
        self._map_resolution = 0.05
        self._map_origin_x = -5.0
        self._map_origin_y = -5.0

        self._rgb_image = None
        self._depth_image = None
        self._depth_raw = None

        self._fx = 469.2
        self._fy = 469.2
        self._cx = 580.6
        self._cy = 358.9
        self._cam_width = self.RGB_W
        self._cam_height = self.RGB_H

        self._monitor_status = 'IDLE'
        self._head_height = 0.0
        self._fall_alert_active = False
        self._fire_alert_active = False

        self._lidar_connected = True
        self._camera_connected = True
        self._camera_fps = 10.0
        self._motor_ready = True

        # Person simulation state
        self._person_visible = False
        self._person_entered_time = 0.0
        self._person_head_height = 1.45
        self._simulate_fall = False
        self._fall_start_time = 0.0

        # Pre-generate SLAM map
        self._gen_map()

    def start(self):
        self._running = True
        # Main simulation timer at 10 Hz
        self._sim_timer = QTimer()
        self._sim_timer.timeout.connect(self._simulate)
        self._sim_timer.start(100)

        # Person scenario timer
        self._scenario_timer = QTimer()
        self._scenario_timer.timeout.connect(self._run_scenario)
        self._scenario_timer.start(8000)  # Every 8 seconds

    def stop(self):
        self._running = False
        if hasattr(self, '_sim_timer'):
            self._sim_timer.stop()
        if hasattr(self, '_scenario_timer'):
            self._scenario_timer.stop()

    def publish_cmd_vel(self, linear_x, angular_z):
        pass  # Mock: no real robot

    # ═══════════════════════════════════════════
    # Thread-safe getters (same API as ROS2Bridge)
    # ═══════════════════════════════════════════

    def get_scan_data(self):
        lock = QMutexLocker(self._mutex)
        return {
            'ranges': list(self._scan_ranges),
            'angle_min': self._scan_angle_min,
            'angle_max': self._scan_angle_max,
            'angle_increment': self._scan_angle_increment,
            'range_min': self._scan_range_min,
            'range_max': self._scan_range_max,
            'timestamp': self._t,
            'frame_id': 'laser',
        }

    def get_odom_data(self):
        lock = QMutexLocker(self._mutex)
        return {
            'x': self._odom_x, 'y': self._odom_y,
            'theta': self._odom_theta,
            'vx': self._odom_vx, 'va': self._odom_va,
        }

    def get_map_data(self):
        lock = QMutexLocker(self._mutex)
        return {
            'data': self._map_data.copy() if self._map_data is not None else None,
            'width': self._map_width, 'height': self._map_height,
            'resolution': self._map_resolution,
            'origin_x': self._map_origin_x, 'origin_y': self._map_origin_y,
        }

    def get_rgb_image(self):
        lock = QMutexLocker(self._mutex)
        if self._rgb_image is not None:
            return self._rgb_image.copy()
        return None

    def get_depth_image(self):
        lock = QMutexLocker(self._mutex)
        if self._depth_image is not None:
            return self._depth_image.copy()
        return None

    def get_depth_raw(self):
        lock = QMutexLocker(self._mutex)
        if self._depth_raw is not None:
            return self._depth_raw.copy()
        return None

    def get_camera_info(self):
        lock = QMutexLocker(self._mutex)
        return {
            'fx': self._fx, 'fy': self._fy,
            'cx': self._cx, 'cy': self._cy,
            'width': self._cam_width, 'height': self._cam_height,
        }

    def get_monitor_status(self):
        lock = QMutexLocker(self._mutex)
        return {'status': self._monitor_status, 'head_height': self._head_height}

    def get_alert_states(self):
        lock = QMutexLocker(self._mutex)
        return {'fall_active': self._fall_alert_active,
                'fire_active': self._fire_alert_active}

    def get_hardware_status(self):
        lock = QMutexLocker(self._mutex)
        return {
            'lidar_connected': self._lidar_connected,
            'camera_connected': self._camera_connected,
            'camera_fps': self._camera_fps,
            'motor_ready': self._motor_ready,
        }

    # ═══════════════════════════════════════════
    # Simulation
    # ═══════════════════════════════════════════

    def _simulate(self):
        """Main simulation tick — generate all sensor data."""
        self._t += 0.1

        # ── Odometry (circular path) ──
        radius = 1.5
        self._odom_x = radius * math.cos(self._t * 0.3)
        self._odom_y = radius * math.sin(self._t * 0.3)
        self._odom_theta = self._t * 0.3 + math.pi / 2
        self._odom_vx = 0.15
        self._odom_va = 0.3

        # ── LIDAR scan (circular room with obstacles) ──
        self._gen_scan()

        # ── RGB image ──
        self._gen_rgb()

        # ── Depth image ──
        self._gen_depth()

        # ── Emit signals ──
        self.scan_updated.emit()
        self.odom_updated.emit()
        self.rgb_image_updated.emit()
        self.depth_image_updated.emit()
        self.hardware_status_updated.emit()

    def _run_scenario(self):
        """Scenario cycle: IDLE → person enters → detection → fall → clear → repeat."""
        import random
        phase = random.choice(['enter', 'enter', 'fall', 'enter_nofall'])

        if phase == 'enter':
            self._person_visible = True
            self._person_head_height = 1.35 + random.random() * 0.3
            self._monitor_status = random.choice(['DETECTED', 'TRACKING'])
            self._simulate_fall = False
            self.monitor_status_updated.emit()
            self.head_height_updated.emit()

            # Clear after 3s
            QTimer.singleShot(3000, self._clear_person)

        elif phase == 'fall':
            self._person_visible = True
            self._monitor_status = 'FALL'
            self._person_head_height = 0.30 + random.random() * 0.2
            self._simulate_fall = True
            self.monitor_status_updated.emit()
            self.head_height_updated.emit()

            # Trigger fall alert
            QTimer.singleShot(800, lambda: self.fall_alert_triggered.emit(True))

            # Clear after 5s
            QTimer.singleShot(5000, self._clear_person)
            QTimer.singleShot(5000, lambda: self.fall_alert_triggered.emit(False))

        elif phase == 'enter_nofall':
            self._person_visible = True
            self._person_head_height = 1.40 + random.random() * 0.2
            self._monitor_status = 'TRACKING'
            self._simulate_fall = False
            self.monitor_status_updated.emit()
            self.head_height_updated.emit()
            QTimer.singleShot(4000, self._clear_person)

    def _clear_person(self):
        self._person_visible = False
        self._monitor_status = 'IDLE'
        self._head_height = 0.0
        self._simulate_fall = False
        self.monitor_status_updated.emit()
        self.head_height_updated.emit()

    def trigger_fall_test(self):
        """Manual fall alert trigger."""
        self.fall_alert_triggered.emit(True)
        QTimer.singleShot(5000, lambda: self.fall_alert_triggered.emit(False))

    def trigger_fire_test(self):
        """Manual fire alert trigger."""
        self.fire_alert_triggered.emit(True)
        QTimer.singleShot(5000, lambda: self.fire_alert_triggered.emit(False))

    # ═══════════════════════════════════════════
    # Data Generators
    # ═══════════════════════════════════════════

    def _gen_scan(self):
        """Generate synthetic LIDAR scan — circular room 4m radius with noise."""
        angles = np.arange(-math.pi, math.pi, self._scan_angle_increment)
        ranges = np.full_like(angles, 4.0, dtype=float)

        # Add some walls/obstacles
        for i, a in enumerate(angles):
            base = 4.0 + 0.15 * math.sin(a * 3) * math.cos(a * 5)
            # Add a box obstacle at angle ~0 (in front)
            if -0.5 < a < 0.5:
                base = min(base, 1.5)
            # Add a wall segment at angle ~2.5
            if 2.0 < a < 3.0:
                base = min(base, 2.0)
            # Noise
            base += random.gauss(0, 0.02)
            ranges[i] = max(0.15, min(11.9, base))

        self._scan_ranges = list(ranges)

    def _gen_map(self):
        """Generate a synthetic SLAM occupancy grid."""
        w, h = self._map_width, self._map_height
        m = np.full((h, w), -1, dtype=np.int8)

        # Circular room
        cx, cy = w // 2, h // 2
        r = w // 2 - 5
        for y in range(h):
            for x in range(w):
                dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
                if dist < r:
                    m[y, x] = 0  # free space
                elif dist < r + 5:
                    m[y, x] = 100  # wall
        # Add some interior obstacles
        for ox, oy in [(60, 70), (140, 110), (100, 50)]:
            for dy in range(-8, 9):
                for dx in range(-8, 9):
                    px, py = ox + dx, oy + dy
                    if 0 <= px < w and 0 <= py < h:
                        m[py, px] = 100
        self._map_data = m

    def _gen_rgb(self):
        """Generate synthetic RGB camera image with simulated room scene."""
        w, h = self.RGB_W, self.RGB_H
        # Background: room-like gradient
        img = np.zeros((h, w, 3), dtype=np.uint8)
        # Sky/ceiling gradient (top)
        for y in range(h // 2):
            shade = int(180 + 40 * y / (h // 2))
            img[y, :] = [shade - 20, shade, shade + 20]
        # Floor gradient (bottom)
        for y in range(h // 2, h):
            shade = int(140 - 60 * (y - h // 2) / (h // 2))
            img[y, :] = [shade, shade + 10, shade - 10]

        # Add room features
        # Door (rectangle at center)
        cv2.rectangle(img, (250, 80), (390, 420), (80, 70, 60), -1)
        cv2.rectangle(img, (250, 80), (390, 420), (50, 40, 30), 2)
        # Window (top-right)
        cv2.rectangle(img, (460, 60), (600, 200), (200, 220, 240), -1)
        cv2.rectangle(img, (460, 60), (600, 200), (100, 100, 100), 2)
        cv2.line(img, (530, 60), (530, 200), (100, 100, 100), 1)
        cv2.line(img, (460, 130), (600, 130), (100, 100, 100), 1)

        # Table (bottom center)
        cv2.rectangle(img, (180, 330), (500, 370), (90, 70, 50), -1)

        # Timestamp overlay
        ts = time.strftime('%H:%M:%S')
        cv2.putText(img, f'CAM01  {ts}', (10, h - 12),
                     cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 1)

        # If person visible, draw a person
        if self._person_visible:
            px, py = 280, 60
            pw, ph = 80, 360 if not self._simulate_fall else 120
            color = (0, 165, 255) if not self._simulate_fall else (0, 0, 255)
            cv2.rectangle(img, (px, py), (px + pw, py + ph), color, 2)
            label = f'头部: {self._person_head_height:.2f}m'
            cv2.rectangle(img, (px, py - 28), (px + 170, py), color, -1)
            cv2.putText(img, label, (px + 6, py - 8),
                         cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

        # Grid overlay (camera guide)
        cv2.line(img, (w // 3, 0), (w // 3, h), (255, 255, 255), 1)
        cv2.line(img, (2 * w // 3, 0), (2 * w // 3, h), (255, 255, 255), 1)
        cv2.line(img, (0, h // 3), (w, h // 3), (255, 255, 255), 1)
        cv2.line(img, (0, 2 * h // 3), (w, 2 * h // 3), (255, 255, 255), 1)

        self._rgb_image = img

    def _gen_depth(self):
        """Generate synthetic depth map."""
        w, h = self.DEPTH_W, self.DEPTH_H
        raw = np.zeros((h, w), dtype=np.uint16)

        # Radial gradient (closer at bottom = floor)
        for y in range(h):
            # Distance increases from bottom to top
            dist = int(500 + (h - y) * 12 + random.gauss(0, 30))
            raw[y, :] = np.clip(dist, 300, 8000)

        # Add person silhouette if visible
        if self._person_visible:
            px, py = int(w * 0.35), int(h * 0.08)
            pw, ph = int(w * 0.15), int(h * 0.85)
            person_depth = int(1200 + random.gauss(0, 50))
            if self._simulate_fall:
                ph = int(h * 0.35)
                py = h - ph - 10
            raw[py:py + ph, px:px + pw] = np.clip(person_depth, 300, 8000)

        # Pseudo-color conversion (matching ROS2Bridge logic)
        valid = (raw > 300) & (raw < 8000)
        depth_vis = raw.astype(np.float32)
        depth_vis[~valid] = 0
        depth_vis[valid] = np.clip(
            (depth_vis[valid] - 300) / (8000 - 300) * 255, 0, 255)
        depth_vis = depth_vis.astype(np.uint8)
        pseudo_color = cv2.applyColorMap(depth_vis, cv2.COLORMAP_JET)
        pseudo_color[~valid] = [16, 16, 32]

        self._depth_raw = raw
        self._depth_image = pseudo_color
