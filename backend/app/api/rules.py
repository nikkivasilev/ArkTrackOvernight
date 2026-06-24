from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Camera, Rule, Severity, TriggerType, Zone
from app.schemas import (
    VALID_SEVERITIES,
    VALID_TRIGGER_TYPES,
    ZONE_INCOMPATIBLE_TRIGGERS,
    RuleCreate,
    RuleOut,
    RuleUpdate,
)

router = APIRouter()


def _validate_create(payload: RuleCreate, scope: str) -> None:
    if payload.trigger_type not in VALID_TRIGGER_TYPES:
        raise HTTPException(status_code=400, detail=f"invalid trigger_type: {payload.trigger_type}")
    if payload.severity not in VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"invalid severity: {payload.severity}")
    if scope == "zone" and payload.trigger_type in ZONE_INCOMPATIBLE_TRIGGERS:
        raise HTTPException(
            status_code=400,
            detail=f"trigger_type {payload.trigger_type} is camera-scope only",
        )


@router.post("/cameras/{camera_id}/rules", response_model=RuleOut)
async def create_camera_rule(
    camera_id: UUID, payload: RuleCreate, db: AsyncSession = Depends(get_db)
) -> RuleOut:
    cam = await db.get(Camera, camera_id)
    if cam is None:
        raise HTTPException(status_code=404, detail="camera not found")
    _validate_create(payload, scope="camera")
    rule = Rule(
        name=payload.name,
        trigger_type=TriggerType(payload.trigger_type),
        severity=Severity(payload.severity),
        camera_id=camera_id,
        zone_id=None,
        params=payload.params,
        enabled=payload.enabled,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return RuleOut.model_validate(rule)


@router.post("/zones/{zone_id}/rules", response_model=RuleOut)
async def create_zone_rule(
    zone_id: UUID, payload: RuleCreate, db: AsyncSession = Depends(get_db)
) -> RuleOut:
    zone = await db.get(Zone, zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail="zone not found")
    _validate_create(payload, scope="zone")
    rule = Rule(
        name=payload.name,
        trigger_type=TriggerType(payload.trigger_type),
        severity=Severity(payload.severity),
        camera_id=None,
        zone_id=zone_id,
        params=payload.params,
        enabled=payload.enabled,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return RuleOut.model_validate(rule)


@router.get("/cameras/{camera_id}/rules", response_model=list[RuleOut])
async def list_rules_for_camera(
    camera_id: UUID, db: AsyncSession = Depends(get_db)
) -> list[RuleOut]:
    zone_ids_q = await db.execute(select(Zone.id).where(Zone.camera_id == camera_id))
    zone_ids = [row[0] for row in zone_ids_q.all()]

    stmt = select(Rule).where(
        or_(
            Rule.camera_id == camera_id,
            Rule.zone_id.in_(zone_ids) if zone_ids else False,
        )
    ).order_by(Rule.created_at)
    q = await db.execute(stmt)
    return [RuleOut.model_validate(r) for r in q.scalars().all()]


@router.patch("/rules/{rule_id}", response_model=RuleOut)
async def update_rule(
    rule_id: UUID, payload: RuleUpdate, db: AsyncSession = Depends(get_db)
) -> RuleOut:
    rule = await db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")
    if payload.name is not None:
        rule.name = payload.name
    if payload.severity is not None:
        if payload.severity not in VALID_SEVERITIES:
            raise HTTPException(status_code=400, detail=f"invalid severity: {payload.severity}")
        rule.severity = Severity(payload.severity)
    if payload.params is not None:
        rule.params = payload.params
    if payload.enabled is not None:
        rule.enabled = payload.enabled
    await db.commit()
    await db.refresh(rule)
    return RuleOut.model_validate(rule)


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    rule = await db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")
    await db.delete(rule)
    await db.commit()
    return {"ok": True}
