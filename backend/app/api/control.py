"""Live runtime controls + metrics for a camera's pipeline.

Routes:
  POST /api/cameras/{camera_id}/modules
      Body: {"yolo_enabled"?, "overlay_enabled"?}
      Toggles the in-memory CameraPipeline module flags AND persists the
      new values to ``Camera.settings.modules``. Welding/groups are no
      longer operator-toggled (Phase 2 runs them unconditionally).

  GET  /api/cameras/{camera_id}/metrics?window_s= | ?since=&until=
      Workforce-metrics summary. ``window_s`` reads the live aggregator
      (falls back to a DB window if the camera isn't running). ``since`` +
      ``until`` always read the ``metric_samples`` table — used for the
      24 h / shift / daily historical reports that must survive restart.

  POST /api/cameras/{camera_id}/detectors/{name}
      Body: partial param dict. Live-tunes a detector (welding, vlm,
      id_recovery, …) via the vendored _TuningMixin and persists the
      values to ``Camera.settings.detectors[name]``.

Phase 4 adds /presets and /presets/apply.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Camera, MetricSample
from app.workers import registry
from app.workers.metrics import derive_zone_occupancy, derive_zone_activity

router = APIRouter()

_MODULE_KEYS = ("yolo_enabled", "overlay_enabled")


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

    Same response shape as ``MetricsAggregator.summary`` so the frontend
    consumes one type. Returns an empty summary if no rows exist in range.
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


@router.post("/cameras/{camera_id}/modules")
async def set_modules(
    camera_id: UUID,
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    cam = await db.get(Camera, camera_id)
    if cam is None:
        raise HTTPException(status_code=404, detail="camera not found")

    updates = {k: bool(payload[k]) for k in _MODULE_KEYS if k in payload}
    if not updates:
        raise HTTPException(
            status_code=400,
            detail=f"send at least one of {_MODULE_KEYS}",
        )

    # Persist to Camera.settings.modules so a worker restart sees them.
    settings = dict(cam.settings or {})
    modules = dict(settings.get("modules") or {})
    modules.update(updates)
    settings["modules"] = modules
    cam.settings = settings
    await db.commit()

    # Apply to the live pipeline if running.
    pipeline = registry.get_pipeline(camera_id)
    if pipeline is not None:
        await pipeline.set_modules(**updates)
        state = pipeline.get_module_state()
    else:
        state = {"running": False, **modules}

    return {"camera_id": str(camera_id), "modules": state, "persisted": modules}


@router.get("/cameras/{camera_id}/metrics")
async def get_metrics(
    camera_id: UUID,
    window_s: float | None = Query(
        None, ge=0.0, description="rolling window in seconds; omit / 0 = whole session"
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

    pipeline = registry.get_pipeline(camera_id)
    metrics = getattr(pipeline, "metrics", None) if pipeline is not None else None

    # Explicit historical range → always DB.
    if since is not None and until is not None:
        if until <= since:
            raise HTTPException(status_code=400, detail="until must be > since")
        summary = await _summary_from_db(db, camera_id, since, until)
        return {
            "camera_id": str(camera_id),
            "running": metrics is not None,
            "source": "db",
            "metrics": summary,
        }
    if (since is None) != (until is None):
        raise HTTPException(status_code=400, detail="pass both since and until, or neither")

    # Live aggregator path (the common one).
    if metrics is not None:
        return {
            "camera_id": str(camera_id),
            "running": True,
            "source": "live",
            "metrics": metrics.summary(window_s),
        }

    # Camera not running — fall back to a DB-served window so the panel
    # still has something to show for a stopped camera.
    if window_s and window_s > 0:
        now = datetime.now(timezone.utc)
        summary = await _summary_from_db(db, camera_id, now - timedelta(seconds=window_s), now)
        return {
            "camera_id": str(camera_id),
            "running": False,
            "source": "db",
            "metrics": summary,
        }
    return {
        "camera_id": str(camera_id),
        "running": False,
        "source": "empty",
        "metrics": _empty_summary(),
    }


@router.post("/cameras/{camera_id}/detectors/{name}")
async def set_detector_params(
    camera_id: UUID,
    name: str,
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    cam = await db.get(Camera, camera_id)
    if cam is None:
        raise HTTPException(status_code=404, detail="camera not found")

    pipeline = registry.get_pipeline(camera_id)
    if pipeline is None:
        raise HTTPException(
            status_code=409, detail="camera not running — start it before tuning detectors"
        )

    try:
        result = await pipeline.set_detector_params(name, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Persist the resolved values to Camera.settings.detectors[name].
    settings = dict(cam.settings or {})
    detectors = dict(settings.get("detectors") or {})
    detectors[name] = result.get("values", {})
    settings["detectors"] = detectors
    cam.settings = settings
    await db.commit()

    return {"camera_id": str(camera_id), "detector": name, **result}
