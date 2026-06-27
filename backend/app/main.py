from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import (
    cameras, control, factories, recordings, reports, rules, sites, zones,
)
from app.config import settings
from app.db import Base, engine
from app import models  # noqa: F401  register tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Phase-1 schema additions for the live pipeline. Idempotent.
        # Replace with Alembic when migration discipline is reintroduced.
        await conn.execute(text(
            "ALTER TABLE cameras "
            "ADD COLUMN IF NOT EXISTS settings JSONB NOT NULL DEFAULT '{}'::jsonb"
        ))
        # Phase-3: historical metrics read-path index. The base table is
        # created by Base.metadata.create_all above; this matches the
        # /metrics-with-since-until query shape (per-camera range scan
        # ordered by bucket_start DESC).
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_metric_samples_camera_bucket "
            "ON metric_samples (camera_id, bucket_start DESC)"
        ))
        # Phase-4 slice: per-zone exclusion flag. Existing rows default to
        # "monitored" (excluded=false). Idempotent.
        await conn.execute(text(
            "ALTER TABLE zones "
            "ADD COLUMN IF NOT EXISTS excluded BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        # Per-zone occupancy histogram per metric bucket (zone-occupancy
        # metrics). {zone_id: {count: seconds}}. Idempotent.
        await conn.execute(text(
            "ALTER TABLE metric_samples "
            "ADD COLUMN IF NOT EXISTS zone_occupancy_seconds JSONB NOT NULL DEFAULT '{}'::jsonb"
        ))
        # Per-zone activity breakdown per metric bucket (what's being done in
        # each zone). {zone_id: {activity: person-seconds}}. Idempotent.
        await conn.execute(text(
            "ALTER TABLE metric_samples "
            "ADD COLUMN IF NOT EXISTS zone_activity_seconds JSONB NOT NULL DEFAULT '{}'::jsonb"
        ))
    yield


app = FastAPI(title="ArkTrack Monitoring Platform", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(factories.router, prefix="/api/factories", tags=["factories"])
app.include_router(sites.router, prefix="/api", tags=["sites"])
app.include_router(cameras.router, prefix="/api", tags=["cameras"])
app.include_router(zones.router, prefix="/api", tags=["zones"])
app.include_router(rules.router, prefix="/api", tags=["rules"])
app.include_router(control.router, prefix="/api", tags=["control"])
app.include_router(reports.router, prefix="/api", tags=["reports"])
app.include_router(recordings.router, prefix="/api", tags=["recordings"])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
