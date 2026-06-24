"""Pipeline orchestrator — main run-loop, per-frame state, lifecycle.

The bulk of per-feature code lives in mixins so this file stays focused
on lifecycle: __init__, subscribe / broadcast, the `run()` loop, and a
few small shared state-mutation helpers used by `run()`.

Mixin layout (alphabetical):
    pipeline_detection.py  — D-FINE + ByteTrack + flash + welding
    pipeline_render.py     — annotated frame + state broadcast
    pipeline_tuning.py     — live operator tuning + presets
    pipeline_vlm.py        — VLM dispatch + tracklets
    pipeline_zones.py      — zone CRUD + per-frame zone evaluation

Backward-compat re-exports: `Pipeline`, `PipelineConfig`, `DETECTOR_REGISTRY`,
`BUILT_IN_PRESETS`, `FrameOut`. main.py + tests rely on these names.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any, Optional

import cv2
import numpy as np
import supervision as sv

from activity import (
    FlashDetector,
    PhantomTracker,
    TrackHistory,
    classify_motion,
)
from dfine_detector import DfineDetector
from group_detector import Group, GroupDetector
from hog_detector import HogDetector
from id_recovery import IdRecovery

# Re-exports — preserve existing `from pipeline import X` callsites.
from pipeline_config import (  # noqa: F401
    BUILT_IN_PRESETS,
    DETECTOR_REGISTRY,
    FrameOut,
    PipelineConfig,
    _param_value_type,
)
from pipeline_detection import _DetectionMixin
from pipeline_render import _RenderMixin
from pipeline_tuning import _TuningMixin
from pipeline_vlm import _VlmMixin, _VlmRuntimeState
from pipeline_zones import _ZonesMixin
from vlm_classifier import VlmClassifier
from yolo_client import YoloClient
from zone_detector import ZoneDetector, ZoneEval

logger = logging.getLogger(__name__)


class Pipeline(
    _TuningMixin,
    _ZonesMixin,
    _DetectionMixin,
    _VlmMixin,
    _RenderMixin,
):
    def __init__(
        self,
        cfg: PipelineConfig,
        shared_detector_dfine: Optional[DfineDetector] = None,
        shared_vlm: Optional[object] = None,
    ):
        self.cfg = cfg
        # Build source map. `prod` is the canonical primary URL; any extras
        # come from cfg.yolo_sources_extra. Active source defaults to `prod`
        # but can be overridden up-front via cfg.yolo_source_active.
        sources = {"prod": cfg.yolo_url, **(cfg.yolo_sources_extra or {})}
        # Optional in-process OpenCV-HOG detector, registered as a switchable
        # source alongside the remote YOLO. Held as `self.detector_hog` so the
        # tuning registry can mutate its params live.
        self.detector_hog: Optional[HogDetector] = None
        # Optional in-process D-FINE-L (Objects365 + COCO) detector. Apache-2.0,
        # via onnxruntime. Gated by `dfine_enabled` AND the ONNX file being
        # present on disk. Missing file → log + skip (pipeline boots anyway).
        # If `shared_detector_dfine` is provided (runtime path, one per
        # process), reuse it instead of constructing a new ORT session +
        # TRT engine per camera.
        self.detector_dfine: Optional[DfineDetector] = None
        local_detectors: dict = {}
        if cfg.opencv_hog_enabled:
            self.detector_hog = HogDetector(
                max_dim=cfg.hog_max_dim,
                scale=cfg.hog_scale,
                hit_threshold=cfg.hog_hit_threshold,
                win_stride=cfg.hog_win_stride,
                nms_iou=cfg.hog_nms_iou,
            )
            local_detectors["opencv-hog"] = self.detector_hog
        if shared_detector_dfine is not None:
            self.detector_dfine = shared_detector_dfine
            local_detectors["dfine-l"] = self.detector_dfine
        elif cfg.dfine_enabled:
            try:
                self.detector_dfine = DfineDetector(
                    onnx_path=cfg.dfine_onnx_path,
                    input_size=cfg.dfine_input_size,
                    conf_threshold=cfg.dfine_conf_threshold,
                    execution_provider=cfg.dfine_execution_provider,
                    max_aspect_ratio=cfg.dfine_max_aspect_ratio,
                    max_box_area_frac=cfg.dfine_max_box_area_frac,
                )
                local_detectors["dfine-l"] = self.detector_dfine
            except (FileNotFoundError, RuntimeError) as e:
                logger.warning(
                    "dfine-l source disabled: %s "
                    "(run tools/download_models to fetch the D-FINE ONNX file)", e
                )
        all_source_names = list(sources) + list(local_detectors)
        requested_active = cfg.yolo_source_active
        active = requested_active if requested_active in all_source_names else "prod"
        if active != requested_active:
            logger.warning(
                "requested active source %r not registered (likely missing model file); "
                "falling back to %r", requested_active, active,
            )
        logger.info(
            "detector active source: %s (available: %s)", active, all_source_names,
        )
        self.yolo = YoloClient(
            sources=sources,
            active=active,
            api_key=cfg.yolo_key,
            local_detectors=local_detectors or None,
        )
        self.tracker = sv.ByteTrack(
            track_activation_threshold=0.08,
            lost_track_buffer=120,            # ~6 s at 20 fps
            minimum_matching_threshold=0.40,  # lenient association
            frame_rate=int(cfg.target_fps),
            minimum_consecutive_frames=1,     # no warmup — recovery layer handles spurious tracks
        )
        self.id_recovery = IdRecovery(
            pos_threshold=300.0,
            time_threshold=10.0,
            hist_weight=0.6,
        )
        self.flash = FlashDetector()
        self.phantom_tracker = PhantomTracker(grace_s=6.0, merge_dist=350.0, min_age_s=1.0)
        # Idle-group detector — clusters non-working workers standing close together.
        self.group_detector = GroupDetector()
        self._groups: list[Group] = []
        # Zone-rule detector — operator-configured camera regions with attached
        # rules ("≥ 3 in welding row", "no one in machine area", etc).
        self.zone_detector = ZoneDetector()
        self._zone_evals: list[ZoneEval] = []
        # VLM activity classifier. Backend selected by cfg.vlm_backend; both
        # the local SigLIP-2 and the remote Qwen satisfy the same seam. A
        # shared instance (the heavy SigLIP ONNX session) is injected by the
        # runtime; otherwise build per-pipeline (tests / standalone).
        self.vlm = None
        if shared_vlm is not None:
            self.vlm = shared_vlm
        elif cfg.vlm_enabled:
            if cfg.vlm_backend == "siglip":
                from siglip_classifier import SiglipClassifier
                self.vlm = SiglipClassifier(
                    onnx_path=cfg.siglip_onnx_path,
                    labels_path=cfg.siglip_labels_path,
                    temperature=cfg.siglip_temperature,
                    min_person_conf=cfg.siglip_min_person_conf,
                    idle_margin=cfg.siglip_idle_margin,
                    revisit_s=cfg.vlm_revisit_s,
                    max_inflight=cfg.vlm_max_inflight,
                    execution_provider=cfg.siglip_execution_provider,
                )
            else:
                self.vlm = VlmClassifier(
                    base_url=cfg.vlm_url,
                    model=cfg.vlm_model,
                    revisit_s=cfg.vlm_revisit_s,
                    max_inflight=cfg.vlm_max_inflight,
                )
        self.vlm_enabled_runtime: bool = cfg.vlm_enabled and self.vlm is not None
        # Per-track tracklet buffers + VLM dispatch dedup. See pipeline_vlm.
        self.vlm_state = _VlmRuntimeState()
        self.tracks: dict[int, TrackHistory] = {}
        self.last_frame: Optional[FrameOut] = None
        # JPEG of the most recent rendered display frame WITHOUT zone overlays.
        # Used by the zone editor as a clean canvas. None when no zones are
        # configured (regular snapshot is already clean).
        self._last_jpeg_no_zones: Optional[bytes] = None
        # Source-frame dimensions, captured once on the first successful read.
        # The zone editor needs these to translate SVG click coords ↔ canonical
        # pipeline coords. None until the first frame.
        self.source_dim: Optional[tuple[int, int]] = None  # (w, h)
        self.frame_event = asyncio.Event()
        self.event_subscribers: list[asyncio.Queue] = []
        self._stopping = False
        # Whether the pipeline is actively processing. When False, the main
        # loop yields without doing any work — no frame reads, no YOLO calls,
        # no tracker updates. The last rendered frame stays on screen.
        self.running: bool = True
        self._running_event = asyncio.Event()
        self._running_event.set()
        # Per-module runtime toggles. The master `running` flag pauses
        # everything; these flags pause individual subsystems while the loop
        # keeps producing frames + the rest of the modules keep running.
        self.yolo_enabled: bool = True
        self.welding_enabled: bool = True
        # NB: self.vlm_enabled_runtime was set above (right after self.vlm).
        # Drawing overlay (bboxes, labels, arc markers, HUD) on the MJPEG stream.
        # When False, the stream shows the raw frame; sidebar/timeline still update
        # because we keep the per-track bookkeeping running.
        self.overlay_enabled: bool = True
        # Idle-group detector: gates the per-frame GroupDetector.step() call.
        self.groups_enabled: bool = True
        # Zone detector: gates the per-frame ZoneDetector.step() call.
        # When False (or no zones configured), no overhead.
        self.zones_enabled: bool = True

        self._yolo_ms_ema = 0.0
        self._src_fps_ema = 0.0
        self._last_wall = time.time()
        # Smart-SAHI bookkeeping: t_video of the last grid pass. Used to force
        # a periodic grid refresh even on quiet scenes so stationary distant
        # workers don't fall out of the tracker.
        self._last_grid_pass_t: float = 0.0
        self._last_tracked: Optional[sv.Detections] = None
        self._last_iid_to_pid: dict[int, int] = {}
        # Optional persist hook. main.py wires this at startup so user-flipped
        # module flags + welding params survive a hard crash, not just graceful
        # shutdown. Pipeline calls it (best-effort, swallowing errors) after
        # every set_modules / set_welding_params.
        self._persist_cb: Optional[Callable[[], None]] = None
        # User-saved detector-param presets. Restored from disk by main.lifespan.
        self._user_presets: dict[str, dict] = {}
        # Optional event journal — persists zone.breach.* events for the
        # /events/history endpoint. Wired by main.lifespan after construction.
        # Pipeline core only knows the protocol-shaped duck (anything with a
        # .record(event) method) so importing event_journal stays optional.
        self.journal: Optional[Any] = None

    # ------------------------------------------------------------------
    # Subscribe / broadcast
    # ------------------------------------------------------------------

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self.event_subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        try:
            self.event_subscribers.remove(q)
        except ValueError:
            pass

    async def _broadcast(self, event: dict):
        # Persist zone.breach.* events first — best-effort, never blocks the
        # broadcast on disk failure. The journal itself filters by type, but
        # we short-circuit here to avoid even calling it on the >99% of events
        # that aren't zone breaches (most messages are 'state' at ~20 Hz).
        if self.journal is not None and event.get("type", "").startswith("zone.breach."):
            try:
                self.journal.record(event)
            except Exception as e:
                logger.warning("journal record failed: %s", e)
        for q in list(self.event_subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    # ------------------------------------------------------------------
    # Module + source state
    # ------------------------------------------------------------------

    async def set_running(self, running: bool) -> bool:
        """Toggle pipeline activity. Returns the new state."""
        running = bool(running)
        if running == self.running:
            return self.running
        self.running = running
        if running:
            # Reset wall-clock so FPS doesn't show a huge gap on resume
            self._last_wall = time.time()
            self._running_event.set()
        else:
            self._running_event.clear()
        await self._broadcast({"type": "running", "running": running})
        return self.running

    def get_module_state(self) -> dict:
        return {
            "running": self.running,
            "yolo_enabled": self.yolo_enabled,
            "welding_enabled": self.welding_enabled,
            "vlm_enabled": self.vlm_enabled_runtime,
            "overlay_enabled": self.overlay_enabled,
            "groups_enabled": self.groups_enabled,
            "zones_enabled": self.zones_enabled,
            "yolo_source": self.yolo.active,
            "yolo_sources": self.yolo.list_sources(),
        }

    async def set_yolo_source(self, name: str) -> str:
        """Switch the active YOLO inference source. Returns the new active
        name. Raises KeyError if unknown."""
        self.yolo.set_source(name)
        # Tell every connected client so all open dashboards reflect the
        # change immediately.
        await self._broadcast({"type": "modules", "modules": self.get_module_state()})
        # Persist immediately so the choice survives a restart.
        if self._persist_cb is not None:
            try:
                self._persist_cb()
            except Exception as e:
                logger.warning("persist after yolo_source change: %s", e)
        return self.yolo.active

    def _persist_safe(self):
        """Best-effort call to the persist hook (swallows errors)."""
        cb = self._persist_cb
        if cb is None:
            return
        try:
            cb()
        except Exception as e:
            logger.warning("persist callback failed: %s", e)

    async def set_modules(
        self, *,
        yolo_enabled=None, welding_enabled=None, vlm_enabled=None,
        overlay_enabled=None, groups_enabled=None, zones_enabled=None,
    ) -> dict:
        """Update any subset of per-module flags. Broadcasts the new state."""
        if yolo_enabled is not None:
            self.yolo_enabled = bool(yolo_enabled)
        if welding_enabled is not None:
            self.welding_enabled = bool(welding_enabled)
        if vlm_enabled is not None:
            self.vlm_enabled_runtime = bool(vlm_enabled) and self.vlm is not None
            if self.vlm is not None:
                self.vlm.set_enabled(self.vlm_enabled_runtime)
        if overlay_enabled is not None:
            self.overlay_enabled = bool(overlay_enabled)
        if groups_enabled is not None:
            self.groups_enabled = bool(groups_enabled)
            if not self.groups_enabled:
                # Clear in-progress candidates so re-enabling doesn't spuriously
                # promote stale clusters from before the toggle.
                self.group_detector._candidates.clear()
                self._groups = []
        if zones_enabled is not None:
            self.zones_enabled = bool(zones_enabled)
            if not self.zones_enabled:
                self._zone_evals = []
        state = self.get_module_state()
        await self._broadcast({"type": "modules", "modules": state})
        self._persist_safe()
        return state

    # ------------------------------------------------------------------
    # Per-frame state mutators used by run()
    # ------------------------------------------------------------------

    def _update_track_histories(
        self,
        tracked: sv.Detections,
        frame: np.ndarray,
        ran_yolo: bool,
        t_video: float,
    ) -> set[int]:
        """For each tracked object this frame: append position, refresh last_bbox /
        last_seen_t. Returns the set of public ids seen this frame."""
        seen_ids: set[int] = set()
        if len(tracked) == 0:
            return seen_ids
        # supervision types tracker_id as Optional[ndarray] but it's always
        # populated when len(tracked) > 0, which we just checked.
        assert tracked.tracker_id is not None
        for i in range(len(tracked)):
            iid = int(tracked.tracker_id[i])
            tid = self._last_iid_to_pid.get(iid, iid)
            seen_ids.add(tid)
            x1, y1, x2, y2 = tracked.xyxy[i]
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            hist = self.tracks.get(tid)
            if hist is None:
                hist = TrackHistory(track_id=tid)
                self.tracks[tid] = hist
            hist.positions.append((t_video, float(cx), float(cy)))
            hist.last_bbox = (int(x1), int(y1), int(x2), int(y2))
            hist.last_seen_t = t_video
            if ran_yolo:
                hist.last_seen_real_t = t_video
        return seen_ids

    def _drop_stale_tracks(self, t_video: float):
        """Remove tracks unseen for >15s (ghost window is 10s)."""
        stale = [tid for tid, h in self.tracks.items()
                 if (t_video - h.last_seen_t) > 15.0]
        for tid in stale:
            self.tracks.pop(tid, None)
            self.vlm_state.tracklets.pop(tid, None)

    def _decide_activities(
        self,
        seen_ids: set[int],
        welding_ids: set[int],
        t_video: float,
    ):
        """Pick a heuristic activity per visible track, append to its timeline."""
        for tid in seen_ids:
            hist = self.tracks[tid]
            if tid in welding_ids:
                hist.activity = "welding"
                hist.activity_conf = 0.9
            else:
                label, conf = classify_motion(hist, t_video)
                hist.activity = label
                hist.activity_conf = conf
            if not hist.timeline or hist.timeline[-1][1] != hist.activity:
                hist.timeline.append((t_video, hist.activity))

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self):
        """Main per-frame loop. Each phase delegates to a helper; this method
        is the orchestrator only — read it top-to-bottom to understand the cycle.
        """
        cap = cv2.VideoCapture(self.cfg.video_path)
        if not cap.isOpened():
            raise RuntimeError(f"cannot open video {self.cfg.video_path}")
        target_dt = 1.0 / self.cfg.target_fps
        frame_idx = 0
        next_tick = time.time()

        while not self._stopping:
            # Pause: cheap wait until resume signal (or stop).
            if not self.running:
                try:
                    await asyncio.wait_for(self._running_event.wait(), timeout=0.5)
                except TimeoutError:
                    pass
                next_tick = time.time()  # realign cadence so we don't burst-process
                continue

            ok, frame = cap.read()
            if not ok:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # loop the file
                continue
            if self.source_dim is None:
                self.source_dim = (int(frame.shape[1]), int(frame.shape[0]))

            t_video = frame_idx / self.cfg.target_fps
            frame_idx += 1

            # --- 1. Welding flashes (Welding module) ---
            flashes, flash_mask = self._detect_flashes(frame, t_video)

            # --- 2. D-FINE + ByteTrack + ID recovery (gated to every Nth frame) ---
            tracked, dets, ran_yolo = await self._detect_and_track(
                frame, t_video, frame_idx,
            )

            # --- 3. Track histories + stale GC ---
            seen_ids = self._update_track_histories(tracked, frame, ran_yolo, t_video)
            self._drop_stale_tracks(t_video)

            # --- 4. Tracklet capture + VLM dispatch (VLM module) ---
            self._capture_tracklets(frame, t_video, seen_ids)
            self._maybe_fire_vlm(t_video)

            # --- 5. Welding attribution + phantom tracker ---
            welding_ids, orphan_flashes, visible_phantom_ids = (
                self._attribute_welding_and_phantoms(flashes, t_video)
            )

            # --- 6. Per-track activity decision ---
            self._decide_activities(seen_ids, welding_ids, t_video)

            # --- 8b. Idle-group detection (clusters of stationary non-working tracks) ---
            if self.groups_enabled:
                self._groups = self.group_detector.step(self.tracks, t_video)
            else:
                self._groups = []

            # --- 8c. Zone-rule evaluation (configured camera regions) ---
            # Counts both confirmed person tracks AND visible phantom welders
            # — the arc is direct evidence of a worker. See _step_zones doc.
            if self.zones_enabled:
                self._zone_evals = await self._step_zones(
                    seen_ids, visible_phantom_ids, t_video,
                )
            else:
                self._zone_evals = []

            # --- 7. Render + publish (MJPEG + state broadcast) ---
            await self._render_and_publish(
                frame, frame_idx, t_video, tracked, dets, ran_yolo,
                seen_ids, flashes, orphan_flashes, visible_phantom_ids,
            )

            # --- 10. Pace to target fps ---
            # `await asyncio.sleep(...)` is the only guaranteed event-loop yield
            # in this loop. The other awaits (broadcast, detect_and_track on
            # non-detect frames) can complete synchronously without yielding.
            # We MUST yield once per iteration, otherwise — when YOLO is off
            # and we fall behind target_fps — the loop monopolises the event
            # loop, starving uvicorn's lifespan startup and other tasks.
            next_tick += target_dt
            sleep_for = next_tick - time.time()
            if sleep_for <= 0:
                # We fell behind; reset schedule to prevent accumulating drift.
                next_tick = time.time()
            await asyncio.sleep(max(0.0, sleep_for))

        cap.release()

    def stop(self):
        self._stopping = True
