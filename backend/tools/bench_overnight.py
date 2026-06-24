"""End-to-end throughput benchmark for the overnight-batch sizing question.

Drives the REAL CameraPipeline.process_frame (decode -> D-FINE-L TensorRT ->
ByteTrack -> SigLIP VLM -> welding/groups) over factory clips, sweeping K
concurrent pipelines to find where the single GPU saturates. The shared
detector (2-worker executor) and shared SigLIP singleton (2 inflight slots)
mean K concurrent pipelines faithfully model one-GPU contention -- so the
plateau of R(K) = "real-time camera-streams sustained" is the cameras-per-GPU
number we need to size 25 cameras x a full day.

Run from backend/:
    ./.venv/Scripts/python.exe tools/bench_overnight.py
    ./.venv/Scripts/python.exe tools/bench_overnight.py --ks 1,2,4,8,12 --full
    ./.venv/Scripts/python.exe tools/bench_overnight.py --novlm    # detection-only ceiling

Throughput is measured wall-to-wall INCLUDING draining inflight VLM, so the
VLM cost is captured even though it fires asynchronously. Warmup (TRT engine
load + first inferences) is excluded.
"""
from __future__ import annotations

import argparse
import asyncio
import math
import sys
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Cyrillic NVR filenames break the default cp1252 Windows console.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import app.pipeline  # noqa: E402,F401  (triggers CUDA/TRT DLL preload)
from app.pipeline.runtime import CameraPipeline  # noqa: E402
from app.workers.frame_sampler import iter_sampled, probe  # noqa: E402

DEFAULT_CLIPS = [
    r"C:/Users/Office2/Desktop/factory/cam2.mp4",
    r"C:/Users/Office2/Desktop/factory/IP Камера25_NVRserver_Montage_20260306095956_20260306100515_372917.mp4",
    r"C:/Users/Office2/Desktop/factory/IP Камера25_NVRserver_Montage_20260306101104_20260306101654_717413.mp4",
]


async def decode_ceiling(clip: str, target_fps: float, max_frames: int | None) -> float:
    """Single-thread decode throughput (frames/sec) with no inference. Tells us
    whether the 4 MP decode itself is a co-limiter vs. the GPU."""
    n = 0
    t0 = time.perf_counter()
    async for _idx, _t, _frame in iter_sampled(clip, target_fps):
        n += 1
        if max_frames and n >= max_frames:
            break
    dt = time.perf_counter() - t0
    return n / dt if dt > 0 else 0.0


async def run_stream(
    clip: str, target_fps: float, max_frames: int | None, novlm: bool, headless: bool,
    noweld: bool,
) -> tuple[CameraPipeline, int, float, int]:
    """Drive one full pipeline over a clip as fast as possible.

    Returns (pipeline, frames_processed, footage_seconds, person_frame_count).
    Pipeline is returned (not closed) so the caller can drain its VLM tasks
    before stopping the clock.
    """
    p = CameraPipeline(camera_id=uuid4(), target_fps=target_fps)
    if headless:
        p.headless = True  # skips JPEG render/encode + overlay drawing
    if noweld:
        p.welding_enabled = False  # _detect_flashes returns early (no MOG2)
    if novlm:
        p.vlm = None  # _maybe_fire_vlm short-circuits on `self.vlm is None`
    n = 0
    occ = 0
    async for idx, t_video, frame in iter_sampled(clip, target_fps):
        try:
            out = await p.process_frame(frame, idx, t_video)
        except Exception as exc:  # one bad frame shouldn't kill the sweep
            print(f"  [warn] process_frame failed: {exc}")
            out = None
        if out is not None and getattr(out, "state", None):
            tracks = out.state.get("tracks") or []
            occ += sum(1 for tr in tracks if not tr.get("ghost"))
        n += 1
        if max_frames and n >= max_frames:
            break
    footage_s = n / target_fps if target_fps > 0 else 0.0
    return p, n, footage_s, occ


async def drain_vlm(timeout: float = 60.0) -> None:
    me = asyncio.current_task()
    pend = [
        t for t in asyncio.all_tasks()
        if t is not me and t.get_name().startswith("vlm-")
    ]
    if pend:
        await asyncio.wait(pend, timeout=timeout)


async def sweep(
    k: int, clips: list[str], target_fps: float, max_frames: int | None, novlm: bool,
    headless: bool, noweld: bool,
) -> dict:
    assignments = [clips[i % len(clips)] for i in range(k)]
    t0 = time.perf_counter()
    results = await asyncio.gather(
        *[run_stream(a, target_fps, max_frames, novlm, headless, noweld) for a in assignments]
    )
    await drain_vlm()
    wall = time.perf_counter() - t0

    pipes = [r[0] for r in results]
    frames = sum(r[1] for r in results)
    footage = sum(r[2] for r in results)
    occ = sum(r[3] for r in results)
    for p in pipes:
        try:
            p.close()
        except Exception:
            pass

    return {
        "k": k,
        "wall_s": wall,
        "frames": frames,
        "footage_s": footage,
        "fps": frames / wall if wall > 0 else 0.0,
        "realtime_streams": footage / wall if wall > 0 else 0.0,  # R(K)
        "avg_occ": occ / frames if frames else 0.0,
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", nargs="+", default=DEFAULT_CLIPS)
    ap.add_argument("--target-fps", type=float, default=8.0, help="analysis sampling fps (native is 8)")
    ap.add_argument("--ks", default="1,2,4,8", help="comma list of concurrency levels")
    ap.add_argument("--max-frames", type=int, default=720, help="frames per stream (720 ~= 90s @8fps); 0 = full clip")
    ap.add_argument("--full", action="store_true", help="process entire clips (overrides --max-frames)")
    ap.add_argument("--warmup", type=int, default=40)
    ap.add_argument("--novlm", action="store_true", help="disable SigLIP to measure detection-only ceiling")
    ap.add_argument("--headless", action="store_true", help="skip JPEG render/encode + overlay drawing (offline batch mode)")
    ap.add_argument("--noweld", action="store_true", help="disable MOG2 welding-flash detection (isolate its cost)")
    ap.add_argument("--cams", type=int, default=25)
    ap.add_argument("--shift-hours", type=float, default=12.0, help="hours of footage recorded per camera/day")
    ap.add_argument("--window-hours", type=float, default=14.0, help="overnight wall-clock processing window")
    args = ap.parse_args()

    ks = [int(x) for x in args.ks.split(",") if x.strip()]
    max_frames = None if args.full else (args.max_frames or None)

    print(f"clips ({len(args.clips)}):")
    for c in args.clips:
        try:
            info = probe(c)
            print(f"  {Path(c).name[:38]:40s} {info.width}x{info.height} {info.fps:.0f}fps {info.duration_s:.0f}s")
        except Exception as exc:
            print(f"  [error] {c}: {exc}")
            return 1
    mode = "FULL clips" if max_frames is None else f"{max_frames} frames/stream"
    print(f"sampling: {args.target_fps:.0f} fps | {mode} | "
          f"VLM={'OFF' if args.novlm else 'ON (siglip)'} | "
          f"render={'HEADLESS' if args.headless else 'ON'} | "
          f"weld={'OFF' if args.noweld else 'ON'}\n")

    # ---- Decode ceiling (single thread) -------------------------------------
    dec = await decode_ceiling(args.clips[0], args.target_fps, args.warmup * 4 or 160)
    print(f"decode ceiling (1 thread): {dec:.1f} fps  ->  {dec/args.target_fps:.1f}x real-time/stream\n")

    # ---- Warmup (TRT engine load + first inferences, excluded) --------------
    print("warming up (TRT engine load + first inferences)...")
    t0 = time.perf_counter()
    wp, *_ = await run_stream(args.clips[0], args.target_fps, args.warmup, args.novlm, args.headless, args.noweld)
    await drain_vlm()
    try:
        from app.pipeline.runtime import _shared_dfine_detector as det
        providers = getattr(det, "active_providers", "?")
    except Exception:
        providers = "?"
    wp.close()
    print(f"warmup done in {time.perf_counter()-t0:.1f}s | D-FINE providers: {providers}\n")

    # ---- Sweep ---------------------------------------------------------------
    print(f"{'K':>3} {'wall_s':>7} {'frames':>7} {'fps':>7} {'R=streams':>10} {'avg_occ':>8}")
    rows = []
    for k in ks:
        r = await sweep(k, args.clips, args.target_fps, max_frames, args.novlm, args.headless, args.noweld)
        rows.append(r)
        print(f"{r['k']:>3} {r['wall_s']:>7.1f} {r['frames']:>7} {r['fps']:>7.1f} "
              f"{r['realtime_streams']:>10.1f} {r['avg_occ']:>8.2f}")

    # ---- Extrapolation -------------------------------------------------------
    r_max = max(r["realtime_streams"] for r in rows)
    avg_occ = sum(r["avg_occ"] for r in rows) / len(rows)
    inc_gpus = math.ceil(args.cams / r_max) if r_max > 0 else float("inf")
    batch_need = args.cams * args.shift_hours / args.window_hours
    batch_gpus = math.ceil(batch_need / r_max) if r_max > 0 else float("inf")

    print("\n=== SIZING (per RTX 3080) ===")
    print(f"peak sustained: {r_max:.1f} real-time camera-streams / 3080   (avg occupancy {avg_occ:.2f} persons/frame)")
    print(f"incremental (process live as footage lands):")
    print(f"   {args.cams} cams / {r_max:.1f} = {args.cams/r_max:.1f}  ->  ceil = {inc_gpus} x 3080")
    print(f"batch (crunch {args.cams}x{args.shift_hours:.0f}h footage in a {args.window_hours:.0f}h window):")
    print(f"   need {batch_need:.1f} streams sustained / {r_max:.1f} = {batch_need/r_max:.1f}  ->  ceil = {batch_gpus} x 3080")
    print("\nNote: a 4090 ~ 2-2.5x a 3080, a 5090/L40S ~ 3-4x, for this FP16 workload.")
    print("VLM scales with occupancy; re-run --novlm to see its marginal cost, and on a busier clip for worst case.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
