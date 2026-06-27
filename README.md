# ArkTrack Monitoring Platform

Overnight batch analysis of factory video. Drop NVR recordings into a watched folder; the offline pipeline crunches them into workforce + per-zone occupancy/activity metrics and PDF reports. The React UI is for **viewing** the analysis (Dashboard analytics + per-camera Analysis) and **configuring** polygon zones + rules.

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
```

`DFINE_URL` / `DFINE_API_KEY` are kept as a remote-detector fallback but are unused while detection runs locally (`yolo_source_active="dfine-l"` in `app/pipeline/runtime.py`).

If the VLM endpoint is unreachable, detection/tracking still work — activity labels just fall back to the motion heuristic (`walking`/`standing`/`unknown` + `welding` from arc attribution). Failed VLM calls log `vlm classify failed in N ms: ...`. Other working endpoints found on the network: `http://10.0.0.2:8000/v1`, `http://192.168.0.45:8080/v1`, `http://10.0.0.4:8080/v1` (the last two are local to this box and get GPU-starved by D-FINE under load — prefer the remote `.33`).

---

## Using the app

1. **Ingest footage (the overnight batch).** Drop NVR recordings into the watched folder (`backend/data/incoming` by default) and run the offline pipeline from `backend/`:
   ```powershell
   .\.venv\Scripts\python.exe -m app.offline run     # ingest new files + build reports
   # or keep watching the folder:
   .\.venv\Scripts\python.exe -m app.offline watch
   ```
   Cameras are created automatically from the NVR filenames; metrics land in `metric_samples`.
2. Open <http://localhost:5173> → **Factories → site → camera**.
3. **Analysis** tab: **Workflow analysis** (working/moving/idle split) and **Zone breakdown** (per-zone occupancy + activity, with a query-time "understaffed (< N people)" selector), over a selectable 24h / 7d / 30d range — read from the persisted `metric_samples`.
4. **Zones** tab: scrub to a frame, click polygon vertices, double-click to close, name it. Mark a zone **"not monitored"** to exclude its region; monitored zones feed the zone breakdown.
5. **Rules** tab: assign detection/count rules to a camera or zone (stored as configuration).
6. **Dashboard**: factory-wide analytics — KPIs, staffing timeline, activity + per-zone breakdowns over day/week/month or a custom date range, with **PDF export**. (Or render a PDF from the CLI: `python -m app.offline report --date YYYY-MM-DD --period day|week|month`.)

> The first detection run builds/loads the TensorRT engine cache (if the TRT execution provider is selected). With the cache already on disk this takes a couple of seconds; a cold cache takes ~6 min (see first-time setup).

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
      main.py                    FastAPI app + lifespan (create_all + idempotent ALTERs)
      models.py                  Camera, Zone, Rule, MetricSample, ProcessedRecording
      api/                        cameras, zones, rules, control (metrics), reports, recordings, factories, sites
      offline/                   overnight batch: folder ingest → headless pipeline → metrics → PDF reports
      pipeline/                   vendored detection pipeline (D-FINE + ByteTrack + welding + VLM + zones)
        runtime.py               CameraPipeline (per-camera) + shared detector + zone wiring
        pipeline_render.py       annotated frame + per-zone occupancy counts → state["zones"]
        dfine_detector.py        ONNX Runtime + TensorRT FP16 detector
        vlm_classifier.py        Qwen activity classifier (SigLIP is the default backend)
      workers/
        metrics.py               MetricsAggregator → metric_samples (incl. zone occupancy histogram)
        frame_sampler.py         video probe + frame sampling (shared by offline + zone editor)
        zone_filter.py           per-zone membership filtering
    data/                        (gitignored) incoming/ (drop folder) + reports/ (generated PDFs)
  frontend/
    src/features/cameras/        AnalysisTab (AnalysisPanel + ZoneOccupancyPanel), ZonesTab, RulesTab
```

---

## Troubleshooting

- **Backend won't start, `ConnectionRefused`** → Postgres isn't up. `docker compose up -d postgres`. After a reboot the container is `Exited` — same command restarts it.
- **Don't use `uvicorn --reload` on Windows** → it logs "Reloading…" then hangs the worker child. Restart manually after backend edits.
- **Port 8002 already in use** (orphan from a killed uvicorn) → find + kill: `netstat -ano | findstr :8002` then `taskkill /PID <pid> /F`.
- **First offline run is slow / GPU log mentions building** → TensorRT is compiling the engine (~6 min cold). Run `tools\warmup_trt.py` once to pre-build; afterwards it loads from `checkpoints/trt_cache/` in seconds. The cache invalidates if you re-export the ONNX, change GPU, or bump TensorRT major version.
- **No activity labels / `vlm classify failed` in the log** → the Qwen VLM at `QWEN_BASE_URL` is unreachable or overloaded. Detection still works; point `QWEN_BASE_URL` at a reachable endpoint and restart.
- **Frontend can't reach the API** → it proxies to `:8002`; confirm the backend is up and `vite.config.ts` still targets 8002.

---

## Known limits

- **Auth: none** — single-operator deployment.
- **Rules: assignment only** — rules are stored as configuration (per camera or zone) but are **not evaluated**; there is no alerting. The product focus is **detection metrics** (workforce + zone occupancy).
- **No live view** — the real-time camera feed / WebSocket path was removed; the app analyses recorded footage via the overnight batch and shows the results.
- Detection backbone, tracking, motion/pose subsystems and other locked MVP decisions are documented in `CLAUDE.md`.
