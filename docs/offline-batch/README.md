# ArkTrack — Offline Batch Analyzer

> Documentation set for the **overnight batch analysis** version of ArkTrack, written so it can be lifted out into its **own standalone project**.

A factory PC records all camera footage and ships the files to an office GPU box. The
box ingests each recording, runs it through the AI pipeline **headless**, stores
per-camera workforce metrics anchored to the **real recorded time**, and produces
**day / week / month** analysis — both as an in-app interactive view and as a
downloadable PDF. Operators still draw **per-camera zones** and configure **rules**
(count thresholds, etc.) that shape the reports.

The core value proposition is unchanged from live ArkTrack: **operators see meaning,
not footage.** What changes is the trigger — recorded files crunched overnight,
instead of live RTSP streams.

```
┌─────────────┐   recordings (mp4, NVR-named)   ┌──────────────────────────────────┐
│ Factory PC  │ ───────────────────────────────►│  Office GPU box (this project)    │
│ (NVR record)│   gigabit / file copy           │                                   │
└─────────────┘                                  │  data/incoming/  ← watch folder   │
                                                 │      │ ingest (parse name → cam)  │
                                                 │      ▼                            │
                                                 │  CameraPipeline (headless)        │
                                                 │   D-FINE-L → ByteTrack → welding  │
                                                 │   → SigLIP VLM → activity         │
                                                 │      │                            │
                                                 │      ▼  metric_samples (10s, UTC) │
                                                 │  Postgres ── reports (day/wk/mo)  │
                                                 │      │           JSON + PDF        │
                                                 │      ▼                            │
                                                 │  React operator UI / REST / CLI   │
                                                 └──────────────────────────────────┘
```

## Documentation index

| Doc | What it covers |
|---|---|
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | End-to-end data flow, the offline package, the AI pipeline internals (detection/tracking/welding/VLM/activity/metrics), the data model, and configuration. |
| **[API.md](API.md)** | REST endpoints, the CLI, the NVR filename contract, and the metric/report data shapes. |
| **[FRONTEND.md](FRONTEND.md)** | The React operator UI — pages, reused components, data flow, and styling tokens. |
| **[EXTRACTION.md](EXTRACTION.md)** | The keep/drop file inventory and a step-by-step guide to carve this into a standalone repo, plus setup & run. |

## What's in scope vs. deferred

**In scope (this version):**
- Folder-drop ingest + auto-processing of recorded files (watcher / CLI).
- Full AI pipeline reuse (D-FINE-L detection, ByteTrack, welding-arc, SigLIP VLM activity) run headless.
- Metrics anchored to real recorded wall-clock time → accurate daily timeline.
- Per-camera **zones** (monitored + excluded) and **rules** (count thresholds feed reports).
- **Day / week / month** reports: interactive in-app + PDF download.
- Operator UI: navigate factories→sites→cameras, browse the recordings ledger, author zones/rules, view reports.

**Deferred (intentionally out of scope here):**
- Batch **alert/event** generation from footage (resting-worker clips, detection alerts). The metrics path is built; alert evaluation in the offline runner is a later phase.
- **Shift-window** reports (only day/week/month).
- Live RTSP streaming, MJPEG, WebSocket state feed, live alerting — these belong to the live ArkTrack and are **not needed** here (see [EXTRACTION.md](EXTRACTION.md) for the drop list).

## Quickstart (against the current repo)

```bash
# backend (from backend/, with the venv active)
#   1. Postgres must be reachable per DATABASE_URL (.env)
#   2. model checkpoints present in backend/checkpoints/ (see ARCHITECTURE.md)

# one-shot: ingest every new file in data/incoming, then report each day touched
python -m app.offline run --tz Europe/Sofia

# unattended: watch the drop folder forever
python -m app.offline watch

# generate a specific report
python -m app.offline report --date 2026-03-06 --period week

# serve the API (powers the operator UI)
uvicorn app.main:app --host 127.0.0.1 --port 8002

# frontend (from frontend/)
npm run dev        # vite on :5173, proxies /api → :8002
```

Then open `http://localhost:5173`, pick a factory, and use its **Reports** and
**Recordings** views.

## Status

All of the above is **shipped and verified** on real factory footage on the
`offline-app` branch (currently uncommitted). Verification scripts live in
`backend/tools/verify_*.py` (synthetic, no GPU needed for the report layer).
