"""Apples-to-apples latency benchmark for DfineDetector.

Reads ~200 real frames from a sample MP4, runs N detections per provider, and
reports min/median/p95 latency. Compares "tensorrt" vs "cuda" so the user can
see whether flipping the EP actually buys anything on real footage.

Run from backend/:
    ./.venv/Scripts/python.exe tools/bench_dfine.py
    ./.venv/Scripts/python.exe tools/bench_dfine.py --eps cuda tensorrt
    ./.venv/Scripts/python.exe tools/bench_dfine.py --video data/uploads/<id>.mp4
"""
from __future__ import annotations

import argparse
import statistics
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app.pipeline  # noqa: E402,F401
from dfine_detector import DfineDetector  # noqa: E402


def load_frames(video_path: Path, n: int) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise SystemExit(f"could not open {video_path}")
    frames: list[np.ndarray] = []
    while len(frames) < n:
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(frame)
    cap.release()
    if not frames:
        raise SystemExit("no frames decoded")
    return frames


def bench(
    ep: str,
    onnx: Path,
    frames: list[np.ndarray],
    warmup: int,
    iters: int,
    concurrent: int = 1,
    detectors: int = 1,
) -> dict:
    print(f"\n--- {ep.upper()} EP (concurrent={concurrent}, detectors={detectors}) ---")
    t0 = time.time()
    dets_list: list[DfineDetector] = []
    for di in range(detectors):
        d = DfineDetector(onnx_path=str(onnx), execution_provider=ep)
        dets_list.append(d)
    t_load = time.time() - t0
    print(f"  init: {t_load:.2f}s for {detectors} detector(s)  active providers: {dets_list[0].active_providers}")

    # Warm-up each detector instance independently.
    for d in dets_list:
        for i in range(warmup):
            d.detect(frames[i % len(frames)])

    timings_ms: list[float] = []
    total_dets = [0]
    timings_lock = threading.Lock()

    def worker(tid: int) -> None:
        # Round-robin: thread N uses detector N % len(dets_list). When
        # detectors == concurrent, each thread gets its own (production
        # current state). When detectors == 1, all threads share (post-fix).
        det = dets_list[tid % len(dets_list)]
        local_timings: list[float] = []
        local_dets = 0
        # Stagger thread starts so they don't fire the first call at the
        # same wall-clock millisecond, which would underestimate steady-state.
        time.sleep(0.001 * tid)
        for i in range(iters):
            f = frames[(tid * 7 + i) % len(frames)]
            t = time.perf_counter()
            dets = det.detect(f)
            local_timings.append((time.perf_counter() - t) * 1000.0)
            local_dets += len(dets)
        with timings_lock:
            timings_ms.extend(local_timings)
            total_dets[0] += local_dets

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(concurrent)]
    wall_t = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall_s = time.perf_counter() - wall_t
    calls = concurrent * iters
    throughput = calls / wall_s if wall_s > 0 else 0.0

    return {
        "ep": ep,
        "concurrent": concurrent,
        "detectors": detectors,
        "active": dets_list[0].active_providers,
        "load_s": round(t_load, 2),
        "n": calls,
        "wall_s": round(wall_s, 2),
        "throughput_hz": round(throughput, 1),
        "min_ms": round(min(timings_ms), 1),
        "median_ms": round(statistics.median(timings_ms), 1),
        "p95_ms": round(statistics.quantiles(timings_ms, n=20)[-1], 1),
        "max_ms": round(max(timings_ms), 1),
        "avg_dets": round(total_dets[0] / max(1, calls), 2),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--video", default="data/uploads/91289e20-e62c-40b2-a24d-6aa7e9f33842.mp4")
    p.add_argument("--onnx", default="checkpoints/dfine_l_obj2coco.onnx")
    p.add_argument("--n-frames", type=int, default=200)
    p.add_argument("--warmup", type=int, default=10)
    p.add_argument("--iters", type=int, default=200, help="iterations per worker thread")
    p.add_argument("--eps", nargs="+", default=["cuda", "tensorrt"])
    p.add_argument(
        "--concurrent", type=int, default=1,
        help="number of Python threads calling detect() in parallel",
    )
    p.add_argument(
        "--detectors", type=int, default=1,
        help="number of independent DfineDetector instances (each its own ORT session). "
             "Threads are assigned round-robin; pass --detectors == --concurrent to "
             "simulate the current per-camera ownership.",
    )
    args = p.parse_args()

    video = ROOT / args.video
    onnx = ROOT / args.onnx
    print(f"video: {video}  onnx: {onnx}  iters: {args.iters}")
    frames = load_frames(video, args.n_frames)
    print(f"loaded {len(frames)} frames  shape={frames[0].shape}")

    results = []
    for ep in args.eps:
        try:
            results.append(bench(ep, onnx, frames, args.warmup, args.iters, args.concurrent, args.detectors))
        except Exception as exc:
            print(f"  {ep} bench failed: {exc}")
            results.append({"ep": ep, "error": str(exc)})

    print("\n=== SUMMARY ===")
    print(
        f"{'ep':<10} {'thr':>4} {'det':>4} {'min':>7} {'median':>7} {'p95':>7} {'max':>7} "
        f"{'hz':>7} {'load_s':>7} {'avg_dets':>9}"
    )
    for r in results:
        if "error" in r:
            print(f"{r['ep']:<10}  ERROR  {r['error']}")
            continue
        print(
            f"{r['ep']:<10} {r['concurrent']:>4} {r['detectors']:>4} "
            f"{r['min_ms']:>7} {r['median_ms']:>7} "
            f"{r['p95_ms']:>7} {r['max_ms']:>7} {r['throughput_hz']:>7} "
            f"{r['load_s']:>7} {r['avg_dets']:>9}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
