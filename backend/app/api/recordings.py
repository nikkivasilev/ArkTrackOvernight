"""Processed-recording ledger endpoints — the operator's view of ingest.

Read-only: lists every recording the offline batch has seen for a factory
(factory → sites → cameras → processed_recordings), newest first, with the
camera name joined in and a ``file_exists`` flag so the UI can surface footage
that has since been rotated/deleted off disk. Ingest itself stays on the
watcher/CLI (it's GPU-bound and sequential), so there is deliberately no
HTTP trigger here.
"""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Camera, Factory, ProcessedRecording, Site
from app.schemas import ProcessedRecordingOut

router = APIRouter()


@router.get("/factories/{factory_id}/recordings", response_model=list[ProcessedRecordingOut])
async def list_recordings(
    factory_id: UUID,
    status: str | None = Query(None, description="filter by status: processing|done|failed"),
    db: AsyncSession = Depends(get_db),
) -> list[ProcessedRecordingOut]:
    factory = await db.get(Factory, factory_id)
    if factory is None:
        raise HTTPException(status_code=404, detail="factory not found")

    site_ids = (
        await db.execute(select(Site.id).where(Site.factory_id == factory_id))
    ).scalars().all()
    cam_name: dict[UUID, str] = {}
    if site_ids:
        rows = (
            await db.execute(
                select(Camera.id, Camera.name).where(Camera.site_id.in_(site_ids))
            )
        ).all()
        cam_name = {cid: name for cid, name in rows}
    if not cam_name:
        return []

    q = select(ProcessedRecording).where(
        ProcessedRecording.camera_id.in_(list(cam_name.keys()))
    )
    if status:
        q = q.where(ProcessedRecording.status == status)
    q = q.order_by(ProcessedRecording.recorded_start.desc())
    recs = (await db.execute(q)).scalars().all()

    out: list[ProcessedRecordingOut] = []
    for r in recs:
        item = ProcessedRecordingOut.model_validate(r)
        item.camera_name = cam_name.get(r.camera_id)
        item.file_exists = Path(r.path).exists()
        out.append(item)
    return out
