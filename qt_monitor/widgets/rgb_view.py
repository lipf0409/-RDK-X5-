#!/usr/bin/env python3
"""RGB 摄像头画面 - 显示 rectified_image 并叠加人体检测框。"""
import numpy as np
import cv2

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap, QPainter, QPen, QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame
)


class RGBView(QWidget):
    """RGB 校正图像显示组件，带人体检测叠加层。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('rgbView')
        self._image_label: QLabel = None
        self._placeholder_label: QLabel = None
        self._current_pixmap: QPixmap = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel('RGB 摄像头  |  rectified_image')
        header.setStyleSheet(
            'padding: 6px 12px; border-bottom: 1px solid #E2E6EA; '
            'font-size: 15px; font-weight: 600; color: #16213E; '
            'background: #F8F9FA;')
        header.setFixedHeight(30)
        layout.addWidget(header)

        content = QFrame()
        content.setObjectName('rgbContent')
        content.setStyleSheet(
            'background-color: #1A1A2E; border: 2px solid #2D3748;')
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(6, 6, 6, 6)

        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setMinimumSize(280, 200)
        self._image_label.setStyleSheet(
            'background-color: #1A1A2E; border: none;')

        self._placeholder_label = QLabel('等待摄像头数据...')
        self._placeholder_label.setAlignment(Qt.AlignCenter)
        self._placeholder_label.setStyleSheet(
            'color: #718096; font-size: 17px; background: transparent;')

        content_layout.addWidget(self._image_label)
        layout.addWidget(content)

    def update_frame(self, bgr_image: np.ndarray,
                     head_height: float = 0.0,
                     monitor_status: str = 'IDLE'):
        if bgr_image is None:
            return

        h, w, ch = bgr_image.shape
        bytes_per_line = ch * w

        qimg = QImage(bgr_image.data, w, h, bytes_per_line,
                       QImage.Format_BGR888)

        pixmap = QPixmap.fromImage(qimg)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        # 人体检测叠加
        if head_height > 0.0 and monitor_status in ('DETECTED', 'TRACKING'):
            bx = int(w * 0.3)
            by = int(h * 0.15)
            bw = int(w * 0.4)
            bh = int(h * 0.7)

            pen = QPen(QColor('#FF7F00'))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawRect(bx, by, bw, bh)

            # 头部高度标签
            painter.fillRect(bx, by - 24, 150, 24, QColor('#FF7F00'))
            font = QFont('Microsoft YaHei', 14)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor('#FFFFFF'))
            painter.drawText(bx + 8, by - 6, f'头部: {head_height:.2f} m')

            # 状态文字
            font_s = QFont('Microsoft YaHei', 14)
            font_s.setBold(True)
            painter.setFont(font_s)
            painter.fillRect(8, 8, 110, 26, QColor(0, 0, 0, 160))
            painter.setPen(QColor('#FF7F00'))
            painter.drawText(16, 27, '检测到人')

        elif monitor_status == 'FALL':
            # 跌倒报警 - 红色边框
            pen = QPen(QColor('#DC2626'))
            pen.setWidth(3)
            painter.setPen(pen)
            painter.drawRect(4, 4, w - 8, h - 8)
            painter.fillRect(8, 8, 200, 32, QColor(220, 38, 38, 210))
            font = QFont('Microsoft YaHei', 16)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor('#FFFFFF'))
            painter.drawText(16, 30, '检测到跌倒!')

        elif monitor_status == 'IDLE':
            font = QFont('Microsoft YaHei', 13)
            painter.setFont(font)
            painter.fillRect(8, 8, 56, 24, QColor(0, 0, 0, 140))
            painter.setPen(QColor('#94A3B8'))
            painter.drawText(16, 25, '空闲')

        painter.end()

        scaled = pixmap.scaled(
            self._image_label.size(), Qt.KeepAspectRatio,
            Qt.SmoothTransformation)
        self._image_label.setPixmap(scaled)
        self._current_pixmap = scaled
        self._placeholder_label.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_pixmap is not None:
            scaled = self._current_pixmap.scaled(
                self._image_label.size(), Qt.KeepAspectRatio,
                Qt.SmoothTransformation)
            self._image_label.setPixmap(scaled)
