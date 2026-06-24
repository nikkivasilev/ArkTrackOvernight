# ArkTrack Monitoring Platform

Real-time factory video monitoring. Upload an MP4 (or point at an RTSP camera), draw polygon zones, and watch the live annotated feed plus workforce + per-zone occupancy metrics stream into the React UI.

Detection runs **in-process on the local GPU**: D-FINE-L via ONNX Runtime + **TensorRT FP16** (~14 ms/frame on an RTX 3080), ByteTrack for tracking, welding-arc + phantom-welder detection, and a remote **Qwen3-next VLM** for activity classification.

See `CLAUDE.md` for the full project brief.

---

## TL;DR — run it (everything already set up)

On this machine the Python venv, the D-FINE ONNX model, and the TensorRT engine cache are already in place. Three terminals (or run the first two in the background):

```powershell
# 1. Postgres (from the project root). Exits on reboot — just re-run it.
docker compose up -d postgres

# 2. Backend (from backend/). NOTE: no --reload on Windows — it hangs the worker.
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8002

# 3. Frontend (from frontend/)
cd frontend
npm run dev
```

Then open **<http://localhost:5173>**.

Health check: <http://localhost:8002/health> → `{"status":"ok"}`.

> If a terminal closes, that service stops. Postgres (Docker) survives terminal close but not a host reboot — re-run step 1 after rebooting.

---

## Ports & services

| Service | URL / port | Notes |
|---|---|---|
| Frontend (Vite) | `http://localhost:5173` | bound to `127.0.0.1`; proxies `/api` + `/api/ws` → backend |
| Backend (FastAPI) | `http://localhost:8002` | **not 8000** — 8000/8001 were taken on this box |
| Postgres | `localhost:5433` | container `bestfactor-postgres`, image `postgres:16`; host **5433** → container 5432 (a native Postgres owns 5432) |
| Qwen VLM (remote) | `QWEN_BASE_URL` in `backend/.env` | currently `http://192.168.0.33:8000/v1` (a box with its own GPU) |

Tables are auto-created on backend startup (`Base.metadata.create_all` + idempotent `ALTER`s in `app/main.py` lifespan). No Alembic migration step.

---

## Configuration — `backend/.env`

Already populated. The keys that matter:

```ini
# Postgres on host port 5433 (see ports table)
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/bestfactor

# Detection confidence floor for D-FINE-L
DFINE_DEFAULT_CONF=0.4

# Remote Qwen3-next VLM (vision-capable). Must be reachable from this box.
QWEN_BASE_URL=http://192.168.0.33:8000/v1
QWEN_MODEL=/models/qwen3-next

CORS_ORIGINS=["http://localhost:5173"]
DEFAULT_SAMPLING_FPS=8.0
```

`DFINE_URL` / `DFINE_API_KEY` are kept as a remote-detector fallback but are unused while detection runs locally (`yolo_source_active="dfine-l"` in `app/pipeline/runtime.py`).

If the VLM endpoint is unreachable, detection/tracking still work — activity labels just fall back to the motion heuristic (`walking`/`standing`/`unknown` + `welding` from arc attribution). Failed VLM calls log `vlm classify failed in N ms: ...`. Other working endpoints found on the network: `http://10.0.0.2:8000/v1`, `http://192.168.0.45:8080/v1`, `http://10.0.0.4:8080/v1` (the last two are local to this box and get GPU-starved by D-FINE under load — prefer the remote `.33`).

---

## Using the app

1. Open <http://localhost:5173> → **Factories → site → camera** (or create a camera and upload an MP4).
2. **Start** the camera (button on the camera page). Status goes `queued → running`.
3. **Live** tab: annotated MJPEG feed, per-track table, **Workflow analysis** (working/moving/idle split over a window), and **Zone occupancy** (per-zone time-at-each-headcount, with a query-time "understaffed (< N people)" selector).
4. **Zones** tab: scrub to a frame, click polygon vertices, double-click to close, name it. Mark a zone **"not monitored"** to exclude its region from detection/metrics; monitored zones feed the zone-occupancy panel.
5. Zone metrics survive a restart — they're flushed to the `metric_samples` table every 60 s and the panel's `24h` window reads from there.

> First start of any camera builds/loads the TensorRT engine. With the cache already on disk this takes a couple of seconds; a cold cache takes ~6 min (see first-time setup).

---

## First-time setup (fresh machine only)

Skip this on the current box — it's done. Needed only on a clean checkout.

**Prerequisites:** Python 3.11+ (3.13 here), Node 18+, Docker Desktop, an NVIDIA GPU + recent driver (for TensorRT), and reachability to a Qwen3-next VLM.

```powershell
# Backend deps
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
# GPU inference stack (Windows / CUDA 12):
.\.venv\Scripts\python.exe -m pip install onnxruntime-gpu==1.26.0 ^
  nvidia-cudnn-cu12 nvidia-cublas-cu12 nvidia-cuda-runtime-cu12 ^
  nvidia-cuda-nvrtc-cu12 nvidia-cufft-cu12 nvidia-nvjitlink-cu12
# TensorRT 10 — MUST be <11 (ORT 1.26 links nvinfer_10.dll; pip defaults to 11.x)
.\.venv\Scripts\python.exe -m pip install "tensorrt-cu12<11"

# D-FINE-L ONNX (one-time export from HuggingFace; needs torch+transformers,
# installable temporarily then removable). Produces checkpoints/dfine_l_obj2coco.onnx
.\.venv\Scripts\python.exe tools\export_dfine_onnx.py

# Build the TensorRT engine cache up front (~6 min first run; cached after).
.\.venv\Scripts\python.exe tools\warmup_trt.py

# Frontend deps
cd ..\frontend
npm install
```

`copy ..\.env.example ..\backend\.env` then edit `DATABASE_URL` (port 5433) and `QWEN_BASE_URL`.

---

## Project layout

```
ArkTrackRefined/
  docker-compose.yml            postgres only (5433:5432)
  backend/
    .env                        (gitignored) DB + VLM + conf
    pyproject.toml
    checkpoints/
      dfine_l_obj2coco.onnx      D-FINE-L model (~120 MB)
      trt_cache/                 TensorRT engine + timing cache (per GPU/shape)
    tools/
      export_dfine_onnx.py       one-time ONNX export
      warmup_trt.py              build the TRT engine cache
      bench_dfine.py             cuda-vs-tensorrt latency bench
    app/
      main.py                    FastAPI app + lifespan (create_all + ALTERs + stale-camera reconcile)
      models.py                  Camera, Zone, Rule, Alert, MetricSample
      api/                        cameras, zones, rules, alerts, control, ws, ...
      pipeline/                   vendored detection pipeline (D-FINE + ByteTrack + welding + VLM + zones)
        runtime.py               CameraPipeline (per-camera) + shared detector + zone wiring
        pipeline_render.py       annotated frame + per-zone occupancy counts → state["zones"]
        dfine_detector.py        ONNX Runtime + TensorRT FP16 detector
        vlm_classifier.py        Qwen3-next activity classifier
      workers/
        camera_worker.py         one asyncio task per camera; drives the pipeline
        metrics.py               MetricsAggregator → metric_samples (incl. zone occupancy histogram)
        rule_engine.py           legacy alert rules (detection / count_min / count_max)
    data/                        (gitignored) uploads/ + alerts/ thumbnails
  frontend/
    src/features/cameras/        LiveTab (feed + AnalysisPanel + ZoneOccupancyPanel), ZonesTab, ...
```

---

## Troubleshooting

- **Backend won't start, `ConnectionRefused`** → Postgres isn't up. `docker compose up -d postgres`. After a reboot the container is `Exited` — same command restarts it.
- **Don't use `uvicorn --reload` on Windows** → it logs "Reloading…" then hangs the worker child. Restart manually after backend edits.
- **Port 8002 already in use** (orphan from a killed uvicorn) → find + kill: `netstat -ano | findstr :8002` then `taskkill /PID <pid> /F`.
- **Cameras stuck `running` after a restart** → worker tasks don't survive a backend restart; on startup the app sweeps stale `running`/`queued` cameras to `cancelled`. Just press **Start** again.
- **First camera start is slow / GPU log mentions building** → TensorRT is compiling the engine (~6 min cold). Run `tools\warmup_trt.py` once to pre-build; afterwards it loads from `checkpoints/trt_cache/` in seconds. The cache invalidates if you re-export the ONNX, change GPU, or bump TensorRT major version.
- **No activity labels / `vlm classify failed` in the log** → the Qwen VLM at `QWEN_BASE_URL` is unreachable or overloaded. Detection still works; point `QWEN_BASE_URL` at a reachable endpoint and restart.
- **Frontend can't reach the API** → it proxies to `:8002`; confirm the backend is up and `vite.config.ts` still targets 8002.

---

## Known limits

- **Auth: none** — single-operator deployment.
- **Alerts** are minimal: only `detection`, `count_min`, `count_max` rule triggers evaluate; `duration` / `absence` / `resting_worker` are stubs, and count rules have no sustained-duration hysteresis. The product focus is **detection metrics** (workforce + zone occupancy), not alerting.
- **Clips**: an alert captures a single thumbnail frame, not a video clip.
- Detection backbone, tracking, motion/pose subsystems and other locked MVP decisions are documented in `CLAUDE.md`.
