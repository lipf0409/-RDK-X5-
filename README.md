# 智能报警监护机器人 — JGB520 + RPLidar A2M6 + 双目视觉 ROS2 平台

## 硬件配置

| 组件 | 型号 | 接口 | 设备名 |
|------|------|------|--------|
| 工控机 | RDK X5 (旭日X5) | - | Ubuntu 22.04 + ROS2 Humble + TROS |
| 双目摄像头 | RDK Stereo Camera (SC230AI) | MIPI CSI | `/dev/video*` |
| 激光雷达 | RPLidar A2M6 | USB 串口 (CP210x: `10c4:ea60`) | `/dev/rplidar` |
| 电机驱动 | JGB520 4轮差速 | 硬件串口 | `/dev/ttyS1` |
| USB音频 | 讯飞 M260C 麦克风阵列 | USB | ALSA 声卡 |
| 报警LED | 红色LED + 220Ω | GPIO23 | 灯光报警 |
| 编码器 | 霍尔编码器 11线 | 通过电机驱动板读取 | - |
| 轮径 | 67mm | - | - |
| 轮距 | 0.25m | - | - |

## 项目结构

```
ucar_01/
├── src/
│   ├── jgb520_driver/              # 电机驱动 + SLAM + Nav2 配置
│   │   ├── jgb520_driver/
│   │   │   ├── motor_driver.py     # 核心电机驱动节点
│   │   │   └── scan_fixer.py       # 雷达点数修正
│   │   ├── launch/
│   │   │   ├── robot_bringup.launch.py
│   │   │   ├── slam.launch.py
│   │   │   └── navigation.launch.py
│   │   ├── config/
│   │   │   ├── slam.yaml
│   │   │   └── navigation.yaml
│   │   ├── setup.py
│   │   └── package.xml
│   ├── rplidar_ros-ros/            # RPLidar ROS2 SDK (C++)
│   └── ucar_vision/                # ★ 视觉监护系统
│       ├── ucar_vision/
│       │   ├── vision_monitor.py   # 跌倒检测核心 (已修复头部查找算法)
│       │   ├── alarm_controller.py # USB音频+LED+电机联动
│       │   └── person_detector.py  # 深度人体检测(HOG, 已被背景差分替代)
│       ├── launch/
│       │   ├── vision_bringup.launch.py
│       │   └── vision_patrol.launch.py
│       ├── config/
│       │   └── vision_params.yaml
│       ├── package.xml
│       └── setup.py
├── depth_person_detector.py        # ★ 背景差分人体检测核心 (板端)
├── board_person_detector_node.py   # ★ 人体检测 ROS2 节点 (板端)
├── windows_test/                   # ★ PC端分析工具集
│   ├── depth_person_detector.py    # 核心算法 (PC+板端共享)
│   ├── depth_analyzer.py           # 深度图离线分析+交互调参
│   ├── fire_detector_standalone.py # PC端火焰检测验证
│   ├── save_depth_frames.py        # 板端深度图录制
│   ├── 开发记录_20260706.md        # 完整诊断记录
│   └── README.md
├── qt_monitor/                     # ★ Qt 桌面监控界面 (PySide6 + ROS2)
│   ├── main.py                     # 生产环境入口 (需 ROS2 + rclpy)
│   ├── run_mock.py                 # Windows 离线测试 (无 ROS2 依赖)
│   ├── mock_bridge.py              # 模拟数据源
│   ├── ros_bridge.py               # ROS2 桥接 (10订阅 + 1发布, 线程安全)
│   ├── widgets/                    # UI 组件库
│   │   ├── left_nav.py             # 左侧导航栏 (NAV/VIS/FALL/FIRE/VOICE)
│   │   ├── status_bar.py           # 顶部报警指示灯
│   │   ├── rgb_view.py             # RGB 实时画面 + 人体检测框
│   │   ├── depth_view.py           # 伪彩色深度图
│   │   ├── slam_view.py            # 激光雷达 + SLAM 2D 热力图
│   │   ├── system_panel.py         # 硬件状态 + 参数面板 + 底盘控制
│   │   └── log_panel.py            # 底部彩色日志
│   ├── styles/
│   │   └── theme.qss               # QSS 主题 (纯白 + 科技橙)
│   └── README.md
├── scripts/
│   └── test_audio_led.sh
├── docs/
│   └── 视觉监护系统技术文档.md
├── sounds/                         # 报警音效 (运行时自动生成)
├── maps/                           # SLAM地图
└── README.md
```

## TF 坐标树

```
odom → base_link → laser
```

- `base_link → laser`: 雷达在车体前方 0.15m，上方 0.1m

---

## 第一步：硬件检查

### 1.1 确认设备识别

```bash
# 查看串口设备
ls -l /dev/ttyS1 /dev/rplidar

# 查看内核日志
dmesg | tail -30
```

### 1.2 创建 udev 规则 (持久化设备名)

```bash
sudo tee /etc/udev/rules.d/99-robot-serial.rules << 'EOF'
# 激光雷达 (CP210x)
KERNEL=="ttyUSB*", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", MODE="0666", SYMLINK+="rplidar"
EOF

sudo udevadm control --reload-rules
sudo udevadm trigger

# 验证
ls -l /dev/rplidar
```

---

## 第二步：编译

```bash
cd ~/ucar_01
source /opt/ros/humble/setup.bash

# 安装依赖
sudo apt update
sudo apt install ros-humble-slam-toolbox ros-humble-navigation2 ros-humble-nav2-bringup ros-humble-teleop-twist-keyboard

# 安装 Foxglove Bridge（可视化工具）
sudo apt install ros-humble-foxglove-bridge

# 编译
colcon build --packages-select jgb520_driver rplidar_ros
source install/setup.bash
  source /home/sunrise/ucar_01/install/setup.bash
  ros2 launch voice_assistant voice_assistant.launch.py

```

---

## 第三步：基础测试

### 3.1 启动机器人基础节点

```bash
source /home/sunrise/ucar_01/install/setup.bash
ros2 launch jgb520_driver robot_bringup.launch.py
```

### 3.2 验证话题

```bash
# 新终端
source ~/ucar_01/install/setup.bash

ros2 topic list
# 应看到: /scan, /cmd_vel, /odom, /encoder_raw, /tf, /tf_static
```
 
##
 # 3.3 键盘控制测试

```bash
source /home/sunrise/ucar_01/install/setup.bash
ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -p speed:=0.15 -p turn:=0.4
# i=前进  ,=后退  j=左转  l=右转  k=停止  q=退出
# q/z: 最大速度 ±10%   w/x: 线速度 ±10%   e/c: 角速度 ±10%
```

---

## 第四步：SLAM 建图

### 4.1 启动 SLAM

```bash
# 终端1：启动 SLAM（电机 + 雷达 + TF + slam_toolbox）
source /home/sunrise/ucar_01/install/setup.bash
ros2 launch jgb520_driver slam.launch.py
```

### 4.2 启动 Foxglove 可视化（RDK X5 推荐）

RDK X5 的 ARM GPU 在 X 转发下渲染 RViz 有 GLSL 兼容问题，改用 Foxglove 浏览器渲染。

**机器人端：**

```bash
# 终端2：启动 Foxglove Bridge
source /home/sunrise/ucar_01/install/setup.bash
ros2 launch foxglove_bridge foxglove_bridge_launch.xml port:=8765
```

**PC 端：**

1. 下载 [Foxglove Desktop](https://www.foxglove.dev/download) 或打开 https://app.foxglove.dev/
2. 点击 **Open connection...**
3. 连接类型选 **Foxglove WebSocket**
4. URL 填：`ws://<机器人IP>:8765`（例如 `ws://10.220.223.222:8765`）
5. 点 **Open**

### 4.3 Foxglove 面板配置

连接成功后，添加以下面板：

| 面板 | 订阅 Topic | 说明 |
|------|-----------|------|
| **3D** | — | 主视图，显示激光和机器人位姿 |
| **Map** | `/map` | 实时 SLAM 地图（最关键） |
| **Raw Messages** | `/map` | 查看地图原始数据，排查用 |

3D 面板设置：
- **Fixed Frame** 设为 `map`
- **Layers** → 添加 Grid，Topic 选 `/map`
- **Topics** 侧边栏勾选 `/scan`

### 4.4 控制小车建图

```bash
# 终端3：键盘控制
source /home/sunrise/ucar_01/install/setup.bash
ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -p speed:=0.15 -p turn:=0.4
```

### 建图技巧

1. **原地 360° 旋转** — 建立初始地图
2. **沿墙慢速行驶** — 覆盖所有区域
3. **走闭环** — 回到起点让 SLAM 自动优化（回环检测）
4. **速度要慢** — 推荐 0.10~0.20 m/s

### 4.5 验证地图是否正常更新

```bash
# 看 /map 时间戳是否持续刷新
ros2 topic echo /map --once 2>&1 | grep "sec:"
# 多跑几次，sec 值应该递增

# 统计地图有效像素（非 -1 的值应该在增长）
python3 -c "
import rclpy; from rclpy.node import Node; from nav_msgs.msg import OccupancyGrid
rclpy.init(); node=Node('m'); c=[0]
def cb(msg):
    d=msg.data; nz=sum(1 for x in d if x!=-1)
    print(f'有效像素:{nz}/{len(d)} size:{msg.info.width}x{msg.info.height}')
    c[0]+=1
    if c[0]>=5: node.destroy_node()
node.create_subscription(OccupancyGrid,'/map',cb,10)
rclpy.spin(node); rclpy.shutdown()
"
```

### 4.6 保存地图

```bash
mkdir -p ~/maps
ros2 run nav2_map_server map_saver_cli -f ~/maps/my_map
# 生成 my_map.yaml + my_map.pgm
```

---

## 第五步：Nav2 导航

### 5.1 启动导航

```bash
source ~/ucar_01/install/setup.bash
ros2 launch jgb520_driver navigation.launch.py map:=/home/sunrise/maps/my_map.yaml
```

### 5.2 Foxglove 导航操作

1. 在 Foxglove 3D 面板中点击 **"2D Pose Estimate"** 设置初始位置
2. 点击 **"Nav2 Goal"** 设置目标点
3. 机器人自动规划路径并导航

---

## 运行命令速查

```bash
# 基础启动
ros2 launch jgb520_driver robot_bringup.launch.py

# SLAM 建图
ros2 launch jgb520_driver slam.launch.py

# Foxglove Bridge（可视化）
ros2 launch foxglove_bridge foxglove_bridge_launch.xml port:=8765

# Nav2 导航
ros2 launch jgb520_driver navigation.launch.py map:=/home/sunrise/maps/my_map.yaml

# 键盘控制（低速建图推荐）
ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -p speed:=0.15 -p turn:=0.4

# 键盘控制（默认速度）
ros2 run teleop_twist_keyboard teleop_twist_keyboard

# 直接发布速度指令
ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.1}, angular: {z: 0.0}}"

# 查看话题
ros2 topic list
ros2 topic echo /odom --once
ros2 topic echo /scan --once
ros2 topic hz /scan

# 查看 TF 树
ros2 run tf2_tools view_frames
ros2 run tf2_ros tf2_echo odom base_link

# 查看节点参数
ros2 param get /rplidar_node serial_port
ros2 param get /jgb520_driver serial_port
ros2 param get /slam_toolbox minimum_travel_distance

# 保存地图
ros2 run nav2_map_server map_saver_cli -f ~/maps/my_map

# 单独编译
colcon build --packages-select jgb520_driver
source install/setup.bash
```

---

## 视觉监护系统

> **当前状态 (2026-07-07)**:
> - ✅ MIPI 双目摄像头 SC230AI 已识别, 10fps
> - ✅ BPU 双目深度模型推理成功
> - ✅ **人体检测**: 背景差分算法, 空场景零误报, 持续追踪
> - ✅ **跌倒检测**: 深度感知头部查找, 头部高度追踪
> - ✅ **声光报警全链路**: 人体检测→跌倒判决→M260C警笛+LED闪烁
> - ✅ M260C USB 音频正常, 音效自动生成
> - ✅ 真实相机内参: `fx=469.2 fy=469.2 cx=580.6 cy=358.9`
> - ✅ 摄像头实际倾角: 约-2° (下倾), 非 +8°
> - ✅ 跌倒阈值已设为正式值 0.45m/1.2s
> - ⚠️ `stereonet_depth` 话题空 — 深度只发 `stereonet_compresseddepth`
> - ⬜ 火焰检测待实机验证
> - ⬜ LED 硬件待接入

### 踩坑记录

| 坑 | 症状 | 根因 | 解决 |
|----|------|------|------|
| hobot_shm + rclpy | `Has_depth:False` 永不变 | 共享内存 CompressedImage 零拷贝, Python 无序列化 | Python 节点不设 shm |
| stereonet_depth 空 | 话题存在但无数据 | stereonet 只往 compresseddepth 发 PNG | 改用 compresseddepth |
| `grab failed` | mipi 几分钟后掉线 | DDS 序列化抢 VIN DMA | taskset + 减少订阅方 |
| NV12 cv_bridge 失败 | person_detector 无图 | cv_bridge 不支持 NV12 | 手动解码, 已内置 |
| `bbox.center.x` 报错 | 崩溃 | vision_msgs 用 Pose2D | → `position.x` |
| HOG 检测率极低 | 1/300 帧 | 分辨率低+ARM慢 | 改深度前景包围盒, 内置于 vision_monitor |
| `--symlink-install` | build 失败 | 老 setuptools | 普通 build |

### 人体检测: 深度图背景差分

```
启动后前 bg_init_frames(10) 帧建立背景模型
之后每帧 |当前深度 - 背景深度| > 200mm → 前景(人)
背景慢速更新(alpha=0.003), 不受光照影响
```

<1ms, 纯numpy。算法在 `depth_person_detector.py`，ROS2 节点在 `board_person_detector_node.py`。

### 话题速查表 (hobot_stereonet)

| 话题 | 类型 | 说明 |
|------|------|------|
| `/image_left_raw` | `sensor_msgs/Image` (nv12 1280×720) | 左目原始图 |
| `/image_right_raw` | `sensor_msgs/Image` (nv12 1280×720) | 右目原始图 |
| `/image_combine_raw` | `sensor_msgs/Image` (nv12 1280×1440) | ★ 左右拼接图 → 给 stereonet |
| `/StereoNetNode/stereonet_depth` | `sensor_msgs/Image` | ⚠️ 话题声明存在但无数据 |
| `/StereoNetNode/stereonet_compresseddepth` | `sensor_msgs/CompressedImage` (PNG) | ★ 实际深度数据 (352×640 uint16) |
| `/StereoNetNode/rectified_image` | `sensor_msgs/Image` | 校正后RGB (与深度对齐) |
| `/StereoNetNode/camera_info` | `sensor_msgs/CameraInfo` | 校正后内参 |
| `/StereoNetNode/stereonet_visual` | `sensor_msgs/Image` | 深度可视化图 |

### 编译视觉包

```bash
cd /home/sunrise/ucar_01
source /opt/tros/humble/setup.bash
unset RMW_FASTRTPS_USE_QOS_FROM_XML
unset FASTRTPS_DEFAULT_PROFILES_FILE

# 安装依赖 (只需一次)
sudo apt install ros-humble-vision-msgs

# 编译 (不用 --symlink-install, RDK X5 的 setuptools 版本不支持)
colcon build --packages-select ucar_vision
source install/setup.bash
```

### 启动序列 (按顺序, 5个终端)

```bash
# ═══ 终端1: MIPI 双目摄像头 (SC230AI) ═══
source /opt/tros/humble/setup.bash
renice -n -10 -p $$ 2>/dev/null
taskset -c 0,1 ros2 launch mipi_cam mipi_cam_dual_channel.launch.py

# ═══ 终端2: 双目深度处理 (BPU) ═══
source /opt/tros/humble/setup.bash
taskset -c 2,3 ros2 launch hobot_stereonet stereonet_model.launch.py \
    stereo_image_topic:=/image_combine_raw \
    stereo_combine_mode:=1 need_rectify:=True alpha:=1

# ═══ 终端3: 人体检测 (背景差分) ═══
# ★ 启动时确保空场景, 等2秒背景建立完成
source /opt/tros/humble/setup.bash
source /home/sunrise/ucar_01/install/setup.bash
unset RMW_FASTRTPS_USE_QOS_FROM_XML
unset FASTRTPS_DEFAULT_PROFILES_FILE
cd /home/sunrise/ucar_01
python3 board_person_detector_node.py --ros-args \
    -p camera_height:=0.20 -p bg_diff_threshold:=200 -p bg_init_frames:=10

# ═══ 终端4: 跌倒检测 ═══
source /opt/tros/humble/setup.bash
source /home/sunrise/ucar_01/install/setup.bash
taskset -c 4,5 ros2 run ucar_vision vision_monitor --ros-args \
    --params-file /home/sunrise/ucar_01/src/ucar_vision/config/vision_params.yaml

# ═══ 终端5: 报警控制器 ═══
source /opt/tros/humble/setup.bash
source /home/sunrise/ucar_01/install/setup.bash
ros2 run ucar_vision alarm_controller --ros-args \
    --params-file /home/sunrise/ucar_01/src/ucar_vision/config/vision_params.yaml \
    -p sim_mode:=true

# ═══ 终端6 (可选): Foxglove 可视化 ═══
source /opt/tros/humble/setup.bash
ros2 launch foxglove_bridge foxglove_bridge_launch.xml port:=8765
```

### 一键启动脚本

板子上创建 `~/start_vision.sh`:

```bash
#!/bin/bash
# 视觉监护系统一键启动 (5个终端)
set -e

pkill -9 -f mipi_cam 2>/dev/null; pkill -9 -f stereonet 2>/dev/null; sleep 2

# 终端1: 摄像头
gnome-terminal -- bash -c "
source /opt/tros/humble/setup.bash
renice -n -10 -p \$\$ 2>/dev/null
taskset -c 0,1 ros2 launch mipi_cam mipi_cam_dual_channel.launch.py
exec bash
"
sleep 5

# 终端2: 深度
gnome-terminal -- bash -c "
source /opt/tros/humble/setup.bash
taskset -c 2,3 ros2 launch hobot_stereonet stereonet_model.launch.py \
    stereo_image_topic:=/image_combine_raw \
    stereo_combine_mode:=1 need_rectify:=True alpha:=1
exec bash
"
sleep 20  # 等 BPU 模型加载

# 终端3: 人体检测 (背景差分, 建背景时确保空场景)
gnome-terminal -- bash -c "
source /opt/tros/humble/setup.bash
source /home/sunrise/ucar_01/install/setup.bash
unset RMW_FASTRTPS_USE_QOS_FROM_XML
unset FASTRTPS_DEFAULT_PROFILES_FILE
cd /home/sunrise/ucar_01
python3 board_person_detector_node.py --ros-args \
    -p camera_height:=0.20 -p bg_diff_threshold:=200 -p bg_init_frames:=10
exec bash
"
sleep 3

# 终端4: 跌倒检测
gnome-terminal -- bash -c "
source /opt/tros/humble/setup.bash
source /home/sunrise/ucar_01/install/setup.bash
taskset -c 4,5 ros2 run ucar_vision vision_monitor --ros-args \
    --params-file /home/sunrise/ucar_01/src/ucar_vision/config/vision_params.yaml
exec bash
"
sleep 2

# 终端5: 报警
gnome-terminal -- bash -c "
source /opt/tros/humble/setup.bash
source /home/sunrise/ucar_01/install/setup.bash
ros2 run ucar_vision alarm_controller --ros-args \
    --params-file /home/sunrise/ucar_01/src/ucar_vision/config/vision_params.yaml \
    -p sim_mode:=true
exec bash
"
echo "All 5 nodes launched."
```

### 带电机雷达的完整启动

```bash
# 终端1-2: 摄像头 + 深度处理 (同上)
# 终端3: 人体检测 (同上)
# 终端4: 跌倒检测
# 终端5: 报警控制器
# 终端6: 电机 + 雷达 + 视觉
source /home/sunrise/ucar_01/install/setup.bash
unset RMW_FASTRTPS_USE_QOS_FROM_XML
unset FASTRTPS_DEFAULT_PROFILES_FILE
ros2 launch ucar_vision vision_patrol.launch.py sim_mode:=true
```

### 关键参数说明

| 参数 | 值 | 说明 |
|------|-----|------|
| 摄像头高度 | 0.20m | 实际离地约15~20cm |
| 摄像头倾角 | -2° | 实测下倾约2°, 非原始配置的+8° |
| 相机内参 fx=fy | 469.2 | 来自 `/StereoNetNode/camera_info` |
| 相机内参 cx, cy | 580.6, 358.9 | cy在图像下方, 说明光轴指向上方 |

> ✅ 跌倒阈值已设为正式值: head_height_threshold=0.45m, fall_duration_threshold=1.2s

### 手工测试报警

```bash
# 手动触发跌倒报警 (不需要检测链路, 直接测声光):
ros2 topic pub /fall_alert std_msgs/msg/Bool "data: true" --once
# → M260C 播放警笛声 (fall_alarm.wav)
# → 终端打印红色报警日志
# → 拍照存证到 ~/snapshots/fall/

# 手动触发火焰报警:
ros2 topic pub /fire_alert std_msgs/msg/Bool "data: true" --once
# → M260C 播放高频蜂鸣 (fire_alarm.wav)
```

### 验证命令

```bash
# 确认话题
ros2 topic list | grep -iE "stereo|person|fall|fire"

# 深度帧率
ros2 topic hz /StereoNetNode/stereonet_compresseddepth

# Python 能否收到深度 (关键测试!)
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
n.get_logger().info('Testing depth reception...')
try: rclpy.spin(n)
except KeyboardInterrupt: pass
"

# vision_monitor 状态
ros2 topic echo /monitor_status --once

# 头部高度
ros2 topic echo /person_head_height --once
```

### 故障排查速查

| 现象 | 原因 | 解决 |
|------|------|------|
| `Package 'ucar_vision' not found` | 没 source 工作空间 | `cd ~/ucar_01 && source install/setup.bash` |
| Python 收不到 CompressedImage | hobot_shm 环境变量未清除 | `unset RMW_FASTRTPS_USE_QOS_FROM_XML; unset FASTRTPS_DEFAULT_PROFILES_FILE` |
| `mipi_node: grab failed` | DDS 序列化抢占 CPU, VIN DMA 掉了 | 用 taskset CPU 隔离 (见启动序列) |
| `stereonet_depth` 存在但无数据 | 正常 — 深度只发在 compresseddepth | 改用 `/StereoNetNode/stereonet_compresseddepth` |
| `Has_depth:False` | hobot_shm 或 stereonet 未启动 | unset 环境变量 + 确认 stereonet 在跑 |
| `Has_det:False` (新版) | person_detector 未启动或人在范围外 | 确认 person_detector 在跑, 人站1-3m内 |
| `Has_det:False` (旧版HOG) | HOG 检测率太低 | 已升级为深度前景分割, 同步最新代码 |
| `ros__parameters` parse error | YAML 缺少 `/ ** /ros__parameters` 包裹 | 已修复 |
| `vision_msgs` not found | 缺 ROS2 包 | `sudo apt install ros-humble-vision-msgs` |
| M260C 没声音 | 设备名不对 | `aplay -l` 查看, 试 `plughw:1,0` |
| `--symlink-install` 报错 | setuptools 版本不支持 | 普通 `colcon build` |
| `colcon build` 失败 | 缺依赖 | `sudo apt install ros-humble-vision-msgs` |
| `inference que is full!` / `pub_que is full!` | 正常 — 队列积压, 不影响功能 | 忽略 |

> 详细技术文档见 `docs/视觉监护系统技术文档.md`

---

## 调试技巧

### 串口问题

```bash
# 检查设备
ls -l /dev/ttyS1 /dev/rplidar
dmesg | tail -30

# 手动测试串口
python3 -c "import serial; s=serial.Serial('/dev/ttyS1', 115200); print(s.is_open); s.close()"
```

### 电机不转排查

1. 检查 `/dev/ttyS1` 是否存在
2. 确认启动日志有 `Serial /dev/ttyS1 opened`
3. 检查电机驱动板供电（电池电压）
4. 直接发速度指令测试: `ros2 topic pub /cmd_vel ...`

### 雷达无数据

1. 检查 `/dev/rplidar` 是否存在
2. 确认波特率 115200
3. `ros2 topic echo /scan --once` 查看是否有数据

### 建图不更新排查

| 检查项 | 命令 | 期望 |
|--------|------|------|
| 雷达频率 | `ros2 topic hz /scan` | ~10-12 Hz |
| 地图频率 | `ros2 topic hz /map` | ~0.5 Hz |
| 里程计 TF | `ros2 run tf2_ros tf2_echo odom base_link` | 车动时有变化 |
| 停车 TF 漂移 | 同上（车停时） | 坐标不动 |
| 地图时间戳 | `ros2 topic echo /map --once \| grep sec` | 持续递增 |
| 地图有效像素 | 见 4.5 节 Python 脚本 | 随移动增长 |
| SLAM 参数 | `ros2 param get /slam_toolbox minimum_travel_distance` | 应为 0.01 |

---

## 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| 地图只有初始几帧 | `minimum_travel_distance` 太大或 TF 断流 | 确认 slam.yaml 中设为 0.01，停车时 TF 不漂移 |
| TF 停车时漂移 | 编码器数据过期未归零 | 确认 motor_driver.py 有 `last_encoder_time` 检查 |
| Foxglove 连接失败 | 选错协议 | 选 **Foxglove WebSocket**，不是 Rosbridge |
| SLAM 建图重影 | 速度太快 / 里程计不准 | 降到 0.15 m/s 以下，标定轮径轮距 |
| Nav2 无法定位 | 初始位姿不对 | Foxglove 中手动设置 2D Pose Estimate |
| 激光 `expected 206, got 163` | Standard 模式点数不稳定 | 警告可忽略，不影响建图 |
| `min_range exceeds capabilities` | LaserScan 未设 range_min | 警告可忽略，或加 `min_range: 0.2` 到 lidar 参数 |

---

## Qt 桌面监控界面 (新增)

`qt_monitor/` 提供专业的 PySide6 桌面端控制与监控界面，可实时可视化所有传感器数据和报警状态。

### 界面布局

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

### 快速测试 (Windows, 无需 ROS2)

```bash
pip install PySide6 numpy opencv-python
python qt_monitor/run_mock.py
```

- `F` 键: 手动触发跌倒报警测试
- `G` 键: 手动触发火焰报警测试
- `R` 键: 重置所有报警状态
- 自动循环: 空闲 -> 人出现 -> 检测 -> 跌倒报警 -> 恢复

### 生产环境启动 (RDK X5)

```bash
# 先启动视觉 + 电机节点 (5个终端, 见视觉监护系统章节)
# 然后:

cd ~/ucar_01
pip install PySide6 numpy opencv-python
python3 qt_monitor/main.py
```

### 功能模块

| 模块 | 数据源 | 功能 |
|------|--------|------|
| **LIDAR/SLAM 视图** | `/scan` + `/map` | Foxglove 风格 2D 激光点云 + 占据栅格热力图 |
| **RGB 画面** | `/StereoNetNode/rectified_image` | 实时彩色画面, 人体橙色追踪框, 头部高度数值 |
| **深度图** | `/StereoNetNode/stereonet_compresseddepth` | PNG 解码 -> CV2 伪彩色映射, 人物轮廓叠加 |
| **报警指示灯** | `/fall_alert` + `/fire_alert` | 顶部三色灯, 报警时红灯闪烁 + 界面日志变红 |
| **系统状态** | 综合 | 雷达/摄像头/电机连接状态, 内参/帧率, 参数值 |
| **事件日志** | 综合 | 底部彩色日志 (灰=普通, 橙=检测, 红=报警) |

### 技术要点

- **线程模型**: ROS2 `MultiThreadedExecutor` 在独立 QThread, `QMutex` 保护数据缓存, GUI 30fps 定时刷新
- **深度图解码**: `CompressedImage(PNG)` -> `np.frombuffer` -> `cv2.imdecode(IMREAD_UNCHANGED)` -> uint16 mm
- **NV12 支持**: RDK X5 mipi_cam 原生 NV12 格式直接 `cv2.COLOR_YUV2BGR_NV12` 转换
- **QSS 主题**: 纯白 (#FFFFFF) 底色 + 科技橙 (#FF7F00) 强调色, 扁平化医疗/安防风格
- **静态展示**: 所有交互控件 `setEnabled(False)`, 专注于数据可视化

详细说明见 `qt_monitor/README.md`。

---

## 电机驱动板参数

当前配置（在 `motor_driver.py` 中自动设置）：

| 参数 | 值 | 说明 |
|------|-----|------|
| `$mtype` | 1 | 520 电机 |
| `$mphase` | 30 | 减速比 |
| `$mline` | 11 | 编码器磁环线数 |
| `$wdiameter` | 67 | 轮径 mm |
| `$MPID` | 1.5, 0.12, 0.5 | PID 参数 |
| `$deadzone` | 800 | 死区 |
| `$upload` | 0,1,1 | 连续上报 $MSPD 速度数据 |

电机映射：M1=左前, M2=左后, M3=右前, M4=右后

校准系数：M1=1.02, M2=1.04, M3=1.04, M4=1.03
