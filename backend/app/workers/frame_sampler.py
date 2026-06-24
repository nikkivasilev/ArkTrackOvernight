from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class VideoInfo:
    width: int
    height: int
    fps: float
    frame_count: int
    duration_s: float


def probe(path: str) -> VideoInfo:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {path}")
    try:
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 25.0
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = n / fps if fps > 0 else 0.0
        return VideoInfo(width=w, height=h, fps=fps, frame_count=n, duration_s=duration)
    finally:
        cap.release()


async def iter_sampled(
    path: str,
    target_fps: float,
    start_frame_idx: int = 0,
) -> AsyncIterator[tuple[int, float, np.ndarray]]:
    """Yield (frame_idx, t_seconds, bgr_frame) at the target sampling rate.

    Sequential decode only. Stride = max(1, round(native_fps / target_fps)).
    Yields control with asyncio.sleep(0) so other tasks (HTTP, WS) can run.
    """
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {path}")
    try:
        native_fps = float(cap.get(cv2.CAP_PROP_FPS)) or 25.0
        stride = max(1, round(native_fps / max(0.1, target_fps)))
        idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                return
            if idx >= start_frame_idx and idx % stride == 0:
                t_s = idx / native_fps
                yield idx, t_s, frame
                await asyncio.sleep(0)
            idx += 1
    finally:
        cap.release()


def grab_frame_at(path: str, t_seconds: float) -> np.ndarray | None:
    """Return BGR frame closest to t_seconds via sequential decode.

    Sequential because CAP_PROP_POS_FRAMES on H.264 lands on the nearest keyframe.
    Slower but correct; only used by the zone-editor scrubber.
    """
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return None
    try:
        native_fps = float(cap.get(cv2.CAP_PROP_FPS)) or 25.0
        target_idx = max(0, int(round(t_seconds * native_fps)))
        idx = 0
        last: np.ndarray | None = None
        while True:
            ok, frame = cap.read()
            if not ok:
                return last
            last = frame
            if idx >= target_idx:
                return frame
            idx += 1
    finally:
        cap.release()
