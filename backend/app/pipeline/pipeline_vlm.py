"""VLM activity classifier dispatch + tracklet capture + patch signatures.

Mixin extracted from pipeline.py. The patch-signature helpers also serve the
stillness-detection branch in pipeline_detection.py — they're hosted here
because they share the same hashing approach as the (in-flight, not-yet-
implemented) ReID embedding branch.

Private state lives in a single dataclass owned by the Pipeline:
    self.vlm_state          — _VlmRuntimeState (per-track tracklets + dispatch)

Required attributes on `self` (provided by Pipeline core):
    self.cfg                : PipelineConfig
    self.vlm                : VlmClassifier | None
    self.vlm_enabled_runtime: bool
    self.tracks             : dict[int, TrackHistory]
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from activity import classify_motion
from tracklet import TrackletBuffer
from vlm_classifier import VlmResult


@dataclass
class _VlmRuntimeState:
    """Per-track tracklet buffers + dispatch deduplication.

    `tracklets` is keyed by public track id; entries grow as the worker is
    seen across cycles, then get classified by VLM and reset on revisit.
    `inflight_ids` gates concurrent dispatches per track (and globally,
    via VlmClassifier.can_fire()).
    """
    tracklets: dict[int, TrackletBuffer] = field(default_factory=dict)
    inflight_ids: set[int] = field(default_factory=set)


class _VlmMixin:
    """VLM dispatch + tracklet buffers + patch-signature helpers."""

    # ------------------------------------------------------------------
    # Tracklet capture — small crops appended per visible track per cycle
    # ------------------------------------------------------------------

    def _capture_tracklets(self, frame: np.ndarray, t: float, seen_ids: set[int]):
        """Append a small crop to each visible track's tracklet buffer."""
        if not self.vlm_enabled_runtime:
            return
        tracklets = self.vlm_state.tracklets
        for tid in seen_ids:
            hist = self.tracks.get(tid)
            if hist is None or hist.last_bbox is None:
                continue
            x1, y1, x2, y2 = hist.last_bbox
            if (y2 - y1) < self.cfg.vlm_min_height_full:
                continue
            tb = tracklets.get(tid)
            if tb is None:
                tb = TrackletBuffer()
                tracklets[tid] = tb
            tb.maybe_capture(frame, t, hist.last_bbox)

    # ------------------------------------------------------------------
    # VLM dispatch — at most one in flight at a time
    # ------------------------------------------------------------------

    def _maybe_fire_vlm(self, t: float):
        """Priority-class-based VLM dispatch (session 5):

            0  never classified           — new track gets first verdict ASAP
            1  recent heuristic transition — confirm new activity within 2 s
            2  heuristic == "unknown"      — VLM is the only source of truth
            3  regular revisit            — cadence-driven refresh

        Established tracks whose heuristic activity is in
        cfg.vlm_heuristic_confident_labels and matches the last VLM verdict
        and has been stable for >= cfg.vlm_confident_stability_s are skipped
        — the heuristic has them nailed, save the slot for harder cases.
        """
        if not self.vlm_enabled_runtime or self.vlm is None:
            return
        if not self.vlm.can_fire():
            return
        vlm_state = self.vlm_state
        confident = set(self.cfg.vlm_heuristic_confident_labels or [])
        stability_s = float(self.cfg.vlm_confident_stability_s)
        candidates: list[tuple[tuple, int]] = []
        for tid, hist in self.tracks.items():
            if tid in vlm_state.inflight_ids:
                continue
            if hist.vlm_marked_false:
                continue
            tb = vlm_state.tracklets.get(tid)
            if tb is None or len(tb.frames) < 2:
                continue
            if hist.last_seen_t == 0:
                continue
            age = t - hist.last_seen_t
            if age > 5.0:
                continue
            if t - tb.frames[0].t < self.cfg.vlm_min_age_s:
                continue

            if hist.vlm_last_t == 0:
                # Class 0: never classified — fire ASAP. Newest tid wins ties
                # (matches baseline behavior: most recent ByteTrack assignment
                # is the one the operator most wants visible).
                priority = (0, -tid)
                candidates.append((priority, tid))
                continue

            if not self.vlm.should_revisit(hist.vlm_last_t, t):
                continue

            last_change_t = hist.timeline[-1][0] if hist.timeline else 0.0
            if (
                hist.activity in confident
                and hist.activity == hist.vlm_activity
                and (t - last_change_t) >= stability_s
            ):
                continue  # confident-heuristic skip

            if last_change_t > hist.vlm_last_t and (t - last_change_t) < 2.0:
                priority = (1, -last_change_t, tid)
            elif hist.activity == "unknown":
                priority = (2, -hist.vlm_last_t, tid)
            else:
                priority = (3, -hist.vlm_last_t, tid)
            candidates.append((priority, tid))

        if not candidates:
            return
        candidates.sort()
        tid = candidates[0][1]
        tb = vlm_state.tracklets[tid]
        vlm_state.inflight_ids.add(tid)
        # Snapshot the buffer (dedupe to avoid the buffer mutating while VLM call is in flight)
        snapshot = TrackletBuffer(
            max_frames=tb.max_frames,
            min_dt=tb.min_dt,
            crop_long_side=tb.crop_long_side,
            pad_ratio=tb.pad_ratio,
        )
        for f in list(tb.frames):
            snapshot.frames.append(f)
        asyncio.create_task(
            self._run_vlm(tid, snapshot, t),
            name=f"vlm-{tid}",
        )

    async def _run_vlm(self, tid: int, tb: TrackletBuffer, t_fired: float):
        try:
            assert self.vlm is not None
            res: Optional[VlmResult] = await self.vlm.classify(tb)
            if res is None:
                return
            hist = self.tracks.get(tid)
            if hist is None:
                return
            # Stability hysteresis: only promote a new label into vlm_activity
            # once it's been observed K consecutive times. K=1 (default) keeps
            # the original behavior — every result sticks immediately.
            hist.vlm_history.append(res.activity)
            k = max(1, int(self.cfg.vlm_stability_k))
            recent = list(hist.vlm_history)[-k:]
            promote = (
                hist.vlm_activity is None                     # bootstrap: take first label
                or len(recent) >= k and len(set(recent)) == 1 # stable: K-of-K agree
            )
            # "not_a_person" is destructive (drops the track from view + state
            # + metrics). Override the gate: never bootstrap-promote it, and
            # always require ≥2 consecutive verdicts even if K is 1, so a
            # single misclassification can't erase a real worker.
            if res.activity == "not_a_person":
                NOT_PERSON_K = 2
                tail = list(hist.vlm_history)[-NOT_PERSON_K:]
                promote = (
                    len(tail) >= NOT_PERSON_K
                    and all(x == "not_a_person" for x in tail)
                )
            if promote:
                hist.vlm_activity = res.activity
                hist.vlm_rollup = res.rollup
                hist.vlm_conf = res.confidence
                if res.activity == "not_a_person":
                    hist.vlm_marked_false = True
            hist.vlm_last_t = t_fired
        finally:
            self.vlm_state.inflight_ids.discard(tid)

    def _effective_vlm(self, hist, t: float) -> tuple[Optional[str], Optional[str]]:
        """Return the authoritative (label, rollup) to display for this track.

        The VLM (SigLIP) only owns the *stationary* call (working vs idle vs
        not_a_person). The two signals it cannot judge from a single static
        crop are taken from stronger sources and win over any VLM verdict:

          - Welding: arc detection. `_decide_activities` sets hist.activity
            = "welding" for arc-attributed tracks earlier this same frame.
          - Walking: track-centroid velocity (`classify_motion`). SigLIP can't
            see motion in one frame, so it mislabels walkers as idle.

        Otherwise the fresh SigLIP verdict (held `2 * vlm_revisit_s`) arbitrates
        the stationary case. (None, None) → caller falls back to the heuristic
        activity, which rolls up to `working` for standing/unknown.
        """
        if hist is None:
            return (None, None)
        # Arc-welding is authoritative.
        if hist.activity == "welding":
            return ("welding", "working")
        # Motion owns walking.
        m_label, m_conf = classify_motion(hist, t)
        if m_label == "walking" and m_conf >= 0.5:
            return ("walking", "moving")
        # Stationary → fresh SigLIP verdict (if any).
        if not hist.vlm_activity or hist.vlm_last_t == 0:
            return (None, None)
        if t - hist.vlm_last_t >= 2 * self.cfg.vlm_revisit_s:
            return (None, None)
        return (hist.vlm_activity, hist.vlm_rollup or "unclear")
