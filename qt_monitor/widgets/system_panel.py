#!/usr/bin/env python3
"""
系统状态面板 - 硬件连接、参数显示、方向键、测试按钮。
所有控件设为不可交互 (setEnabled(False))。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QGroupBox, QGridLayout
)


class SystemPanel(QWidget):
    """右侧系统状态面板。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('systemPanel')
        self._hw_labels: dict[str, QLabel] = {}
        self._param_labels: dict[str, QLabel] = {}
        self._param_sliders: dict[str, QSlider] = {}
        self._status_labels: dict[str, QLabel] = {}
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        header = QLabel('系统状态与参数')
        header.setStyleSheet(
            'padding: 6px 12px; border-bottom: 1px solid #E2E6EA; '
            'font-size: 15px; font-weight: 600; color: #16213E; '
            'background: #F8F9FA;')
        header.setFixedHeight(30)
        main_layout.addWidget(header)

        content = QWidget()
        content.setStyleSheet('background: #FFFFFF;')
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(10, 8, 10, 8)
        content_layout.setSpacing(6)

        # ── 硬件状态 ──
        hw_group = QGroupBox('硬件状态')
        hw_layout = QGridLayout(hw_group)
        hw_layout.setVerticalSpacing(6)
        hw_layout.setHorizontalSpacing(12)

        hw_items = [
            ('激光雷达 (RPLidar A2M6)', 0, 'lidar'),
            ('双目摄像头 (SC230AI)',     1, 'camera'),
            ('电机驱动 (JGB520)',        2, 'motor'),
        ]
        for label, row, key in hw_items:
            name_lbl = QLabel(label)
            name_lbl.setStyleSheet(
                'font-size: 15px; color: #4A5568; background: transparent;')
            status_lbl = QLabel('--')
            status_lbl.setStyleSheet(
                'font-size: 15px; font-weight: 600; color: #718096; '
                'background: transparent;')
            hw_layout.addWidget(name_lbl, row, 0)
            hw_layout.addWidget(status_lbl, row, 1)
            self._hw_labels[key] = status_lbl
        content_layout.addWidget(hw_group)

        # ── 相机内参 ──
        cam_group = QGroupBox('相机内参')
        cam_layout = QGridLayout(cam_group)
        cam_layout.setVerticalSpacing(4)
        cam_layout.setHorizontalSpacing(10)

        for col, (label, key) in enumerate([
            ('fx', 'fx'), ('fy', 'fy'), ('cx', 'cx'), ('cy', 'cy')]):
            lbl = QLabel(f'{label}:')
            lbl.setStyleSheet(
                'font-size: 14px; color: #718096; background: transparent;')
            val = QLabel('--')
            val.setStyleSheet(
                'font-size: 15px; font-weight: 600; color: #FF7F00; '
                'background: transparent;')
            cam_layout.addWidget(lbl, 0, col * 2)
            cam_layout.addWidget(val, 0, col * 2 + 1)
            self._status_labels[key] = val
        content_layout.addWidget(cam_group)

        # ── 视觉参数 ──
        param_group = QGroupBox('视觉参数')
        param_layout = QVBoxLayout(param_group)
        param_layout.setSpacing(6)

        # 背景差分阈值
        bg_widget = QWidget()
        bg_widget.setStyleSheet('background: transparent;')
        bg_layout = QVBoxLayout(bg_widget)
        bg_layout.setContentsMargins(0, 0, 0, 0)
        bg_layout.setSpacing(2)
        bg_header = QHBoxLayout()
        bg_name = QLabel('背景差分阈值')
        bg_name.setStyleSheet(
            'font-size: 15px; color: #4A5568; background: transparent;')
        bg_val = QLabel('200 mm')
        bg_val.setStyleSheet(
            'font-size: 15px; font-weight: 600; color: #FF7F00; '
            'background: transparent;')
        bg_header.addWidget(bg_name)
        bg_header.addStretch()
        bg_header.addWidget(bg_val)
        self._param_labels['bg_diff'] = bg_val
        bg_layout.addLayout(bg_header)

        slider_bg = QSlider(Qt.Horizontal)
        slider_bg.setRange(50, 500)
        slider_bg.setValue(200)
        slider_bg.setEnabled(False)
        self._param_sliders['bg_diff'] = slider_bg
        bg_layout.addWidget(slider_bg)
        param_layout.addWidget(bg_widget)

        # 头部高度阈值
        hh_widget = QWidget()
        hh_widget.setStyleSheet('background: transparent;')
        hh_layout = QVBoxLayout(hh_widget)
        hh_layout.setContentsMargins(0, 0, 0, 0)
        hh_layout.setSpacing(2)
        hh_header = QHBoxLayout()
        hh_name = QLabel('头部高度阈值')
        hh_name.setStyleSheet(
            'font-size: 15px; color: #4A5568; background: transparent;')
        hh_val = QLabel('0.45 m')
        hh_val.setStyleSheet(
            'font-size: 15px; font-weight: 600; color: #FF7F00; '
            'background: transparent;')
        hh_header.addWidget(hh_name)
        hh_header.addStretch()
        hh_header.addWidget(hh_val)
        self._param_labels['head_h'] = hh_val
        hh_layout.addLayout(hh_header)

        slider_hh = QSlider(Qt.Horizontal)
        slider_hh.setRange(20, 150)
        slider_hh.setValue(45)
        slider_hh.setEnabled(False)
        self._param_sliders['head_h'] = slider_hh
        hh_layout.addWidget(slider_hh)
        param_layout.addWidget(hh_widget)
        content_layout.addWidget(param_group)

        # ── 底盘方向键 (禁用) ──
        dpad_group = QGroupBox('底盘控制  |  /cmd_vel')
        dpad_layout = QVBoxLayout(dpad_group)
        dpad_layout.setAlignment(Qt.AlignCenter)

        dpad_widget = QWidget()
        dpad_widget.setObjectName('dpadWidget')
        dpad_grid = QGridLayout(dpad_widget)
        dpad_grid.setSpacing(4)

        btn_style = (
            'QPushButton { background-color: #F1F5F9; border: 1px solid #D0D5DD; '
            'border-radius: 6px; min-width: 52px; max-width: 52px; '
            'min-height: 52px; max-height: 52px; font-size: 20px; '
            'color: #94A3B8; } '
            'QPushButton:disabled { background-color: #F8FAFC; '
            'color: #CBD5E1; border: 1px solid #E2E6EA; }')
        btn_stop_style = (
            'QPushButton { background-color: #FFF7ED; '
            'border: 2px solid #FF7F00; border-radius: 6px; '
            'min-width: 52px; max-width: 52px; '
            'min-height: 52px; max-height: 52px; '
            'font-size: 14px; font-weight: bold; color: #FF7F00; } '
            'QPushButton:disabled { background-color: #F8FAFC; '
            'color: #CBD5E1; border: 1px solid #E2E6EA; }')

        btn_fwd = QPushButton('/\\')
        btn_fwd.setStyleSheet(btn_style)
        btn_fwd.setEnabled(False)
        btn_left = QPushButton('<')
        btn_left.setStyleSheet(btn_style)
        btn_left.setEnabled(False)
        btn_stop = QPushButton('停止')
        btn_stop.setStyleSheet(btn_stop_style)
        btn_stop.setEnabled(False)
        btn_right = QPushButton('>')
        btn_right.setStyleSheet(btn_style)
        btn_right.setEnabled(False)
        btn_back = QPushButton('\\/')
        btn_back.setStyleSheet(btn_style)
        btn_back.setEnabled(False)

        dpad_grid.addWidget(btn_fwd, 0, 1)
        dpad_grid.addWidget(btn_left, 1, 0)
        dpad_grid.addWidget(btn_stop, 1, 1)
        dpad_grid.addWidget(btn_right, 1, 2)
        dpad_grid.addWidget(btn_back, 2, 1)
        dpad_layout.addWidget(dpad_widget, alignment=Qt.AlignCenter)

        speed_lbl = QLabel('线速度: 0.15 m/s  |  角速度: 0.40 rad/s')
        speed_lbl.setStyleSheet(
            'font-size: 14px; color: #718096; background: transparent; '
            'padding-top: 4px;')
        speed_lbl.setAlignment(Qt.AlignCenter)
        dpad_layout.addWidget(speed_lbl)
        content_layout.addWidget(dpad_group)

        # ── 测试按钮 (禁用) ──
        test_group = QGroupBox('报警测试')
        test_layout = QHBoxLayout(test_group)
        test_layout.setSpacing(10)

        btn_fall = QPushButton('模拟跌倒')
        btn_fall.setEnabled(False)
        btn_fall.setStyleSheet(
            'QPushButton { background-color: #FFF7ED; color: #FF7F00; '
            'border: 1px solid #FFB080; border-radius: 6px; '
            'padding: 8px 16px; font-size: 15px; } '
            'QPushButton:disabled { background-color: #F8FAFC; '
            'color: #CBD5E1; border: 1px solid #E2E6EA; }')
        test_layout.addWidget(btn_fall)

        btn_fire = QPushButton('模拟火焰')
        btn_fire.setEnabled(False)
        btn_fire.setStyleSheet(
            'QPushButton { background-color: #FFF7ED; color: #FF7F00; '
            'border: 1px solid #FFB080; border-radius: 6px; '
            'padding: 8px 16px; font-size: 15px; } '
            'QPushButton:disabled { background-color: #F8FAFC; '
            'color: #CBD5E1; border: 1px solid #E2E6EA; }')
        test_layout.addWidget(btn_fire)
        content_layout.addWidget(test_group)

        content_layout.addStretch()
        main_layout.addWidget(content)

    # ── 公开更新方法 ──

    def update_hardware_status(self, hw_data: dict):
        lidar_ok = hw_data.get('lidar_connected', False)
        cam_ok = hw_data.get('camera_connected', False)
        motor_ok = hw_data.get('motor_ready', False)
        fps = hw_data.get('camera_fps', 0.0)

        self._hw_labels['lidar'].setText(
            '已连接' if lidar_ok else '未连接')
        self._hw_labels['lidar'].setStyleSheet(
            'font-size: 15px; font-weight: 600; '
            f'color: {"#16A34A" if lidar_ok else "#94A3B8"}; '
            'background: transparent;')

        self._hw_labels['camera'].setText(
            f'{fps:.1f} fps' if cam_ok else '未连接')
        self._hw_labels['camera'].setStyleSheet(
            'font-size: 15px; font-weight: 600; '
            f'color: {"#16A34A" if cam_ok else "#94A3B8"}; '
            'background: transparent;')

        self._hw_labels['motor'].setText(
            '就绪' if motor_ok else '--')
        self._hw_labels['motor'].setStyleSheet(
            'font-size: 15px; font-weight: 600; '
            f'color: {"#16A34A" if motor_ok else "#94A3B8"}; '
            'background: transparent;')

    def update_camera_info(self, cam_data: dict):
        for key in ['fx', 'fy', 'cx', 'cy']:
            val = cam_data.get(key, 0.0)
            self._status_labels[key].setText(f'{val:.1f}')

    def update_params(self, bg_diff: int = None, head_h: float = None):
        if bg_diff is not None:
            self._param_labels['bg_diff'].setText(f'{bg_diff} mm')
            self._param_sliders['bg_diff'].setValue(bg_diff)
        if head_h is not None:
            self._param_labels['head_h'].setText(f'{head_h:.2f} m')
            self._param_sliders['head_h'].setValue(int(head_h * 100))
