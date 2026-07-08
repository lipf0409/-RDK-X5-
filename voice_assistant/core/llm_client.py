#!/usr/bin/env python3
"""
LLM 大模型对话模块
==================
合并来自 voice_assistant.py (LLMClient) 和 voice_assistant_audio.py (llm_chat)。

支持后端:
  - ollama: 本地模型 (免费、隐私、推荐)
  - openai:  OpenAI API (云端、效果好)
"""

import logging
from typing import Optional

log = logging.getLogger("llm_client")


class LLMClient:
    """大模型对话客户端"""

    def __init__(self, config):
        self.config = config

    def chat(self, user_text: str) -> Optional[str]:
        """发送文本到 LLM 并获取回复"""
        return self.chat_with_prompt(
            system=self.config.system_prompt,
            user=user_text,
            temperature=0.7,
            max_tokens=200,
        )

    def chat_with_prompt(self, system: str, user: str,
                         temperature: float = 0.7,
                         max_tokens: int = 200) -> Optional[str]:
        """发送自定义 system prompt 到 LLM 并获取回复"""
        if self.config.llm_backend == "ollama":
            return self._chat_ollama_raw(system, user, temperature, max_tokens)
        elif self.config.llm_backend == "openai":
            return self._chat_openai_raw(system, user, temperature, max_tokens)
        else:
            log.error(f"未知的 LLM 后端: {self.config.llm_backend}")
            return None

    def _chat_ollama(self, user_text: str) -> Optional[str]:
        return self._chat_ollama_raw(
            self.config.system_prompt, user_text, 0.7, 200)

    def _chat_ollama_raw(self, system: str, user: str,
                         temperature: float, max_tokens: int) -> Optional[str]:
        """使用本地 Ollama 模型"""
        try:
            import ollama

            client = ollama.Client(host=self.config.ollama_host)
            response = client.chat(
                model=self.config.ollama_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                options={"temperature": temperature},
            )
            reply = response["message"]["content"].strip()
            preview = reply[:100] + "..." if len(reply) > 100 else reply
            log.info(f"🤖 LLM (Ollama/{self.config.ollama_model}): {preview}")
            return reply

        except Exception as e:
            log.error(f"Ollama 对话失败: {e}")
            return None

    def _chat_openai(self, user_text: str) -> Optional[str]:
        return self._chat_openai_raw(
            self.config.system_prompt, user_text, 0.7, 200)

    def _chat_openai_raw(self, system: str, user: str,
                         temperature: float, max_tokens: int) -> Optional[str]:
        """使用 OpenAI 兼容 API (DeepSeek / OpenAI / 硅基流动)"""
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=self.config.openai_api_key,
                base_url=self.config.openai_base_url,
            )
            response = client.chat.completions.create(
                model=self.config.llm_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            reply = response.choices[0].message.content.strip()
            preview = reply[:100] + "..." if len(reply) > 100 else reply
            log.info(f"🤖 LLM (OpenAI/{self.config.llm_model}): {preview}")
            return reply

        except Exception as e:
            log.error(f"OpenAI 对话失败: {e}")
            return None
