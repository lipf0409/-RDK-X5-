#!/usr/bin/env python3
"""顶部状态栏 - 纯文字指示灯, 无嵌套组件, 避免遮挡。"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel


class StatusBar(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('statusBar')
        self.setFixedHeight(36)
        self._blink = False
        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._toggle)
        self._labels: dict[str, QLabel] = {}
        self._active: dict[str, bool] = {
            'normal': True, 'fall': False, 'fire': False}
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(14)

        title = QLabel('智能报警监护  |  JGB520')
        title.setStyleSheet(
            'font-size: 16px; font-weight: 700; color: #16213E; '
            'background: transparent;')
        layout.addWidget(title)
        layout.addStretch()

        for key, text, color in [
            ('normal', '● 正常', '#22C55E'),
            ('fall',   '● 跌倒', '#888888'),
            ('fire',   '● 火焰', '#888888'),
        ]:
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f'font-size: 15px; font-weight: 600; color: {color}; '
                'background: transparent;')
            self._labels[key] = lbl
            layout.addWidget(lbl)
            layout.setAlignment(lbl, Qt.AlignVCenter)

    def _toggle(self):
        self._blink = not self._blink
        for key in ('fall', 'fire'):
            if self._active[key]:
                c = self._blink_color(key)
                self._labels[key].setStyleSheet(
                    f'font-size: 15px; font-weight: 700; color: {c}; '
                    'background: transparent;')

    def _blink_color(self, key):
        if self._blink:
            return '#DC2626' if key == 'fall' else '#F59E0B'
        else:
            return '#FCA5A5' if key == 'fall' else '#FDE68A'

    def set_normal_active(self, active):
        self._active['normal'] = active
        self._labels['normal'].setStyleSheet(
            'font-size: 15px; font-weight: 600; '
            f'color: {"#22C55E" if active else "#888"}; '
            'background: transparent;')

    def set_fall_alert(self, active):
        self._active['fall'] = active
        if active:
            self._blink_timer.start(400)
        else:
            self._blink_timer.stop()
            self._labels['fall'].setStyleSheet(
                'font-size: 15px; font-weight: 600; color: #888; '
                'background: transparent;')

    def set_fire_alert(self, active):
        self._active['fire'] = active
        if active:
            self._blink_timer.start(400)
        else:
            if not self._active['fall']:
                self._blink_timer.stop()
            self._labels['fire'].setStyleSheet(
                'font-size: 15px; font-weight: 600; color: #888; '
                'background: transparent;')
