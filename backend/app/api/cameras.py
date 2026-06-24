from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from uuid import UUID

import cv2
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models import Camera, CameraKind, CameraStatus, ProcessedRecording, Site
from app.realtime import live_streams
from app.realtime.broadcaster import broadcaster
from app.schemas import CameraOut
from app.storage.media import upload_path
from app.workers import frame_sampler, registry
from app.workers.camera_worker import run_camera_worker

router = APIRouter()


def _start_worker(camera_id: UUID) -> None:
    task = asyncio.create_task(run_camera_worker(camera_id))
    registry.register(camera_id, task)


@router.post("/sites/{site_id}/cameras", response_model=CameraOut)
async def upload_camera(
    site_id: UUID,
    file: UploadFile = File(...),
    name: str | None = Form(None),
    sampling_fps: float | None = Form(None),
    db: AsyncSession = Depends(get_db),
) -> CameraOut:
    site = await db.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="site not found")
    if not file.filename:
        raise HTTPException(status_code=400, detail="missing filename")

    camera_id = uuid.uuid4()
    dest = upload_path(camera_id, file.filename)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            out.write(chunk)

    try:
        info = frame_sampler.probe(str(dest))
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"could not open video: {exc}")

    # sampling_fps semantics: None / 0 → Auto (worker probes native fps).
    # Positive value → operator-chosen preset, use as-is. Default Auto.
    persisted_fps = float(sampling_fps) if sampling_fps and sampling_fps > 0 else 0.0
    cam = Camera(
        id=camera_id,
        site_id=site_id,
        kind=CameraKind.file,
        name=name or file.filename,
        path_or_url=str(dest),
        duration_s=info.duration_s,
        sampling_fps=persisted_fps,
        status=CameraStatus.queued,
    )
    db.add(cam)
    await db.commit()
    await db.refresh(cam)

    _start_worker(cam.id)
    return CameraOut.model_validate(cam)


@router.get("/sites/{site_id}/cameras", response_model=list[CameraOut])
async def list_cameras_for_site(
    site_id: UUID, db: AsyncSession = Depends(get_db)
) -> list[CameraOut]:
    q = await db.execute(select(Camera).where(Camera.site_id == site_id).order_by(Camera.created_at))
    return [CameraOut.model_validate(c) for c in q.scalars().all()]


@router.get("/cameras", response_model=list[CameraOut])
async def list_all_cameras(db: AsyncSession = Depends(get_db)) -> list[CameraOut]:
    q = await db.execute(select(Camera).order_by(Camera.created_at.desc()))
    return [CameraOut.model_validate(c) for c in q.scalars().all()]


@router.get("/cameras/{camera_id}", response_model=CameraOut)
async def get_camera(camera_id: UUID, db: AsyncSession = Depends(get_db)) -> CameraOut:
    cam = await db.get(Camera, camera_id)
    if cam is None:
        raise HTTPException(status_code=404, detail="camera not found")
    return CameraOut.model_validate(cam)


@router.post("/cameras/{camera_id}/start", response_model=CameraOut)
async def start_camera(camera_id: UUID, db: AsyncSession = Depends(get_db)) -> CameraOut:
    cam = await db.get(Camera, camera_id)
    if cam is None:
        raise HTTPException(status_code=404, detail="camera not found")
    if registry.is_running(camera_id):
        return CameraOut.model_validate(cam)
    cam.status = CameraStatus.queued
    cam.error = None
    cam.last_processed_frame_idx = 0
    await db.commit()
    _start_worker(camera_id)
    await db.refresh(cam)
    return CameraOut.model_validate(cam)


@router.post("/cameras/{camera_id}/cancel", response_model=CameraOut)
async def cancel_camera(camera_id: UUID, db: AsyncSession = Depends(get_db)) -> CameraOut:
    cam = await db.get(Camera, camera_id)
    if cam is None:
        raise HTTPException(status_code=404, detail="camera not found")
    # When a worker task is registered, registry.cancel() raises CancelledError
    # inside it; the worker's `except CancelledError` handler then writes
    # status=cancelled to the DB. But after a backend restart the registry is
    # empty (no tasks survived), so registry.cancel() returns False silently
    # and the stale `running` DB row would stick forever. Update the DB here
    # too — idempotent with the worker's own write when both happen.
    had_task = registry.cancel(camera_id)
    if cam.status in (CameraStatus.queued, CameraStatus.running):
        cam.status = CameraStatus.cancelled
        await db.commit()
        await db.refresh(cam)
        await broadcaster.publish({
            "type": "camera.updated", "v": 1,
            "data": {"id": str(camera_id), "status": "cancelled"},
        })
    return CameraOut.model_validate(cam)


@router.delete("/cameras/{camera_id}")
async def delete_camera(camera_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    cam = await db.get(Camera, camera_id)
    if cam is None:
        raise HTTPException(status_code=404, detail="camera not found")
    registry.cancel(camera_id)
    live_streams.clear(camera_id)
    try:
        p = Path(cam.path_or_url)
        if p.exists():
            p.unlink()
    except Exception:
        pass
    await db.delete(cam)
    await db.commit()
    return {"ok": True}


@router.get("/cameras/{camera_id}/frame")
async def get_camera_frame(
    camera_id: UUID,
    t: float = Query(0.0, ge=0.0, description="time offset in seconds"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    cam = await db.get(Camera, camera_id)
    if cam is None:
        raise HTTPException(status_code=404, detail="camera not found")
    path = cam.path_or_url
    if not path or not Path(path).exists():
        # Offline cameras reference the first file seen; if it's been rotated or
        # deleted off disk, fall back to the newest recording still present.
        recs = (
            await db.execute(
                select(ProcessedRecording.path)
                .where(
                    ProcessedRecording.camera_id == camera_id,
                    ProcessedRecording.status == "done",
                )
                .order_by(ProcessedRecording.recorded_start.desc())
            )
        ).scalars().all()
        path = next((p for p in recs if p and Path(p).exists()), None)
    if path is None:
        raise HTTPException(status_code=404, detail="no recording on disk for this camera")
    frame = frame_sampler.grab_frame_at(path, t)
    if frame is None:
        raise HTTPException(status_code=404, detail="frame not available")
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not ok:
        raise HTTPException(status_code=500, detail="encode failed")
    return Response(content=buf.tobytes(), media_type="image/jpeg")


_MJPEG_BOUNDARY = b"frame"


def _mjpeg_chunk(jpeg: bytes) -> bytes:
    return (
        b"--" + _MJPEG_BOUNDARY + b"\r\n"
        b"Content-Type: image/jpeg\r\n"
        b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
        + jpeg + b"\r\n"
    )


@router.get("/cameras/{camera_id}/live.mjpg")
async def get_camera_live_mjpeg(
    camera_id: UUID, db: AsyncSession = Depends(get_db)
) -> StreamingResponse:
    cam = await db.get(Camera, camera_id)
    if cam is None:
        raise HTTPException(status_code=404, detail="camera not found")

    async def gen():
        first = live_streams.latest(camera_id)
        if first is not None:
            yield _mjpeg_chunk(first)
        async with live_streams.subscribe(camera_id) as q:
            while True:
                jpeg = await q.get()
                yield _mjpeg_chunk(jpeg)

    return StreamingResponse(
        gen(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store"},
    )
