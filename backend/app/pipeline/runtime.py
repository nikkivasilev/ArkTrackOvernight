"""Per-camera wrapper around the vendored ModelTesting Pipeline.

The vendored ``Pipeline.run()`` owns its own cv2.VideoCapture and pacing
loop; ArkTrackRefined already has ``frame_sampler.iter_sampled`` driving
each camera worker, so we expose ``process_frame()`` instead and let the
worker push frames in.

Phase-1 scope: keep welding/groups/zones/VLM/pose disabled (see
``_phase1_cfg``). Phase 2 flips the flags and feeds Postgres zones in via
``pipeline_zones.replace_zones``.
"""
from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urlparse, urlunparse
from uuid import UUID

import numpy as np
from shapely.geometry import Polygon

from app.config import settings
from app.pipeline.pipeline import Pipeline
from app.pipeline.pipeline_config import FrameOut, PipelineConfig
from dfine_detector import DfineDetector

logger = logging.getLogger(__name__)

# Process-wide singleton: one DfineDetector shared across all CameraPipelines.
# Without sharing, each camera spawns its own ORT session + TRT engine in GPU
# memory and a duplicate CPU thread pool — measurable ~3 ms median per-call
# regression at two cameras, plus ~65 MB of redundant GPU memory per camera.
# With sharing, two cameras queue cleanly on one CUDA stream — demand at
# 2×30 fps = 60 calls/sec is under the ~70 calls/sec capacity from the
# single-thread TRT bench.
_shared_dfine_detector: Optional[DfineDetector] = None


def _get_or_make_shared_dfine(cfg: PipelineConfig) -> Optional[DfineDetector]:
    """Lazily build (or return) the single process-wide DfineDetector.

    Returns None when D-FINE is disabled or the ONNX file is missing — the
    Pipeline then falls back to remote `prod` as before.
    """
    global _shared_dfine_detector
    if _shared_dfine_detector is not None:
        return _shared_dfine_detector
    if not cfg.dfine_enabled:
        return None
    try:
        _shared_dfine_detector = DfineDetector(
            onnx_path=cfg.dfine_onnx_path,
            input_size=cfg.dfine_input_size,
            conf_threshold=cfg.dfine_conf_threshold,
            execution_provider=cfg.dfine_execution_provider,
            max_aspect_ratio=cfg.dfine_max_aspect_ratio,
            max_box_area_frac=cfg.dfine_max_box_area_frac,
        )
        logger.info("shared dfine-l detector ready (active providers: %s)",
                    _shared_dfine_detector.active_providers)
    except (FileNotFoundError, RuntimeError) as e:
        logger.warning("shared dfine-l detector disabled: %s", e)
        _shared_dfine_detector = None
    return _shared_dfine_detector


# Process-wide singleton: one SigLIP-2 classifier (1.6 GB ONNX session) shared
# across all cameras, like the D-FINE detector. Only built when the local
# "siglip" backend is selected; the remote "qwen" backend is per-pipeline
# (cheap HTTP client) so this returns None for it.
_shared_siglip = None


def _get_or_make_shared_siglip(cfg: PipelineConfig):
    """Lazily build (or return) the process-wide SigLIP classifier, or None
    when the backend isn't 'siglip' / VLM is disabled / the ONNX is missing
    (Pipeline then builds the configured backend itself, e.g. Qwen)."""
    global _shared_siglip
    if _shared_siglip is not None:
        return _shared_siglip
    if not cfg.vlm_enabled or cfg.vlm_backend != "siglip":
        return None
    try:
        from siglip_classifier import SiglipClassifier
        _shared_siglip = SiglipClassifier(
            onnx_path=cfg.siglip_onnx_path,
            labels_path=cfg.siglip_labels_path,
            temperature=cfg.siglip_temperature,
            min_person_conf=cfg.siglip_min_person_conf,
            idle_margin=cfg.siglip_idle_margin,
            revisit_s=cfg.vlm_revisit_s,
            max_inflight=cfg.vlm_max_inflight,
            execution_provider=cfg.siglip_execution_provider,
        )
        logger.info("shared siglip classifier ready (providers: %s)",
                    _shared_siglip.active_providers)
    except (FileNotFoundError, RuntimeError, Exception) as e:
        logger.warning("shared siglip classifier disabled: %s", e)
        _shared_siglip = None
    return _shared_siglip


def _detector_base_url(full_url: str) -> str:
    """Strip a trailing /predict/image off settings.dfine_url so YoloClient
    (which appends /predict/image itself) hits the right path."""
    p = urlparse(full_url)
    path = p.path.rstrip("/")
    for suffix in ("/predict/image", "/predict/pose"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    return urlunparse(p._replace(path=path))


def _vlm_base_url(full_url: str) -> str:
    """Strip a trailing /v1 off settings.qwen_base_url so VlmClassifier
    (which appends /v1/chat/completions itself) hits the right path."""
    p = urlparse(full_url)
    path = p.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[: -len("/v1")]
    return urlunparse(p._replace(path=path))


def _phase1_cfg(target_fps: float) -> PipelineConfig:
    """Build a PipelineConfig with every Phase-2/3 feature off.

    Keeping all the dataclass fields on the default values from
    pipeline_config.PipelineConfig and only flipping the runtime gates.
    """
    cfg = PipelineConfig(
        video_path="",  # external frame source, never read
        yolo_url=_detector_base_url(settings.dfine_url),
        yolo_key=settings.dfine_api_key,
        target_fps=float(target_fps) if target_fps and target_fps > 0 else 10.0,
        conf=float(settings.dfine_default_conf),
        sahi_conf=float(settings.dfine_default_conf),
        # Phase-1: no SAHI tiling (single full-frame call per cycle keeps
        # latency predictable while we shake out the integration).
        sahi_enabled=False,
        sahi_smart=False,
        # VLM tracklet classifier ON — gives true `resting`/`sitting`
        # signals the heuristic can't distinguish from `standing`.
        vlm_enabled=True,
        vlm_url=_vlm_base_url(settings.qwen_base_url),
        vlm_model=settings.qwen_model,
        opencv_hog_enabled=False,
        # Local D-FINE-L via onnxruntime + TensorRT (session 5) — registered
        # as "dfine-l" in the YoloClient sources alongside the remote "prod".
        # The active source defaults to "dfine-l" so detection runs in-process
        # on GPU (~14 ms/frame vs ~200 ms over remote HTTP). If the ONNX file
        # is missing on disk, Pipeline.__init__ logs a warning and falls back
        # to "prod" automatically.
        dfine_enabled=True,
        dfine_execution_provider="tensorrt",
        yolo_source_active="dfine-l",
    )
    # Detect every Nth frame: at low sampling FPS (3-10) we want every frame
    # to hit the detector. ByteTrack handles association either way.
    cfg.detect_every_n = 1
    return cfg


class CameraPipeline(Pipeline):
    """Per-camera Pipeline driven from camera_worker.

    Differences from vendored Pipeline:
      * No ``run()`` invocation. ``process_frame(...)`` is called by the
        worker once per sampled frame.
      * ``_broadcast`` swallows messages locally (camera_worker reads
        state out of ``self.last_frame`` and broadcasts via the app's
        ``broadcaster`` directly). Phase 2 wires zone-breach events.
    """

    def __init__(self, camera_id: UUID, target_fps: float):
        cfg = _phase1_cfg(target_fps)
        shared = _get_or_make_shared_dfine(cfg)
        shared_vlm = _get_or_make_shared_siglip(cfg)
        super().__init__(cfg, shared_detector_dfine=shared, shared_vlm=shared_vlm)
        self.camera_id = camera_id
        # Phase 2: welding-arc + idle-group detection run unconditionally —
        # they feed the workforce metrics layer and are no longer operator
        # toggles. Zones stay off (alerting feature; Phase 4).
        self.welding_enabled = True
        self.groups_enabled = True
        self.zones_enabled = False
        # Per-camera metrics aggregator. Attached by camera_worker so the
        # /metrics route can read it via registry.get_pipeline().
        self.metrics = None
        # Excluded-zone polygons in source-frame pixel coordinates. Tracks
        # and flashes whose foot-point falls inside any of these are dropped
        # from state before metrics aggregation / WS broadcast. The worker
        # sets these at start (from DB) and on PATCH /api/zones/{id}.
        self.excluded_polys_px: list[list[tuple[float, float]]] = []
        # Cached shapely Polygons rebuilt whenever excluded_polys_px changes.
        # Used by _render_and_publish to suppress draw_* calls for detections
        # whose foot-point falls inside an excluded zone.
        self._excluded_polygons: list[Polygon] = []
        # Monitored (non-excluded) zones for occupancy metrics. Each entry is
        # (zone_id, zone_name, shapely Polygon in source-frame pixels). The
        # renderer counts visible real + phantom foot-points inside each and
        # emits per-zone counts into state["zones"]; the metrics aggregator
        # integrates those into per-zone occupancy histograms.
        self._metric_zones: list[tuple[str, str, Polygon]] = []
        # Raw normalized definitions, kept so we can re-scale once source_dim
        # arrives (mirror of _excluded_polys_norm).
        self._metric_zones_norm: list[dict] = []

    async def _broadcast(self, event: dict) -> None:  # type: ignore[override]
        # Phase 1: pipeline events stay local; camera_worker assembles
        # the WS message from `self.last_frame.state` and pushes through
        # the existing app broadcaster.
        return

    async def process_frame(
        self,
        frame: np.ndarray,
        frame_idx: int,
        t_video: float,
    ) -> Optional[FrameOut]:
        """Run one cycle of the vendored pipeline on a caller-supplied frame.

        Mirrors the body of vendored Pipeline.run()'s loop, minus
        cv2.VideoCapture management and target-fps pacing (the camera worker
        already paces via frame_sampler).
        """
        if not self.running:
            return self.last_frame

        if self.source_dim is None:
            self.source_dim = (int(frame.shape[1]), int(frame.shape[0]))

        flashes, flash_mask = self._detect_flashes(frame, t_video)

        tracked, dets, ran_yolo = await self._detect_and_track(
            frame, t_video, frame_idx,
        )

        seen_ids = self._update_track_histories(tracked, frame, ran_yolo, t_video)
        self._drop_stale_tracks(t_video)

        self._capture_tracklets(frame, t_video, seen_ids)
        self._maybe_fire_vlm(t_video)

        welding_ids, orphan_flashes, visible_phantom_ids = (
            self._attribute_welding_and_phantoms(flashes, t_video)
        )

        self._decide_activities(seen_ids, welding_ids, t_video)

        if self.groups_enabled:
            self._groups = self.group_detector.step(self.tracks, t_video)
        else:
            self._groups = []

        if self.zones_enabled:
            self._zone_evals = await self._step_zones(
                seen_ids, visible_phantom_ids, t_video,
            )
        else:
            self._zone_evals = []

        await self._render_and_publish(
            frame, frame_idx, t_video, tracked, dets, ran_yolo,
            seen_ids, flashes, orphan_flashes, visible_phantom_ids,
        )
        return self.last_frame

    def set_excluded_zones(self, polys_normalized: list[list[list[float]]]) -> None:
        """Replace the excluded-zone polygons. Input is normalized 0..1 coords
        (the Postgres storage shape); we scale them into source-frame pixels
        using ``self.source_dim`` so the per-frame filter can do a direct
        point-in-polygon check against bbox/flash centroids.

        Called when zones change (PATCH /api/zones/{id}) and at worker start.
        Safe to call before the first frame — ``source_dim`` will be filled
        in later and the worker re-pushes zones once dimensions are known.
        """
        if self.source_dim is None:
            # No frame seen yet; the worker re-applies after probing.
            self.excluded_polys_px = []
            self._excluded_polygons = []
            self._excluded_polys_norm = polys_normalized
            return
        w, h = self.source_dim
        out: list[list[tuple[float, float]]] = []
        for poly in polys_normalized:
            pts: list[tuple[float, float]] = []
            for p in poly:
                if len(p) >= 2:
                    pts.append((float(p[0]) * w, float(p[1]) * h))
            if len(pts) >= 3:
                out.append(pts)
        self.excluded_polys_px = out
        self._excluded_polygons = [Polygon(pts) for pts in out]
        self._excluded_polys_norm = polys_normalized

    def set_metric_zones(self, zones: list[dict]) -> None:
        """Replace the monitored-zone set used for occupancy metrics.

        ``zones`` is a list of {"id", "name", "polygon"} where polygon is
        normalized 0..1 coords (Postgres storage shape). Scaled to source-frame
        pixels via ``self.source_dim`` so the renderer can foot-point test
        against them. Like set_excluded_zones, safe to call before the first
        frame — the worker re-pushes once source_dim is known.
        """
        self._metric_zones_norm = zones
        if self.source_dim is None:
            self._metric_zones = []
            return
        w, h = self.source_dim
        built: list[tuple[str, str, Polygon]] = []
        for z in zones:
            pts = [
                (float(p[0]) * w, float(p[1]) * h)
                for p in (z.get("polygon") or [])
                if len(p) >= 2
            ]
            if len(pts) >= 3:
                built.append((str(z.get("id")), str(z.get("name") or ""), Polygon(pts)))
        self._metric_zones = built

    def close(self) -> None:
        self.stop()
        try:
            self.yolo.close()
        except Exception:
            pass
