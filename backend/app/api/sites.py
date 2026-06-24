from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Factory, Site
from app.schemas import SiteCreate, SiteOut, SiteUpdate

router = APIRouter()


@router.post("/factories/{factory_id}/sites", response_model=SiteOut)
async def create_site(
    factory_id: UUID, payload: SiteCreate, db: AsyncSession = Depends(get_db)
) -> SiteOut:
    f = await db.get(Factory, factory_id)
    if f is None:
        raise HTTPException(status_code=404, detail="factory not found")
    s = Site(factory_id=factory_id, name=payload.name, address=payload.address)
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return SiteOut.model_validate(s)


@router.get("/factories/{factory_id}/sites", response_model=list[SiteOut])
async def list_sites_for_factory(
    factory_id: UUID, db: AsyncSession = Depends(get_db)
) -> list[SiteOut]:
    q = await db.execute(select(Site).where(Site.factory_id == factory_id).order_by(Site.created_at))
    return [SiteOut.model_validate(s) for s in q.scalars().all()]


@router.get("/sites/{site_id}", response_model=SiteOut)
async def get_site(site_id: UUID, db: AsyncSession = Depends(get_db)) -> SiteOut:
    s = await db.get(Site, site_id)
    if s is None:
        raise HTTPException(status_code=404, detail="site not found")
    return SiteOut.model_validate(s)


@router.patch("/sites/{site_id}", response_model=SiteOut)
async def update_site(
    site_id: UUID, payload: SiteUpdate, db: AsyncSession = Depends(get_db)
) -> SiteOut:
    s = await db.get(Site, site_id)
    if s is None:
        raise HTTPException(status_code=404, detail="site not found")
    if payload.name is not None:
        s.name = payload.name
    if payload.address is not None:
        s.address = payload.address
    await db.commit()
    await db.refresh(s)
    return SiteOut.model_validate(s)


@router.delete("/sites/{site_id}")
async def delete_site(site_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    s = await db.get(Site, site_id)
    if s is None:
        raise HTTPException(status_code=404, detail="site not found")
    await db.delete(s)
    await db.commit()
    return {"ok": True}
