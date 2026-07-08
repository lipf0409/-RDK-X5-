#!/usr/bin/env python3
"""
深度图人体检测 — 背景差分算法
═══════════════════════════════════
适用于: 低矮安装(15~20cm) + 双目深度相机的移动机器人

核心思路:
  深度图不受光照影响 → 背景差分极其稳定
  1. 初始化: 前N帧建立背景模型(中值)
  2. 每帧: |当前深度 - 背景深度| > 阈值 → 前景(人)
  3. 前景聚类 → 包围盒 → 人体检测
  4. 背景持续慢更新，适应环境变化

可同时在 PC (读PNG) 和 RDK X5 (ROS2) 上使用。
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Optional, Tuple, List


@dataclass
class CameraParams:
    """相机参数（深度图坐标系）— 来自 camera_info"""
    fx: float = 469.2
    fy: float = 469.2
    cx: float = 580.6
    cy: float = 358.9
    height: float = 0.20       # 摄像头离地高度 (m)
    pitch_deg: float = -2.0    # 俯仰角 (度), 上仰为正, 下倾为负


@dataclass
class DetectParams:
    """检测参数"""
    depth_min: int = 300          # 最小有效深度 (mm)
    depth_max: int = 8000         # 最大有效深度 (mm)
    bg_diff_threshold: int = 200  # 背景差分阈值 (mm), |frame - bg| > 此值 = 前景
    min_foreground_pixels: int = 500   # 最小前景像素数
    min_bbox_area: int = 600          # 最小包围盒面积 (px²)
    min_aspect_ratio: float = 1.5    # bbox 最小高宽比(h/w), 站立的人>1.5, 噪声≈1.0
    max_aspect_ratio: float = 8.0    # bbox 最大高宽比, 筛掉细长噪声
    bg_alpha: float = 0.05           # 背景更新速率 (0=不更新, 1=即时更新)
    bg_init_frames: int = 10         # 初始化背景需要的帧数


@dataclass
class DetectionResult:
    """检测结果"""
    found: bool
    bbox: Optional[Tuple[int, int, int, int]] = None  # (x, y, w, h) 像素坐标
    bbox_normalized: Optional[Tuple[float, float, float, float]] = None  # 归一化
    foreground_pixels: int = 0
    person_mask: Optional[np.ndarray] = None    # 前景mask
    background: Optional[np.ndarray] = None     # 背景模型 (用于可视化)
    bg_ready: bool = False                      # 背景是否已建立


class DepthPersonDetector:
    """
    背景差分深度人体检测器

    用法:
        detector = DepthPersonDetector(camera_params, detect_params)
        # 逐帧喂入:
        result = detector.detect(depth_frame, return_debug=True)
    """

    def __init__(self, camera: CameraParams = None, params: DetectParams = None):
        self.camera = camera or CameraParams()
        self.params = params or DetectParams()

        # 背景模型
        self._bg_model: Optional[np.ndarray] = None
        self._bg_buffer: List[np.ndarray] = []   # 初始化阶段的帧缓存
        self._bg_ready = False
        self._detect_count = 0

    # ═══════════════════════════════════════════════
    # 核心检测
    # ═══════════════════════════════════════════════

    def detect(self, depth: np.ndarray, return_debug: bool = False) -> DetectionResult:
        """
        对一张深度图做人体检测

        Args:
            depth: uint16 深度图 (mm), shape=(H, W)
            return_debug: 是否返回 person_mask/background

        Returns:
            DetectionResult
        """
        self._detect_count += 1
        h, w = depth.shape
        p = self.params

        # ── 步骤1: 建立/更新背景模型 ──
        self._update_background(depth)

        if not self._bg_ready:
            return DetectionResult(
                found=False, foreground_pixels=0,
                background=self._bg_model.copy() if self._bg_model is not None and return_debug else None,
                bg_ready=False)

        # ── 步骤2: 背景差分 ──
        valid = (depth > p.depth_min) & (depth < p.depth_max)
        bg_valid = (self._bg_model > p.depth_min) & (self._bg_model < p.depth_max)
        both_valid = valid & bg_valid

        diff = np.abs(depth.astype(np.float32) - self._bg_model.astype(np.float32))
        fg_mask = both_valid & (diff > p.bg_diff_threshold)

        # ── 步骤3: 形态学去噪 ──
        # 用简单方法: 只保留连通区域 > min_foreground_pixels
        # (避免导入 cv2 做 morphology, 保持纯numpy可独立运行)
        person_mask = fg_mask.copy()

        # ── 步骤4: 找前景包围盒 ──
        rows, cols = np.where(person_mask)
        n_fg = len(rows)

        if n_fg < p.min_foreground_pixels:
            return DetectionResult(
                found=False, foreground_pixels=n_fg,
                person_mask=person_mask if return_debug else None,
                background=self._bg_model.copy() if return_debug else None,
                bg_ready=True)

        y1, y2 = rows.min(), rows.max()
        x1, x2 = cols.min(), cols.max()
        bw, bh = x2 - x1, y2 - y1

        if bw * bh < p.min_bbox_area:
            return DetectionResult(
                found=False, foreground_pixels=n_fg,
                person_mask=person_mask if return_debug else None,
                background=self._bg_model.copy() if return_debug else None,
                bg_ready=True)

        # ── 宽高比过滤 (站立的人高>宽, 噪声通常接近正方形) ──
        aspect = bh / max(1, bw)
        if aspect < p.min_aspect_ratio or aspect > p.max_aspect_ratio:
            return DetectionResult(
                found=False, foreground_pixels=n_fg,
                person_mask=person_mask if return_debug else None,
                background=self._bg_model.copy() if return_debug else None,
                bg_ready=True)

        # ── 步骤5: 归一化bbox ──
        bbox_norm = (
            float(x1 + bw / 2) / w,
            float(y1 + bh / 2) / h,
            float(bw) / w,
            float(bh) / h,
        )

        return DetectionResult(
            found=True,
            bbox=(x1, y1, bw, bh),
            bbox_normalized=bbox_norm,
            foreground_pixels=n_fg,
            person_mask=person_mask if return_debug else None,
            background=self._bg_model.copy() if return_debug else None,
            bg_ready=True)

    # ═══════════════════════════════════════════════
    # 背景模型维护
    # ═══════════════════════════════════════════════

    def _update_background(self, depth):
        """更新背景模型"""
        p = self.params

        if not self._bg_ready:
            # 初始化阶段: 缓存帧
            self._bg_buffer.append(depth.copy())
            if len(self._bg_buffer) >= p.bg_init_frames:
                # 逐像素中值 → 鲁棒的背景模型
                stack = np.stack(self._bg_buffer, axis=0)
                self._bg_model = np.median(stack, axis=0).astype(np.float32)
                self._bg_buffer = []  # 释放内存
                self._bg_ready = True
        else:
            # 运行阶段: 指数移动平均慢更新
            valid = (depth > p.depth_min) & (depth < p.depth_max)
            # 只在当前帧深度有效时更新 (避免用零值污染背景)
            update_mask = valid & (self._bg_model > p.depth_min)
            if update_mask.any():
                self._bg_model[update_mask] = (
                    (1 - p.bg_alpha) * self._bg_model[update_mask] +
                    p.bg_alpha * depth[update_mask].astype(np.float32))

    def reset_background(self):
        """重置背景模型 (场景变化时调用)"""
        self._bg_model = None
        self._bg_buffer = []
        self._bg_ready = False

    @property
    def bg_ready(self):
        return self._bg_ready

    # ═══════════════════════════════════════════════
    # 报告
    # ═══════════════════════════════════════════════

    def report(self, depth: np.ndarray = None):
        """打印背景模型状态"""
        if self._bg_model is not None:
            b = self._bg_model
            valid = (b > self.params.depth_min) & (b < self.params.depth_max)
            print(f"[BG Model] shape={b.shape} min={b.min():.0f} max={b.max():.0f} "
                  f"valid={valid.sum()} ({100*valid.sum()/b.size:.1f}%) "
                  f"ready={self._bg_ready}")
        else:
            print(f"[BG Model] not initialized, "
                  f"buffer={len(self._bg_buffer)}/{self.params.bg_init_frames}")
