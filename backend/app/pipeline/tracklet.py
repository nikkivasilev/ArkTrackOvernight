"""Per-track tracklet ring buffer — captures recent frame crops of each tracked
person so we can send them to the VLM for activity classification.

Each track holds the last N frames (sampled at most once every `min_dt`) of its
last_bbox crop. The VLM classifier pulls a sub-sample for inference.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np


@dataclass
class TrackletFrame:
    t: float                    # video time
    bbox: tuple[int, int, int, int]
    crop: np.ndarray            # BGR small jpeg-quality patch


@dataclass
class TrackletBuffer:
    """A ring buffer of recent frames belonging to a single tracked person."""
    max_frames: int = 16
    min_dt: float = 0.20         # seconds between captures (5 fps sampling)
    crop_long_side: int = 192    # downscale crop to keep memory + VLM upload tiny
    pad_ratio: float = 0.15      # extra padding around bbox
    frames: deque = field(default_factory=lambda: deque())

    def maybe_capture(
        self,
        frame_bgr: np.ndarray,
        t: float,
        bbox: tuple[int, int, int, int],
    ) -> bool:
        """Capture a crop iff enough time has passed since the last one."""
        if self.frames and (t - self.frames[-1].t) < self.min_dt:
            return False

        H, W = frame_bgr.shape[:2]
        x1, y1, x2, y2 = bbox
        bw = x2 - x1; bh = y2 - y1
        if bw <= 0 or bh <= 0:
            return False

        px = int(bw * self.pad_ratio)
        py = int(bh * self.pad_ratio)
        cx1 = max(0, x1 - px); cy1 = max(0, y1 - py)
        cx2 = min(W, x2 + px); cy2 = min(H, y2 + py)
        crop = frame_bgr[cy1:cy2, cx1:cx2]
        if crop.size == 0:
            return False

        # Downscale to keep memory + upload tiny
        long_side = max(crop.shape[0], crop.shape[1])
        if long_side > self.crop_long_side:
            scale = self.crop_long_side / long_side
            new_w = max(2, int(crop.shape[1] * scale))
            new_h = max(2, int(crop.shape[0] * scale))
            crop = cv2.resize(crop, (new_w, new_h), interpolation=cv2.INTER_AREA)

        self.frames.append(TrackletFrame(t=t, bbox=bbox, crop=crop.copy()))
        while len(self.frames) > self.max_frames:
            self.frames.popleft()
        return True

    def sampled(self, n: int = 6) -> list[TrackletFrame]:
        """Return up to n frames evenly spaced across the buffer."""
        if not self.frames:
            return []
        if len(self.frames) <= n:
            return list(self.frames)
        idxs = np.linspace(0, len(self.frames) - 1, n).astype(int)
        return [self.frames[i] for i in idxs]

    def latest_t(self) -> Optional[float]:
        return self.frames[-1].t if self.frames else None
