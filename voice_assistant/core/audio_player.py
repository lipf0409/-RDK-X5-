#!/usr/bin/env python3
"""
音频播放器模块
==============
合并来自 voice_assistant.py (AudioPlayer) 和 voice_assistant_audio.py (play_audio/play_ding)。

特性:
  - 跨平台播放: sounddevice → pygame → winsound 回退链
  - 唤醒提示音: 预录制 WAV 或 numpy 实时合成 (C5+E5 双音)
  - 本地音频回退: play_local_response() 播放预录制响应文件
  - 序列播放: play_sequence() 拼接多段音频
"""

import logging
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("audio_player")

# 预录制音频映射
_RESPONSE_MAP = {
    "class":    "audio_class/{}.wav",
    "cross":    "audio_cross/{}.wav",
    "room":     "audio_room/{}.wav",
    "sum":      "audio_sum/{}.wav",
    "task":     "audio_task/{}.wav",
    "traffic":  "audio_traffic/{}.wav",
    "category": "{}.wav",
    "mp3":      "{}.mp3",
}


class AudioPlayer:
    """跨平台音频播放器"""

    def __init__(self, config):
        self.config = config
        self._pygame_inited = False

    # ------------------------------------------------------------------
    # 通用播放
    # ------------------------------------------------------------------
    def play(self, filepath: str, block: bool = True) -> bool:
        """播放音频文件，自动选择后端"""
        if not os.path.exists(filepath):
            log.error(f"音频文件不存在: {filepath}")
            return False

        ext = os.path.splitext(filepath)[1].lower()

        # Linux: aplay 直接播放，避免 PyAudio ALSA 冲突
        if platform.system() == "Linux":
            if self._play_linux(filepath, block):
                return True

        if ext == ".wav":
            return self._play_wav(filepath, block)
        elif ext == ".mp3":
            return self._play_mp3(filepath, block)
        else:
            log.warning(f"不支持的音频格式: {ext}")
            return False

    def _play_linux(self, filepath: str, block: bool = True) -> bool:
        """Linux: aplay 指定 M260C 扬声器 (hw:0,0)"""
        try:
            import subprocess
            cmd = ["aplay", "-q", "-D", "plughw:0,0"]
            if not block:
                cmd.insert(2, "--buffer-time=100000")
            cmd.append(filepath)
            subprocess.run(cmd, check=True, timeout=30)
            return True
        except Exception as e:
            log.debug(f"aplay hw:0,0 failed: {e}, trying default...")
            try:
                subprocess.run(["aplay", "-q", "-D", "plughw:0,0", filepath], check=True, timeout=30)
                return True
            except Exception:
                return False

    def _play_wav(self, filepath: str, block: bool = True) -> bool:
        """播放 WAV: sounddevice → pygame → winsound"""
        # 方法1: sounddevice (推荐)
        try:
            import sounddevice as sd
            import soundfile as sf
            data, sr = sf.read(filepath)
            sd.play(data, sr, device=self.config.audio_output_device)
            if block:
                sd.wait()
            return True
        except Exception as e:
            log.debug(f"sounddevice 播放失败: {e}")

        # 方法2: pygame (跨平台)
        try:
            return self._play_pygame(filepath, block)
        except Exception as e:
            log.debug(f"pygame 播放失败: {e}")

        # 方法3: 系统命令 (Windows winsound / Linux aplay)
        try:
            import platform
            if platform.system() == "Windows":
                import winsound
                winsound.PlaySound(filepath, winsound.SND_FILENAME)
            else:
                import subprocess
                subprocess.run(["aplay", "-q", filepath], check=True)
            return True
        except Exception as e:
            log.debug(f"系统播放失败: {e}")

        log.error(f"所有播放方式均失败")
        return False

    def _play_mp3(self, filepath: str, block: bool = True) -> bool:
        """播放 MP3: pygame"""
        return self._play_pygame(filepath, block)

    def _play_pygame(self, filepath: str, block: bool = True) -> bool:
        """pygame mixer 播放"""
        import pygame

        if not self._pygame_inited:
            try:
                pygame.mixer.init()
                self._pygame_inited = True
            except Exception as e:
                log.error(f"pygame mixer 初始化失败: {e}")
                return False

        try:
            pygame.mixer.music.load(filepath)
            pygame.mixer.music.play()
            if block:
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)
            return True
        except Exception as e:
            log.error(f"pygame 播放失败: {e}")
            return False

    # ------------------------------------------------------------------
    # 唤醒提示音
    # ------------------------------------------------------------------
    def play_wake_sound(self) -> bool:
        """
        播放唤醒提示音。
        优先使用预录制 WAV 文件，否则 numpy 实时合成。
        """
        # 1. 预录制文件优先
        wake_file = self.config.wake_sound_file
        if wake_file and os.path.exists(wake_file):
            return self.play(wake_file, block=True)

        # 2. 实时合成: C5 + E5 双音
        return self._synthesize_ding()

    def _synthesize_ding(self) -> bool:
        """合成并播放唤醒提示音 (C5+E5, 150ms)"""
        try:
            import numpy as np
            import wave, os, tempfile

            sr = 44100
            duration = 0.15
            t = np.linspace(0, duration, int(sr * duration), endpoint=False)
            freq1, freq2 = 523.25, 659.25
            audio = (0.3 * (
                np.sin(2 * np.pi * freq1 * t) * np.exp(-t * 8)
                + np.sin(2 * np.pi * freq2 * t) * np.exp(-t * 8)
            ) * 32767).astype(np.int16)

            tmp = os.path.join(tempfile.gettempdir(), "_wake_ding.wav")
            wf = wave.open(tmp, "wb")
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr)
            wf.writeframes(audio.tobytes()); wf.close()
            return self.play(tmp, block=True)
        except Exception as e:
            log.debug(f"合成唤醒音失败: {e}")
            return False

    # ------------------------------------------------------------------
    # 错误提示音
    # ------------------------------------------------------------------
    def play_error_sound(self) -> bool:
        """播放错误提示音"""
        error_file = str(
            Path(self.config.local_audio_dir) / "error.wav"
        )
        if os.path.exists(error_file):
            return self.play(error_file, block=True)
        # Fallback: 低频短音 写入临时文件后播放
        try:
            import numpy as np
            import wave, tempfile
            sr = 44100
            t = np.linspace(0, 0.2, int(sr * 0.2), endpoint=False)
            audio = (0.3 * np.sin(2 * np.pi * 200 * t) * np.exp(-t * 10) * 32767).astype(np.int16)
            tmp = os.path.join(tempfile.gettempdir(), "_error_beep.wav")
            wf = wave.open(tmp, "wb")
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr)
            wf.writeframes(audio.tobytes()); wf.close()
            return self.play(tmp, block=True)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 本地预录制音频回退
    # ------------------------------------------------------------------
    def play_local_response(self, category: str, key: str) -> bool:
        """
        播放预录制响应音频。

        参数:
          category: 音频类别 ("class", "cross", "room", "sum", "task", "traffic", "category", "mp3")
          key:     音频文件名 (不含扩展名)

        示例:
          play_local_response("class", "apple")   → audio_resources/audio_class/apple.wav
          play_local_response("category", "fruits") → audio_resources/fruits.wav
        """
        if not self.config.local_audio_enabled:
            return False

        template = _RESPONSE_MAP.get(category)
        if template is None:
            log.warning(f"未知音频类别: {category}")
            return False

        filename = template.format(key)
        filepath = os.path.join(self.config.local_audio_dir, filename)

        if os.path.exists(filepath):
            log.info(f"播放本地音频: {category}/{key}")
            return self.play(filepath, block=True)
        else:
            log.warning(f"本地音频文件不存在: {filepath}")
            return False

    def play_sequence(self, items: list) -> bool:
        """
        按顺序播放多段音频 (拼接)。

        参数:
          items: [(category, key), ...] 或 [filepath, ...]

        示例:
          play_sequence([
              ("task", "get"),
              ("class", "apple"),
              ("sum", "finish1"),
              ("category", "fruits"),
              ("sum", "finish2"),
              ("sum", "5"),
              ("sum", "yuan"),
          ])
        """
        for item in items:
            if isinstance(item, tuple):
                ok = self.play_local_response(item[0], item[1])
            else:
                ok = self.play(str(item), block=True)
            if not ok:
                log.warning(f"播放失败: {item}")
                continue
        return True

    @staticmethod
    def synthesize_ding_to_file(filepath: str) -> bool:
        """将唤醒提示音合成并保存到文件"""
        try:
            import numpy as np
            import wave

            sr = 44100
            duration = 0.15
            t = np.linspace(0, duration, int(sr * duration), endpoint=False)
            freq1, freq2 = 523.25, 659.25
            audio = (0.3 * (
                np.sin(2 * np.pi * freq1 * t) * np.exp(-t * 8)
                + np.sin(2 * np.pi * freq2 * t) * np.exp(-t * 8)
            ) * 32767).astype(np.int16)

            wf = wave.open(filepath, "wb")
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(audio.tobytes())
            wf.close()
            log.info(f"唤醒提示音已保存: {filepath}")
            return True
        except Exception as e:
            log.warning(f"合成提示音失败: {e}")
            return False

    @staticmethod
    def synthesize_error_to_file(filepath: str) -> bool:
        """将错误提示音合成并保存到文件"""
        try:
            import numpy as np
            import wave

            sr = 44100
            duration = 0.2
            t = np.linspace(0, duration, int(sr * duration), endpoint=False)
            audio = (0.3 * np.sin(2 * np.pi * 200 * t) * np.exp(-t * 10) * 32767).astype(np.int16)

            wf = wave.open(filepath, "wb")
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(audio.tobytes())
            wf.close()
            log.info(f"错误提示音已保存: {filepath}")
            return True
        except Exception as e:
            log.warning(f"合成错误提示音失败: {e}")
            return False
