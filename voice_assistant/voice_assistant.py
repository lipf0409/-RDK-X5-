#!/usr/bin/env python3
"""
语音唤醒 + 智能对话助手
=========================
M260C USB 圆形6麦阵列 语音唤醒系统。

特性:
  - 串口唤醒 (M260C 内置 DSP, ~0.1s 延迟)  ← 默认
  - 音频唤醒 (VAD + ASR, ~3s 延迟)           ← 自动回退
  - ASR → LLM → TTS 完整对话链路
  - 钩子系统: on_wakeup / on_recognition / on_response
  - 本地预录制音频回退 (断网时)

架构:
  core/ 包: 共享模块 (config, audio, asr, llm, tts, wake_up)
  voice_assistant.py: 主控制器 (编排 core 模块)
  voice_assistant_ros.py: ROS 桥接节点

用法:
  python voice_assistant.py                          # 默认 (auto 模式)
  python voice_assistant.py --wake serial            # 仅串口
  python voice_assistant.py --wake audio             # 仅音频
  python voice_assistant.py --list-audio             # 列出音频设备
  python voice_assistant.py --list-serial            # 列出串口
"""

import argparse
import asyncio
import logging
import os
import platform
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

# 确保 core 包可导入
sys.path.insert(0, str(Path(__file__).parent))

from core.config_manager import ConfigManager, Config
from core.audio_device import find_mic, find_speaker, print_devices
from core.audio_recorder import AudioRecorder
from core.audio_player import AudioPlayer
from core.asr_client import ASRClient
from core.llm_client import LLMClient
from core.tts_client import TTSClient
from core.wake_up import WakeUpManager
from core.semantic_parser import SemanticParser

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("voice_assistant")


# ============================================================================
# 语音助手主控制器
# ============================================================================
class VoiceAssistant:
    """语音助手主控制器 — 编排所有 core 模块"""

    def __init__(self, config: Config = None):
        self.config = config or Config()

        # 音频设备
        self._mic_index, self._mic_rate = find_mic(self.config.audio_input_device)
        self._spk_index = find_speaker(self.config.audio_output_device)
        self.config.audio_input_device = self._mic_index
        self.config.audio_output_device = self._spk_index

        # 模块初始化
        self.recorder = AudioRecorder(self.config)
        self.player = AudioPlayer(self.config)
        self.asr_client = ASRClient(self.config)
        self.llm_client = LLMClient(self.config)
        self.tts_client = TTSClient(self.config)
        self.wake_manager = WakeUpManager(
            self.config, self.recorder, self.asr_client
        )

        # 语义理解模块 (LLM 意图解析 + 关键词降级)
        self.semantic = SemanticParser(self.llm_client)

        # 状态
        self._running = False
        self._processing = False

        # 钩子 (供 ROS 节点等外部消费者使用)
        self._hook_wakeup: list[Callable] = []
        self._hook_recognition: list[Callable] = []
        self._hook_response: list[Callable] = []

    # ------------------------------------------------------------------
    # 钩子注册
    # ------------------------------------------------------------------
    def on_wakeup(self, callback: Callable):
        """注册唤醒钩子 callback(wake_data: dict)"""
        self._hook_wakeup.append(callback)

    def on_recognition(self, callback: Callable):
        """注册识别钩子 callback(text: str)"""
        self._hook_recognition.append(callback)

    def on_response(self, callback: Callable):
        """注册回复钩子 callback(text: str)"""
        self._hook_response.append(callback)

    # ------------------------------------------------------------------
    # 启动 / 停止
    # ------------------------------------------------------------------
    def start(self) -> bool:
        """启动语音助手"""
        log.info("=" * 60)
        log.info("🎤 M260C 语音助手启动中...")
        log.info(f"   唤醒词: '{self.config.wake_word}'")
        log.info(f"   唤醒模式: {self.config.wake_backend}")
        log.info(f"   串口: {self.config.serial_port} @ {self.config.serial_baudrate} baud")
        log.info(f"   麦克风: [{self._mic_index}] {self._mic_rate}Hz")
        log.info(f"   扬声器: [{self._spk_index}]")
        log.info(f"   ASR: {self.config.asr_backend}  |  "
                 f"LLM: {self.config.llm_backend}  |  TTS: {self.config.tts_backend}")
        if IS_LINUX and self.config.ros_enabled:
            log.info(f"   ROS: 启用 ({self.config.ros_angle_topic}, "
                     f"{self.config.ros_question_topic}, {self.config.ros_answer_topic})")
        log.info(f"   本地音频回退: {'启用' if self.config.local_audio_enabled else '禁用'}")
        log.info(f"   平台: {platform.system()} {platform.machine()}")
        log.info("=" * 60)

        # 启动唤醒管理器
        if not self.wake_manager.start(self._on_wakeup):
            log.error("唤醒引擎启动失败!")
            return False

        self._running = True
        log.info("✅ 语音助手已就绪，等待唤醒词 '小飞小飞'...")
        log.info("   (按 Ctrl+C 停止)")
        return True

    def stop(self):
        """停止语音助手"""
        log.info("正在停止语音助手...")
        self._running = False
        self.wake_manager.stop()
        self.recorder.close()
        log.info("✅ 已停止")

    # ------------------------------------------------------------------
    # 唤醒处理
    # ------------------------------------------------------------------
    def _on_wakeup(self, wake_data: dict):
        """唤醒回调 — 在新线程中处理对话"""
        # 通知外部钩子
        for cb in self._hook_wakeup:
            try:
                cb(wake_data)
            except Exception as e:
                log.error(f"唤醒钩子异常: {e}")

        # 避免重复处理
        if self._processing:
            log.info("正在处理上一轮对话，跳过本次唤醒")
            return

        threading.Thread(
            target=self._handle_dialogue,
            args=(wake_data,),
            daemon=True,
            name="dialogue",
        ).start()

    def _handle_dialogue(self, wake_data: dict):
        """执行完整对话流程: ding → 录音 → ASR → LLM → TTS → 播放"""
        self._processing = True
        try:
            # 0. 打印唤醒信息
            source = wake_data.get("source", "?")
            angle = wake_data.get("angle", -1)
            score = wake_data.get("score", 0)
            log.info(f"🔔 收到唤醒 [{source}] angle={angle}° score={score:.0f}")

            # 1. 播放唤醒提示音 (简短 ding)
            self.player.play_wake_sound()

            # 1.5 检查唤醒文本中是否已包含指令 (如 "小飞小飞开始巡逻")
            wake_text = wake_data.get("asr_text", "")
            if wake_text and self._try_execute_command(wake_text):
                log.info("唤醒文本中已包含指令，跳过二次录音")
                return

            # 2. 录音
            audio_file = self.recorder.record()
            if not audio_file:
                log.warning("录音失败或没有语音输入")
                return

            # 3. ASR 识别
            user_text = self.asr_client.recognize(audio_file)
            if not user_text:
                self.player.play_error_sound()
                return

            # 通知外部钩子
            for cb in self._hook_recognition:
                try:
                    cb(user_text)
                except Exception as e:
                    log.error(f"识别钩子异常: {e}")

            log.info(f"👤 用户说: {user_text}")

            # 4. 检查是否为机器人指令 → 直接执行，跳过 LLM+TTS
            is_cmd = self._try_execute_command(user_text)
            if is_cmd:
                # 清理录音后返回 (已通过 ROS2 发布指令)
                if not self.config.save_audio and os.path.exists(audio_file):
                    try: os.remove(audio_file)
                    except OSError: pass
                return

            # 5. LLM 对话
            reply_text = self.llm_client.chat(user_text)
            if not reply_text:
                asyncio.run(self._speak_and_play("抱歉，我暂时无法回答这个问题。"))
                return

            # 通知外部钩子
            for cb in self._hook_response:
                try:
                    cb(reply_text)
                except Exception as e:
                    log.error(f"回复钩子异常: {e}")

            # 6. TTS + 播放
            asyncio.run(self._speak_and_play(reply_text))

            # 6. 清理录音
            if not self.config.save_audio and os.path.exists(audio_file):
                try:
                    os.remove(audio_file)
                except OSError:
                    pass

        except Exception as e:
            log.error(f"对话流程异常: {e}", exc_info=True)
        finally:
            self._processing = False

    def _try_execute_command(self, text: str) -> bool:
        """使用语义理解解析语音指令并执行。返回 True 表示匹配到指令。"""
        try:
            # 使用语义解析器 (LLM 优先, 关键词降级)
            cmd = self.semantic.parse(text)
            if not cmd:
                return False

            action = cmd.get("action", "none")
            confidence = cmd.get("confidence", 0.7)

            # speak/none 类型: 非机器人指令, 走 LLM 对话
            if action in ("speak", "none"):
                log.info(f"非机器人指令 (confidence={confidence:.0%}), 走 LLM 对话")
                return False

            # 巡逻指令: 播放应答语音
            if action == "patrol" and cmd.get("mode") == "start":
                self._play_wake_response()

            # 查询指令: 生成场景描述
            if action == "query" and cmd.get("query_type") == "inspect":
                self._handle_inspect_query(cmd)

            # 通过钩子发布到 ROS2
            for cb in self._hook_recognition:
                try: cb(text)
                except Exception: pass
            if hasattr(self, '_hook_command'):
                for cb in getattr(self, '_hook_command', []):
                    try: cb(cmd)
                    except Exception: pass

            log.info(f"✅ 指令已执行: {action} (语义理解, confidence={confidence:.0%})")
            return True

        except Exception as e:
            log.debug(f"指令解析失败: {e}")
        return False

    def _handle_inspect_query(self, cmd: dict):
        """处理检查类查询: 结合视觉检测结果播报场景"""
        # 获取最新的视觉检测信息 (通过钩子从 ROS 节点注入)
        detection = getattr(self, '_latest_detection', None)
        if detection and self.llm_client:
            desc = self.semantic.describe_scene(detection)
            if desc:
                log.info(f"📷 场景描述: {desc}")
                # 异步播报
                import asyncio
                asyncio.run(self._speak_and_play(desc))
                return
        # 无检测数据时用 LLM 直接回复
        log.info("无视觉数据, 跳过场景描述")

    def update_detection(self, detection_info: dict):
        """更新视觉检测结果 (供 ROS 节点调用)"""
        self._latest_detection = detection_info
        self.semantic.add_context("detection", detection_info)

    def on_command(self, callback):
        """注册指令钩子 callback(cmd: dict)"""
        if not hasattr(self, '_hook_command'):
            self._hook_command = []
        self._hook_command.append(callback)

    def _play_wake_response(self):
        """播放唤醒应答 '小飞收到，开始巡逻'。"""
        import os
        # 多路径搜索
        dirs = [
            os.path.dirname(os.path.abspath(__file__)),
            "/home/sunrise/ucar_01/voice_assistant",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "voice_assistant"),
        ]
        for d in dirs:
            path = os.path.join(d, "audio_resources", "wake_response.wav")
            if os.path.exists(path):
                log.info(f"播放唤醒应答: {path}")
                self.player.play(path, block=True)
                return
        log.warning("唤醒应答文件未找到，使用合成 ding")
        self.player.play_wake_sound()

    async def _speak_and_play(self, text: str):
        """合成语音并播放，期间静音 VAD 防止回音"""
        self.wake_manager.muted = True
        audio_file = await self.tts_client.synthesize_with_fallback(text)

        if audio_file:
            self.player.play(audio_file, block=True)
            # 等余音消散 + 防 aplay 被后续录音打断
            import time
            time.sleep(0.8)
            try:
                os.remove(audio_file)
            except OSError:
                pass
        elif self.config.local_audio_enabled:
            log.warning("云端 TTS 不可用，尝试本地音频...")
            response = self._match_local_response(text)
            if response:
                self.player.play_sequence(response)
            else:
                self.player.play_error_sound()

        time.sleep(0.5)
        self.wake_manager.muted = False

    def _match_local_response(self, text: str) -> Optional[list]:
        """尝试将 LLM 回复文本匹配为本地预录制音频序列"""
        text_lower = text.lower()
        result = []

        # 常见模式匹配
        import re

        # 匹配: "我已完成..." + 物品列表
        if any(w in text for w in ["已完成", "采购", "购买"]):
            result.append(("sum", "finish1"))
            # 检测物品类别
            if any(w in text for w in ["水果", "苹果", "香蕉", "西瓜"]):
                result.append(("category", "fruits"))
            elif any(w in text for w in ["蔬菜", "辣椒", "西红柿", "土豆"]):
                result.append(("category", "vages"))
            elif any(w in text for w in ["甜品", "蛋糕", "甜点"]):
                result.append(("category", "sweets"))
            # 匹配数字
            nums = re.findall(r'\d+', text)
            if nums:
                n = int(nums[0])
                if 1 <= n <= 10:
                    result.append(("sum", str(n)))
                elif 11 <= n <= 19:
                    result.append(("sum", "10"))
                    result.append(("sum", str(n - 10)))
            if "元" in text:
                result.append(("sum", "yuan"))
            if result:
                return result

        # 匹配: 房间导航
        for room in ["a", "b", "c"]:
            if room in text_lower or f"房间{room}" in text:
                return [("room", room.upper())]

        return None

    def run_forever(self):
        """运行主循环 (阻塞)"""
        if not self.start():
            return
        try:
            while self._running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            log.info("\n收到中断信号")
        finally:
            self.stop()


# ============================================================================
# 命令行入口
# ============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="M260C 语音唤醒 + 智能对话助手",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python voice_assistant.py                              # 默认 (auto 模式)
  python voice_assistant.py --wake serial                # 强制串口唤醒
  python voice_assistant.py --wake audio                 # 强制音频唤醒
  python voice_assistant.py --config config.yaml         # 指定配置文件
  python voice_assistant.py --port COM11 --asr iflytek   # 命令行覆盖配置
  python voice_assistant.py --list-audio                 # 列出音频设备
  python voice_assistant.py --list-serial                # 列出串口
        """,
    )
    parser.add_argument("--config", "-c", default=None, help="YAML 配置文件路径")
    parser.add_argument("--port", default=None, help=f"串口号 (默认: COM11)")
    parser.add_argument("--wake", default=None, choices=["serial", "audio", "auto"],
                        help="唤醒模式 (默认: auto)")
    parser.add_argument("--asr", default=None, choices=["whisper_api", "iflytek"],
                        help="ASR 后端")
    parser.add_argument("--llm", default=None, choices=["ollama", "openai"],
                        help="LLM 后端")
    parser.add_argument("--tts", default=None, choices=["edge", "pyttsx3"],
                        help="TTS 后端")
    parser.add_argument("--ollama-model", default=None, help="Ollama 模型名")
    parser.add_argument("--save-audio", action="store_true", help="保存录音文件")
    parser.add_argument("--debug", action="store_true", help="调试模式")
    parser.add_argument("--ros", action="store_true", help="启用 ROS 发布模式")
    parser.add_argument("--list-audio", action="store_true", help="列出音频设备后退出")
    parser.add_argument("--list-serial", action="store_true", help="列出串口后退出")
    args = parser.parse_args()

    # 设备列表模式
    if args.list_audio or args.list_serial:
        print_devices()
        return

    # 构建 CLI 覆盖字典
    cli = {}
    if args.port:
        cli["serial_port"] = args.port
    if args.wake:
        cli["wake_backend"] = args.wake
    if args.asr:
        cli["asr_backend"] = args.asr
    if args.llm:
        cli["llm_backend"] = args.llm
    if args.tts:
        cli["tts_backend"] = args.tts
    if args.ollama_model:
        cli["ollama_model"] = args.ollama_model
    if args.save_audio:
        cli["save_audio"] = True
    if args.debug:
        cli["debug"] = True
    if args.ros:
        cli["ros_enabled"] = True

    # 解析配置
    config = ConfigManager.resolve(yaml_path=args.config, cli_overrides=cli)

    # 启动
    assistant = VoiceAssistant(config)
    assistant.run_forever()


if __name__ == "__main__":
    main()
