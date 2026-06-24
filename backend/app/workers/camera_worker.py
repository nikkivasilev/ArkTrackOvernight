from __future__ import annotations

import asyncio
import logging
import time
import traceback
from collections import deque
from datetime import datetime, timezone
from uuid import UUID

import cv2
import httpx
import numpy as np
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.db import SessionLocal
from app.inference import dfine_client
from app.inference.dfine_client import Detection
from app.models import Alert, Camera, CameraKind, CameraStatus, MetricSample, Rule, Severity, Zone
from app.pipeline.runtime import CameraPipeline
from app.realtime import live_streams
from app.realtime.broadcaster import broadcaster
from app.storage.media import alert_clip_path, alert_thumbnail_path, save_thumbnail
from app.workers import frame_sampler, registry, zone_filter
from app.workers.clip_extractor import extract_clip, first_frame
from app.workers.metrics import BUCKET_S, MetricsAggregator
from app.workers.resting_clips import RestingClipTracker, RestingInstance
from app.workers.rule_engine import AlertIntent, RuleSpec, RuleState, evaluate_frame

logger = logging.getLogger(__name__)

# Cap WebSocket state broadcasts at this rate even if the pipeline runs
# faster. Each broadcast fans out to every connected dashboard, so we trade
# a few intermediate frames for predictable load.
STATE_BROADCAST_HZ = 10.0
_STATE_MIN_INTERVAL = 1.0 / STATE_BROADCAST_HZ

# Default rolling window folded into each broadcast `state.metrics` block.
# The /metrics REST route can request any window from the live aggregator.
DEFAULT_METRICS_WINDOW_S = 600.0

# Cadence for the DB flush of closed metric buckets. 60 s is short enough
# that a backend crash loses at most a minute of historical reporting and
# long enough to keep the camera-worker DB chatter quiet (~one batch insert
# of ≤6 rows per minute, per running camera).
METRICS_FLUSH_INTERVAL_S = 60.0


async def _load_rule_specs(session, camera_id: UUID) -> list[RuleSpec]:
    zones_q = await session.execute(select(Zone).where(Zone.camera_id == camera_id))
    zones_by_id = {z.id: z for z in zones_q.scalars().all()}

    rules_q = await session.execute(
        select(Rule).where(
            Rule.enabled.is_(True),
            or_(
                Rule.camera_id == camera_id,
                Rule.zone_id.in_(list(zones_by_id.keys())) if zones_by_id else False,
            ),
        )
    )
    rules = rules_q.scalars().all()

    specs: list[RuleSpec] = []
    for r in rules:
        zone = zones_by_id.get(r.zone_id) if r.zone_id else None
        specs.append(
            RuleSpec(
                id=r.id,
                name=r.name,
                trigger_type=r.trigger_type.value if hasattr(r.trigger_type, "value") else str(r.trigger_type),
                severity=r.severity.value if hasattr(r.severity, "value") else str(r.severity),
                params=r.params or {},
                polygon=zone.polygon if zone else None,
                zone_id=r.zone_id,
                camera_id=r.camera_id,
            )
        )
    return specs


def _draw_box_on_thumbnail(frame_bgr: np.ndarray, det: Detection) -> np.ndarray:
    h, w = frame_bgr.shape[:2]
    x1, y1 = int(det.x1 * w), int(det.y1 * h)
    x2, y2 = int(det.x2 * w), int(det.y2 * h)
    out = frame_bgr.copy()
    cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), 2)
    label = f"{det.name} {det.confidence:.2f}"
    cv2.putText(out, label, (x1, max(0, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    return out


def _alert_payload(alert: Alert, rule_name: str) -> dict:
    return {
        "id": str(alert.id),
        "camera_id": str(alert.camera_id),
        "rule_id": str(alert.rule_id),
        "rule_name": rule_name,
        "zone_id": str(alert.zone_id) if alert.zone_id else None,
        "severity": alert.severity.value if hasattr(alert.severity, "value") else str(alert.severity),
        "acknowledged": alert.acknowledged,
        "start_timestamp_in_video": alert.start_timestamp_in_video,
        "end_timestamp_in_video": alert.end_timestamp_in_video,
        "detection_box": alert.detection_box,
        "confidence": alert.confidence,
        "has_clip": bool(alert.clip_path),
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
    }


async def _persist_fire(
    session,
    camera_id: UUID,
    intent: AlertIntent,
    frame_bgr: np.ndarray,
    t_seconds: float,
) -> Alert:
    severity = Severity(intent.rule.severity) if intent.rule.severity in Severity.__members__ else Severity.warn
    detection_box: dict | None = None
    if intent.detection is not None:
        detection_box = {
            "x1": intent.detection.x1,
            "y1": intent.detection.y1,
            "x2": intent.detection.x2,
            "y2": intent.detection.y2,
        }
    alert = Alert(
        camera_id=camera_id,
        rule_id=intent.rule.id,
        zone_id=intent.rule.zone_id,
        severity=severity,
        start_timestamp_in_video=t_seconds,
        detection_box=detection_box,
        confidence=intent.confidence,
        thumbnail_path="",
    )
    session.add(alert)
    await session.flush()

    if intent.detection is not None:
        thumb = _draw_box_on_thumbnail(frame_bgr, intent.detection)
    else:
        thumb = frame_bgr
    path = alert_thumbnail_path(alert.id)
    save_thumbnail(thumb, path)
    alert.thumbnail_path = str(path)
    await session.commit()
    await session.refresh(alert)
    return alert


async def _persist_resolve(session, alert_id: UUID, t_seconds: float) -> None:
    alert = await session.get(Alert, alert_id)
    if alert is None:
        return
    alert.end_timestamp_in_video = t_seconds
    await session.commit()


async def _persist_resting_clip(
    session,
    camera_id: UUID,
    rule: RuleSpec,
    inst: RestingInstance,
    source_path: str,
) -> Alert:
    """Create an Alert for a closed resting instance: extract a clip that
    FOLLOWS the worker (a window sized to their bbox + `crop_pad_px` context,
    panned along the bbox trajectory) over [start - pre_roll, end], + a matching
    thumbnail/poster taken from frame 0 of that clip."""
    severity = Severity(rule.severity) if rule.severity in Severity.__members__ else Severity.warn
    params = rule.params or {}
    pre_roll = float(params.get("pre_roll_s", 3.0))
    crop_pad = int(params.get("crop_pad_px", 120))
    min_clip = float(params.get("min_clip_s", 10.0))
    start = max(0.0, inst.start_t - pre_roll)
    end = inst.end_t
    # Guarantee a minimum saved-video length: if the rest was brief, extend the
    # clip with post-roll footage (the source has frames past the rest end; the
    # following window holds the worker's last position, showing them get up).
    if min_clip > 0 and (end - start) < min_clip:
        end = start + min_clip

    # Normalize the last-known bbox → detection_box (matches _persist_fire +
    # the frontend AlertCard overlay convention: 0..1 fractions).
    detection_box: dict | None = None
    if inst.last_bbox is not None:
        try:
            info = frame_sampler.probe(source_path)
            if info.width > 0 and info.height > 0:
                x1, y1, x2, y2 = inst.last_bbox
                detection_box = {
                    "x1": max(0.0, min(1.0, x1 / info.width)),
                    "y1": max(0.0, min(1.0, y1 / info.height)),
                    "x2": max(0.0, min(1.0, x2 / info.width)),
                    "y2": max(0.0, min(1.0, y2 / info.height)),
                }
        except Exception:
            detection_box = None

    alert = Alert(
        camera_id=camera_id,
        rule_id=rule.id,
        zone_id=rule.zone_id,
        severity=severity,
        start_timestamp_in_video=start,
        end_timestamp_in_video=end,
        detection_box=detection_box,
        confidence=inst.vlm_conf,
        thumbnail_path="",
    )
    session.add(alert)
    await session.flush()  # assigns alert.id

    # Extract the clip (VP8 WebM, off-loop), following the worker's trajectory.
    # Best-effort: the alert + thumbnail still stand if extraction fails.
    clip_path = alert_clip_path(alert.id)
    have_clip = await extract_clip(source_path, start, end, clip_path, track=inst.track, pad=crop_pad)
    if have_clip:
        alert.clip_path = str(clip_path)

    # Thumbnail/poster = frame 0 of the written clip so the <video poster>
    # matches the footage exactly. Fall back to the full source frame if the
    # clip failed.
    thumb = await asyncio.to_thread(first_frame, clip_path) if have_clip else None
    if thumb is None:
        thumb = await asyncio.to_thread(frame_sampler.grab_frame_at, source_path, inst.start_t)
    if thumb is not None:
        tpath = alert_thumbnail_path(alert.id)
        save_thumbnail(thumb, tpath)
        alert.thumbnail_path = str(tpath)

    await session.commit()
    await session.refresh(alert)
    return alert


async def _handle_resting_instance(
    camera_id: UUID,
    rule: RuleSpec,
    inst: RestingInstance,
    source_path: str,
    sema: asyncio.Semaphore,
) -> None:
    """Background task: persist + broadcast one resting-clip alert. Never raises
    into the worker loop — a failure here must not kill the camera."""
    async with sema:
        try:
            async with SessionLocal() as session:
                alert = await _persist_resting_clip(session, camera_id, rule, inst, source_path)
            await broadcaster.publish({
                "type": "alert.created", "v": 1,
                "data": _alert_payload(alert, rule.name),
            })
        except Exception:
            logger.exception("resting-clip handling failed for camera %s", camera_id)


async def _paced_emitter(
    camera_id: UUID,
    queue: "asyncio.Queue",
    sampling_fps: float,
    buffer_s: float,
) -> None:
    """Drain ``(t_video, jpeg, state_dict)`` tuples at the source's native pace.

    Holds back until the queue has at least ``buffer_s × sampling_fps`` items
    (the head start), then emits one tuple per real-time tick by sleeping by
    the video-time delta between consecutive frames. WS state broadcasts are
    rate-capped at the same 10 Hz the unbuffered path uses; MJPEG emits
    every frame.

    On ``None`` sentinel the queue is closed. If the sentinel arrives during
    prefill, we still drain whatever buffered items we collected — videos
    were specced to always be longer than the buffer, but the edge case is
    cheap to handle and avoids losing the entire run on a fast pipeline.
    """
    target_prefill = max(1, int(buffer_s * sampling_fps))
    prefill: "deque" = deque()
    pipeline_done = False

    # Phase 1: prefill the head start (or sentinel arrives first).
    while len(prefill) < target_prefill:
        item = await queue.get()
        if item is None:
            pipeline_done = True
            break
        prefill.append(item)

    # Phase 2: emit at source-native pace.
    prev_t: float | None = None
    last_state_broadcast = 0.0
    while True:
        if prefill:
            item = prefill.popleft()
        elif pipeline_done:
            return
        else:
            item = await queue.get()
            if item is None:
                return

        t_video, jpeg, state_dict = item
        if prev_t is not None:
            dt = max(0.0, t_video - prev_t)
            # Cap pathological waits (e.g., if t_video rolled over for any
            # reason); fall back to the nominal frame period.
            if dt > 5.0:
                dt = 1.0 / max(1.0, sampling_fps)
            if dt > 0:
                await asyncio.sleep(dt)
        prev_t = t_video

        live_streams.publish(camera_id, jpeg)
        now = time.monotonic()
        if now - last_state_broadcast >= _STATE_MIN_INTERVAL:
            last_state_broadcast = now
            await broadcaster.publish(
                {"type": "state", "v": 1, "data": state_dict}
            )


async def _flush_metrics(camera_id: UUID, aggregator: MetricsAggregator, now_t: float) -> None:
    """Persist closed-and-unflushed metric buckets to ``metric_samples``.

    Uses ``ON CONFLICT (camera_id, bucket_start) DO NOTHING`` so re-running
    the flush after a crash mid-transaction can't double-insert. The
    aggregator's high-water-mark only advances after the commit succeeds —
    a transient DB error means we retry the same buckets next cycle.
    """
    rows = aggregator.collect_flushable(now_t)
    if not rows:
        return
    payload = [{"camera_id": camera_id, **row} for _, row in rows]
    try:
        async with SessionLocal() as session:
            stmt = (
                pg_insert(MetricSample)
                .values(payload)
                .on_conflict_do_nothing(index_elements=["camera_id", "bucket_start"])
            )
            await session.execute(stmt)
            await session.commit()
    except Exception:
        logger.exception("metrics flush failed for camera %s", camera_id)
        return
    aggregator.mark_flushed_through(rows[-1][0])


async def _set_inference_error(camera_id: UUID, msg: str | None) -> None:
    async with SessionLocal() as session:
        cam = await session.get(Camera, camera_id)
        if cam is None:
            return
        new = f"inference: {msg}" if msg else None
        if cam.error == new:
            return
        cam.error = new
        await session.commit()


def _legacy_detections_from_state(state: dict, w: int, h: int) -> list[Detection]:
    """Convert vendored-pipeline track entries into the normalized
    ``Detection`` dataclass the legacy rule_engine consumes.

    The legacy path keeps working alongside the new pipeline so existing
    rule rows still fire alerts; Phase 3 retires it.
    """
    out: list[Detection] = []
    for t in state.get("tracks") or []:
        bbox = t.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        x1, y1, x2, y2 = bbox
        out.append(Detection(
            class_id=0,
            name="person",
            confidence=float(t.get("conf") or 0.0),
            x1=max(0.0, min(1.0, x1 / w)),
            y1=max(0.0, min(1.0, y1 / h)),
            x2=max(0.0, min(1.0, x2 / w)),
            y2=max(0.0, min(1.0, y2 / h)),
        ))
    return out


async def run_camera_worker(camera_id: UUID) -> None:
    """Process a single camera end-to-end. One task per camera.

    Drives the vendored ModelTesting pipeline (`CameraPipeline.process_frame`)
    on each sampled frame, pushes the rendered MJPEG to ``live_streams``,
    and broadcasts ``state`` events over the app's WS broadcaster. The
    legacy rule engine still runs against the rendered tracks so existing
    Alert rows keep firing until Phase 3 retires it.
    """
    pipeline: CameraPipeline | None = None
    emitter_task: "asyncio.Task | None" = None
    out_queue: "asyncio.Queue | None" = None
    buffer_s = 0.0
    resting_tracker: RestingClipTracker | None = None
    resting_rule: RuleSpec | None = None
    resting_sema = asyncio.Semaphore(2)
    resting_tasks: set["asyncio.Task"] = set()
    try:
        async with SessionLocal() as session:
            cam = await session.get(Camera, camera_id)
            if cam is None:
                logger.warning("worker: camera %s not found", camera_id)
                return
            path = cam.path_or_url
            cam_kind = cam.kind
            start_idx = cam.last_processed_frame_idx
            persisted_modules = dict((cam.settings or {}).get("modules") or {})
            # sampling_fps == 0 → Auto: probe the source's native fps and
            # sample at that rate. Any positive value is a user-chosen
            # preset (3 / 8 / 15 / 30 fps from the UI) — use as-is.
            if cam.sampling_fps and cam.sampling_fps > 0:
                sampling_fps = float(cam.sampling_fps)
            else:
                try:
                    info = frame_sampler.probe(path)
                    sampling_fps = float(info.fps) if info.fps and info.fps > 0 else 10.0
                except Exception as exc:
                    logger.warning("worker %s: probe failed (%s); falling back to 10 fps",
                                   camera_id, exc)
                    sampling_fps = 10.0
            cam.status = CameraStatus.running
            cam.error = None
            await session.commit()
            await broadcaster.publish({
                "type": "camera.updated", "v": 1,
                "data": {"id": str(camera_id), "status": "running"},
            })
            rule_specs = await _load_rule_specs(session, camera_id)
            all_zones = (
                await session.execute(select(Zone).where(Zone.camera_id == camera_id))
            ).scalars().all()
            excluded_zone_polys = [list(z.polygon) for z in all_zones if z.excluded]
            # Monitored (non-excluded) zones drive occupancy metrics.
            metric_zones = [
                {"id": str(z.id), "name": z.name, "polygon": list(z.polygon)}
                for z in all_zones if not z.excluded
            ]

        # Resting-worker clip capture is gated per-camera by an enabled
        # `resting_worker` rule. No such rule → feature dormant for this camera.
        resting_rule = next(
            (r for r in rule_specs if r.trigger_type == "resting_worker"), None
        )
        resting_tracker = RestingClipTracker(resting_rule.params) if resting_rule else None

        pipeline = CameraPipeline(camera_id=camera_id, target_fps=sampling_fps)
        if persisted_modules:
            # yolo/overlay remain operator-settable; welding/groups are
            # forced on in CameraPipeline.__init__ and not overridable.
            await pipeline.set_modules(**{
                k: v for k, v in persisted_modules.items()
                if k in ("yolo_enabled", "overlay_enabled")
            })
        metrics = MetricsAggregator(wall_clock_origin=datetime.now(timezone.utc))
        pipeline.metrics = metrics
        if excluded_zone_polys:
            pipeline.set_excluded_zones(excluded_zone_polys)
        if metric_zones:
            pipeline.set_metric_zones(metric_zones)
        registry.attach_pipeline(camera_id, pipeline)

        # File sources race through frames flat-out — pace the user-visible
        # output through a 20 s pre-buffer so the dashboard plays smoothly.
        # RTSP cameras are already paced by the source and we don't want to
        # delay alerts, so they keep the direct-publish path.
        buffer_s = (
            float(settings.live_buffer_s)
            if cam_kind == CameraKind.file and settings.live_buffer_s > 0
            else 0.0
        )
        buffered = buffer_s > 0
        if buffered:
            # Cap the queue at 2× the head-start window. A fast pipeline
            # producing way ahead of source-fps would otherwise grow memory
            # unbounded over long videos (50 KB/frame × source-fps × hours).
            # When the queue fills, `await queue.put(...)` in the frame loop
            # blocks until the emitter consumes one — natural back-pressure
            # that keeps the worker producing at roughly source-fps once the
            # buffer is full.
            queue_max = max(2, int(2 * buffer_s * sampling_fps))
            out_queue = asyncio.Queue(maxsize=queue_max)
            emitter_task = asyncio.create_task(
                _paced_emitter(camera_id, out_queue, sampling_fps, buffer_s),
                name=f"emitter-{camera_id}",
            )

        last_inference_error: str | None = None
        rule_state: dict[type, RuleState] = {}
        last_state_broadcast = 0.0
        last_metrics_flush = time.monotonic()
        prev_t: float | None = None

        async for frame_idx, t_seconds, frame in frame_sampler.iter_sampled(
            path, target_fps=sampling_fps, start_frame_idx=start_idx
        ):
            try:
                frame_out = await pipeline.process_frame(frame, frame_idx, t_seconds)
                if last_inference_error is not None:
                    last_inference_error = None
                    await _set_inference_error(camera_id, None)
            except Exception as exc:
                msg = f"{exc.__class__.__name__}: {exc}"
                if msg != last_inference_error:
                    last_inference_error = msg
                    await _set_inference_error(camera_id, msg)
                    logger.warning("worker %s: pipeline step failed: %s", camera_id, msg)
                frame_out = None

            if frame_out is None:
                continue

            # Re-bind normalized polygons → pixel polys once source_dim is
            # known (first successful frame). After this the call is a
            # no-op until set_excluded_zones is invoked again.
            if (
                pipeline.source_dim is not None
                and not pipeline.excluded_polys_px
                and getattr(pipeline, "_excluded_polys_norm", None)
            ):
                pipeline.set_excluded_zones(pipeline._excluded_polys_norm)
            # Same deferral for monitored (metric) zones.
            if (
                pipeline.source_dim is not None
                and not pipeline._metric_zones
                and getattr(pipeline, "_metric_zones_norm", None)
            ):
                pipeline.set_metric_zones(pipeline._metric_zones_norm)

            zone_filter.apply(frame_out.state, pipeline.excluded_polys_px)

            # Fold this frame into the workforce-metrics aggregator. This
            # runs at process time (not playback time) so the live aggregator
            # and `metric_samples` DB flush reflect what the pipeline has
            # actually seen, independent of the buffered display position.
            dt = (t_seconds - prev_t) if prev_t is not None else 0.0
            prev_t = t_seconds
            metrics.add(frame_out.state, dt)

            # Compose the full state-dict the WS broadcasts. Snapshotted at
            # process time and enqueued alongside the JPEG so the buffered
            # display shows metrics aligned with the visible frame.
            state_msg = {
                "camera_id": str(camera_id),
                **frame_out.state,
                "metrics": metrics.summary(DEFAULT_METRICS_WINDOW_S),
            }

            if buffered:
                await out_queue.put((t_seconds, frame_out.jpeg, state_msg))
            else:
                live_streams.publish(camera_id, frame_out.jpeg)
                now = time.monotonic()
                if now - last_state_broadcast >= _STATE_MIN_INTERVAL:
                    last_state_broadcast = now
                    await broadcaster.publish(
                        {"type": "state", "v": 1, "data": state_msg}
                    )

            now = time.monotonic()
            if now - last_metrics_flush >= METRICS_FLUSH_INTERVAL_S:
                last_metrics_flush = now
                await _flush_metrics(camera_id, metrics, now_t=t_seconds)

            if rule_specs:
                h, w = frame.shape[:2]
                legacy_dets = _legacy_detections_from_state(frame_out.state, w, h)
                intents = evaluate_frame(legacy_dets, rule_specs, rule_state)
                if intents:
                    async with SessionLocal() as session:
                        for intent in intents:
                            st = rule_state.get(intent.rule.id)
                            if intent.transition == "fire":
                                alert = await _persist_fire(session, camera_id, intent, frame, t_seconds)
                                if st is not None:
                                    st.open_alert_id = alert.id
                                await broadcaster.publish({
                                    "type": "alert.created", "v": 1,
                                    "data": _alert_payload(alert, intent.rule.name),
                                })
                            elif intent.transition == "resolve" and st and st.open_alert_id:
                                await _persist_resolve(session, st.open_alert_id, t_seconds)
                                await broadcaster.publish({
                                    "type": "alert.resolved", "v": 1,
                                    "data": {"id": str(st.open_alert_id), "end_timestamp_in_video": t_seconds},
                                })
                                st.open_alert_id = None

            # Resting-worker clip capture: feed the rendered tracks; spawn a
            # background extraction for each instance that closed this frame.
            if resting_tracker is not None and resting_rule is not None:
                for inst in resting_tracker.update(t_seconds, frame_out.state.get("tracks") or []):
                    task = asyncio.create_task(
                        _handle_resting_instance(camera_id, resting_rule, inst, path, resting_sema)
                    )
                    resting_tasks.add(task)
                    task.add_done_callback(resting_tasks.discard)

            if frame_idx - start_idx > 90 and frame_idx % 90 == 0:
                async with SessionLocal() as session:
                    cam = await session.get(Camera, camera_id)
                    if cam is not None:
                        cam.last_processed_frame_idx = frame_idx
                        await session.commit()

        # Close out any resting instances still open at end-of-video.
        if resting_tracker is not None and resting_rule is not None and prev_t is not None:
            for inst in resting_tracker.flush(prev_t):
                task = asyncio.create_task(
                    _handle_resting_instance(camera_id, resting_rule, inst, path, resting_sema)
                )
                resting_tasks.add(task)
                task.add_done_callback(resting_tasks.discard)

        async with SessionLocal() as session:
            cam = await session.get(Camera, camera_id)
            if cam is not None:
                cam.status = CameraStatus.completed
                await session.commit()
        await broadcaster.publish({
            "type": "camera.updated", "v": 1,
            "data": {"id": str(camera_id), "status": "completed"},
        })

    except asyncio.CancelledError:
        # Hard cancel — drop the buffered tail; the operator asked to stop.
        if emitter_task is not None and not emitter_task.done():
            emitter_task.cancel()
        # Drop any in-flight resting-clip extractions (no partial clip is ever
        # served — the alert/clip/thumbnail commit together at the end).
        for t in resting_tasks:
            t.cancel()
        async with SessionLocal() as session:
            cam = await session.get(Camera, camera_id)
            if cam is not None:
                cam.status = CameraStatus.cancelled
                await session.commit()
        await broadcaster.publish({
            "type": "camera.updated", "v": 1,
            "data": {"id": str(camera_id), "status": "cancelled"},
        })
        raise
    except Exception as exc:
        tb = traceback.format_exc()
        logger.exception("worker failed: %s", exc)
        async with SessionLocal() as session:
            cam = await session.get(Camera, camera_id)
            if cam is not None:
                cam.status = CameraStatus.failed
                cam.error = f"{exc}\n{tb}"
                await session.commit()
        await broadcaster.publish({
            "type": "camera.updated", "v": 1,
            "data": {"id": str(camera_id), "status": "failed", "error": str(exc)},
        })
    finally:
        # Let the paced emitter drain whatever's left in the buffer so the
        # operator sees the tail of the run, then time out so a hung
        # consumer can't block teardown indefinitely.
        if emitter_task is not None and not emitter_task.done():
            try:
                await out_queue.put(None)
                await asyncio.wait_for(emitter_task, timeout=buffer_s + 5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                emitter_task.cancel()
            except Exception:
                logger.exception("emitter drain failed for camera %s", camera_id)
                emitter_task.cancel()

        # Capture the final partial bucket — advance now_t past the latest
        # bucket boundary so collect_flushable() releases it.
        try:
            if pipeline is not None and pipeline.metrics is not None:
                await _flush_metrics(
                    camera_id,
                    pipeline.metrics,
                    now_t=pipeline.metrics.latest_t + BUCKET_S,
                )
        except Exception:
            logger.exception("final metrics flush failed for camera %s", camera_id)

        # Let in-flight resting-clip extractions finish (bounded), so a clip
        # whose instance closed near the end isn't lost. Timed so a hung
        # encode can't block teardown.
        if resting_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*resting_tasks, return_exceptions=True), timeout=30.0
                )
            except (asyncio.TimeoutError, asyncio.CancelledError):
                for t in resting_tasks:
                    t.cancel()

        registry.detach_pipeline(camera_id)
        if pipeline is not None:
            pipeline.close()
