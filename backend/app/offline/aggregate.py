"""Pure folding of ``metric_samples`` rows into report summaries.

A single ``fold_samples`` so the day-summary builder doesn't add a third copy
of the bucket-folding that ``control._summary_from_db`` and
``MetricsAggregator.summary`` already do (those stay untouched). The output
shape matches the live ``/metrics`` summary so any downstream consumer reads
one type.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

from app.workers.metrics import derive_zone_activity, derive_zone_occupancy

ROLLUP_ORDER = ["working", "moving", "idle", "unclear"]


def _pct(d: dict[str, float]) -> dict[str, float]:
    total = sum(d.values())
    if total <= 0:
        return {}
    return {k: round(100.0 * v / total, 1) for k, v in d.items()}


def fold_samples(rows: Iterable, window_s: float | None = None) -> dict:
    """Fold an iterable of ``MetricSample`` rows into one summary dict.

    Sums activity/rollup seconds, time-weights average headcount, takes the max
    peak, and merges per-zone occupancy + activity. ``window_s`` is just echoed
    into the result (the caller knows the wall span); pass None to omit.
    """
    act: dict[str, float] = {}
    ru: dict[str, float] = {}
    worker_s = 0.0
    headcount_dur = 0.0
    dur_sum = 0.0
    frames = 0
    peak = 0
    zone_occ: dict[str, dict] = {}
    zone_act: dict[str, dict] = {}

    for r in rows:
        worker_s += float(r.worker_seconds or 0.0)
        for k, v in (r.activity_seconds or {}).items():
            act[k] = act.get(k, 0.0) + float(v)
        for k, v in (r.rollup_seconds or {}).items():
            ru[k] = ru.get(k, 0.0) + float(v)
        headcount_dur += float(r.avg_headcount or 0.0) * float(r.duration_s or 0.0)
        dur_sum += float(r.duration_s or 0.0)
        frames += int(r.frames or 0)
        peak = max(peak, int(r.peak_headcount or 0))
        for zid, hist in (r.zone_occupancy_seconds or {}).items():
            agg = zone_occ.setdefault(zid, {})
            for cnt, s in hist.items():
                agg[cnt] = agg.get(cnt, 0.0) + float(s)
        for zid, ahist in (r.zone_activity_seconds or {}).items():
            agg2 = zone_act.setdefault(zid, {})
            for a, s in ahist.items():
                agg2[a] = agg2.get(a, 0.0) + float(s)

    return {
        "window_s": round(window_s, 1) if window_s else None,
        "worker_seconds": round(worker_s, 1),
        "activity_seconds": {k: round(v, 1) for k, v in act.items()},
        "rollup_seconds": {k: round(v, 1) for k, v in ru.items()},
        "activity_pct": _pct(act),
        "rollup_pct": _pct(ru),
        "avg_headcount": round(headcount_dur / dur_sum, 2) if dur_sum > 0 else 0.0,
        "peak_headcount": peak,
        "frames": frames,
        "observed_s": round(dur_sum, 1),
        "zone_occupancy": derive_zone_occupancy(zone_occ),
        "zone_activity": derive_zone_activity(zone_act),
    }


def staffing_timeline(
    rows: Iterable, day_start: datetime, day_end: datetime, bin_minutes: int = 30,
) -> list[dict]:
    """Average concurrent total headcount across all cameras, per time-of-day bin.

    Within a bin: sum(avg_headcount × duration) over every row from every
    camera, divided by the bin's wall-seconds → the average number of people
    present across the whole factory during that bin (so two cameras each
    showing 4 people read as ~8). Bins with no footage report 0.
    """
    bin_s = bin_minutes * 60.0
    n_bins = max(1, int((day_end - day_start).total_seconds() // bin_s))
    person_s = [0.0] * n_bins
    for r in rows:
        if r.bucket_start < day_start or r.bucket_start >= day_end:
            continue
        idx = int((r.bucket_start - day_start).total_seconds() // bin_s)
        if 0 <= idx < n_bins:
            person_s[idx] += float(r.avg_headcount or 0.0) * float(r.duration_s or 0.0)
    out = []
    for i in range(n_bins):
        t = day_start + timedelta(seconds=i * bin_s)
        out.append({"t": t, "avg_headcount": round(person_s[i] / bin_s, 2)})
    return out


def daily_timeline(
    rows: Iterable, start_utc: datetime, end_utc: datetime, tz: ZoneInfo,
) -> list[dict]:
    """Average concurrent total headcount per LOCAL CALENDAR DAY (week/month reports).

    The multi-day analogue of ``staffing_timeline``: each metric row is binned by
    the local calendar date of its ``bucket_start``, and each day's person-seconds
    are divided by that day's own wall-second span — so DST days (23 h / 25 h) are
    weighted correctly instead of a flat 86 400. Each item is
    ``{"t": <UTC midnight of the local day>, "date": <date>, "avg_headcount": float}``.
    Days with no footage report 0. ``end_utc`` is exclusive (a local midnight).
    """
    person_s: dict = {}
    for r in rows:
        if r.bucket_start < start_utc or r.bucket_start >= end_utc:
            continue
        d = r.bucket_start.astimezone(tz).date()
        person_s[d] = (
            person_s.get(d, 0.0)
            + float(r.avg_headcount or 0.0) * float(r.duration_s or 0.0)
        )

    out = []
    d = start_utc.astimezone(tz).date()
    end_d = end_utc.astimezone(tz).date()
    while d < end_d:
        day_start_local = datetime.combine(d, time.min, tzinfo=tz)
        day_end_local = datetime.combine(d + timedelta(days=1), time.min, tzinfo=tz)
        span = (day_end_local - day_start_local).total_seconds()
        avg = person_s.get(d, 0.0) / span if span > 0 else 0.0
        out.append({
            "t": day_start_local.astimezone(timezone.utc),
            "date": d,
            "avg_headcount": round(avg, 2),
        })
        d += timedelta(days=1)
    return out
