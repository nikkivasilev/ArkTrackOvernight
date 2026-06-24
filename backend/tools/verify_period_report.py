"""Validate the period report layer (week/month) with synthetic metrics.

No GPU/pipeline — the ingest→metrics path is verified separately. Here we build
a throwaway factory/site/camera/zone, synthesize a week of metric_samples (with
one day left empty), then assert:

  * build_week_summary / build_month_summary produce a per-CALENDAR-DAY timeline
    (timeline_kind == "daily") of the right length, with each day's average
    headcount matching a hand calc and the empty day reading 0;
  * factory_summary.worker_seconds equals the sum across all buckets;
  * render_period_pdf writes non-trivial week + month PDFs (exercises the
    daily-bar chart branch);
  * week_bounds is DST-correct (a spring-forward week is 167 h, not 168);
  * build_day_summary still works (intraday timeline) — a refactor regression guard.

Cleans up the throwaway factory (cascades everything).
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import delete  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import (  # noqa: E402
    Camera, CameraKind, Factory, MetricSample, Site, Zone,
)
from app.offline.day_summary import (  # noqa: E402
    build_day_summary, build_month_summary, build_week_summary, week_bounds,
)
from app.offline.report_pdf import render_period_pdf  # noqa: E402

TZ = ZoneInfo("UTC")
ANCHOR = date(2026, 3, 4)        # a Wednesday → ISO week Mon 2026-03-02 .. Sun 03-08
EMPTY_DAY = date(2026, 3, 5)     # left with no footage
BUCKETS_PER_DAY = 6
BUCKET_S = 600.0
REPORTS = ROOT / "data" / "reports"


def people_for(d: date) -> float:
    """Deterministic per-day headcount; 0 on the empty day."""
    if d == EMPTY_DAY:
        return 0.0
    return float(d.day % 5 + 2)  # 2..6, varies by day


def synth_week(camera_id, zone_id: str, monday: date) -> list[MetricSample]:
    rows: list[MetricSample] = []
    for i in range(7):
        d = monday + timedelta(days=i)
        ppl = people_for(d)
        if ppl <= 0:
            continue
        for b in range(BUCKETS_PER_DAY):
            t = (datetime.combine(d, time(8, 0), tzinfo=TZ)
                 + timedelta(seconds=b * BUCKET_S)).astimezone(timezone.utc)
            working = ppl * BUCKET_S
            rows.append(MetricSample(
                camera_id=camera_id, bucket_start=t, duration_s=BUCKET_S,
                worker_seconds=working, frames=int(BUCKET_S * 8),
                peak_headcount=int(ppl) + 1, avg_headcount=ppl,
                activity_seconds={"welding": working * 0.7, "walking": working * 0.3},
                rollup_seconds={"working": working},
                zone_occupancy_seconds={zone_id: {str(int(ppl)): BUCKET_S}},
                zone_activity_seconds={zone_id: {"welding": working * 0.7,
                                                 "walking": working * 0.3}},
            ))
    return rows


def check(label: str, cond: bool) -> bool:
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    return cond


async def main() -> int:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    oks: list[bool] = []

    # --- DST correctness (pure, no DB) -------------------------------------
    ny = ZoneInfo("America/New_York")
    s_utc, e_utc, _, _ = week_bounds(date(2026, 3, 8), ny)  # week of spring-forward
    span_h = (e_utc - s_utc).total_seconds() / 3600.0
    oks.append(check(f"spring-forward week span == 167 h (got {span_h:g})", span_h == 167.0))

    monday = week_bounds(ANCHOR, TZ)[2]
    exp_worker_s = sum(people_for(monday + timedelta(days=i)) for i in range(7)) \
        * BUCKET_S * BUCKETS_PER_DAY

    fac_id = None
    try:
        async with SessionLocal() as s:
            fac = Factory(name="__verify_period__")
            s.add(fac); await s.flush()
            fac_id = fac.id
            site = Site(factory_id=fac.id, name="Main Site")
            s.add(site); await s.flush()
            cam = Camera(site_id=site.id, name="IP Камера25 (welding bay)",
                         kind=CameraKind.file, path_or_url="x", sampling_fps=0.0)
            s.add(cam); await s.flush()
            zone = Zone(camera_id=cam.id, name="Welding station",
                        polygon=[[0, 0], [1, 0], [1, 1]], excluded=False)
            s.add(zone); await s.flush()
            s.add_all(synth_week(cam.id, str(zone.id), monday))
            await s.commit()

        async with SessionLocal() as s:
            wk = await build_week_summary(s, fac_id, ANCHOR, tz=TZ)
            mo = await build_month_summary(s, fac_id, ANCHOR, tz=TZ)
            day = await build_day_summary(s, fac_id, date(2026, 3, 4), tz=TZ)

        # --- week ----------------------------------------------------------
        oks.append(check("week timeline_kind == daily", wk.timeline_kind == "daily"))
        oks.append(check(f"week timeline has 7 days (got {len(wk.timeline)})",
                         len(wk.timeline) == 7))
        wk_by_date = {e["date"]: e["avg_headcount"] for e in wk.timeline}
        per_day_ok = all(
            wk_by_date.get(monday + timedelta(days=i))
            == round(people_for(monday + timedelta(days=i)) / 24.0, 2)
            for i in range(7)
        )
        oks.append(check("week per-day avg_headcount matches hand calc", per_day_ok))
        oks.append(check("empty day reads 0", wk_by_date.get(EMPTY_DAY) == 0.0))
        oks.append(check(
            f"week worker_seconds == {exp_worker_s:g} (got {wk.factory_summary['worker_seconds']:g})",
            abs(wk.factory_summary["worker_seconds"] - exp_worker_s) < 1.0))
        oks.append(check("week has 1 camera", len(wk.cameras) == 1))

        # --- month (March = 31 days; same buckets) -------------------------
        oks.append(check("month timeline_kind == daily", mo.timeline_kind == "daily"))
        oks.append(check(f"month timeline has 31 days (got {len(mo.timeline)})",
                         len(mo.timeline) == 31))
        mo_by_date = {e["date"]: e["avg_headcount"] for e in mo.timeline}
        oks.append(check("month filmed day matches",
                         mo_by_date.get(date(2026, 3, 2)) == round(4 / 24.0, 2)))
        oks.append(check("month unfilmed day reads 0",
                         mo_by_date.get(date(2026, 3, 15)) == 0.0))
        oks.append(check("month worker_seconds == week total",
                         abs(mo.factory_summary["worker_seconds"] - exp_worker_s) < 1.0))

        # --- day regression ------------------------------------------------
        oks.append(check("day timeline_kind == intraday", day.timeline_kind == "intraday"))
        oks.append(check("day worker_seconds matches",
                         abs(day.factory_summary["worker_seconds"]
                             - people_for(date(2026, 3, 4)) * BUCKET_S * BUCKETS_PER_DAY) < 1.0))

        # --- PDFs ----------------------------------------------------------
        REPORTS.mkdir(parents=True, exist_ok=True)
        wk_pdf = render_period_pdf(wk, REPORTS / "verify_week_report.pdf")
        mo_pdf = render_period_pdf(mo, REPORTS / "verify_month_report.pdf")
        oks.append(check(f"week PDF > 10 KB ({wk_pdf.stat().st_size} B)",
                         wk_pdf.stat().st_size > 10_000))
        oks.append(check(f"month PDF > 10 KB ({mo_pdf.stat().st_size} B)",
                         mo_pdf.stat().st_size > 10_000))
        print(f"\n  week PDF  -> {wk_pdf}")
        print(f"  month PDF -> {mo_pdf}")
    finally:
        if fac_id is not None:
            async with SessionLocal() as s:
                await s.execute(delete(Factory).where(Factory.id == fac_id))
                await s.commit()
            print(f"cleaned up temp factory {fac_id}")

    ok = all(oks)
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(asyncio.run(main()))
