"""OpenCV drawing primitives used by `_render_and_publish`.

All functions are pure pixel-pushers that mutate the frame buffer in
place. No state, no asyncio, no business logic — just bbox / label /
overlay rendering. The Pipeline's render mixin (pipeline_render.py)
chooses what + when to draw; this module decides only how.

Functions, in z-order they're typically composed:
    draw_flash         — welding arc marker (orphan = thick red, attributed = thin)
    draw_motion_roi    — yellow dashed rectangle for motion-aware SAHI ROI
    draw_track         — solid bbox + label (real YOLO track or phantom welder)
    draw_ghost_track   — dashed bbox for unseen-this-cycle tracks
    draw_motion_track  — cyan dashed bbox for unconfirmed motion blobs
    draw_group         — amber dashed circle around an idle cluster
    draw_zone          — polygon outline + count label, pulses red on breach
    draw_hud           — bottom-strip telemetry overlay

color_for_activity() is the single mapping from activity label → BGR
tuple, sourced from activity.ACTIVITY_COLORS so the legend stays in sync.
"""

import cv2
import numpy as np

from activity import ACTIVITY_COLORS


def draw_track(img: np.ndarray, x1: int, y1: int, x2: int, y2: int, label: str, color: tuple[int, int, int], conf: float = 0.0):
    cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
    text = f"{label}"
    if conf > 0:
        text = f"{label} {conf:.2f}"
    (tw, th), bl = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
    pad = 4
    by1 = max(0, y1 - th - 2 * pad)
    cv2.rectangle(img, (x1, by1), (x1 + tw + 2 * pad, y1), color, -1)
    cv2.putText(img, text, (x1 + pad, y1 - pad), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)


def draw_flash(img: np.ndarray, cx: float, cy: float, area: int, orphan: bool = False):
    # Cap the indicator circle to the actual weld-point size, not the full glow spread.
    r = max(15, min(45, int((area ** 0.5) * 0.30)))
    color = (0, 0, 255) if orphan else (180, 220, 220)
    thickness = 3 if orphan else 1
    cv2.circle(img, (int(cx), int(cy)), r, color, thickness)
    label = "WELDING (anon)" if orphan else "arc"
    cv2.putText(img, label, (int(cx) - 60, int(cy) - r - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)


def draw_motion_roi(img: np.ndarray, x1: int, y1: int, x2: int, y2: int):
    """Thin cyan dashed-look outline showing where the motion-aware ROI fired."""
    color = (255, 200, 0)
    cv2.rectangle(img, (x1, y1), (x2, y2), color, 1, cv2.LINE_AA)
    cv2.putText(img, "motion", (x1 + 4, y1 + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)


def _dashed_rect(img: np.ndarray, x1: int, y1: int, x2: int, y2: int, color, thickness: int = 2, dash: int = 8, gap: int = 6):
    """Draw a dashed rectangle outline. Used for "ghost" / stale tracks."""
    # Top edge
    x = x1
    while x < x2:
        x_end = min(x + dash, x2)
        cv2.line(img, (x, y1), (x_end, y1), color, thickness, cv2.LINE_AA)
        x = x_end + gap
    # Bottom edge
    x = x1
    while x < x2:
        x_end = min(x + dash, x2)
        cv2.line(img, (x, y2), (x_end, y2), color, thickness, cv2.LINE_AA)
        x = x_end + gap
    # Left edge
    y = y1
    while y < y2:
        y_end = min(y + dash, y2)
        cv2.line(img, (x1, y), (x1, y_end), color, thickness, cv2.LINE_AA)
        y = y_end + gap
    # Right edge
    y = y1
    while y < y2:
        y_end = min(y + dash, y2)
        cv2.line(img, (x2, y), (x2, y_end), color, thickness, cv2.LINE_AA)
        y = y_end + gap


def draw_motion_track(
    img: np.ndarray,
    x1: int, y1: int, x2: int, y2: int,
    label: str,
):
    """Cyan dashed thin outline for unconfirmed motion tracks (M-N).
    These are objects MOG2+Norfair are tracking that YOLO hasn't confirmed yet.
    """
    color = (255, 220, 0)  # cyan in BGR
    _dashed_rect(img, x1, y1, x2, y2, color, thickness=2, dash=8, gap=5)
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
    pad = 4
    by1 = max(0, y1 - th - 2 * pad)
    cv2.rectangle(img, (x1, by1), (x1 + tw + 2 * pad, y1), color, -1)
    cv2.putText(img, label, (x1 + pad, y1 - pad),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (10, 10, 10), 1, cv2.LINE_AA)


def draw_ghost_track(
    img: np.ndarray,
    x1: int, y1: int, x2: int, y2: int,
    label: str,
    color: tuple[int, int, int],
    stale_s: float,
):
    """Render a 'remembered but not currently confirmed' track. Dashed outline,
    slightly desaturated color, with `(stale Xs)` suffix on the label.
    """
    # Dim the color so ghost boxes recede vs. active ones
    dim = tuple(int(c * 0.7) for c in color)
    _dashed_rect(img, x1, y1, x2, y2, dim, thickness=2, dash=10, gap=6)
    text = f"{label}  stale {stale_s:.1f}s"
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
    pad = 4
    by1 = max(0, y1 - th - 2 * pad)
    cv2.rectangle(img, (x1, by1), (x1 + tw + 2 * pad, y1), dim, -1)
    cv2.putText(img, text, (x1 + pad, y1 - pad), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (240, 240, 240), 1, cv2.LINE_AA)


def draw_group(
    img: np.ndarray,
    cx: int, cy: int, radius: int,
    label: str,
):
    """Dashed-circle outline around an idle-cluster centroid + label badge.
    Color is amber to differentiate from track / phantom / motion overlays."""
    color = (0, 165, 255)   # BGR — amber
    # Outer dashed circle (approximated by short arcs)
    n_dashes = 24
    for i in range(0, n_dashes, 2):
        a0 = i * 360 / n_dashes
        a1 = (i + 1) * 360 / n_dashes
        cv2.ellipse(img, (cx, cy), (radius, radius), 0, a0, a1, color, 2, cv2.LINE_AA)
    # Centre dot
    cv2.circle(img, (cx, cy), 4, color, -1, cv2.LINE_AA)
    # Label badge (bottom-right of the circle)
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
    pad = 5
    bx = cx + int(radius * 0.6)
    by = cy + int(radius * 0.6)
    cv2.rectangle(img, (bx, by - th - 2 * pad), (bx + tw + 2 * pad, by), color, -1)
    cv2.putText(img, label, (bx + pad, by - pad),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (10, 10, 10), 2, cv2.LINE_AA)


def draw_zone(
    img: np.ndarray,
    polygon: list[tuple[float, float]],
    label: str,
    in_breach: bool,
    pulse_phase: float = 0.0,
):
    """Translucent fill + outlined polygon + label badge.

    `pulse_phase` is a 0..1 value driving the breach pulse — caller passes
    `(t * 2.0) % 1.0` or similar; we map it to outline thickness so a
    breaching zone visibly breathes. Non-breaching zones are drawn calm.
    """
    if len(polygon) < 3:
        return
    pts = np.array([[int(round(x)), int(round(y))] for x, y in polygon], dtype=np.int32)
    pts_for_cv = pts.reshape(-1, 1, 2)

    # Color: green when calm, red when in breach.
    if in_breach:
        outline = (0, 0, 230)        # BGR red
        fill    = (0, 0, 230)
        fill_alpha = 0.18
    else:
        outline = (90, 200, 90)       # BGR green
        fill    = (90, 200, 90)
        fill_alpha = 0.08

    # Translucent fill via overlay-blend.
    overlay = img.copy()
    cv2.fillPoly(overlay, [pts_for_cv], fill)
    cv2.addWeighted(overlay, fill_alpha, img, 1.0 - fill_alpha, 0, img)

    # Outline. Thickness pulses 2..5 px when in breach.
    thickness = 2
    if in_breach:
        thickness = 2 + int(round(3 * pulse_phase))
    cv2.polylines(img, [pts_for_cv], isClosed=True, color=outline,
                  thickness=thickness, lineType=cv2.LINE_AA)

    # Label badge near the polygon centroid.
    cx = int(round(pts[:, 0].mean()))
    cy = int(round(pts[:, 1].mean()))
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
    pad = 6
    bx = cx - (tw + 2 * pad) // 2
    by = cy - th // 2
    cv2.rectangle(img, (bx, by - pad), (bx + tw + 2 * pad, by + th + pad),
                  outline, -1)
    cv2.putText(img, label, (bx + pad, by + th),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)


def draw_hud(img: np.ndarray, info: dict):
    h, w = img.shape[:2]
    lines = []
    lines.append(f"frame {info.get('frame', 0)}  t={info.get('t', 0.0):.2f}s")
    lines.append(f"src fps {info.get('src_fps', 0):.1f}  yolo {info.get('yolo_ms', 0):.0f} ms")
    lines.append(f"tracks {info.get('n_tracks', 0)}   detections {info.get('n_dets', 0)}")
    counts = info.get("activity_counts", {})
    if counts:
        lines.append("  ".join(f"{k}:{v}" for k, v in counts.items()))
    y = 30
    for s in lines:
        (tw, th), _ = cv2.getTextSize(s, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        cv2.rectangle(img, (10, y - th - 6), (10 + tw + 12, y + 6), (0, 0, 0), -1)
        cv2.putText(img, s, (16, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        y += th + 12


def color_for_activity(activity: str) -> tuple[int, int, int]:
    return ACTIVITY_COLORS.get(activity, ACTIVITY_COLORS["unknown"])
