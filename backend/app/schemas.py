from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field


# ---------- Factory ----------

class FactoryCreate(BaseModel):
    name: str
    address: str | None = None


class FactoryUpdate(BaseModel):
    name: str | None = None
    address: str | None = None


class FactoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    address: str | None
    created_at: datetime


# ---------- Site ----------

class SiteCreate(BaseModel):
    name: str
    address: str | None = None


class SiteUpdate(BaseModel):
    name: str | None = None
    address: str | None = None


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    factory_id: UUID
    name: str
    address: str | None
    created_at: datetime


# ---------- Camera ----------

class CameraOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    site_id: UUID
    name: str
    kind: str
    path_or_url: str
    duration_s: float | None
    sampling_fps: float
    status: str
    last_processed_frame_idx: int
    error: str | None
    created_at: datetime


# ---------- Zone ----------

class ZoneCreate(BaseModel):
    name: str
    polygon: list[list[float]] = Field(..., description="[[x, y], ...] normalized 0..1")
    excluded: bool = False


class ZoneUpdate(BaseModel):
    name: str | None = None
    excluded: bool | None = None


class ZoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    camera_id: UUID
    name: str
    polygon: list[list[float]]
    excluded: bool
    created_at: datetime


# ---------- Rule ----------

VALID_TRIGGER_TYPES = {
    "detection", "count_min", "count_max", "duration", "absence", "resting_worker",
}
ZONE_INCOMPATIBLE_TRIGGERS = {"resting_worker"}
VALID_SEVERITIES = {"info", "warn", "critical"}


class RuleCreate(BaseModel):
    name: str
    trigger_type: str
    severity: str = "warn"
    params: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class RuleUpdate(BaseModel):
    name: str | None = None
    severity: str | None = None
    params: dict[str, Any] | None = None
    enabled: bool | None = None


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    trigger_type: str
    severity: str
    camera_id: UUID | None
    zone_id: UUID | None
    params: dict[str, Any]
    enabled: bool
    created_at: datetime


# ---------- Alert ----------

class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    camera_id: UUID
    rule_id: UUID
    zone_id: UUID | None
    severity: str
    acknowledged: bool
    acknowledged_at: datetime | None
    start_timestamp_in_video: float
    end_timestamp_in_video: float | None
    wall_clock_at: datetime | None
    detection_box: dict[str, float] | None
    confidence: float | None
    created_at: datetime
    # Read from the ORM but not serialized; surfaced as the `has_clip` flag so
    # the frontend knows to show a video player without leaking the FS path.
    clip_path: str | None = Field(default=None, exclude=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_clip(self) -> bool:
        return bool(self.clip_path)


# ---------- Offline reports ----------

class CameraDayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    camera_id: str
    name: str
    summary: dict[str, Any]
    zone_names: dict[str, str]
    recordings: int
    footage_s: float


class PeriodSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    factory_id: str
    factory_name: str
    period: str
    start: date
    end: date
    tz: str
    generated_at: datetime
    start_utc: datetime
    end_utc: datetime
    factory_summary: dict[str, Any]
    timeline: list[dict[str, Any]]
    timeline_kind: str
    cameras: list[CameraDayOut]
    zone_names: dict[str, str]
    total_recordings: int
    total_footage_s: float


# ---------- Processed recordings (offline ledger) ----------

class ProcessedRecordingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    camera_id: UUID
    camera_name: str | None = None
    path: str
    filename: str
    recorded_start: datetime
    recorded_end: datetime | None
    frames: int
    footage_s: float
    status: str
    error: str | None
    processed_at: datetime | None
    created_at: datetime
    file_exists: bool = False
