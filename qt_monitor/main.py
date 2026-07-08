#!/usr/bin/env python3
"""
智能报警监护机器人 - Qt 监控界面 (生产环境)。
单页全功能静态展示, 适配 7 寸屏 (1024x600)。
需要 ROS2 + rclpy。
"""
import sys, os, signal
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QSplitter
)

import rclpy
from ros_bridge import get_bridge
from splash import show_splash_and_run
from widgets.left_nav import LeftNavBar
from widgets.status_bar import StatusBar
from widgets.rgb_view import RGBView
from widgets.depth_view import DepthView
from widgets.slam_view import SlamView
from widgets.log_panel import LogPanel
from widgets.voice_chat import VoiceChatWidget


class MainWindow(QMainWindow):

    WINDOW_TITLE = '智能报警监护  |  JGB520 + RPLidar A2M6 + SC230AI'

    def __init__(self):
        super().__init__()
        self._bridge = None
        self.setWindowTitle(self.WINDOW_TITLE)
        self.resize(1024, 600)
        self.setMinimumSize(800, 480)

        cw = QWidget()
        cw.setStyleSheet('background-color: #EEF0F2;')
        self.setCentralWidget(cw)
        root = QHBoxLayout(cw)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 左侧导航 (静态) ──
        self._left_nav = LeftNavBar()
        self._left_nav.set_active_module('nav')
        for btn in self._left_nav._buttons.values():
            btn.setEnabled(False)
        root.addWidget(self._left_nav)

        # ── 右侧内容 ──
        right = QWidget()
        right.setStyleSheet('background-color: #EEF0F2;')
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        self._status_bar = StatusBar()
        rl.addWidget(self._status_bar)

        # 主区域
        main_split = QSplitter(Qt.Vertical)
        main_split.setStyleSheet(
            'QSplitter::handle { background-color: #D0D5DD; height: 3px; }')

        top = QSplitter(Qt.Horizontal)
        top.setStyleSheet(
            'QSplitter::handle { background-color: #D0D5DD; width: 3px; }')
        self._rgb_view = RGBView()
        self._depth_view = DepthView()
        top.addWidget(self._rgb_view)
        top.addWidget(self._depth_view)
        top.setSizes([480, 480])
        main_split.addWidget(top)

        bottom = QSplitter(Qt.Horizontal)
        bottom.setStyleSheet(
            'QSplitter::handle { background-color: #D0D5DD; width: 3px; }')
        self._slam_view = SlamView()
        self._voice_chat = VoiceChatWidget(bridge=None)
        bottom.addWidget(self._slam_view)
        bottom.addWidget(self._voice_chat)
        bottom.setSizes([500, 460])
        main_split.addWidget(bottom)
        main_split.setSizes([310, 210])
        rl.addWidget(main_split)

        self._log_panel = LogPanel()
        self._log_panel.setMaximumHeight(68)
        rl.addWidget(self._log_panel)
        root.addWidget(right)

        # ROS2
        QTimer.singleShot(100, self._init_ros2)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(33)

        self._fall_clear = QTimer(self); self._fall_clear.setSingleShot(True)
        self._fall_clear.timeout.connect(lambda: self._on_fall(False))
        self._fire_clear = QTimer(self); self._fire_clear.setSingleShot(True)
        self._fire_clear.timeout.connect(lambda: self._on_fire(False))

    def _init_ros2(self):
        self._log_panel.log_system_startup()
        try:
            self._bridge = get_bridge()
        except Exception as e:
            self._log_panel.append_log(f'ROS2 初始化失败: {e}', 'fire')
            return
        self._bridge.fall_alert_triggered.connect(self._on_fall)
        self._bridge.fire_alert_triggered.connect(self._on_fire)
        self._voice_chat.set_bridge(self._bridge)
        self._bridge.start()
        self._log_panel.log_ros2_ready(10, 1)
        self._status_bar.set_normal_active(True)

    def _refresh(self):
        if self._bridge is None or not self._bridge._running:
            return
        b = self._bridge
        self._slam_view.update_scan(b.get_scan_data())
        self._slam_view.update_odom(b.get_odom_data())
        md = b.get_map_data()
        if md.get('data') is not None:
            self._slam_view.update_map(md)

        rgb = b.get_rgb_image()
        mon = b.get_monitor_status()
        hh = mon.get('head_height', 0.0)
        st = mon.get('status', 'IDLE')
        if rgb is not None:
            self._rgb_view.update_frame(rgb, hh, st)
        dp = b.get_depth_image()
        if dp is not None:
            self._depth_view.update_frame(dp, hh, st)

        mon2 = b.get_monitor_status()
        if mon2.get('status') in ('DETECTED', 'TRACKING') and mon2.get('head_height', 0) > 0:
            self._log_panel.log_detection(mon2['head_height'])

    def _on_fall(self, active):
        self._status_bar.set_fall_alert(active)
        if active:
            self._log_panel.log_fall_alert()
            self._fall_clear.start(5000)
        else:
            self._log_panel.log_fall_cleared()

    def _on_fire(self, active):
        self._status_bar.set_fire_alert(active)
        if active:
            self._log_panel.log_fire_alert()
            self._fire_clear.start(5000)
        else:
            self._log_panel.log_fire_cleared()

    def closeEvent(self, event):
        if self._bridge:
            self._bridge.stop()
        super().closeEvent(event)


def main():
    if not rclpy.ok():
        rclpy.init(args=sys.argv)
    app = QApplication(sys.argv)
    app.setFont(QFont('Microsoft YaHei', 14))
    qss = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       'styles', 'theme.qss')
    if os.path.exists(qss):
        with open(qss, 'r', encoding='utf-8') as f:
            app.setStyleSheet(f.read())
    w = MainWindow()
    show_splash_and_run(app, w, duration_ms=2000)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    ec = app.exec()
    if rclpy.ok():
        rclpy.shutdown()
    sys.exit(ec)


if __name__ == '__main__':
    main()
