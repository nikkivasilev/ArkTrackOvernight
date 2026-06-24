"""HTTP client for the remote YOLO inference server.

Wraps a JPEG-upload protocol over plain HTTP — the server runs the
detection model and we just send frames and parse boxes.

Public surface:
    Detection      — dataclass: (x1, y1, x2, y2, conf, cls, name)
    YoloClient
        .detect(frame, conf, max_dim, jpeg_quality) → list[Detection]
        .set_source(name)                           — switch to alternate URL
        .list_sources()                             → list[str]
        .active                                     — current source name

Multi-source: the client keeps a {name: url} map. `prod` is the canonical
primary; operators can switch to e.g. `local` mid-flight via the dashboard.

In-process detectors (e.g. `HogDetector`, `DfineDetector`) can be passed
via `local_detectors` and share the same name-space. When the active
source name belongs to a local detector, `.detect()` dispatches to it
directly and the HTTP path is bypassed.
"""

import io
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

import cv2
import numpy as np
import requests
from requests.adapters import HTTPAdapter


@dataclass
class Detection:
    x1: float
    y1: float
    x2: float
    y2: float
    conf: float
    cls: int = 0
    name: str = "person"

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2

    @property
    def w(self) -> float:
        return self.x2 - self.x1

    @property
    def h(self) -> float:
        return self.y2 - self.y1


@runtime_checkable
class LocalDetector(Protocol):
    """Shape an in-process detector must expose to plug into YoloClient
    as a non-HTTP source."""

    def detect(
        self,
        frame_bgr: np.ndarray,
        conf: float = ...,
        max_dim: Optional[int] = ...,
        jpeg_quality: Optional[int] = ...,
    ) -> list[Detection]: ...


class YoloClient:
    """HTTP client for one or more YOLO inference servers.

    Sources are configured as a `{name: url}` dict; one is `active` at a time
    and `set_source(name)` switches without re-creating the session/pool.
    Single-URL backwards-compatible: passing `base_url=...` still works and
    creates a sources dict of `{"primary": base_url}`.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: str = "",
        jpeg_quality: int = 65,
        timeout: float = 8.0,
        pool_size: int = 12,
        sources: Optional[dict[str, str]] = None,
        active: Optional[str] = None,
        local_detectors: Optional[dict[str, LocalDetector]] = None,
    ):
        # Normalize the sources dict. Backwards-compat: a bare base_url
        # becomes the single "primary" source. Empty URLs are kept (some
        # test paths build a Pipeline without ever calling YOLO).
        if sources:
            self._sources = {k: (v or "").rstrip("/") for k, v in sources.items()}
        elif base_url is not None:
            self._sources = {"primary": (base_url or "").rstrip("/")}
        else:
            raise ValueError("YoloClient needs either base_url or sources")
        # In-process detectors that share the same name-keying. Each entry
        # is a `LocalDetector` (anything with `.detect` and `.pose`). When
        # the active source name appears here, calls dispatch in-process
        # and the HTTP path is bypassed.
        self._local: dict[str, LocalDetector] = dict(local_detectors or {})
        # A name collision between HTTP and local would make dispatch ambiguous.
        collisions = set(self._sources) & set(self._local)
        if collisions:
            raise ValueError(
                f"YoloClient: source name(s) appear in both http and local: {sorted(collisions)}"
            )
        if not self._sources and not self._local:
            raise ValueError("YoloClient: at least one source name required")
        # Pick the active source. Default to first http source if not specified;
        # otherwise the first local detector.
        all_names = list(self._sources) + list(self._local)
        if active and active in all_names:
            self._active = active
        else:
            self._active = all_names[0]
        # HTTP keep-alive ON via a persistent Session + bounded connection pool.
        # The YOLO server runs uvicorn with --timeout-keep-alive 5, so idle
        # sockets are reaped server-side; we additionally call .close() on
        # shutdown to release them cleanly.
        self.session = requests.Session()
        self.session.headers["X-API-Key"] = api_key
        adapter = HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.jpeg_quality = jpeg_quality
        self.timeout = timeout

    @property
    def base(self) -> str:
        """URL of the currently active HTTP source. Raises if the active
        source is a local detector — callers should check `is_local` first."""
        if self._active in self._local:
            raise RuntimeError(
                f"active source {self._active!r} is a local detector; has no base URL"
            )
        return self._sources[self._active]

    @property
    def active(self) -> str:
        return self._active

    @property
    def is_local(self) -> bool:
        """True when the active source dispatches to an in-process detector."""
        return self._active in self._local

    def list_sources(self) -> list[str]:
        # HTTP sources first (preserves the historical order for `prod` and
        # any operator-defined alternates), then local detectors.
        return list(self._sources.keys()) + list(self._local.keys())

    def set_source(self, name: str) -> None:
        """Switch the active source. Raises KeyError on unknown name.
        Accepts either an HTTP source name or a local-detector name."""
        if name not in self._sources and name not in self._local:
            raise KeyError(
                f"unknown YOLO source {name!r}; available: {self.list_sources()}"
            )
        self._active = name

    def close(self):
        """Release pooled HTTP connections cleanly. Call on app shutdown."""
        try:
            self.session.close()
        except Exception:
            pass

    def _maybe_downscale(self, frame_bgr: np.ndarray, max_dim: Optional[int]):
        """Resize so the longer side is at most max_dim. Returns (img, scale).
        scale is the factor we shrunk by — used to scale detections back to
        the *input* frame's coordinate space.
        """
        if max_dim is None or max_dim <= 0:
            return frame_bgr, 1.0
        h, w = frame_bgr.shape[:2]
        m = max(h, w)
        if m <= max_dim:
            return frame_bgr, 1.0
        scale = max_dim / m
        new_w = int(round(w * scale))
        new_h = int(round(h * scale))
        return cv2.resize(frame_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA), scale

    def _encode(self, frame_bgr: np.ndarray, jpeg_quality: Optional[int] = None) -> bytes:
        q = jpeg_quality if jpeg_quality is not None else self.jpeg_quality
        ok, buf = cv2.imencode(
            ".jpg", frame_bgr,
            [cv2.IMWRITE_JPEG_QUALITY, q, cv2.IMWRITE_JPEG_OPTIMIZE, 1],
        )
        if not ok:
            raise RuntimeError("jpeg encode failed")
        return buf.tobytes()

    def detect(
        self,
        frame_bgr: np.ndarray,
        conf: float = 0.10,
        max_dim: Optional[int] = None,
        jpeg_quality: Optional[int] = None,
    ) -> list[Detection]:
        if self._active in self._local:
            return self._local[self._active].detect(
                frame_bgr, conf=conf, max_dim=max_dim, jpeg_quality=jpeg_quality
            )
        img, scale = self._maybe_downscale(frame_bgr, max_dim)
        jpg = self._encode(img, jpeg_quality)
        files = {"file": ("frame.jpg", io.BytesIO(jpg), "image/jpeg")}
        r = self.session.post(
            f"{self.base}/predict/image",
            params={"conf": conf},
            files=files,
            timeout=self.timeout,
        )
        r.raise_for_status()
        inv = 1.0 / scale if scale != 1.0 else 1.0
        out: list[Detection] = []
        for d in r.json():
            if d.get("name") != "person":
                continue
            b = d["box"]
            out.append(Detection(
                x1=float(b["x1"]) * inv, y1=float(b["y1"]) * inv,
                x2=float(b["x2"]) * inv, y2=float(b["y2"]) * inv,
                conf=float(d["confidence"]),
                cls=int(d.get("class", 0)),
                name=d.get("name", "person"),
            ))
        return out

    def health(self) -> dict:
        if self._active in self._local:
            return {"ok": True, "kind": "local", "source": self._active}
        r = self.session.get(f"{self.base}/health", timeout=5)
        r.raise_for_status()
        return r.json()
