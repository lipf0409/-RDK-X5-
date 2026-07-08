#!/usr/bin/env python3
"""
语音助手核心模块包
==================
提供统一的公共 API，消除 voice_assistant.py 和 voice_assistant_audio.py 之间的重复代码。

使用:
    from core import ConfigManager, AudioPlayer, ASRClient, LLMClient, TTSClient, WakeUpManager
    from core import AudioRecorder, find_mic, find_speaker
"""

from .config_manager import Config, ConfigManager
from .audio_device import find_mic, find_speaker, list_audio_devices, list_serial_ports, print_devices
from .audio_recorder import AudioRecorder
from .audio_player import AudioPlayer
from .asr_client import ASRClient
from .llm_client import LLMClient
from .tts_client import TTSClient
from .wake_up import WakeUpManager, SerialWakeBackend, AudioWakeBackend

__all__ = [
    "Config",
    "ConfigManager",
    "find_mic",
    "find_speaker",
    "list_audio_devices",
    "list_serial_ports",
    "print_devices",
    "AudioRecorder",
    "AudioPlayer",
    "ASRClient",
    "LLMClient",
    "TTSClient",
    "WakeUpManager",
    "SerialWakeBackend",
    "AudioWakeBackend",
]
