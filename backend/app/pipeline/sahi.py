"""
Slicing-Aided Hyper Inference (SAHI).

Splits a high-resolution frame into overlapping tiles, runs detection on each
tile, and merges results back into the original coordinate system. Drives
recall on small / far-field objects that the full-frame pass under-detects
because the detector's input is downsampled.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from geom import bbox_iou
from yolo_client import Detection


def make_tiles(
    frame_w: int,
    frame_h: int,
    n_cols: int = 2,
    n_rows: int = 2,
    overlap: float = 0.25,
) -> list[tuple[int, int, int, int]]:
    """Compute tile rectangles (x1, y1, x2, y2) covering the frame with overlap."""
    n_cols = max(1, n_cols)
    n_rows = max(1, n_rows)
    if n_cols == 1 and n_rows == 1:
        return [(0, 0, frame_w, frame_h)]

    # Tile size such that all tiles together cover the frame with the requested overlap.
    # span_in_tiles = n_cols - (n_cols - 1) * overlap  →  tile_w = frame_w / span
    tw = int(round(frame_w / max(1e-6, n_cols - (n_cols - 1) * overlap)))
    th = int(round(frame_h / max(1e-6, n_rows - (n_rows - 1) * overlap)))
    tw = min(tw, frame_w)
    th = min(th, frame_h)

    if n_cols > 1:
        step_x = (frame_w - tw) / (n_cols - 1)
    else:
        step_x = 0
    if n_rows > 1:
        step_y = (frame_h - th) / (n_rows - 1)
    else:
        step_y = 0

    tiles = []
    for r in range(n_rows):
        for c in range(n_cols):
            x1 = int(round(c * step_x))
            y1 = int(round(r * step_y))
            x2 = min(frame_w, x1 + tw)
            y2 = min(frame_h, y1 + th)
            tiles.append((x1, y1, x2, y2))
    return tiles


def crop_tile(frame: np.ndarray, rect: tuple[int, int, int, int]) -> np.ndarray:
    x1, y1, x2, y2 = rect
    return frame[y1:y2, x1:x2]


def offset_detections(dets: Iterable[Detection], dx: int, dy: int) -> list[Detection]:
    out = []
    for d in dets:
        out.append(Detection(
            x1=d.x1 + dx, y1=d.y1 + dy,
            x2=d.x2 + dx, y2=d.y2 + dy,
            conf=d.conf, cls=d.cls, name=d.name,
        ))
    return out


def nms_merge(dets: list[Detection], iou_thresh: float = 0.45) -> list[Detection]:
    """Greedy NMS — keep the highest-conf detection, drop overlaps."""
    if not dets:
        return []
    sorted_dets = sorted(dets, key=lambda d: d.conf, reverse=True)
    kept: list[Detection] = []
    for d in sorted_dets:
        d_box = (d.x1, d.y1, d.x2, d.y2)
        skip = False
        for k in kept:
            if bbox_iou(d_box, (k.x1, k.y1, k.x2, k.y2)) > iou_thresh:
                skip = True
                break
        if not skip:
            kept.append(d)
    return kept


def filter_edge_detections(
    dets: list[Detection],
    tile_rect: tuple[int, int, int, int],
    edge_margin: int = 4,
    frame_size: tuple[int, int] | None = None,
) -> list[Detection]:
    """Drop detections whose bbox touches a tile edge that is not on the frame border.

    Boxes that hug a non-border tile edge are usually halves of objects clipped by
    the slice; the full object will be picked up by an adjacent tile and merged via NMS.
    """
    x1, y1, x2, y2 = tile_rect
    fw, fh = (frame_size or (None, None))
    out = []
    for d in dets:
        # Convert to tile-local coords for the comparison.
        # `left/top/right/bottom` are distances from each tile edge to the
        # detection's matching edge; small value = detection touches that side.
        left   = d.x1 - x1
        top    = d.y1 - y1
        right  = (x2 - x1) - (d.x2 - x1)
        bottom = (y2 - y1) - (d.y2 - y1)
        # Touching left edge but tile is not at frame left → drop
        on_frame_left   = (fw is None) or (x1 <= 0)
        on_frame_right  = (fw is None) or (x2 >= fw)
        on_frame_top    = (fh is None) or (y1 <= 0)
        on_frame_bottom = (fh is None) or (y2 >= fh)
        if left   < edge_margin and not on_frame_left:    continue
        if top    < edge_margin and not on_frame_top:     continue
        if right  < edge_margin and not on_frame_right:   continue
        if bottom < edge_margin and not on_frame_bottom:  continue
        out.append(d)
    return out
