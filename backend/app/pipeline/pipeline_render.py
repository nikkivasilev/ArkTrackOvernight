"""Annotated-frame rendering + WS state broadcast.

Mixin extracted from pipeline.py during the 2026-05-09 refactor. The big
`_render_and_publish` method composes one display frame per cycle by layering
overlays in fixed z-order, encodes JPEG, and pushes a state dict to all WS
subscribers.

Required attributes on `self` (provided by Pipeline):
    self.cfg                  : PipelineConfig
    self.tracks               : dict[int, TrackHistory]
    self.phantom_tracker      : PhantomTracker
    self._metric_zones        : list[(zone_id, name, shapely Polygon px)]
    self._groups              : list[Group]
    self._last_iid_to_pid     : dict[int, int]
    self._last_jpeg_no_zones  : bytes | None
    self._last_wall           : float
    self._src_fps_ema         : float
    self._yolo_ms_ema         : float
    self.last_frame           : FrameOut | None
    self.frame_event          : asyncio.Event
    self.running              : bool
    self.overlay_enabled      : bool

Plus methods inherited from sibling mixins / Pipeline core:
    self._effective_vlm(hist, t)   — _VlmMixin
    self._broadcast(event)          — Pipeline core
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from typing import Optional

import cv2
import numpy as np
import supervision as sv
from shapely.geometry import Point

from activity import phantom_label, phantom_track_id, rollup_activity
from geom import bbox_iou
from pipeline_config import FrameOut
from renderer import (
    color_for_activity,
    draw_flash,
    draw_ghost_track,
    draw_group,
    draw_track,
    draw_zone,
)
from yolo_client import Detection


# Operator-facing display aliases for the activity *label* only. These do NOT
# change the rollup bucket (lifting/unknown already roll up to "working") — they
# just collapse noisy/granular labels into "working" in the track table, the
# on-frame label, and the per-activity breakdown. `lifting_or_carrying` over-
# fires on SigLIP and reads better as plain working; `unknown` (heuristic slow-
# mover / margin-gate fallback) is counted as working anyway, so show it so.
_DISPLAY_ACTIVITY_ALIAS = {
    "lifting_or_carrying": "working",
    "unknown": "working",
}


def _display_activity(label: str) -> str:
    return _DISPLAY_ACTIVITY_ALIAS.get(label, label)


class _RenderMixin:
    """Annotated frame rendering + state broadcast."""

    # These are also set in Pipeline.__init__; declared here so mypy knows
    # the Optional shape when the mixin assigns None to them.
    last_frame: Optional[FrameOut]
    _last_jpeg_no_zones: Optional[bytes]

    async def _render_and_publish(
        self,
        frame: np.ndarray,
        frame_idx: int,
        t_video: float,
        tracked: sv.Detections,
        dets: list[Detection],
        ran_yolo: bool,
        seen_ids: set[int],
        flashes: dict,
        orphan_flashes: dict,
        visible_phantom_ids: set[int],
    ):
        """Build the annotated display frame, encode JPEG, broadcast state.

        Layered rendering, in z-order:
          1. flash markers (orphan red, attributed faint)
          2. real D-FINE tracks
          3. ghost tracks (real but unseen this cycle)
          4. phantom welders
          5. HUD overlay
        """
        # Headless/offline mode (set by the offline batch runner / benchmark):
        # skip the display resize, all drawing, and the JPEG encode. Only the
        # `state` dict is produced — nothing here consumes the JPEG and the
        # full-frame imencode is the dominant per-frame CPU cost.
        headless = getattr(self, "headless", False)

        # Display scaling
        display = frame
        if not headless and frame.shape[1] != self.cfg.display_width:
            scale = self.cfg.display_width / frame.shape[1]
            display = cv2.resize(frame, (self.cfg.display_width, int(frame.shape[0] * scale)))
        sx = display.shape[1] / frame.shape[1]
        sy = display.shape[0] / frame.shape[0]

        # When the overlay is off, every draw_* call is skipped and we ship the
        # raw video. Bookkeeping (track_state / activity_counts) keeps running so
        # the sidebar + timeline still update. Headless forces it off entirely.
        overlay = self.overlay_enabled and not headless

        # Excluded-zone visual filter: skip draw_* calls for detections whose
        # foot-point (bottom-center, source-frame px) is inside any "not
        # monitored" zone. State filtering for the WS broadcast still happens
        # downstream in zone_filter.apply — this gate only suppresses pixels
        # so the operator's live video doesn't show boxes in excluded zones.
        excluded_polys = getattr(self, "_excluded_polygons", None) or []

        def _foot_in_excluded(x1: float, y1: float, x2: float, y2: float) -> bool:
            if not excluded_polys:
                return False
            p = Point((float(x1) + float(x2)) / 2.0, float(y2))
            return any(poly.covers(p) for poly in excluded_polys)

        def _pt_in_excluded(x: float, y: float) -> bool:
            if not excluded_polys:
                return False
            p = Point(float(x), float(y))
            return any(poly.covers(p) for poly in excluded_polys)

        # 1. Flashes — orphans get a thicker red marker, attributed flashes a thin one.
        # Suppress orphan markers for flashes already attached to a visible phantom.
        attributed_flash_ids = {
            ps.flash_id for pid, ps in self.phantom_tracker.active.items()
            if pid in visible_phantom_ids and ps.flash_id is not None
        }
        if overlay:
            for fid, ev in flashes.items():
                is_orphan = fid in orphan_flashes
                if is_orphan and fid in attributed_flash_ids:
                    continue
                if _pt_in_excluded(ev.cx, ev.cy):
                    continue
                draw_flash(display, ev.cx * sx, ev.cy * sy, ev.area, orphan=is_orphan)

        activity_counts: dict[str, int] = defaultdict(int)
        rollup_counts: dict[str, int] = defaultdict(int)
        track_state: list[dict] = []
        real_bboxes: list[tuple[int, int, int, int]] = []
        # Foot-points (source-frame px) of every visible non-ghost track —
        # real + phantom — paired with their public id and display activity.
        # Tested against the monitored-zone polygons after the draw loops to
        # produce per-zone occupancy counts AND per-zone activity breakdowns
        # for state["zones"].
        zone_footpoints: list[tuple[float, float, int, str]] = []

        # 3. Real YOLO tracks
        if len(tracked) > 0 and tracked.tracker_id is not None:
            for i in range(len(tracked)):
                iid = int(tracked.tracker_id[i])
                tid = self._last_iid_to_pid.get(iid, iid)
                x1, y1, x2, y2 = tracked.xyxy[i]
                rx1, ry1 = int(x1 * sx), int(y1 * sy)
                rx2, ry2 = int(x2 * sx), int(y2 * sy)
                hist = self.tracks.get(tid)
                # VLM has stably ruled this out as a false detection — skip
                # rendering, state, and rollup counting.
                if hist is not None and hist.vlm_marked_false:
                    continue
                activity = hist.activity if hist else "unknown"
                conf = hist.activity_conf if hist else 0.0
                # VLM verdict (with stale-walking reconciliation)
                vlm_label, vlm_rollup = self._effective_vlm(hist, t_video)
                display_activity = _display_activity(vlm_label or activity)
                rollup_for_state = vlm_rollup if vlm_label else rollup_activity(activity)
                color = color_for_activity(activity)
                if overlay and not _foot_in_excluded(x1, y1, x2, y2):
                    draw_track(display, rx1, ry1, rx2, ry2, f"#{tid} {display_activity}", color, conf)
                activity_counts[display_activity] += 1
                rollup_counts[rollup_for_state] += 1
                track_state.append({
                    "track_id": tid,
                    "label": f"#{tid}",
                    "bbox": [int(x1), int(y1), int(x2), int(y2)],
                    "activity": display_activity,
                    "heuristic_activity": activity,
                    "vlm_activity": vlm_label,
                    "rollup": rollup_for_state,
                    "conf": round(conf, 2),
                    "vlm_conf": round(hist.vlm_conf, 2) if hist else 0.0,
                    "phantom": False,
                })
                real_bboxes.append((int(x1), int(y1), int(x2), int(y2)))
                zone_footpoints.append(((x1 + x2) / 2.0, float(y2), tid, display_activity))

        # 4. Ghost tracks (known but unseen this cycle, dashed outline)
        GHOST_MAX_AGE = 10.0
        # IoU above which a ghost or phantom is considered the same person as a
        # fresh D-FINE track and gets suppressed. Ghosts persist on the last
        # known D-FINE bbox so the person has usually drifted a little — 0.5
        # misses near-misses, 0.3 risks suppressing genuinely separate people
        # standing shoulder-to-shoulder. 0.4 is the empirical middle.
        DEDUP_IOU = 0.4
        # Inherit-last-rollup window: when a ghost has no fresh VLM verdict,
        # fall back to its heuristic activity as long as the track was last
        # seen within this many seconds. Beyond that, the rollup goes back to
        # "unclear" so the operator still gets a "haven't seen them in a while"
        # signal. Keeps the timeline from flickering grey on every missed
        # frame while preserving genuine uncertainty.
        GHOST_SMOOTH_S = 5.0
        ghost_ids: set[int] = set()
        for tid, hist in self.tracks.items():
            if tid in seen_ids or hist.last_bbox is None:
                continue
            # VLM has stably ruled this out as a false detection — don't
            # surface it as a ghost either.
            if hist.vlm_marked_false:
                continue
            age = t_video - hist.last_seen_t
            if age <= 0.05 or age > GHOST_MAX_AGE:
                continue
            # D-FINE supremacy: if a fresh real track already occupies this
            # region, the ghost is redundant — drop it entirely (no draw, no
            # rollup count, no track_state entry).
            if any(bbox_iou(hist.last_bbox, rb) > DEDUP_IOU for rb in real_bboxes):
                continue
            ghost_ids.add(tid)
            bx1, by1, bx2, by2 = hist.last_bbox
            rx1, ry1 = int(bx1 * sx), int(by1 * sy)
            rx2, ry2 = int(bx2 * sx), int(by2 * sy)
            color = color_for_activity(hist.activity)
            vlm_label_g, vlm_rollup_g = self._effective_vlm(hist, t_video)
            ghost_activity = _display_activity(vlm_label_g or hist.activity)
            if overlay and not _foot_in_excluded(bx1, by1, bx2, by2):
                draw_ghost_track(
                    display, rx1, ry1, rx2, ry2,
                    f"#{tid} {ghost_activity}", color, age,
                )
            # Inherit the last confident rollup so brief disappearances don't
            # flip the operator's view to grey. Two-tier:
            #   1. fresh VLM verdict (≤ 2·vlm_revisit_s, enforced inside
            #      _effective_vlm) → use it.
            #   2. heuristic activity is non-"unknown" and the track was seen
            #      within GHOST_SMOOTH_S → rollup_activity(hist.activity).
            #   3. otherwise "unclear" (genuine uncertainty).
            if vlm_label_g:
                ghost_rollup = vlm_rollup_g or "unclear"
            elif hist.activity and hist.activity != "unknown" and age <= GHOST_SMOOTH_S:
                ghost_rollup = rollup_activity(hist.activity)
            else:
                ghost_rollup = "unclear"
            rollup_counts[ghost_rollup] += 1
            track_state.append({
                "track_id": tid,
                "label": f"#{tid}",
                "bbox": [bx1, by1, bx2, by2],
                "activity": ghost_activity,
                "heuristic_activity": hist.activity,
                "vlm_activity": vlm_label_g,
                "rollup": ghost_rollup,
                "conf": round(hist.activity_conf, 2),
                "phantom": False,
                "ghost": True,
                "stale_s": round(age, 1),
            })

        # 5. Phantom welders — A-N labelled red boxes anchored to flash centroid.
        # Perspective-aware sizing: smaller for far arcs (top), larger for near (bottom).
        H_full = frame.shape[0]
        for pid in sorted(visible_phantom_ids):
            ps = self.phantom_tracker.active[pid]
            tid = phantom_track_id(pid)
            depth_factor = max(0.0, min(1.0, ps.cy / max(1, H_full)))
            raw = (ps.area ** 0.5) * 0.35
            min_r = 18 + 12 * depth_factor   # 18 (far) → 30 (near)
            max_r = 35 + 60 * depth_factor   # 35 (far) → 95 (near)
            radius = int(max(min_r, min(max_r, raw)))
            bw = bh = radius * 2
            bx1 = int(ps.cx - bw / 2); by1 = int(ps.cy - bh / 2)
            bx2 = int(ps.cx + bw / 2); by2 = int(ps.cy + bh / 2)
            # D-FINE supremacy: if a real track already covers the welder, the
            # arc-anchored phantom is redundant. Orphan welders (no overlapping
            # real track) still render — that's the case the phantom exists for.
            if any(bbox_iou((bx1, by1, bx2, by2), rb) > DEDUP_IOU for rb in real_bboxes):
                continue
            rx1, ry1 = int(bx1 * sx), int(by1 * sy)
            rx2, ry2 = int(bx2 * sx), int(by2 * sy)
            color = color_for_activity("welding")
            if overlay and not _foot_in_excluded(bx1, by1, bx2, by2):
                draw_track(display, rx1, ry1, rx2, ry2, f"{phantom_label(tid)} welding", color, 0.8)
            activity_counts["welding"] += 1
            rollup_counts[rollup_activity("welding")] += 1
            track_state.append({
                "track_id": tid,
                "label": phantom_label(tid),
                "bbox": [bx1, by1, bx2, by2],
                "activity": "welding",
                "rollup": "working",
                "conf": 0.8,
                "phantom": True,
            })
            # A welder behind an arc is present in the zone — count its
            # foot-point (bottom-center of the synthetic box) toward occupancy.
            zone_footpoints.append((float(ps.cx), float(by2), tid, "welding"))

        # 7. Idle-groups overlay (amber dashed circles around clusters of
        # non-working workers standing close together for ≥ min_duration_s).
        # Groups whose centroid lands inside any excluded ("not monitored")
        # zone are dropped entirely — no draw, no state, no rollup count.
        groups_state: list[dict] = []
        for g in self._groups:
            if _pt_in_excluded(g.cx, g.cy):
                continue
            cx_d = int(g.cx * sx)
            cy_d = int(g.cy * sy)
            # Pad a bit so the circle clears the members' bboxes
            r_d = int(max(g.radius, 60) * max(sx, sy)) + 20
            kind_label = "Chatting" if g.is_chatting else "Group"
            label = f"{kind_label} · {len(g.member_ids)} · {int(g.age_s)}s"
            if overlay:
                draw_group(display, cx_d, cy_d, r_d, label)
            groups_state.append({
                "group_id": g.group_id,
                "members": list(g.member_ids),
                "cx": int(g.cx),
                "cy": int(g.cy),
                "radius": int(g.radius),
                "age_s": round(g.age_s, 1),
                "is_chatting": g.is_chatting,
            })
            rollup_counts["group_idle"] += 1

        # 7b. Monitored zones — count visible foot-points (real + phantom)
        # inside each zone polygon, draw the outline + live count, and emit
        # per-zone occupancy into state["zones"]. The metrics aggregator
        # integrates these into occupancy histograms; the frontend zone-metrics
        # view derives understaffed/avg/peak from them.
        # First snapshot the display BEFORE zones are drawn — the "clean
        # canvas" the in-browser zone editor draws on. We keep track / phantom
        # overlays for spatial reference; HUD comes later so it's absent here.
        metric_zones = getattr(self, "_metric_zones", None) or []
        if overlay and metric_zones:
            ok_nz, jpg_nz = cv2.imencode(
                ".jpg", display, [cv2.IMWRITE_JPEG_QUALITY, self.cfg.jpeg_quality]
            )
            if ok_nz:
                self._last_jpeg_no_zones = jpg_nz.tobytes()
        else:
            self._last_jpeg_no_zones = None

        zones_state: list[dict] = []
        pulse_phase = 0.5 + 0.5 * math.sin(t_video * math.tau)
        for zid, zname, poly in metric_zones:
            members: list[int] = []
            activities: dict[str, int] = {}
            for (fx, fy, tid, act) in zone_footpoints:
                if poly.covers(Point(fx, fy)):
                    members.append(tid)
                    activities[act] = activities.get(act, 0) + 1
            count = len(members)
            if overlay:
                poly_disp = [(px * sx, py * sy) for (px, py) in poly.exterior.coords]
                draw_zone(display, poly_disp, f"{zname} [{count}]", False, pulse_phase)
            zones_state.append({
                "zone_id": zid,
                "zone_name": zname,
                "count": count,
                "members": members,
                # Per-zone activity headcount this frame; the metrics aggregator
                # integrates it into person-seconds-per-activity histograms.
                "activities": activities,
            })

        # 8. FPS / HUD
        now_wall = time.time()
        inst = 1.0 / max(1e-3, now_wall - self._last_wall)
        self._last_wall = now_wall
        self._src_fps_ema = (
            0.85 * self._src_fps_ema + 0.15 * inst if self._src_fps_ema else inst
        )
        # HUD intentionally not burned onto the JPEG — the React Hud
        # component in LiveTab already shows frame/t/fps/D-FINE-ms/dets/WS
        # from the same state fields, so painting it on the video too is
        # redundant and clutters the operator's frame.
        # self._src_fps_ema / self._yolo_ms_ema still feed state.src_fps /
        # state.yolo_ms in the broadcast below.

        # Encode + publish. Headless skips the JPEG entirely (no consumer; the
        # full-frame imencode is the single biggest per-frame CPU cost).
        if headless:
            jpeg_bytes = b""
        else:
            ok, jpg = cv2.imencode(".jpg", display, [cv2.IMWRITE_JPEG_QUALITY, self.cfg.jpeg_quality])
            if not ok:
                return
            jpeg_bytes = jpg.tobytes()
        self.last_frame = FrameOut(
            frame_idx=frame_idx,
            t=t_video,
            jpeg=jpeg_bytes,
            state={
                "frame": frame_idx,
                "t": round(t_video, 2),
                "running": self.running,
                "src_fps": round(self._src_fps_ema, 1),
                "yolo_ms": round(self._yolo_ms_ema, 0),
                "tracks": track_state,
                "activity_counts": dict(activity_counts),
                "rollup_counts": dict(rollup_counts),
                "n_dets": len(dets),
                "n_phantoms": len(visible_phantom_ids),
                "n_phantoms_in_grace": sum(
                    1 for ps in self.phantom_tracker.active.values() if ps.flash_id is None  # type: ignore[misc]
                ),
                "flashes": [
                    {"cx": int(ev.cx), "cy": int(ev.cy), "area": ev.area,
                     "orphan": fid in orphan_flashes}
                    for fid, ev in flashes.items()
                ],
                "orphan_welding_count": max(0, len(orphan_flashes) - len(visible_phantom_ids)),
                "groups": groups_state,
                "zones": zones_state,
            },
        )
        self.frame_event.set()
        self.frame_event.clear()
        await self._broadcast({"type": "state", "data": self.last_frame.state})
