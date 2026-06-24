"""Spatial-clustering group detector.

Flags 2+ idle-classified workers standing close together for a sustained time —
the typical visual signature of "chatting in a group". Built on top of the
existing per-track activity classification (VLM where available, heuristic
rollup otherwise), so we don't need a separate ML model.

Pipeline per frame:
  1. Filter to tracks that are stationary (low velocity) AND idle (rollup is
     `idle`, or VLM label is one of {chatting, standing_idle, on_phone, sleeping}).
     If `idle_only` is False, every stationary track is eligible.
  2. Cluster the eligible centroids by proximity (union-find on pairwise distances).
  3. Track each cluster across frames using the frozenset of member IDs as a key.
     Promote to a "group" only after `min_duration_s` of consistent membership.
  4. Drop candidates whose membership hasn't appeared in ~1.5 s (members walked
     off, or someone joined/left → key changes, candidate restarts under the
     new key — short by design).

All knobs are direct instance attributes so the live-tuning registry can mutate
them without recreating the detector. `step()` reads them every frame.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from activity import TrackHistory, rollup_activity

# VLM labels the detector treats as "explicitly not working"
NON_WORKING_VLM = {"chatting", "standing_idle", "on_phone", "sleeping"}


@dataclass
class Group:
    """A confirmed group — emitted only after `min_duration_s` of persistence."""
    group_id: int
    member_ids: tuple[int, ...]      # sorted for determinism
    cx: float                         # cluster centroid in source-frame px
    cy: float
    radius: float                     # max distance from centroid to any member
    first_seen_t: float
    age_s: float
    is_chatting: bool = False         # sustained idle co-presence (age_s >= chatting_min_duration_s)


class GroupDetector:
    def __init__(
        self,
        proximity_px: int = 250,
        min_members: int = 2,
        min_duration_s: float = 5.0,
        max_velocity_pxs: float = 30.0,
        idle_only: bool = True,
        chatting_min_duration_s: float = 10.0,
    ):
        self.proximity_px = proximity_px
        self.min_members = min_members
        self.min_duration_s = min_duration_s
        self.max_velocity_pxs = max_velocity_pxs
        self.idle_only = idle_only
        # Sustained idle co-presence beyond this is treated as `chatting`.
        # Must be >= min_duration_s. The signal: 2+ workers stationary, none
        # doing working-rollup activity, together for at least this long.
        self.chatting_min_duration_s = chatting_min_duration_s

        # frozenset[track_id] → {first_seen, last_seen, group_id}
        self._candidates: dict[frozenset[int], dict] = {}
        self._next_gid = 1

    # ------------------------------------------------------------------

    @staticmethod
    def _velocity(hist: TrackHistory, t: float, window: float = 2.0) -> float:
        recent = [(ts, x, y) for (ts, x, y) in hist.positions if t - ts < window]
        if len(recent) < 2:
            return 0.0
        dt = recent[-1][0] - recent[0][0]
        if dt < 0.1:
            return 0.0
        dx = recent[-1][1] - recent[0][1]
        dy = recent[-1][2] - recent[0][2]
        return math.hypot(dx, dy) / dt

    @staticmethod
    def _is_idle(hist: TrackHistory) -> bool:
        """Prefer the VLM label when available; otherwise fall back to the
        heuristic rollup (which buckets `unknown`/`standing` as `unclear`).

        Special case: a VLM `walking` verdict can lag reality by up to 10 s
        (the worker walked, then stopped, but the mosaic captured the motion).
        We accept `walking` here as a *candidate* — the velocity gate in step()
        is the source of truth for whether they're actually moving, and will
        filter out anyone going faster than `max_velocity_pxs`.
        """
        if hist.vlm_activity:
            return (hist.vlm_activity in NON_WORKING_VLM
                    or hist.vlm_activity == "walking")
        return rollup_activity(hist.activity) in {"idle", "unclear"}

    # ------------------------------------------------------------------

    def step(self, tracks: dict[int, TrackHistory], t: float) -> list[Group]:
        # 1. Filter eligible tracks
        eligible: list[tuple[int, float, float]] = []  # (track_id, cx, cy)
        for tid, hist in tracks.items():
            if hist.last_bbox is None:
                continue
            # Filter out tracks the VLM stably classified as not-a-person.
            if hist.vlm_marked_false:
                continue
            if t - hist.last_seen_t > 1.0:
                continue            # only fresh tracks
            if self.idle_only and not self._is_idle(hist):
                continue
            if self._velocity(hist, t) > self.max_velocity_pxs:
                continue
            x1, y1, x2, y2 = hist.last_bbox
            eligible.append((tid, (x1 + x2) / 2, (y1 + y2) / 2))

        # 2. Cluster by proximity (union-find; n is small)
        n = len(eligible)
        parent = list(range(n))

        def _find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(n):
            _, cxi, cyi = eligible[i]
            for j in range(i + 1, n):
                _, cxj, cyj = eligible[j]
                if math.hypot(cxi - cxj, cyi - cyj) <= self.proximity_px:
                    ri, rj = _find(i), _find(j)
                    if ri != rj:
                        parent[rj] = ri

        clusters: dict[int, list[int]] = {}
        for i in range(n):
            clusters.setdefault(_find(i), []).append(i)

        # 3. Track each cluster across frames; promote when sustained
        confirmed: list[Group] = []
        for idxs in clusters.values():
            if len(idxs) < self.min_members:
                continue
            members = frozenset(eligible[i][0] for i in idxs)
            cand = self._candidates.get(members)
            if cand is None:
                cand = {"first_seen": t, "last_seen": t, "group_id": self._next_gid}
                self._next_gid += 1
                self._candidates[members] = cand
            else:
                cand["last_seen"] = t
            age = t - cand["first_seen"]
            if age >= self.min_duration_s:
                cxs = [eligible[i][1] for i in idxs]
                cys = [eligible[i][2] for i in idxs]
                ccx = sum(cxs) / len(cxs)
                ccy = sum(cys) / len(cys)
                radius = max(math.hypot(cx - ccx, cy - ccy) for cx, cy in zip(cxs, cys))
                confirmed.append(Group(
                    group_id=cand["group_id"],
                    member_ids=tuple(sorted(members)),
                    cx=ccx, cy=ccy, radius=radius,
                    first_seen_t=cand["first_seen"],
                    age_s=age,
                    is_chatting=(age >= self.chatting_min_duration_s),
                ))

        # 4. GC stale candidates (≥1.5 s since last seen → drop)
        for key in [k for k, v in self._candidates.items() if t - v["last_seen"] > 1.5]:
            self._candidates.pop(key, None)

        return confirmed
