"""One-off verification for app.offline.runner.process_recording.

Makes a short clip from a factory file, runs it through the offline engine
under a THROWAWAY camera anchored to a known wall-clock start, then asserts the
metric_samples landed at start_dt + video-time. Deletes the temp camera at the
end (cascade removes its rows) so nothing is polluted.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app.pipeline  # noqa: E402,F401  (CUDA/TRT preload)
from sqlalchemy import delete, select  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Camera, CameraKind, MetricSample, Site  # noqa: E402
from app.offline.runner import process_recording  # noqa: E402

SRC = r"C:/Users/Office2/Desktop/factory/cam2.mp4"
N_FRAMES = 240  # ~30 s at native 8 fps
START_DT = datetime(2026, 3, 6, 9, 59, 56, tzinfo=timezone.utc)


def make_short_clip() -> str:
    cap = cv2.VideoCapture(SRC)
    fps = cap.get(cv2.CAP_PROP_FPS) or 8.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    tmp = str(Path(tempfile.gettempdir()) / "offline_verify_clip.mp4")
    out = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    n = 0
    while n < N_FRAMES:
        ok, frame = cap.read()
        if not ok:
            break
        out.write(frame)
        n += 1
    cap.release()
    out.release()
    print(f"made {n}-frame clip @ {fps:.1f}fps -> {tmp}")
    return tmp


async def main() -> int:
    clip = make_short_clip()

    async with SessionLocal() as s:
        site = (await s.execute(select(Site))).scalars().first()
        cam = Camera(
            site_id=site.id, name="__offline_verify__",
            kind=CameraKind.file, path_or_url=clip, sampling_fps=0.0,
        )
        s.add(cam)
        await s.commit()
        await s.refresh(cam)
        cam_id = cam.id
    print(f"temp camera {cam_id}")

    try:
        stats = await process_recording(cam_id, clip, START_DT)
        print(f"RunStats: frames={stats.frames} footage={stats.footage_s:.1f}s "
              f"buckets={stats.buckets_flushed} start={stats.start_dt} end={stats.end_dt}")

        async with SessionLocal() as s:
            rows = (await s.execute(
                select(MetricSample)
                .where(MetricSample.camera_id == cam_id)
                .order_by(MetricSample.bucket_start.asc())
            )).scalars().all()
        print(f"\nmetric_samples rows: {len(rows)}")
        ok = True
        for r in rows:
            off = (r.bucket_start - START_DT).total_seconds()
            aligned = abs(off % 10.0) < 0.001 or abs(off % 10.0 - 10.0) < 0.001
            print(f"  {r.bucket_start.isoformat()}  +{off:6.1f}s  "
                  f"frames={r.frames:3d} avg_hc={r.avg_headcount:.2f} "
                  f"peak={r.peak_headcount} aligned={aligned}")
            if off < 0 or not aligned:
                ok = False
        # First bucket must start at/after START_DT and be 10s-aligned to it.
        if rows and (rows[0].bucket_start - START_DT).total_seconds() not in (0.0,):
            print(f"NOTE first bucket offset = "
                  f"{(rows[0].bucket_start - START_DT).total_seconds()}s (expect 0.0)")
        print("\nRESULT:", "PASS" if (ok and rows) else "FAIL")
        return 0 if (ok and rows) else 1
    finally:
        async with SessionLocal() as s:
            await s.execute(delete(Camera).where(Camera.id == cam_id))
            await s.commit()
        print(f"cleaned up temp camera {cam_id}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(asyncio.run(main()))
