from __future__ import annotations

from pathlib import Path
from uuid import UUID

import cv2
import numpy as np

from app.config import settings


def upload_path(camera_id: UUID, filename: str) -> Path:
    suffix = Path(filename).suffix or ".mp4"
    return settings.data_dir / "uploads" / f"{camera_id}{suffix}"


def alert_thumbnail_path(alert_id: UUID) -> Path:
    return settings.data_dir / "alerts" / f"{alert_id}.jpg"


def alert_clip_path(alert_id: UUID) -> Path:
    return settings.data_dir / "alerts" / f"{alert_id}.webm"


def save_thumbnail(frame_bgr: np.ndarray, path: Path, quality: int = 85) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
