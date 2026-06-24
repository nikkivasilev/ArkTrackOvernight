"""Geometry helpers — single source of truth for IoU, bbox math.

Multiple modules historically reimplemented IoU. Importing from here keeps
them consistent and makes the math reviewable in one place.
"""

from __future__ import annotations

BBox = tuple[float, float, float, float]   # (x1, y1, x2, y2)


def bbox_iou(a: BBox, b: BBox) -> float:
    """IoU between two axis-aligned bboxes. Returns 0 for empty/degenerate boxes."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1); iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2); iy2 = min(ay2, by2)
    iw = max(0.0, ix2 - ix1); ih = max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    a_area = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    b_area = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = a_area + b_area - inter
    if union <= 0:
        return 0.0
    return inter / union


def bbox_center(bbox: BBox) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return (x1 + x2) / 2, (y1 + y2) / 2


def bbox_size(bbox: BBox) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return max(0.0, x2 - x1), max(0.0, y2 - y1)


def bbox_pad(bbox: BBox, pad: int, frame_w: int, frame_h: int) -> tuple[int, int, int, int]:
    """Pad a bbox by `pad` px on each side, clamped to frame bounds. Returns ints."""
    x1, y1, x2, y2 = bbox
    return (
        max(0, int(x1) - pad),
        max(0, int(y1) - pad),
        min(frame_w, int(x2) + pad),
        min(frame_h, int(y2) + pad),
    )


def centroid_distance(a_center: tuple[float, float], b_center: tuple[float, float]) -> float:
    dx = a_center[0] - b_center[0]
    dy = a_center[1] - b_center[1]
    return (dx * dx + dy * dy) ** 0.5
