from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import httpx
import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class Detection:
    class_id: int
    name: str
    confidence: float
    # Normalized 0..1 against the submitted image
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2.0

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2.0

    def to_dict(self) -> dict:
        return {
            "class_id": self.class_id,
            "name": self.name,
            "confidence": self.confidence,
            "x1": self.x1,
            "y1": self.y1,
            "x2": self.x2,
            "y2": self.y2,
        }


def _encode_jpeg(frame_bgr: np.ndarray, quality: int = 85) -> bytes:
    ok, buf = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return buf.tobytes()


async def detect(
    client: httpx.AsyncClient,
    frame_bgr: np.ndarray,
    *,
    conf: float | None = None,
    timeout: float = 10.0,
) -> list[Detection]:
    """POST a frame to the remote D-FINE-L service, return normalized detections."""
    h, w = frame_bgr.shape[:2]
    jpeg = _encode_jpeg(frame_bgr)
    files = {"file": ("frame.jpg", jpeg, "image/jpeg")}
    headers = {"X-API-Key": settings.dfine_api_key}
    params = {"conf": conf if conf is not None else settings.dfine_default_conf}

    resp = await client.post(
        settings.dfine_url,
        params=params,
        headers=headers,
        files=files,
        timeout=timeout,
    )
    resp.raise_for_status()
    raw = resp.json()

    detections: list[Detection] = []
    for item in raw:
        box = item.get("box") or {}
        x1, y1 = float(box.get("x1", 0)), float(box.get("y1", 0))
        x2, y2 = float(box.get("x2", 0)), float(box.get("y2", 0))
        # Server returns pixel coords; normalize to 0..1 against submitted image.
        detections.append(
            Detection(
                class_id=int(item.get("class", 0)),
                name=str(item.get("name", "")),
                confidence=float(item.get("confidence", 0.0)),
                x1=max(0.0, min(1.0, x1 / w)),
                y1=max(0.0, min(1.0, y1 / h)),
                x2=max(0.0, min(1.0, x2 / w)),
                y2=max(0.0, min(1.0, y2 / h)),
            )
        )
    return detections
