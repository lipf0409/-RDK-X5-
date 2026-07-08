# 基于 RDK X5 的智能跌倒监护机器人系统

> 🏆 家庭智能监护机器人 — 双目视觉 + 激光 SLAM + 语音交互 + 声光报警  
> 🎓 毕业设计 / 竞赛作品  
> 📅 2026-07

---

## 📋 目录

- [作品概述](#作品概述)
- [硬件配置](#硬件配置)
- [系统架构](#系统架构)
- [项目结构](#项目结构)
- [功能模块](#功能模块)
- [快速开始](#快速开始)
- [视觉监护系统](#视觉监护系统)
- [SLAM 建图与导航](#slam-建图与导航)
- [语音助手](#语音助手)
- [桌面监控界面](#桌面监控界面)
- [Web 仪表盘](#web-仪表盘)
- [一键启动脚本](#一键启动脚本)
- [故障排查](#故障排查)
- [技术亮点](#技术亮点)

---

## 作品概述

本系统基于**地平线 RDK X5（旭日X5）**工控机，搭载 ROS2 Humble + TROS 平台，集成**双目视觉跌倒检测**、**激光 SLAM 自主导航**、**语音交互**与**声光报警**等功能，构建了一套完整的家庭智能监护机器人系统。

### 核心功能

| 功能 | 描述 | 状态 |
|------|------|:----:|
| 🧍 人体检测 | 深度图背景差分，空场景零误报，<1ms 推理 | ✅ |
| 🚨 跌倒检测 | 深度感知头部查找 + 高度追踪 + 多条件融合判决 | ✅ |
| 🔥 火焰检测 | HSV 颜色空间火焰识别 | ✅ |
| 🗺️ SLAM 建图 | slam_toolbox 在线建图，支持回环检测 | ✅ |
| 🧭 自主导航 | Nav2 路径规划 + 避障导航 | ✅ |
| 🔊 声光报警 | 讯飞 M260C 警笛 + GPIO LED 闪烁 + 自动拍照存证 | ✅ |
| 🎤 语音交互 | 讯飞 ASR/TTS + DeepSeek 大模型语义理解 | ✅ |
| 📊 桌面监控 | Qt PySide6 专业监控界面，多视图实时可视化 | ✅ |
| 🌐 Web 仪表盘 | Flask Web 实时监控画面，浏览器访问 | ✅ |

---

## 硬件配置

| 组件 | 型号 | 接口 | 设备名 |
|------|------|------|--------|
| 工控机 | **RDK X5 (旭日X5)** | - | Ubuntu 22.04 + ROS2 Humble + TROS |
| 双目摄像头 | RDK Stereo Camera (SC230AI) | MIPI CSI | `/dev/video*` |
| 激光雷达 | RPLidar A2M6 | USB 串口 (CP210x: `10c4:ea60`) | `/dev/rplidar` |
| 电机驱动 | JGB520 4轮差速 | 硬件串口 | `/dev/ttyS1` |
| USB 音频 | 讯飞 M260C 麦克风阵列 | USB | ALSA 声卡 |
| 报警 LED | 红色 LED + 220Ω | GPIO23 | 灯光报警 |
| 编码器 | 霍尔编码器 11 线 | 通过电机驱动板读取 | - |
| 轮径 | 67mm | - | - |
| 轮距 | 0.25m | - | - |

---

## 系统架构

```
┌──────────────────────────────────────────────────────────────────┐
│                         RDK X5 (旭日X5)                          │
│                                                                  │
│  ┌──────────────────┐  ┌───────────────┐  ┌──────────────────┐  │
│  │ MIPI 双目摄像头   │  │  BPU (NPU)    │  │  JGB520 电机驱动  │  │
│  │ SC230AI          │  │  StereoNet    │  │  + 霍尔编码器     │  │
│  │ RGB + Depth      │  │  深度推理      │  │  4轮差速底盘      │  │
│  └────────┬─────────┘  └───────┬───────┘  └────────┬─────────┘  │
│           │                    │                    │            │
│  ┌────────▼────────────────────▼────────────────────▼─────────┐  │
│  │                      ROS2 数据总线 (Humble)                  │  │
│  │                                                             │  │
│  │  /image_combine_raw      /stereonet_compresseddepth         │  │
│  │  /rectified_image        /scan (激光雷达)                   │  │
│  │  /person_detections      /odom (里程计)                     │  │
│  │  /fall_alert             /cmd_vel (速度控制)                │  │
│  │  /fire_alert             /map (SLAM 地图)                   │  │
│  └─────────────────────────────────────────────────────────────┘  │
│           │              │              │                         │
│  ┌────────▼───┐  ┌───────▼──────┐  ┌───▼──────────────┐        │
│  │ 视觉监护    │  │ 报警控制器   │  │ SLAM / Nav2       │        │
│  │            │  │              │  │                   │        │
│  │ ·背景差分  │──▶│ ·USB 音频报警│  │ ·激光建图         │        │
│  │ ·头部追踪  │  │ ·GPIO LED   │  │ ·路径规划         │        │
│  │ ·跌倒判决  │  │ ·自动停车   │  │ ·自主导航         │        │
│  │ ·火焰检测  │  │ ·拍照存证   │  │ ·避障绕行         │        │
│  └────────────┘  └──────────────┘  └───────────────────┘        │
│                                                                  │
│  ┌─────────────────────┐  ┌────────────────────┐                │
│  │ 语音助手             │  │ 监控界面            │                │
│  │ ·讯飞 ASR 语音识别   │  │ ·Qt 桌面端 (PySide6)│                │
│  │ ·DeepSeek 语义理解   │  │ ·Web 仪表盘 (Flask) │                │
│  │ ·讯飞 TTS 语音合成   │  │ ·Foxglove 可视化    │                │
│  └─────────────────────┘  └────────────────────┘                │
└──────────────────────────────────────────────────────────────────┘
```

### 数据流

```
双目相机 ──→ RGB ──→ StereoNet(BPU) ──→ 深度图 ──→ 人体检测
                │                                      │
                └──→ 校正图像 ──────────────────→ vision_monitor
                                                       │
                                          ┌────────────┤
                                          ▼            ▼
                                     跌倒判决      火焰检测
                                          │            │
                                          └─────┬──────┘
                                                ▼
                                         alarm_controller
                                         ├── USB 音频报警
                                         ├── GPIO LED 闪烁
                                         ├── 电机停车
                                         └── 拍照存证
```

---

## 项目结构

```
ucar_01/
├── src/
│   ├── jgb520_driver/                  # 电机驱动 + SLAM + Nav2 配置
│   │   ├── jgb520_driver/
│   │   │   ├── motor_driver.py         # 核心电机驱动节点 (PID 控制)
│   │   │   └── scan_fixer.py           # 雷达点数修正
│   │   ├── launch/
│   │   │   ├── robot_bringup.launch.py # 基础启动 (电机 + 雷达)
│   │   │   ├── slam.launch.py          # SLAM 建图
│   │   │   └── navigation.launch.py    # Nav2 导航
│   │   ├── config/
│   │   │   ├── slam.yaml               # slam_toolbox 参数
│   │   │   └── navigation.yaml         # Nav2 导航参数
│   │   ├── setup.py
│   │   └── package.xml
│   │
│   ├── rplidar_ros-ros/                # RPLidar ROS2 SDK (C++)
│   │   ├── src/rplidar_node.cpp        # 雷达驱动节点
│   │   ├── sdk/                        # RPLidar 官方 SDK
│   │   ├── launch/                     # 启动文件
│   │   └── rviz/                       # RViz 配置
│   │
│   └── ucar_vision/                    # ★ 视觉监护系统
│       ├── ucar_vision/
│       │   ├── vision_monitor.py       # 跌倒检测核心
│       │   ├── alarm_controller.py     # 声光报警控制器
│       │   └── person_detector.py      # 深度人体检测
│       ├── launch/
│       │   ├── vision_bringup.launch.py
│       │   └── vision_patrol.launch.py # 巡逻模式
│       ├── config/
│       │   └── vision_params.yaml      # 视觉参数配置
│       ├── setup.py
│       └── package.xml
│
├── board_person_detector_node.py       # 人体检测 ROS2 节点
├── depth_person_detector.py            # 背景差分算法核心
│
├── qt_monitor/                         # ★ Qt 桌面监控界面
│   ├── main.py                         # 生产环境入口 (ROS2)
│   ├── run_mock.py                     # Windows 离线测试
│   ├── mock_bridge.py                  # 模拟数据源
│   ├── ros_bridge.py                   # ROS2 桥接层
│   ├── widgets/                        # UI 组件库
│   │   ├── left_nav.py                 # 左侧导航栏
│   │   ├── status_bar.py               # 顶部报警指示灯
│   │   ├── rgb_view.py                 # RGB 实时画面
│   │   ├── depth_view.py               # 伪彩色深度图
│   │   ├── slam_view.py                # 激光 SLAM 2D 热力图
│   │   ├── system_panel.py             # 硬件状态 + 底盘控制
│   │   ├── log_panel.py                # 底部彩色日志
│   │   ├── alarm_panel.py              # 报警面板
│   │   └── voice_chat.py               # 语音对话面板
│   ├── styles/theme.qss                # QSS 主题
│   └── start_qt.sh                     # 自启动脚本
│
├── voice_assistant/                    # ★ 语音助手
│   ├── voice_assistant.py              # 主逻辑
│   ├── voice_assistant_node.py         # ROS2 节点
│   ├── voice_command.py                # 语音指令处理
│   ├── core/
│   │   ├── asr_client.py               # 讯飞 ASR 语音识别
│   │   ├── tts_client.py               # 讯飞 TTS 语音合成
│   │   ├── llm_client.py               # DeepSeek 大模型
│   │   ├── semantic_parser.py          # 语义理解模块
│   │   ├── config_manager.py           # 配置管理
│   │   ├── audio_player.py             # 音频播放
│   │   ├── audio_recorder.py           # 音频录制
│   │   ├── audio_device.py             # 音频设备管理
│   │   └── wake_up/                    # 语音唤醒模块
│   │       ├── wake_manager.py         # 唤醒管理
│   │       ├── audio_wake.py           # 音频唤醒
│   │       └── serial_wake.py          # 串口唤醒
│   ├── aiui_sdk/                       # 讯飞 AIUI SDK
│   ├── audio_resources/                # 音频资源文件
│   ├── launch/                         # 启动文件
│   └── config.yaml.example             # 配置示例
│
├── web_dashboard/                      # ★ Web 实时仪表盘
│   ├── web_server.py                   # Flask 服务器
│   └── templates/index.html            # 仪表盘页面
│
├── docs/
│   ├── 视觉监护系统技术文档.md          # 视觉系统详细文档
│   └── 部署清单.md                      # 部署步骤清单
│
├── scripts/                            # 辅助脚本
├── start_all.sh                        # 一键启动 (6 节点)
├── start_all_slam.sh                   # 一键启动 (8 节点, 含 SLAM)
├── ucar_nodes.service                  # systemd 开机自启
├── gen_project_intro.py                # 项目策划书生成
├── slam.md                             # SLAM 使用说明
├── README.md                           # 英文/详细说明
└── README_CN.md                        # 中文说明 (本文件)
```

---

## 功能模块

### 1. 视觉监护系统 (`src/ucar_vision/`)

基于双目深度视觉的跌倒检测与火焰检测系统。

**核心算法：**
- **人体检测**：深度图背景差分算法，启动后自动建立背景模型，不受光照影响，<1ms 推理
- **跌倒检测**：3D 反投影 + 头部高度追踪 + 卡尔曼滤波 + 多条件融合（高度 <0.45m 持续 >1.2s）
- **火焰检测**：HSV 颜色空间火焰区域识别

**关键参数：**

| 参数 | 值 | 说明 |
|------|-----|------|
| 摄像头高度 | 0.20m | 实际离地约 15~20cm |
| 摄像头倾角 | -2° | 实测下倾约 2° |
| 相机内参 fx=fy | 469.2 | 来自 StereNet camera_info |
| 跌倒高度阈值 | 0.45m | 头部低于此高度判定跌倒 |
| 跌倒持续阈值 | 1.2s | 持续超过此时间触发报警 |

### 2. 底盘驱动与导航 (`src/jgb520_driver/`)

JGB520 4 轮差速底盘驱动，集成 SLAM 与自主导航。

**TF 坐标树：**
```
odom → base_link → laser
```
- `base_link → laser`: 雷达在车体前方 0.15m，上方 0.1m

**电机参数：**

| 参数 | 值 | 说明 |
|------|-----|------|
| 电机类型 | 520 电机 | 减速比 1:30 |
| 编码器 | 11 线霍尔 | 4 倍频 = 44 CPR |
| 轮径 | 67mm | - |
| PID | 1.5, 0.12, 0.5 | P, I, D 参数 |

### 3. 语音助手 (`voice_assistant/`)

基于讯飞 + DeepSeek 的智能语音交互系统。

**功能链：**
```
语音唤醒 ("小飞小飞")
    → 讯飞 ASR 语音识别
    → DeepSeek 大模型语义理解
    → 指令执行 (检查状态/控制移动/问答)
    → 讯飞 TTS 语音合成播报
```

### 4. Qt 桌面监控界面 (`qt_monitor/`)

专业 PySide6 桌面监控界面，实时可视化所有传感器数据。

```
+--------+------------------------------------------+
| NAVBAR | Status: [Normal] [Fall Alert] [Fire Alert]|
| NAV    +-------------------+----------------------+
| VIS    |                   |                      |
| FALL   |  RGB Camera       |  Depth Map           |
| FIRE   |  (rectified_image)|  (pseudo-color)      |
| VOICE  +-------------------+----------------------+
|        |                   |  System Status       |
| CFG    |  SLAM / LIDAR     |  - Hardware: OK      |
|        |  (scan + map)     |  - Params + D-Pad    |
+--------+-------------------+----------------------+
|                Event Log (color-coded)              |
+---------------------------------------------------+
```

### 5. Web 仪表盘 (`web_dashboard/`)

基于 Flask 的 Web 实时监控页面，浏览器访问 `http://<rdk_ip>:8080`。

---

## 快速开始

### 环境要求

- **硬件**：RDK X5 (旭日X5)
- **系统**：Ubuntu 22.04
- **平台**：ROS2 Humble + TROS (地平线 TogetherROS)
- **Python**：3.10+

### 1. 硬件检查

```bash
# 查看串口设备
ls -l /dev/ttyS1 /dev/rplidar

# 查看内核日志
dmesg | tail -30

# 创建 udev 规则 (持久化设备名)
sudo tee /etc/udev/rules.d/99-robot-serial.rules << 'EOF'
KERNEL=="ttyUSB*", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", MODE="0666", SYMLINK+="rplidar"
EOF

sudo udevadm control --reload-rules
sudo udevadm trigger
ls -l /dev/rplidar
```

### 2. 安装依赖

```bash
# ROS2 依赖
sudo apt update
sudo apt install ros-humble-slam-toolbox ros-humble-navigation2 \
    ros-humble-nav2-bringup ros-humble-teleop-twist-keyboard \
    ros-humble-foxglove-bridge ros-humble-vision-msgs

# Python 依赖
pip install pyserial numpy opencv-python PySide6 flask
```

### 3. 编译

```bash
cd ~/ucar_01
source /opt/tros/humble/setup.bash

# 编译所有包
colcon build

# 或选择性编译
colcon build --packages-select jgb520_driver rplidar_ros ucar_vision voice_assistant

source install/setup.bash
```

### 4. 一键启动

```bash
# 基础模式 (6 节点：摄像头 + 深度 + 人体检测 + 跌倒 + 报警 + 语音)
./start_all.sh

# SLAM 模式 (8 节点：基础上 + 电机雷达 + SLAM)
./start_all_slam.sh
```

---

## 视觉监护系统

### 启动序列 (5 个终端)

```bash
# ═══ 终端1: MIPI 双目摄像头 ═══
source /opt/tros/humble/setup.bash
renice -n -10 -p $$ 2>/dev/null
taskset -c 0,1 ros2 launch mipi_cam mipi_cam_dual_channel.launch.py

# ═══ 终端2: 双目深度处理 (BPU) ═══
source /opt/tros/humble/setup.bash
taskset -c 2,3 ros2 launch hobot_stereonet stereonet_model.launch.py \
    stereo_image_topic:=/image_combine_raw \
    stereo_combine_mode:=1 need_rectify:=True alpha:=1

# ═══ 终端3: 人体检测 ═══
# ★ 启动时确保空场景, 等 2 秒背景建立完成
source /opt/tros/humble/setup.bash
source ~/ucar_01/install/setup.bash
cd ~/ucar_01
python3 board_person_detector_node.py --ros-args \
    -p camera_height:=0.20 -p bg_diff_threshold:=200 -p bg_init_frames:=10

# ═══ 终端4: 跌倒检测 ═══
source /opt/tros/humble/setup.bash
source ~/ucar_01/install/setup.bash
taskset -c 4,5 ros2 run ucar_vision vision_monitor --ros-args \
    --params-file ~/ucar_01/src/ucar_vision/config/vision_params.yaml

# ═══ 终端5: 报警控制器 ═══
source /opt/tros/humble/setup.bash
source ~/ucar_01/install/setup.bash
ros2 run ucar_vision alarm_controller --ros-args \
    --params-file ~/ucar_01/src/ucar_vision/config/vision_params.yaml \
    -p sim_mode:=true
```

### 人体检测算法：深度图背景差分

```
启动后前 bg_init_frames(10) 帧建立背景模型
之后每帧 |当前深度 - 背景深度| > 200mm → 前景(人)
背景慢速更新 (alpha=0.003), 不受光照影响
纯 numpy 实现，<1ms 推理
```

### 话题速查

| 话题 | 类型 | 说明 |
|------|------|------|
| `/image_combine_raw` | `Image` (NV12 1280×1440) | 左右拼接图 → StereNet |
| `/StereoNetNode/stereonet_compresseddepth` | `CompressedImage` (PNG) | ★ 实际深度数据 (352×640 uint16) |
| `/StereoNetNode/rectified_image` | `Image` | 校正后 RGB |
| `/StereoNetNode/camera_info` | `CameraInfo` | 校正后内参 |
| `/person_detections` | 自定义 | 人体检测框 |
| `/person_head_height` | `Float32` | 头部高度 (m) |
| `/fall_alert` | `Bool` | 跌倒报警 |
| `/fire_alert` | `Bool` | 火焰报警 |
| `/monitor_status` | `String` | 监控状态 |

### 手工测试

```bash
# 手动触发跌倒报警
ros2 topic pub /fall_alert std_msgs/msg/Bool "data: true" --once

# 手动触发火焰报警
ros2 topic pub /fire_alert std_msgs/msg/Bool "data: true" --once
```

---

## SLAM 建图与导航

### SLAM 建图

```bash
# 启动 SLAM
ros2 launch jgb520_driver slam.launch.py

# Foxglove 可视化 (RDK X5 推荐，替代 RViz)
ros2 launch foxglove_bridge foxglove_bridge_launch.xml port:=8765
# PC 端连接: ws://<机器人IP>:8765

# 键盘控制建图 (低速推荐)
ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -p speed:=0.15 -p turn:=0.4

# 保存地图
ros2 run nav2_map_server map_saver_cli -f ~/maps/my_map
```

### 建图技巧

1. **原地 360° 旋转** — 建立初始地图
2. **沿墙慢速行驶** — 覆盖所有区域
3. **走闭环** — 回到起点让 SLAM 自动优化（回环检测）
4. **速度要慢** — 推荐 0.10~0.20 m/s

### Nav2 导航

```bash
ros2 launch jgb520_driver navigation.launch.py map:=/home/sunrise/maps/my_map.yaml
```

在 Foxglove 中：
1. 点击 **"2D Pose Estimate"** 设置初始位置
2. 点击 **"Nav2 Goal"** 设置目标点
3. 机器人自动规划路径并导航

---

## 语音助手

### 配置

复制并编辑配置文件：

```bash
cp voice_assistant/config.yaml.example voice_assistant/config.yaml
```

配置内容：

```yaml
# 讯飞 ASR/TTS
asr.iflytek.app_id: "YOUR_APP_ID"
asr.iflytek.api_key: "YOUR_API_KEY"
asr.iflytek.api_secret: "YOUR_API_SECRET"

# DeepSeek 大模型
llm.openai.api_key: "YOUR_DEEPSEEK_KEY"
llm.openai.base_url: "https://api.deepseek.com"

# 唤醒模式
wake_backend.mode: "audio"              # VAD + ASR 唤醒

# TTS 引擎
tts.backend: "iflytek"                  # 讯飞 TTS
```

### 启动

```bash
ros2 launch voice_assistant voice_assistant.launch.py
```

### 语音指令示例

| 指令 | 功能 |
|------|------|
| "小飞小飞" | 语音唤醒 |
| "检查一下" | 查看当前监护状态 |
| "往前走" / "后退" | 控制机器人移动 |
| "转一圈看看" | 原地旋转巡视 |
| "有什么异常吗" | 查询报警记录 |

---

## 桌面监控界面

### Windows 离线测试

```bash
pip install PySide6 numpy opencv-python
python qt_monitor/run_mock.py
```

快捷键：
- `F` — 手动触发跌倒报警
- `G` — 手动触发火焰报警
- `R` — 重置报警状态

### RDK X5 生产环境

```bash
pip install PySide6 numpy opencv-python
python3 qt_monitor/main.py
```

### 功能模块详解

| 模块 | 数据源 | 功能 |
|------|--------|------|
| **LIDAR/SLAM 视图** | `/scan` + `/map` | Foxglove 风格 2D 激光点云 + 占据栅格热力图 |
| **RGB 画面** | `/StereoNetNode/rectified_image` | 实时彩色画面 + 人体追踪框 + 头部高度数值 |
| **深度图** | `/StereoNetNode/stereonet_compresseddepth` | PNG 解码 → 伪彩色映射 + 人物轮廓叠加 |
| **报警指示灯** | `/fall_alert` + `/fire_alert` | 三色灯，报警时红灯闪烁 |
| **系统状态** | 综合 | 雷达/摄像头/电机连接状态、内参、帧率 |
| **事件日志** | 综合 | 彩色日志 (灰=普通, 橙=检测, 红=报警) |

---

## Web 仪表盘

浏览器访问 `http://<rdk_ip>:8080`，实时查看：
- RGB 双目相机画面 (MJPEG)
- 深度图 (伪彩色)
- 人体检测状态
- 语音对话状态
- 告警指示灯

```bash
cd ~/ucar_01
python3 web_dashboard/web_server.py
```

---

## 一键启动脚本

### start_all.sh (6 节点)

```bash
./start_all.sh
```

启动节点：
1. MIPI 双目摄像头
2. StereoNet 深度处理 (BPU)
3. 人体检测 (背景差分)
4. 跌倒检测
5. 报警控制器
6. 语音助手

### start_all_slam.sh (8 节点)

```bash
./start_all_slam.sh
```

在 6 节点基础上增加：
7. 电机 + 激光雷达
8. SLAM 建图

### 开机自启

```bash
sudo cp ucar_nodes.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ucar_nodes.service
```

---

## 运行命令速查

```bash
# 基础启动
ros2 launch jgb520_driver robot_bringup.launch.py

# SLAM 建图
ros2 launch jgb520_driver slam.launch.py

# Nav2 导航
ros2 launch jgb520_driver navigation.launch.py map:=/home/sunrise/maps/my_map.yaml

# Foxglove Bridge
ros2 launch foxglove_bridge foxglove_bridge_launch.xml port:=8765

# 键盘控制
ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -p speed:=0.15 -p turn:=0.4

# 查看话题
ros2 topic list
ros2 topic echo /odom --once
ros2 topic hz /scan

# 查看 TF 树
ros2 run tf2_tools view_frames

# 查看参数
ros2 param get /rplidar_node serial_port
ros2 param get /jgb520_driver serial_port
```

---

## 故障排查

### 视觉系统

| 现象 | 原因 | 解决 |
|------|------|------|
| `Has_depth:False` | hobot_shm 环境变量未清除 | `unset RMW_FASTRTPS_USE_QOS_FROM_XML` |
| Python 收不到深度 | 共享内存零拷贝不兼容 Python | Python 节点不设 shm |
| `stereonet_depth` 空 | 深度只发 compresseddepth | 改用 `/stereonet_compresseddepth` |
| `grab failed` | DDS 抢 VIN DMA | taskset CPU 隔离 |
| `Has_det:False` | 检测节点未启动或人在范围外 | 确认在 1-3m 范围内 |

### SLAM / 导航

| 现象 | 原因 | 解决 |
|------|------|------|
| 地图不更新 | `minimum_travel_distance` 太大 | slam.yaml 设为 0.01 |
| TF 停车漂移 | 编码器数据过期 | 确认驱动有时间戳检查 |
| 建图重影 | 速度太快 / 里程计不准 | 降到 0.15 m/s，标定轮径 |
| Nav2 无法定位 | 初始位姿不对 | Foxglove 设置 2D Pose Estimate |

### 语音

| 现象 | 原因 | 解决 |
|------|------|------|
| M260C 没声音 | 设备名不对 | `aplay -l` 查看，试 `plughw:1,0` |
| ASR 无响应 | API 凭证错误 | 检查 config.yaml 讯飞凭证 |
| 语义理解失败 | DeepSeek API 不可达 | 检查网络 + API Key |

---

## 技术亮点

### 🧠 算法创新

1. **深度图背景差分人体检测**：不受光照影响，空场景零误报，<1ms 纯 numpy 实现
2. **3D 反投影头部追踪**：利用双目深度相机内参，将 2D 检测框反投影到 3D 空间，追踪头部高度变化
3. **多条件融合跌倒判决**：头部高度 + 宽高比变化 + 持续时间，三重条件共同决策
4. **卡尔曼滤波平滑**：对头部高度时序数据做卡尔曼滤波，消除深度噪声抖动

### ⚡ 工程优化

1. **CPU 核心隔离 (taskset)**：MIPI 摄像头、BPU 推理、视觉处理分别绑定不同 CPU 核心
2. **共享内存避开**：Python 节点不启用 hobot_shm，避免零拷贝兼容问题
3. **NV12 手动解码**：绕过 cv_bridge 限制，内置 NV12→BGR 转换
4. **深度 PNG 解码**：从 CompressedImage 中解码 16 位深度图

### 🎨 交互设计

1. **多终端监控**：Qt 桌面端 + Web 仪表盘 + Foxglove，三种可视化方案
2. **语音自然交互**：唤醒词 + ASR + 大模型语义理解 + TTS 播报，端到端语音对话
3. **声光联动报警**：跌倒触发 → 警笛响 + LED 闪 + 自动停车 + 拍照存证

### 📐 系统架构

1. **模块化 ROS2 节点**：视觉、报警、语音、底盘各自独立节点，松耦合
2. **一键启动脚本**：6/8 节点并行启动，日志分离
3. **systemd 开机自启**：上电自动运行，无需人工干预

---

## 踩坑记录

| 坑 | 症状 | 根因 | 解决 |
|----|------|------|------|
| hobot_shm + rclpy | `Has_depth:False` | 共享内存 CompressedImage 零拷贝，Python 无序列化 | Python 节点不设 shm |
| stereonet_depth 空 | 话题存在但无数据 | stereonet 只往 compresseddepth 发 PNG | 改用 compresseddepth |
| `grab failed` | mipi 几分钟后掉线 | DDS 序列化抢 VIN DMA | taskset + 减少订阅方 |
| NV12 cv_bridge 失败 | person_detector 无图 | cv_bridge 不支持 NV12 | 手动解码 |
| HOG 检测率极低 | 1/300 帧 | 分辨率低 + ARM 慢 | 改用深度前景包围盒 |
| `--symlink-install` | build 失败 | 老 setuptools | 普通 build |
| Foxglove 连接失败 | 选错协议 | 选 Rosbridge 而非 WebSocket | 选 Foxglove WebSocket |

---

## 参考文献

- 地平线 RDK X5 开发手册
- RPLidar A2M6 开发指南
- ROS2 Humble 官方文档
- slam_toolbox 使用指南
- Nav2 导航框架文档

---

## 开源协议

本项目遵循 [MIT License](LICENSE)。

---

> 📧 作者：[lipf0409](https://github.com/lipf0409)  
> 🔗 仓库：[https://github.com/lipf0409/-RDK-X5-](https://github.com/lipf0409/-RDK-X5-)
