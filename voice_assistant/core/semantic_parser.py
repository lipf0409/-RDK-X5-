#!/usr/bin/env python3
"""
语义理解模块 (LLM-based Semantic Parser)
========================================
利用大模型将自然语言转换为结构化机器人指令，替代传统关键词匹配。

特性:
  - Function Calling 风格: 定义可用动作的 JSON Schema
  - 上下文理解: "再去一次" / "换个方向" 等省略表达
  - 意图消歧: "前面" → 前进 / "到前面" → 导航 自动区分
  - 离线回退: LLM 不可用时自动降级为关键词匹配
  - 摄像头语义: "看看有没有人" → 拍照 + 场景描述

使用:
    from core.semantic_parser import SemanticParser
    parser = SemanticParser(llm_client)
    cmd = parser.parse("去卧室检查一下有没有异常")
    # → {"action": "navigate", "target": "bedroom", "intent": "inspect", ...}
"""

import json
import logging
from typing import Optional

log = logging.getLogger("semantic_parser")

# ═══════════════════════════════════════════════════════════════
# 机器人可用动作 Schema (Function Calling 定义)
# ═══════════════════════════════════════════════════════════════
ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["move", "navigate", "patrol", "query", "speak", "none"],
            "description": "动作类型: move=移动控制, navigate=导航去某地, patrol=巡逻, query=查询状态, speak=纯对话, none=无法理解"
        },
        "linear": {
            "type": "number",
            "description": "线速度 m/s, 正值前进负值后退, 仅 move 时需要"
        },
        "angular": {
            "type": "number",
            "description": "角速度 rad/s, 正值左转负值右转, 仅 move 时需要"
        },
        "target": {
            "type": "string",
            "description": "导航目标: dock=充电桩, bedroom=卧室, living_room=客厅, kitchen=厨房"
        },
        "mode": {
            "type": "string",
            "enum": ["start", "stop", "pause"],
            "description": "巡逻模式, 仅 patrol 时需要"
        },
        "query_type": {
            "type": "string",
            "enum": ["position", "battery", "status", "inspect"],
            "description": "查询类型: position=位置, battery=电量, status=状态, inspect=检查异常"
        },
        "intent": {
            "type": "string",
            "description": "用户意图描述, 用于日志和上下文"
        },
        "confidence": {
            "type": "number",
            "minimum": 0, "maximum": 1,
            "description": "置信度 0~1"
        },
        "reply": {
            "type": "string",
            "description": "如果 action=none, 简短回复用户的问题"
        }
    },
    "required": ["action"]
}

SYSTEM_PROMPT = """你是一个智能机器人语义理解模块，负责将用户的中文语音指令解析为结构化 JSON。

## 可用动作
- move: 移动控制 (linear=线速度m/s, angular=角速度rad/s)
  - "前进/往前走" → linear=0.2, angular=0
  - "后退" → linear=-0.15, angular=0
  - "左转" → linear=0, angular=0.5
  - "右转" → linear=0, angular=-0.5
  - "停/停下" → linear=0, angular=0
  - "掉头" → linear=0, angular=1.0
  - "慢点" → 速度减半
  - "快点" → 速度加倍(最大0.35)
- navigate: 导航到指定地点 (target: dock/bedroom/living_room/kitchen)
  - "去卧室/到卧室/回卧室" → target=bedroom
  - "去充电/回去充电" → target=dock
- patrol: 巡逻控制 (mode: start/stop/pause)
  - "开始巡逻/巡线/巡视" → mode=start
  - "停止巡逻/别巡了" → mode=stop
- query: 状态查询 (query_type: position/battery/status/inspect)
  - "你在哪里/位置" → query_type=position
  - "还有多少电/电量" → query_type=battery
  - "状态/检查一下/有没有异常" → query_type=inspect
- speak: 纯信息播报, 不需要机器人动作
- none: 无法理解时使用, 提供 reply 字段简短回复

## 语义理解要点
1. 省略表达的上下文补全: "再去一次" → 重复上次导航目标
2. 隐含意图: "去卧室看看" → navigate到卧室 + query_type=inspect
3. 多意图合并: "去充电然后休息" → navigate到dock
4. 非移动指令不要输出 move: "你好/谢谢/天气" → action=speak
5. 只输出 JSON, 不要其他文字

## 上下文
{context}

## 对话历史
{history}

请将以下用户语音解析为 JSON:"""


class SemanticParser:
    """LLM 语义解析器 — 自然语言 → 结构化指令"""

    def __init__(self, llm_client=None):
        self._llm = llm_client
        self._context: dict = {"last_target": None, "last_action": None}
        self._history: list[dict] = []  # 最近 N 轮对话

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def parse(self, text: str) -> Optional[dict]:
        """
        解析用户自然语言为结构化指令。

        Returns:
            dict 或 None (如果解析失败)
            {
                "action": "navigate",
                "target": "bedroom",
                "intent": "用户想去卧室检查",
                "confidence": 0.9,
                ...
            }
        """
        if not text or not text.strip():
            return None

        # 策略1: LLM 语义解析 (优先)
        if self._llm:
            result = self._parse_with_llm(text)
            if result:
                self._update_context(result)
                return result

        # 策略2: 关键词降级 (离线可用)
        result = self._parse_keyword(text)
        if result:
            self._update_context(result)
        return result

    # ------------------------------------------------------------------
    # LLM 语义解析
    # ------------------------------------------------------------------
    def _parse_with_llm(self, text: str) -> Optional[dict]:
        """使用大模型解析自然语言"""
        try:
            prompt = SYSTEM_PROMPT.format(
                context=json.dumps(self._context, ensure_ascii=False),
                history=json.dumps(self._history[-5:], ensure_ascii=False),
            )
            full = f"{prompt}\n用户说: {text}\nJSON:"

            reply = self._llm.chat_with_prompt(
                system="你是机器人语义解析器，只输出 JSON，不输出其他内容。",
                user=full,
                temperature=0.1,  # 低温度确保稳定输出
                max_tokens=300,
            )

            if not reply:
                return None

            # 清洗 LLM 输出 (提取 JSON)
            result = self._extract_json(reply)
            if not result:
                log.debug(f"LLM 输出无法解析为 JSON: {reply[:100]}")
                return None

            # 校验必填字段
            if "action" not in result:
                return None

            confidence = result.get("confidence", 0.8)
            intent = result.get("intent", text)
            log.info(f"🧠 语义理解: {text!r} → {result['action']} "
                     f"(置信度={confidence:.0%} 意图={intent})")
            return result

        except Exception as e:
            log.warning(f"LLM 语义解析失败，降级关键词: {e}")
            return None

    # ------------------------------------------------------------------
    # JSON 提取
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_json(text: str) -> Optional[dict]:
        """从 LLM 输出中提取 JSON 对象"""
        text = text.strip()
        # 去掉 markdown 代码块
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:]) if len(lines) > 1 else text
            if text.endswith("```"):
                text = text[:-3]
        # 找到 JSON 边界
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        return None

    # ------------------------------------------------------------------
    # 关键词降级 (离线可用)
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_keyword(text: str) -> Optional[dict]:
        """传统关键词匹配 (LLM 不可用时的降级方案)"""
        # 复用现有的 VoiceCommandParser
        try:
            from voice_command import VoiceCommandParser
            parser = VoiceCommandParser()
            cmd = parser.parse(text)
            if cmd:
                cmd["confidence"] = 0.7
                cmd["source"] = "keyword"
                log.info(f"📋 关键词匹配: {text!r} → {cmd['action']}")
                return cmd
        except ImportError:
            pass
        return None

    # ------------------------------------------------------------------
    # 上下文管理
    # ------------------------------------------------------------------
    def _update_context(self, cmd: dict):
        """更新上下文和对话历史"""
        action = cmd.get("action", "")
        self._context["last_action"] = action

        if action == "navigate":
            self._context["last_target"] = cmd.get("target")
        elif action == "patrol":
            self._context["last_mode"] = cmd.get("mode")

        # 记录对话历史 (最近10轮)
        self._history.append({
            "role": "user",
            "intent": cmd.get("intent", ""),
            "action": action,
        })
        if len(self._history) > 10:
            self._history = self._history[-10:]

    def add_context(self, key: str, value):
        """手动添加上下文 (如来自视觉检测的结果)"""
        self._context[key] = value

    def clear_history(self):
        """清空对话历史"""
        self._history.clear()
        self._context = {"last_target": None, "last_action": None}

    # ------------------------------------------------------------------
    # 场景理解: 结合视觉检测结果生成语义描述
    # ------------------------------------------------------------------
    def describe_scene(self, detection_info: dict) -> Optional[str]:
        """
        将视觉检测结果转换为自然语言描述 (供 LLM 对话使用)。

        detection_info 格式:
            {"person_count": 2, "has_fall": False, "has_fire": False,
             "head_heights": [1.65, 1.70], "location": "living_room"}
        """
        if not self._llm:
            parts = []
            n = detection_info.get("person_count", 0)
            if n > 0:
                parts.append(f"检测到{n}人")
            if detection_info.get("has_fall"):
                parts.append("⚠️ 有人跌倒")
            if detection_info.get("has_fire"):
                parts.append("🔥 检测到火焰")
            return "，".join(parts) if parts else "未检测到异常"

        prompt = f"""根据以下视觉检测数据，用一句简短自然的中文描述场景:

{json.dumps(detection_info, ensure_ascii=False)}

要求: 20字以内，口语化，适合语音播报。"""

        try:
            reply = self._llm.chat_with_prompt(
                system="你是智能机器人，用简短中文描述视觉场景。",
                user=prompt,
                temperature=0.3,
                max_tokens=80,
            )
            return reply.strip() if reply else None
        except Exception as e:
            log.warning(f"场景描述失败: {e}")
            return None
