#!/usr/bin/env python3
"""
音频软件唤醒模块
================
从 voice_assistant_audio.py 主循环逻辑抽取。

纯音频方式实现唤醒: VAD 检测语音 → 录音 → ASR 识别 → 唤醒词匹配。
不依赖串口，任何麦克风都可以使用。延迟约 3 秒 (vs 串口 ~0.1s)。

唤醒词列表: ["小飞", "小飞小飞", "xiao fei", "xiao3 fei1"]
"""

import logging
import os
import threading
import time
from typing import Callable, Optional

log = logging.getLogger("audio_wake")

# 唤醒词列表 (支持多种变体)
_WAKE_WORDS = ["小飞", "小飞小飞", "xiao fei", "xiao3 fei1"]


class AudioWakeBackend:
    """
    纯音频唤醒后端。

    使用:
        backend = AudioWakeBackend(config, audio_recorder, asr_client)
        backend.start(lambda data: print(f"wake! {data}"))
        ...
        backend.stop()
    """

    def __init__(self, config, audio_recorder, asr_client):
        self.config = config
        self.recorder = audio_recorder
        self.asr_client = asr_client
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._callbacks: list[Callable] = []
        self._muted = False  # TTS 播放时跳过 VAD

    def start(self, callback: Callable = None) -> bool:
        """启动音频监听线程。返回 True。"""
        if callback:
            self._callbacks.append(callback)

        if not self.recorder.is_open:
            if not self.recorder.open():
                log.error("无法打开麦克风，音频唤醒不可用")
                return False

        self._running = True
        self._thread = threading.Thread(
            target=self._listen_loop, daemon=True, name="audio-wake"
        )
        self._thread.start()
        log.info("🎧 音频唤醒监听已启动 (VAD + ASR，延迟约3秒)")
        return True

    def stop(self):
        """停止监听"""
        self._running = False
        self.recorder.close()

    def on_wakeup(self, callback: Callable):
        """注册唤醒回调"""
        self._callbacks.append(callback)

    # ------------------------------------------------------------------
    # 监听循环
    # ------------------------------------------------------------------
    def _listen_loop(self):
        """VAD 监听 → ASR 识别 → 唤醒词匹配"""
        while self._running:
            # TTS 播放期间完全停止录音
            while self._muted and self._running:
                time.sleep(0.2)
            if not self._running:
                break
            # 1. VAD 等待语音
            log.debug("VAD 监听中...")
            audio_file = self.recorder.listen_for_speech(
                timeout=30.0, mute_flag=lambda: self._muted)
            if not audio_file:
                log.debug("VAD 超时，继续监听...")
                continue

            log.info(f"VAD 检测到语音: {audio_file}")

            # 2. ASR 识别
            text = self.asr_client.recognize(audio_file)

            # 清理临时文件
            try:
                os.remove(audio_file)
            except OSError:
                pass

            if not text:
                log.info("ASR 未识别到文字，继续监听...")
                continue

            log.info(f"ASR 识别: {text}")

            # 3. 唤醒词匹配
            is_wake, matched_word = _check_wake_word(text)
            if not is_wake:
                log.info(f"未匹配到唤醒词 (识别文本: {text})")
                continue

            # 4. 通知回调
            log.info(f"🎤 音频唤醒! 匹配词={matched_word}, 原文={text}")
            wake_data = {
                "keyword": matched_word,
                "score": 1000,
                "beam": -1,
                "angle": -1,
                "timestamp": time.time(),
                "source": "audio",
                "asr_text": text,  # ASR 识别原文
            }
            for cb in self._callbacks:
                try:
                    cb(wake_data)
                except Exception as e:
                    log.error(f"唤醒回调异常: {e}")


def _check_wake_word(text: str) -> tuple:
    """
    检查文本是否包含唤醒词。
    返回 (is_wake: bool, matched_word: str)。
    """
    text_clean = text.lower().replace(" ", "")
    for ww in _WAKE_WORDS:
        ww_clean = ww.lower().replace(" ", "")
        if ww_clean in text_clean:
            return True, ww
    return False, ""
