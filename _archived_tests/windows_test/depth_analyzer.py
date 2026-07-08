#!/usr/bin/env python3
"""
深度图人体检测 — PC端离线分析工具
══════════════════════════════════
加载板端录制的深度PNG文件，运行背景差分检测，交互调参。

用法:
  python depth_analyzer.py --folder ./depth_samples_floor/ --interactive
  python depth_analyzer.py --folder ./depth_samples_floor/
"""

import cv2, numpy as np, argparse, sys
from pathlib import Path
from depth_person_detector import *


def colorize_depth(d, vmin=300, vmax=5000):
    dn = np.clip((d.astype(np.float32)-vmin)/(vmax-vmin)*255, 0, 255).astype(np.uint8)
    return cv2.applyColorMap(dn, cv2.COLORMAP_TURBO)


def visualize(depth, result: DetectionResult, params: DetectParams):
    h, w = depth.shape
    out_w = w * 2 + 10
    out_h = h * 2 + 10
    viz = np.zeros((out_h, out_w, 3), dtype=np.uint8)

    # ── 左上: 深度伪彩色 + bbox + 前景 ──
    depth_viz = colorize(depth, vmin=params.depth_min, vmax=params.depth_max)
    if result.person_mask is not None:
        depth_viz[result.person_mask] = (0, 0, 255)
    if result.found and result.bbox:
        x, y, bw, bh = result.bbox
        cv2.rectangle(depth_viz, (x, y), (x+bw, y+bh), (0, 255, 0), 2)
    cv2.putText(depth_viz, f'Depth + FG mask', (5, 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255,255,255), 1)
    viz[0:h, 0:w] = depth_viz

    # ── 右上: 背景模型 ──
    if result.background is not None:
        bg_viz = colorize(result.background, vmin=params.depth_min, vmax=params.depth_max)
        cv2.putText(bg_viz, f'Background model', (5, 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255,255,255), 1)
    else:
        bg_viz = np.zeros((h, w, 3), dtype=np.uint8)
        cv2.putText(bg_viz, 'BG not ready', (w//2-40, h//2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150,150,150), 1)
    viz[0:h, w+5:w+5+w] = bg_viz

    # ── 下方: 差分热力图 ──
    if result.background is not None:
        valid = (depth > params.depth_min) & (depth < params.depth_max)
        bg_valid = (result.background > params.depth_min) & (result.background < params.depth_max)
        both = valid & bg_valid
        diff_viz = np.zeros((h, w, 3), dtype=np.uint8)
        diff_viz[:] = (30, 30, 30)
        if both.any():
            diff_vals = np.abs(depth.astype(np.float32) - result.background)
            diff_display = np.clip(diff_vals / 500.0 * 255, 0, 255).astype(np.uint8)
            diff_color = cv2.applyColorMap(diff_display, cv2.COLORMAP_HOT)
            diff_viz[both] = diff_color[both]
        # 画阈值线
        cv2.putText(diff_viz, f'|frame - bg|  (threshold={params.bg_diff_threshold}mm)', (5, 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255,255,255), 1)
    else:
        diff_viz = np.zeros((h, w, 3), dtype=np.uint8)
    viz[h+5:h+5+h, 0:w] = diff_viz

    # ── 右下: 信息面板 ──
    info = np.zeros((h, w, 3), dtype=np.uint8)
    lines = [
        f'Status: {"PERSON" if result.found else ("no person" if result.bg_ready else "BG init...")}',
        f'FG pixels: {result.foreground_pixels}',
        f'BG ready: {result.bg_ready}',
        f'Threshold: {params.bg_diff_threshold}mm',
        f'Min FG: {params.min_foreground_pixels}px',
        f'Min area: {params.min_bbox_area}px2',
        f'Depth range: {params.depth_min}-{params.depth_max}mm',
    ]
    if result.found and result.bbox:
        x, y, bw, bh = result.bbox
        lines.append(f'Bbox: {bw}x{bh} @({x},{y})')
    for i, line in enumerate(lines):
        cv2.putText(info, line, (10, 25+i*22), cv2.FONT_HERSHEY_SIMPLEX,
                    0.45, (200, 200, 200), 1)
    viz[h+5:h+5+h, w+5:w+5+w] = info

    return viz


def interactive_mode(files, params):
    cv2.namedWindow('Depth Analyzer')
    cv2.createTrackbar('Frame', 'Depth Analyzer', 0, len(files)-1, lambda v: None)
    cv2.createTrackbar('bgDiffThr (mm)', 'Depth Analyzer',
                       params.bg_diff_threshold, 1000, lambda v: None)
    cv2.createTrackbar('minFG / 100', 'Depth Analyzer',
                       params.min_foreground_pixels//100, 200, lambda v: None)
    cv2.createTrackbar('bgInitFrames', 'Depth Analyzer',
                       params.bg_init_frames, 30, lambda v: None)
    cv2.createTrackbar('depthMax (m)', 'Depth Analyzer',
                       params.depth_max//1000, 15, lambda v: None)

    last_frame_idx = -1
    detector = DepthPersonDetector(CameraParams(), params)

    while True:
        frame_idx = cv2.getTrackbarPos('Frame', 'Depth Analyzer')
        params.bg_diff_threshold = max(50, cv2.getTrackbarPos('bgDiffThr (mm)', 'Depth Analyzer'))
        params.min_foreground_pixels = max(100, cv2.getTrackbarPos('minFG / 100', 'Depth Analyzer') * 100)
        params.bg_init_frames = max(1, cv2.getTrackbarPos('bgInitFrames', 'Depth Analyzer'))
        params.depth_max = max(2000, cv2.getTrackbarPos('depthMax (m)', 'Depth Analyzer') * 1000)

        if frame_idx != last_frame_idx or detector._detect_count == 0:
            last_frame_idx = frame_idx
            detector.reset_background()
            # 用前 bg_init_frames 帧建背景
            start = max(0, frame_idx - params.bg_init_frames)
            for i in range(start, frame_idx + 1):
                d = cv2.imread(str(files[i]), cv2.IMREAD_UNCHANGED)
                detector.detect(d)

        d = cv2.imread(str(files[frame_idx]), cv2.IMREAD_UNCHANGED)
        result = detector.detect(d, return_debug=True)
        viz = visualize(d, result, params)

        h_viz, w_viz = viz.shape[:2]
        if h_viz > 800:
            s = 800 / h_viz
            viz = cv2.resize(viz, (int(w_viz*s), int(h_viz*s)))

        cv2.imshow('Depth Analyzer', viz)
        key = cv2.waitKey(100) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('n') and frame_idx < len(files)-1:
            cv2.setTrackbarPos('Frame', 'Depth Analyzer', frame_idx+1)
        elif key == ord('p') and frame_idx > 0:
            cv2.setTrackbarPos('Frame', 'Depth Analyzer', frame_idx-1)

    cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description='Depth Person Detector - PC Analysis')
    parser.add_argument('--folder', required=True, help='Folder of depth PNG files')
    parser.add_argument('--interactive', action='store_true', help='Interactive mode')
    parser.add_argument('--bg-diff', type=int, default=200, help='BG diff threshold mm')
    parser.add_argument('--depth-max', type=int, default=8000, help='Max depth mm')
    args = parser.parse_args()

    folder = Path(args.folder)
    files = sorted(list(folder.glob('*.png')))
    if not files:
        print(f'No PNG files in {folder}')
        sys.exit(1)

    params = DetectParams(
        bg_diff_threshold=args.bg_diff,
        depth_max=args.depth_max)

    if args.interactive:
        interactive_mode(files, params)
    else:
        # 批量模式
        detector = DepthPersonDetector(CameraParams(), params)
        found_count = 0
        for i, f in enumerate(files):
            d = cv2.imread(str(f), cv2.IMREAD_UNCHANGED)
            result = detector.detect(d, return_debug=False)
            if result.found:
                found_count += 1
                print(f'Frame {i}: PERSON bbox={result.bbox} fg={result.foreground_pixels}')
            elif result.bg_ready:
                print(f'Frame {i}: no person (fg={result.foreground_pixels})')
            else:
                print(f'Frame {i}: building bg...')
        print(f'\n{found_count}/{len(files)} frames with person detected')


if __name__ == '__main__':
    main()
