"""Workforce-metrics read-path for a camera.

Routes:
  GET  /api/cameras/{camera_id}/metrics?window_s= | ?since=&until=
      Workforce-metrics summary read from the persisted ``metric_samples``
      table. ``window_s`` serves a trailing window (now-window_s .. now);
      ``since`` + ``until`` serve an explicit historical range — used for the
      24 h / shift / daily analysis views and reports.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Camera, MetricSample
from app.workers.metrics import derive_zone_occupancy, derive_zone_activity

router = APIRouter()


def _empty_summary(window_s: float = 0.0) -> dict:
    return {
        "window_s": round(window_s, 1),
        "worker_seconds": 0.0,
        "activity_seconds": {}, "rollup_seconds": {},
        "activity_pct": {}, "rollup_pct": {},
        "avg_headcount": 0.0, "peak_headcount": 0, "frames": 0,
        "zone_occupancy": {},
        "zone_activity": {},
    }


def _pct(d: dict[str, float]) -> dict[str, float]:
    total = sum(d.values())
    if total <= 0:
        return {}
    return {k: round(100.0 * v / total, 1) for k, v in d.items()}


async def _summary_from_db(
    db: AsyncSession, camera_id: UUID, since: datetime, until: datetime,
) -> dict:
    """Aggregate persisted metric buckets between two wall-clock datetimes.

    Returns an empty summary if no rows exist in range.
    """
    q = await db.execute(
        select(MetricSample)
        .where(
            MetricSample.camera_id == camera_id,
            MetricSample.bucket_start >= since,
            MetricSample.bucket_start < until,
        )
        .order_by(MetricSample.bucket_start.asc())
    )
    rows = q.scalars().all()
    if not rows:
        return _empty_summary((until - since).total_seconds())

    act: dict[str, float] = {}
    ru: dict[str, float] = {}
    worker_s = 0.0
    headcount_dur = 0.0  # sum(avg_headcount × duration_s) for weighted avg
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
        # Fold per-zone occupancy histograms ({zone_id: {count_str: seconds}}).
        for zid, hist in (r.zone_occupancy_seconds or {}).items():
            agg = zone_occ.setdefault(zid, {})
            for cnt, s in hist.items():
                agg[cnt] = agg.get(cnt, 0.0) + float(s)
        # Fold per-zone activity breakdowns ({zone_id: {activity: seconds}}).
        for zid, ahist in (r.zone_activity_seconds or {}).items():
            agg2 = zone_act.setdefault(zid, {})
            for a, s in ahist.items():
                agg2[a] = agg2.get(a, 0.0) + float(s)

    return {
        "window_s": round((until - since).total_seconds(), 1),
        "worker_seconds": round(worker_s, 1),
        "activity_seconds": {k: round(v, 1) for k, v in act.items()},
        "rollup_seconds": {k: round(v, 1) for k, v in ru.items()},
        "activity_pct": _pct(act),
        "rollup_pct": _pct(ru),
        "avg_headcount": round(headcount_dur / dur_sum, 2) if dur_sum > 0 else 0.0,
        "peak_headcount": peak,
        "frames": frames,
        "zone_occupancy": derive_zone_occupancy(zone_occ),
        "zone_activity": derive_zone_activity(zone_act),
    }


@router.get("/cameras/{camera_id}/metrics")
async def get_metrics(
    camera_id: UUID,
    window_s: float | None = Query(
        None, ge=0.0, description="trailing window in seconds (now-window_s .. now)"
    ),
    since: datetime | None = Query(
        None, description="ISO-8601 start of historical window (UTC)"
    ),
    until: datetime | None = Query(
        None, description="ISO-8601 end of historical window (UTC)"
    ),
    db: AsyncSession = Depends(get_db),
) -> dict:
    cam = await db.get(Camera, camera_id)
    if cam is None:
        raise HTTPException(status_code=404, detail="camera not found")

    # Explicit historical range.
    if since is not None and until is not None:
        if until <= since:
            raise HTTPException(status_code=400, detail="until must be > since")
        summary = await _summary_from_db(db, camera_id, since, until)
        return {"camera_id": str(camera_id), "source": "db", "metrics": summary}
    if (since is None) != (until is None):
        raise HTTPException(status_code=400, detail="pass both since and until, or neither")

    # Trailing window served from the persisted samples.
    if window_s and window_s > 0:
        now = datetime.now(timezone.utc)
        summary = await _summary_from_db(db, camera_id, now - timedelta(seconds=window_s), now)
        return {"camera_id": str(camera_id), "source": "db", "metrics": summary}

    return {"camera_id": str(camera_id), "source": "empty", "metrics": _empty_summary()}
