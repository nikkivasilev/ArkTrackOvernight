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

A full-stack, real-time AI surveillance platform with two coexisting inference flows:

1. **General surveillance** D-FINE-L → anomaly score → rule match → conclusion. Trigger types: `detection`, `duration`, `count`, `absence`.
2. **Resting-worker detection** — D-FINE-L + ByteTrack → two-tier motion analysis → 3-second pre-incident clip → Qwen VLM verification → conclusion. Trigger type: `resting_worker`.

Both flows share the same FastAPI app, Postgres schema, Redis stream, Celery worker pool, WebSocket broadcaster, and React frontend. They diverge only at the detection worker (whose single frame decode is reused for both paths) and at their final Conclusion-creation step.

The core value proposition: **operators see meaning, not footage.**


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
- **Stream Server**: MediaMTX (RTSP + file relay)
- **Frame Queue**: Redis Streams
- **AI — Detection**: D-FINE-L (at server)
- **Task Queue**: Celery + Redis (clip extraction, email alerts)
- **Database**: PostgreSQL + TimescaleDB extension
- **ORM**: SQLAlchemy 2.0 async
- **Migrations**: Alembic
- **Storage**: MinIO (local dev) / S3-compatible (prod) — event clips + frame snapshots
- **Real-time**: FastAPI native WebSockets
- **Auth**: JWT (access + refresh tokens), bcrypt

### Frontend
- **Framework**: React 18 + Vite

