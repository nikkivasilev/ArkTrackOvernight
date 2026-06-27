# CLAUDE.md — ArkTrack Monitoring Platform

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## What This Project Is

ArkTrack analyses factory video with an in-process AI pipeline (D-FINE-L detection →
ByteTrack tracking → activity / VLM classification → polygon zones) and turns it into
workforce and per-zone occupancy/activity metrics. The core value proposition:
**operators see meaning, not footage.**

The workflow is **overnight batch analysis → reports**:

- **Offline batch** — `app.offline` ingests recordings dropped into a watched folder,
  runs each through the pipeline (`app.pipeline.runtime.CameraPipeline`) headless,
  writes metrics to Postgres, and generates per-day / per-period **PDF reports**.
  Cameras are created automatically from the NVR filenames.
- **Web app** (React + FastAPI) — view the analysis: a **Dashboard** (factory-wide
  workforce analytics over day/week/month or any custom date range, with PDF export),
  per-camera **Analysis** (workforce + per-zone breakdowns, read from the persisted
  `metric_samples`), and the ingest **Recordings** ledger. It is also where you
  **configure**: draw polygon **Zones** and assign **Rules** to cameras/zones.

One FastAPI app + one Postgres database back both. Rules are stored as configuration
(zone/rule assignment); rule *evaluation* / alerting is not implemented. There is no
live feed — the real-time camera path was removed; analysis is read from stored metrics.


---

## Decisions Locked for MVP

| Decision | Choice | Reason |
|---|---|---|
| Detection backbone | ✅ D-FINE-L 
| Pose model | ✅ RTMPose (MMPose, Apache-2.0 ONNX) |  Top-down: annotates D-FINE bboxes with COCO-17 keypoints. Off by default until the ONNX checkpoint is placed. |
| Tracking | ✅ ByteTrack (supervision) + ID Recovery | Motion-only tracker, supplemented by HSV-histogram tracker stitching across short losses. |
| Motion subsystem | ✅ MOG2 + Norfair every-frame | Ported from ark-track. Fills gaps when detection is gated; supports stillness re-confirm. |
| Stillness re-confirm | ✅ Synthetic dets via patch-sig | Keeps stationary workers' tracks alive when the detector misses them but pixels haven't changed. |
| Phantom welders | ✅ Synthetic + grace period | Synthesises a person detection at orphan-arc centroids; survives `PHANTOM_GRACE_SECONDS` of arc-off so brief tip-ups don't blink the welder out. |
| Zone drawing 
| Floor plan upload 
| Rule editor | ✅ Structured form only | Predictable, fast to build, debuggable |
| Source types | ✅ RTSP + file upload | Every real IP camera speaks RTSP; file for testing |
| Sampling config | ✅ Presets only (Low/Medium/High) | No custom config exposed to user |
---

## Tech Stack

### Backend
- **Language**: Python 3.11+
- **API Framework**: FastAPI (async throughout)
- **Detection**: D-FINE-L in-process via ONNX Runtime (CPU by default; CUDA / TensorRT FP16 optional execution providers)
- **Tracking**: ByteTrack (supervision) + HSV-histogram ID recovery
- **Activity classification**: local SigLIP (ONNX, default) or a remote Qwen VLM over HTTP (optional)
- **Video I/O**: OpenCV — uploaded files + RTSP, read directly (no separate stream server)
- **Database**: PostgreSQL via SQLAlchemy 2.0 async + asyncpg
- **Schema**: `Base.metadata.create_all` + idempotent `ALTER`s at startup (no migration tool)
- **Storage**: local filesystem under `backend/data/` (uploads, alert thumbnails, generated PDF reports)
- **Offline batch / reports**: `app.offline` (folder ingest → headless pipeline → metrics → PDF via fpdf2 + matplotlib)
- **Real-time**: FastAPI native WebSockets + in-process broadcaster
- **Auth**: none (single-operator deployment)

### Frontend
- **Framework**: React 18 + Vite

