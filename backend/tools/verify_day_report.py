"""Validate the report layer (day_summary + report_pdf) with synthetic metrics.

No GPU/pipeline — the ingest→metrics path is verified separately. Here we
build a throwaway factory/site/cameras/zones, synthesize a day of
metric_samples + ledger rows, build the DaySummary, render the PDF, and assert
it's a non-trivial file. Cleans up the factory (cascades everything).
"""
from __future__ import annotations

import asyncio
import math
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import delete, select  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import (  # noqa: E402
    Camera, CameraKind, Factory, MetricSample, ProcessedRecording, Site, Zone,
)
from app.offline.day_summary import build_day_summary  # noqa: E402
from app.offline.report_pdf import render_day_pdf  # noqa: E402

TZ = ZoneInfo("UTC")
DAY = date(2026, 3, 6)
OUT = ROOT / "data" / "reports" / "verify_day_report.pdf"


def synth_buckets(camera_id, zones: list[str], base_people: float):
    """10-min buckets over an 08:00–17:00 local shift with a staffing curve."""
    start_local = datetime.combine(DAY, time(8, 0), tzinfo=TZ)
    rows = []
    for i in range(54):  # 9 h × 6 buckets
        t = (start_local + timedelta(minutes=10 * i)).astimezone(timezone.utc)
        # staffing peaks midday, dips at lunch (~12:30)
        hour = 8 + i / 6.0
        curve = math.sin((hour - 8) / 9.0 * math.pi)
        lunch = 0.45 if 12.3 <= hour <= 13.0 else 1.0
        people = max(0.0, base_people * curve * lunch)
        dur = 600.0
        working = people * dur * 0.62
        idle = people * dur * 0.23
        moving = people * dur * 0.15
        zocc = {z: {str(int(round(people))): dur} for z in zones}
        zact = {
            z: {"welding": people * dur * 0.4, "walking": people * dur * 0.15,
                "standing_idle": people * dur * 0.2, "assembling": people * dur * 0.25}
            for z in zones
        }
        rows.append(MetricSample(
            camera_id=camera_id, bucket_start=t, duration_s=dur,
            worker_seconds=working + idle + moving,
            frames=int(dur * 8), peak_headcount=int(round(people)) + 1,
            avg_headcount=round(people, 2),
            activity_seconds={"welding": working * 0.6, "assembling": working * 0.4,
                              "walking": moving, "standing_idle": idle},
            rollup_seconds={"working": working, "idle": idle, "moving": moving},
            zone_occupancy_seconds=zocc, zone_activity_seconds=zact,
        ))
    return rows


async def main() -> int:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    fac_id = None
    try:
        async with SessionLocal() as s:
            fac = Factory(name="__verify_factory__")
            s.add(fac)
            await s.flush()
            fac_id = fac.id
            site = Site(factory_id=fac.id, name="Main Site")
            s.add(site)
            await s.flush()
            cam_a = Camera(site_id=site.id, name="IP Камера25 (welding bay)",
                           kind=CameraKind.file, path_or_url="x", sampling_fps=0.0)
            cam_b = Camera(site_id=site.id, name="Line 2 assembly",
                           kind=CameraKind.file, path_or_url="x", sampling_fps=0.0)
            s.add_all([cam_a, cam_b])
            await s.flush()
            za = Zone(camera_id=cam_a.id, name="Welding station",
                      polygon=[[0, 0], [1, 0], [1, 1]], excluded=False)
            zb = Zone(camera_id=cam_b.id, name="Conveyor",
                      polygon=[[0, 0], [1, 0], [1, 1]], excluded=False)
            s.add_all([za, zb])
            await s.flush()

            rows = synth_buckets(cam_a.id, [str(za.id)], 7.0)
            rows += synth_buckets(cam_b.id, [str(zb.id)], 4.0)
            s.add_all(rows)
            s.add_all([
                ProcessedRecording(
                    camera_id=cam_a.id, path="/x/a1.mp4", filename="a1.mp4",
                    recorded_start=datetime.combine(DAY, time(8, 0), tzinfo=timezone.utc),
                    recorded_end=datetime.combine(DAY, time(17, 0), tzinfo=timezone.utc),
                    frames=259200, footage_s=32400.0, status="done"),
                ProcessedRecording(
                    camera_id=cam_b.id, path="/x/b1.mp4", filename="b1.mp4",
                    recorded_start=datetime.combine(DAY, time(8, 0), tzinfo=timezone.utc),
                    recorded_end=datetime.combine(DAY, time(17, 0), tzinfo=timezone.utc),
                    frames=259200, footage_s=32400.0, status="done"),
            ])
            await s.commit()

        async with SessionLocal() as s:
            summary = await build_day_summary(s, fac_id, DAY, tz=TZ, bin_minutes=30)
        print(f"factory_summary worker-hours={summary.factory_summary['worker_seconds']/3600:.1f} "
              f"avg_hc={summary.factory_summary['avg_headcount']} "
              f"peak={summary.factory_summary['peak_headcount']} "
              f"cameras={len(summary.cameras)} timeline_bins={len(summary.timeline)}")
        for c in summary.cameras:
            print(f"  camera {c.name!r}: {c.summary['worker_seconds']/3600:.1f}h "
                  f"zones={list(c.zone_names.values())}")

        path = render_day_pdf(summary, OUT)
        size = path.stat().st_size
        print(f"\nPDF -> {path} ({size} bytes)")
        ok = (
            size > 10_000
            and len(summary.cameras) == 2
            and summary.factory_summary["peak_headcount"] > 0
        )
        print("RESULT:", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        if fac_id is not None:
            async with SessionLocal() as s:
                await s.execute(delete(Factory).where(Factory.id == fac_id))
                await s.commit()
            print(f"cleaned up temp factory {fac_id}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(asyncio.run(main()))
