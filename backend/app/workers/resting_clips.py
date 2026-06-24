"""Resting-worker instance tracking for clip capture.

Pure logic, no IO. One ``RestingClipTracker`` per running camera that has an
enabled ``resting_worker`` rule. Fed the per-frame ``(t_seconds, tracks)`` from
the rendered state; it watches each track's DISPLAY activity and emits a
``RestingInstance`` whenever a track has spent a sustained period in a
resting/idle posture (sitting / sleeping / standing_idle / on_phone).

It also keeps a short rolling per-track **bbox trajectory** for ALL tracks
(timestamped), so when an instance closes the clip can FOLLOW the worker —
including the seconds of pre-roll before they settled (the worker was usually
walking in, recorded here while still moving). The instance carries that
trajectory; the camera worker / clip extractor pan a crop window along it.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

# Display activity labels (post-alias, as they appear in state["tracks"][].activity)
# that count as "resting". Plain "standing" is intentionally excluded — the
# heuristic assigns it to any stationary worker, including those actively working.
DEFAULT_RESTING_LABELS = ["sitting", "sleeping", "standing_idle", "on_phone"]

DEFAULT_PRE_ROLL_S = 3.0
DEFAULT_MIN_RESTING_S = 5.0
DEFAULT_END_GRACE_S = 2.0
DEFAULT_MAX_CLIP_S = 120.0


@dataclass
class RestingInstance:
    """A closed resting period for one track. Pre-roll is applied at extraction."""

    track_id: int
    start_t: float                       # video time of first resting classification
    end_t: float                         # video time the resting period ended
    last_bbox: Optional[list[int]]       # last known bbox (source px) while resting
    vlm_conf: Optional[float]            # last VLM confidence seen while resting
    # Timestamped bbox trajectory over [start_t - pre_roll, end_t] (source px),
    # sampled at the pipeline rate. Drives the following crop. May be sparse /
    # empty if the worker wasn't detected for parts of the window.
    track: list[tuple[float, list[int]]] = field(default_factory=list)


@dataclass
class _Open:
    start_t: float
    last_resting_t: float                # last frame this track was IN the resting set
    last_seen_t: float                   # last frame this track appeared at all
    last_bbox: Optional[list[int]] = None
    last_vlm_conf: Optional[float] = None


class RestingClipTracker:
    def __init__(self, params: Optional[dict] = None) -> None:
        p = params or {}
        self.pre_roll_s = _f(p.get("pre_roll_s"), DEFAULT_PRE_ROLL_S)
        self.min_resting_s = _f(p.get("min_resting_s"), DEFAULT_MIN_RESTING_S)
        self.end_grace_s = _f(p.get("end_grace_s"), DEFAULT_END_GRACE_S)
        self.max_clip_s = _f(p.get("max_clip_s"), DEFAULT_MAX_CLIP_S)
        labels = p.get("resting_labels") or DEFAULT_RESTING_LABELS
        self.resting_labels = {str(x) for x in labels}
        self._open: dict[int, _Open] = {}
        # Rolling per-track (t, bbox) history. Long enough to cover a whole
        # clip window: pre-roll + the longest possible rest + a margin.
        self._hist_window = self.pre_roll_s + self.max_clip_s + 5.0
        self._history: dict[int, deque[tuple[float, list[int]]]] = {}

    def update(self, t_seconds: float, tracks: list[dict]) -> list[RestingInstance]:
        """Fold one frame; return any instances that closed this frame."""
        t = float(t_seconds)
        present: set[int] = set()
        for tr in tracks:
            tid = tr.get("track_id")
            if tid is None:
                continue
            tid = int(tid)
            present.add(tid)
            bbox = tr.get("bbox")
            if bbox:
                hist = self._history.setdefault(tid, deque())
                hist.append((t, [int(v) for v in bbox]))
                while hist and hist[0][0] < t - self._hist_window:
                    hist.popleft()
            resting = str(tr.get("activity") or "") in self.resting_labels
            # ghost track dicts omit vlm_conf → use .get
            vconf = tr.get("vlm_conf")
            if resting:
                inst = self._open.get(tid)
                if inst is None:
                    self._open[tid] = _Open(
                        start_t=t, last_resting_t=t, last_seen_t=t,
                        last_bbox=list(bbox) if bbox else None,
                        last_vlm_conf=float(vconf) if vconf is not None else None,
                    )
                else:
                    inst.last_resting_t = t
                    inst.last_seen_t = t
                    if bbox:
                        inst.last_bbox = list(bbox)
                    if vconf is not None:
                        inst.last_vlm_conf = float(vconf)
            elif tid in self._open:
                self._open[tid].last_seen_t = t

        self._gc_history(t, present)
        return self._close_pass(t, present)

    def _gc_history(self, t: float, present: set[int]) -> None:
        """Drop trajectories for tracks gone longer than the clip window."""
        for tid in [k for k in self._history if k not in present]:
            hist = self._history[tid]
            if not hist or hist[-1][0] < t - self._hist_window:
                del self._history[tid]

    def _trajectory(self, tid: int, clip_start: float, end_t: float) -> list[tuple[float, list[int]]]:
        hist = self._history.get(tid)
        if not hist:
            return []
        return [(ts, list(b)) for (ts, b) in hist if clip_start - 0.05 <= ts <= end_t + 0.05]

    def _close_pass(self, t: float, present: set[int]) -> list[RestingInstance]:
        closed: list[RestingInstance] = []
        for tid, inst in list(self._open.items()):
            left_set = (t - inst.last_resting_t) >= self.end_grace_s
            absent = (tid not in present) and (t - inst.last_seen_t) >= self.end_grace_s
            capped = (t - inst.start_t) >= self.max_clip_s
            if not (left_set or absent or capped):
                continue
            end_t = (inst.start_t + self.max_clip_s) if capped else inst.last_resting_t
            del self._open[tid]
            if end_t - inst.start_t >= self.min_resting_s:
                closed.append(RestingInstance(
                    track_id=tid, start_t=inst.start_t, end_t=end_t,
                    last_bbox=inst.last_bbox, vlm_conf=inst.last_vlm_conf,
                    track=self._trajectory(tid, inst.start_t - self.pre_roll_s, end_t),
                ))
            # Cap-close while still resting → re-open a fresh instance now.
            if capped and tid in present and (t - inst.last_resting_t) < self.end_grace_s:
                self._open[tid] = _Open(
                    start_t=t, last_resting_t=t, last_seen_t=t,
                    last_bbox=inst.last_bbox, last_vlm_conf=inst.last_vlm_conf,
                )
        return closed

    def flush(self, t_seconds: float) -> list[RestingInstance]:
        """Close all still-open instances (called once when the worker stops)."""
        t = float(t_seconds)
        out: list[RestingInstance] = []
        for tid, inst in self._open.items():
            if inst.last_resting_t - inst.start_t >= self.min_resting_s:
                out.append(RestingInstance(
                    track_id=tid, start_t=inst.start_t, end_t=inst.last_resting_t,
                    last_bbox=inst.last_bbox, vlm_conf=inst.last_vlm_conf,
                    track=self._trajectory(tid, inst.start_t - self.pre_roll_s, inst.last_resting_t),
                ))
        self._open.clear()
        return out


def _f(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default
