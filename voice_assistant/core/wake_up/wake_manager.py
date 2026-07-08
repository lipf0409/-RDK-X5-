#!/usr/bin/env python3
"""
唤醒管理器模块
==============
编排器：串口硬件唤醒优先 → 音频软件唤醒回退。

模式:
  - "serial": 仅使用串口唤醒 (M260C 内置 DSP，延迟 ~0.1s)
  - "audio":  仅使用音频唤醒 (VAD + ASR，延迟 ~3s)
  - "auto":   先尝试串口，失败自动切换到音频 (推荐)
"""

import logging
from typing import Callable

log = logging.getLogger("wake_manager")


class WakeUpManager:
    """
    多后端唤醒编排器。

    使用:
        mgr = WakeUpManager(config, audio_recorder, asr_client)
        mgr.on_wakeup(lambda data: print(f"wake! {data}"))
        mgr.start()
    """

    def __init__(self, config, audio_recorder, asr_client):
        self.config = config
        self._recorder = audio_recorder
        self._asr_client = asr_client

        # 延迟导入，避免串口依赖不可用时无法加载
        from .serial_wake import SerialWakeBackend
        from .audio_wake import AudioWakeBackend

        self._serial = SerialWakeBackend(config)
        self._audio = AudioWakeBackend(config, audio_recorder, asr_client)
        self._active: str = ""
        self._callbacks: list[Callable] = []

    @property
    def active_backend(self) -> str:
        """当前活跃的后端: 'serial' | 'audio' | '' (未启动)"""
        return self._active

    @property
    def has_angle(self) -> bool:
        """串口唤醒模式才有声源角度信息"""
        return self._active == "serial"

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start(self, callback: Callable = None) -> bool:
        """
        启动最佳可用唤醒后端。
        callback: 唤醒时回调 callback(wake_data: dict)
        返回 True 表示至少有一个后端启动成功。
        """
        if callback:
            self._callbacks.append(callback)

        mode = self.config.wake_backend

        if mode == "serial":
            return self._start_serial()
        elif mode == "audio":
            return self._start_audio()
        else:  # "auto"
            return self._start_auto()

    def stop(self):
        """停止所有后端"""
        self._serial.stop()
        self._audio.stop()
        self._active = ""

    @property
    def muted(self) -> bool:
        return getattr(self._audio, '_muted', False)

    @muted.setter
    def muted(self, val: bool):
        self._audio._muted = val

    def on_wakeup(self, callback: Callable):
        """注册唤醒回调"""
        self._callbacks.append(callback)

    # ------------------------------------------------------------------
    # 启动策略
    # ------------------------------------------------------------------
    def _start_serial(self) -> bool:
        """强制串口模式"""
        ok = self._serial.start(self._on_wakeup)
        if ok:
            self._active = "serial"
            log.info("唤醒模式: SERIAL (硬件 DSP)")
        else:
            log.error("串口唤醒配置为必需但不可用!")
        return ok

    def _start_audio(self) -> bool:
        """强制音频模式"""
        ok = self._audio.start(self._on_wakeup)
        if ok:
            self._active = "audio"
            log.info("唤醒模式: AUDIO (VAD + ASR)")
        else:
            log.error("音频唤醒启动失败!")
        return ok

    def _start_auto(self) -> bool:
        """自动模式: 串口优先 → 音频回退"""
        if self._serial.start(self._on_wakeup):
            self._active = "serial"
            log.info("唤醒模式: SERIAL (硬件 DSP, ~0.1s 延迟)")
            return True

        log.warning("串口连接失败，尝试音频唤醒回退...")
        if self._audio.start(self._on_wakeup):
            self._active = "audio"
            log.info("唤醒模式: AUDIO (VAD + ASR, ~3s 延迟)")
            log.warning("提示: 连接 M260C USB 并检查 COM 口可启用硬件唤醒")
            return True

        log.error("所有唤醒方式均不可用! 请检查 M260C 连接")
        return False

    # ------------------------------------------------------------------
    # 回调转发
    # ------------------------------------------------------------------
    def _on_wakeup(self, wake_data: dict):
        """将唤醒事件转发给所有注册的回调"""
        for cb in self._callbacks:
            try:
                cb(wake_data)
            except Exception as e:
                log.error(f"唤醒回调异常: {e}")
