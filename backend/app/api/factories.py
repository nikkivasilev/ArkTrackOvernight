from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Factory
from app.schemas import FactoryCreate, FactoryOut, FactoryUpdate

router = APIRouter()


@router.post("", response_model=FactoryOut)
async def create_factory(payload: FactoryCreate, db: AsyncSession = Depends(get_db)) -> FactoryOut:
    f = Factory(name=payload.name, address=payload.address)
    db.add(f)
    await db.commit()
    await db.refresh(f)
    return FactoryOut.model_validate(f)


@router.get("", response_model=list[FactoryOut])
async def list_factories(db: AsyncSession = Depends(get_db)) -> list[FactoryOut]:
    q = await db.execute(select(Factory).order_by(Factory.created_at))
    return [FactoryOut.model_validate(f) for f in q.scalars().all()]


@router.get("/{factory_id}", response_model=FactoryOut)
async def get_factory(factory_id: UUID, db: AsyncSession = Depends(get_db)) -> FactoryOut:
    f = await db.get(Factory, factory_id)
    if f is None:
        raise HTTPException(status_code=404, detail="factory not found")
    return FactoryOut.model_validate(f)


@router.patch("/{factory_id}", response_model=FactoryOut)
async def update_factory(
    factory_id: UUID, payload: FactoryUpdate, db: AsyncSession = Depends(get_db)
) -> FactoryOut:
    f = await db.get(Factory, factory_id)
    if f is None:
        raise HTTPException(status_code=404, detail="factory not found")
    if payload.name is not None:
        f.name = payload.name
    if payload.address is not None:
        f.address = payload.address
    await db.commit()
    await db.refresh(f)
    return FactoryOut.model_validate(f)


@router.delete("/{factory_id}")
async def delete_factory(factory_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    f = await db.get(Factory, factory_id)
    if f is None:
        raise HTTPException(status_code=404, detail="factory not found")
    await db.delete(f)
    await db.commit()
    return {"ok": True}
