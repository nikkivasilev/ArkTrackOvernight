"""One-shot TensorRT engine builder for D-FINE-L.

Loads DfineDetector with the tensorrt EP, runs a single dummy inference, and
exits. The first call serialises the optimised engine + timing cache to disk
under ``backend/checkpoints/trt_cache/``; subsequent backend starts (live or
via this script) load from cache in seconds instead of spending 5-15 min
re-building.

Run from ``backend/``:
    ./.venv/Scripts/python.exe tools/warmup_trt.py

The build is verbose by design — TRT prints layer-by-layer tactics selection
so you can watch progress. If you see "Total Activation Memory" / "Engine
serialized" lines and the script exits 0, the cache is ready.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# Make `app.pipeline...` imports work the same way uvicorn does. The pipeline
# package __init__ adds its directory to sys.path on import, after which the
# flat module imports (dfine_detector, yolo_client, ...) resolve.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

import app.pipeline  # noqa: E402,F401  (side effect: registers pipeline dir on sys.path)
from dfine_detector import DfineDetector  # noqa: E402


def main() -> int:
    backend_root = Path(__file__).resolve().parent.parent
    onnx = backend_root / "checkpoints" / "dfine_l_obj2coco.onnx"
    if not onnx.exists():
        print(f"ONNX file not found at {onnx}; run tools/export_dfine_onnx.py first.")
        return 1

    print(f"Loading {onnx.name} with TensorRT EP. Engine build can take 5-15 min on first run.")
    t0 = time.time()
    det = DfineDetector(
        onnx_path=str(onnx),
        execution_provider="tensorrt",
    )
    t_load = time.time() - t0
    print(f"Session ready in {t_load:.1f}s. Active providers: {det.active_providers}")

    # One real inference to trigger the first engine build (for shape 640x640).
    print("Running dummy inference to seal engine cache...")
    dummy = (np.random.rand(720, 1280, 3) * 255).astype(np.uint8)
    t1 = time.time()
    dets = det.detect(dummy)
    t_first = time.time() - t1
    print(f"First inference: {t_first * 1000:.1f} ms; {len(dets)} detections.")

    # Second inference to measure steady-state.
    t2 = time.time()
    det.detect(dummy)
    t_steady = time.time() - t2
    print(f"Steady-state inference: {t_steady * 1000:.1f} ms.")

    cache = backend_root / "checkpoints" / "trt_cache"
    files = sorted(cache.glob("*")) if cache.exists() else []
    print(f"Cache dir {cache} contains {len(files)} file(s):")
    for f in files:
        print(f"  {f.name}  ({f.stat().st_size / (1024 * 1024):.1f} MB)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
