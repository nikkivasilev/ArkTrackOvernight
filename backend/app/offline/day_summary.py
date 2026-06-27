"""Build a factory period summary (day / week / month) from ``metric_samples``.

Aggregates one local-calendar period across every camera under a factory into
the structure the PDF/JSON report renders: a factory-wide headline, a staffing
timeline (intraday curve for a day; per-day bars for a week/month), per-camera
breakdowns, and per-zone occupancy/activity — plus the footage-coverage facts
from the ``processed_recordings`` ledger so the report states honestly which
hours were actually filmed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Camera, Factory, MetricSample, ProcessedRecording, Site, Zone
from app.offline.aggregate import daily_timeline, fold_samples, staffing_timeline


@dataclass
class CameraDay:
    camera_id: str
    name: str
    summary: dict
    zone_names: dict[str, str]
    recordings: int
    footage_s: float


@dataclass
class PeriodSummary:
    factory_id: str
    factory_name: str
    period: str            # "day" | "week" | "month"
    start: date            # first local calendar day (inclusive)
    end: date              # last local calendar day (inclusive)
    tz: str
    generated_at: datetime
    start_utc: datetime
    end_utc: datetime
    factory_summary: dict
    timeline: list[dict]
    timeline_kind: str     # "intraday" (per-bin) | "daily" (per-calendar-day)
    cameras: list[CameraDay] = field(default_factory=list)
    zone_names: dict[str, str] = field(default_factory=dict)
    total_recordings: int = 0
    total_footage_s: float = 0.0


# Back-compat alias: the day report and existing callers still import DaySummary.
DaySummary = PeriodSummary


_UTC = ZoneInfo("UTC")


def _local_midnight_utc(d: date, tz: ZoneInfo) -> datetime:
    """The UTC instant of local 00:00 on ``d`` (DST-correct for that date)."""
    return datetime.combine(d, time.min, tzinfo=tz).astimezone(_UTC)


def day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime, date, date]:
    return _local_midnight_utc(day, tz), _local_midnight_utc(day + timedelta(days=1), tz), day, day


def week_bounds(any_day: date, tz: ZoneInfo) -> tuple[datetime, datetime, date, date]:
    """ISO week (Monday-start) containing ``any_day``."""
    monday = any_day - timedelta(days=any_day.isoweekday() - 1)
    return (
        _local_midnight_utc(monday, tz),
        _local_midnight_utc(monday + timedelta(days=7), tz),
        monday, monday + timedelta(days=6),
    )


def month_bounds(any_day: date, tz: ZoneInfo) -> tuple[datetime, datetime, date, date]:
    first = any_day.replace(day=1)
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)  # 1st of next month
    return (
        _local_midnight_utc(first, tz),
        _local_midnight_utc(nxt, tz),
        first, nxt - timedelta(days=1),
    )


async def build_period_summary(
    session: AsyncSession,
    factory_id,
    start_utc: datetime,
    end_utc: datetime,
    tz: ZoneInfo,
    period: str,
    start: date,
    end: date,
    bin_minutes: int = 30,
    timeline_kind: str | None = None,
) -> PeriodSummary:
    """Fold every camera under a factory over [start_utc, end_utc) into a summary.

    ``period`` is "day" | "week" | "month"; it only selects the timeline shape
    (intraday curve vs per-day bars). The metric folding is range-agnostic, so
    the same builder serves all three — the day/week/month wrappers below just
    compute the local-calendar bounds.
    """
    window_s = (end_utc - start_utc).total_seconds()

    factory = await session.get(Factory, factory_id)
    if factory is None:
        raise ValueError(f"factory {factory_id} not found")

    # Cameras under this factory (factory → sites → cameras).
    site_ids = (
        await session.execute(select(Site.id).where(Site.factory_id == factory_id))
    ).scalars().all()
    cameras = (
        await session.execute(select(Camera).where(Camera.site_id.in_(site_ids)))
        if site_ids else None
    )
    cameras = cameras.scalars().all() if cameras is not None else []
    cam_ids = [c.id for c in cameras]

    # Zone id → name across all these cameras (for readable zone labels).
    zone_names: dict[str, str] = {}
    if cam_ids:
        zones = (
            await session.execute(select(Zone).where(Zone.camera_id.in_(cam_ids)))
        ).scalars().all()
        zone_names = {str(z.id): z.name for z in zones}

    # All metric rows for the period, ordered for the timeline.
    rows: list[MetricSample] = []
    if cam_ids:
        rows = (
            await session.execute(
                select(MetricSample)
                .where(
                    MetricSample.camera_id.in_(cam_ids),
                    MetricSample.bucket_start >= start_utc,
                    MetricSample.bucket_start < end_utc,
                )
                .order_by(MetricSample.bucket_start.asc())
            )
        ).scalars().all()

    rows_by_cam: dict = {}
    for r in rows:
        rows_by_cam.setdefault(r.camera_id, []).append(r)

    # Footage coverage from the ledger (recordings overlapping the period). The
    # 1-day lower-bound slack lets a recording that started just before the
    # window but ran into it still count (NVR exports are short).
    ledger: list[ProcessedRecording] = []
    if cam_ids:
        ledger = (
            await session.execute(
                select(ProcessedRecording).where(
                    ProcessedRecording.camera_id.in_(cam_ids),
                    ProcessedRecording.recorded_start < end_utc,
                    ProcessedRecording.recorded_start >= start_utc - timedelta(days=1),
                    ProcessedRecording.status == "done",
                )
            )
        ).scalars().all()
    rec_by_cam: dict = {}
    for rec in ledger:
        if rec.recorded_start < end_utc and (rec.recorded_end or rec.recorded_start) >= start_utc:
            rec_by_cam.setdefault(rec.camera_id, []).append(rec)

    cam_days: list[CameraDay] = []
    for cam in cameras:
        crows = rows_by_cam.get(cam.id, [])
        if not crows and cam.id not in rec_by_cam:
            continue  # camera contributed nothing this period
        crecs = rec_by_cam.get(cam.id, [])
        summary = fold_samples(crows, window_s=window_s)
        # Attach readable zone names onto the per-zone blocks.
        czones = {
            zid: zone_names.get(zid, zid)
            for zid in set(summary["zone_occupancy"]) | set(summary["zone_activity"])
        }
        cam_days.append(CameraDay(
            camera_id=str(cam.id), name=cam.name, summary=summary,
            zone_names=czones, recordings=len(crecs),
            footage_s=round(sum(r.footage_s or 0.0 for r in crecs), 1),
        ))

    cam_days.sort(key=lambda c: c.summary["worker_seconds"], reverse=True)

    kind = timeline_kind or ("intraday" if period == "day" else "daily")
    if kind == "intraday":
        timeline = staffing_timeline(rows, start_utc, end_utc, bin_minutes)
    else:
        timeline = daily_timeline(rows, start_utc, end_utc, tz)
    timeline_kind = kind

    return PeriodSummary(
        factory_id=str(factory_id),
        factory_name=factory.name,
        period=period,
        start=start,
        end=end,
        tz=str(tz),
        generated_at=datetime.now(_UTC),
        start_utc=start_utc,
        end_utc=end_utc,
        factory_summary=fold_samples(rows, window_s=window_s),
        timeline=timeline,
        timeline_kind=timeline_kind,
        cameras=cam_days,
        zone_names=zone_names,
        total_recordings=len(ledger),
        total_footage_s=round(sum(r.footage_s or 0.0 for r in ledger), 1),
    )


async def build_day_summary(
    session: AsyncSession,
    factory_id,
    day: date,
    tz: ZoneInfo | None = None,
    bin_minutes: int = 30,
) -> PeriodSummary:
    tz = tz or ZoneInfo(settings.factory_tz)
    start_utc, end_utc, start, end = day_bounds(day, tz)
    return await build_period_summary(
        session, factory_id, start_utc, end_utc, tz, "day", start, end, bin_minutes
    )


async def build_week_summary(
    session: AsyncSession, factory_id, any_day: date, tz: ZoneInfo | None = None,
) -> PeriodSummary:
    tz = tz or ZoneInfo(settings.factory_tz)
    start_utc, end_utc, start, end = week_bounds(any_day, tz)
    return await build_period_summary(
        session, factory_id, start_utc, end_utc, tz, "week", start, end
    )


async def build_month_summary(
    session: AsyncSession, factory_id, any_day: date, tz: ZoneInfo | None = None,
) -> PeriodSummary:
    tz = tz or ZoneInfo(settings.factory_tz)
    start_utc, end_utc, start, end = month_bounds(any_day, tz)
    return await build_period_summary(
        session, factory_id, start_utc, end_utc, tz, "month", start, end
    )


async def build_range_summary(
    session: AsyncSession,
    factory_id,
    start: date,
    end: date,
    tz: ZoneInfo | None = None,
    bin_minutes: int = 30,
) -> PeriodSummary:
    """Arbitrary inclusive local-date range [start, end].

    Same range-agnostic folding as the day/week/month builders; the timeline is
    an intraday curve for spans up to 2 days and per-day bars beyond that.
    """
    tz = tz or ZoneInfo(settings.factory_tz)
    start_utc = _local_midnight_utc(start, tz)
    end_utc = _local_midnight_utc(end + timedelta(days=1), tz)
    kind = "intraday" if (end - start).days <= 1 else "daily"
    return await build_period_summary(
        session, factory_id, start_utc, end_utc, tz, "range", start, end,
        bin_minutes, timeline_kind=kind,
    )
