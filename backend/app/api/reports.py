"""Factory analytics endpoints — the in-app dashboard + downloadable reports.

Driven by the same period-summary builders the CLI/watcher use
(``app.offline.day_summary``), so the interactive JSON view and the PDF agree:

  GET /api/factories/{id}/report?period=day|week|month&date=YYYY-MM-DD
  GET /api/factories/{id}/report?start=YYYY-MM-DD&end=YYYY-MM-DD   (custom range)
      -> PeriodSummaryOut (JSON) for the dashboard.
  GET /api/factories/{id}/report.pdf?period=&date=  |  ?start=&end=
      -> the rendered PDF as a download.
  GET /api/factories/{id}/data-extent
      -> {min, max} metric timestamps so the dashboard can offer "all-time".

Period mode: ``date`` is any day inside the period (defaults to today in the
factory timezone). Range mode: ``start``/``end`` are inclusive local dates.
"""
from __future__ import annotations

from datetime import date as date_cls, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models import Camera, Factory, MetricSample, Site
from app.offline.day_summary import (
    build_day_summary,
    build_month_summary,
    build_range_summary,
    build_week_summary,
)
from app.offline.reports import generate_range_report, generate_report
from app.schemas import PeriodSummaryOut

router = APIRouter()

_BUILDERS = {
    "day": build_day_summary,
    "week": build_week_summary,
    "month": build_month_summary,
}


def _anchor(date_str: str | None, tz: ZoneInfo) -> date_cls:
    if not date_str:
        return datetime.now(tz).date()
    return _parse_date(date_str)


def _parse_date(date_str: str) -> date_cls:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=422, detail="dates must be YYYY-MM-DD")


def _range(start: str, end: str) -> tuple[date_cls, date_cls]:
    s, e = _parse_date(start), _parse_date(end)
    if e < s:
        raise HTTPException(status_code=422, detail="end must be >= start")
    return s, e


async def _require_factory(db: AsyncSession, factory_id: UUID) -> Factory:
    factory = await db.get(Factory, factory_id)
    if factory is None:
        raise HTTPException(status_code=404, detail="factory not found")
    return factory


@router.get("/factories/{factory_id}/report", response_model=PeriodSummaryOut)
async def get_report(
    factory_id: UUID,
    period: str = Query("day", pattern="^(day|week|month)$"),
    date: str | None = Query(None, description="YYYY-MM-DD; any day in the period (default: today)"),
    start: str | None = Query(None, description="custom range start, YYYY-MM-DD (inclusive)"),
    end: str | None = Query(None, description="custom range end, YYYY-MM-DD (inclusive)"),
    db: AsyncSession = Depends(get_db),
) -> PeriodSummaryOut:
    await _require_factory(db, factory_id)
    tz = ZoneInfo(settings.factory_tz)
    if start or end:
        if not (start and end):
            raise HTTPException(status_code=422, detail="pass both start and end")
        s, e = _range(start, end)
        summary = await build_range_summary(db, factory_id, s, e, tz=tz)
    else:
        summary = await _BUILDERS[period](db, factory_id, _anchor(date, tz), tz=tz)
    return PeriodSummaryOut.model_validate(summary)


@router.get("/factories/{factory_id}/report.pdf")
async def get_report_pdf(
    factory_id: UUID,
    period: str = Query("day", pattern="^(day|week|month)$"),
    date: str | None = Query(None),
    start: str | None = Query(None),
    end: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    await _require_factory(db, factory_id)
    tz = ZoneInfo(settings.factory_tz)
    if start or end:
        if not (start and end):
            raise HTTPException(status_code=422, detail="pass both start and end")
        s, e = _range(start, end)
        path = await generate_range_report(str(factory_id), s, e, tz)
    else:
        path = await generate_report(str(factory_id), _anchor(date, tz), tz, period=period)
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@router.get("/factories/{factory_id}/data-extent")
async def data_extent(factory_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Earliest / latest metric bucket across the factory's cameras (UTC ISO),
    or nulls if no metrics exist. Lets the dashboard seed an "all-time" range."""
    await _require_factory(db, factory_id)
    cam_subq = (
        select(Camera.id)
        .join(Site, Site.id == Camera.site_id)
        .where(Site.factory_id == factory_id)
    )
    mn, mx = (
        await db.execute(
            select(func.min(MetricSample.bucket_start), func.max(MetricSample.bucket_start))
            .where(MetricSample.camera_id.in_(cam_subq))
        )
    ).one()
    return {
        "min": mn.isoformat() if mn else None,
        "max": mx.isoformat() if mx else None,
    }
