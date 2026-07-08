#!/usr/bin/env python3
"""
离线测试 - 单页全功能静态展示, 适配 7 寸屏 (1024x600)。
所有功能在同一页面展示, 无交互。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QSplitter, QLabel
)

from mock_bridge import MockBridge
from splash import show_splash_and_run
from widgets.left_nav import LeftNavBar
from widgets.status_bar import StatusBar
from widgets.rgb_view import RGBView
from widgets.depth_view import DepthView
from widgets.slam_view import SlamView
from widgets.log_panel import LogPanel
from widgets.voice_chat import VoiceChatWidget


class MockMainWindow(QMainWindow):

    WINDOW_TITLE = '智能报警监护  |  模拟模式'
    W = 1024
    H = 600

    def __init__(self):
        super().__init__()
        self._bridge = MockBridge()
        self.setWindowTitle(self.WINDOW_TITLE)
        self.resize(self.W, self.H)
        self.setMinimumSize(800, 480)

        # ── 根布局: 左导航 + 右内容 ──
        cw = QWidget()
        cw.setStyleSheet('background-color: #EEF0F2;')
        self.setCentralWidget(cw)
        root = QHBoxLayout(cw)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 左侧导航 (静态, 所有按钮禁用) ──
        self._left_nav = LeftNavBar()
        self._left_nav.set_active_module('nav')
        # 强制所有按钮禁用
        for btn in self._left_nav._buttons.values():
            btn.setEnabled(False)
        root.addWidget(self._left_nav)

        # ── 右侧 ──
        right = QWidget()
        right.setStyleSheet('background-color: #EEF0F2;')
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        # 状态栏
        self._status_bar = StatusBar()
        rl.addWidget(self._status_bar)

        # ── 主区域: 上半(视频) + 下半(SLAM+报警) ──
        main_split = QSplitter(Qt.Vertical)
        main_split.setStyleSheet(
            'QSplitter::handle { background-color: #D0D5DD; height: 3px; }')

        # 上半: RGB | 深度图
        top = QSplitter(Qt.Horizontal)
        top.setStyleSheet(
            'QSplitter::handle { background-color: #D0D5DD; width: 3px; }')
        self._rgb_view = RGBView()
        self._depth_view = DepthView()
        top.addWidget(self._rgb_view)
        top.addWidget(self._depth_view)
        top.setSizes([480, 480])
        main_split.addWidget(top)

        # 下半: SLAM | AI 对话
        bottom = QSplitter(Qt.Horizontal)
        bottom.setStyleSheet(
            'QSplitter::handle { background-color: #D0D5DD; width: 3px; }')
        self._slam_view = SlamView()
        self._voice_chat = VoiceChatWidget()
        bottom.addWidget(self._slam_view)
        bottom.addWidget(self._voice_chat)
        bottom.setSizes([500, 460])
        main_split.addWidget(bottom)

        main_split.setSizes([290, 230])
        rl.addWidget(main_split)

        # ── 日志 ──
        self._log_panel = LogPanel()
        self._log_panel.setMaximumHeight(68)
        rl.addWidget(self._log_panel)

        root.addWidget(right)

        # ── 启动模拟 ──
        self._bridge.start()
        self._log_panel.log_system_startup()
        self._log_panel.append_log('模拟模式 -- 静态展示, 无交互', 'system')
        self._status_bar.set_normal_active(True)

        self._bridge.fall_alert_triggered.connect(self._on_fall)
        self._bridge.fire_alert_triggered.connect(self._on_fire)

        # 刷新
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(33)

        print('智能报警监护 -- 模拟模式 (单页静态展示)')

    def _refresh(self):
        if not self._bridge._running:
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

    def _on_fall(self, active):
        self._status_bar.set_fall_alert(active)
        if active:
            self._log_panel.log_fall_alert()
        else:
            self._log_panel.log_fall_cleared()

    def _on_fire(self, active):
        self._status_bar.set_fire_alert(active)
        if active:
            self._log_panel.log_fire_alert()
        else:
            self._log_panel.log_fire_cleared()

    def closeEvent(self, event):
        self._bridge.stop()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont('Microsoft YaHei', 14))
    qss = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       'styles', 'theme.qss')
    if os.path.exists(qss):
        with open(qss, 'r', encoding='utf-8') as f:
            app.setStyleSheet(f.read())
    w = MockMainWindow()
    show_splash_and_run(app, w, duration_ms=2000)
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
