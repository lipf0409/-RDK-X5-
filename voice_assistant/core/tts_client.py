#!/usr/bin/env python3
"""
TTS 语音合成模块
================
合并来自 voice_assistant.py (TTSClient) 和 voice_assistant_audio.py (tts_synthesize)。

支持后端:
  - iflytek: 讯飞在线语音合成 (WebSocket, 免费 500次/天, 中文自然)
  - edge:    Edge TTS (免费云端, 需翻墙)
  - pyttsx3: 离线 TTS (中文生硬, 仅作备选)

新增:
  - synthesize_with_fallback(): 云端 TTS → 本地回退
"""

import asyncio
import logging
import os
import time
from typing import Optional

log = logging.getLogger("tts_client")


class TTSClient:
    """语音合成客户端"""

    def __init__(self, config):
        self.config = config

    async def synthesize(self, text: str) -> Optional[str]:
        """将文本合成为语音文件，返回文件路径"""
        if self.config.tts_backend == "iflytek":
            return await self._synthesize_iflytek(text)
        elif self.config.tts_backend == "edge":
            return await self._synthesize_edge(text)
        elif self.config.tts_backend == "pyttsx3":
            return self._synthesize_pyttsx3(text)
        else:
            log.error(f"未知的 TTS 后端: {self.config.tts_backend}")
            return None

    async def synthesize_with_fallback(self, text: str) -> Optional[str]:
        """
        智能回退: Edge TTS → pyttsx3 → 失败返回 None
        """
        # 1. 尝试配置的云端 TTS
        result = await self.synthesize(text)
        if result:
            return result

        # 2. 云端失败，自动回退 pyttsx3
        log.info("云端 TTS 失败，回退到本地 pyttsx3...")
        try:
            result = self._synthesize_pyttsx3(text)
            if result:
                return result
        except Exception:
            pass

        # 3. 本地也失败
        log.error("所有 TTS 方式均失败")
        return None

    async def _synthesize_edge(self, text: str) -> Optional[str]:
        """使用 Edge TTS (免费，效果好)，输出 WAV 供 aplay 播放"""
        try:
            import edge_tts

            mp3_path = os.path.join(self.config.temp_dir, f"tts_{int(time.time())}.mp3")
            wav_path = os.path.join(self.config.temp_dir, f"tts_{int(time.time())}.wav")
            communicate = edge_tts.Communicate(text, self.config.edge_voice)
            await communicate.save(mp3_path)

            # 转换为 WAV (aplay 不支持 MP3)
            import subprocess
            subprocess.run(
                ["ffmpeg", "-y", "-i", mp3_path, "-ar", "16000", "-ac", "1",
                 "-sample_fmt", "s16", wav_path],
                capture_output=True, check=True, timeout=10,
            )
            try:
                os.remove(mp3_path)
            except OSError:
                pass

            log.info(f"🔊 TTS (Edge): {text[:60]}...")
            return wav_path

        except Exception as e:
            log.error(f"Edge TTS 合成失败: {e}")
            return None

    async def _synthesize_iflytek(self, text: str) -> Optional[str]:
        """讯飞在线语音合成 WebSocket API (参照官方 websdk demo)"""
        import hashlib, hmac, base64, json as _json
        from datetime import datetime
        from time import mktime
        from wsgiref.handlers import format_date_time
        from urllib.parse import urlencode
        import websocket

        try:
            # 官方 host: ws-api.xfyun.cn
            host = "ws-api.xfyun.cn"
            path = "/v2/tts"
            now = datetime.now()
            date = format_date_time(mktime(now.timetuple()))

            # HMAC-SHA256 签名 (与官方一致)
            sig_origin = f"host: {host}\ndate: {date}\nGET {path} HTTP/1.1"
            sig = base64.b64encode(hmac.new(
                self.config.iflytek_api_secret.encode('utf-8'),
                sig_origin.encode('utf-8'), hashlib.sha256).digest()).decode('utf-8')

            auth_origin = (f'api_key="{self.config.iflytek_api_key}", '
                           f'algorithm="hmac-sha256", '
                           f'headers="host date request-line", '
                           f'signature="{sig}"')
            auth = base64.b64encode(auth_origin.encode('utf-8')).decode('utf-8')

            ws_url = f"wss://{host}{path}?{urlencode({'authorization': auth, 'date': date, 'host': host})}"

            # 业务参数 (与官方 demo 一致)
            params = {
                "common": {"app_id": self.config.iflytek_app_id},
                "business": {
                    "aue": "raw",
                    "auf": "audio/L16;rate=16000",
                    "vcn": "x4_yezi",   # 讯飞叶子 (中文女声)
                    "tte": "utf8",
                },
                "data": {
                    "status": 2,
                    "text": str(base64.b64encode(text.encode('utf-8')), "UTF8"),
                },
            }

            ws = websocket.create_connection(ws_url, timeout=10)
            ws.send(_json.dumps(params))

            # 接收所有音频帧 (讯飞分多帧发送)
            pcm_data = b""
            ws.settimeout(10)
            while True:
                try:
                    msg = ws.recv()
                    resp = _json.loads(msg)
                    code = resp.get("code", 0)
                    if code != 0:
                        log.error(f"讯飞 TTS 错误: code={code} msg={resp.get('message', '')}")
                        break
                    audio_b64 = resp.get("data", {}).get("audio", "")
                    if audio_b64:
                        pcm_data += base64.b64decode(audio_b64)
                    status = resp.get("data", {}).get("status", 0)
                    if status == 2:  # 最后一帧
                        break
                except websocket.WebSocketTimeoutException:
                    break
            ws.close()

            if len(pcm_data) < 100:
                log.warning("讯飞 TTS 返回音频过短")
                return None

            # 保存 raw PCM 为 16kHz 16-bit mono WAV
            import wave
            wav_path = os.path.join(self.config.temp_dir, f"tts_{int(time.time())}.wav")
            wf = wave.open(wav_path, "wb")
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(pcm_data)
            wf.close()

            log.info(f"🔊 TTS (讯飞): {text[:60]}...")
            return wav_path

        except Exception as e:
            log.error(f"讯飞 TTS 合成失败: {e}")
            return None

    def _synthesize_pyttsx3(self, text: str) -> Optional[str]:
        """使用 pyttsx3 (离线 espeak)"""
        try:
            import pyttsx3

            filepath = os.path.join(self.config.temp_dir, f"tts_{int(time.time())}.wav")
            engine = pyttsx3.init()
            # Linux espeak 中文优化
            engine.setProperty("rate", 150)  # 慢一点更清晰
            # 尝试设置中文语音
            voices = engine.getProperty("voices")
            for v in voices:
                if "mandarin" in v.id.lower() or "chinese" in v.id.lower() or "zh" in v.id.lower():
                    engine.setProperty("voice", v.id)
                    break
            engine.save_to_file(text, filepath)
            engine.runAndWait()
            engine.stop()
            log.info(f"🔊 TTS (pyttsx3): {text[:60]}...")
            return filepath

        except Exception as e:
            log.error(f"pyttsx3 TTS 合成失败: {e}")
            return None
