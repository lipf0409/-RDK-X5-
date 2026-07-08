#!/usr/bin/env python3
"""深度图视图 - stereonet_compresseddepth PNG 数据伪彩色显示。"""
import numpy as np
import cv2

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap, QPainter, QPen, QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame
)


class DepthView(QWidget):
    """伪彩色深度图显示组件，带人体检测叠加。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('depthView')
        self._image_label: QLabel = None
        self._current_pixmap: QPixmap = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel('深度图  |  compresseddepth (伪彩色)')
        header.setStyleSheet(
            'padding: 6px 12px; border-bottom: 1px solid #E2E6EA; '
            'font-size: 15px; font-weight: 600; color: #16213E; '
            'background: #F8F9FA;')
        header.setFixedHeight(30)
        layout.addWidget(header)

        content = QFrame()
        content.setStyleSheet(
            'background-color: #1A1A2E; border: 2px solid #2D3748;')
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(6, 6, 6, 6)

        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setMinimumSize(280, 200)
        self._image_label.setStyleSheet(
            'background-color: #1A1A2E; border: none;')
        content_layout.addWidget(self._image_label)
        layout.addWidget(content)

        # 色标条
        scale_bar = QLabel()
        scale_bar.setFixedHeight(14)
        scale_bar.setStyleSheet(
            'background: qlineargradient(x1:0, y1:0, x2:1, y2:0, '
            'stop:0 #000080, stop:0.25 #0088FF, stop:0.5 #00FF88, '
            'stop:0.75 #FFFF00, stop:1 #FF0000); '
            'border-radius: 2px; margin: 0px 8px;')
        layout.addWidget(scale_bar)

        # 范围标签
        range_widget = QWidget()
        range_layout = QVBoxLayout(range_widget)
        range_layout.setContentsMargins(8, 0, 8, 2)
        range_widget.setStyleSheet('background: #FFFFFF;')
        rl = QLabel('0.3 m                                          8.0 m')
        rl.setStyleSheet(
            'font-size: 12px; color: #718096; background: transparent;')
        range_layout.addWidget(rl)
        layout.addWidget(range_widget)

    def update_frame(self, pseudo_color: np.ndarray,
                     head_height: float = 0.0,
                     monitor_status: str = 'IDLE'):
        if pseudo_color is None:
            return

        h, w, ch = pseudo_color.shape
        bytes_per_line = ch * w
        qimg = QImage(pseudo_color.data, w, h, bytes_per_line,
                       QImage.Format_BGR888)
        pixmap = QPixmap.fromImage(qimg)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        if head_height > 0.0 and monitor_status in ('DETECTED', 'TRACKING'):
            bx = int(w * 0.3)
            by = int(h * 0.15)
            bw = int(w * 0.4)
            bh = int(h * 0.7)

            pen = QPen(QColor('#FF7F00'))
            pen.setWidth(2)
            pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.drawRect(bx, by, bw, bh)

            painter.fillRect(bx, by - 24, 160, 24, QColor('#FF7F00'))
            font = QFont('Microsoft YaHei', 14)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor('#FFFFFF'))
            painter.drawText(bx + 8, by - 6, f'深度头部: {head_height:.2f} m')

        elif monitor_status == 'FALL':
            pen = QPen(QColor('#DC2626'))
            pen.setWidth(3)
            painter.setPen(pen)
            painter.drawRect(4, 4, w - 8, h - 8)

        # 右上角信息
        font = QFont('Consolas', 12)
        painter.setFont(font)
        text = f'{w}x{h}  uint16'
        tw = 110
        painter.fillRect(w - tw - 10, 6, tw, 20, QColor(0, 0, 0, 160))
        painter.setPen(QColor('#94A3B8'))
        painter.drawText(w - tw, 20, text)

        painter.end()
        scaled = pixmap.scaled(
            self._image_label.size(), Qt.KeepAspectRatio,
            Qt.SmoothTransformation)
        self._image_label.setPixmap(scaled)
        self._current_pixmap = scaled

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_pixmap is not None:
            scaled = self._current_pixmap.scaled(
                self._image_label.size(), Qt.KeepAspectRatio,
                Qt.SmoothTransformation)
            self._image_label.setPixmap(scaled)
