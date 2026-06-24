"""Workforce metrics aggregation.

One ``MetricsAggregator`` per running camera. Each frame the camera worker
calls ``add(state, dt)``; the aggregator accumulates **worker-seconds** per
activity and per rollup category into fixed 10-second time buckets. A
rolling window of buckets (~8 h retention) lets ``summary(window_s)``
answer "over the last N seconds, the workforce spent X% working / Y%
moving / Z% idle".

worker-seconds = sum over visible tracks of (time that track held an
activity). A frame with 10 tracks advancing 0.1 s contributes 1.0
worker-second, split across whatever activities those 10 tracks held.
Percentages are over total worker-seconds so they sum to ~100%.

Phase 3: the aggregator can be flushed to the ``metric_samples`` table for
historical reports that survive camera restart. The worker calls
``collect_flushable(now_t)`` to drain closed-and-unflushed buckets, persists
them, then calls ``mark_flushed_through(last_start_t)`` only on success so a
DB error doesn't silently drop a bucket.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

BUCKET_S = 10.0          # bucket granularity
RETENTION_S = 8 * 3600.0  # keep ~8 h of buckets (~2880 buckets)
MAX_DT = 5.0             # clamp per-frame dt so a stall can't skew metrics


@dataclass
class _Bucket:
    start_t: float
    activity_s: dict[str, float] = field(default_factory=dict)
    rollup_s: dict[str, float] = field(default_factory=dict)
    headcount_dt: float = 0.0  # sum(headcount * dt) — for time-weighted average
    dt_sum: float = 0.0
    frames: int = 0
    peak_headcount: int = 0
    # Per-zone occupancy histogram: {zone_id: {count: seconds-at-that-count}}.
    # Time-integrated: every frame adds dt to the bucket for the count its
    # zone currently holds. Threshold-agnostic — understaffed/overstaffed/avg
    # /peak all derive from this at read time.
    zone_occ_s: dict[str, dict[int, float]] = field(default_factory=dict)
    # Per-zone activity breakdown: {zone_id: {activity: person-seconds}}.
    # Worker-weighted — each frame adds (members-doing-activity * dt). The
    # per-zone analogue of activity_s; "what is being done in this zone".
    zone_act_s: dict[str, dict[str, float]] = field(default_factory=dict)


class MetricsAggregator:
    def __init__(
        self,
        bucket_s: float = BUCKET_S,
        retention_s: float = RETENTION_S,
        wall_clock_origin: Optional[datetime] = None,
    ):
        self.bucket_s = bucket_s
        self.retention_s = retention_s
        # Wall-clock timestamp corresponding to video-time t=0 for this
        # camera run. Used to map bucket start_t (seconds-from-camera-start)
        # to the absolute datetime stored in metric_samples.bucket_start.
        # None → DB flush is disabled (the aggregator still works in-memory).
        self.wall_clock_origin = wall_clock_origin
        self._buckets: deque[_Bucket] = deque()
        self._latest_t = 0.0
        self._session_start_t: Optional[float] = None
        # High-water-mark for DB flush: every bucket whose start_t is at or
        # below this value has been persisted (or skipped on conflict).
        self._last_flushed_start_t: Optional[float] = None

    @property
    def latest_t(self) -> float:
        return self._latest_t

    def add(self, state: dict, dt: float) -> None:
        """Fold one rendered frame's state into the current time bucket."""
        t = float(state.get("t") or 0.0)
        if self._session_start_t is None:
            self._session_start_t = t
        self._latest_t = max(self._latest_t, t)
        dt = max(0.0, min(float(dt), MAX_DT))

        # Skip ghost tracks: they are workers the pipeline has lost sight of,
        # so their rollup is forced to `unclear` (≠ their last-known activity).
        # Counting them would both dilute the analysis and make activity-time
        # and rollup-time disagree. Real + phantom + motion-only tracks all
        # carry internally-consistent activity/rollup and are counted.
        tracks = [tr for tr in (state.get("tracks") or []) if not tr.get("ghost")]
        # Orphan welding arcs: arcs that aren't attributed to any track and
        # haven't yet been promoted to a phantom worker. They're rendered on
        # the MJPEG as arc circles and shown as `welding (anon)` chips, but
        # they wouldn't otherwise enter the metrics — count each one as one
        # anonymous welder doing welding/working, per operator policy.
        orphan_welders = int(state.get("orphan_welding_count") or 0)
        n = len(tracks) + orphan_welders
        b = self._bucket_for(t)
        b.frames += 1
        b.dt_sum += dt
        b.headcount_dt += n * dt
        b.peak_headcount = max(b.peak_headcount, n)
        for tr in tracks:
            act = str(tr.get("activity") or "unknown")
            ru = str(tr.get("rollup") or "unclear")
            b.activity_s[act] = b.activity_s.get(act, 0.0) + dt
            b.rollup_s[ru] = b.rollup_s.get(ru, 0.0) + dt
        if orphan_welders > 0:
            add_s = orphan_welders * dt
            b.activity_s["welding"] = b.activity_s.get("welding", 0.0) + add_s
            b.rollup_s["working"] = b.rollup_s.get("working", 0.0) + add_s
        # Per-zone occupancy: each monitored zone reports its current count in
        # state["zones"]; add dt to that zone's histogram at its count. Every
        # zone present this frame gets dt — including count 0 (empty) — so the
        # histogram integrates to the full observed time per zone.
        for z in (state.get("zones") or []):
            zid = z.get("zone_id")
            if zid is None:
                continue
            count = int(z.get("count") or 0)
            hist = b.zone_occ_s.setdefault(str(zid), {})
            hist[count] = hist.get(count, 0.0) + dt
            # Per-zone activity: add (headcount-doing-activity * dt) so the
            # breakdown is worker-weighted (3 welders + 1 idle for 10 s →
            # 30 welding-seconds / 10 idle-seconds → 75% / 25%).
            acts = z.get("activities") or {}
            if acts:
                ahist = b.zone_act_s.setdefault(str(zid), {})
                for act, cnt in acts.items():
                    ahist[act] = ahist.get(act, 0.0) + int(cnt) * dt
        self._gc()

    def summary(self, window_s: Optional[float] = None) -> dict:
        """Aggregate the buckets inside ``window_s`` (None / <=0 = whole session)."""
        if window_s is None or window_s <= 0:
            buckets = list(self._buckets)
            effective_window = self._session_span()
        else:
            cutoff = self._latest_t - window_s
            buckets = [b for b in self._buckets if b.start_t + self.bucket_s > cutoff]
            effective_window = window_s

        act: dict[str, float] = {}
        ru: dict[str, float] = {}
        headcount_dt = 0.0
        dt_sum = 0.0
        frames = 0
        peak = 0
        zone_occ: dict[str, dict[int, float]] = {}
        zone_act: dict[str, dict[str, float]] = {}
        for b in buckets:
            for k, v in b.activity_s.items():
                act[k] = act.get(k, 0.0) + v
            for k, v in b.rollup_s.items():
                ru[k] = ru.get(k, 0.0) + v
            headcount_dt += b.headcount_dt
            dt_sum += b.dt_sum
            frames += b.frames
            peak = max(peak, b.peak_headcount)
            for zid, hist in b.zone_occ_s.items():
                agg = zone_occ.setdefault(zid, {})
                for cnt, s in hist.items():
                    agg[cnt] = agg.get(cnt, 0.0) + s
            for zid, ahist in b.zone_act_s.items():
                agg2 = zone_act.setdefault(zid, {})
                for a, s in ahist.items():
                    agg2[a] = agg2.get(a, 0.0) + s

        return {
            "window_s": round(effective_window, 1),
            "worker_seconds": round(sum(ru.values()), 1),
            "activity_seconds": {k: round(v, 1) for k, v in act.items()},
            "rollup_seconds": {k: round(v, 1) for k, v in ru.items()},
            "activity_pct": _pct(act),
            "rollup_pct": _pct(ru),
            "avg_headcount": round(headcount_dt / dt_sum, 2) if dt_sum > 0 else 0.0,
            "peak_headcount": peak,
            "frames": frames,
            "zone_occupancy": derive_zone_occupancy(zone_occ),
            "zone_activity": derive_zone_activity(zone_act),
        }

    # ------------------------------------------------------------------
    # Flush API (Phase 3 — DB-backed historical metrics)
    # ------------------------------------------------------------------

    def collect_flushable(self, now_t: float) -> list[tuple[float, dict]]:
        """Snapshot every closed bucket whose start_t hasn't been flushed yet.

        A bucket is "closed" once ``now_t`` has advanced past ``start_t +
        bucket_s``. Returns ``[(bucket_start_t, row)]`` where ``row`` is a
        dict matching the ``metric_samples`` columns (minus id / created_at).
        Does not mutate state — caller calls ``mark_flushed_through(...)``
        once the DB transaction commits so a failed insert doesn't lose data.
        """
        if self.wall_clock_origin is None:
            return []
        out: list[tuple[float, dict]] = []
        for b in self._buckets:
            if b.start_t + self.bucket_s > now_t:
                # Bucket still open; wait for it to close.
                continue
            if (
                self._last_flushed_start_t is not None
                and b.start_t <= self._last_flushed_start_t
            ):
                continue
            bucket_start_dt = self.wall_clock_origin + timedelta(seconds=b.start_t)
            row = {
                "bucket_start": bucket_start_dt,
                "duration_s": self.bucket_s,
                "worker_seconds": round(sum(b.rollup_s.values()), 3),
                "frames": b.frames,
                "peak_headcount": b.peak_headcount,
                "avg_headcount": round(b.headcount_dt / b.dt_sum, 3) if b.dt_sum > 0 else 0.0,
                "activity_seconds": {k: round(v, 3) for k, v in b.activity_s.items()},
                "rollup_seconds": {k: round(v, 3) for k, v in b.rollup_s.items()},
                # {zone_id: {count_str: seconds}} — JSON-key-safe (str counts).
                "zone_occupancy_seconds": {
                    zid: {str(cnt): round(s, 3) for cnt, s in hist.items()}
                    for zid, hist in b.zone_occ_s.items()
                },
                # {zone_id: {activity: person-seconds}}.
                "zone_activity_seconds": {
                    zid: {a: round(s, 3) for a, s in ahist.items()}
                    for zid, ahist in b.zone_act_s.items()
                },
            }
            out.append((b.start_t, row))
        return out

    def mark_flushed_through(self, last_start_t: float) -> None:
        """Advance the high-water-mark. Subsequent ``collect_flushable`` calls
        will skip buckets at or below ``last_start_t``."""
        if (
            self._last_flushed_start_t is None
            or last_start_t > self._last_flushed_start_t
        ):
            self._last_flushed_start_t = last_start_t

    # ------------------------------------------------------------------

    def _bucket_for(self, t: float) -> _Bucket:
        start = (int(t // self.bucket_s)) * self.bucket_s
        if self._buckets and self._buckets[-1].start_t == start:
            return self._buckets[-1]
        b = _Bucket(start_t=start)
        self._buckets.append(b)
        return b

    def _gc(self) -> None:
        cutoff = self._latest_t - self.retention_s
        while self._buckets and self._buckets[0].start_t < cutoff:
            self._buckets.popleft()

    def _session_span(self) -> float:
        if not self._buckets or self._session_start_t is None:
            return 0.0
        return max(0.0, self._latest_t - self._session_start_t)


def _pct(d: dict[str, float]) -> dict[str, float]:
    total = sum(d.values())
    if total <= 0:
        return {}
    return {k: round(100.0 * v / total, 1) for k, v in d.items()}


def derive_zone_occupancy(folded: dict[str, dict]) -> dict[str, dict]:
    """Turn a folded {zone_id: {count: seconds}} histogram into the API shape.

    Accepts int OR str count keys (live aggregator uses ints; DB rows store
    str keys). Emits, per zone:
        seconds_at : {count_str: seconds}   — the raw histogram (frontend
                     derives understaffed-time for any N from this)
        total_s    : total observed seconds for the zone
        avg        : time-weighted mean occupancy
        peak       : highest count ever observed
    """
    out: dict[str, dict] = {}
    for zid, hist in folded.items():
        norm: dict[int, float] = {}
        for cnt, s in hist.items():
            norm[int(cnt)] = norm.get(int(cnt), 0.0) + float(s)
        total = sum(norm.values())
        weighted = sum(k * s for k, s in norm.items())
        out[zid] = {
            "seconds_at": {str(k): round(v, 1) for k, v in sorted(norm.items())},
            "total_s": round(total, 1),
            "avg": round(weighted / total, 2) if total > 0 else 0.0,
            "peak": max(norm.keys()) if norm else 0,
        }
    return out


def derive_zone_activity(folded: dict[str, dict]) -> dict[str, dict]:
    """Turn a folded {zone_id: {activity: person-seconds}} map into the API shape.

    Emits, per zone:
        seconds : {activity: person-seconds}   — raw worker-weighted totals
        total_s : total person-seconds across all activities
        pct     : {activity: pct of total}     — the "30% welding, 10% idle…"
                  breakdown (sums to ~100%)
    """
    out: dict[str, dict] = {}
    for zid, hist in folded.items():
        secs = {a: float(s) for a, s in hist.items()}
        total = sum(secs.values())
        out[zid] = {
            "seconds": {a: round(s, 1) for a, s in secs.items()},
            "total_s": round(total, 1),
            "pct": _pct(secs),
        }
    return out
