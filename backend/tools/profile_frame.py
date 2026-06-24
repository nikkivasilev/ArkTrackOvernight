"""cProfile of headless process_frame to find the single-thread CPU hog.

The render strip + VLM-off still cap throughput at ~17 fps, so the bottleneck is
synchronous main-thread work somewhere in process_frame. This profiles a single
headless pipeline (VLM off, so we isolate the deterministic CPU path) over N
frames and prints the top functions by tottime (self time on the main thread) —
detection runs in an executor thread so its internal time won't dominate here;
what shows up IS the loop-thread bottleneck.

Run from backend/:
    ./.venv/Scripts/python.exe tools/profile_frame.py --frames 250
"""
from __future__ import annotations

import argparse
import asyncio
import cProfile
import pstats
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import app.pipeline  # noqa: E402,F401
from app.pipeline.runtime import CameraPipeline  # noqa: E402
from app.workers.frame_sampler import iter_sampled  # noqa: E402

DEFAULT_CLIP = r"C:/Users/Office2/Desktop/factory/cam2.mp4"


async def drive(clip: str, n: int, target_fps: float) -> int:
    p = CameraPipeline(camera_id=uuid4(), target_fps=target_fps)
    p.headless = True
    p.vlm = None
    i = 0
    async for idx, t_video, frame in iter_sampled(clip, target_fps):
        await p.process_frame(frame, idx, t_video)
        i += 1
        if i >= n:
            break
    return i


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default=DEFAULT_CLIP)
    ap.add_argument("--frames", type=int, default=250)
    ap.add_argument("--target-fps", type=float, default=8.0)
    args = ap.parse_args()

    print("warmup...")
    asyncio.run(drive(args.clip, 30, args.target_fps))

    print(f"profiling {args.frames} frames (headless, VLM off)...")
    pr = cProfile.Profile()
    pr.enable()
    asyncio.run(drive(args.clip, args.frames, args.target_fps))
    pr.disable()

    st = pstats.Stats(pr)
    st.strip_dirs()
    print("\n===== TOP BY TOTTIME (self time on main thread) =====")
    st.sort_stats("tottime").print_stats(28)
    print("\n===== TOP BY CUMULATIVE =====")
    st.sort_stats("cumulative").print_stats(24)
    return 0


if __name__ == "__main__":
    sys.exit(main())
