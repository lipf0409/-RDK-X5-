#!/usr/bin/env python3
"""合并报警面板 - 跌倒+火焰状态合并显示, 带硬件状态和语音状态条。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGroupBox
)


class AlarmPanel(QWidget):
    """跌倒和火焰报警合并为一个紧凑面板。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('alarmPanel')
        self._fall_lbl: QLabel = None
        self._fire_lbl: QLabel = None
        self._fall_dot: QLabel = None
        self._fire_dot: QLabel = None
        self._hw_labels: dict[str, QLabel] = {}
        self._voice_lbl: QLabel = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 标题 ──
        header = QLabel('报警与状态')
        header.setStyleSheet(
            'padding: 6px 12px; border-bottom: 1px solid #E2E6EA; '
            'font-size: 15px; font-weight: 600; color: #16213E; '
            'background: #F8F9FA;')
        header.setFixedHeight(30)
        layout.addWidget(header)

        content = QWidget()
        content.setStyleSheet('background: #FFFFFF;')
        cl = QVBoxLayout(content)
        cl.setContentsMargins(8, 4, 8, 4)
        cl.setSpacing(4)

        # ── 报警指示灯 (跌倒 + 火焰并排) ──
        alarm_group = QGroupBox('报警状态')
        alarm_layout = QHBoxLayout(alarm_group)
        alarm_layout.setContentsMargins(10, 8, 10, 8)
        alarm_layout.setSpacing(12)

        # 跌倒
        fall_widget = QWidget()
        fall_widget.setStyleSheet('background: transparent;')
        fl = QHBoxLayout(fall_widget)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(6)
        self._fall_dot = QLabel()
        self._fall_dot.setFixedSize(16, 16)
        self._fall_dot.setStyleSheet(self._dot_inactive('#DC2626'))
        self._fall_lbl = QLabel('跌倒: 正常')
        self._fall_lbl.setStyleSheet(
            'font-size: 15px; color: #4A5568; font-weight: 500; '
            'background: transparent;')
        fl.addWidget(self._fall_dot)
        fl.addWidget(self._fall_lbl)
        fl.addStretch()
        alarm_layout.addWidget(fall_widget)

        # 分隔
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet('border: none; border-left: 1px solid #E2E6EA;')
        alarm_layout.addWidget(sep)

        # 火焰
        fire_widget = QWidget()
        fire_widget.setStyleSheet('background: transparent;')
        ffl = QHBoxLayout(fire_widget)
        ffl.setContentsMargins(0, 0, 0, 0)
        ffl.setSpacing(6)
        self._fire_dot = QLabel()
        self._fire_dot.setFixedSize(16, 16)
        self._fire_dot.setStyleSheet(self._dot_inactive('#D97706'))
        self._fire_lbl = QLabel('火焰: 正常')
        self._fire_lbl.setStyleSheet(
            'font-size: 15px; color: #4A5568; font-weight: 500; '
            'background: transparent;')
        ffl.addWidget(self._fire_dot)
        ffl.addWidget(self._fire_lbl)
        ffl.addStretch()
        alarm_layout.addWidget(fire_widget)

        cl.addWidget(alarm_group)

        # ── 硬件状态 (单行紧凑) ──
        hw_group = QGroupBox('硬件状态')
        hw_layout = QHBoxLayout(hw_group)
        hw_layout.setSpacing(12)
        hw_layout.setContentsMargins(10, 8, 10, 8)

        for key, label in [
            ('lidar',  '雷达'),
            ('camera', '摄像头'),
            ('motor',  '电机'),
        ]:
            item = QHBoxLayout()
            item.setSpacing(3)
            name = QLabel(label)
            name.setStyleSheet(
                'font-size: 13px; color: #718096; background: transparent;')
            status = QLabel('--')
            status.setStyleSheet(
                'font-size: 13px; font-weight: 600; color: #94A3B8; '
                'background: transparent;')
            item.addWidget(name)
            item.addWidget(status)
            hw_layout.addLayout(item)
            self._hw_labels[key] = status
        hw_layout.addStretch()

        cl.addWidget(hw_group)

        # ── 语音状态条 ──
        voice_bar = QFrame()
        voice_bar.setStyleSheet(
            'background-color: #F0FDF4; border: 1px solid #BBF7D0; '
            'border-radius: 4px;')
        vl = QHBoxLayout(voice_bar)
        vl.setContentsMargins(8, 4, 8, 4)
        vl.setSpacing(6)

        voice_dot = QLabel()
        voice_dot.setFixedSize(12, 12)
        voice_dot.setStyleSheet(
            'background-color: #22C55E; border: 2px solid #16A34A; '
            'border-radius: 6px;')
        vl.addWidget(voice_dot)

        self._voice_lbl = QLabel('语音: 待命中 (唤醒词: 你好机器人)')
        self._voice_lbl.setStyleSheet(
            'font-size: 14px; color: #16A34A; font-weight: 500; '
            'background: transparent;')
        vl.addWidget(self._voice_lbl)
        vl.addStretch()

        cl.addWidget(voice_bar)
        cl.addStretch()
        layout.addWidget(content)

    def _dot_inactive(self, color: str) -> str:
        return (
            f'background-color: #CCCCCC; border: 2px solid #BBBBBB; '
            f'border-radius: 8px; min-width: 16px; max-width: 16px; '
            f'min-height: 16px; max-height: 16px;')

    def _dot_active(self, color: str) -> str:
        return (
            f'background-color: {color}; border: 2px solid {color}; '
            f'border-radius: 8px; min-width: 16px; max-width: 16px; '
            f'min-height: 16px; max-height: 16px;')

    # ── 公开方法 ──

    def set_fall_alert(self, active: bool):
        if active:
            self._fall_dot.setStyleSheet(self._dot_active('#DC2626'))
            self._fall_lbl.setText('跌倒: 报警!')
            self._fall_lbl.setStyleSheet(
                'font-size: 15px; color: #DC2626; font-weight: 700; '
                'background: transparent;')
        else:
            self._fall_dot.setStyleSheet(self._dot_inactive('#DC2626'))
            self._fall_lbl.setText('跌倒: 正常')
            self._fall_lbl.setStyleSheet(
                'font-size: 15px; color: #4A5568; font-weight: 500; '
                'background: transparent;')

    def set_fire_alert(self, active: bool):
        if active:
            self._fire_dot.setStyleSheet(self._dot_active('#D97706'))
            self._fire_lbl.setText('火焰: 报警!')
            self._fire_lbl.setStyleSheet(
                'font-size: 15px; color: #D97706; font-weight: 700; '
                'background: transparent;')
        else:
            self._fire_dot.setStyleSheet(self._dot_inactive('#D97706'))
            self._fire_lbl.setText('火焰: 正常')
            self._fire_lbl.setStyleSheet(
                'font-size: 15px; color: #4A5568; font-weight: 500; '
                'background: transparent;')

    def update_hardware(self, hw_data: dict):
        lidar_ok = hw_data.get('lidar_connected', False)
        cam_ok = hw_data.get('camera_connected', False)
        motor_ok = hw_data.get('motor_ready', False)
        fps = hw_data.get('camera_fps', 0.0)

        def _st(ok, text):
            return ('OK' if ok else '--', '#16A34A' if ok else '#94A3B8')

        t, c = _st(lidar_ok, '')
        self._hw_labels['lidar'].setText('已连接' if lidar_ok else '未连接')
        self._hw_labels['lidar'].setStyleSheet(
            f'font-size:14px;font-weight:600;color:{c};background:transparent;')

        t, c = _st(cam_ok, '')
        self._hw_labels['camera'].setText(
            f'{fps:.1f} fps' if cam_ok else '未连接')
        self._hw_labels['camera'].setStyleSheet(
            f'font-size:14px;font-weight:600;color:{c};background:transparent;')

        t, c = _st(motor_ok, '')
        self._hw_labels['motor'].setText('就绪' if motor_ok else '--')
        self._hw_labels['motor'].setStyleSheet(
            f'font-size:14px;font-weight:600;color:{c};background:transparent;')
