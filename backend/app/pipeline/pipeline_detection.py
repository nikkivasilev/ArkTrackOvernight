"""Detection cycle — full-frame + SAHI YOLO, flash + welding attribution,
ID-recovered tracker output. Mixin extracted from pipeline.py.

Required attributes on `self` (provided by Pipeline):
    self.cfg                : PipelineConfig
    self.yolo               : YoloClient
    self.flash              : FlashDetector
    self.tracker            : sv.ByteTrack
    self.id_recovery        : IdRecovery
    self.phantom_tracker    : PhantomTracker
    self.tracks             : dict[int, TrackHistory]
    self._yolo_ms_ema       : float
    self._last_grid_pass_t  : float
    self._last_tracked      : sv.Detections | None
    self._last_iid_to_pid   : dict[int, int]
    self.yolo_enabled       : bool
    self.welding_enabled    : bool
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor

# Dedicated, bounded pool for D-FINE detect() calls. Caps the number of OS
# threads pumping the shared ORT session — without this, asyncio's default
# pool (min(32, cpu_count()+4) threads) lets per-camera workers spawn
# unbounded threads that thrash the GIL while the GPU sits idle waiting.
# 2 workers comfortably handle two cameras (each detect ~14 ms).
_DFINE_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dfine")

import numpy as np
import supervision as sv

from activity import (
    attribute_welding,
    build_flash_mask,
)
from sahi import (
    crop_tile,
    filter_edge_detections,
    make_tiles,
    nms_merge,
    offset_detections,
)
from yolo_client import Detection

logger = logging.getLogger(__name__)


class _DetectionMixin:
    """Per-cycle detection + tracking. Mixed into Pipeline."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _detections_to_sv(self, dets: list[Detection]) -> sv.Detections:
        if not dets:
            return sv.Detections.empty()
        xyxy = np.array([[d.x1, d.y1, d.x2, d.y2] for d in dets], dtype=np.float32)
        conf = np.array([d.conf for d in dets], dtype=np.float32)
        cls = np.array([d.cls for d in dets], dtype=int)
        return sv.Detections(xyxy=xyxy, confidence=conf, class_id=cls)

    def _full_conf(self) -> float:
        """Switch 3: confidence used for the full-frame YOLO call. SAHI tile
        conf (`sahi_conf`) is unaffected — small-object recall depends on it."""
        return self.cfg.conf_high if self.cfg.conf_high_enabled else self.cfg.conf

    # ------------------------------------------------------------------
    # YOLO calls — full frame + SAHI tiles
    # ------------------------------------------------------------------

    async def _detect_async(
        self,
        frame: np.ndarray,
        conf: float | None = None,
        max_dim: int | None = None,
        jpeg_quality: int | None = None,
    ) -> tuple[list[Detection], float]:
        loop = asyncio.get_running_loop()
        t0 = time.time()
        dets = await loop.run_in_executor(
            _DFINE_EXECUTOR,
            self.yolo.detect,
            frame,
            conf if conf is not None else self._full_conf(),
            max_dim,
            jpeg_quality,
        )
        return dets, (time.time() - t0) * 1000

    async def _detect_sahi_async(
        self,
        frame: np.ndarray,
        with_grid: bool = True,
    ) -> tuple[list[Detection], float]:
        """Full-frame + SAHI tile inferences run concurrently, then NMS-merged.

        Uses return_exceptions=True so a single slow/timed-out call can't stall
        the rest; we just drop that contribution and keep going.

        `with_grid=False` skips the tile fanout (used by smart SAHI when a
        refresh isn't due — full-frame still runs, the cycle just stays cheap).
        """
        H, W = frame.shape[:2]
        rects = (
            make_tiles(W, H, self.cfg.sahi_cols, self.cfg.sahi_rows, self.cfg.sahi_overlap)
            if with_grid else []
        )
        t0 = time.time()

        full_task = self._detect_async(
            frame, self._full_conf(),
            max_dim=self.cfg.detect_max_dim,
            jpeg_quality=self.cfg.upload_jpeg_quality,
        )
        tile_tasks = [
            self._detect_async(
                crop_tile(frame, r), self.cfg.sahi_conf,
                max_dim=self.cfg.tile_max_dim,
                jpeg_quality=self.cfg.tile_jpeg_quality,
            )
            for r in rects
        ]

        results = await asyncio.gather(full_task, *tile_tasks, return_exceptions=True)
        n_total = 1 + len(rects)
        n_failed = 0
        merged: list[Detection] = []

        # full. asyncio.gather(return_exceptions=True) yields BaseException,
        # not just Exception — so we isinstance against BaseException to
        # also catch CancelledError / KeyboardInterrupt cleanly.
        first = results[0]
        if isinstance(first, BaseException):
            n_failed += 1
        else:
            merged.extend(first[0])

        # tiles
        for rect, r in zip(rects, results[1:1 + len(rects)]):
            if isinstance(r, BaseException):
                n_failed += 1
                continue
            tile_dets, _ms = r
            shifted = offset_detections(tile_dets, rect[0], rect[1])
            shifted = filter_edge_detections(shifted, rect, edge_margin=4, frame_size=(W, H))
            merged.extend(shifted)

        if n_failed:
            logger.warning("sahi: %d/%d sub-calls failed this cycle", n_failed, n_total)
        merged = nms_merge(merged, iou_thresh=self.cfg.sahi_nms_iou)
        return merged, (time.time() - t0) * 1000

    # ------------------------------------------------------------------
    # Per-frame helpers (called in order from run())
    # ------------------------------------------------------------------

    def _detect_flashes(self, frame: np.ndarray, t_video: float):
        """Run welding-arc detection if Welding module is enabled. Returns
        (flashes, flash_mask). When the module is off, both are empty / None.
        """
        if not self.welding_enabled:
            return {}, None
        flashes = self.flash.detect(frame, t_video)
        flash_mask = build_flash_mask(frame.shape, flashes, dilate_extra=60)
        return flashes, flash_mask

    async def _detect_and_track(
        self,
        frame: np.ndarray,
        t_video: float,
        frame_idx: int,
    ) -> tuple[sv.Detections, list[Detection], bool]:
        """D-FINE every Nth frame, then run ByteTrack and remap internal ids
        to public ids. On non-YOLO frames the previous tracker output is
        reused unchanged.

        Returns (tracked, dets, ran_yolo). On exception inside the YOLO call,
        dets is set to [] and the cycle still runs the tracker on the empty
        set so existing tracks age normally.
        """
        ran_yolo = self.yolo_enabled and (frame_idx % self.cfg.detect_every_n == 0)
        dets: list[Detection] = []
        if not ran_yolo:
            tracked = self._last_tracked if self._last_tracked is not None else sv.Detections.empty()
            return tracked, dets, ran_yolo

        try:
            if self.cfg.sahi_enabled:
                if self.cfg.sahi_smart:
                    use_grid = (t_video - self._last_grid_pass_t >= self.cfg.sahi_refresh_s)
                    if use_grid:
                        self._last_grid_pass_t = t_video
                    dets, yolo_ms = await self._detect_sahi_async(frame, with_grid=use_grid)
                else:
                    dets, yolo_ms = await self._detect_sahi_async(frame)
            else:
                dets, yolo_ms = await self._detect_async(
                    frame,
                    max_dim=self.cfg.detect_max_dim,
                    jpeg_quality=self.cfg.upload_jpeg_quality,
                )
            self._yolo_ms_ema = (
                0.8 * self._yolo_ms_ema + 0.2 * yolo_ms if self._yolo_ms_ema else yolo_ms
            )
        except Exception as e:
            logger.warning("yolo error: %s", e)
            dets = []

        sv_dets = self._detections_to_sv(dets)
        tracked = self.tracker.update_with_detections(sv_dets)

        # Remap raw tracker IDs to stable public IDs via the recovery layer
        if len(tracked) > 0:
            iids = [int(x) for x in tracked.tracker_id]
            boxes = [tuple(map(float, b)) for b in tracked.xyxy]
            self._last_iid_to_pid = self.id_recovery.step(t_video, iids, boxes, frame)
        else:
            self._last_iid_to_pid = self.id_recovery.step(t_video, [], [], frame)
        self._last_tracked = tracked
        return tracked, dets, ran_yolo

    # ------------------------------------------------------------------
    # Welding attribution + phantom tracker step
    # ------------------------------------------------------------------

    def _attribute_welding_and_phantoms(
        self,
        flashes: dict,
        t_video: float,
    ) -> tuple[set[int], dict, set[int]]:
        """Run welding attribution + phantom tracker step. Returns
        (welding_ids, orphan_flashes, visible_phantom_ids). When Welding module
        is off, all three are empty."""
        if not self.welding_enabled:
            return set(), {}, set()
        welding_ids, orphan_flashes = attribute_welding(flashes, self.tracks, t_video)
        # Tell PhantomTracker which flash locations were claimed by a real
        # track this frame, so any phantom in grace at that location retires
        # early instead of lingering 6 s and risking a double-render.
        claimed_centroids = [
            (ev.cx, ev.cy) for fid, ev in flashes.items() if fid not in orphan_flashes
        ]
        visible_phantom_ids = self.phantom_tracker.step(
            t_video, orphan_flashes, claimed_centroids=claimed_centroids,
        )
        return welding_ids, orphan_flashes, visible_phantom_ids
