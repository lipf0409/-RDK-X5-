#!/usr/bin/env python3
"""
统一音频设备查找模块
=====================
合并来自 voice_assistant.py 和 voice_assistant_audio.py 的设备发现逻辑。

优先级策略:
  麦克风:
    1. 用户指定的设备索引
    2. 内置麦克风阵列 (Intel SST / 智音)
    3. 原生 16000Hz 输入设备 (ASR 最佳)
    4. Digital_Array_Mic (M260C) via DirectSound
    5. 任何包含 "digital" 关键词的输入设备
    6. 系统默认输入设备

  扬声器:
    1. 用户指定的设备索引
    2. USB Audio 设备 (M260C 扬声器)
    3. 系统默认输出设备
"""

import logging
from typing import Optional, Tuple

log = logging.getLogger("audio_device")


def find_mic(preferred_index: Optional[int] = None) -> Tuple[Optional[int], int]:
    """
    查找最佳麦克风输入设备。
    返回 (device_index, sample_rate)。device_index 为 None 时表示未找到。
    """
    # 用户指定优先
    if preferred_index is not None:
        log.info(f"使用用户指定的输入设备: 索引 {preferred_index}")
        return preferred_index, _get_device_rate(preferred_index, is_input=True)

    try:
        import pyaudio
        p = pyaudio.PyAudio()
        devices = [(i, p.get_device_info_by_index(i)) for i in range(p.get_device_count())]

        # 优先级1: Linux ALSA M260C/XFMDPV0018 硬件设备
        for i, info in devices:
            name = info["name"].lower()
            if info["maxInputChannels"] > 0 and any(
                kw in name for kw in ["xfmdpv", "m260", "6mic", "6-mic", "circular"]
            ):
                rate = int(info["defaultSampleRate"])
                log.info(f"M260C Linux: [{i}] {info['name']} ({rate}Hz)")
                p.terminate()
                return i, rate

        # 优先级2: 蓝牙耳机麦克风 (iFLYBUDS / headset / headphones)
        for i, info in devices:
            name = info["name"].lower()
            if info["maxInputChannels"] > 0 and any(
                kw in name for kw in ["iflybuds", "headset", "headphone", "earphone"]
            ):
                rate = int(info["defaultSampleRate"])
                log.info(f"Headset mic: [{i}] {info['name']} ({rate}Hz)")
                p.terminate()
                return i, rate

        # 优先级3: 笔记本内置麦克风阵列 (Intel SST)
        for i, info in devices:
            name = info["name"].lower()
            ha = p.get_host_api_info_by_index(info["hostApi"])
            if (info["maxInputChannels"] > 0 and "digital" in name
                    and "mme" in ha["name"].lower()):
                rate = int(info["defaultSampleRate"])
                log.info(f"M260C MME: [{i}] {info['name']} ({rate}Hz)")
                p.terminate()
                return i, rate

        # 优先级2: 原生 16000Hz 输入设备 (ASR 最佳)
        for i, info in devices:
            if info["maxInputChannels"] > 0 and int(info["defaultSampleRate"]) == 16000:
                log.info(f"找到原生 16kHz 输入: [{i}] {info['name']}")
                p.terminate()
                return i, 16000

        # 优先级3: Intel SST / 麦克风阵列 (笔记本内置，备用)
        for i, info in devices:
            name = info["name"].lower()
            if info["maxInputChannels"] > 0 and (
                "智音" in name or "intel" in name or "麦克风阵列" in name
            ):
                rate = int(info["defaultSampleRate"])
                log.info(f"使用内置麦克风阵列: [{i}] {info['name']} ({rate}Hz)")
                p.terminate()
                return i, rate

        # 优先级4: 任何 Digital_Array_Mic
        for i, info in devices:
            name = info["name"].lower()
            if info["maxInputChannels"] > 0 and "digital" in name:
                rate = int(info["defaultSampleRate"])
                log.info(f"找到数字麦克风阵列: [{i}] {info['name']} ({rate}Hz)")
                p.terminate()
                return i, rate

        # 最终 fallback: 第一个可用输入设备
        for i, info in devices:
            if info["maxInputChannels"] > 0:
                rate = int(info["defaultSampleRate"])
                log.info(f"使用系统默认输入: [{i}] {info['name']} ({rate}Hz)")
                p.terminate()
                return i, rate

        p.terminate()
    except ImportError:
        log.warning("未安装 pyaudio，无法查找音频设备")
    except Exception as e:
        log.warning(f"查找音频设备失败: {e}")

    return None, 16000


def find_speaker(preferred_index: Optional[int] = None) -> Optional[int]:
    """
    查找最佳扬声器输出设备。
    返回 device_index，None 表示未找到。
    """
    if preferred_index is not None:
        log.info(f"使用用户指定的输出设备: 索引 {preferred_index}")
        return preferred_index

    try:
        import pyaudio
        p = pyaudio.PyAudio()

        # 优先查找 USB Audio (M260C 扬声器) - 多个关键词匹配
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            name = info["name"].lower()
            if info["maxOutputChannels"] > 0:
                if any(kw in name for kw in ["usb audio", "usb-audio", "m260", "digital"]):
                    log.info(f"M260C speaker: [{i}] {info['name']}")
                    p.terminate()
                    return i

        # Fallback: 第一个可用输出
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info["maxOutputChannels"] > 0:
                log.info(f"Fallback speaker: [{i}] {info['name']}")
                p.terminate()
                return i

        p.terminate()
    except ImportError:
        log.warning("pyaudio not installed")
    except Exception as e:
        log.warning(f"Speaker search failed: {e}")

    return None


def _get_device_rate(device_index: int, is_input: bool = True) -> int:
    """获取指定设备的采样率"""
    try:
        import pyaudio
        p = pyaudio.PyAudio()
        info = p.get_device_info_by_index(device_index)
        p.terminate()
        return int(info["defaultSampleRate"])
    except Exception:
        return 16000


def list_audio_devices() -> list:
    """列出所有音频设备，返回设备信息列表"""
    devices = {"input": [], "output": []}
    try:
        import pyaudio
        p = pyaudio.PyAudio()
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            entry = {
                "index": i,
                "name": info["name"],
                "sample_rate": int(info["defaultSampleRate"]),
                "channels_in": info["maxInputChannels"],
                "channels_out": info["maxOutputChannels"],
                "host_api": p.get_host_api_info_by_index(info["hostApi"])["name"],
            }
            if info["maxInputChannels"] > 0:
                devices["input"].append(entry)
            if info["maxOutputChannels"] > 0:
                devices["output"].append(entry)
        p.terminate()
    except Exception as e:
        log.warning(f"列出设备失败: {e}")
    return devices


def list_serial_ports() -> list:
    """列出所有可用串口"""
    ports = []
    try:
        import serial.tools.list_ports
        for p in serial.tools.list_ports.comports():
            ports.append({
                "device": p.device,
                "description": p.description,
                "hwid": p.hwid,
                "vid": p.vid,
                "pid": p.pid,
            })
    except Exception as e:
        log.warning(f"列出串口失败: {e}")
    return ports


def print_devices():
    """打印格式化的音频设备和串口列表 (CLI 用途)"""
    import sys
    # 安全输出：用 ascii 替换无法编码的字符
    def safe_print(s):
        try:
            print(s)
        except UnicodeEncodeError:
            print(s.encode(sys.stdout.encoding, errors='replace').decode(sys.stdout.encoding, errors='replace'))

    audio = list_audio_devices()

    safe_print("\n" + "=" * 70)
    safe_print("  音频输入设备 (麦克风)")
    safe_print("=" * 70)
    for d in audio["input"]:
        safe_print(f"  [{d['index']}] {d['name']}")
        safe_print(f"      采样率: {d['sample_rate']}Hz, 通道: {d['channels_in']}, "
                   f"驱动: {d['host_api']}")

    safe_print("\n" + "=" * 70)
    safe_print("  音频输出设备 (扬声器)")
    safe_print("=" * 70)
    for d in audio["output"]:
        safe_print(f"  [{d['index']}] {d['name']}")
        safe_print(f"      采样率: {d['sample_rate']}Hz, 通道: {d['channels_out']}, "
                   f"驱动: {d['host_api']}")

    safe_print("\n" + "=" * 70)
    safe_print("  可用串口")
    safe_print("=" * 70)
    ports = list_serial_ports()
    if ports:
        for p in ports:
            safe_print(f"  {p['device']}")
            safe_print(f"    描述: {p['description']}")
            if p['vid']:
                safe_print(f"    VID:PID = {p['vid']:04X}:{p['pid']:04X}")
    else:
        safe_print("  (未找到串口)")
    safe_print("")
