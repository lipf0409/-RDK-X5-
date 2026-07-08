#!/usr/bin/env python3
"""
SLAM / LIDAR 2D View — Foxglove-style rendering of /scan point cloud
and /map occupancy grid as a heatmap overlay.
"""
import numpy as np
import math

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import (
    QPainter, QPen, QColor, QBrush, QFont, QPainterPath, QImage, QPixmap
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame
)


class SlamView(QWidget):
    """2D rendering widget for LIDAR point cloud and SLAM occupancy grid.

    Draws scan points in green on dark background, robot pose as orange
    triangle, and SLAM map as a semi-transparent heatmap.
    """

    # Display parameters
    DISPLAY_RADIUS_M = 5.0     # Default view radius (meters)
    PIXELS_PER_METER = 60      # Scale factor
    ROBOT_SIZE_PX = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('slamView')
        self.setMinimumSize(300, 250)

        # Data buffers
        self._scan_points: list[tuple[float, float]] = []
        self._robot_x: float = 0.0
        self._robot_y: float = 0.0
        self._robot_theta: float = 0.0
        self._map_image: QImage = None
        self._map_origin: tuple[float, float] = (0.0, 0.0)
        self._map_resolution: float = 0.05
        self._map_width: int = 0
        self._map_height: int = 0
        self._has_scan: bool = False
        self._has_map: bool = False

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Section header
        header = QLabel('SLAM 建图  |  /scan + /map 热力图')
        header.setStyleSheet(
            'padding: 6px 12px; border-bottom: 1px solid #F0F0F0; '
            'font-size: 15px; font-weight: 600; color: #333; '
            'background: #FFFFFF;')
        header.setFixedHeight(30)
        layout.addWidget(header)

        # Canvas
        self._canvas = SlamCanvas(self)
        self._canvas.setStyleSheet(
            'background-color: #0D1117; border: 1px solid #30363D; '
            'border-radius: 0px;')
        layout.addWidget(self._canvas)

    # ── Public update methods ──

    def update_scan(self, scan_data: dict):
        """Convert LaserScan ranges to 2D Cartesian points."""
        ranges = scan_data.get('ranges', [])
        angle_min = scan_data.get('angle_min', 0.0)
        angle_inc = scan_data.get('angle_increment', 0.0)
        range_max = scan_data.get('range_max', 12.0)

        points = []
        for i, r in enumerate(ranges):
            if not (0.15 < r < range_max - 0.1):
                continue
            angle = angle_min + i * angle_inc
            px = r * math.cos(angle)
            py = r * math.sin(angle)
            points.append((px, py))

        self._scan_points = points
        self._has_scan = len(points) > 0
        self._canvas.update()

    def update_odom(self, odom_data: dict):
        """Update robot pose."""
        self._robot_x = odom_data.get('x', 0.0)
        self._robot_y = odom_data.get('y', 0.0)
        self._robot_theta = odom_data.get('theta', 0.0)
        self._canvas.update()

    def update_map(self, map_data: dict):
        """Build a QImage from OccupancyGrid data for heatmap overlay."""
        data = map_data.get('data')
        if data is None or data.size == 0:
            return

        w = map_data.get('width', 0)
        h = map_data.get('height', 0)
        res = map_data.get('resolution', 0.05)
        ox = map_data.get('origin_x', 0.0)
        oy = map_data.get('origin_y', 0.0)

        # Create RGBA heatmap image
        img = np.zeros((h, w, 4), dtype=np.uint8)

        # Known (0-100): white → gray heatmap
        known = (data >= 0) & (data <= 100)
        # Unknown (-1): transparent
        unknown = data == -1

        # Grayscale: free=255 (white), occupied=0 (black)
        gray = np.clip(255 - data.astype(np.int32) * 255 // 100, 0, 255)
        gray[unknown] = 0

        # Set RGBA: free space light, occupied dark, unknown transparent
        img[known, 0] = gray[known]       # R
        img[known, 1] = gray[known]       # G
        img[known, 2] = gray[known]       # B
        img[known, 3] = 180               # Alpha (semi-transparent)
        img[unknown, 3] = 0               # Transparent for unknown

        qimg = QImage(img.data, w, h, w * 4, QImage.Format_RGBA8888)
        self._map_image = qimg.copy()
        self._map_origin = (ox, oy)
        self._map_resolution = res
        self._map_width = w
        self._map_height = h
        self._has_map = True
        self._canvas.update()

    # ── Coordinate conversion ──

    def world_to_pixel(self, wx: float, wy: float) -> tuple[int, int]:
        """Convert world coordinates (meters) to canvas pixel coordinates."""
        cx = self._canvas.width() // 2
        cy = self._canvas.height() // 2
        px = int(cx + wx * self.PIXELS_PER_METER)
        py = int(cy - wy * self.PIXELS_PER_METER)
        return px, py


class SlamCanvas(QFrame):
    """Custom paint widget for the SLAM/LIDAR 2D view."""

    def __init__(self, owner: SlamView):
        super().__init__(owner)
        self._owner = owner
        self.setMinimumSize(280, 240)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()
        cx = w // 2
        cy = h // 2
        ppm = SlamView.PIXELS_PER_METER
        owner = self._owner

        # ── Background ──
        painter.fillRect(0, 0, w, h, QColor('#0D1117'))

        # ── Grid ──
        pen_grid = QPen(QColor('#1A2A3A'))
        pen_grid.setWidth(1)
        painter.setPen(pen_grid)
        for i in range(-10, 11):
            px = cx + int(i * ppm)
            painter.drawLine(px, 0, px, h)
            py = cy - int(i * ppm)
            painter.drawLine(0, py, w, py)

        # Bolder center axes
        pen_axis = QPen(QColor('#253545'))
        pen_axis.setWidth(1)
        painter.setPen(pen_axis)
        painter.drawLine(cx, 0, cx, h)
        painter.drawLine(0, cy, w, cy)

        # ── SLAM Map (heatmap overlay) ──
        if owner._has_map and owner._map_image is not None:
            map_img = owner._map_image
            ox, oy = owner._map_origin
            res = owner._map_resolution
            mw = owner._map_width
            mh = owner._map_height

            # Map pixel → world → canvas pixel
            map_world_w = mw * res
            map_world_h = mh * res
            map_px = int(cx + ox * ppm)
            map_py = int(cy - oy * ppm)
            map_cw = int(map_world_w * ppm)
            map_ch = int(map_world_h * ppm)

            scaled = map_img.scaled(map_cw, map_ch, Qt.IgnoreAspectRatio,
                                     Qt.SmoothTransformation)
            painter.drawImage(map_px, map_py - map_ch, scaled)

        # ── LIDAR Scan Points ──
        if owner._has_scan:
            pen_scan = QPen(QColor('#00FF88'))
            pen_scan.setWidth(1)
            painter.setPen(pen_scan)
            for sx, sy in owner._scan_points:
                px, py = owner.world_to_pixel(sx, sy)
                if 0 <= px < w and 0 <= py < h:
                    painter.drawPoint(px, py)

        # ── Range Circles ──
        for r_m in [1.0, 2.0, 3.0, 4.0, 5.0]:
            pen_circle = QPen(QColor('#1A2A3A'))
            pen_circle.setWidth(1)
            pen_circle.setStyle(Qt.DotLine)
            painter.setPen(pen_circle)
            r_px = int(r_m * ppm)
            painter.drawEllipse(QRectF(cx - r_px, cy - r_px,
                                        r_px * 2, r_px * 2))

        # ── Robot Pose (orange triangle) ──
        rx, ry = owner.world_to_pixel(owner._robot_x, owner._robot_y)
        theta = owner._robot_theta
        size = SlamView.ROBOT_SIZE_PX

        # Triangle points: forward (at theta), left-back, right-back
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)
        # Forward tip
        fpx = rx + int(size * 1.2 * cos_t)
        fpy = ry - int(size * 1.2 * sin_t)
        # Back-left
        blpx = rx + int(size * 0.8 * math.cos(theta + 2.5))
        blpy = ry - int(size * 0.8 * math.sin(theta + 2.5))
        # Back-right
        brpx = rx + int(size * 0.8 * math.cos(theta - 2.5))
        brpy = ry - int(size * 0.8 * math.sin(theta - 2.5))

        path = QPainterPath()
        path.moveTo(fpx, fpy)
        path.lineTo(blpx, blpy)
        path.lineTo(brpx, brpy)
        path.closeSubpath()

        painter.setPen(QPen(QColor('#FF7F00'), 2))
        painter.setBrush(QBrush(QColor(255, 127, 0, 180)))
        painter.drawPath(path)

        # ── Info Text ──
        font = QFont('Consolas', 13)
        painter.setFont(font)
        painter.setPen(QColor('#8B949E'))
        text_y = h - 16
        painter.drawText(10, text_y,
                          f'x:{owner._robot_x:.2f}  '
                          f'y:{owner._robot_y:.2f}  '
                          f'角度:{math.degrees(owner._robot_theta):.0f}')

        n_points = len(owner._scan_points)
        painter.drawText(10, text_y - 18,
                          f'扫描点: {n_points}  '
                          f'地图: {"有" if owner._has_map else "--"}  '
                          f'比例: {SlamView.PIXELS_PER_METER} px/m')
