"""Activity classification + welding flash detection + phantom welders.

The "what is each track doing right now" layer. Splits into four loosely
related subsystems that all happen to share TrackHistory as their state:

  1. TrackHistory + classify_motion
       Heuristic activity labels from position history.
       walking | standing | unknown

  2. FlashDetector
       Per-frame welding-arc blob detection (HSV + B-R + compactness +
       persistence). Returns {flash_id: FlashEvent}.

  3. attribute_welding
       Snap each flash to the nearest live track (or mark orphan).
       Returns (welding_track_ids, orphan_flashes).

  4. PhantomTracker
       Keeps a "ghost worker" alive at orphan-flash centroids for a grace
       window so the UI shows welding even when YOLO can't see the welder
       through the arc. phantom_track_id() / phantom_label() / is_phantom()
       give phantom IDs a deterministic mapping to the public track-id space
       (offset by PHANTOM_OFFSET).

Vocabulary:
    activity   — fine-grained label (walking, welding, standing, ...)
    rollup     — coarse bucket {working, moving, idle, group_idle, unclear}
                 used by activity counts + zone membership filters.
    rollup_activity(activity) → bucket  (the canonical mapping)

Color map (ACTIVITY_COLORS) is defined here so renderer.py and the
zone-overlay code share it.
"""

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

ACTIVITY_COLORS = {
    "welding":       (0,   0, 255),
    "walking":       (0, 200, 255),
    "standing":      (0, 200,   0),
    "sitting":       (255, 100, 100),
    "unknown":       (150, 150, 150),
}


@dataclass
class FlashEvent:
    cx: float
    cy: float
    area: int
    first_seen: float
    last_seen: float


@dataclass
class TrackHistory:
    track_id: int
    positions: deque = field(default_factory=lambda: deque(maxlen=60))
    activity: str = "unknown"
    activity_conf: float = 0.0
    welding_until: float = 0.0
    timeline: deque = field(default_factory=lambda: deque(maxlen=600))
    # Last known bbox in source-frame coords (x1, y1, x2, y2). Used by the
    # ghost-track rendering path.
    last_bbox: Optional[tuple[int, int, int, int]] = None
    last_seen_t: float = 0.0          # Last time we considered the track present (any source)
    last_seen_real_t: float = 0.0     # Last fresh YOLO detection
    # VLM activity classification (filled in by vlm_classifier on a slow cadence).
    # `vlm_activity` is the rich label (e.g. "operating welding torch"); `activity`
    # stays as the heuristic short label so existing logic keeps working.
    # `vlm_activity` is the *displayed/stable* label — it only changes after
    # `vlm_stability_k` consecutive same-class calls (see pipeline._run_vlm).
    vlm_activity: Optional[str] = None
    vlm_rollup: Optional[str] = None     # working / moving / idle / unclear
    vlm_conf: float = 0.0
    vlm_last_t: float = 0.0              # last successful VLM call (video time)
    vlm_inflight: bool = False           # set True while a VLM call is pending
    # Recent raw VLM call results (just the activity string). Used to apply
    # the stability rule before promoting a label into `vlm_activity`.
    vlm_history: deque = field(default_factory=lambda: deque(maxlen=8))
    # Set True once the VLM has stably emitted "not_a_person" (≥2 consecutive
    # calls). Renderer + group detector short-circuit on this so the track
    # vanishes from operator view, state.tracks, and metrics. ByteTrack still
    # keeps the underlying track alive — the natural _drop_stale_tracks
    # eviction cleans it up eventually.
    vlm_marked_false: bool = False


FLASH_DEFAULTS: dict = {
    "min_area_far": 350,
    "min_area_near": 1500,
    "min_blob_bmr": 80.0,
    "min_blob_compactness": 0.40,
    "per_pixel_bmr": 30,
    "per_pixel_v": 235,
    "persist_frames": 2,
    "merge_dist": 120.0,
    # Switch 1: temporal V-channel variance gate. Real welding arcs flicker
    # fast (V swings >50 over 2-3 frames). Static cyan surfaces (PPE accents,
    # painted scaffolding) don't. When enabled, the per-pixel mask AND's with
    # `(max_V - min_V) >= temporal_variance_min` over the last 3 V frames.
    # Default OFF so behaviour is unchanged until you flip the switch.
    "temporal_variance_enabled": False,
    "temporal_variance_min": 30,
}


# Bounds enforced when the user tunes via the UI. Keeps values in physically
# meaningful ranges (e.g. a per-pixel V of 0 or 300 is nonsense).
FLASH_PARAM_BOUNDS: dict = {
    "min_area_far":         (50,    5000),
    "min_area_near":        (200,  10000),
    "min_blob_bmr":         (0.0,   200.0),
    "min_blob_compactness": (0.0,     1.0),
    "per_pixel_bmr":        (0,      100),
    "per_pixel_v":          (150,    255),
    "persist_frames":       (1,       10),
    "merge_dist":           (10.0,  1000.0),
    "temporal_variance_enabled": (0,      1),
    "temporal_variance_min":     (5,    100),
}


class FlashDetector:
    """Detects bright welding-arc events as saturated blue-white blobs.

    Filters tuned from a 6-frame analysis pass on this scene:
      * **per-pixel** thresholds: V > 235 + (B−R) > 30 (was 20 — too lax,
        admitted reflections from chromed surfaces)
      * **perspective-aware min_area**: smaller minimum at the top of the
        frame (far-field arcs are tiny in pixels), larger at the bottom
        (near-field arcs are big; small bottom blobs are reflections off
        the floor or the chassis itself)
      * **per-blob B−R mean**: real arcs have strong blue tint (>= 100);
        reflections drop to 50–90
      * **per-blob compactness**: real arc blobs fill > 40% of their bbox;
        fragmented streaks (glare on a railing, etc.) score < 0.3

    All filter knobs are direct instance attributes so they can be mutated
    live from the UI tuning panel — `detect()` reads them every frame.
    """

    def __init__(
        self,
        min_area_far: int = FLASH_DEFAULTS["min_area_far"],
        min_area_near: int = FLASH_DEFAULTS["min_area_near"],
        min_blob_bmr: float = FLASH_DEFAULTS["min_blob_bmr"],
        min_blob_compactness: float = FLASH_DEFAULTS["min_blob_compactness"],
        per_pixel_bmr: int = FLASH_DEFAULTS["per_pixel_bmr"],
        per_pixel_v: int = FLASH_DEFAULTS["per_pixel_v"],
        persist_frames: int = FLASH_DEFAULTS["persist_frames"],
        merge_dist: float = FLASH_DEFAULTS["merge_dist"],
        temporal_variance_enabled: bool = FLASH_DEFAULTS["temporal_variance_enabled"],
        temporal_variance_min: int = FLASH_DEFAULTS["temporal_variance_min"],
        # Back-compat: a single `min_area` keyword overrides both bounds
        min_area: Optional[int] = None,
    ):
        if min_area is not None:
            self.min_area_far = min_area
            self.min_area_near = min_area
        else:
            self.min_area_far = min_area_far
            self.min_area_near = min_area_near
        self.min_blob_bmr = min_blob_bmr
        self.min_blob_compactness = min_blob_compactness
        self.per_pixel_bmr = per_pixel_bmr
        self.per_pixel_v = per_pixel_v
        self.persist_frames = persist_frames
        self.merge_dist = merge_dist
        self.temporal_variance_enabled = bool(temporal_variance_enabled)
        self.temporal_variance_min = int(temporal_variance_min)
        # Ring buffer of the last N V-channels (downsampled to halve compute).
        # Used only when temporal_variance_enabled is True.
        self._v_history: deque = deque(maxlen=3)
        self.recent: dict[int, FlashEvent] = {}
        self._next_id = 1

    @property
    def min_area(self) -> int:                  # back-compat for callers / analyzer
        return min(self.min_area_far, self.min_area_near)

    def _min_area_for_y(self, cy: float, frame_h: int) -> float:
        """Linear interpolation of the area floor as a function of y."""
        f = max(0.0, min(1.0, cy / max(1, frame_h)))   # 0 at top, 1 at bottom
        return self.min_area_far + (self.min_area_near - self.min_area_far) * f

    def detect(self, frame_bgr: np.ndarray, t: float) -> dict[int, FlashEvent]:
        """Returns {flash_id: FlashEvent} for confirmed flashes. IDs are stable across frames.

        The reported (cx, cy) is the *brightness-weighted* centroid of the blob — that
        lands on the bright core (the weld point) instead of the geometric center of
        the larger glow halo.
        """
        H, W = frame_bgr.shape[:2]
        # Welding arc has very high V (brightness), saturated, and high blue channel.
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
        v = hsv[:, :, 2]
        b = frame_bgr[:, :, 0].astype(np.int16)
        r = frame_bgr[:, :, 2].astype(np.int16)
        bmr = b - r                                          # signed; reflections often have low values
        bluish = bmr > self.per_pixel_bmr
        bright = v > self.per_pixel_v
        per_pixel = bright & bluish

        # Switch 1: temporal V-channel variance gate. Real arcs swing V hard
        # frame-to-frame; static cyan surfaces don't. We keep a 3-frame ring
        # buffer of V and require (max - min) >= threshold per pixel before
        # admitting it. The buffer is maintained unconditionally so toggling
        # the switch on doesn't require a warmup wait — if the buffer hasn't
        # been written yet (first call) we fall back to single-frame behaviour.
        self._v_history.append(v)
        if self.temporal_variance_enabled and len(self._v_history) >= 2:
            stack = np.stack(self._v_history, axis=0)        # (K, H, W) uint8
            v_max = stack.max(axis=0)
            v_min = stack.min(axis=0)
            flicker = (v_max.astype(np.int16) - v_min.astype(np.int16)) >= self.temporal_variance_min
            per_pixel = per_pixel & flicker

        mask = per_pixel.astype(np.uint8) * 255

        # Tighten then expand to remove specks while merging close blobs.
        # cv2 stubs widen the dtype-typed return; silence the strict narrowing.
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))     # type: ignore[assignment]
        mask = cv2.morphologyEx(mask, cv2.MORPH_DILATE, np.ones((9, 9), np.uint8))   # type: ignore[assignment]

        n, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
        events_now: list[FlashEvent] = []
        for i in range(1, n):
            area = int(stats[i, cv2.CC_STAT_AREA])
            bx = int(stats[i, cv2.CC_STAT_LEFT])
            by = int(stats[i, cv2.CC_STAT_TOP])
            bw = int(stats[i, cv2.CC_STAT_WIDTH])
            bh = int(stats[i, cv2.CC_STAT_HEIGHT])
            if bw == 0 or bh == 0:
                continue
            # Geometric centroid (fallback)
            gcx, gcy = float(centroids[i, 0]), float(centroids[i, 1])

            # Perspective-aware minimum area
            min_area_here = self._min_area_for_y(gcy, H)
            if area < min_area_here:
                continue

            # Per-blob compactness (filled fraction of bbox)
            compactness = area / max(1, bw * bh)
            if compactness < self.min_blob_compactness:
                continue

            # Per-blob mean (B-R) — strong discriminator for real arcs vs reflections
            sub_lab = labels[by:by + bh, bx:bx + bw]
            in_blob = (sub_lab == i)
            sub_bmr = bmr[by:by + bh, bx:bx + bw]
            mean_bmr = float(sub_bmr[in_blob].mean()) if in_blob.any() else 0.0
            if mean_bmr < self.min_blob_bmr:
                continue

            # Brightness-weighted centroid biases toward the hot core. Restrict to
            # this blob's bbox and weight only pixels that belong to the blob,
            # by their excess brightness above 220.
            sub_v = v[by:by + bh, bx:bx + bw].astype(np.float32)
            weights = np.where(in_blob, np.maximum(sub_v - 220.0, 0.0), 0.0)
            total_w = float(weights.sum())
            if total_w > 0:
                ys_grid, xs_grid = np.mgrid[0:bh, 0:bw]
                cx = bx + float((weights * xs_grid).sum() / total_w)
                cy = by + float((weights * ys_grid).sum() / total_w)
            else:
                cx, cy = gcx, gcy
            events_now.append(FlashEvent(cx=cx, cy=cy, area=area, first_seen=t, last_seen=t))

        # Merge with recent events to give them persistence
        merged: dict[int, FlashEvent] = {}
        used = set()
        for ev in events_now:
            best_id = None
            best_d = self.merge_dist
            for k, prev in self.recent.items():
                if k in used:
                    continue
                d = ((ev.cx - prev.cx) ** 2 + (ev.cy - prev.cy) ** 2) ** 0.5
                if d < best_d:
                    best_d = d
                    best_id = k
            if best_id is not None:
                used.add(best_id)
                prev = self.recent[best_id]
                merged[best_id] = FlashEvent(
                    cx=ev.cx, cy=ev.cy, area=max(prev.area, ev.area),
                    first_seen=prev.first_seen, last_seen=t,
                )
            else:
                merged[self._next_id] = ev
                self._next_id += 1

        # Carry over recent events that haven't been seen this frame for a short grace period
        for k, prev in self.recent.items():
            if k in used:
                continue
            if t - prev.last_seen < 0.4:
                merged[k] = prev

        self.recent = merged
        # Only return events that have persisted for at least N observations (filters spurious flicker)
        return {fid: ev for fid, ev in self.recent.items() if (ev.last_seen - ev.first_seen) >= 0.05}


def build_flash_mask(
    frame_shape: tuple[int, ...],
    flashes: dict[int, "FlashEvent"],
    dilate_extra: int = 30,
) -> Optional[np.ndarray]:
    """Mask of welding-flash regions to ignore in motion detection. Returns
    a single-channel uint8 mask (255 inside flash regions) sized to the full
    frame, or None if there are no flashes.
    """
    if not flashes:
        return None
    mask = np.zeros(frame_shape[:2], dtype=np.uint8)
    for ev in flashes.values():
        radius = max(40, int((ev.area ** 0.5) * 0.8)) + dilate_extra
        # cv2.circle stubs require Sequence[float] for color; (255,) is fine at runtime.
        cv2.circle(mask, (int(ev.cx), int(ev.cy)), radius, 255, -1)  # type: ignore[call-overload]
    return mask


def attribute_welding(
    flashes: dict[int, FlashEvent],
    tracks: dict[int, TrackHistory],
    t: float,
    max_dist: float = 200.0,
    bbox_pad: float = 0.4,
) -> tuple[set[int], dict[int, FlashEvent]]:
    """Attribute each arc flash to a welder track ONLY if the flash centroid
    falls inside that track's last bbox (padded by ``bbox_pad`` on each side).

    A welder's arc is at their hands/torch — inside or just below their box.
    The previous logic snapped each flash to the nearest track within 350 px of
    any recent position, which let an arc bleed onto an adjacent non-welding
    worker. Requiring bbox containment (plus a ``max_dist`` backstop on the
    bbox-center distance, for very large boxes) keeps the label on the actual
    welder. Tracks unseen for >4 s are ignored (the orphan path → phantom
    handles a welder D-FINE has lost). Returns (welding_track_ids, orphans).
    """
    welding_ids: set[int] = set()
    orphans: dict[int, FlashEvent] = {}
    for fid, ev in flashes.items():
        best_id = None
        best_d = float("inf")
        for tid, hist in tracks.items():
            bb = hist.last_bbox
            if bb is None or (t - hist.last_seen_t) > 4.0:
                continue
            x1, y1, x2, y2 = bb
            pw = (x2 - x1) * bbox_pad
            ph = (y2 - y1) * bbox_pad
            if not (x1 - pw <= ev.cx <= x2 + pw and y1 - ph <= ev.cy <= y2 + ph):
                continue  # arc not on this worker's body
            cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
            d = ((cx - ev.cx) ** 2 + (cy - ev.cy) ** 2) ** 0.5
            if d < max_dist and d < best_d:
                best_d = d
                best_id = tid
        if best_id is not None:
            welding_ids.add(best_id)
            tracks[best_id].welding_until = t + 1.5
        else:
            orphans[fid] = ev
    for tid, hist in tracks.items():
        if hist.welding_until > t:
            welding_ids.add(tid)
    return welding_ids, orphans


# Phantom tracks: stable IDs allocated to long-persisting unattributed welding flashes.
# track_id = PHANTOM_OFFSET + phantom_id; phantom_id is allocated sequentially by PhantomTracker
# (NOT tied to flash_id) so phantom_id can survive an arc-off pause and resume.
PHANTOM_OFFSET = 100_000


def is_phantom(track_id: int) -> bool:
    return track_id >= PHANTOM_OFFSET


def phantom_label(track_id: int) -> str:
    return f"A{track_id - PHANTOM_OFFSET}"


def phantom_track_id(phantom_id: int) -> int:
    return PHANTOM_OFFSET + phantom_id


@dataclass
class PhantomState:
    phantom_id: int
    flash_id: Optional[int]   # currently-active flash, or None during grace period
    cx: float
    cy: float
    area: int
    first_seen: float
    last_seen: float


class PhantomTracker:
    """Promotes persistent orphan flashes to stable phantom IDs.

    A phantom keeps its ID across short arc-off pauses by being held in a
    grace-period buffer; when a new orphan flash appears within `merge_dist`
    of a recent phantom, the old phantom_id is re-attached.
    """

    def __init__(
        self,
        grace_s: float = 6.0,         # how long to hold a phantom after its flash dies
        merge_dist: float = 350.0,    # how far an arc may move and still inherit the same phantom
        min_age_s: float = 1.0,       # min orphan-flash age before promotion to a brand-new phantom
    ):
        self.grace_s = grace_s
        self.merge_dist = merge_dist
        self.min_age_s = min_age_s
        self._next_pid = 1
        self._active: dict[int, PhantomState] = {}  # phantom_id -> state

    @property
    def active(self) -> dict[int, PhantomState]:
        return self._active

    def step(
        self,
        t: float,
        orphan_flashes: dict[int, "FlashEvent"],
        claimed_centroids: Optional[list[tuple[float, float]]] = None,
    ) -> set[int]:
        """Update phantoms with this frame's orphan flashes. Returns the set of phantom_ids
        that are *visible* this frame (i.e. have a currently-active flash).

        `claimed_centroids` is the list of flash centroids that *were* attributed to a
        real YOLO track this frame. Any phantom in grace (no orphan flash this frame)
        whose location is within merge_dist of a claimed centroid is retired early —
        this prevents a stale phantom from re-anchoring on a later orphan flash and
        rendering alongside the real track that took over its location."""
        used: set[int] = set()
        visible: set[int] = set()

        # 1. Try to attribute each orphan flash to an existing (live or in-grace) phantom
        for fid, ev in orphan_flashes.items():
            best_pid = None
            best_d = self.merge_dist
            for pid, ps in self._active.items():
                if pid in used:
                    continue
                if t - ps.last_seen > self.grace_s:
                    continue
                d = ((ev.cx - ps.cx) ** 2 + (ev.cy - ps.cy) ** 2) ** 0.5
                if d < best_d:
                    best_d = d
                    best_pid = pid

            if best_pid is not None:
                ps = self._active[best_pid]
                ps.flash_id = fid
                ps.cx = ev.cx
                ps.cy = ev.cy
                ps.area = max(ps.area, ev.area)
                ps.last_seen = t
                used.add(best_pid)
                visible.add(best_pid)
            else:
                # Allocate a new phantom only if the orphan flash has persisted briefly.
                # This avoids creating a phantom for a single-frame spurious flicker.
                if t - ev.first_seen >= self.min_age_s:
                    pid = self._next_pid
                    self._next_pid += 1
                    self._active[pid] = PhantomState(
                        phantom_id=pid, flash_id=fid,
                        cx=ev.cx, cy=ev.cy, area=ev.area,
                        first_seen=ev.first_seen, last_seen=t,
                    )
                    visible.add(pid)
                    used.add(pid)

        # 2. Phantoms not visible this frame: clear their flash_id (they're in grace)
        for pid, ps in self._active.items():
            if pid not in used:
                ps.flash_id = None

        # 3. Retire phantoms whose location was claimed by a real YOLO track this frame
        # AND that did not get an orphan flash assigned (i.e., they're in grace).
        # If a phantom is still actively flashing (in `used`), keep it — the real track
        # may simply be near, not the actual welder.
        if claimed_centroids:
            for pid in list(self._active.keys()):
                if pid in used:
                    continue
                ps = self._active[pid]
                for cx, cy in claimed_centroids:
                    if ((ps.cx - cx) ** 2 + (ps.cy - cy) ** 2) ** 0.5 < self.merge_dist:
                        self._active.pop(pid, None)
                        break

        # 4. Retire phantoms that have been in grace too long
        for pid in [pid for pid, ps in self._active.items() if t - ps.last_seen > self.grace_s]:
            self._active.pop(pid, None)

        return visible


# ----- High-level activity rollup -----------------------------------------

# Operator policy: a worker is counted as "working" until the classifier
# can prove they're moving (walking) or idle (sitting). "standing" and
# "unknown" therefore roll up to working — at low fps the heuristic
# emits these constantly and they should default to the productive bucket,
# not bloat an `unclear` slice the operator can't act on.
WORKING_LABELS = {"welding", "standing", "unknown"}
MOVING_LABELS = {"walking"}
IDLE_LABELS = {"sitting"}
UNCLEAR_LABELS: set[str] = set()

ROLLUP_ORDER = ["working", "moving", "idle", "unclear"]
ROLLUP_COLORS = {
    "working":  (0,   80, 220),  # red-ish
    "moving":   (0, 180, 255),   # amber
    "idle":     (220, 120, 80),  # cool
    "unclear":  (140, 140, 140), # grey
}


def rollup_activity(label: str) -> str:
    if label in MOVING_LABELS:
        return "moving"
    if label in IDLE_LABELS:
        return "idle"
    # Default → working. Catches the explicit WORKING_LABELS set above
    # AND any future / unrecognized activity strings: per operator policy,
    # uncategorised → working until proven otherwise.
    return "working"


def classify_motion(hist: TrackHistory, t: float) -> tuple[str, float]:
    if len(hist.positions) < 4:
        return "unknown", 0.0
    pts = [(ts, x, y) for (ts, x, y) in hist.positions if (t - ts) < 1.5]
    if len(pts) < 3:
        return "unknown", 0.0
    xs = np.array([p[1] for p in pts])
    ys = np.array([p[2] for p in pts])
    # px/sec speed normalized by bbox-ish scale; we don't have h here so use absolute
    dx = xs[-1] - xs[0]
    dy = ys[-1] - ys[0]
    dt = pts[-1][0] - pts[0][0]
    if dt < 0.2:
        return "unknown", 0.0
    speed = (dx ** 2 + dy ** 2) ** 0.5 / dt  # px/sec
    if speed > 80:
        return "walking", min(0.9, 0.4 + speed / 400)
    if speed < 20:
        return "standing", 0.5
    return "unknown", 0.3
