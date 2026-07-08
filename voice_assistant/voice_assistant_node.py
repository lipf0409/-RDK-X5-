#!/usr/bin/env python3
"""
ROS2 语音助手节点
==================
发布:
  /voice/angle    (Int32)   - 唤醒声源角度
  /voice/wakeup   (String)  - 唤醒事件 JSON
  /voice/question (String)  - 用户语音识别文本
  /voice/answer   (String)  - AI 回复文本
  /voice/command  (String)  - 解析后的机器人指令 JSON
  /cmd_vel        (Twist)   - 移动控制指令

订阅:
  /voice/speak    (String)  - 外部请求 TTS 播报 (如 QT 告警)
"""

import asyncio
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import rclpy
from rclpy.node import Node
from std_msgs.msg import Int32, String, Bool
from geometry_msgs.msg import Twist


class VoiceAssistantNode(Node):
    def __init__(self):
        super().__init__("voice_assistant_node")

        # 加载配置
        from core.config_manager import ConfigManager
        self._config = ConfigManager.resolve()
        self._config.ros_enabled = True

        # ── 发布者 ──
        self._pub_angle = self.create_publisher(Int32, "/voice/angle", 10)
        self._pub_wakeup = self.create_publisher(String, "/voice/wakeup", 10)
        self._pub_question = self.create_publisher(String, "/voice/question", 10)
        self._pub_answer = self.create_publisher(String, "/voice/answer", 10)
        self._pub_command = self.create_publisher(String, "/voice/command", 10)
        self._pub_cmd_vel = self.create_publisher(Twist, "/cmd_vel", 10)

        # ── 订阅者 ──
        self._sub_speak = self.create_subscription(
            String, "/voice/speak", self._on_speak, 10)
        self._sub_fall = self.create_subscription(
            Bool, "/fall_alert", self._on_fall_alert, 10)
        self._sub_fire = self.create_subscription(
            Bool, "/fire_alert", self._on_fire_alert, 10)
        self._sub_status = self.create_subscription(
            String, "/monitor_status", self._on_monitor_status, 10)
        self._fall_playing = False
        self._fire_playing = False

        # 视觉检测缓存 (用于语义理解场景描述)
        self._latest_detection = {
            "person_count": 0, "has_fall": False, "has_fire": False,
            "head_heights": [], "location": "家"
        }

        # ── 指令解析器 ──
        from voice_command import VoiceCommandParser
        self._cmd_parser = VoiceCommandParser()

        # ── 对话状态 ──
        self._dialogue_active = False
        self._last_cmd_time = 0.0

        self.get_logger().info(
            "Voice topics: /voice/[angle, wakeup, question, answer, command] + /cmd_vel + /voice/speak")

        # ── 启动内部语音助手 ──
        from voice_assistant import VoiceAssistant
        self._assistant = VoiceAssistant(self._config)
        self._assistant.on_wakeup(self._on_wakeup)
        self._assistant.on_recognition(self._on_recognition)
        self._assistant.on_response(self._on_response)
        self._assistant.on_command(self._on_command)

        self._thread = threading.Thread(
            target=self._assistant.start, daemon=True)
        self._thread.start()

    # ── ROS2 回调 ──

    def _on_wakeup(self, wake_data: dict):
        angle = wake_data.get("angle", -1)
        if 0 <= angle <= 360:
            self._pub_angle.publish(Int32(data=int(angle)))
        self._pub_wakeup.publish(
            String(data=json.dumps(wake_data, ensure_ascii=False)))
        self._dialogue_active = True
        self.get_logger().info(f"Wake: angle={angle} deg")

    def _on_recognition(self, text: str):
        self._pub_question.publish(String(data=text))
        self.get_logger().info(f"Q: {text}")

        # 使用语义解析器 (LLM优先, 关键词降级)
        cmd = self._assistant.semantic.parse(text) if hasattr(self._assistant, 'semantic') else self._cmd_parser.parse(text)
        if cmd:
            cmd_json = json.dumps(cmd, ensure_ascii=False)
            self._pub_command.publish(String(data=cmd_json))
            self.get_logger().info(f"Cmd: {cmd['action']} (confidence={cmd.get('confidence','?')})")

            # === 移动指令已禁用 (改用键盘 teleop 控制) ===
            # if cmd["action"] == "move":
            #     tw = Twist()
            #     tw.linear.x = float(cmd["linear"])
            #     tw.angular.z = float(cmd["angular"])
            #     self._pub_cmd_vel.publish(tw)
            #     self.get_logger().info(
            #         f"Move: linear={tw.linear.x} angular={tw.angular.z}")
            #     # 2 秒后自动停止
            #     if tw.linear.x != 0 or tw.angular.z != 0:
            #         self._schedule_stop()
            if cmd["action"] == "move":
                self.get_logger().info(
                    f"Move cmd ignored (keyboard control only): "
                    f"linear={cmd.get('linear')} angular={cmd.get('angular')}")

            elif cmd["action"] == "navigate":
                target = cmd.get("target", "")
                pose = self._cmd_parser.get_nav_pose(target)
                if pose:
                    self.get_logger().info(
                        f"Navigate to: {target} ({pose})")
                    # Future: publish navigation goal

            elif cmd["action"] == "patrol":
                mode = cmd.get("mode", "")
                self.get_logger().info(f"Patrol: {mode}")

            elif cmd["action"] == "query":
                qtype = cmd.get("type", "")
                self.get_logger().info(f"Query: {qtype}")

    def _on_response(self, text: str):
        self._pub_answer.publish(String(data=text))
        self._dialogue_active = False
        self.get_logger().info(f"A: {text[:80]}")

    def _on_command(self, cmd: dict):
        """语音指令 → ROS2 话题"""
        cmd_json = self._cmd_parser.to_json(cmd)
        self._pub_command.publish(String(data=cmd_json))
        if cmd["action"] == "move":
            # === 移动指令已禁用 (改用键盘 teleop 控制) ===
            # from geometry_msgs.msg import Twist
            # tw = Twist()
            # tw.linear.x = float(cmd["linear"])
            # tw.angular.z = float(cmd["angular"])
            # self._pub_cmd_vel.publish(tw)
            self.get_logger().info(f"Move cmd ignored: l={cmd.get('linear')} a={cmd.get('angular')}")
        elif cmd["action"] == "patrol":
            self.get_logger().info(f"Patrol: {cmd['mode']}")

    def _on_speak(self, msg: String):
        """外部请求 TTS 播报 (如 QT 告警)。"""
        text = msg.data
        self.get_logger().info(f"TTS request: {text[:60]}")
        try:
            asyncio.run(self._assistant._speak_and_play(text))
        except Exception as e:
            self.get_logger().error(f"TTS failed: {e}")

    def _on_monitor_status(self, msg: String):
        """接收视觉监控状态，更新检测缓存"""
        try:
            status = msg.data
            # 解析 status 字符串: "FPS:xx KF_height:x.xx Fall_counter:x Fire_counter:x Has_depth:xx Has_color:xx Has_det:xx"
            parts = {}
            for part in status.split():
                if ':' in part:
                    k, v = part.split(':', 1)
                    parts[k] = v

            has_det = parts.get('Has_det', 'False') == 'True'
            fire_cnt = float(parts.get('Fire_counter', '0'))
            fall_cnt = float(parts.get('Fall_counter', '0'))
            kf_height = float(parts.get('KF_height', '1.7'))

            self._latest_detection = {
                "person_count": 1 if has_det else 0,
                "has_fall": fall_cnt > 5,
                "has_fire": fire_cnt > 0,
                "head_heights": [kf_height] if has_det else [],
                "location": "家",
            }
            # 同步到语音助手的语义解析器
            if hasattr(self._assistant, 'update_detection'):
                self._assistant.update_detection(self._latest_detection)
        except Exception:
            pass

    def _on_fall_alert(self, msg: Bool):
        """跌倒告警 → 语音播报。"""
        if msg.data and not self._fall_playing:
            self._fall_playing = True
            self.get_logger().warn("FALL ALERT!")
            self._play_alert("alert_fall.wav", "发现人员跌倒，已报警")

    def _on_fire_alert(self, msg: Bool):
        """火警告警 → 语音播报。"""
        if msg.data and not self._fire_playing:
            self._fire_playing = True
            self.get_logger().warn("FIRE ALERT!")
            self._play_alert("alert_fire.wav", "发现火警，请注意")

    def _play_alert(self, wav_file: str, tts_text: str):
        """播放预录制告警 WAV，回退到 TTS 合成。"""
        import os, threading
        # 多路径搜索 (ROS2 install 目录不同)
        search_dirs = [
            "/home/sunrise/ucar_01/voice_assistant/audio_resources",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio_resources"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../../voice_assistant/audio_resources"),
        ]
        path = None
        for d in search_dirs:
            p = os.path.join(d, wav_file)
            if os.path.exists(p):
                path = p
                break
        if path:
            self.get_logger().info(f"Playing alert: {path}")
            self._assistant.player.play(path, block=True)
        else:
            self.get_logger().warn(f"Alert file not found, using TTS: {wav_file}")
            try:
                asyncio.run(self._assistant._speak_and_play(tts_text))
            except Exception as e:
                self.get_logger().error(f"TTS fallback failed: {e}")
        # 10 秒冷却
        def _cooldown():
            import time
            time.sleep(10)
            if wav_file == "alert_fall.wav":
                self._fall_playing = False
            else:
                self._fire_playing = False
        threading.Thread(target=_cooldown, daemon=True).start()

    # === 自动停车已禁用 (改用键盘 teleop 控制) ===
    # def _schedule_stop(self):
    #     """2 秒后自动停车 (安全措施)。"""
    #     import time
    #     self._last_cmd_time = time.time()
    #     t = threading.Timer(2.0, self._auto_stop, args=(self._last_cmd_time,))
    #     t.daemon = True
    #     t.start()
    #
    # def _auto_stop(self, cmd_time: float):
    #     """如果 2 秒内没有新指令，自动停车。"""
    #     import time
    #     if time.time() - self._last_cmd_time >= 1.9:
    #         tw = Twist()
    #         tw.linear.x = 0.0
    #         tw.angular.z = 0.0
    #         self._pub_cmd_vel.publish(tw)
    #         self.get_logger().info("Auto-stop: 2s timeout")

    # ── 生命周期 ──

    def destroy_node(self):
        self._assistant.stop()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = VoiceAssistantNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
