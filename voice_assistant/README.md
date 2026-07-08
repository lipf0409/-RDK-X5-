# M260C 语音唤醒 + 智能对话助手

基于 **iFLYTEK M260C USB 圆形6麦阵列** 的语音唤醒和 AI 对话系统。

支持 **Windows 10/11 (开发)** 和 **Linux / RDK X5 (部署)**。

## 功能流程

```
[唤醒] 说"小飞小飞" → VAD 检测 → 录音 → 讯飞 ASR → 唤醒词匹配
    ↓
[对话] 听到"叮" → 说出问题 → 录音 → 讯飞 ASR → 文本
    ↓
[回复] 文本 → DeepSeek LLM → 智能回复 → Edge TTS / espeak → M260C 扬声器
```

## 项目结构

```
voice_assistant/
├── core/                          # 核心共享模块
│   ├── config_manager.py         # 统一配置 (YAML + ENV + CLI)
│   ├── audio_device.py           # 麦克风/扬声器自动发现
│   ├── audio_recorder.py         # 录音器 (VAD + 静音检测 + 增益)
│   ├── audio_player.py           # 播放器 (aplay/ffmpeg 多后端)
│   ├── asr_client.py             # 语音识别 (讯飞 WebSocket)
│   ├── llm_client.py             # 大模型对话 (DeepSeek/Ollama)
│   ├── tts_client.py             # 语音合成 (Edge → espeak 自动回退)
│   └── wake_up/                  # 唤醒后端
│       ├── serial_wake.py        # 串口硬件唤醒 (二进制协议 0xA5 0x01)
│       ├── audio_wake.py         # 音频软件唤醒 (VAD + ASR)
│       └── wake_manager.py       # 编排器 (auto/serial/audio)
│
├── voice_assistant.py            # 主入口 (命令行)
├── voice_assistant_node.py       # ROS2 节点
├── voice_assistant_audio.py      # (废弃) 旧版纯音频模式
│
├── launch/
│   └── voice_assistant.launch.py # ROS2 launch 文件
├── package.xml                   # ROS2 包定义
├── setup.py / setup.cfg          # ROS2 安装配置
├── config.yaml                   # 配置文件
├── requirements_voice.txt        # Python 依赖
│
├── aiui_sdk/                     # 讯飞 AIUI SDK 配置 (Linux 硬件唤醒用)
│   ├── aiui.cfg
│   └── assets/vtn/
│
├── audio_resources/              # 预录制音频 (离线回退)
│
├── tools/
│   ├── list_devices.py           # 列出音频+串口设备
│   └── test_wakeup.py            # 唤醒连通性测试
│
├── test_iflytek.py               # 讯飞 ASR 回归测试
└── test_pipeline.py              # 完整链路测试 (键盘触发)
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements_voice.txt
sudo apt-get install -y ffmpeg espeak-ng portaudio19-dev  # Linux 额外依赖
```

### 2. 检查设备

```bash
# 列出音频设备和串口
python tools/list_devices.py
python voice_assistant.py --list-audio
python voice_assistant.py --list-serial
```

### 3. 配置

编辑 `config.yaml`:

```yaml
serial:
  port: "/dev/ttyUSB0"      # Windows: COM11; Linux: /dev/ttyUSB0

wake_backend:
  mode: "audio"             # audio(默认) | serial(AIUI SDK) | auto

asr:
  backend: "iflytek"        # 讯飞免费 500次/天

llm:
  backend: "openai"
  openai:
    base_url: "https://api.deepseek.com"
    model: "deepseek-chat"
    api_key: "sk-your-key"

tts:
  backend: "edge"           # Edge(免费云端) | pyttsx3(离线)
```

### 4. 运行

```bash
# 命令行模式
python voice_assistant.py

# 指定配置
python voice_assistant.py --wake audio           # 仅音频唤醒
python voice_assistant.py --wake serial          # 仅串口唤醒
python voice_assistant.py --debug --save-audio   # 调试模式

# 连通性测试
python tools/test_wakeup.py
```

## 唤醒模式

| 模式 | 原理 | 延迟 | 硬件要求 | 适用平台 |
|------|------|------|----------|----------|
| `audio` | VAD + 讯飞 ASR 唤醒词匹配 | ~3s | 任意麦克风 | Windows + Linux |
| `serial` | M260C DSP 硬件唤醒 | ~0.1s | M260C + AIUI SDK | Linux only |
| `auto` | 串口优先 → 音频回退 | ~0.1s 或 ~3s | M260C | Linux only |

## ROS2 集成

### 部署

```bash
# 链接到 ROS2 工作空间
ln -s /home/sunrise/ucar_01/voice_assistant /home/sunrise/ucar_01/src/voice_assistant

# 编译
cd /home/sunrise/ucar_01
colcon build --packages-select voice_assistant
source install/setup.bash
```

### 启动

```bash
# 单独启动
ros2 launch voice_assistant voice_assistant.launch.py

# 与导航一起启动
ros2 launch voice_assistant voice_assistant.launch.py &
ros2 launch ucar_nav ucar_navigation.launch.py &
```

### 发布话题

| 话题 | 类型 | 说明 |
|------|------|------|
| `/voice/angle` | `std_msgs/Int32` | 唤醒声源角度 (0-360°) |
| `/voice/wakeup` | `std_msgs/String` | 唤醒事件 JSON |
| `/voice/question` | `std_msgs/String` | ASR 识别文本 |
| `/voice/answer` | `std_msgs/String` | AI 回复文本 |

### 订阅者示例

其他 ROS2 节点可订阅话题获取语音信息：

```python
import rclpy
from rclpy.node import Node
from std_msgs.msg import Int32, String

class MyNode(Node):
    def __init__(self):
        super().__init__("my_node")
        self.sub = self.create_subscription(Int32, "/voice/angle", self.on_angle, 10)

    def on_angle(self, msg):
        self.get_logger().info(f"Wake angle: {msg.data}")
```

## LLM 后端

| 后端 | 配置 | 价格 | 中文质量 |
|------|------|------|----------|
| **DeepSeek** | `base_url: https://api.deepseek.com` | ¥1/百万token | ⭐⭐⭐⭐⭐ |
| **Ollama** | 本地安装 `ollama pull qwen2:1.5b` | 免费 | ⭐⭐⭐ |
| **OpenAI** | `base_url: https://api.openai.com/v1` | 按量付费 | ⭐⭐⭐⭐ |

## TTS 后端

| 后端 | 配置 | 特点 |
|------|------|------|
| **edge** | 免费云端 | 中文自然，需翻墙 |
| **pyttsx3** | 本地 espeak | 离线可用，中文略生硬 |

Edge TTS 不可用时自动回退到 espeak。

## ASR 后端

| 后端 | 配置 | 免费额度 |
|------|------|----------|
| **iflytek** | 讯飞 WebSocket | 500次/天 |
| **whisper_api** | OpenAI Whisper | 按量付费 |

## M260C 设备信息

| 接口 | 设备 | 说明 |
|------|------|------|
| 麦克风 | `XFM-DP-V0.0.18 USB Audio (hw:1,0)` | 16000Hz 原生 |
| 扬声器 | `USB Audio Device (hw:0,0)` | 44100Hz |
| 串口 | `/dev/ttyUSB0` (CH9102) | 115200 baud, 8N1 |

串口使用二进制帧协议: `0xA5 0x01` 头 + 7字节帧头 + JSON内容 + CRC校验。

## M260C 串口协议

```
帧格式:
  Byte 0:    0xA5 (同步头)
  Byte 1:    0x01 (UID)
  Byte 2:    消息类型 (0x01=CONFIRM, 0x04=AIUI_MSG)
  Byte 3-4:  内容长度 (小端序 uint16)
  Byte 5-6:  会话 ID (小端序 uint16)
  Byte 7..:  内容 (JSON)
  最后字节:  CRC = (~sum + 1) & 0xFF

唤醒事件 JSON:
  {"type":"aiui_event","content":{"eventType":4,"info":"{\"ivw\":{\"keyword\":\"xiao3 fei1 xiao3 fei1\",\"score\":901,\"beam\":4,\"angle\":242}}"}}
```

## 故障排除

| 现象 | 原因 | 解决 |
|------|------|------|
| 找不到麦克风 | M260C 未连接 | `python tools/list_devices.py` |
| VAD 不触发 | 阈值不匹配 | 调整 `audio.silence_threshold` (M260C推荐500) |
| ASR 无结果 | 录音质量差 | 调高增益或靠近麦克风 |
| 播放无声音 | 设备选错 | `--list-audio` 确认扬声器 |
| Edge TTS 失败 | SSL 被墙 | 自动回退 espeak |
| 串口连接失败 | 权限不足 | `sudo usermod -aG dialout $USER` |
| ALSA xrun | 缓冲区过小 | 已自动使用 2048 帧缓冲 |
