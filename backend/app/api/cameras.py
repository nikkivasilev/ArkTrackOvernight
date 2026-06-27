from __future__ import annotations

from pathlib import Path
from uuid import UUID

import cv2
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Camera, ProcessedRecording
from app.schemas import CameraOut
from app.workers import frame_sampler

router = APIRouter()


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


@router.delete("/cameras/{camera_id}")
async def delete_camera(camera_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    cam = await db.get(Camera, camera_id)
    if cam is None:
        raise HTTPException(status_code=404, detail="camera not found")
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
