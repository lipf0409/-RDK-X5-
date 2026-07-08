#!/usr/bin/env python3
"""
ASR 语音识别模块
=================
合并三份讯飞 WebSocket 实现 (test_iflytek.py + voice_assistant_audio.py + test_pipeline.py)
以及 OpenAI Whisper API。

支持后端:
  - iflytek:    讯飞语音听写 WebSocket API (免费 500次/天，中文最佳)
  - whisper_api: OpenAI Whisper API (需要 API Key)
"""

import base64
import hashlib
import hmac
import json as _json
import logging
import os
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urlencode

log = logging.getLogger("asr_client")


class ASRClient:
    """语音识别客户端"""

    def __init__(self, config):
        self.config = config

    def recognize(self, audio_path: str) -> Optional[str]:
        """
        将音频文件识别为文本。
        返回识别文本，失败返回 None。
        """
        if self.config.asr_backend == "iflytek":
            return self._recognize_iflytek(audio_path)
        elif self.config.asr_backend == "whisper_api":
            return self._recognize_whisper(audio_path)
        else:
            log.error(f"未知的 ASR 后端: {self.config.asr_backend}")
            return None

    # ------------------------------------------------------------------
    # Whisper API
    # ------------------------------------------------------------------
    def _recognize_whisper(self, audio_path: str) -> Optional[str]:
        """使用 OpenAI Whisper API"""
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=self.config.openai_api_key,
                base_url=self.config.openai_base_url,
            )
            with open(audio_path, "rb") as f:
                result = client.audio.transcriptions.create(
                    model=self.config.whisper_model,
                    file=f,
                    language="zh",
                )
            text = result.text.strip()
            log.info(f"📝 ASR (Whisper): {text}")
            return text if text else None

        except Exception as e:
            log.error(f"Whisper API 识别失败: {e}")
            return None

    # ------------------------------------------------------------------
    # 讯飞语音听写 WebSocket API
    # ------------------------------------------------------------------
    def _recognize_iflytek(self, audio_path: str) -> Optional[str]:
        """讯飞语音听写 - WebSocket 分帧上传"""
        import websocket

        # 读取音频
        with open(audio_path, "rb") as f:
            audio_data = f.read()

        # 跳过 WAV 头 (44 bytes)，只取 PCM 数据
        if audio_data[:4] == b"RIFF":
            audio_data = audio_data[44:]

        if len(audio_data) == 0:
            log.warning("ASR: 音频为空")
            return None

        # 鉴权参数
        host = "iat-api.xfyun.cn"
        path = "/v2/iat"
        now = datetime.utcnow()
        date = now.strftime("%a, %d %b %Y %H:%M:%S GMT")

        # HMAC-SHA256 签名
        signature_origin = f"host: {host}\ndate: {date}\nGET {path} HTTP/1.1"
        signature_sha = hmac.new(
            self.config.iflytek_api_secret.encode(),
            signature_origin.encode(),
            hashlib.sha256,
        ).digest()
        signature = base64.b64encode(signature_sha).decode()

        authorization_origin = (
            f'api_key="{self.config.iflytek_api_key}", algorithm="hmac-sha256", '
            f'headers="host date request-line", signature="{signature}"'
        )
        authorization = base64.b64encode(authorization_origin.encode()).decode()

        query = urlencode({
            "authorization": authorization,
            "date": date,
            "host": host,
        })
        ws_url = f"wss://{host}{path}?{query}"

        # WebSocket 同步通信
        result_text = []
        chunk_size = 1280  # 40ms at 16kHz

        try:
            ws = websocket.create_connection(ws_url, timeout=10)

            # 分帧发送: status=0 首帧(带参数), status=1 中间帧, status=2 尾帧
            pos = 0
            while pos < len(audio_data):
                end = min(pos + chunk_size, len(audio_data))
                chunk = audio_data[pos:end]

                if pos == 0:
                    # 首帧: 参数 + 第一块音频
                    params = {
                        "common": {"app_id": self.config.iflytek_app_id},
                        "business": {
                            "language": "zh_cn",
                            "domain": "iat",
                            "accent": "mandarin",
                            "vad_eos": 3000,
                            "dwa": "wpgs",
                        },
                        "data": {
                            "status": 0,
                            "format": "audio/L16;rate=16000",
                            "encoding": "raw",
                            "audio": base64.b64encode(chunk).decode(),
                        },
                    }
                elif end < len(audio_data):
                    # 中间帧
                    params = {
                        "data": {
                            "status": 1,
                            "format": "audio/L16;rate=16000",
                            "encoding": "raw",
                            "audio": base64.b64encode(chunk).decode(),
                        }
                    }
                else:
                    # 尾帧
                    params = {
                        "data": {
                            "status": 2,
                            "format": "audio/L16;rate=16000",
                            "encoding": "raw",
                            "audio": base64.b64encode(chunk).decode(),
                        }
                    }
                ws.send(_json.dumps(params))
                pos = end

            # 接收结果
            ws.settimeout(5)
            while True:
                try:
                    msg = ws.recv()
                    m = _json.loads(msg)
                    code = m.get("code", 0)
                    if code != 0:
                        log.error(f"讯飞 ASR 错误: code={code}, msg={m.get('message', '')}")
                        break
                    r = m.get("data", {}).get("result", {})
                    if r:
                        for w in r.get("ws", []):
                            for c in w.get("cw", []):
                                result_text.append(c.get("w", ""))
                    st = m.get("data", {}).get("status", 0)
                    if st == 2:
                        break
                except websocket.WebSocketTimeoutException:
                    break
                except Exception as e:
                    log.error(f"讯飞接收错误: {e}")
                    break

            ws.close()

        except Exception as e:
            log.error(f"讯飞 ASR 连接失败: {e}")
            return None

        # 清洗结果
        text = "".join(result_text)
        if text:
            # 去除中文标点和空白
            text = re.sub(r"[　-〿＀-￯\s]+", "", text)
            log.info(f"📝 ASR (讯飞): {text}")
            return text
        else:
            log.warning("讯飞 ASR 未识别到文字")
            return None
