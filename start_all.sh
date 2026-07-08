#!/bin/bash
# UCar 智能监护机器人 - 一键启动 (6 节点, QT 已自启)
source /opt/tros/humble/setup.bash
source /home/sunrise/ucar_01/install/setup.bash
LOG="/tmp/ucar_startup.log"
echo "$(date) Starting ALL nodes..." > $LOG

echo "[1/6] MIPI camera..." | tee -a $LOG
taskset -c 0,1 ros2 launch mipi_cam mipi_cam_dual_channel.launch.py &
sleep 3

echo "[2/6] StereoNet depth (BPU)..." | tee -a $LOG
taskset -c 2,3 ros2 launch hobot_stereonet stereonet_model.launch.py \
    stereo_image_topic:=/image_combine_raw stereo_combine_mode:=1 need_rectify:=True alpha:=1 &
echo "  (waiting 20s for BPU...)" | tee -a $LOG
sleep 20

echo "[3/6] Person detector..." | tee -a $LOG
cd /home/sunrise/ucar_01
python3 board_person_detector_node.py --ros-args -p camera_height:=0.20 &
sleep 3

echo "[4/6] Vision monitor..." | tee -a $LOG
taskset -c 4,5 ros2 run ucar_vision vision_monitor --ros-args \
    --params-file /home/sunrise/ucar_01/src/ucar_vision/config/vision_params.yaml &
sleep 2

echo "[5/6] Alarm controller..." | tee -a $LOG
ros2 run ucar_vision alarm_controller --ros-args \
    --params-file /home/sunrise/ucar_01/src/ucar_vision/config/vision_params.yaml -p sim_mode:=true &
sleep 2

echo "[6/6] Voice assistant..." | tee -a $LOG
ros2 launch voice_assistant voice_assistant.launch.py &
sleep 2

echo "========================================" | tee -a $LOG
echo "All 6 nodes started! (QT auto-started)" | tee -a $LOG
echo "========================================" | tee -a $LOG
wait
