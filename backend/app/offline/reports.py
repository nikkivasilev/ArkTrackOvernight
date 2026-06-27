"""Generate factory day-summary PDFs — the bridge from processed metrics to
the deliverable artifact. Shared by the CLI and the watcher.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import Factory
from app.offline.day_summary import (
    build_day_summary,
    build_month_summary,
    build_range_summary,
    build_week_summary,
)
from app.offline.report_pdf import render_period_pdf

logger = logging.getLogger(__name__)

_BUILDERS = {
    "day": build_day_summary,
    "week": build_week_summary,
    "month": build_month_summary,
}


async def resolve_factory(name_or_id: str | None):
    """Return a Factory by id, by name, or the sole factory if unspecified."""
    async with SessionLocal() as s:
        if name_or_id:
            facs = (await s.execute(select(Factory))).scalars().all()
            for f in facs:
                if str(f.id) == name_or_id or f.name == name_or_id:
                    return f.id, f.name
            raise ValueError(f"no factory matching {name_or_id!r}")
        facs = (await s.execute(select(Factory))).scalars().all()
        if not facs:
            raise RuntimeError("no factories exist")
        if len(facs) > 1:
            raise ValueError(
                f"{len(facs)} factories exist — specify one: "
                + ", ".join(f.name for f in facs)
            )
        return facs[0].id, facs[0].name


async def generate_report(
    factory: str | None, anchor: date, tz: ZoneInfo | None = None,
    out_dir: Path | None = None, period: str = "day",
) -> Path:
    """Render a factory report PDF for the period containing ``anchor``.

    ``period`` is "day" | "week" | "month"; ``anchor`` is any date inside it
    (the day itself / any day of the ISO week / any day of the month). ``period``
    is the trailing arg so the existing positional ``(factory, day, tz[, out])``
    call sites (watcher, CLI) keep working unchanged.
    """
    if period not in _BUILDERS:
        raise ValueError(f"unknown period {period!r} (day|week|month)")
    tz = tz or ZoneInfo(settings.factory_tz)
    out_dir = out_dir or settings.offline_report_dir
    fac_id, fac_name = await resolve_factory(factory)
    async with SessionLocal() as s:
        summary = await _BUILDERS[period](s, fac_id, anchor, tz=tz)
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in fac_name).strip()
    if period == "week":
        stem = f"week_{summary.start:%G-W%V}"
    elif period == "month":
        stem = f"month_{summary.start:%Y-%m}"
    else:
        stem = f"day_{summary.start:%Y-%m-%d}"
    out_path = Path(out_dir) / f"{stem}_{safe}.pdf"
    path = render_period_pdf(summary, out_path)
    logger.info(
        "report %s %s %s -> %s (%d cameras, %.1f worker-hours)",
        fac_name, period, summary.start, path, len(summary.cameras),
        summary.factory_summary["worker_seconds"] / 3600.0,
    )
    return path


async def generate_range_report(
    factory: str | None, start: date, end: date,
    tz: ZoneInfo | None = None, out_dir: Path | None = None,
) -> Path:
    """Render a factory report PDF for an arbitrary inclusive date range."""
    tz = tz or ZoneInfo(settings.factory_tz)
    out_dir = out_dir or settings.offline_report_dir
    fac_id, fac_name = await resolve_factory(factory)
    async with SessionLocal() as s:
        summary = await build_range_summary(s, fac_id, start, end, tz=tz)
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in fac_name).strip()
    out_path = Path(out_dir) / f"range_{start:%Y-%m-%d}_{end:%Y-%m-%d}_{safe}.pdf"
    path = render_period_pdf(summary, out_path)
    logger.info(
        "report %s range %s..%s -> %s (%d cameras, %.1f worker-hours)",
        fac_name, start, end, path, len(summary.cameras),
        summary.factory_summary["worker_seconds"] / 3600.0,
    )
    return path
