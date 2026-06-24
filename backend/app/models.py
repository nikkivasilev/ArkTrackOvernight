import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class CameraKind(str, enum.Enum):
    file = "file"
    rtsp = "rtsp"


class CameraStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class TriggerType(str, enum.Enum):
    detection = "detection"
    count_min = "count_min"
    count_max = "count_max"
    duration = "duration"
    absence = "absence"
    resting_worker = "resting_worker"


class Severity(str, enum.Enum):
    info = "info"
    warn = "warn"
    critical = "critical"


class Factory(Base):
    __tablename__ = "factories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sites: Mapped[list["Site"]] = relationship(back_populates="factory", cascade="all, delete-orphan")


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    factory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("factories.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    factory: Mapped[Factory] = relationship(back_populates="sites")
    cameras: Mapped[list["Camera"]] = relationship(back_populates="site", cascade="all, delete-orphan")


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[CameraKind] = mapped_column(Enum(CameraKind, name="camera_kind"), default=CameraKind.file)
    path_or_url: Mapped[str] = mapped_column(String(1024))
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    sampling_fps: Mapped[float] = mapped_column(Float, default=3.0)
    status: Mapped[CameraStatus] = mapped_column(
        Enum(CameraStatus, name="camera_status"), default=CameraStatus.queued
    )
    last_processed_frame_idx: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    site: Mapped[Site] = relationship(back_populates="cameras")
    zones: Mapped[list["Zone"]] = relationship(back_populates="camera", cascade="all, delete-orphan")
    rules: Mapped[list["Rule"]] = relationship(
        back_populates="camera",
        cascade="all, delete-orphan",
        foreign_keys="Rule.camera_id",
    )
    alerts: Mapped[list["Alert"]] = relationship(back_populates="camera", cascade="all, delete-orphan")


class Zone(Base):
    __tablename__ = "zones"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    polygon: Mapped[list] = mapped_column(JSONB)
    # When True, tracks / flashes whose foot-point falls inside the polygon
    # are dropped before metrics aggregation and WS broadcast. Used for
    # too-far / unreliable regions of the frame.
    excluded: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    camera: Mapped[Camera] = relationship(back_populates="zones")
    rules: Mapped[list["Rule"]] = relationship(
        back_populates="zone",
        cascade="all, delete-orphan",
        foreign_keys="Rule.zone_id",
    )


class Rule(Base):
    __tablename__ = "rules"
    __table_args__ = (
        CheckConstraint(
            "(camera_id IS NOT NULL)::int + (zone_id IS NOT NULL)::int = 1",
            name="rule_exactly_one_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    trigger_type: Mapped[TriggerType] = mapped_column(
        Enum(TriggerType, name="trigger_type"), default=TriggerType.detection
    )
    severity: Mapped[Severity] = mapped_column(Enum(Severity, name="severity"), default=Severity.warn)
    camera_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="CASCADE"), nullable=True, index=True
    )
    zone_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zones.id", ondelete="CASCADE"), nullable=True, index=True
    )
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    camera: Mapped[Camera | None] = relationship(back_populates="rules", foreign_keys=[camera_id])
    zone: Mapped[Zone | None] = relationship(back_populates="rules", foreign_keys=[zone_id])
    alerts: Mapped[list["Alert"]] = relationship(back_populates="rule", cascade="all, delete-orphan")


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rules.id", ondelete="CASCADE"), index=True
    )
    zone_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zones.id", ondelete="SET NULL"), nullable=True
    )
    severity: Mapped[Severity] = mapped_column(Enum(Severity, name="severity"), default=Severity.warn)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    start_timestamp_in_video: Mapped[float] = mapped_column(Float)
    end_timestamp_in_video: Mapped[float | None] = mapped_column(Float, nullable=True)
    wall_clock_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    thumbnail_path: Mapped[str] = mapped_column(String(1024))
    # Optional video clip on disk (resting-worker events). Null for alerts that
    # only captured a single thumbnail frame.
    clip_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    detection_box: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    camera: Mapped[Camera] = relationship(back_populates="alerts")
    rule: Mapped[Rule] = relationship(back_populates="alerts")


class ProcessedRecording(Base):
    """Ledger of recorded files the offline overnight batch has crunched.

    One row per source file. Makes the folder-watcher / batch ingest
    idempotent: a file already present (by ``path``) is skipped instead of
    reprocessed. Also records the parsed wall-clock span and run stats so the
    day-summary report knows which footage backs each camera-day.
    """
    __tablename__ = "processed_recordings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="CASCADE"), index=True
    )
    # Absolute source path of the recording — natural dedupe key.
    path: Mapped[str] = mapped_column(String(1024), unique=True)
    filename: Mapped[str] = mapped_column(String(512))
    # Real wall-clock span parsed from the NVR filename (UTC). recorded_start
    # is the anchor passed to the offline runner as wall_clock_origin.
    recorded_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    recorded_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    frames: Mapped[int] = mapped_column(Integer, default=0)
    footage_s: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32), default="done")
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MetricSample(Base):
    """One 10-second bucket of workforce metrics for a camera.

    Flushed periodically from the in-memory ``MetricsAggregator`` so the
    Analysis panel can answer historical windows that survive camera stop
    / restart. Unique (camera_id, bucket_start) makes flushes idempotent.
    """
    __tablename__ = "metric_samples"
    __table_args__ = (
        UniqueConstraint("camera_id", "bucket_start", name="uq_metric_samples_cam_bucket"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="CASCADE"), index=True
    )
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_s: Mapped[float] = mapped_column(Float)
    worker_seconds: Mapped[float] = mapped_column(Float)
    frames: Mapped[int] = mapped_column(Integer)
    peak_headcount: Mapped[int] = mapped_column(Integer)
    avg_headcount: Mapped[float] = mapped_column(Float)
    activity_seconds: Mapped[dict] = mapped_column(JSONB, default=dict)
    rollup_seconds: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Per-zone occupancy histogram for this bucket: {zone_id: {count: seconds}}.
    # JSON keys are strings (zone uuid, occupancy count). Every threshold query
    # (understaffed < N, overstaffed > M, avg, peak, utilization) derives from
    # this — no threshold is baked in at capture time.
    zone_occupancy_seconds: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Per-zone activity breakdown for this bucket: {zone_id: {activity:
    # person-seconds}}. Worker-weighted; "what was being done in each zone".
    # The pct breakdown is derived at read time.
    zone_activity_seconds: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
