#!/usr/bin/env python3
"""
事件日志面板 - 底部彩色日志区域。
颜色编码: 灰色=系统信息, 橙色=人体检测, 红色=报警事件。
"""
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor, QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTextEdit, QHBoxLayout
)


class LogPanel(QWidget):
    """底部可滚动、带颜色编码的事件日志。"""

    MAX_LINES = 500

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('logPanel')
        self.setMaximumHeight(90)
        self._line_count: int = 0
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(12, 2, 12, 2)

        title = QLabel('事件日志')
        title.setStyleSheet(
            'font-size: 15px; font-weight: 600; color: #4A5568; '
            'background: transparent;')
        header_layout.addWidget(title)
        header_layout.addStretch()

        clear_hint = QLabel('[自动滚动]')
        clear_hint.setStyleSheet(
            'font-size: 12px; color: #94A3B8; background: transparent;')
        header_layout.addWidget(clear_hint)

        header_widget = QWidget()
        header_widget.setStyleSheet(
            'background: #F8F9FA; border-bottom: 1px solid #E2E6EA;')
        header_widget.setLayout(header_layout)
        layout.addWidget(header_widget)

        self._text_edit = QTextEdit()
        self._text_edit.setReadOnly(True)
        self._text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self._text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._text_edit.setStyleSheet(
            'QTextEdit { background-color: #FAFBFC; color: #4A5568; '
            'border: none; font-family: "Consolas", "Microsoft YaHei", monospace; '
            'font-size: 14px; padding: 5px 8px; } ')
        layout.addWidget(self._text_edit)

    def append_log(self, message: str, level: str = 'info'):
        now = datetime.now().strftime('%H:%M:%S')
        colors = {
            'info':      '#4A5568',
            'detection': '#FF7F00',
            'fall':      '#DC2626',
            'fire':      '#D97706',
            'system':    '#718096',
        }
        bold_levels = {'fall', 'fire'}

        color = colors.get(level, '#4A5568')
        is_bold = level in bold_levels

        cursor = self._text_edit.textCursor()
        cursor.movePosition(QTextCursor.End)

        fmt = cursor.charFormat()
        fmt.setForeground(QColor('#94A3B8'))
        fmt.setFontWeight(QFont.Normal)
        fmt.setFontPointSize(13)
        cursor.insertText(f'[{now}] ', fmt)

        fmt2 = cursor.charFormat()
        fmt2.setForeground(QColor(color))
        fmt2.setFontPointSize(13)
        if is_bold:
            fmt2.setFontWeight(QFont.Bold)
        else:
            fmt2.setFontWeight(QFont.Normal)
        cursor.insertText(f'{message}\n', fmt2)

        self._text_edit.setTextCursor(cursor)
        self._line_count += 1
        if self._line_count > self.MAX_LINES:
            cursor.movePosition(QTextCursor.Start)
            cursor.select(QTextCursor.LineUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()
            self._line_count -= 1

    def log_scene_change(self, event: str):
        self.append_log(event, 'system')

    def log_detection(self, head_height: float):
        self.append_log(
            f'检测到人 -- 头部高度: {head_height:.2f} m', 'detection')

    def log_fall_alert(self):
        self.append_log(
            '跌倒报警 -- 头部高度低于阈值! 已触发报警.', 'fall')

    def log_fall_cleared(self):
        self.append_log('跌倒报警已解除 -- 恢复监护.', 'system')

    def log_fire_alert(self):
        self.append_log(
            '火焰报警 -- 检测到火焰! 已触发报警.', 'fire')

    def log_fire_cleared(self):
        self.append_log('火焰报警已解除 -- 恢复监护.', 'system')

    def log_system_startup(self):
        self.append_log(
            '智能报警监护系统启动 -- JGB520 + RPLidar A2M6 + SC230AI', 'system')
        self.append_log('ROS2 桥接初始化中...', 'system')

    def log_ros2_ready(self, num_subs: int, num_pubs: int):
        self.append_log(
            f'ROS2 桥接就绪 -- {num_subs} 个订阅, {num_pubs} 个发布', 'system')
