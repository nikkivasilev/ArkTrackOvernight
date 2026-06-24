"""End-to-end check for app.offline.batch.ingest_folder.

Builds a temp drop dir holding one NVR-named short clip, runs the folder
ingest, asserts a camera + ledger row + metric_samples were produced at the
filename's wall-clock time, then re-runs to confirm idempotent skip. Cleans up
the created camera (cascades metrics + ledger) and temp files.
"""
from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app.pipeline  # noqa: E402,F401  (CUDA/TRT preload)
from sqlalchemy import delete, select  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Camera, MetricSample, ProcessedRecording  # noqa: E402
from app.offline.batch import ingest_folder  # noqa: E402

SRC = r"C:/Users/Office2/Desktop/factory/cam2.mp4"
CLIP_NAME = "TESTCAM_VERIFY_NVRserver_Montage_20260306095956_20260306100026_000001.mp4"
EXP_LABEL = "TESTCAM_VERIFY"
EXP_START = datetime(2026, 3, 6, 9, 59, 56, tzinfo=timezone.utc)


def make_clip(dst: Path, n_frames: int = 240) -> None:
    cap = cv2.VideoCapture(SRC)
    fps = cap.get(cv2.CAP_PROP_FPS) or 8.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    out = cv2.VideoWriter(str(dst), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    n = 0
    while n < n_frames:
        ok, frame = cap.read()
        if not ok:
            break
        out.write(frame)
        n += 1
    cap.release()
    out.release()
    print(f"made {n}-frame clip @ {fps:.1f}fps -> {dst.name}")


async def main() -> int:
    # The ProcessedRecording table was just added — ensure schema exists.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    drop = Path(tempfile.mkdtemp(prefix="offline_batch_"))
    make_clip(drop / CLIP_NAME)
    clip_path = str(drop / CLIP_NAME)
    cam_id = None
    ok = True
    try:
        rows = await ingest_folder(drop_dir=drop, tz=ZoneInfo("UTC"))
        print(f"\ningest_folder -> {len(rows)} processed")
        ok = ok and len(rows) == 1
        if rows:
            r = rows[0]
            cam_id = r.camera_id
            print(f"  ledger: status={r.status} frames={r.frames} "
                  f"footage={r.footage_s:.0f}s start={r.recorded_start.isoformat()}")
            ok = ok and r.status == "done" and r.frames > 0

            async with SessionLocal() as s:
                cam = await s.get(Camera, cam_id)
                ms = (await s.execute(
                    select(MetricSample).where(MetricSample.camera_id == cam_id)
                    .order_by(MetricSample.bucket_start.asc())
                )).scalars().all()
            print(f"  camera name={cam.name!r}")
            print(f"  metric_samples: {len(ms)} rows; "
                  f"first={ms[0].bucket_start.isoformat() if ms else None}")
            ok = ok and cam.name == EXP_LABEL and len(ms) >= 1
            ok = ok and ms and ms[0].bucket_start == EXP_START

        # Re-run: must skip (idempotent).
        rows2 = await ingest_folder(drop_dir=drop, tz=ZoneInfo("UTC"))
        print(f"re-run ingest_folder -> {len(rows2)} processed (expect 0)")
        ok = ok and len(rows2) == 0

        print("\nRESULT:", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        if cam_id is not None:
            async with SessionLocal() as s:
                # processed_recordings cascades on camera delete; be explicit too.
                await s.execute(delete(ProcessedRecording).where(ProcessedRecording.camera_id == cam_id))
                await s.execute(delete(Camera).where(Camera.id == cam_id))
                await s.commit()
            print(f"cleaned up temp camera {cam_id}")
        shutil.rmtree(drop, ignore_errors=True)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(asyncio.run(main()))
