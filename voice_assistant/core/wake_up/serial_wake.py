#!/usr/bin/env python3
"""
M260C 串口硬件唤醒模块 (二进制帧协议)
======================================
基于 C++ 参考实现 (iflyucar/ucar/ucar_ws/src/speech_command/) 逆向。

M260C 通过 USB 转串口 (CH9102) 使用二进制帧协议通信:

  帧格式 (发送/接收):
    Byte 0:    0xA5          (同步头)
    Byte 1:    0x01          (UID, 确认帧为 0x00)
    Byte 2:    消息类型       (0x01=CONFIRM, 0x04=AIUI_MSG)
    Byte 3-4:  内容长度       (小端序 uint16)
    Byte 5-6:  会话ID         (小端序 uint16)
    Byte 7..:  内容           (AIUI_MSG 时为 JSON 字符串)
    最后字节:  CRC 校验       ((~sum_of_previous_bytes + 1) & 0xFF)

  接收流程:
    1. 读字节流, 找 0xA5 0x01 同步头
    2. 解析 7 字节头, 获取 size + sid
    3. 读取 size + 1 (CRC) 字节内容
    4. 验证 CRC
    5. 发送 CONFIRM 确认帧 (0xA5 0x00 0x00 0x00 0x00 sid_L sid_H + CRC)
    6. 解析 JSON: eventType=4 → 唤醒! 提取 ivw.{keyword,score,beam,angle}
"""

import json
import logging
import queue
import struct
import threading
import time
from typing import Callable, Optional

log = logging.getLogger("serial_wake")

# 协议常量
SYNC_HEAD = 0xA5
SYNC_HEAD_SECOND = 0x01
MSG_TYPE_CONFIRM = 0x01
MSG_TYPE_AIUI = 0x04

HEADER_SIZE = 7  # sync + uid + type + size(2) + sid(2)
MIN_FRAME = HEADER_SIZE + 1  # header + min 1 byte CRC


def _calc_crc(data: bytes) -> int:
    """计算协议 CRC: (~sum + 1) & 0xFF"""
    s = sum(data) & 0xFFFFFFFF
    return (~s + 1) & 0xFF


def _make_confirm(sid: int) -> bytes:
    """
    构造确认帧:
      0xA5 0x00 0x01 0x04 0x00 sid_L sid_H + 4 bytes zeros + CRC
    即 MakeMsgPacket(sid, CONFIRM, "\x00\x00\x00\x00")
    """
    content = b'\xa5\x00\x00\x00'
    size = len(content)
    header = bytes([
        0xA5,                    # sync
        0x00,                    # uid
        MSG_TYPE_CONFIRM,        # type
        size & 0xFF,             # size_low
        (size >> 8) & 0xFF,      # size_high
        sid & 0xFF,              # sid_low
        (sid >> 8) & 0xFF,       # sid_high
    ])
    payload = header + content
    crc = _calc_crc(payload)
    return payload + bytes([crc])


def _unpack_header(data: bytes) -> Optional[dict]:
    """
    解析 7 字节头部，返回 {type, size, sid} 或 None。
    data 至少 7 字节。
    """
    if len(data) < HEADER_SIZE:
        return None
    if data[0] != SYNC_HEAD or data[1] != SYNC_HEAD_SECOND:
        return None
    return {
        'type': data[2],
        'size': data[3] | (data[4] << 8),   # little-endian uint16
        'sid': data[5] | (data[6] << 8),
    }


class SerialWakeBackend:
    """
    M260C 二进制协议串口唤醒后端。

    与 C++ speech_command_node 实现兼容。
    提供与 AudioWakeBackend 相同的接口。
    """

    def __init__(self, config):
        self.config = config
        self._serial = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._wakeup_callbacks: list[Callable] = []
        self._last_wake_time = 0.0

    @property
    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def connect(self) -> bool:
        """连接 M260C 串口"""
        try:
            import serial
            self._serial = serial.Serial(
                port=self.config.serial_port,
                baudrate=self.config.serial_baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.1,  # 短超时，用于非阻塞读取
            )
            log.info(f"Serial connected: {self.config.serial_port} @ "
                     f"{self.config.serial_baudrate} baud (binary protocol)")
            return True
        except Exception as e:
            log.error(f"Serial connect failed ({self.config.serial_port}): {e}")
            return False

    def disconnect(self):
        """断开串口"""
        self._running = False
        if self._serial and self._serial.is_open:
            self._serial.close()
            log.info("Serial disconnected")

    def start(self, callback: Callable = None) -> bool:
        """启动串口监听线程"""
        if not self.is_connected:
            if not self.connect():
                return False
        if callback:
            self._wakeup_callbacks.append(callback)

        self._running = True
        self._thread = threading.Thread(
            target=self._read_loop, daemon=True, name="serial-wake"
        )
        self._thread.start()
        log.info("Serial wake-up listening (binary protocol, 'xiao fei xiao fei')")
        return True

    def stop(self):
        """停止监听"""
        self._running = False
        self.disconnect()

    def on_wakeup(self, callback: Callable):
        """注册唤醒回调 callback(wake_data: dict)"""
        self._wakeup_callbacks.append(callback)

    # ------------------------------------------------------------------
    # 二进制帧读取循环
    # ------------------------------------------------------------------
    def _read_loop(self):
        """读取字节流，解析二进制帧"""
        buf = b''
        last_heartbeat = 0
        while self._running and self.is_connected:
            try:
                # 读可用字节
                waiting = self._serial.in_waiting
                now = time.time()
                if waiting == 0:
                    if now - last_heartbeat > 5:
                        log.info("Serial alive: waiting for wake-up... (say xiao fei xiao fei)")
                        last_heartbeat = now
                    time.sleep(0.01)
                    continue

                chunk = self._serial.read(min(waiting, 1024))
                if not chunk:
                    continue
                buf += chunk

                # 尝试从 buffer 中解析帧
                buf = self._process_buffer(buf)

            except serial.SerialException as e:
                log.error(f"Serial error: {e}")
                time.sleep(0.5)
            except Exception as e:
                log.error(f"Serial read error: {e}")
                time.sleep(0.1)

    def _process_buffer(self, buf: bytes) -> bytes:
        """从字节缓冲区中提取并处理完整帧，返回剩余字节"""
        while len(buf) >= MIN_FRAME:
            # 查找同步头
            sync_idx = buf.find(bytes([SYNC_HEAD, SYNC_HEAD_SECOND]))
            if sync_idx < 0:
                # 没有同步头，保留最后可能的部分 (最多1字节)
                return buf[-1:] if len(buf) > 0 else b''

            if sync_idx > 0:
                log.debug(f"Skipping {sync_idx} bytes before sync header")
            buf = buf[sync_idx:]

            if len(buf) < MIN_FRAME:
                return buf  # 不完整的头部

            # 解析头部
            header = _unpack_header(buf[:HEADER_SIZE])
            if header is None:
                buf = buf[1:]
                continue

            # 跳过 type=0xFF 的心跳帧
            if buf[2] == 0xFF:
                buf = buf[HEADER_SIZE:]
                continue

            msg_type = header['type']
            content_size = header['size']
            sid = header['sid']

            # 计算完整帧长度
            total_len = HEADER_SIZE + content_size + 1  # header + content + CRC
            if len(buf) < total_len:
                return buf  # 内容还没收完，等更多字节

            frame = buf[:total_len]
            buf = buf[total_len:]

            # 验证 CRC
            expected_crc = _calc_crc(frame[:-1])
            actual_crc = frame[-1]
            if expected_crc != actual_crc:
                log.debug(f"CRC mismatch: expected 0x{expected_crc:02X}, "
                          f"got 0x{actual_crc:02X}")
                continue

            # 发送确认
            try:
                ack = _make_confirm(sid)
                self._serial.write(ack)
                log.debug(f"Sent ACK for sid={sid}")
            except Exception as e:
                log.debug(f"Failed to send ACK: {e}")

            # 处理消息
            if msg_type == MSG_TYPE_AIUI:
                content = frame[HEADER_SIZE:HEADER_SIZE + content_size]
                self._handle_aiui_message(content)
            else:
                log.debug(f"Unknown msg type: 0x{msg_type:02X}")

        return buf

    def _handle_aiui_message(self, content: bytes):
        """解析 AIUI JSON 消息并检测唤醒事件"""
        try:
            text = content.decode('utf-8', errors='replace')
        except Exception:
            text = content.decode('gbk', errors='replace')

        log.debug(f"AIUI message: {text[:200]}")

        try:
            msg = json.loads(text)
        except json.JSONDecodeError:
            log.debug(f"Non-JSON AIUI content: {text[:100]}")
            return

        msg_type = msg.get("type", "")

        if msg_type == "aiui_event":
            inner = msg.get("content", {})
            event_type = inner.get("eventType", 0)

            if event_type == 4:  # EVENT_WAKEUP
                self._handle_wakeup(inner)
            elif event_type == 3:
                state = inner.get("arg1", 0)
                state_names = {1: "IDLE", 2: "READY", 3: "WORKING"}
                log.debug(f"M260C state: {state_names.get(state, state)}")
            elif event_type == 5:
                log.debug("M260C sleep")
        elif msg_type == "version":
            log.info(f"M260C version: {msg.get('content', '')[:100]}")
        elif msg_type == "error":
            log.warning(f"M260C error: {msg.get('content', '')}")
        elif msg_type == "started":
            log.info(f"M260C started: {msg.get('content', '')[:100]}")

    def _handle_wakeup(self, content: dict):
        """处理唤醒事件"""
        now = time.time()

        # 冷却检查
        if now - self._last_wake_time < self.config.wake_cooldown:
            log.debug("Wake cooldown, skipping")
            return

        # 解析 info JSON
        info_str = content.get("info", "{}")
        try:
            info = json.loads(info_str)
            ivw = info.get("ivw", {})
            score = ivw.get("score", 0)
            keyword = ivw.get("keyword", "")
            beam = ivw.get("beam", -1)
            angle = ivw.get("angle", -1)
        except json.JSONDecodeError:
            score = 0
            keyword = ""
            beam = -1
            angle = -1

        # 置信度过滤
        if score < self.config.wake_score_threshold:
            log.debug(f"Wake score too low: {score} < {self.config.wake_score_threshold}")
            return

        self._last_wake_time = now
        log.info(f"WAKE-UP! keyword={keyword} score={score:.0f} "
                 f"beam={beam} angle={angle} deg")

        # 通知回调
        wake_data = {
            "keyword": keyword,
            "score": score,
            "beam": beam,
            "angle": angle,
            "timestamp": now,
            "source": "serial",
        }
        for cb in self._wakeup_callbacks:
            try:
                cb(wake_data)
            except Exception as e:
                log.error(f"Wake callback error: {e}")
