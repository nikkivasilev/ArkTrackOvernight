"""Offline recording engine — process one file end-to-end into metric_samples.

This is the offline analogue of ``camera_worker.run_camera_worker``: it drives
the same vendored ``CameraPipeline`` over every sampled frame of a recorded
file, but with three differences that make it a batch crunch rather than a
live feed:

  1. **Headless** — ``pipeline.headless = True`` skips the JPEG render/encode
     and overlay drawing (the bulk of the per-frame CPU cost, see the overnight
     benchmark). No live MJPEG, no WS state broadcast, no pre-buffer.
  2. **Real timestamps** — the ``MetricsAggregator`` is anchored to the
     recording's actual wall-clock start (``start_dt``, parsed from the NVR
     filename) instead of ``datetime.now()``. So a bucket at video-time t lands
     in ``metric_samples`` at ``start_dt + t`` — the real time it was filmed.
     This is what lets a day's worth of files reconstruct an accurate timeline.
  3. **Idempotent flush** — buckets are persisted with the same
     ``ON CONFLICT (camera_id, bucket_start) DO NOTHING`` the live path uses, so
     re-running a file (or overlapping recordings) can't double-count.

The detection/tracking/VLM/welding/group stack is byte-for-byte the live one,
so the metrics are directly comparable to live runs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import SessionLocal
from app.models import MetricSample
from app.pipeline.runtime import CameraPipeline
from app.workers import frame_sampler, zone_filter
from app.workers.metrics import BUCKET_S, MetricsAggregator

logger = logging.getLogger(__name__)

# Persist closed buckets to the DB every this-many seconds of FOOTAGE (not wall
# time — offline runs much faster than real-time). Kept well below the
# aggregator's 8 h in-memory retention so a long (12 h) single file never GCs an
# unflushed bucket before it's written.
FLUSH_EVERY_FOOTAGE_S = 300.0


@dataclass
class RunStats:
    camera_id: UUID
    path: str
    start_dt: datetime
    frames: int
    footage_s: float
    buckets_flushed: int

    @property
    def end_dt(self) -> datetime:
        return self.start_dt + timedelta(seconds=self.footage_s)


async def _flush(camera_id: UUID, aggregator: MetricsAggregator, now_t: float) -> int:
    """Persist closed-and-unflushed metric buckets. Returns rows written.

    Mirrors ``camera_worker._flush_metrics``: the high-water-mark only advances
    after the commit succeeds, so a transient DB error retries the same buckets
    on the next flush rather than dropping them.
    """
    rows = aggregator.collect_flushable(now_t)
    if not rows:
        return 0
    payload = [{"camera_id": camera_id, **row} for _, row in rows]
    async with SessionLocal() as session:
        stmt = (
            pg_insert(MetricSample)
            .values(payload)
            .on_conflict_do_nothing(index_elements=["camera_id", "bucket_start"])
        )
        await session.execute(stmt)
        await session.commit()
    aggregator.mark_flushed_through(rows[-1][0])
    return len(rows)


async def process_recording(
    camera_id: UUID,
    path: str,
    start_dt: datetime,
    target_fps: float | None = None,
    excluded_zone_polys: list[list[list[float]]] | None = None,
    metric_zones: list[dict] | None = None,
) -> RunStats:
    """Crunch one recorded file into ``metric_samples`` at real wall-clock time.

    Args:
        camera_id: the ``Camera`` this footage belongs to (rows are keyed by it).
        path: local path to the recording.
        start_dt: timezone-aware UTC datetime the recording STARTED. Video-time
            t=0 maps here; bucket t lands at ``start_dt + t``.
        target_fps: analysis sampling rate; ``None`` → probe the file's native
            fps (factory NVR exports are ~8 fps, already low).
        excluded_zone_polys: normalized 0..1 polygons to drop from metrics.
        metric_zones: monitored zones [{"id","name","polygon"}] for per-zone
            occupancy / activity breakdowns.

    Returns a ``RunStats`` summarizing what was processed.
    """
    if start_dt.tzinfo is None:
        raise ValueError("start_dt must be timezone-aware (UTC)")

    if target_fps is None or target_fps <= 0:
        try:
            info = frame_sampler.probe(path)
            target_fps = float(info.fps) if info.fps and info.fps > 0 else 8.0
        except Exception as exc:
            logger.warning("probe failed for %s (%s); defaulting to 8 fps", path, exc)
            target_fps = 8.0

    pipeline = CameraPipeline(camera_id=camera_id, target_fps=target_fps)
    pipeline.headless = True
    metrics = MetricsAggregator(wall_clock_origin=start_dt)
    pipeline.metrics = metrics
    if excluded_zone_polys:
        pipeline.set_excluded_zones(excluded_zone_polys)
    if metric_zones:
        pipeline.set_metric_zones(metric_zones)

    frames = 0
    buckets_flushed = 0
    prev_t: float | None = None
    last_flush_footage = 0.0

    try:
        async for frame_idx, t_seconds, frame in frame_sampler.iter_sampled(
            path, target_fps=target_fps
        ):
            try:
                frame_out = await pipeline.process_frame(frame, frame_idx, t_seconds)
            except Exception as exc:
                logger.warning("process_frame failed at idx %d (%s)", frame_idx, exc)
                frame_out = None
            if frame_out is None:
                continue

            # Re-bind normalized zone polygons → pixel polys once source_dim is
            # known (first successful frame), exactly as the live worker does.
            if (
                pipeline.source_dim is not None
                and not pipeline.excluded_polys_px
                and getattr(pipeline, "_excluded_polys_norm", None)
            ):
                pipeline.set_excluded_zones(pipeline._excluded_polys_norm)
            if (
                pipeline.source_dim is not None
                and not pipeline._metric_zones
                and getattr(pipeline, "_metric_zones_norm", None)
            ):
                pipeline.set_metric_zones(pipeline._metric_zones_norm)

            zone_filter.apply(frame_out.state, pipeline.excluded_polys_px)

            dt = (t_seconds - prev_t) if prev_t is not None else 0.0
            prev_t = t_seconds
            metrics.add(frame_out.state, dt)
            frames += 1

            if t_seconds - last_flush_footage >= FLUSH_EVERY_FOOTAGE_S:
                last_flush_footage = t_seconds
                buckets_flushed += await _flush(camera_id, metrics, now_t=t_seconds)

        # Final flush — advance now_t past the last bucket boundary so the
        # trailing partial bucket is released.
        buckets_flushed += await _flush(
            camera_id, metrics, now_t=metrics.latest_t + BUCKET_S
        )
    finally:
        pipeline.close()

    footage_s = frames / target_fps if target_fps > 0 else 0.0
    logger.info(
        "processed %s: %d frames, %.0fs footage, %d buckets -> %s",
        path, frames, footage_s, buckets_flushed, camera_id,
    )
    return RunStats(
        camera_id=camera_id,
        path=path,
        start_dt=start_dt,
        frames=frames,
        footage_s=footage_s,
        buckets_flushed=buckets_flushed,
    )
