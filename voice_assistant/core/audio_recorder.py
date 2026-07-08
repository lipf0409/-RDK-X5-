#!/usr/bin/env python3
"""
录音器模块
==========
合并来自 voice_assistant.py (AudioRecorder) 和 voice_assistant_audio.py (AudioListener)。

提供两种录音模式:
  1. record(duration)    - 定时录音 + 静音截断 (用于串口唤醒后录音)
  2. listen_for_speech()  - VAD 持续监听 + 自动录音 (用于纯音频唤醒模式)
"""

import logging
import os
import struct
import time
import wave
from typing import Optional, Tuple

import pyaudio as _pyaudio_ref

from .audio_device import find_mic

log = logging.getLogger("audio_recorder")


class AudioRecorder:
    """统一录音器: 双模式 (定时 / VAD监听) + 自动重采样到 16kHz"""

    def __init__(self, config):
        self.config = config
        self._p = None
        self._stream = None
        self._mic_index = None
        self._mic_rate = 16000
        self._open = False

    def open(self) -> bool:
        """打开麦克风，准备录音"""
        try:
            import pyaudio
        except ImportError:
            log.error("未安装 pyaudio，无法录音")
            return False

        self._mic_index = self.config.audio_input_device
        if self._mic_index is None:
            self._mic_index, self._mic_rate = find_mic()
        else:
            # 获取用户指定设备的采样率
            try:
                p_test = pyaudio.PyAudio()
                info = p_test.get_device_info_by_index(self._mic_index)
                self._mic_rate = int(info["defaultSampleRate"])
                p_test.terminate()
            except Exception:
                self._mic_rate = 16000

        if self._mic_index is None:
            log.error("未找到可用麦克风")
            return False

        self._p = pyaudio.PyAudio()
        try:
            # 用设备原生采样率打开（PyAudio 软件重采样不可靠）
            self._stream = self._p.open(
                format=pyaudio.paInt16,
                channels=self.config.channels,
                rate=self._mic_rate,  # 用设备原生采样率
                input=True,
                input_device_index=self._mic_index,
                frames_per_buffer=self.config.chunk_size * 2,  # Linux ALSA 需要更大缓冲区
            )
            self._stream.start_stream()
            self._open = True
            log.info(f"麦克风已打开: [{self._mic_index}] "
                     f"原生采样率={self._mic_rate}Hz, "
                     f"录音后将重采样到 {self.config.sample_rate}Hz")
            return True
        except Exception as e:
            log.error(f"无法打开麦克风: {e}")
            self._p.terminate()
            self._p = None
            return False

    def close(self):
        """关闭麦克风"""
        self._open = False
        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._p:
            try:
                self._p.terminate()
            except Exception:
                pass
            self._p = None

    def _reopen(self):
        """ALSA xrun 恢复：关闭并重新打开流"""
        log.warning("检测到音频流错误，尝试恢复...")
        try:
            if self._stream:
                self._stream.stop_stream()
                self._stream.close()
            self._stream = None
        except Exception:
            pass
        time.sleep(0.5)
        try:
            self._stream = self._p.open(
                format=self._p.get_sample_size(pyaudio.paInt16),
                channels=self.config.channels,
                rate=self._mic_rate,
                input=True,
                input_device_index=self._mic_index,
                frames_per_buffer=self.config.chunk_size * 2,  # 更大缓冲区
            )
            self._stream.start_stream()
            return True
        except Exception as e:
            log.error(f"流恢复失败: {e}")
            return False

    @property
    def is_open(self) -> bool:
        return self._open

    # ------------------------------------------------------------------
    # 模式1: 定时录音 (串口唤醒后使用)
    # ------------------------------------------------------------------
    def record(self, duration: float = None) -> Optional[str]:
        if not self._open:
            if not self.open():
                return None
        if duration is None:
            duration = self.config.record_seconds_max

        mic_rate = self._mic_rate  # 用设备原生采样率
        channels = self.config.channels
        chunk = self.config.chunk_size

        log.info(f"🎙️  开始录音 (最长 {duration} 秒)...")

        frames = []
        silent_chunks = 0
        max_silent = int(self.config.silence_seconds * mic_rate / chunk)

        try:
            while len(frames) * chunk / mic_rate < duration:
                data = self._stream.read(chunk, exception_on_overflow=False)
                frames.append(data)

                rms = self._compute_rms(data)
                if rms < self.config.silence_threshold:
                    silent_chunks += 1
                else:
                    silent_chunks = 0

                if silent_chunks >= max_silent and len(frames) > mic_rate // chunk:
                    dur = len(frames) * chunk / mic_rate
                    log.info(f"检测到静音，停止录音 ({dur:.1f}秒)")
                    break
        except Exception as e:
            log.error(f"录音异常: {e}")

        if not frames:
            log.warning("未录制到音频数据")
            return None

        # 组装原始音频 + 增益提升
        raw = b"".join(frames)
        raw = _apply_gain(raw, target_rms=3000)

        # 如果设备采样率不是 16kHz，重采样
        if self._mic_rate != 16000:
            raw = _resample_pcm(raw, self._mic_rate, 16000)
            log.debug(f"已重采样 {self._mic_rate}Hz -> 16000Hz")

        # 保存为 WAV
        filepath = os.path.join(self.config.temp_dir, f"voice_cmd_{int(time.time())}.wav")
        return self._save_wav(filepath, raw, 16000, channels)

    # ------------------------------------------------------------------
    # 模式2: VAD 持续监听 (纯音频唤醒使用)
    # ------------------------------------------------------------------
    def listen_for_speech(self, timeout: float = 30.0,
                          mute_flag=None) -> Optional[str]:
        """
        持续监听直到检测到语音并自动录制完成。
        VAD 状态机: waiting → recording → done
        mute_flag: 可选的 lambda/函数，返回 True 时立即中止录音
        """
        if not self._open:
            if not self.open():
                return None

        mic_rate = self._mic_rate
        chunk = self.config.chunk_size
        channels = self.config.channels

        frames = []
        voiced_chunks = 0
        silent_chunks = 0
        min_voiced = int(0.15 * mic_rate / chunk)      # 至少 0.15s 语音 (短唤醒词)
        max_silent = int(self.config.silence_seconds * mic_rate / chunk)
        state = "waiting"

        log.info("VAD 监听中 (说 xiao fei xiao fei)...")
        last_heartbeat = 0
        heartbeat_interval = 3  # 每3秒打印一次当前 RMS

        while True:
            try:
                data = self._stream.read(chunk, exception_on_overflow=False)
            except Exception:
                break

            rms = self._compute_rms(data)

            # 心跳日志：显示 VAD 在正常运行
            now = time.time()
            if now - last_heartbeat > heartbeat_interval:
                log.info(f"VAD alive: state={state} rms={rms:.0f} threshold={self.config.silence_threshold}")
                last_heartbeat = now

            if state == "waiting":
                if rms > self.config.silence_threshold:
                    voiced_chunks += 1
                    frames.append(data)
                    if voiced_chunks >= min_voiced:
                        state = "recording"
                        log.info(f"VAD: 检测到语音! RMS={rms:.0f}")
                        silent_chunks = 0
                else:
                    voiced_chunks = 0

            elif state == "recording":
                frames.append(data)
                if rms < self.config.silence_threshold:
                    silent_chunks += 1
                else:
                    silent_chunks = 0
                if silent_chunks >= max_silent:
                    state = "done"
                    break

            # TTS 播放期间立即中止录音
            if mute_flag and mute_flag():
                log.debug("VAD aborted (muted)")
                return None

            if len(frames) * chunk / mic_rate > timeout:
                break

        min_frames = mic_rate // chunk  # 至少 1 秒音频
        if state != "done" or len(frames) < min_frames:
            return None

        raw = b"".join(frames)
        raw = _apply_gain(raw, target_rms=3000)
        dur = len(raw) / (mic_rate * channels * 2)
        log.info(f"VAD: 检测到语音 {dur:.1f}s (设备={mic_rate}Hz)")

        # 重采样到 16kHz (ASR 要求)
        if mic_rate != 16000:
            raw = _resample_pcm(raw, mic_rate, 16000)
            log.debug(f"已重采样到 16000Hz ({len(raw)/32000:.1f}s)")

        # 截断过长音频 (最多20秒)
        max_bytes = 20 * 16000 * 2
        if len(raw) > max_bytes:
            raw = raw[:max_bytes]
            log.debug("音频过长，已截断至前20秒")

        filepath = os.path.join(self.config.temp_dir, f"vad_{int(time.time())}.wav")
        return self._save_wav(filepath, raw, 16000, channels)

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    def _save_wav(self, filepath: str, raw: bytes, rate: int, channels: int) -> str:
        """保存原始 PCM 为 WAV 文件"""
        wf = wave.open(filepath, "wb")
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(rate)
        wf.writeframes(raw)
        wf.close()
        dur = len(raw) / (rate * channels * 2)
        log.info(f"✅ 录音完成: {filepath} ({dur:.1f}秒)")
        return filepath

    @staticmethod
    def _compute_rms(data: bytes) -> float:
        """计算 PCM 16-bit 音频的 RMS 值"""
        count = len(data) // 2
        if count == 0:
            return 0
        fmt = f"<{count}h"
        samples = struct.unpack(fmt, data)
        return (sum(s * s for s in samples) / count) ** 0.5


# ============================================================================
# 简易增益
# ============================================================================
def _apply_gain(raw: bytes, target_rms: float = 3000.0) -> bytes:
    """线性增益：将音频 RMS 提升到目标水平，带削波保护"""
    try:
        import numpy as np
        arr = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
        rms = float(np.sqrt(np.mean(arr**2)))
        if rms < 10:
            return raw  # 静音不增益
        if rms < target_rms:
            gain = min(target_rms / rms, 30.0)  # 最多 30 倍
            arr = arr * gain
            peak = float(np.max(np.abs(arr)))
            if peak > 32000:
                arr = arr * (32000.0 / peak)
        return arr.astype(np.int16).tobytes()
    except ImportError:
        return raw


# ============================================================================
# PCM 重采样工具
# ============================================================================
def _resample_pcm(raw: bytes, src_rate: int, dst_rate: int) -> bytes:
    """PCM 16-bit 重采样 (线性插值，numpy 加速)"""
    if src_rate == dst_rate:
        return raw
    try:
        import numpy as np
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
        n_out = int(len(samples) * dst_rate / src_rate)
        indices = np.arange(n_out) * src_rate / dst_rate
        lo = np.floor(indices).astype(np.int64)
        hi = np.minimum(lo + 1, len(samples) - 1)
        frac = indices - lo
        result = ((1 - frac) * samples[lo] + frac * samples[hi]).astype(np.int16)
        return result.tobytes()
    except ImportError:
        pass
    # 纯 Python fallback
    count_in = len(raw) // 2
    samples = struct.unpack(f"<{count_in}h", raw)
    count_out = int(count_in * dst_rate / src_rate)
    ratio = src_rate / dst_rate
    out = []
    for i in range(count_out):
        idx = i * ratio
        lo = int(idx)
        hi = min(lo + 1, count_in - 1)
        frac = idx - lo
        out.append(int(samples[lo] * (1 - frac) + samples[hi] * frac))
    return struct.pack(f"<{count_out}h", *out)
