#!/usr/bin/env python3
"""
Windows 独立火焰检测脚本
────────────────────────────
技术路线（与板端 vision_monitor.py 的 detect_fire_color() 完全一致）：
  1. BGR → HSV 颜色空间转换
  2. 火焰颜色双阈值 (橙红 + 黄色范围)
  3. 形态学去噪 (开运算 + 闭运算)
  4. 连通区域分析 → 过滤小噪点
  5. 持续检测 > 阈值 → 触发报警

运行：
  python fire_detector_standalone.py               # 使用默认摄像头
  python fire_detector_standalone.py --camera 1    # 使用第二个摄像头
  python fire_detector_standalone.py --video fire_test.mp4
"""

import cv2
import numpy as np
import argparse
import time
import sys
from pathlib import Path
from datetime import datetime


# ── 颜色定义 ──
class Colors:
    RED = '\033[91m'
    YELLOW = '\033[93m'
    GREEN = '\033[92m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


class FireDetector:
    """
    火焰检测器

    与板端 VisionMonitor.detect_fire_color() 算法完全一致：
      - HSV 双范围 (红-橙-黄)
      - 形态学开闭运算去噪
      - 连通区域面积过滤
      - 持续触发机制
    """

    def __init__(self,
                 fire_threshold=0.01,          # 火焰像素占比触发阈值
                 fire_duration=1.5,            # 持续时间（秒）
                 fire_cooldown=5.0,            # 报警冷却（秒）
                 min_contour_area=500):        # 最小火焰连通区域
        self.fire_threshold = fire_threshold
        self.fire_duration = fire_duration
        self.fire_cooldown = fire_cooldown
        self.min_contour_area = min_contour_area

        # ── 火焰 HSV 范围（与板端完全一致） ──
        # 范围1: 橙红色 (0° ~ 25°)
        self.lower1 = np.array([0, 100, 180])
        self.upper1 = np.array([25, 255, 255])
        # 范围2: 深红色 (160° ~ 180°)
        self.lower2 = np.array([160, 100, 180])
        self.upper2 = np.array([180, 255, 255])

        # 形态学核
        self.kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

        # ── 状态机 ──
        self.fire_counter = 0.0
        self.last_alarm_time = 0.0
        self.last_update_time = time.time()

        # ── 截图 ──
        self.screenshot_dir = Path(__file__).parent / 'screenshots' / 'fire'
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    # ═══════════════════════════════════════════════
    # 火焰检测核心 (与板端 detect_fire_color() 一致)
    # ═══════════════════════════════════════════════

    def detect_fire(self, frame):
        """
        检测帧中的火焰

        返回: (fire_score, fire_mask, contours)
          fire_score: 0.0 ~ 1.0 火焰置信度
          fire_mask: 火焰像素mask (用于可视化)
          contours: 火焰连通区域列表
        """
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # 双阈值 mask
        mask1 = cv2.inRange(hsv, self.lower1, self.upper1)
        mask2 = cv2.inRange(hsv, self.lower2, self.upper2)
        mask = cv2.bitwise_or(mask1, mask2)

        # 形态学去噪 (与板端一致)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self.kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self.kernel)

        # 火焰像素占比
        total_pixels = mask.shape[0] * mask.shape[1]
        fire_pixels = np.sum(mask > 0)
        fire_ratio = fire_pixels / total_pixels

        # 连通区域分析
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                        cv2.CHAIN_APPROX_SIMPLE)
        large_fire = [c for c in contours if cv2.contourArea(c) > self.min_contour_area]

        # 火焰置信度
        fire_score = 0.0
        if fire_ratio > 0.001 and len(large_fire) > 0:
            # 归一化: fire_ratio * 10, 上限 1.0 (与板端一致)
            fire_score = min(1.0, fire_ratio * 10.0)

        return fire_score, mask, large_fire

    # ═══════════════════════════════════════════════
    # 判决逻辑
    # ═══════════════════════════════════════════════

    def judge_fire(self, fire_score):
        """
        时序验证：火情需要持续存在才触发报警

        返回: (is_fire_alarm, fire_counter)
        """
        now = time.time()
        dt = now - self.last_update_time
        self.last_update_time = now

        if fire_score > 0.3:
            # 有火焰 → 累积
            self.fire_counter += fire_score * dt * 0.5
        else:
            # 无火焰 → 衰减
            self.fire_counter = max(0.0, self.fire_counter - dt * 0.1)

        alarm_triggered = False
        if self.fire_counter >= self.fire_duration:
            if now - self.last_alarm_time > self.fire_cooldown:
                alarm_triggered = True
                self.last_alarm_time = now
                self.fire_counter = 0.0

        return alarm_triggered, self.fire_counter

    # ═══════════════════════════════════════════════
    # 可视化
    # ═══════════════════════════════════════════════

    def draw_fire(self, frame, fire_mask, contours, fire_score, fire_counter,
                  alarm_triggered):
        """绘制火焰检测结果"""
        h, w = frame.shape[:2]

        # 火焰区域高亮
        if fire_score > 0.01:
            fire_overlay = frame.copy()
            fire_overlay[fire_mask > 0] = (0, 0, 255)  # 红色标记火焰像素
            cv2.addWeighted(fire_overlay, 0.4, frame, 0.6, 0, frame)

        # 绘制火焰轮廓
        for cnt in contours:
            if cv2.contourArea(cnt) > self.min_contour_area:
                cv2.drawContours(frame, [cnt], -1, (0, 165, 255), 3)

        # ── 报警横幅 ──
        if alarm_triggered:
            overlay = frame.copy()
            cv2.rectangle(overlay, (0, 0), (w, 80), (0, 0, 255), -1)
            cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
            cv2.putText(frame, "!!! FIRE DETECTED !!!", (w // 2 - 200, 55),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)

        # ── 信息面板 ──
        panel_x = 10
        panel_y = h - 130

        overlay = frame.copy()
        cv2.rectangle(overlay, (panel_x, panel_y), (280, h), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)

        y = panel_y + 25
        lines = [
            f"Fire Score: {fire_score:.3f}",
            f"Fire Counter: {fire_counter:.2f}s",
            f"Contours: {len(contours)}",
            f"Threshold: {self.fire_threshold}",
        ]

        for line in lines:
            color = (200, 200, 200)
            if 'Counter' in line and fire_counter > 0.5:
                color = (0, 0, 255)
            elif 'Score' in line and fire_score > 0.3:
                color = (0, 0, 255)

            cv2.putText(frame, line, (panel_x + 10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
            y += 22

        return frame


def main():
    parser = argparse.ArgumentParser(description='Windows Standalone Fire Detector')
    parser.add_argument('--camera', type=int, default=0, help='Camera index')
    parser.add_argument('--video', type=str, default=None, help='Video file path')
    parser.add_argument('--fire-threshold', type=float, default=0.01,
                        help='Fire pixel ratio threshold (default: 0.01)')
    parser.add_argument('--duration', type=float, default=1.5,
                        help='Fire duration before alarm (seconds, default: 1.5)')
    parser.add_argument('--cooldown', type=float, default=5.0,
                        help='Alarm cooldown (seconds, default: 5.0)')
    args = parser.parse_args()

    print(f"{Colors.BOLD}{Colors.CYAN}")
    print("=" * 60)
    print("  Windows 火焰检测 — Standalone Test")
    print("  (与板端 detect_fire_color() 算法一致)")
    print("=" * 60)
    print(f"{Colors.RESET}")

    detector = FireDetector(
        fire_threshold=args.fire_threshold,
        fire_duration=args.duration,
        fire_cooldown=args.cooldown)

    if args.video:
        cap = cv2.VideoCapture(args.video)
        window_name = f'Fire Detector - {args.video}'
    else:
        cap = cv2.VideoCapture(args.camera)
        window_name = f'Fire Detector - Camera {args.camera}'

    if not cap.isOpened():
        print(f"{Colors.RED}Cannot open video source!{Colors.RESET}")
        sys.exit(1)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    print(f"{Colors.GREEN}Press 'q' to quit, 's' to save screenshot{Colors.RESET}")

    fps_counter = 0
    fps_timer = time.time()
    fps_display = 0.0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # 检测火焰
        fire_score, fire_mask, contours = detector.detect_fire(frame)

        # 判决
        alarm, fire_counter = detector.judge_fire(fire_score)

        # 报警
        if alarm:
            print(f"\n{Colors.RED}{Colors.BOLD}"
                  f"╔══════════════════════════════╗\n"
                  f"║  🔥 火焰报警触发！            ║\n"
                  f"║  置信度: {fire_score:.2f}                 ║\n"
                  f"╚══════════════════════════════╝"
                  f"{Colors.RESET}")

            ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
            fname = detector.screenshot_dir / f'fire_{ts}.jpg'
            cv2.imwrite(str(fname), frame)
            print(f"  Screenshot: {fname}")

        # 绘制
        frame = detector.draw_fire(frame, fire_mask, contours,
                                   fire_score, fire_counter, alarm)

        # FPS
        fps_counter += 1
        if time.time() - fps_timer > 1.0:
            fps_display = fps_counter / (time.time() - fps_timer)
            fps_counter = 0
            fps_timer = time.time()

        cv2.putText(frame, f"FPS: {fps_display:.1f}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(frame, "Q=Quit  S=Screenshot", (10, frame.shape[0] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)

        cv2.imshow(window_name, frame)
        key = cv2.waitKey(1) & 0xFF

        if key == ord('q'):
            break
        elif key == ord('s'):
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            fname = detector.screenshot_dir.parent / f'fire_manual_{ts}.jpg'
            cv2.imwrite(str(fname), frame)
            print(f"Screenshot: {fname}")

    cap.release()
    cv2.destroyAllWindows()
    print(f"\n{Colors.GREEN}Fire detector stopped.{Colors.RESET}")


if __name__ == '__main__':
    main()
