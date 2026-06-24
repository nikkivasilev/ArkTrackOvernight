"""Most-automated trigger: watch the drop directory and crunch + report as
footage lands.

Uses ``watchfiles.awatch`` to block on filesystem events, debounces until the
directory has been quiet for a beat (the factory ships large files; we wait
for the copy to finish), then runs the folder ingest. Every distinct
factory-local date that got new footage has its day-summary PDF (re)generated,
so the report on disk always reflects the latest processed metrics.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config import settings
from app.offline.batch import ingest_folder
from app.offline.reports import generate_report

logger = logging.getLogger(__name__)

# Wait for the drop dir to be quiet this long before ingesting, so we don't
# start crunching a file that's still being copied over the network.
QUIET_SECONDS = 30.0


async def _ingest_and_report(drop_dir: Path, tz: ZoneInfo) -> None:
    rows = await ingest_folder(drop_dir, tz)
    if not rows:
        return
    # Distinct factory-local dates touched by this batch → regenerate each.
    days: set[date] = set()
    for r in rows:
        if r.status == "done" and r.recorded_start is not None:
            days.add(r.recorded_start.astimezone(tz).date())
    for day in sorted(days):
        try:
            path = await generate_report(None, day, tz)
            logger.info("regenerated report for %s -> %s", day, path)
        except Exception:
            logger.exception("report generation failed for %s", day)


async def watch(drop_dir: Path | None = None, tz: ZoneInfo | None = None) -> None:
    """Watch ``drop_dir`` forever, ingesting + reporting on each quiet batch."""
    from watchfiles import awatch  # local import: only the watcher needs it

    drop_dir = Path(drop_dir or settings.offline_drop_dir)
    tz = tz or ZoneInfo(settings.factory_tz)
    drop_dir.mkdir(parents=True, exist_ok=True)
    logger.info("watching %s (tz=%s)", drop_dir, tz)

    # Catch up on anything already sitting in the folder at startup.
    await _ingest_and_report(drop_dir, tz)

    async for _changes in awatch(str(drop_dir), debounce=int(QUIET_SECONDS * 1000)):
        # awatch already coalesces bursts within `debounce`; add a short settle
        # so a still-copying multi-GB file is fully flushed before we open it.
        await asyncio.sleep(QUIET_SECONDS)
        try:
            await _ingest_and_report(drop_dir, tz)
        except Exception:
            logger.exception("ingest/report cycle failed")
