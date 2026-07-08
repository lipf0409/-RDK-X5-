#!/bin/bash
# QT 监控界面 - 开机自启脚本
# lightdm 已经启动 Xorg，直接使用

LOG="/tmp/qt_monitor_startup.log"
echo "$(date) Starting QT monitor..." > $LOG

export DISPLAY=:0
export XAUTHORITY=/var/run/lightdm/root/:0

# Source ROS2
source /opt/tros/humble/setup.bash
source /home/sunrise/ucar_01/install/setup.bash
unset RMW_FASTRTPS_USE_QOS_FROM_XML
unset FASTRTPS_DEFAULT_PROFILES_FILE

# 用 PySide6 的 QT 插件
export QT_QPA_PLATFORM=xcb
export QT_QPA_PLATFORM_PLUGIN_PATH=/usr/local/lib/python3.10/dist-packages/PySide6/Qt/plugins/platforms

cd /home/sunrise/ucar_01
python3 qt_monitor/main.py >> $LOG 2>&1
