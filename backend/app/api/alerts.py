from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Alert, Camera, Site
from app.realtime.broadcaster import broadcaster
from app.schemas import AlertOut

router = APIRouter()


@router.get("", response_model=list[AlertOut])
async def list_alerts(
    factory_id: UUID | None = Query(None),
    site_id: UUID | None = Query(None),
    camera_id: UUID | None = Query(None),
    acknowledged: bool | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> list[AlertOut]:
    stmt = select(Alert).order_by(Alert.created_at.desc()).limit(limit)
    if camera_id:
        stmt = stmt.where(Alert.camera_id == camera_id)
    elif site_id:
        stmt = stmt.join(Camera, Camera.id == Alert.camera_id).where(Camera.site_id == site_id)
    elif factory_id:
        stmt = (
            stmt.join(Camera, Camera.id == Alert.camera_id)
            .join(Site, Site.id == Camera.site_id)
            .where(Site.factory_id == factory_id)
        )
    if acknowledged is not None:
        stmt = stmt.where(Alert.acknowledged.is_(acknowledged))
    q = await db.execute(stmt)
    return [AlertOut.model_validate(a) for a in q.scalars().all()]


@router.get("/{alert_id}", response_model=AlertOut)
async def get_alert(alert_id: UUID, db: AsyncSession = Depends(get_db)) -> AlertOut:
    alert = await db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    return AlertOut.model_validate(alert)


@router.post("/{alert_id}/ack", response_model=AlertOut)
async def ack_alert(alert_id: UUID, db: AsyncSession = Depends(get_db)) -> AlertOut:
    alert = await db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    if not alert.acknowledged:
        alert.acknowledged = True
        alert.acknowledged_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(alert)
        await broadcaster.publish({
            "type": "alert.acknowledged", "v": 1,
            "data": {"id": str(alert.id), "acknowledged_at": alert.acknowledged_at.isoformat()},
        })
    return AlertOut.model_validate(alert)


@router.delete("/{alert_id}")
async def delete_alert(alert_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    alert = await db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    # Remove the media files from disk (best-effort), then the row.
    for p in (alert.thumbnail_path, alert.clip_path):
        if p:
            try:
                Path(p).unlink(missing_ok=True)
            except OSError:
                pass
    await db.delete(alert)
    await db.commit()
    await broadcaster.publish({
        "type": "alert.deleted", "v": 1, "data": {"id": str(alert_id)},
    })
    return {"id": str(alert_id), "deleted": True}


@router.get("/{alert_id}/thumbnail")
async def get_alert_thumbnail(alert_id: UUID, db: AsyncSession = Depends(get_db)) -> FileResponse:
    alert = await db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    p = Path(alert.thumbnail_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="thumbnail not found")
    return FileResponse(p, media_type="image/jpeg")


@router.get("/{alert_id}/clip")
async def get_alert_clip(alert_id: UUID, db: AsyncSession = Depends(get_db)) -> FileResponse:
    alert = await db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    if not alert.clip_path:
        raise HTTPException(status_code=404, detail="clip not available")
    p = Path(alert.clip_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="clip file missing")
    # FileResponse serves HTTP Range natively → <video> seeking works.
    return FileResponse(p, media_type="video/webm")
