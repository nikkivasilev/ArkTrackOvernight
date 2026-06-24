"""Verify headless mode changes ONLY rendering, never the metrics `state`.

Feeds the same frames through two CameraPipelines in lockstep — one normal,
one headless — and asserts their per-frame `state` dicts are identical after
dropping the volatile timing fields (src_fps/yolo_ms, which are wall-clock EMAs
that differ run to run). VLM is disabled on both so detection/tracking/welding/
groups/zones are fully deterministic and directly comparable.

Run from backend/:
    ./.venv/Scripts/python.exe tools/check_headless_parity.py
    ./.venv/Scripts/python.exe tools/check_headless_parity.py --frames 120
"""
from __future__ import annotations

import argparse
import asyncio
import json
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

# Wall-clock EMA timing fields — expected to differ between two runs.
VOLATILE = {"src_fps", "yolo_ms"}

DEFAULT_CLIP = r"C:/Users/Office2/Desktop/factory/cam2.mp4"


def _norm(state: dict | None) -> str:
    if state is None:
        return "<none>"
    clean = {k: v for k, v in state.items() if k not in VOLATILE}
    return json.dumps(clean, sort_keys=True, default=str)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default=DEFAULT_CLIP)
    ap.add_argument("--frames", type=int, default=80)
    ap.add_argument("--target-fps", type=float, default=8.0)
    args = ap.parse_args()

    live = CameraPipeline(camera_id=uuid4(), target_fps=args.target_fps)
    head = CameraPipeline(camera_id=uuid4(), target_fps=args.target_fps)
    live.vlm = None  # deterministic: no async VLM verdicts
    head.vlm = None
    head.headless = True

    n = 0
    mismatches = 0
    first_bad: tuple[int, str, str] | None = None
    async for idx, t_video, frame in iter_sampled(args.clip, args.target_fps):
        out_live = await live.process_frame(frame.copy(), idx, t_video)
        out_head = await head.process_frame(frame.copy(), idx, t_video)

        # The headless FrameOut must carry no JPEG; the live one must.
        if out_head is not None and out_head.jpeg != b"":
            print(f"FAIL: headless produced a non-empty JPEG at frame {idx}")
            return 1

        s_live = _norm(out_live.state if out_live else None)
        s_head = _norm(out_head.state if out_head else None)
        if s_live != s_head:
            mismatches += 1
            if first_bad is None:
                first_bad = (idx, s_live, s_head)
        n += 1
        if n >= args.frames:
            break

    print(f"compared {n} frames | mismatches: {mismatches}")
    if first_bad is not None:
        idx, sl, sh = first_bad
        print(f"\nfirst mismatch at frame {idx}:")
        print(f"  live: {sl[:600]}")
        print(f"  head: {sh[:600]}")
        print("\nRESULT: FAIL — headless changed the state dict")
        return 1
    print("RESULT: PASS — headless state is identical to live (minus jpeg + timing)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
