"""Extract a video clip from a source file between two video timestamps.

Writes VP8 WebM (browser-playable in Chrome/Firefox/Edge) via OpenCV's
VideoWriter — chosen because this deployment has no ffmpeg CLI and opencv's
H.264 (avc1) is broken by a mismatched OpenH264 DLL, whereas VP8 works
out of the box with no extra dependency. (If cross-browser/Safari H.264 is
needed later, add the bundled `imageio-ffmpeg` binary and shell out instead.)

When a `track` (timestamped bbox trajectory) is supplied the clip FOLLOWS the
worker: a fixed-size window (sized to the largest bbox over the trajectory +
`pad` context, so the subject always fits) is panned to keep the worker
centered, frame by frame, across the pre-roll and the rest. Without a track it
falls back to the full (downscaled) frame.

Synchronous decode/encode runs in a worker thread so the asyncio loop is never
blocked. One frame is held in memory at a time — safe for long clips.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_MAX_WIDTH = 1280   # downscale wide source frames (full-frame fallback only)

Track = list[tuple[float, list[int]]]


def _centers(track: Track) -> list[tuple[float, float, float]]:
    """(t, cx, cy) per trajectory sample, sorted by t."""
    out = [(t, (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0) for t, b in track]
    out.sort(key=lambda r: r[0])
    return out


def _window_size(track: Track, pad: int, fw: int, fh: int) -> tuple[int, int]:
    """Fixed crop size = largest bbox over the trajectory + 2*pad, clamped to
    the frame, even dims (VP8/yuv420p)."""
    maxw = max((b[2] - b[0]) for _, b in track)
    maxh = max((b[3] - b[1]) for _, b in track)
    win_w = min(fw, maxw + 2 * pad)
    win_h = min(fh, maxh + 2 * pad)
    win_w = max(2, win_w - (win_w % 2))
    win_h = max(2, win_h - (win_h % 2))
    return win_w, win_h


async def extract_clip(
    src: str,
    start_t: float,
    end_t: float,
    out_path: Path,
    track: Optional[Track] = None,
    pad: int = 30,
) -> bool:
    """Write [start_t, end_t] of `src` to `out_path` as VP8 WebM, following the
    worker along `track` when given. Returns success."""
    return await asyncio.to_thread(_extract_sync, src, start_t, end_t, out_path, track, pad)


def first_frame(path: Path) -> Optional[np.ndarray]:
    """Read frame 0 of a written clip (used as the alert thumbnail/poster so it
    matches the footage exactly)."""
    cap = cv2.VideoCapture(str(path))
    try:
        ok, frame = cap.read()
        return frame if ok else None
    finally:
        cap.release()


def _extract_sync(
    src: str,
    start_t: float,
    end_t: float,
    out_path: Path,
    track: Optional[Track],
    pad: int,
) -> bool:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    start = max(0.0, float(start_t))
    end = float(end_t)
    if end <= start:
        return False

    centers = _centers(track) if track else []
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        logger.warning("clip: cannot open source %s", src)
        return False
    writer: cv2.VideoWriter | None = None
    win: Optional[tuple[int, int]] = None
    fw = fh = 0
    ci = 0          # advancing pointer into `centers` (frames are read in time order)
    written = 0
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 25.0
        # Seek near the start (lands on the nearest preceding keyframe → a little
        # extra pre-roll, which is acceptable for review).
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(start * fps))
        fourcc = cv2.VideoWriter_fourcc(*"VP80")
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if t < start:
                continue
            if t > end:
                break

            if centers:
                if win is None:
                    fh, fw = frame.shape[:2]
                    win = _window_size(track, pad, fw, fh)
                # Advance the pointer to the sample bracketing this frame's time
                # (frames are read in increasing t, so the pointer only moves
                # forward → O(frames) total, not O(frames × samples)).
                while ci + 1 < len(centers) and centers[ci + 1][0] <= t:
                    ci += 1
                cx, cy = _interp_center(centers, ci, t)
                win_w, win_h = win
                x0 = max(0, min(fw - win_w, int(round(cx - win_w / 2))))
                y0 = max(0, min(fh - win_h, int(round(cy - win_h / 2))))
                out_frame = frame[y0:y0 + win_h, x0:x0 + win_w]
            else:
                out_frame = frame
                if out_frame.shape[1] > _MAX_WIDTH:
                    scale = _MAX_WIDTH / out_frame.shape[1]
                    out_frame = cv2.resize(
                        out_frame,
                        (_MAX_WIDTH, max(2, int(out_frame.shape[0] * scale))),
                        interpolation=cv2.INTER_AREA,
                    )

            if writer is None:
                h, w = out_frame.shape[:2]
                writer = cv2.VideoWriter(str(out_path), fourcc, fps, (w, h))
                if not writer.isOpened():
                    logger.warning("clip: VideoWriter failed to open for %s", out_path)
                    return False
            writer.write(out_frame)
            written += 1
    finally:
        cap.release()
        if writer is not None:
            writer.release()

    if written == 0 or not out_path.exists() or out_path.stat().st_size == 0:
        logger.warning("clip: no frames written for %s (%.1f-%.1fs)", src, start, end)
        return False
    return True


def _interp_center(centers, ci: int, t: float) -> tuple[float, float]:
    """Linear-interpolate the (cx, cy) at time t between sample ci and ci+1."""
    t0, cx0, cy0 = centers[ci]
    if ci + 1 >= len(centers):
        return cx0, cy0
    t1, cx1, cy1 = centers[ci + 1]
    if t <= t0 or t1 <= t0:
        return cx0, cy0
    if t >= t1:
        return cx1, cy1
    f = (t - t0) / (t1 - t0)
    return cx0 + (cx1 - cx0) * f, cy0 + (cy1 - cy0) * f
