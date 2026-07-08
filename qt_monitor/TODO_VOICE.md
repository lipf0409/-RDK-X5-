# TODO: 语音助手 QT 集成剩余工作

## 已完成 ✅

| 模块 | 状态 | 说明 |
|------|------|------|
| `ros_bridge.py` | ✅ | 订阅 `/voice/wakeup`, `/voice/question`, `/voice/answer`；信号+数据缓存 |
| `main.py` | ✅ | `VoiceChatWidget(bridge=...)` 连接 bridge，`_init_ros2` 中 set_bridge |
| `widgets/voice_chat.py` | ✅ | 实时显示唤醒/识别/回复；唤醒状态指示灯；输入框+发送按钮可用 |
| `voice_assistant_node.py` | ✅ | ROS2 节点，发布 `/voice/angle`, `/voice/wakeup`, `/voice/question`, `/voice/answer` |

## 待完成 🔲

### 1. 语音指令解析模块 (新建 `voice_command.py`)

**目的**: 将 ASR 识别的文本映射为机器人控制指令。

需要放在 `voice_assistant/` 目录下（不是 qt_monitor），因为它是后端逻辑。

```python
# voice_assistant/voice_command.py

class VoiceCommandParser:
    """解析语音文本 → 机器人动作"""
    
    COMMANDS = {
        # 导航指令 → 目标点位
        "去卧室":   {"action": "navigate", "target": "bedroom"},
        "去客厅":   {"action": "navigate", "target": "living_room"},
        "去厨房":   {"action": "navigate", "target": "kitchen"},
        "回充电":   {"action": "navigate", "target": "dock"},
        "回桩":     {"action": "navigate", "target": "dock"},
        
        # 移动指令 → /cmd_vel Twist
        "前进":     {"action": "move", "linear": 0.2, "angular": 0},
        "后退":     {"action": "move", "linear": -0.2, "angular": 0},
        "左转":     {"action": "move", "linear": 0, "angular": 0.5},
        "右转":     {"action": "move", "linear": 0, "angular": -0.5},
        "停止":     {"action": "move", "linear": 0, "angular": 0},
        "停":       {"action": "move", "linear": 0, "angular": 0},
        
        # 巡逻指令
        "开始巡逻": {"action": "patrol", "mode": "start"},
        "停止巡逻": {"action": "patrol", "mode": "stop"},
        
        # 查询指令
        "你在哪":   {"action": "query", "type": "position"},
        "电量":     {"action": "query", "type": "battery"},
    }
    
    def parse(self, text: str) -> dict | None:
        """解析文本，返回动作字典或 None"""
        for keyword, cmd in self.COMMANDS.items():
            if keyword in text:
                return {"raw": text, **cmd}
        return None
```

**集成方式**: 在 `voice_assistant_node.py` 的回调中调用 parser，发布到 `/voice/command`。

---

### 2. ROS2 指令发布 (修改 `voice_assistant_node.py`)

在 `voice_assistant_node.py` 中添加：

- **新建 Publisher**: `/voice/command` (String) — 解析后的指令 JSON
- **新建 Publisher**: `/cmd_vel` (Twist) — 移动控制
- **在 `_on_recognition` 回调中**: 调用 `VoiceCommandParser.parse()`，发布指令

```python
from geometry_msgs.msg import Twist
from voice_command import VoiceCommandParser

class VoiceAssistantNode(Node):
    def __init__(self):
        ...
        self._cmd_parser = VoiceCommandParser()
        self._pub_command = self.create_publisher(String, "/voice/command", 10)
        self._pub_cmd_vel = self.create_publisher(Twist, "/cmd_vel", 10)
    
    def _on_recognition(self, text: str):
        # 原有发布
        ...
        # 新增：解析指令并发布
        cmd = self._cmd_parser.parse(text)
        if cmd:
            self._pub_command.publish(String(data=json.dumps(cmd)))
            if cmd["action"] == "move":
                tw = Twist()
                tw.linear.x = cmd["linear"]
                tw.angular.z = cmd["angular"]
                self._pub_cmd_vel.publish(tw)
                self.get_logger().info(f"Voice cmd: {cmd['action']} l={tw.linear.x} a={tw.angular.z}")
```

---

### 3. QT 左导航栏支持 (修改 `left_nav.py` + `main.py`)

**目标**: 点击左侧"语音"按钮切换显示语音面板；默认隐藏语音面板。

当前 `main.py` 把所有面板都显示在主界面上。需要改为：

```
main.py 修改：
  - 语音面板默认隐藏 (self._voice_chat.hide())
  - 连接 left_nav.module_selected 信号
  - 点击"语音"按钮 → 显示/隐藏 VoiceChatWidget
  - 点击其他按钮 → 隐藏 VoiceChatWidget
```

```python
# main.py _init_ros2() 或 __init__() 中
self._left_nav.module_selected.connect(self._on_nav_changed)
self._voice_chat.hide()  # 默认隐藏

def _on_nav_changed(self, module_id):
    if module_id == 'voice':
        self._voice_chat.setVisible(not self._voice_chat.isVisible())
    # 其他模块切换逻辑...
```

---

### 4. QT 接收并显示语音指令 (修改 `voice_chat.py`)

在 `VoiceChatWidget` 中订阅 `/voice/command` 话题，显示指令执行反馈：

```python
# ros_bridge.py 添加
self._voice_command: str = ""
voice_command_updated = Signal(str)

# subscriber
self._node.create_subscription(String, '/voice/command', self._voice_command_callback, 10)

# voice_chat.py 连接
self._bridge.voice_command_updated.connect(self._on_command)
```

---

### 5. 语音播报告警 (修改 `voice_assistant_node.py`)

当 QT monitor 检测到跌倒/火焰告警时，语音助手自动播报。

**方案 A**: QT 发布 `/voice/speak` 话题，voice_assistant_node 订阅后 TTS 播报。

```python
# voice_assistant_node.py 新增
self._sub_speak = self.create_subscription(
    String, '/voice/speak', self._on_speak, 10)

def _on_speak(self, msg):
    """外部请求语音播报 (如告警)"""
    text = msg.data
    asyncio.run(self._speak(text))
```

**方案 B**: QT monitor 直接调用 voice_assistant 的 TTS（需要共享进程或 service）。

推荐方案 A（解耦）。

---

### 6. 语音面板独立窗口模式 (可选)

当前语音面板嵌入在主窗口右下角。可改为独立弹出窗口：

- 在 `main.py` 中可选择 `QDialog` 或 `QDockWidget` 显示语音面板
- 适合 7 寸小屏上单独展示对话

---

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `voice_assistant/voice_command.py` | **新建** | 语音指令解析器 |
| `voice_assistant/voice_assistant_node.py` | 修改 | 添加 `/voice/command`, `/cmd_vel` 发布 + `/voice/speak` 订阅 |
| `voice_assistant/package.xml` | 修改 | 添加 `geometry_msgs` 依赖 |
| `voice_assistant/core/wake_up/serial_wake.py` | 已修改 | 心跳日志 |
| `voice_assistant/core/config_manager.py` | 已修改 | 多路径配置搜索 |
| `qt_monitor/ros_bridge.py` | 已修改 | 添加 voice 订阅和信号 |
| `qt_monitor/main.py` | 已修改 | bridge→voice_chat 连接 |
| `qt_monitor/widgets/voice_chat.py` | 已修改 | 实时对话 + 唤醒指示 |
| `qt_monitor/widgets/left_nav.py` | 可不改 | 已有语音按钮 |

## 实施顺序

```
1. voice_command.py (新建)         → 指令解析
2. voice_assistant_node.py (修改)   → 发布 /voice/command + /cmd_vel
3. 部署测试                          → 说"前进"小车能走
4. QT ros_bridge.py (加 command)    → QT 接收指令
5. QT voice_chat.py (显示指令)      → QT 显示指令执行
6. QT main.py (left_nav切换)       → 语音按钮切换面板
7. voice_assistant_node.py (语音告警) → 跌倒/火焰时语音播报
```

## 验证步骤

1. 启动 voice_assistant ROS2 节点
2. 说"小飞小飞"唤醒
3. 说"前进" → `rostopic echo /cmd_vel` 应看到 linear.x=0.2
4. 说"停止" → `rostopic echo /cmd_vel` 应看到全零
5. 启动 QT monitor → 语音面板应实时显示对话
6. 说话后在 QT 文本输入框键入"去卧室" → 触发导航
