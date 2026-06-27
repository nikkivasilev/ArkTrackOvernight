from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Camera, Zone
from app.schemas import ZoneCreate, ZoneOut, ZoneUpdate

router = APIRouter()


def _validate_polygon(polygon: list[list[float]]) -> None:
    if len(polygon) < 3:
        raise HTTPException(status_code=400, detail="polygon needs at least 3 points")
    for pt in polygon:
        if len(pt) != 2:
            raise HTTPException(status_code=400, detail="each point must be [x, y]")
        x, y = pt
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise HTTPException(status_code=400, detail="coords must be normalized 0..1")


@router.post("/cameras/{camera_id}/zones", response_model=ZoneOut)
async def create_zone(
    camera_id: UUID, payload: ZoneCreate, db: AsyncSession = Depends(get_db)
) -> ZoneOut:
    cam = await db.get(Camera, camera_id)
    if cam is None:
        raise HTTPException(status_code=404, detail="camera not found")
    _validate_polygon(payload.polygon)
    zone = Zone(
        camera_id=camera_id,
        name=payload.name,
        polygon=payload.polygon,
        excluded=payload.excluded,
    )
    db.add(zone)
    await db.commit()
    await db.refresh(zone)
    return ZoneOut.model_validate(zone)


@router.get("/cameras/{camera_id}/zones", response_model=list[ZoneOut])
async def list_zones(camera_id: UUID, db: AsyncSession = Depends(get_db)) -> list[ZoneOut]:
    q = await db.execute(select(Zone).where(Zone.camera_id == camera_id).order_by(Zone.created_at))
    return [ZoneOut.model_validate(z) for z in q.scalars().all()]


@router.patch("/zones/{zone_id}", response_model=ZoneOut)
async def update_zone(
    zone_id: UUID, payload: ZoneUpdate, db: AsyncSession = Depends(get_db)
) -> ZoneOut:
    zone = await db.get(Zone, zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail="zone not found")
    if payload.name is not None:
        zone.name = payload.name
    if payload.excluded is not None:
        zone.excluded = payload.excluded
    await db.commit()
    await db.refresh(zone)
    return ZoneOut.model_validate(zone)


@router.delete("/zones/{zone_id}")
async def delete_zone(zone_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    zone = await db.get(Zone, zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail="zone not found")
    await db.delete(zone)
    await db.commit()
    return {"ok": True}
