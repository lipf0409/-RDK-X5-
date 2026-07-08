#!/usr/bin/env python3
"""启动画面 - 应用启动时展示。"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QPen, QBrush
from PySide6.QtWidgets import QSplashScreen, QApplication


def create_splash(app: QApplication) -> QSplashScreen:
    """创建启动画面, 居中显示项目名称和加载状态。

    绘制一个 480x320 的纯色启动画面:
      - 深蓝底色 (#16213E)
      - 橙色 Logo 标识
      - 项目标题和副标题
      - 底部版本信息和加载提示
    """
    w, h = 480, 320
    pixmap = QPixmap(w, h)
    pixmap.fill(QColor('#16213E'))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    # ── 橙色顶部装饰条 ──
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor('#FF7F00')))
    painter.drawRect(0, 0, w, 4)

    # ── Logo 圆形 ──
    cx, cy = w // 2, 100
    r = 44
    painter.setBrush(QBrush(QColor('#FF7F00')))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(cx - r, cy - r, r * 2, r * 2)

    font_logo = QFont('Microsoft YaHei', 28)
    font_logo.setBold(True)
    painter.setFont(font_logo)
    painter.setPen(QColor('#FFFFFF'))
    painter.drawText(cx - r, cy - r, r * 2, r * 2,
                      Qt.AlignCenter, 'R')

    # ── 标题 ──
    font_title = QFont('Microsoft YaHei', 22)
    font_title.setBold(True)
    painter.setFont(font_title)
    painter.setPen(QColor('#FFFFFF'))
    painter.drawText(0, 165, w, 36, Qt.AlignCenter,
                     '智能报警监护机器人')

    # ── 副标题 ──
    font_sub = QFont('Microsoft YaHei', 13)
    painter.setFont(font_sub)
    painter.setPen(QColor('#8899BB'))
    painter.drawText(0, 205, w, 24, Qt.AlignCenter,
                     'JGB520 + RPLidar A2M6 + SC230AI')

    # ── 分割线 ──
    painter.setPen(QPen(QColor('#2A3A5E'), 1))
    painter.drawLine(100, 245, w - 100, 245)

    # ── 底部信息 ──
    font_bot = QFont('Microsoft YaHei', 11)
    painter.setFont(font_bot)
    painter.setPen(QColor('#667799'))
    painter.drawText(0, 258, w, 20, Qt.AlignCenter,
                     'RDK X5  |  Ubuntu 22.04  |  ROS2 Humble')
    painter.drawText(0, 280, w, 20, Qt.AlignCenter,
                     'PySide6 Qt 监控界面')

    # ── 加载提示 ──
    font_load = QFont('Microsoft YaHei', 10)
    painter.setFont(font_load)
    painter.setPen(QColor('#FF7F00'))
    painter.drawText(0, h - 28, w, 20, Qt.AlignCenter,
                     '正在初始化传感器连接...')

    painter.end()

    splash = QSplashScreen(pixmap)
    splash.setWindowFlags(
        Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
    splash.setEnabled(False)

    return splash


def show_splash_and_run(app: QApplication, main_window,
                        duration_ms: int = 2000):
    """显示启动画面, 延时后显示主窗口。

    Args:
        app: QApplication 实例
        main_window: 主窗口实例
        duration_ms: 启动画面显示时长 (毫秒)
    """
    splash = create_splash(app)
    splash.show()
    app.processEvents()

    def _show_main():
        splash.close()
        main_window.show()

    QTimer.singleShot(duration_ms, _show_main)
