"""Folder batch orchestration — crunch a drop directory of recordings.

Ties the ingest layer (filename → camera + wall-clock span) to the recording
engine (file → metric_samples at real time), recording each file in the
``processed_recordings`` ledger so re-runs skip finished work.

Processing is **sequential**: there is one office GPU and a single shared
detector/VLM, and the overnight benchmark showed throughput is CPU/GIL-bound,
so fanning out files concurrently in one process buys little and complicates
failure handling. One file at a time, ledger-checkpointed, is the robust
overnight shape. (Multi-PROCESS is the documented next lever if wall-clock
becomes a problem.)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.models import ProcessedRecording, Zone
from app.offline.ingest import (
    ParsedRecording,
    already_processed,
    default_site_id,
    list_recordings,
    resolve_camera,
)
from app.offline.runner import process_recording

logger = logging.getLogger(__name__)


async def _load_zones(session: AsyncSession, camera_id) -> tuple[list, list]:
    """Return (excluded_polys_norm, metric_zones) for a camera, mirroring the
    live worker's zone loading so offline metrics honour the same exclusions
    and monitored zones."""
    zones = (
        await session.execute(select(Zone).where(Zone.camera_id == camera_id))
    ).scalars().all()
    excluded = [list(z.polygon) for z in zones if z.excluded]
    metric = [
        {"id": str(z.id), "name": z.name, "polygon": list(z.polygon)}
        for z in zones if not z.excluded
    ]
    return excluded, metric


async def process_one(parsed: ParsedRecording, site_id) -> ProcessedRecording:
    """Resolve the camera, crunch one file, and write its ledger row.

    Idempotent at the caller level (skip via ``already_processed``); here we
    also upsert the ledger row so a retried failure overwrites the prior
    ``failed`` entry rather than duplicating it.
    """
    async with SessionLocal() as session:
        cam = await resolve_camera(session, parsed.camera_label, site_id, parsed.path)
        camera_id = cam.id
        excluded, metric_zones = await _load_zones(session, camera_id)

    # Upsert a ledger row in "processing" state up front so a crash mid-run
    # leaves a visible breadcrumb rather than nothing.
    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(ProcessedRecording).where(ProcessedRecording.path == parsed.path)
            )
        ).scalars().first()
        if row is None:
            row = ProcessedRecording(path=parsed.path)
            session.add(row)
        row.camera_id = camera_id
        row.filename = parsed.filename
        row.recorded_start = parsed.start
        row.recorded_end = parsed.end
        row.status = "processing"
        row.error = None
        await session.commit()
        await session.refresh(row)
        row_id = row.id

    try:
        stats = await process_recording(
            camera_id, parsed.path, parsed.start,
            excluded_zone_polys=excluded or None,
            metric_zones=metric_zones or None,
        )
        status, error = "done", None
        frames, footage_s = stats.frames, stats.footage_s
        # Backfill end from actual footage length if the filename lacked it.
        rec_end = parsed.end or stats.end_dt
    except Exception as exc:
        logger.exception("offline processing failed for %s", parsed.path)
        status, error = "failed", f"{exc.__class__.__name__}: {exc}"
        frames, footage_s, rec_end = 0, 0.0, parsed.end

    async with SessionLocal() as session:
        row = await session.get(ProcessedRecording, row_id)
        row.status = status
        row.error = error
        row.frames = frames
        row.footage_s = footage_s
        row.recorded_end = rec_end
        row.processed_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(row)
        return row


async def ingest_folder(
    drop_dir: Path | None = None,
    tz: ZoneInfo | None = None,
    reprocess: bool = False,
) -> list[ProcessedRecording]:
    """Process every new recording in ``drop_dir``. Returns the ledger rows
    touched this run (skipped-already rows are excluded).

    ``reprocess=True`` ignores the ledger and re-crunches everything (the
    ON CONFLICT DO NOTHING on metric_samples keeps that safe)."""
    drop_dir = drop_dir or settings.offline_drop_dir
    tz = tz or ZoneInfo(settings.factory_tz)
    recordings = list_recordings(drop_dir, tz)
    logger.info("offline ingest: %d recordings under %s", len(recordings), drop_dir)

    async with SessionLocal() as session:
        site_id = await default_site_id(session)

    results: list[ProcessedRecording] = []
    for rec in recordings:
        if not reprocess:
            async with SessionLocal() as session:
                if await already_processed(session, rec.path):
                    logger.info("skip (already processed): %s", rec.filename)
                    continue
        logger.info("processing %s [%s]", rec.filename, rec.camera_label)
        results.append(await process_one(rec, site_id))
    logger.info("offline ingest complete: %d processed", len(results))
    return results
