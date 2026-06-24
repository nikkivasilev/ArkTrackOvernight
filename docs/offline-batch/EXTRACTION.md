# Extraction Guide — carve out a standalone offline project

The offline batch analyzer is **cleanly separable** from live ArkTrack: the offline path
never imports the live subsystems (RTSP, WebSocket, MJPEG, live `camera_worker`, alerting).
This guide lists exactly what to **keep** vs **drop**, then the steps to stand it up.

> Verified: `app/offline/runner.process_recording` and the report API import only the
> pipeline + DB + metrics modules below — none of the live-only files.

---

## 1. Backend — keep / drop

### KEEP

```
app/__init__.py  config.py  db.py  models.py*  schemas.py*  main.py*
app/offline/            ← ALL: ingest, runner, batch, watcher, aggregate,
                          day_summary, report_pdf, reports, __main__, __init__
app/pipeline/           ← ALL (vendored stack the CameraPipeline drives):
                          runtime, pipeline, pipeline_config, pipeline_detection,
                          pipeline_vlm, pipeline_render, pipeline_tuning, pipeline_zones,
                          activity, tracklet, geom, sahi, dfine_detector, yolo_client,
                          siglip_classifier, vlm_classifier, zone_detector, id_recovery,
                          group_detector, hog_detector, renderer, __init__
app/workers/            ← frame_sampler, metrics, zone_filter, __init__   (only these)
app/storage/            ← media, __init__   (path helpers)
app/inference/          ← dfine_client (OPTIONAL — only if you want the remote-detector fallback)
app/api/                ← factories, sites, cameras*, zones, rules, control*, reports,
                          recordings, __init__
checkpoints/            ← dfine_l_obj2coco.onnx, siglip2_*.onnx(.data), siglip2_labels.*,
                          trt_cache/ (or let TRT rebuild on first run)
tools/                  ← export_dfine_onnx, export_siglip_onnx, warmup_trt,
                          verify_* (keep the offline ones), bench_overnight (optional)
```

`*` = keep the file but trim live-only bits:
- **`models.py`** — drop the `Alert` model.
- **`schemas.py`** — drop `AlertOut`.
- **`main.py`** — register only the kept routers; drop the `alerts.clip_path` migration.
- **`api/cameras.py`** — keep CRUD + `GET /frame`; drop `/start`, `/cancel`, `/live.mjpg`.
- **`api/control.py`** — keep `GET /cameras/{id}/metrics`; drop module/detector-tuning routes.

### DROP (live-only — never imported by the offline path)

```
app/realtime/           ← broadcaster, live_streams, __init__   (WS fanout, MJPEG pub/sub)
app/api/ws.py                                                   (WebSocket endpoint)
app/api/alerts.py                                              (alert CRUD)
app/workers/camera_worker.py                                  (live RTSP/file loop)
app/workers/registry.py                                       (running-worker registry)
app/workers/rule_engine.py                                    (alert firing)
app/workers/resting_clips.py + clip_extractor.py             (resting-worker clips)
```

After dropping, remove the corresponding `include_router(...)` lines and imports in
`main.py` (`ws`, `alerts`) and any `Alert`/`broadcaster` references.

### Result

~47 of ~65 backend modules. No Redis, Celery, MediaMTX, or MinIO. PostgreSQL is the only
datastore; the GPU + ONNX checkpoints are the only heavy runtime dependency.

---

## 2. Backend — trimmed dependencies

Minimal `pyproject.toml` deps for the offline service:

```toml
dependencies = [
  "fastapi>=0.110", "uvicorn[standard]>=0.27",        # API (optional if CLI-only)
  "sqlalchemy[asyncio]>=2.0.25", "asyncpg>=0.29",      # DB
  "pydantic>=2.5", "pydantic-settings>=2.1",           # config + schemas
  "opencv-python-headless>=4.9", "numpy>=1.26",         # video I/O + arrays
  "shapely>=2.0",                                       # zone polygons
  "supervision>=0.22", "scipy>=1.13",                  # ByteTrack + pipeline
  "onnxruntime-gpu>=1.17",                              # D-FINE / SigLIP inference
  "fpdf2>=2.8", "matplotlib>=3.8",                     # PDF reports
  "tzdata>=2024.1",                                     # factory_tz on Windows
  "watchfiles>=0.20",                                  # the drop-folder watcher
  "httpx>=0.26",                                       # remote detector/VLM fallback (optional)
]
```

Plus NVIDIA runtime wheels for the GPU EP (`nvidia-cudnn-cu12`, `nvidia-cublas-cu12`,
`tensorrt-cu12`, …) per the ORT version. **Drop**: `python-multipart` (only the upload
endpoint), `alembic` (schema via `create_all`), `requests`.

**Torch / transformers are EXPORT-time only** — needed to regenerate the ONNX checkpoints
(`tools/export_*.py`), not for inference. A lean inference box ships the pre-exported
`checkpoints/` and omits them.

---

## 3. Frontend — keep / drop

### KEEP
```
api/client.ts          routes.tsx          main.tsx   index.html
state/AppContext.tsx*   styles.css   theme.css   vite.config.ts   tsconfig.json   package.json
layout/                ← AppShell*, NavTree, Breadcrumb, BottomNav, CommandPalette
ui/                    ← ALL except Hud.tsx
features/factories/    ← FactoriesPage, FactoryPage
features/sites/        ← SitePage
features/cameras/      ← CameraPage* (drop Live tab), CameraContext, CameraCreatePage,
                         CameraStatusBadge, ZonesTab, PolygonSvg, RulesTab,
                         MetricsBreakdown, ZoneCard, AnalysisPanel, ZoneOccupancyPanel
features/dashboard/    ← DashboardPage* (drop live thumbs), WorkforceOverview, aggregateMetrics
features/reports/      ← ReportsPage, StaffingTimelineChart
features/recordings/   ← RecordingsPage
```

### DROP (live-only)
```
hooks/useEventsWS.ts (extract its TYPES first), useCameraState.ts, useTrackHistory.ts
ui/Hud.tsx
features/cameras/LiveTab.tsx, LiveZonesOverlay.tsx, TrackTimeline.tsx, AlertsTab.tsx
features/alerts/        ← AlertsPage, AlertCard
```

### Edits after copying
1. **Extract shared types.** Move `MetricsSummary`, `ZoneOccupancy`, `ZoneActivity` from
   `hooks/useEventsWS.ts` into `api/metrics.ts`; repoint the 6 importers (ZoneCard,
   MetricsBreakdown, AnalysisPanel, ZoneOccupancyPanel, WorkforceOverview, aggregateMetrics,
   and client.ts).
2. **AppContext** — remove the `useEventsWS()` call and alert state; no WS connection.
3. **AppShell** — remove the WS status indicator.
4. **CameraPage / routes** — remove the `live` tab + default to `zones`.
5. **DashboardPage** — replace live MJPEG thumbs with a static frame (`/cameras/{id}/frame`)
   or a placeholder.
6. **client.ts** — drop `liveUrl`, `startCamera`/`cancelCamera` (optional), `setCameraModules`,
   and all `*Alert*` methods.

`package.json` deps are unchanged (unused ones simply aren't bundled). The `/api → :8002`
proxy in `vite.config.ts` is needed.

---

## 4. Setup

1. **PostgreSQL** reachable via `DATABASE_URL`. Schema is created automatically
   (`Base.metadata.create_all` + the idempotent `ALTER`s in `main.py`, also run by the CLI).
2. **Checkpoints** in `backend/checkpoints/` — copy the pre-exported ONNX files, or
   regenerate: `python tools/export_dfine_onnx.py` and `python tools/export_siglip_onnx.py`
   (these need torch + transformers). Optionally `python tools/warmup_trt.py` to prebuild the
   TensorRT engine cache.
3. **`.env`** (minimum):
   ```bash
   DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/arktrack
   FACTORY_TZ=Europe/Sofia              # NVR stamps are factory-local
   OFFLINE_DROP_DIR=/mnt/nvr/incoming
   OFFLINE_REPORT_DIR=/mnt/reports
   # remote fallbacks (only if not using local checkpoints):
   # DFINE_URL=...   DFINE_API_KEY=...   QWEN_BASE_URL=...   QWEN_MODEL=...
   ```
4. **Bootstrap data**: create one Factory + Site (the single-site MVP assumes one exists;
   `ingest.default_site_id` raises otherwise). Cameras are then auto-created per NVR label on
   first ingest.

---

## 5. Run

```bash
# Unattended overnight: watch the drop folder (run under a service — NSSM / systemd / Task Scheduler)
python -m app.offline watch

# Or one-shot
python -m app.offline --tz Europe/Sofia run

# REST API for the operator UI
uvicorn app.main:app --host 0.0.0.0 --port 8002

# Frontend
npm install && npm run dev          # dev (proxies to :8002)
npm run build                       # production bundle → dist/
```

Operator flow: factory PC drops files → `watch` ingests + processes → they appear in
**Recordings** → draw **Zones** / set **Rules** on the auto-created cameras → reprocess if
needed → read **Reports** (day/week/month, in-app + PDF).

---

## 6. Suggested standalone layout

```
arktrack-offline/
├── backend/
│   ├── app/{config,db,models,schemas,main}.py
│   ├── app/offline/*          app/pipeline/*
│   ├── app/workers/{frame_sampler,metrics,zone_filter}.py
│   ├── app/storage/media.py   app/inference/dfine_client.py (optional)
│   ├── app/api/{factories,sites,cameras,zones,rules,control,reports,recordings}.py
│   ├── checkpoints/           tools/{export_*,warmup_trt,verify_*}.py
│   ├── pyproject.toml         .env
│   └── data/{incoming,reports}/
└── frontend/                  ← keep-list from §3
```

---

## 7. Known follow-ups for the standalone

- **Batch alerts** — wire `rule_engine` + alert persistence into `runner.py` (with real
  recorded timestamps) if event/clip generation from footage is wanted. Deferred here.
- **Shift windows** — `build_period_summary` is range-generic; add a shift bound helper +
  `period="shift"` when shift schedules are defined.
- **Multi-factory** — `ingest.default_site_id` assumes one site; add `--site`/`--factory`
  routing for multi-tenant.
- **Throughput** — downscale the welding-flash MOG2 pass (the profiled bottleneck) to fit
  more cameras per GPU (see `tools/bench_overnight.py`).
- **factory_tz** — must be set to the real factory timezone; the demo data used UTC.
