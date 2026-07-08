# 智能报警监护机器人 — Qt 控制与监控界面

基于 PySide6 + ROS2 (rclpy) 的专业桌面端监控应用，用于 JGB520 智能报警监护机器人的实时数据可视化与状态监控。

## 功能概述

- **RGB 实时画面** — SC230AI 双目摄像头彩色图像，叠加人体检测追踪框和头部高度数值
- **伪彩色深度图** — stereonet_compresseddepth 的 PNG 压缩深度数据解码为 JET 伪彩色显示
- **LIDAR / SLAM 2D 视图** — Foxglove 风格的激光点云与占据栅格热力图渲染
- **AI 语音对话窗口** — 模型唤醒状态 + 对话历史展示
- **报警监控** — 跌倒检测与火焰检测，顶部纯文字三色指示灯闪烁 + 事件日志红色标注
- **彩色事件日志** — 底部滚动日志（灰色=系统, 橙色=人体检测, 红色=报警）
- **启动画面** — 应用启动时展示项目信息和初始化状态

## 布局

```
启动画面 (2秒) → 主界面 (1024x600, 7寸屏):
+------+-------------------+-------------------+
| 导航 | ● 正常 ● 跌倒 ● 火焰 |                 |
| (静态)+-------------------+-------------------+
|      | RGB 摄像头         | 深度图 (伪彩色)    |
|      +-------------------+-------------------+
|      | SLAM 热力图        | AI 对话窗口       |
+------+-------------------+-------------------+
|              事件日志                         |
+----------------------------------------------+
```

## 项目结构

```
qt_monitor/
├── main.py                # 生产环境入口 (需 ROS2 + rclpy)
├── run_mock.py            # Windows 离线测试启动器 (无 ROS2 依赖)
├── splash.py              # 启动画面 (深蓝底 + 橙色 Logo)
├── mock_bridge.py         # 模拟数据源（用于离线测试）
├── ros_bridge.py          # ROS2 桥接层 (10 订阅 + 1 发布, 线程安全)
├── widgets/
│   ├── left_nav.py        # 左侧导航栏 (导航/视觉/跌倒/火焰/语音)
│   ├── status_bar.py      # 顶部纯文字指示灯 (● 正常 / ● 跌倒 / ● 火焰)
│   ├── rgb_view.py        # RGB 画面 + 人体检测框叠加
│   ├── depth_view.py      # 伪彩色深度图 + 人物轮廓
│   ├── slam_view.py       # LIDAR + SLAM 2D 热力图 (Foxglove 风格)
│   ├── voice_chat.py      # AI 语音对话窗口 (唤醒状态 + 示例对话)
│   ├── alarm_panel.py     # 报警合并面板 (跌倒+火焰, 备用)
│   ├── system_panel.py    # 硬件状态 + 参数面板 + 方向键
│   └── log_panel.py       # 底部彩色事件日志
└── styles/
    └── theme.qss          # QSS 主题样式表 (深蓝侧栏 + 灰白分区 + 科技橙)
```

## 设计规范

| 项目 | 说明 |
|------|------|
| **色彩主题** | 深蓝侧栏 (#16213E) + 灰白分区 (#EEF0F2/#F8F9FA) + 科技橙强调色 (#FF7F00) |
| **布局** | 左侧导航栏 (60px) + 右侧工作区（上: RGB+深度图, 下: SLAM+AI对话） |
| **设计风格** | 扁平化、现代、专业医疗器械 / 安防监控风格 |
| **字体** | Microsoft YaHei / PingFang SC |
| **交互模式** | 静态展示 — 所有按钮/控件设置为 setEnabled(False) |
| **线程模型** | ROS2 MultiThreadedExecutor 在独立 QThread 中 spin，QMutex 保护数据缓存，GUI 30fps 定时刷新 |
| **屏幕适配** | 针对 7 寸屏 (1024x600) 优化字号和控件尺寸 |

## 快速测试 (Windows, 无需 ROS2)

```bash
pip install PySide6 numpy opencv-python
python qt_monitor/run_mock.py
```

Mock 模式模拟所有数据源：
- 圆形房间激光雷达扫描点云
- 合成室内场景（门/窗/桌子）RGB 图像
- 径向渐变深度图 + 人体轮廓
- 圆形轨迹里程计
- 自动场景循环: 空闲 -> 人员出现 -> 检测追踪 -> 跌倒报警 -> 恢复

## RDK X5 生产部署

### 1. 环境要求

| 项目 | 版本/说明 |
|------|-----------|
| 硬件 | RDK X5 (旭日X5), 7 寸触摸屏 (1024x600) |
| 系统 | Ubuntu 22.04 (ARM64) |
| ROS2 | Humble + TROS (地平线适配版) |
| Python | 3.10+ |
| Qt 绑定 | PySide6 |
| 图像处理 | numpy, opencv-python |

### 2. 安装依赖

```bash
# Python 依赖
pip install PySide6 numpy opencv-python

# ROS2 系统依赖 (如未安装)
sudo apt install ros-humble-vision-msgs
```

### 3. 环境变量 (关键!)

Qt 应用必须在清除 hobot_shm 环境变量的终端中运行，否则 Python 节点无法接收 CompressedImage 数据：

```bash
unset RMW_FASTRTPS_USE_QOS_FROM_XML
unset FASTRTPS_DEFAULT_PROFILES_FILE
```

### 4. 依赖的 ROS2 节点与数据流

Qt 界面本身不产生数据，它订阅以下节点发布的 ROS2 话题。

#### 4.1 必须先启动的外部节点

| 序号 | 节点 | 启动命令 | 提供的话题 | 说明 |
|------|------|----------|-----------|------|
| 1 | **mipi_cam** | `ros2 launch mipi_cam mipi_cam_dual_channel.launch.py` | `/image_combine_raw` (nv12 1280x1440) | SC230AI 双目原始图像 |
| 2 | **hobot_stereonet** | `ros2 launch hobot_stereonet stereonet_model.launch.py` | `/StereoNetNode/stereonet_compresseddepth` (PNG uint16 352x640), `/StereoNetNode/rectified_image` (校正RGB), `/StereoNetNode/camera_info` | BPU 双目深度推理 |
| 3 | **board_person_detector_node** | `python3 board_person_detector_node.py` | 内部使用，不直接发布话题 | 背景差分人体检测, 与 vision_monitor 内部通信 |
| 4 | **vision_monitor** | `ros2 run ucar_vision vision_monitor` | `/monitor_status` (String), `/person_head_height` (Float32) | 跌倒检测核心节点 |
| 5 | **alarm_controller** | `ros2 run ucar_vision alarm_controller` | `/fall_alert` (Bool), `/fire_alert` (Bool) | 声光报警联动控制 |
| 6 | **voice_assistant** | `ros2 launch voice_assistant voice_assistant.launch.py` | `/voice/wakeup` (String), `/voice/question` (String), `/voice/answer` (String), `/voice/command` (String), `/voice/angle` (Int32) | AI 语音唤醒+对话+指令 |

#### 4.2 可选节点 (电机+雷达, 影响 SLAM 页面)

| 序号 | 节点 | 启动命令 | 提供的话题 | 说明 |
|------|------|----------|-----------|------|
| 6 | **jgb520_driver** | `ros2 launch jgb520_driver robot_bringup.launch.py` | `/scan` (LaserScan), `/odom` (Odometry), `/cmd_vel` (订阅) | 电机驱动 + RPLidar |
| 7 | **slam_toolbox** | `ros2 launch jgb520_driver slam.launch.py` | `/map` (OccupancyGrid) | SLAM 建图 |

#### 4.3 节点依赖关系图

```
mipi_cam (SC230AI)
  └─> /image_combine_raw (nv12)
        └─> hobot_stereonet (BPU)
              ├─> /StereoNetNode/stereonet_compresseddepth (PNG depth)
              ├─> /StereoNetNode/rectified_image (RGB)
              └─> /StereoNetNode/camera_info

board_person_detector_node (背景差分)
  └─> (内部数据)
        └─> vision_monitor (跌倒检测)
              ├─> /monitor_status
              └─> /person_head_height
                    └─> alarm_controller (报警联动)
                          ├─> /fall_alert
                          └─> /fire_alert

jgb520_driver (电机+雷达)
  ├─> /scan
  └─> /odom
        └─> slam_toolbox
              └─> /map

voice_assistant (语音助手)
  ├─> /voice/wakeup (唤醒事件 JSON)
  ├─> /voice/question (用户语音文本)
  ├─> /voice/answer (AI 回复文本)
  ├─> /voice/command (解析后的指令 JSON)
  ├─> /voice/angle (唤醒角度)
  ├─> /cmd_vel (移动指令 → jgb520_driver)
  └─> 订阅 /voice/speak (外部 TTS 请求)

qt_monitor/main.py (本应用)
  ← 订阅以上所有话题 + /voice/*
  → 发布 /cmd_vel (底盘控制) + /voice/speak (告警播报)
```

### 5. Qt 界面订阅的话题详情

| 话题 | 类型 | 来源节点 | 对应界面组件 | 重要性 |
|------|------|----------|-------------|--------|
| `/scan` | `sensor_msgs/LaserScan` | rplidar_ros | SLAM 视图 (点云渲染) | 可选 |
| `/odom` | `nav_msgs/Odometry` | jgb520_driver | SLAM 视图 (机器人位姿) | 可选 |
| `/map` | `nav_msgs/OccupancyGrid` | slam_toolbox | SLAM 视图 (热力图叠加) | 可选 |
| `/StereoNetNode/rectified_image` | `sensor_msgs/Image` | hobot_stereonet | RGB 视图 | **必须** |
| `/StereoNetNode/stereonet_compresseddepth` | `sensor_msgs/CompressedImage` | hobot_stereonet | 深度视图 | **必须** |
| `/StereoNetNode/camera_info` | `sensor_msgs/CameraInfo` | hobot_stereonet | 相机内参显示 | 可选 |
| `/monitor_status` | `std_msgs/String` | vision_monitor | RGB/深度图叠加状态 | **必须** |
| `/person_head_height` | `std_msgs/Float32` | vision_monitor | RGB/深度图头部高度数值 | **必须** |
| `/fall_alert` | `std_msgs/Bool` | alarm_controller | 顶部指示灯 + 日志 | **必须** |
| `/fire_alert` | `std_msgs/Bool` | alarm_controller | 顶部指示灯 + 日志 | **必须** |
| `/voice/wakeup` | `std_msgs/String` | voice_assistant | AI 对话窗口 (唤醒指示灯) | 可选 |
| `/voice/question` | `std_msgs/String` | voice_assistant | AI 对话窗口 (用户语音) | 可选 |
| `/voice/answer` | `std_msgs/String` | voice_assistant | AI 对话窗口 (AI 回复) | 可选 |
| `/voice/command` | `std_msgs/String` | voice_assistant | AI 对话窗口 (机器人指令) | 可选 |
| `/voice/angle` | `std_msgs/Int32` | voice_assistant | 唤醒声源角度 | 可选 |

### 6. 一键启动 (推荐)

```bash
# 完整版 (7 节点: 摄像头 + 检测 + 语音 + QT)
/home/sunrise/ucar_01/start_all.sh

# 含 SLAM 雷达版 (9 节点: +电机 + 建图)
/home/sunrise/ucar_01/start_all_slam.sh
```

### 7. 手动启动 (调试用)

### 8. 可选: 带电机雷达的完整启动 (旧版手动)

在终端6改为:

```bash
source /home/sunrise/ucar_01/install/setup.bash
unset RMW_FASTRTPS_USE_QOS_FROM_XML
unset FASTRTPS_DEFAULT_PROFILES_FILE
ros2 launch ucar_vision vision_patrol.launch.py sim_mode:=true
```

然后在终端7启动 Qt 界面:

```bash
source /home/sunrise/ucar_01/install/setup.bash
unset RMW_FASTRTPS_USE_QOS_FROM_XML
unset FASTRTPS_DEFAULT_PROFILES_FILE
cd /home/sunrise/ucar_01
python3 qt_monitor/main.py
```

### 8. 验证各节点数据

```bash
# 确认所有话题存在
ros2 topic list | grep -iE "stereo|person|fall|fire|scan|odom|map"

# 深度帧率
ros2 topic hz /StereoNetNode/stereonet_compresseddepth

# 确认 Python 能收到深度 (最关键!)
python3 -c "
import rclpy, numpy as np, cv2
from sensor_msgs.msg import CompressedImage
rclpy.init()
n = rclpy.create_node('test')
c = [0]
def cb(m):
    c[0] += 1
    arr = np.frombuffer(m.data, np.uint8)
    depth = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
    if depth is not None:
        n.get_logger().info(f'#{c[0]} {depth.shape} dtype={depth.dtype}')
n.create_subscription(CompressedImage, '/StereoNetNode/stereonet_compresseddepth', cb, 10)
try: rclpy.spin(n)
except KeyboardInterrupt: pass
"

# vision_monitor 状态
ros2 topic echo /monitor_status --once

# 头部高度
ros2 topic echo /person_head_height --once

# 手动测试报警
ros2 topic pub /fall_alert std_msgs/msg/Bool "data: true" --once
ros2 topic pub /fire_alert std_msgs/msg/Bool "data: true" --once
```

## RDK X5 部署注意事项

### CPU 隔离 (重要)

RDK X5 是 ARM 平台，DDS 序列化可能抢占 VIN DMA 导致摄像头掉线。必须用 `taskset` 隔离 CPU 核心：

| 节点 | 绑定 CPU 核 | 原因 |
|------|------------|------|
| mipi_cam | 0, 1 | VIN DMA 需要独占核心 |
| hobot_stereonet | 2, 3 | BPU 推理需要独立核心 |
| vision_monitor | 4, 5 | Python 图像处理 |
| qt_monitor | 不限 | Qt GUI 可以在任意核心 |

### hobot_shm 环境变量

**关键**: 运行 Qt 界面的终端**必须**清除以下环境变量，否则 Python 无法接收 CompressedImage 数据：

```bash
unset RMW_FASTRTPS_USE_QOS_FROM_XML
unset FASTRTPS_DEFAULT_PROFILES_FILE
```

原因是地平线 `hobot_shm` 使用共享内存零拷贝传输 CompressedImage，
Python 侧无序列化支持，必须走 DDS 网络传输路径。

### Qt 显示

RDK X5 的 ARM GPU 在 X 转发下渲染 RViz 有 GLSL 兼容问题。本 Qt 应用使用纯 CPU 渲染 (QPainter)，不受此限制，可直接在本地 X11 显示或通过 X 转发远程显示。

```bash
# 本地 7 寸屏直接运行
export DISPLAY=:0
python3 qt_monitor/main.py

# 远程 X 转发 (PC 端查看)
ssh -X sunrise@<RDK_IP>
export DISPLAY=:0
python3 qt_monitor/main.py
```

## 图像处理管线

深度图可视化的关键路径:

```
CompressedImage.data (PNG 字节, 352x640 uint16)
  -> np.frombuffer()
  -> cv2.imdecode(IMREAD_UNCHANGED)   # PNG 解码为 uint16 numpy 数组
  -> 归一化 300-8000mm 到 0-255
  -> cv2.applyColorMap(COLORMAP_JET)  # JET 伪彩色映射
  -> QImage(Format_BGR888)
  -> QPixmap
  -> QLabel.setPixmap()
```

RGB 图像支持多种编码格式:
- `rgb8`, `bgr8`, `bgra8` — 标准格式
- `nv12` — RDK X5 mipi_cam 原生格式（手动 YUV -> BGR 转换）

## 语音控制

### 语音指令列表

对着 M260C 说 **"小飞小飞"** 唤醒，然后说指令：

| 指令 | 动作 | 说明 |
|------|------|------|
| 前进 / 往前走 / 直走 | 直线前进 0.2m/s | 2秒自动停止 |
| 后退 / 往后 | 后退 0.15m/s | 2秒自动停止 |
| 左转 / 向左 | 左转 0.5rad/s | 2秒自动停止 |
| 右转 / 向右 | 右转 -0.5rad/s | 2秒自动停止 |
| 停 / 停下 / 停止 | 立即停止 | 发布零速度 |
| 快一点 / 慢点前进 | 调速 | 0.35/0.10 m/s |
| 掉头 / 转过来 | 原地旋转 | 1.0 rad/s |
| 开始巡逻 / 启动巡线 | 启动巡逻 | 发布 JSON 到 /voice/command |
| 停止巡逻 | 停止巡逻 | |
| 回充电桩 / 去充电 | 导航到充电桩 | |
| 去卧室 / 去客厅 / 去厨房 | 导航到目标点 | |
| 你在哪 | 查询位置 | |
| 电量 / 还有多少电 | 查询电量 | |
| 状态 / 检查状态 | 查询状态 | |

### QT 界面操作

- 点击左侧 **"语音"** 按钮 → 弹出 AI 对话面板
- 对话面板实时显示：唤醒 → 用户语音 → AI 回复 → 机器人指令
- 文本输入框可打字，点击"发送"通过语音助手播报
- 唤醒时指示灯由红变绿，显示"已唤醒 - 正在对话"

### 验证语音指令

```bash
# 查看解析后的指令
ros2 topic echo /voice/command

# 查看底盘指令
ros2 topic echo /cmd_vel

# 手动测试告警播报
ros2 topic pub /voice/speak std_msgs/msg/String "data: '检测到有人摔倒，请立即处理'" --once
```

## 故障排查

| 现象 | 原因 | 解决 |
|------|------|------|
| RGB/深度图黑屏 | 对应 ROS2 节点未启动 | 确认 hobot_stereonet 在跑, 话题有数据 |
| 深度图有话题但 Python 收不到 | hobot_shm 环境变量未清除 | `unset RMW_FASTRTPS_USE_QOS_FROM_XML` |
| Qt 界面卡顿 | 数据频率过高 | 正常, 30fps 定时刷新已做限流 |
| mipi_cam 运行几分钟后掉线 | DDS 序列化抢占 VIN DMA | 用 taskset CPU 隔离 |
| 人体检测/跌倒无显示 | vision_monitor 未启动或人在范围外 | 确认 vision_monitor 在跑, 人站 1-3m 内 |
| Python 依赖缺失 | 未安装 PySide6/numpy/cv2 | `pip install PySide6 numpy opencv-python` |
| import 报错 | 环境变量 ros 冲突 | `unset PYTHONPATH` (如使用系统 Python) |
