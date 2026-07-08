#!/usr/bin/env python3
"""
语音对话模块 - 连接语音助手 ROS2 节点。
实时显示: 唤醒状态 / 用户语音 / AI 回复。
支持键盘输入发送文字。
"""
import json
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor, QTextCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QLineEdit, QPushButton, QFrame
)


class VoiceChatWidget(QWidget):
    """语音对话聊天窗口。

    连接 ROS2 /voice/* 话题:
      - /voice/wakeup  → 绿色唤醒指示
      - /voice/question → 用户语音文本
      - /voice/answer   → AI 回复文本
    """

    send_message = Signal(str)

    def __init__(self, bridge=None, parent=None):
        super().__init__(parent)
        self.setObjectName('voiceChatWidget')
        self._bridge = bridge
        self._wake_count = 0
        self._setup_ui()
        self._connect_bridge()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 标题栏 ──
        header = QLabel('AI 语音对话')
        header.setStyleSheet(
            'padding: 6px 12px; border-bottom: 1px solid #E2E6EA; '
            'font-size: 15px; font-weight: 600; color: #16213E; '
            'background: #F8F9FA;')
        header.setFixedHeight(30)
        layout.addWidget(header)

        # ── 对话历史 ──
        self._chat_history = QTextEdit()
        self._chat_history.setReadOnly(True)
        self._chat_history.setStyleSheet(
            'QTextEdit { background-color: #FAFBFC; color: #2D3436; '
            'border: none; font-family: "Microsoft YaHei", "Segoe UI", sans-serif; '
            'font-size: 14px; padding: 8px 10px; }')
        layout.addWidget(self._chat_history)

        # ── 唤醒状态条 ──
        wake_bar = QFrame()
        wake_bar.setStyleSheet(
            'background-color: #FEF2F2; border-top: 1px solid #FECACA; '
            'border-bottom: 1px solid #FECACA;')
        wl = QHBoxLayout(wake_bar)
        wl.setContentsMargins(10, 5, 10, 5)
        wl.setSpacing(8)

        self._wake_dot = QLabel()
        self._wake_dot.setFixedSize(10, 10)
        self._wake_dot.setStyleSheet(
            'background-color: #EF4444; border-radius: 5px;')
        wl.addWidget(self._wake_dot)

        self._wake_label = QLabel('待命中 (说"小飞小飞"唤醒)')
        self._wake_label.setStyleSheet(
            'font-size: 13px; color: #DC2626; font-weight: 500; background: transparent;')
        wl.addWidget(self._wake_label)
        wl.addStretch()

        self._mic_label = QLabel('[MIC OFF]')
        self._mic_label.setStyleSheet(
            'font-size: 12px; color: #94A3B8; background: transparent; '
            'padding: 2px 6px; border: 1px solid #D0D5DD; border-radius: 3px;')
        wl.addWidget(self._mic_label)
        layout.addWidget(wake_bar)

        # ── 输入区域 ──
        input_bar = QFrame()
        input_bar.setStyleSheet('background-color: #FFFFFF;')
        il = QHBoxLayout(input_bar)
        il.setContentsMargins(10, 6, 10, 6)
        il.setSpacing(8)

        self._input_field = QLineEdit()
        self._input_field.setPlaceholderText('输入指令控制机器人...')
        self._input_field.setEnabled(True)
        self._input_field.setMinimumHeight(34)
        self._input_field.setStyleSheet(
            'QLineEdit { background-color: #F8FAFC; '
            'border: 1px solid #D0D5DD; border-radius: 6px; '
            'padding: 4px 10px; font-size: 14px; color: #2D3436; }')

        send_btn = QPushButton('发送')
        send_btn.setEnabled(True)
        send_btn.setMinimumHeight(34)
        send_btn.setMinimumWidth(60)
        send_btn.clicked.connect(self._on_send)
        send_btn.setStyleSheet(
            'QPushButton { background-color: #FF7F00; color: #FFFFFF; '
            'border: none; border-radius: 6px; font-size: 14px; '
            'font-weight: 600; padding: 4px 16px; } '
            'QPushButton:hover { background-color: #E06E00; }')

        voice_btn = QPushButton('🎤')
        voice_btn.setEnabled(True)
        voice_btn.setMinimumHeight(34)
        voice_btn.setMinimumWidth(40)
        voice_btn.setToolTip('语音助手已就绪')
        voice_btn.setStyleSheet(
            'QPushButton { background-color: #F1F5F9; color: #4A5568; '
            'border: 1px solid #D0D5DD; border-radius: 6px; '
            'font-size: 16px; padding: 4px 10px; }')

        self._input_field.returnPressed.connect(self._on_send)
        il.addWidget(self._input_field)
        il.addWidget(send_btn)
        il.addWidget(voice_btn)
        layout.addWidget(input_bar)

    def _connect_bridge(self):
        """连接 ROS2 语音话题信号。"""
        if self._bridge is None:
            return
        self._bridge.voice_wakeup_updated.connect(self._on_wakeup)
        self._bridge.voice_question_updated.connect(self._on_question)
        self._bridge.voice_answer_updated.connect(self._on_answer)
        self._bridge.voice_command_updated.connect(self._on_command)

    # ── ROS2 信号回调 ──

    def _on_wakeup(self, data: str):
        """/voice/wakeup: 唤醒事件。"""
        self._wake_count += 1
        try:
            info = json.loads(data)
            angle = info.get('angle', -1)
            keyword = info.get('keyword', '')
        except json.JSONDecodeError:
            angle = -1
            keyword = ''
        self._set_wake_active(True)
        angle_str = f' (角度:{angle}°)' if 0 <= angle <= 360 else ''
        self._append_system(f'🎤 已唤醒 [{self._wake_count}]{angle_str}')

    def _on_question(self, text: str):
        """/voice/question: 用户语音识别结果。"""
        self._append_message('你', text, '#4A5568', '#F1F5F9')
        self._set_wake_active(True)

    def _on_answer(self, text: str):
        """/voice/answer: AI 回复。"""
        self._append_message('AI', text, '#FF7F00', '#FFF7ED')
        self._set_wake_active(False)

    def _on_command(self, data: str):
        """/voice/command: 机器人指令。"""
        try:
            cmd = json.loads(data)
            action = cmd.get("action", "")
            if action == "move":
                l = cmd.get("linear", 0)
                a = cmd.get("angular", 0)
                if l > 0:
                    desc = f"前进 (速度:{l:.1f}m/s)"
                elif l < 0:
                    desc = f"后退 (速度:{abs(l):.1f}m/s)"
                elif a > 0:
                    desc = f"左转 (角速度:{a:.1f}rad/s)"
                elif a < 0:
                    desc = f"右转 (角速度:{abs(a):.1f}rad/s)"
                else:
                    desc = "停止"
            elif action == "patrol":
                desc = {"start": "开始巡逻", "stop": "停止巡逻", "pause": "暂停巡逻"}.get(
                    cmd.get("mode", ""), "巡逻指令")
            elif action == "navigate":
                desc = f"导航到: {cmd.get('target', '?')}"
            elif action == "query":
                desc = f"查询: {cmd.get('type', '?')}"
            else:
                desc = f"指令: {action}"
            self._append_system(f"🤖 {desc}")
        except json.JSONDecodeError:
            pass

    # ── 用户输入 ──

    def _on_send(self):
        text = self._input_field.text().strip()
        if text:
            self._append_message('你', text, '#4A5568', '#F1F5F9')
            self.send_message.emit(text)
            self._input_field.clear()

    # ── UI 更新 ──

    def _set_wake_active(self, active: bool):
        if active:
            self._wake_dot.setStyleSheet(
                'background-color: #22C55E; border-radius: 5px;')
            self._wake_label.setStyleSheet(
                'font-size: 13px; color: #16A34A; font-weight: 500; '
                'background: transparent;')
            self._wake_label.setText('已唤醒 - 正在对话')
            self._mic_label.setText('[MIC ON]')
            self._mic_label.setStyleSheet(
                'font-size: 12px; color: #22C55E; background: transparent; '
                'padding: 2px 6px; border: 1px solid #22C55E; border-radius: 3px;')
        else:
            self._wake_dot.setStyleSheet(
                'background-color: #EF4444; border-radius: 5px;')
            self._wake_label.setStyleSheet(
                'font-size: 13px; color: #DC2626; font-weight: 500; '
                'background: transparent;')
            self._wake_label.setText('待命中 (说"小飞小飞"唤醒)')
            self._mic_label.setText('[MIC OFF]')
            self._mic_label.setStyleSheet(
                'font-size: 12px; color: #94A3B8; background: transparent; '
                'padding: 2px 6px; border: 1px solid #D0D5DD; border-radius: 3px;')

    def _append_system(self, text: str):
        """添加系统消息。"""
        cursor = self._chat_history.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = cursor.charFormat()
        fmt.setForeground(QColor('#94A3B8'))
        fmt.setFontWeight(QFont.Normal)
        fmt.setFontPointSize(12)
        cursor.insertText(f'{text}\n', fmt)
        self._chat_history.setTextCursor(cursor)

    def _append_message(self, sender: str, text: str,
                        name_color: str, bg_color: str):
        """添加一条消息。"""
        cursor = self._chat_history.textCursor()
        cursor.movePosition(QTextCursor.End)

        fmt_name = cursor.charFormat()
        fmt_name.setForeground(QColor(name_color))
        fmt_name.setFontWeight(QFont.Bold)
        fmt_name.setFontPointSize(13)
        cursor.insertText(f'{sender}: ', fmt_name)

        fmt_text = cursor.charFormat()
        fmt_text.setForeground(QColor('#2D3436'))
        fmt_text.setFontWeight(QFont.Normal)
        fmt_text.setFontPointSize(13)
        cursor.insertText(f'{text}\n\n', fmt_text)

        self._chat_history.setTextCursor(cursor)

    # ── 外部调用 ──

    def add_user_message(self, text: str):
        """添加用户消息 (供外部模块调用)。"""
        self._append_message('你', text, '#4A5568', '#F1F5F9')

    def add_robot_message(self, text: str):
        """添加机器人回复。"""
        self._append_message('AI', text, '#FF7F00', '#FFF7ED')

    def set_bridge(self, bridge):
        """设置/更新 ROS2 bridge 引用。"""
        self._bridge = bridge
        self._connect_bridge()
