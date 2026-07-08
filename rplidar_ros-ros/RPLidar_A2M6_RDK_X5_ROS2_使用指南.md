# RPLidar A2M6 在 RDK X5 (ROS2) 完整使用指南

## 概述

本文档针对以下环境：
- 雷达型号：**RPLidar A2M6**
- 平台：**RDK X5**
- 操作系统：**ROS2 (Humble)**
- 串口设备：**/dev/ttyUSB1** (USB0已被其他设备占用)

---

## 一、硬件准备

### 1.1 RPLidar A2M6 规格

| 参数 | 数值 |
|------|------|
| 测距范围 | 0.15m - 12m |
| 角度分辨率 | 0.3375° |
| 扫描频率 | 10Hz (可调) |
| 采样率 | 8000次/秒 |
| 通信接口 | USB转串口 |
| 波特率 | **115200** (A2M6专用) |

### 1.2 串口设备识别

由于 `/dev/ttyUSB0` 已被占用，需要确认雷达所在串口：

```bash
# 查看所有USB串口设备
ls -la /dev/ttyUSB*

# 查看设备详细信息
dmesg | grep ttyUSB

# 方法：先拔掉雷达，执行 ls /dev/ttyUSB*，再插上雷达，再次执行
# 新增的设备就是雷达
```

**预期结果**：雷达设备为 `/dev/ttyUSB1`

---

## 二、SDK 基础调用（理解原理）

### 2.1 核心架构

SDK 使用 **Channel + Driver** 架构：

```
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│  串口/网络    │ ──── │   Driver     │ ──── │   应用层      │
│  Channel     │      │   (驱动)      │      │  (ROS2/自研)  │
└──────────────┘      └──────────────┘      └──────────────┘
   createSerialPort     createLidarDriver      grabScanDataHq
   createTcpChannel                            ascendScanData
   createUdpChannel
```

### 2.2 核心 API 调用流程

```cpp
#include "sl_lidar.h"
#include "sl_lidar_driver.h"
using namespace sl;

// 1. 创建串口通道 (A2M6 波特率为 115200)
IChannel* channel = *createSerialPortChannel("/dev/ttyUSB1", 115200);

// 2. 创建雷达驱动
ILidarDriver* drv = *createLidarDriver();

// 3. 连接雷达
sl_result res = drv->connect(channel);
if (!SL_IS_OK(res)) {
    printf("连接失败: 0x%x\n", res);
    return -1;
}

// 4. 获取设备信息
sl_lidar_response_device_info_t devinfo;
drv->getDeviceInfo(devinfo);
printf("型号: %d, 固件: %d.%d\n",
       devinfo.model,
       devinfo.firmware_version >> 8,
       devinfo.firmware_version & 0xFF);

// 5. 检查健康状态
sl_lidar_response_device_health_t health;
drv->getHealth(health);
if (health.status != SL_LIDAR_STATUS_OK) {
    printf("雷达异常，状态: %d\n", health.status);
    drv->reset();  // 尝试重置
}

// 6. 启动电机 (A系列必须)
drv->setMotorSpeed(600);  // 设置转速 600RPM

// 7. 启动扫描
LidarScanMode scanMode;
drv->startScan(false, true, 0, &scanMode);
printf("扫描模式: %s, 最大距离: %.1fm\n",
       scanMode.scan_mode, scanMode.max_distance);

// 8. 获取扫描数据
sl_lidar_response_measurement_node_hq_t nodes[8192];
size_t count = sizeof(nodes) / sizeof(nodes[0]);
res = drv->grabScanDataHq(nodes, count);

if (SL_IS_OK(res)) {
    // 9. 数据排序（按角度升序）
    drv->ascendScanData(nodes, count);

    // 10. 解析数据
    for (size_t i = 0; i < count; i++) {
        float angle = nodes[i].angle_z_q14 * 90.0f / 16384.0f;  // 角度(度)
        float distance = nodes[i].dist_mm_q2 / 4.0f / 1000.0f;  // 距离(米)
        uint8_t quality = nodes[i].quality >> 2;  // 信号质量

        if (distance > 0) {
            printf("角度: %6.2f°, 距离: %6.3fm, 质量: %d\n",
                   angle, distance, quality);
        }
    }
}

// 11. 停止扫描和电机
drv->stop();
drv->setMotorSpeed(0);

// 12. 释放资源
delete drv;
delete channel;
```

### 2.3 数据结构详解

```cpp
typedef struct sl_lidar_response_measurement_node_hq_t {
    _u16 angle_z_q14;   // 角度，Q14定点数
    _u32 dist_mm_q2;    // 距离(mm)，Q2定点数
    _u8  quality;       // 信号质量 (0-255)
    _u8  flag;          // 标志位，bit0为同步位
} __attribute__((packed)) sl_lidar_response_measurement_node_hq_t;
```

**解析公式**：
```cpp
// 角度计算
float angle_deg = node.angle_z_q14 * 90.0f / 16384.0f;

// 距离计算
float distance_m = node.dist_mm_q2 / 4.0f / 1000.0f;

// 质量计算
uint8_t quality = node.quality >> 2;

// 判断是否为新的一圈起始点
bool is_new_scan = (node.flag & SL_LIDAR_RESP_HQ_FLAG_SYNCBIT) != 0;
```

### 2.4 编译 SDK 示例程序

```bash
cd /path/to/rplidar_sdk-master
make clean
make

# 生成的可执行文件在 output/Linux/Release/

# 运行测试 (注意修改串口为 USB1)
./output/Linux/Release/ultra_simple --channel --serial /dev/ttyUSB1 115200
```

---

## 三、ROS2 部署

### 3.1 创建工作空间

```bash
# 创建ROS2工作空间
mkdir -p ~/ros2_ws/src
cd ~/ros2_ws/src

# 复制rplidar_ros包
cp -r /path/to/rplidar_ros-ros2 ./rplidar_ros
```

### 3.2 修改Launch文件（适配A2M6 + USB1）

创建新的启动文件 `rplidar_a2m6_launch.py`：

```python
#!/usr/bin/env python3

import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

def generate_launch_description():
    # A2M6 参数配置
    channel_type = LaunchConfiguration('channel_type', default='serial')
    serial_port = LaunchConfiguration('serial_port', default='/dev/ttyUSB1')  # 注意改为USB1
    serial_baudrate = LaunchConfiguration('serial_baudrate', default='115200')  # A2M6波特率
    frame_id = LaunchConfiguration('frame_id', default='laser')
    inverted = LaunchConfiguration('inverted', default='false')
    angle_compensate = LaunchConfiguration('angle_compensate', default='true')
    scan_mode = LaunchConfiguration('scan_mode', default='Sensitivity')  # A2M6推荐模式

    return LaunchDescription([
        DeclareLaunchArgument(
            'channel_type',
            default_value=channel_type,
            description='通信类型: serial/tcp/udp'),

        DeclareLaunchArgument(
            'serial_port',
            default_value=serial_port,
            description='串口设备路径'),

        DeclareLaunchArgument(
            'serial_baudrate',
            default_value=serial_baudrate,
            description='A2M6波特率: 115200'),

        DeclareLaunchArgument(
            'frame_id',
            default_value=frame_id,
            description='雷达坐标系ID'),

        DeclareLaunchArgument(
            'inverted',
            default_value=inverted,
            description='是否反转雷达数据'),

        DeclareLaunchArgument(
            'angle_compensate',
            default_value=angle_compensate,
            description='是否启用角度补偿'),

        DeclareLaunchArgument(
            'scan_mode',
            default_value=scan_mode,
            description='扫描模式: Sensitivity/Standard'),

        Node(
            package='rplidar_ros',
            executable='rplidar_node',
            name='rplidar_node',
            parameters=[{
                'channel_type': channel_type,
                'serial_port': serial_port,
                'serial_baudrate': serial_baudrate,
                'frame_id': frame_id,
                'inverted': inverted,
                'angle_compensate': angle_compensate,
                'scan_mode': scan_mode,
            }],
            output='screen',
        ),
    ])
```

将文件保存到 `rplidar_ros/launch/rplidar_a2m6_launch.py`

### 3.3 创建可视化启动文件

创建 `view_rplidar_a2m6_launch.py`：

```python
#!/usr/bin/env python3

import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

def generate_launch_description():
    return LaunchDescription([
        # 启动雷达节点
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([
                os.path.join(
                    get_package_share_directory('rplidar_ros'),
                    'launch',
                    'rplidar_a2m6_launch.py'
                )
            ])
        ),

        # 启动RViz可视化
        Node(
            package='rviz2',
            executable='rviz2',
            name='rviz2',
            arguments=[
                '-d', os.path.join(
                    get_package_share_directory('rplidar_ros'),
                    'rviz',
                    'rplidar_ros.rviz'
                )
            ],
            output='screen',
        ),
    ])
```

### 3.4 配置串口权限

**方法一：临时权限（每次重启需重新执行）**
```bash
sudo chmod 666 /dev/ttyUSB1
```

**方法二：永久udev规则（推荐）**

创建规则文件 `99-rplidar.rules`：
```bash
sudo nano /etc/udev/rules.d/99-rplidar.rules
```

添加内容：
```
# RPLidar A2M6 (使用USB1)
KERNEL=="ttyUSB[1-9]", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", MODE="0666", SYMLINK+="rplidar"
```

应用规则：
```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

重新插拔USB后，雷达设备将同时可通过 `/dev/rplidar` 访问。

### 3.5 编译

```bash
cd ~/ros2_ws
source /opt/ros/humble/setup.bash
colcon build --packages-select rplidar_ros
source install/setup.bash

# 添加到bashrc
echo "source ~/ros2_ws/install/setup.bash" >> ~/.bashrc
```

---

## 四、测试与验证

### 4.1 检查设备连接

```bash
# 查看USB设备
ls -la /dev/ttyUSB*

# 确认设备属性
udevadm info -a /dev/ttyUSB1 | grep -E "idVendor|idProduct|serial"

# 测试串口
sudo apt install minicom
sudo minicom -D /dev/ttyUSB1 -b 115200
```

### 4.2 启动雷达节点

```bash
# 启动雷达节点
ros2 launch rplidar_ros rplidar_a2m6_launch.py

# 带RViz可视化启动
ros2 launch rplidar_ros view_rplidar_a2m6_launch.py
```

### 4.3 验证数据

```bash
# 新开终端

# 查看话题列表
ros2 topic list
# 预期输出包含: /scan

# 查看扫描数据
ros2 topic echo /scan

# 查看话题信息
ros2 topic info /scan
# 预期: Type: sensor_msgs/msg/LaserScan

# 查看发布频率
ros2 topic hz /scan
# 预期: average rate ~10 Hz

# 查看数据内容
ros2 topic echo /scan --once
```

### 4.4 RViz 配置

在RViz中添加 LaserScan 显示：
1. 点击左下角 `Add`
2. 选择 `By topic` → `/scan` → `LaserScan`
3. 设置 `Fixed Frame` 为 `laser`
4. 调整 `Size` 和 `Color` 以便观察

---

## 五、TF 坐标系配置

### 5.1 坐标系结构

```
map
 └── odom
      └── base_link
           └── laser_link (雷达安装位置)
```

### 5.2 发布静态TF

假设雷达安装在车体前方 0.2m，中心偏左 0.05m，高度 0.15m：

```bash
# 发布 base_link -> laser_link 变换
ros2 run tf2_ros static_transform_publisher \
    0.2 0.05 0.15 0 0 0 base_link laser_link
```

**参数说明**：
- `x=0.2`: 雷达在车体前方 20cm
- `y=0.05`: 雷达在车体左侧 5cm
- `z=0.15`: 雷达高度 15cm
- `roll=0, pitch=0, yaw=0`: 无旋转

### 5.3 在Launch文件中添加TF

```python
# 在 LaunchDescription 中添加
Node(
    package='tf2_ros',
    executable='static_transform_publisher',
    name='laser_tf_publisher',
    arguments=['0.2', '0.05', '0.15', '0', '0', '0', 'base_link', 'laser_link'],
),
```

### 5.4 验证TF

```bash
# 查看TF树
ros2 run tf2_tools view_frames
# 生成 frames.pdf 文件

# 查看特定变换
ros2 run tf2_ros tf2_echo base_link laser_link
```

---

## 六、仿真环境搭建

### 6.1 安装仿真工具

```bash
# 安装Gazebo（需要RDK X5性能支持）
sudo apt install ros-humble-gazebo-ros-pkgs

# 安装导航相关包
sudo apt install ros-humble-nav2-bringup
sudo apt install ros-humble-slam-toolbox
sudo apt install ros-humble-robot-localization
```

### 6.2 创建机器人描述

创建 `robot.urdf.xacro`：

```xml
<?xml version="1.0"?>
<robot name="my_robot" xmlns:xacro="http://www.ros.org/wiki/xacro">

  <!-- 基座 -->
  <link name="base_link">
    <visual>
      <geometry><box size="0.6 0.4 0.2"/></geometry>
      <material name="blue">
        <color rgba="0 0 0.8 1"/>
      </material>
    </visual>
    <collision>
      <geometry><box size="0.6 0.4 0.2"/></geometry>
    </collision>
  </link>

  <!-- 雷达支架 -->
  <link name="laser_link">
    <visual>
      <geometry><cylinder radius="0.05" length="0.08"/></geometry>
      <material name="black">
        <color rgba="0 0 0 1"/>
      </material>
    </visual>
  </link>

  <!-- 雷达坐标系 (A2M6 实际扫描中心) -->
  <joint name="laser_joint" type="fixed">
    <parent link="base_link"/>
    <child link="laser_link"/>
    <origin xyz="0.2 0.05 0.15" rpy="0 0 0"/>
  </joint>

  <!-- 地盘坐标系 -->
  <link name="base_footprint"/>
  <joint name="base_footprint_joint" type="fixed">
    <parent link="base_footprint"/>
    <child link="base_link"/>
    <origin xyz="0 0 0.1" rpy="0 0 0"/>
  </joint>

</robot>
```

### 6.3 Gazebo 世界配置

创建 `gazebo_world.launch.py`：

```python
import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node

def generate_launch_description():
    pkg_path = get_package_share_directory('my_robot_description')
    urdf_file = os.path.join(pkg_path, 'urdf', 'robot.urdf.xacro')

    return LaunchDescription([
        # 启动Gazebo
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([
                os.path.join(
                    get_package_share_directory('gazebo_ros'),
                    'launch',
                    'gazebo.launch.py'
                )
            ]),
            launch_arguments={'world': 'empty_world'}.items()
        ),

        # 生成机器人状态
        Node(
            package='robot_state_publisher',
            executable='robot_state_publisher',
            parameters=[{'robot_description': open(urdf_file).read()}]
        ),

        # 在Gazebo中生成机器人
        Node(
            package='gazebo_ros',
            executable='spawn_entity.py',
            arguments=['-topic', 'robot_description', '-entity', 'my_robot']
        ),
    ])
```

---

## 七、实车集成

### 7.1 完整启动脚本

创建 `robot_bringup.launch.py`：

```python
#!/usr/bin/env python3

import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node, PushRosNamespace

def generate_launch_description():
    use_sim_time = LaunchConfiguration('use_sim_time', default='false')

    return LaunchDescription([
        DeclareLaunchArgument(
            'use_sim_time',
            default_value='false',
            description='Use simulation time'),

        # 雷达节点
        Node(
            package='rplidar_ros',
            executable='rplidar_node',
            name='rplidar_node',
            parameters=[{
                'serial_port': '/dev/ttyUSB1',
                'serial_baudrate': 115200,
                'frame_id': 'laser_link',
                'angle_compensate': True,
                'scan_mode': 'Sensitivity',
                'use_sim_time': use_sim_time,
            }],
            output='screen',
        ),

        # TF变换: base_link -> laser_link
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='laser_tf_publisher',
            arguments=['0.2', '0.05', '0.15', '0', '0', '0', 'base_link', 'laser_link'],
            parameters=[{'use_sim_time': use_sim_time}],
        ),

        # 可以添加底盘驱动节点
        # Node(
        #     package='my_chassis_driver',
        #     executable='chassis_node',
        #     ...
        # ),
    ])
```

### 7.2 配置里程计

如果使用底盘编码器，需要发布 `odom -> base_link` TF：

```python
# 里程计节点示例
Node(
    package='robot_localization',
    executable='ekf_node',
    name='ekf_filter_node',
    parameters=[os.path.join(pkg_path, 'config', 'ekf.yaml')],
),
```

### 7.3 参数配置文件

创建 `config/rplidar_params.yaml`：

```yaml
rplidar_node:
  ros__parameters:
    channel_type: "serial"
    serial_port: "/dev/ttyUSB1"
    serial_baudrate: 256000
    frame_id: "laser_link"
    inverted: false
    angle_compensate: true
    flip_x_axis: false
    auto_standby: false
    scan_mode: "Sensitivity"
    scan_frequency: 10.0
    topic_name: "scan"
```

---

## 八、SLAM 建图

### 8.1 安装 SLAM 工具

```bash
# Slam Toolbox (推荐，轻量级)
sudo apt install ros-humble-slam-toolbox

# 或 Cartographer (精度更高，资源消耗大)
sudo apt install ros-humble-cartographer ros-humble-cartographer-ros
```

### 8.2 使用 Slam Toolbox 建图

创建 `slam_launch.py`：

```python
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os

def generate_launch_description():
    slam_toolbox_dir = get_package_share_directory('slam_toolbox')

    return LaunchDescription([
        # Slam Toolbox 在线建图
        Node(
            package='slam_toolbox',
            executable='async_slam_toolbox_node',
            name='slam_toolbox',
            parameters=[
                os.path.join(slam_toolbox_dir, 'config', 'mapper_params_online_async.yaml'),
                {'use_sim_time': False}
            ],
            output='screen',
        ),
    ])
```

启动建图：

```bash
# 终端1：启动机器人
ros2 launch my_robot robot_bringup.launch.py

# 终端2：启动建图
ros2 launch my_robot slam_launch.py

# 终端3：启动键盘控制
ros2 run teleop_twist_keyboard teleop_twist_keyboard
```

### 8.3 保存地图

```bash
# 保存地图到指定路径
ros2 run nav2_map_server map_saver_cli -f ~/maps/my_map

# 生成两个文件：
# my_map.pgm - 地图图像
# my_map.yaml - 地图配置
```

### 8.4 使用 Cartographer 建图（可选）

创建 `cartographer.launch.py`：

```python
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os

def generate_launch_description():
    cartographer_config_dir = os.path.join(
        get_package_share_directory('cartographer_ros'),
        'configuration_files'
    )
    configuration_basename = 'my_robot.lua'

    return LaunchDescription([
        Node(
            package='cartographer_ros',
            executable='cartographer_node',
            name='cartographer_node',
            arguments=[
                '-configuration_directory', cartographer_config_dir,
                '-configuration_basename', configuration_basename
            ],
            parameters=[{'use_sim_time': False}],
            output='screen',
        ),

        Node(
            package='cartographer_ros',
            executable='cartographer_occupancy_grid_node',
            name='occupancy_grid_node',
            parameters=[
                {'use_sim_time': False},
                {'resolution': 0.05}
            ],
            output='screen',
        ),
    ])
```

---

## 九、Nav2 导航

### 9.1 安装 Nav2

```bash
sudo apt install ros-humble-navigation2
sudo apt install ros-humble-nav2-bringup
```

### 9.2 Nav2 配置文件

创建 `config/nav2_params.yaml`：

```yaml
bt_navigator:
  ros__parameters:
    global_frame: map
    robot_base_frame: base_link
    odom_topic: /odom
    bt_loop_duration: 10
    default_server_timeout: 20

controller_server:
  ros__parameters:
    controller_frequency: 20.0
    controller_plugins: ["FollowPath"]
    FollowPath:
      plugin: "dwb_core::DWBLocalPlanner"
      min_vel_x: 0.0
      max_vel_x: 0.5
      max_vel_theta: 1.0
      min_speed_xy: 0.1
      max_speed_xy: 0.5

planner_server:
  ros__parameters:
    planner_plugins: ["GridBased"]
    GridBased:
      plugin: "nav2_navfn_planner/NavfnPlanner"
      tolerance: 0.5

behavior_server:
  ros__parameters:
    costmap_topic: local_costmap/costmap_raw
    footprint_topic: local_costmap/published_footprint
    cycle_frequency: 10.0
    behavior_plugins: ["spin", "backup", "drive_on_heading", "wait"]
    spin:
      plugin: "nav2_behaviors/Spin"
    backup:
      plugin: "nav2_behaviors/BackUp"
```

### 9.3 导航启动文件

创建 `navigation_launch.py`：

```python
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, DeclareLaunchArgument
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os

def generate_launch_description():
    nav2_bringup_dir = get_package_share_directory('nav2_bringup')
    map_file = LaunchConfiguration('map')

    return LaunchDescription([
        DeclareLaunchArgument(
            'map',
            default_value=os.path.expanduser('~/maps/my_map.yaml'),
            description='Full path to map yaml file'),

        # Nav2 导航栈
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([
                os.path.join(nav2_bringup_dir, 'launch', 'bringup_launch.py')
            ]),
            launch_arguments={
                'map': map_file,
                'use_sim_time': 'False',
            }.items()
        ),
    ])
```

### 9.4 启动导航

```bash
# 终端1：启动机器人
ros2 launch my_robot robot_bringup.launch.py

# 终端2：启动导航
ros2 launch my_robot navigation_launch.py map:=~/maps/my_map.yaml

# 终端3：启动RViz
rviz2
```

在RViz中：
1. 设置 `Fixed Frame` 为 `map`
2. 添加 `Map` 显示，话题为 `/map`
3. 添加 `LaserScan` 显示
4. 添加 `Path` 显示
5. 使用 `2D Pose Estimate` 设置初始位姿
6. 使用 `Nav2 Goal` 设置导航目标

---

## 十、故障排查

### 10.1 雷达连接问题

| 问题 | 可能原因 | 解决方案 |
|------|----------|----------|
| 找不到 /dev/ttyUSB1 | USB未识别 | 检查USB线、执行 `dmesg \| tail` |
| 权限被拒绝 | 权限不足 | `sudo chmod 666 /dev/ttyUSB1` 或配置udev |
| 连接超时 | 波特率错误 | 确认A2M6使用115200 |
| 设备忙 | 其他程序占用 | `lsof /dev/ttyUSB1` 查看占用进程 |

### 10.2 数据异常

| 问题 | 可能原因 | 解决方案 |
|------|----------|----------|
| 无数据 | 电机未启动 | A系列需调用 `setMotorSpeed()` |
| 数据全0 | 雷达遮挡 | 检查雷达视野是否被遮挡 |
| 数据跳变 | 电磁干扰 | 远离电机、电源等干扰源 |
| 点云稀疏 | 扫描模式错误 | 尝试不同 scan_mode |

### 10.3 TF 问题

```bash
# 查看TF树
ros2 run tf2_tools view_frames

# 检查特定变换
ros2 run tf2_ros tf2_echo base_link laser_link

# 常见错误
# - "Frame does not exist": 检查TF是否正确发布
# - "Extrapolation into the future": 时间戳问题，检查use_sim_time
```

### 10.4 调试命令

```bash
# 查看节点信息
ros2 node list
ros2 node info /rplidar_node

# 查看话题信息
ros2 topic list
ros2 topic hz /scan
ros2 topic bw /scan

# 查看参数
ros2 param list /rplidar_node
ros2 param get /rplidar_node serial_baudrate

# 录制数据
ros2 bag record /scan /tf

# 播放数据
ros2 bag play recorded_bag.db3
```

---

## 十一、开发流程总结

```
┌─────────────────────────────────────────────────────────────────┐
│                RDK X5 + RPLidar A2M6 开发流程                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Step 1: SDK理解                                                 │
│  ├─ 阅读 ultra_simple/main.cpp                                   │
│  ├─ 理解 Channel + Driver 架构                                   │
│  ├─ 理解数据结构 sl_lidar_response_measurement_node_hq_t         │
│  └─ 测试命令: ./ultra_simple --channel --serial /dev/ttyUSB1 115200 │
│                                                                  │
│  Step 2: ROS2部署                                                │
│  ├─ 创建工作空间 ~/ros2_ws/src                                   │
│  ├─ 复制 rplidar_ros 包                                          │
│  ├─ 创建 rplidar_a2m6_launch.py (波特率115200, 串口/dev/ttyUSB1) │
│  ├─ 配置 udev 规则                                               │
│  ├─ colcon build 编译                                            │
│  └─ 测试: ros2 launch rplidar_ros rplidar_a2m6_launch.py         │
│                                                                  │
│  Step 3: 仿真验证                                                │
│  ├─ 安装 Gazebo + Nav2                                           │
│  ├─ 创建机器人 URDF 模型                                         │
│  ├─ 配置 TF 坐标系                                               │
│  └─ 在仿真中测试雷达数据流                                        │
│                                                                  │
│  Step 4: 实车集成                                                │
│  ├─ 确定雷达安装位置 → 更新TF                                    │
│  ├─ 配置底盘驱动节点                                              │
│  ├─ 配置里程计 → 发布 odom→base_link                             │
│  └─ 整合启动脚本                                                 │
│                                                                  │
│  Step 5: SLAM建图                                                │
│  ├─ 安装 slam_toolbox                                            │
│  ├─ 启动建图: ros2 launch slam_toolbox online_async_launch.py    │
│  ├─ 控制机器人移动采集数据                                        │
│  └─ 保存地图: ros2 run nav2_map_server map_saver_cli -f my_map   │
│                                                                  │
│  Step 6: 自主导航                                                │
│  ├─ 安装 Nav2                                                    │
│  ├─ 配置 nav2_params.yaml                                        │
│  ├─ 启动导航: ros2 launch nav2_bringup bringup_launch.py         │
│  └─ 在RViz中设置目标点                                            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 附录A: A2M6 技术参数

| 参数 | 规格 |
|------|------|
| 型号 | RPLIDAR A2M6 |
| 测距原理 | 三角测距 |
| 测距范围 | 0.15m - 12m (室内) |
| 测距精度 | < 1% (典型值) |
| 角度分辨率 | 0.3375° |
| 扫描角度 | 360° |
| 扫描频率 | 10 Hz (可调 5-15Hz) |
| 采样率 | 8000 samples/sec |
| 通信接口 | USB 2.0 (虚拟串口) |
| 波特率 | 115200 bps |
| 供电电压 | 5V DC |
| 功耗 | < 2.5W |
| 尺寸 | 76mm × 41.5mm |
| 重量 | < 150g |

---

## 附录B: 常用命令速查

```bash
# ===== 设备检查 =====
ls /dev/ttyUSB*                    # 查看串口设备
dmesg | grep ttyUSB                # 查看设备日志
udevadm info -a /dev/ttyUSB1       # 查看设备属性

# ===== 权限设置 =====
sudo chmod 666 /dev/ttyUSB1        # 临时权限
sudo ./create_udev_rules.sh        # 永久规则

# ===== ROS2 命令 =====
ros2 launch rplidar_ros rplidar_a2m6_launch.py    # 启动雷达
ros2 topic echo /scan                              # 查看数据
ros2 topic hz /scan                                # 查看频率
ros2 run tf2_tools view_frames                     # 查看TF树

# ===== SLAM 命令 =====
ros2 launch slam_toolbox online_async_launch.py   # 启动建图
ros2 run nav2_map_server map_saver_cli -f my_map  # 保存地图

# ===== 导航命令 =====
ros2 launch nav2_bringup bringup_launch.py map:=/path/to/map.yaml  # 启动导航

# ===== 调试命令 =====
ros2 node list                     # 查看节点
ros2 topic list                    # 查看话题
ros2 bag record /scan /tf          # 录制数据
ros2 bag play recording.db3        # 回放数据
```

---

## 附录C: 关键文件路径

| 功能 | 文件位置 |
|------|----------|
| SDK核心API | `rplidar_sdk-master/sdk/include/sl_lidar_driver.h` |
| 数据类型定义 | `rplidar_sdk-master/sdk/include/sl_types.h` |
| 最简示例 | `rplidar_sdk-master/app/ultra_simple/main.cpp` |
| ROS2节点实现 | `rplidar_ros-ros2/src/rplidar_node.cpp` |
| Launch配置 | `rplidar_ros-ros2/launch/rplidar_a2m6_launch.py` |

---

**文档版本**: v1.0
**适用雷达**: RPLidar A2M6
**适用平台**: RDK X5 + ROS2 Humble
**创建日期**: 2026-06-09
