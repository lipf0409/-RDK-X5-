#!/usr/bin/env python3
"""
语音指令解析器
==============
将 ASR 识别的中文文本映射为机器人控制指令。

指令类型:
  move     → /cmd_vel Twist (前进/后退/左转/右转/停止)
  navigate → 目标点位导航
  patrol   → 开始/停止巡逻
  query    → 状态查询 (位置/电量)
  speak    → 语音播报请求

使用:
    from voice_command import VoiceCommandParser
    parser = VoiceCommandParser()
    cmd = parser.parse("前进")
    # → {"action": "move", "linear": 0.20, "angular": 0.0, "raw": "前进"}
"""

import json
import logging

log = logging.getLogger("voice_command")


class VoiceCommandParser:
    """语音 → 机器人动作映射"""

    # 指令关键词 → 动作参数
    COMMANDS = {
        # ── 移动指令 → /cmd_vel ──
        "前进":     {"action": "move", "linear": 0.20, "angular": 0.00},
        "往前走":   {"action": "move", "linear": 0.20, "angular": 0.00},
        "直走":     {"action": "move", "linear": 0.20, "angular": 0.00},
        "后退":     {"action": "move", "linear": -0.15, "angular": 0.00},
        "往后":     {"action": "move", "linear": -0.15, "angular": 0.00},
        "左转":     {"action": "move", "linear": 0.00, "angular": 0.50},
        "向左":     {"action": "move", "linear": 0.00, "angular": 0.50},
        "右转":     {"action": "move", "linear": 0.00, "angular": -0.50},
        "向右":     {"action": "move", "linear": 0.00, "angular": -0.50},
        "停":       {"action": "move", "linear": 0.00, "angular": 0.00},
        "停下":     {"action": "move", "linear": 0.00, "angular": 0.00},
        "停止":     {"action": "move", "linear": 0.00, "angular": 0.00},
        "别动":     {"action": "move", "linear": 0.00, "angular": 0.00},

        # 慢速移动
        "慢点前进": {"action": "move", "linear": 0.10, "angular": 0.00},
        "慢慢走":   {"action": "move", "linear": 0.10, "angular": 0.00},
        "快点":     {"action": "move", "linear": 0.35, "angular": 0.00},

        # 原地旋转
        "掉头":     {"action": "move", "linear": 0.00, "angular": 1.00},
        "转一圈":   {"action": "move", "linear": 0.00, "angular": 0.80},
        "转过来":   {"action": "move", "linear": 0.00, "angular": 1.00},

        # ── 巡逻指令 ──
        "开始巡逻": {"action": "patrol", "mode": "start"},
        "启动巡逻": {"action": "patrol", "mode": "start"},
        "开始巡线": {"action": "patrol", "mode": "start"},
        "开始":     {"action": "patrol", "mode": "start"},  # 简短别名
        "停止巡逻": {"action": "patrol", "mode": "stop"},
        "结束巡逻": {"action": "patrol", "mode": "stop"},
        "暂停巡逻": {"action": "patrol", "mode": "pause"},

        # ── 导航指令 → 需要目标点位 ──
        "回充电桩": {"action": "navigate", "target": "dock"},
        "去充电":   {"action": "navigate", "target": "dock"},
        "回去充电": {"action": "navigate", "target": "dock"},
        "回起点":   {"action": "navigate", "target": "origin"},
        "去卧室":   {"action": "navigate", "target": "bedroom"},
        "去客厅":   {"action": "navigate", "target": "living_room"},
        "去厨房":   {"action": "navigate", "target": "kitchen"},
        "去任务点A": {"action": "navigate", "target": "task_a"},
        "去任务点B": {"action": "navigate", "target": "task_b"},
        "去任务点C": {"action": "navigate", "target": "task_c"},

        # ── 查询指令 ──
        "你在哪":   {"action": "query", "type": "position"},
        "你在哪里": {"action": "query", "type": "position"},
        "电量":     {"action": "query", "type": "battery"},
        "还有多少电": {"action": "query", "type": "battery"},
        "状态":     {"action": "query", "type": "status"},
        "检查状态": {"action": "query", "type": "status"},
    }

    # 导航目标点位坐标 (需根据实际地图配置)
    NAV_TARGETS = {
        "dock":       {"x": 0.00, "y": 0.00, "z": 0.00, "w": 1.00},
        "origin":     {"x": 0.00, "y": 0.00, "z": 0.00, "w": 1.00},
        "bedroom":    {"x": 2.00, "y": 1.00, "z": 0.00, "w": 1.00},
        "living_room":{"x": 4.00, "y": 1.00, "z": 0.00, "w": 1.00},
        "kitchen":    {"x": 3.00, "y": 3.00, "z": 0.00, "w": 1.00},
        "task_a":     {"x": 1.05, "y": 0.30, "z": 0.99, "w": 0.12},
        "task_b":     {"x": 1.85, "y": 2.66, "z": -1.0, "w": 0.98},
        "task_c":     {"x": 2.05, "y": 3.23, "z": 0.55, "w": 0.86},
    }

    def parse(self, text: str) -> dict | None:
        """
        解析语音文本，返回标准化指令字典。

        返回格式:
          {"action": str, "raw": str, ...参数}
          或 None (未匹配到指令)

        调用方通过 action 字段决定发布到什么 ROS2 话题:
          - "move"     → geometry_msgs/Twist 到 /cmd_vel
          - "navigate" → 带 target 的 JSON 到 /voice/command
          - "patrol"   → 带 mode 的 JSON 到 /voice/command
          - "query"    → 带 type 的 JSON 到 /voice/command
        """
        text_clean = text.replace(" ", "").replace("，", "").replace("。", "")
        text_lower = text.lower()

        # 1. 精确匹配 (最长优先)
        sorted_cmds = sorted(self.COMMANDS.items(), key=lambda x: -len(x[0]))
        for keyword, cmd in sorted_cmds:
            if keyword in text_clean or keyword in text_lower:
                result = {"raw": text, **cmd}
                log.info(f"Voice cmd: {keyword} → {cmd['action']}")
                return result

        # 2. 模糊匹配: 包含"去"+"地点"的组合
        for place in ["卧室", "客厅", "厨房", "充电桩", "起点"]:
            if ("去" in text_clean or "到" in text_clean) and place in text_clean:
                target = {"卧室": "bedroom", "客厅": "living_room",
                          "厨房": "kitchen", "充电桩": "dock", "起点": "origin"}[place]
                result = {"raw": text, "action": "navigate", "target": target}
                log.info(f"Voice cmd (fuzzy): 去{place} → navigate/{target}")
                return result

        return None

    def get_nav_pose(self, target: str) -> dict | None:
        """获取导航目标位姿。"""
        return self.NAV_TARGETS.get(target)

    def to_json(self, cmd: dict) -> str:
        """将指令字典序列化为 JSON 字符串。"""
        return json.dumps(cmd, ensure_ascii=False)
