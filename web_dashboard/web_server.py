#!/usr/bin/env python3
"""
Web Dashboard - 实时监控画面
访问: http://<rdk_ip>:8080

画面:
  - RGB 双目相机 (MJPEG)
  - 深度图 (伪彩色)
  - 人体检测状态
  - 语音对话状态
  - 告警指示灯
"""

import sys, os, threading, time, base64, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "qt_monitor"))

from flask import Flask, render_template, Response, jsonify
import cv2
import numpy as np

app = Flask(__name__)

# ── 全局状态 (ROS2 线程写入, Flask 线程读取) ──
_lock = threading.Lock()
_state = {
    "rgb": None,          # BGR numpy array
    "depth": None,        # RGB pseudo-color numpy array
    "monitor_status": "IDLE",
    "head_height": 0.0,
    "fall_active": False,
    "fire_active": False,
    "voice_wakeup": "",
    "voice_question": "",
    "voice_answer": "",
    "fps_rgb": 0.0,
    "fps_depth": 0.0,
}


def ros2_thread():
    """后台线程: 订阅 ROS2 话题并更新 _state"""
    import rclpy
    from rclpy.node import Node
    from rclpy.executors import MultiThreadedExecutor
    from sensor_msgs.msg import Image, CompressedImage
    from std_msgs.msg import String, Float32, Bool
    from cv_bridge import CvBridge

    rclpy.init()
    node = Node("web_dashboard")
    bridge = CvBridge()

    # FPS: 消息时间戳队列 (2秒窗口)
    rgb_timestamps = []
    depth_timestamps = []

    def rgb_cb(msg: Image):
        # FPS 计数 (只计帧，不处理)
        ts = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        rgb_ts.append(ts)
        while rgb_ts and rgb_ts[0] < ts - 2.0:
            rgb_ts.pop(0)
        with _lock:
            _state["fps_rgb"] = round(len(rgb_ts) / 2.0, 1) if len(rgb_ts) > 1 else 0
        # 每3帧处理一次图像 (节省 CPU)
        if len(rgb_ts) % 3 != 0:
            return
        try:
            if msg.encoding == "nv12":
                yuv = np.frombuffer(msg.data, np.uint8).reshape(msg.height * 3 // 2, msg.width)
                bgr = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_NV12)
            else:
                bgr = bridge.imgmsg_to_cv2(msg, "bgr8")
            with _lock:
                _state["rgb"] = cv2.resize(bgr, (640, 360))
        except Exception:
            pass

    def depth_cb(msg: CompressedImage):
        ts = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        depth_ts.append(ts)
        while depth_ts and depth_ts[0] < ts - 2.0:
            depth_ts.pop(0)
        with _lock:
            _state["fps_depth"] = round(len(depth_ts) / 2.0, 1) if len(depth_ts) > 1 else 0
        # 每3帧处理一次
        if len(depth_ts) % 3 != 0:
            return
        try:
            arr = np.frombuffer(msg.data, np.uint8)
            raw = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
            if raw is not None:
                valid = (raw > 300) & (raw < 8000)
                vis = raw.astype(np.float32)
                vis[~valid] = 0
                vis[valid] = np.clip((vis[valid] - 300) / 7700 * 255, 0, 255)
                vis = vis.astype(np.uint8)
                color = cv2.applyColorMap(vis, cv2.COLORMAP_JET)
                color[~valid] = [16, 16, 32]
                with _lock:
                    _state["depth"] = cv2.resize(color, (640, 360))
        except Exception:
            pass

    rgb_ts = []
    depth_ts = []

    def monitor_cb(msg: String):
        with _lock:
            _state["monitor_status"] = msg.data

    def head_cb(msg: Float32):
        with _lock:
            _state["head_height"] = round(msg.data, 3)

    def fall_cb(msg: Bool):
        with _lock:
            _state["fall_active"] = msg.data

    def fire_cb(msg: Bool):
        with _lock:
            _state["fire_active"] = msg.data

    def voice_wake_cb(msg: String):
        with _lock:
            _state["voice_wakeup"] = msg.data[:200]

    def voice_q_cb(msg: String):
        with _lock:
            _state["voice_question"] = msg.data[:200]

    def voice_a_cb(msg: String):
        with _lock:
            _state["voice_answer"] = msg.data[:200]

    node.create_subscription(Image, "/StereoNetNode/rectified_image", rgb_cb, 10)
    node.create_subscription(CompressedImage, "/StereoNetNode/stereonet_compresseddepth", depth_cb, 10)
    node.create_subscription(String, "/monitor_status", monitor_cb, 10)
    node.create_subscription(Float32, "/person_head_height", head_cb, 10)
    node.create_subscription(Bool, "/fall_alert", fall_cb, 10)
    node.create_subscription(Bool, "/fire_alert", fire_cb, 10)
    node.create_subscription(String, "/voice/wakeup", voice_wake_cb, 10)
    node.create_subscription(String, "/voice/question", voice_q_cb, 10)
    node.create_subscription(String, "/voice/answer", voice_a_cb, 10)

    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


# ── Flask 路由 ──

@app.route("/")
def index():
    return render_template("index.html")


def _gen_mjpeg(getter):
    """MJPEG 流生成器"""
    while True:
        with _lock:
            frame = getter()
        if frame is not None:
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")
        time.sleep(0.03)


@app.route("/video/rgb")
def video_rgb():
    return Response(_gen_mjpeg(lambda: _state["rgb"]),
                    mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/video/depth")
def video_depth():
    return Response(_gen_mjpeg(lambda: _state["depth"]),
                    mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/api/state")
def api_state():
    with _lock:
        return jsonify({
            "status": _state["monitor_status"],
            "head_height": _state["head_height"],
            "fall": _state["fall_active"],
            "fire": _state["fire_active"],
            "fps_rgb": round(_state["fps_rgb"], 1),
            "fps_depth": round(_state["fps_depth"], 1),
            "voice_wakeup": _state["voice_wakeup"],
            "voice_question": _state["voice_question"],
            "voice_answer": _state["voice_answer"],
        })


def main():
    t = threading.Thread(target=ros2_thread, daemon=True)
    t.start()
    time.sleep(2)
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)


if __name__ == "__main__":
    main()
