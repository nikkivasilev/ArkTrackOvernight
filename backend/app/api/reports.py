"""Factory period-report endpoints — the in-app + downloadable analysis.

Both shapes are driven by the same period-summary builders the CLI/watcher use
(``app.offline.day_summary``), so the interactive JSON view and the PDF can
never disagree:

  GET /api/factories/{id}/report?period=day|week|month&date=YYYY-MM-DD
      -> PeriodSummaryOut (JSON) for the interactive Reports page.
  GET /api/factories/{id}/report.pdf?period=&date=
      -> the rendered PDF as a download.

``date`` is any day inside the period (the day / any day of the ISO week / any
day of the month); it defaults to today in the factory timezone.
"""
from __future__ import annotations

from datetime import date as date_cls, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models import Factory
from app.offline.day_summary import (
    build_day_summary,
    build_month_summary,
    build_week_summary,
)
from app.offline.reports import generate_report
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
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")


@router.get("/factories/{factory_id}/report", response_model=PeriodSummaryOut)
async def get_report(
    factory_id: UUID,
    period: str = Query("day", pattern="^(day|week|month)$"),
    date: str | None = Query(None, description="YYYY-MM-DD; any day in the period (default: today)"),
    db: AsyncSession = Depends(get_db),
) -> PeriodSummaryOut:
    factory = await db.get(Factory, factory_id)
    if factory is None:
        raise HTTPException(status_code=404, detail="factory not found")
    tz = ZoneInfo(settings.factory_tz)
    summary = await _BUILDERS[period](db, factory_id, _anchor(date, tz), tz=tz)
    return PeriodSummaryOut.model_validate(summary)


@router.get("/factories/{factory_id}/report.pdf")
async def get_report_pdf(
    factory_id: UUID,
    period: str = Query("day", pattern="^(day|week|month)$"),
    date: str | None = Query(None, description="YYYY-MM-DD; any day in the period (default: today)"),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    factory = await db.get(Factory, factory_id)
    if factory is None:
        raise HTTPException(status_code=404, detail="factory not found")
    tz = ZoneInfo(settings.factory_tz)
    path = await generate_report(str(factory_id), _anchor(date, tz), tz, period=period)
    return FileResponse(path, media_type="application/pdf", filename=path.name)
