# Architecture

This document describes how the offline batch analyzer works end to end: the
ingest/processing/reporting package, the AI pipeline it drives, the data model,
configuration, and runtime requirements.

All paths are relative to `backend/` unless noted.

---

## 1. End-to-end data flow

```
recording file lands in data/incoming/
   │
   │  ingest.parse_nvr_filename()        →  camera label + (start, end) UTC
   │  ingest.resolve_camera()            →  get-or-create Camera by (site, label)
   │  batch.process_one()                →  ProcessedRecording row (status="processing")
   ▼
runner.process_recording(camera_id, path, start_dt, excluded_zones, metric_zones)
   │  CameraPipeline(headless=True)
   │  MetricsAggregator(wall_clock_origin=start_dt)        ← anchors to REAL time
   │  for each sampled frame:
   │      state = pipeline.process_frame(frame, idx, t)    ← detect/track/welding/VLM/activity
   │      zone_filter.apply(state, excluded_polys)         ← drop tracks in excluded zones
   │      metrics.add(state, dt)                           ← fold into 10s buckets
   │      every 300s of footage → flush closed buckets
   ▼
metric_samples  (one row per camera per 10s bucket, bucket_start = start_dt + t, UTC)
   │  ON CONFLICT (camera_id, bucket_start) DO NOTHING     ← idempotent; re-runs safe
   ▼
day_summary.build_period_summary()        ← folds rows over a local day/week/month
   │  aggregate.fold_samples()            ← sum activity/rollup, weight headcount, merge zones
   │  aggregate.staffing_timeline()       ← intraday curve (day)
   │  aggregate.daily_timeline()          ← per-calendar-day bars (week/month), DST-correct
   ▼
PeriodSummary  →  JSON  (api/reports.py → operator UI)
               →  PDF   (report_pdf.render_period_pdf → download / CLI)
```

Two properties make this trustworthy:

- **Real timestamps.** `MetricsAggregator(wall_clock_origin=start_dt)` maps video-time
  `t=0` to the recording's actual start (parsed from the filename), so a bucket at
  video-time `t` lands in `metric_samples` at `start_dt + t`. A day's worth of files
  reconstructs an accurate factory timeline.
- **Idempotent flush.** Buckets are keyed `(camera_id, bucket_start)` and inserted with
  `ON CONFLICT DO NOTHING`, so re-running a file (or overlapping recordings) can't
  double-count.

The detection/tracking/VLM/welding stack is **byte-for-byte the live pipeline** — the
offline runner is the batch analogue of the live `camera_worker`, differing only in:
headless (no JPEG render/encode), real-time anchoring, and a footage-time flush cadence.

---

## 2. The offline package (`app/offline/`)

| File | Role | Key entry points |
|---|---|---|
| `ingest.py` | Parse NVR filenames → camera label + start/end UTC; get-or-create `Camera`; ledger helpers. | `parse_nvr_filename(path, tz)`, `list_recordings(dir, tz)`, `resolve_camera(session, label, site_id, path)`, `already_processed`, `default_site_id` |
| `runner.py` | Process **one** file: headless `CameraPipeline` over sampled frames → `metric_samples` at real time. | `process_recording(camera_id, path, start_dt, target_fps=None, excluded_zone_polys=None, metric_zones=None) -> RunStats` |
| `batch.py` | Orchestrate a folder: list, skip already-processed, process sequentially, write ledger. | `ingest_folder(drop_dir=None, tz=None, reprocess=False)`, `process_one(parsed, site_id)`, `_load_zones(session, camera_id)` |
| `watcher.py` | Watch the drop dir (`watchfiles.awatch` + 30 s quiet-settle) → ingest + regenerate reports per day touched. | `watch(drop_dir=None, tz=None)` |
| `aggregate.py` | Pure folding of `metric_samples` rows (no DB). | `fold_samples(rows, window_s)`, `staffing_timeline(rows, start, end, bin_minutes)`, `daily_timeline(rows, start_utc, end_utc, tz)` |
| `day_summary.py` | Build a factory **period** summary (day/week/month) from `metric_samples` + ledger. | `build_period_summary(...)`, `build_day/week/month_summary(...)`, `day_bounds/week_bounds/month_bounds`, dataclasses `PeriodSummary`/`CameraDay` |
| `report_pdf.py` | Render a `PeriodSummary` → A4 PDF (matplotlib charts + fpdf2 layout, Cyrillic fonts). | `render_period_pdf(summary, out_path=None)` (alias `render_day_pdf`) |
| `reports.py` | Resolve factory + build summary + render PDF; shared by CLI and watcher. | `generate_report(factory, anchor, tz=None, out_dir=None, period="day")`, `resolve_factory` |
| `__main__.py` | CLI: `ingest` / `report` / `run` / `watch`. Calls `Base.metadata.create_all` first. | `python -m app.offline <cmd>` |

### Period reporting details

- **`fold_samples`** sums `activity_seconds`/`rollup_seconds`, time-weights `avg_headcount`
  (`Σ(avg·dur)/Σdur`), takes max `peak_headcount`, and merges per-zone occupancy +
  activity histograms. Output shape matches the live `/metrics` summary, so the same
  renderer serves live and batch.
- **Timeline shape** is period-aware:
  - **day** → `staffing_timeline` (30-min intra-day bins; `timeline_kind="intraday"`).
  - **week/month** → `daily_timeline` (one point per **local calendar day**;
    `timeline_kind="daily"`). It buckets by `bucket_start.astimezone(tz).date()` and
    divides each day by **its own** local wall-second span, so DST days (23 h / 25 h)
    are weighted correctly — a flat 1440-min bin would drift.
- **Period bounds** (`day_bounds`/`week_bounds`/`month_bounds`) build local midnights with
  `tzinfo=tz` then `.astimezone(UTC)` — never `+86400·N` — so they're DST-safe. Week is
  ISO (Monday start).
- **Footage coverage** comes from the `processed_recordings` ledger (overlap query with a
  1-day lower-bound slack), so reports state honestly which hours were actually filmed.

---

## 3. The AI pipeline (`app/pipeline/`, `app/workers/`)

The offline runner drives `CameraPipeline` (`pipeline/runtime.py`), a thin wrapper over
the vendored `Pipeline` (`pipeline/pipeline.py`, ported from the ModelTesting PoC).
Everything below runs per sampled frame.

### 3.1 `CameraPipeline.process_frame(frame, frame_idx, t_seconds) -> FrameOut | None`

Per-frame order:

1. **Welding-flash detect** — `FlashDetector` (HSV V>235 + (B−R)>30 + morphology + connected
   components + perspective-aware area + temporal flicker gate). 2-frame persistence.
2. **Detect + track** — D-FINE-L person detection → ByteTrack association → ID recovery.
3. **Update track histories** — append `(t, cx, cy)`; heuristic `classify_motion` (speed
   >80 px/s → walking, <20 → standing, else unknown).
4. **Drop stale tracks** — unseen > `lost_track_buffer` (~6 s).
5. **Capture tracklets** — 224×224 crops per track for the VLM.
6. **Fire VLM** — at most one in-flight; priority dispatch (never-classified > heuristic
   transition > unknown > revisit), skips confident walking/welding.
7. **Attribute welding** — snap flashes to tracks whose padded bbox contains the arc
   centroid; unattributed arcs → **phantom** welders (stable IDs, grace period).
8. **Decide activities** — welding wins; else heuristic; else recent VLM verdict.
9. **Idle groups** — `group_detector` clusters stationary workers.
10. **Zones** — per-zone occupancy + activity (monitored zones).
11. **Render & publish** — headless skips JPEG; always assembles the `state` dict.

Returns `FrameOut(frame_idx, t, jpeg, state)`. **`headless=True`** (set by the runner)
skips the JPEG encode + overlay — the bulk of per-frame CPU.

Zone binding: `set_excluded_zones(norm_polys)` and `set_metric_zones([{id,name,polygon}])`
store normalized 0..1 polygons and scale them to pixels once `source_dim` is known (first
frame). `.metrics` is the attached `MetricsAggregator`. `.close()` releases the detector.

### 3.2 The `state` dict (what metrics consume)

```python
state = {
  "t": float,                       # video time (s)
  "tracks": [ {                     # one per tracked person
      "track_id": int,
      "bbox": [x1,y1,x2,y2],        # source pixels
      "activity": str,             # welding/walking/standing/sitting/unknown/...
      "vlm_activity": str | None,  # fine-grained VLM label
      "rollup": str,               # working | moving | idle | unclear
      "confidence": float,
      "ghost": bool,               # kept-alive but unseen this frame (excluded from metrics)
      "phantom": bool,             # synthesized from an orphan welding arc
  }, ... ],
  "activity_counts": {label: int},
  "rollup_counts": {bucket: int},
  "flashes": [ {"cx","cy","area","orphan"} ... ],
  "orphan_welding_count": int,     # unattributed arcs → anonymous welders
  "zones": [ {"zone_id","name","count","activities":{label:int}} ... ],
  "groups": [ ... ],
}
```

### 3.3 Subsystems & files

| Subsystem | Files | Notes |
|---|---|---|
| **Detection — D-FINE-L** | `pipeline/dfine_detector.py`, `pipeline/yolo_client.py`, remote fallback `inference/dfine_client.py` | Local ONNX (default) via ONNX Runtime; **TensorRT FP16** EP (~14 ms/frame on RTX 3080) with CUDA→CPU fallback. One **shared** detector singleton per process across cameras, behind a bounded `ThreadPoolExecutor`. Person class only, conf default 0.4, 640×640 input. |
| **Tracking** | `supervision` ByteTrack inside `pipeline/pipeline_detection.py`; `pipeline/id_recovery.py` | `track_activation_threshold≈0.08`, `lost_track_buffer≈120 frames`. ID recovery re-stitches dropped tracks via HSV (+optional LAB) histograms within a spatial/time window. |
| **Welding** | `pipeline/activity.py` (`FlashDetector`, `PhantomTracker`) | Arc detection + orphan→phantom promotion (IDs offset by 100000, survive a grace period of arc-off). |
| **VLM (activity)** | `pipeline/siglip_classifier.py` (default), `pipeline/vlm_classifier.py` (remote Qwen), `pipeline/pipeline_vlm.py` | **SigLIP-2-so400m-NaFlex** local ONNX, zero-shot cosine vs. precomputed label embeddings; co-resident with D-FINE on the GPU. `vlm_backend="siglip"` default; Qwen (`qwen_base_url`) selectable. |
| **Activity rollup** | `pipeline/activity.py` | Fine labels → rollups: `walking→moving`, `sitting→idle`, everything else (welding/standing/unknown/…) → `working` (operator policy: default to productive). `not_a_person→unclear`. |
| **Groups** | `pipeline/group_detector.py` | Idle-group clustering of stationary workers. |
| **Zones (metrics)** | `pipeline/zone_detector.py`, `app/workers/zone_filter.py` | `zone_filter.apply(state, excluded_polys_px)` drops tracks/flashes whose **foot-point** (bottom-center) is in an excluded polygon and recomputes counts. Monitored zones produce per-zone occupancy + activity. |
| **Metrics** | `app/workers/metrics.py` | See §3.4. |
| **Video I/O** | `app/workers/frame_sampler.py` | `probe(path)→VideoInfo(fps,duration_s,…)`, `iter_sampled(path,target_fps)` (sequential decode, stride = native/target), `grab_frame_at(path,t)` (zone-editor scrubber). OpenCV `VideoCapture`. |
| **Geometry / misc** | `pipeline/geom.py`, `pipeline/tracklet.py`, `pipeline/sahi.py`, `pipeline/hog_detector.py`, `pipeline/renderer.py`, `pipeline/pipeline_render.py`, `pipeline/pipeline_tuning.py` | Support modules for the vendored pipeline. SAHI tiling off by default in this build. |

### 3.4 MetricsAggregator (`app/workers/metrics.py`)

- **Buckets**: `BUCKET_S = 10.0`. `add(state, dt)` (dt clamped to 5 s) folds the frame:
  per visible (non-`ghost`) track adds `dt` to `activity_seconds[activity]` and
  `rollup_seconds[rollup]`; accumulates `headcount·dt` and `peak`; orphan welders counted
  as anonymous `welding`/`working`. Per monitored zone: `zone_occupancy_seconds[zone][count] += dt`
  (a time-at-each-headcount histogram) and `zone_activity_seconds[zone][activity] += count·dt`
  (worker-weighted).
- **Flush**: `collect_flushable(now_t)` returns closed buckets (`start_t + BUCKET_S < now_t`)
  as rows ready for `metric_samples`, stamped `bucket_start = wall_clock_origin + start_t`.
  `mark_flushed_through(last_start_t)` advances the high-water-mark **only after commit**,
  so a transient DB error retries rather than drops.
- **Read**: `summary(window_s)` (live) and `aggregate.fold_samples` (DB/report) produce the
  same shape; `derive_zone_occupancy`/`derive_zone_activity` turn the raw histograms into
  `{seconds_at,total_s,avg,peak}` / `{seconds,total_s,pct}`.

### 3.5 Models, checkpoints & GPU

Checkpoints live in `backend/checkpoints/` (**git-ignored** — ~1.7 GB):

| File | Size | Purpose | Produced by |
|---|---|---|---|
| `dfine_l_obj2coco.onnx` | ~120 MB | D-FINE-L person detector | `tools/export_dfine_onnx.py` |
| `trt_cache/*.engine`, `.profile`, `.timing` | — | TensorRT FP16 engine cache (built on first run; `tools/warmup_trt.py`) | ONNX Runtime TRT EP |
| `siglip2_so400m_naflex_vision.onnx` + `.onnx.data` | ~1.6 GB | SigLIP-2 vision tower | `tools/export_siglip_onnx.py` |
| `siglip2_labels.npy` + `.json` | ~60 KB | Precomputed label embeddings + manifest | `tools/export_siglip_onnx.py` |

Runtime:
- **Inference** needs `onnxruntime-gpu` + NVIDIA CUDA/cuDNN/TensorRT libs (pip wheels). On
  Windows the DLLs are preloaded by `dfine_detector.py`. **Torch / transformers are needed
  only at EXPORT time** (to create the ONNX) — a lean inference box ships the pre-exported
  checkpoints and does not need them.
- **VRAM**: ~2.5 GB D-FINE (TRT FP16) + ~1.5 GB SigLIP ≈ ~5–7 GB co-resident; developed on
  an RTX 3080 (10 GB). Throughput ~1.2–1.8× real-time per stream headless; the open perf
  lever is downscaling the welding-flash MOG2 pass (see `tools/bench_overnight.py`).
- **Remote fallback**: if local ONNX is unavailable, the pipeline can call a remote D-FINE
  HTTP endpoint (`dfine_url`) and/or remote Qwen VLM (`qwen_base_url`). For a self-contained
  box, ship the local checkpoints.

---

## 4. Data model (`app/models.py`)

PostgreSQL via SQLAlchemy 2.0 async (`asyncpg`). Hierarchy: **Factory → Site → Camera →
{Zone, Rule}**; metrics and the ledger hang off Camera.

| Table | Key columns | Used by offline? |
|---|---|---|
| `factories` | `id`, `name`, `address`, `created_at` | ✅ report scope (factory → its sites → cameras) |
| `sites` | `id`, `factory_id→`, `name`, `address` | ✅ cameras are created under a site |
| `cameras` | `id`, `site_id→`, `name` (**= NVR label**), `kind` (`file`/`rtsp`), `path_or_url`, `duration_s`, `sampling_fps` (0 = auto-probe), `settings` JSONB, plus live-only `status`/`last_processed_frame_idx`/`error` | ✅ identity + zones/rules anchor; live-only fields ignored |
| `zones` | `id`, `camera_id→`, `name`, `polygon` JSONB (`[[x,y]…]` normalized 0..1), `excluded` bool | ✅ excluded → dropped from metrics; monitored → per-zone breakdowns |
| `rules` | `id`, `name`, `trigger_type` enum, `severity`, `camera_id?`/`zone_id?` (XOR check), `params` JSONB, `enabled` | ✅ read for report context (e.g. `count_min.threshold` seeds default understaffing N). Alert *firing* is live-only. |
| `processed_recordings` | `id`, `camera_id→`, `path` (**unique** dedupe key), `filename`, `recorded_start` (UTC, indexed), `recorded_end`, `frames`, `footage_s`, `status` (`processing`/`done`/`failed`), `error`, `processed_at` | ✅ the ingest ledger + footage-coverage facts |
| `metric_samples` | `id` (bigint), `camera_id→`, `bucket_start` (UTC), `duration_s`, `worker_seconds`, `frames`, `peak_headcount`, `avg_headcount`, `activity_seconds`/`rollup_seconds`/`zone_occupancy_seconds`/`zone_activity_seconds` (JSONB). **Unique `(camera_id, bucket_start)`** | ✅ the metrics sink + report source |
| `alerts` | resting-worker clips, detection events, thumbnails | ❌ **live-only** — droppable in a standalone offline build |

### Schema creation / migrations

The project uses `Base.metadata.create_all` (not Alembic) plus idempotent `ALTER TABLE …
ADD COLUMN IF NOT EXISTS` statements run in `app/main.py`'s lifespan. The offline CLI also
calls `create_all` on startup. The offline-relevant ones:

```sql
ALTER TABLE cameras        ADD COLUMN IF NOT EXISTS settings JSONB NOT NULL DEFAULT '{}'::jsonb;
CREATE INDEX IF NOT EXISTS ix_metric_samples_camera_bucket ON metric_samples (camera_id, bucket_start DESC);
ALTER TABLE zones          ADD COLUMN IF NOT EXISTS excluded BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE metric_samples ADD COLUMN IF NOT EXISTS zone_occupancy_seconds JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE metric_samples ADD COLUMN IF NOT EXISTS zone_activity_seconds  JSONB NOT NULL DEFAULT '{}'::jsonb;
-- alerts.clip_path is live-only; drop with the alerts table in a standalone build
```

Plain PostgreSQL is sufficient — `metric_samples` is a regular table with a btree index
(TimescaleDB is mentioned in the legacy stack but not required by the code).

---

## 5. Configuration (`app/config.py`)

Pydantic `BaseSettings`, env-overridable (`.env`). Offline-relevant fields:

| Setting | Env var | Default | Meaning |
|---|---|---|---|
| `database_url` | `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/bestfactor` | Postgres DSN (local dev uses port **5433**, db `bestfactor`). |
| `offline_drop_dir` | `OFFLINE_DROP_DIR` | `data/incoming` | Watched folder for incoming recordings. |
| `offline_report_dir` | `OFFLINE_REPORT_DIR` | `data/reports` | Where PDFs are written. |
| `factory_tz` | `FACTORY_TZ` | `UTC` | Timezone of NVR filename stamps; sets the local day/week/month boundaries. **Set this** (e.g. `Europe/Sofia`) — NVR stamps are factory-local. |
| `dfine_url` / `dfine_api_key` / `dfine_default_conf` | `DFINE_*` | remote URL / "" / 0.4 | Remote detector fallback + confidence. |
| `qwen_base_url` / `qwen_model` | `QWEN_*` | remote URL / path | Remote VLM (if not using local SigLIP). |
| `default_sampling_fps` | `DEFAULT_SAMPLING_FPS` | 8.0 | Default analysis fps (runner auto-probes native fps when camera `sampling_fps=0`). |
| `inference_semaphore_size` | `INFERENCE_SEMAPHORE_SIZE` | 4 | Detector concurrency bound. |
| `data_dir` | `DATA_DIR` | `data` | Base for `uploads/`, `incoming/`, `reports/`. |

Live-only (droppable): `cors_origins` (keep for the API), `live_buffer_s`.

---

## 6. Infrastructure

| Component | Required for offline? | Notes |
|---|---|---|
| PostgreSQL | ✅ | The only datastore. asyncpg driver. |
| NVIDIA GPU + ONNX Runtime (CUDA/TensorRT) | ✅ (for real throughput) | CPU EP works for testing the report layer; full pipeline wants a GPU. |
| Model checkpoints (`backend/checkpoints/`) | ✅ | Ship the pre-exported ONNX (see §3.5). |
| Python 3.11+, FastAPI, SQLAlchemy, OpenCV, fpdf2, matplotlib, watchfiles, tzdata | ✅ | See [EXTRACTION.md](EXTRACTION.md) for the trimmed dependency list. |
| Redis / Celery / MediaMTX / MinIO | ❌ | **Not used** by the offline path. The watcher uses `watchfiles`; batch is sequential; reports/PDFs are written to local disk. |

Next: the [API & CLI reference](API.md), the [frontend architecture](FRONTEND.md), and the
[extraction guide](EXTRACTION.md).
