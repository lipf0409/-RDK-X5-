# 智能监护机器人 — 人体检测+跌倒报警 部署指南

## 当前状态 (2026-07-07)

| 模块 | 状态 | 说明 |
|------|------|------|
| 人体检测 | ✅ 通过 | 深度图背景差分，空场景零误报 |
| 跌倒检测 | ✅ 通过 | 头部高度追踪 + 多条件融合 |
| 声光报警 | ✅ 通过 | M260C音频 + GPIO LED |
| 火焰检测 | ⬜ 待测 | HSV算法与板端一致 |

## 文件清单

### PC端（windows_test/）

| 文件 | 用途 |
|------|------|
| `depth_person_detector.py` | ★ 核心检测算法（背景差分） |
| `board_person_detector_node.py` | ★ 板端 ROS2 人体检测节点 |
| `depth_analyzer.py` | PC端深度图离线分析工具 |
| `save_depth_frames.py` | 板端录制深度PNG供PC分析 |
| `fire_detector_standalone.py` | PC端火焰检测验证 |
| `开发记录_20260706.md` | 完整诊断记录 |

### 板端（~/ucar_01/）

| 文件 | 说明 |
|------|------|
| `depth_person_detector.py` | 核心算法 |
| `board_person_detector_node.py` | ROS2节点 |
| `src/ucar_vision/ucar_vision/vision_monitor.py` | 跌倒检测（已修复头部查找） |
| `src/ucar_vision/config/vision_params.yaml` | 视觉参数 |

## 当前配置参数

### 人体检测
| 参数 | 值 | 说明 |
|------|-----|------|
| camera_height | 0.20m | 摄像头离地高度 |
| bg_diff_threshold | 200mm | 背景差分阈值 |
| bg_init_frames | 10 | 建背景帧数 |
| bg_alpha | 0.003 | 背景更新速率 |
| min_foreground_pixels | 5000 | 最少前景像素 |
| min_bbox_area | 2000 px² | 最小包围盒面积 |
| min_aspect_ratio | 0.8 | 最小高宽比 |

### 跌倒检测（测试用，正式部署需调整）
| 参数 | 值 | 说明 |
|------|-----|------|
| camera_height | 0.20m | 摄像头高度 |
| camera_pitch_deg | -2.0 | 俯仰角（下倾2°） |
| head_height_threshold | 0.95m | ⚠️ 测试值，正式改为0.45m |
| fall_duration_threshold | 0.3s | ⚠️ 测试值，正式改为1.2s |
| aspect_ratio_threshold | 1.15 | 宽高比阈值 |
| fall_cooldown | 5.0s | 报警冷却 |

### 真实相机内参
```
fx=469.2  fy=469.2  cx=580.6  cy=358.9
深度图: 352×640 (uint16 mm)
```

## 启动命令（5终端）

```bash
# ═══ 终端1: MIPI摄像头 ═══
source /opt/tros/humble/setup.bash
renice -n -10 -p $$ 2>/dev/null
taskset -c 0,1 ros2 launch mipi_cam mipi_cam_dual_channel.launch.py

# ═══ 终端2: BPU深度 ═══
source /opt/tros/humble/setup.bash
taskset -c 2,3 ros2 launch hobot_stereonet stereonet_model.launch.py \
    stereo_image_topic:=/image_combine_raw stereo_combine_mode:=1 need_rectify:=True

# ═══ 终端3: 人体检测 ═══
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

# ═══ 终端5: 报警 ═══
source /opt/tros/humble/setup.bash
source /home/sunrise/ucar_01/install/setup.bash
ros2 run ucar_vision alarm_controller --ros-args \
    --params-file /home/sunrise/ucar_01/src/ucar_vision/config/vision_params.yaml \
    -p sim_mode:=true
```

## 验证命令

```bash
# 检测链路
ros2 topic echo /person_detections --once    # 人体检测结果
ros2 topic echo /monitor_status --once       # vision_monitor状态
ros2 topic echo /person_head_height --once   # 头部高度

# 手动触发报警（测试声光）
ros2 topic pub /fall_alert std_msgs/msg/Bool "data: true" --once

# Foxglove可视化
# /board_person_detector/debug   → 人体检测mask+bbox
# /vision_monitor/debug          → 跌倒检测标注
```

## 已知修改（相对原始代码）

1. `vision_monitor.py`: 头部查找从 `bbox_cy - bh*0.3` 改为深度感知扫描
2. `vision_params.yaml`: camera_pitch 从 8.0° 改为 -2.0°
3. 背景差分算法替代原版深度阈值法
4. 宽高比过滤 + 大面积豁免

## 正式部署前需还原

```yaml
# vision_params.yaml
head_height_threshold: 0.45   # 0.95 → 0.45
fall_duration_threshold: 1.2  # 0.3 → 1.2
```
