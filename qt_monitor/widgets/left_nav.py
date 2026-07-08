#!/usr/bin/env python3
"""
左侧导航栏 - 中文文字标签垂直侧边栏。
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QSizePolicy, QLabel
)


class LeftNavBar(QWidget):
    """垂直导航侧边栏，使用中文文字标签。"""

    module_selected = Signal(str)

    # (module_id, label, tooltip)
    MODULES = [
        ('nav',     '导航',  'SLAM 建图与导航'),
        ('vision',  '视觉',  '双目视觉监护'),
        ('fall',    '跌倒',  '跌倒检测报警'),
        ('fire',    '火焰',  '火焰检测报警'),
        ('voice',   '语音',  '语音唤醒'),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('leftNavBar')
        self.setFixedWidth(60)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self._buttons: dict[str, QPushButton] = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 12, 6, 12)
        layout.setSpacing(6)

        # Logo
        logo = QPushButton('R')
        logo.setObjectName('navLogo')
        logo.setToolTip('机器人监护系统')
        logo.setEnabled(False)
        logo.setFixedSize(36, 36)
        layout.addWidget(logo, alignment=Qt.AlignCenter)

        layout.addSpacing(16)

        # 模块导航按钮
        for module_id, label, tooltip in self.MODULES:
            btn = QPushButton(label)
            btn.setObjectName(f'navBtn_{module_id}')
            btn.setCheckable(True)
            btn.setMinimumHeight(44)
            btn.setFixedWidth(48)
            btn.setToolTip(tooltip)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setEnabled(True)
            btn.clicked.connect(
                lambda checked, mid=module_id: self._on_module_clicked(mid))
            self._buttons[module_id] = btn
            layout.addWidget(btn, alignment=Qt.AlignCenter)

        layout.addStretch()

        # 设置按钮
        config_btn = QPushButton('设置')
        config_btn.setObjectName('navBtn_config')
        config_btn.setCheckable(True)
        config_btn.setMinimumHeight(44)
        config_btn.setFixedWidth(48)
        config_btn.setToolTip('系统参数配置')
        config_btn.setCursor(Qt.PointingHandCursor)
        config_btn.setEnabled(True)
        config_btn.clicked.connect(
            lambda: self._on_module_clicked('config'))
        self._buttons['config'] = config_btn
        layout.addWidget(config_btn, alignment=Qt.AlignCenter)

    def _on_module_clicked(self, module_id: str):
        self.set_active_module(module_id)
        self.module_selected.emit(module_id)

    def set_active_module(self, module_id: str):
        for mid, btn in self._buttons.items():
            btn.setChecked(mid == module_id)
