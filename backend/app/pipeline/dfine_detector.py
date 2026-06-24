"""In-process D-FINE-L person detector backed by ONNX Runtime.

The previous Phase-1 stub deferred all detection to the remote HTTP server
at `prod` (YoloClient). This implementation runs the same architecture
locally — D-FINE-L exported from `ustc-community/dfine-large-coco` via
`tools/export_dfine_onnx.py` — on the GPU via ORT's `CUDAExecutionProvider`,
cutting per-detection latency from ~150-250 ms (remote HTTP) to ~15-25 ms
(local CUDA).

Plugged into `YoloClient._local["dfine-l"]` by `Pipeline.__init__`. Implements
the `LocalDetector` protocol from `yolo_client.py:75-95`.

Postprocessing follows the standard DETR-style decode: per-query sigmoid
over logits, take the max-class as that query's detection, decode the box
from cxcywh in [0,1] to xyxy in source-frame pixels, then filter by:
  - confidence threshold
  - COCO class 0 (person)
  - sanity caps: aspect ratio + max box area fraction
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


def _register_nvidia_dlls() -> None:
    """On Windows, the NVIDIA pip wheels (nvidia-cudnn-cu12, nvidia-cublas-cu12,
    etc.) drop CUDA / cuDNN DLLs under ``site-packages/nvidia/<lib>/bin/``.

    Three things are needed for ORT's CUDAExecutionProvider to find them
    via its internal LoadLibrary calls:
      1. Add each bin directory via ``os.add_dll_directory`` (LoadLibraryEx
         with USER_DIRS flag).
      2. Prepend each bin directory to ``os.environ['PATH']`` (so plain
         LoadLibrary calls find them too — ORT's bridge uses both paths).
      3. Preload the critical DLLs by name via ``ctypes.WinDLL`` so they're
         already in the process's loader table before
         ``onnxruntime_providers_cuda.dll`` looks them up.

    No-op on non-Windows."""
    if sys.platform != "win32":
        return
    bin_dirs: list[Path] = []

    # nvidia-cudnn-cu12, nvidia-cublas-cu12, etc. drop under site-packages/nvidia/<lib>/bin/.
    for base in sys.path:
        nvidia_root = Path(base) / "nvidia"
        if nvidia_root.is_dir():
            for lib_dir in nvidia_root.iterdir():
                bin_dir = lib_dir / "bin"
                if bin_dir.is_dir():
                    bin_dirs.append(bin_dir)
            break

    # tensorrt-cu12 drops nvinfer_10.dll etc. flat under site-packages/tensorrt_libs/
    # (no bin/ subfolder). ORT's TensorrtExecutionProvider DLL hard-links against
    # nvinfer_10.dll + nvonnxparser_10.dll, so they must be loadable when the
    # provider is created.
    for base in sys.path:
        trt_root = Path(base) / "tensorrt_libs"
        if trt_root.is_dir():
            bin_dirs.append(trt_root)
            break

    for bd in bin_dirs:
        try:
            os.add_dll_directory(str(bd))
        except (OSError, ValueError):
            pass

    # Prepend to PATH so plain LoadLibrary() finds them.
    if bin_dirs:
        new_path = os.pathsep.join(str(p) for p in bin_dirs) + os.pathsep + os.environ.get("PATH", "")
        os.environ["PATH"] = new_path

    # Preload critical DLLs by name so ORT's resolver always finds them.
    import ctypes
    critical = [
        "cublasLt64_12.dll",
        "cublas64_12.dll",
        "cudart64_12.dll",
        "cufft64_11.dll",
        "cudnn64_9.dll",
        "cudnn_graph64_9.dll",
        "cudnn_engines_precompiled64_9.dll",
        "cudnn_engines_runtime_compiled64_9.dll",
        "cudnn_heuristic64_9.dll",
        "cudnn_ops64_9.dll",
        "cudnn_cnn64_9.dll",
        "cudnn_adv64_9.dll",
        # TensorRT 10 — preloaded only when the EP is requested at session-creation
        # time; harmless to preload regardless because they sit in site-packages.
        "nvinfer_10.dll",
        "nvinfer_plugin_10.dll",
        "nvonnxparser_10.dll",
    ]
    for dll_name in critical:
        for bd in bin_dirs:
            candidate = bd / dll_name
            if candidate.exists():
                try:
                    ctypes.WinDLL(str(candidate))
                except OSError:
                    pass
                break


_register_nvidia_dlls()

# Import ORT only AFTER registering the cuDNN/cuBLAS DLL directories.
import onnxruntime as ort  # noqa: E402

from yolo_client import Detection  # noqa: E402

logger = logging.getLogger(__name__)

# COCO class id for "person" — D-FINE's output head matches the COCO index.
COCO_PERSON_CLS = 0


def _resolve_path(path: str) -> Path:
    """Resolve relative ``path`` against the backend root (CWD when uvicorn
    runs from backend/). Absolute paths pass through unchanged."""
    p = Path(path)
    if p.is_absolute():
        return p
    return Path.cwd() / p


class DfineDetector:
    """ONNX-Runtime-backed in-process D-FINE-L wrapper."""

    def __init__(
        self,
        onnx_path: str,
        input_size: int = 640,
        conf_threshold: float = 0.40,
        execution_provider: str = "cuda",
        max_aspect_ratio: float = 3.0,
        max_box_area_frac: float = 0.85,
    ):
        path = _resolve_path(onnx_path)
        if not path.exists():
            raise FileNotFoundError(
                f"D-FINE-L ONNX not found at {path}. Run "
                "`python tools/export_dfine_onnx.py` from backend/."
            )

        # Build the ORT provider list. "tensorrt" prepends TensorrtExecutionProvider
        # (FP16, on-disk engine + timing cache) ahead of CUDA so unsupported ops
        # delegate down to CUDA EP. "cuda" picks CUDAExecutionProvider. "cpu"
        # forces CPU. Anything else → cpu (safe).
        ep_request = (execution_provider or "cpu").strip().lower()
        available = set(ort.get_available_providers())
        providers: list[str | tuple[str, dict]] = []
        cuda_opts = {
            "device_id": 0,
            "arena_extend_strategy": "kNextPowerOfTwo",
            "cudnn_conv_algo_search": "EXHAUSTIVE",
            "do_copy_in_default_stream": True,
        }
        if ep_request == "tensorrt" and "TensorrtExecutionProvider" in available:
            cache_dir = _resolve_path("checkpoints/trt_cache")
            cache_dir.mkdir(parents=True, exist_ok=True)
            providers.append((
                "TensorrtExecutionProvider",
                {
                    "device_id": 0,
                    "trt_fp16_enable": True,
                    "trt_engine_cache_enable": True,
                    "trt_engine_cache_path": str(cache_dir),
                    "trt_timing_cache_enable": True,
                    "trt_timing_cache_path": str(cache_dir),
                    # Hold builder workspace at a couple of GB — D-FINE-L's graph
                    # benefits from larger tactics search, RTX 3080 has 10 GB.
                    "trt_max_workspace_size": 2 * 1024 * 1024 * 1024,
                },
            ))
            providers.append(("CUDAExecutionProvider", cuda_opts))
        elif ep_request == "tensorrt":
            logger.warning(
                "dfine-l requested tensorrt but TensorrtExecutionProvider not in "
                "ORT providers (%s); falling back to CUDA/CPU.",
                sorted(available),
            )
            if "CUDAExecutionProvider" in available:
                providers.append(("CUDAExecutionProvider", cuda_opts))
        elif ep_request == "cuda" and "CUDAExecutionProvider" in available:
            providers.append(("CUDAExecutionProvider", cuda_opts))
        elif ep_request == "cuda":
            logger.warning(
                "dfine-l requested cuda but CUDAExecutionProvider not in "
                "ORT providers (%s); falling back to CPU.",
                sorted(available),
            )
        providers.append("CPUExecutionProvider")

        sess_opts = ort.SessionOptions()
        sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        # TRT EP runs the heavy compute on the GPU. ORT's CPU thread pool only
        # dispatches kernels and runs any subgraph TRT couldn't compile (rare
        # for D-FINE). Capping to 1 thread each kills the per-session pool
        # overhead — critical when multiple detectors / cameras share a process.
        sess_opts.intra_op_num_threads = 1
        sess_opts.inter_op_num_threads = 1

        logger.info(
            "loading D-FINE-L from %s with providers=%s", path, providers
        )
        self.session = ort.InferenceSession(
            str(path), sess_options=sess_opts, providers=providers
        )
        self.active_providers = self.session.get_providers()
        logger.info("dfine-l active providers: %s", self.active_providers)

        self.input_name = self.session.get_inputs()[0].name
        out_names = [o.name for o in self.session.get_outputs()]
        if "logits" not in out_names or "pred_boxes" not in out_names:
            raise RuntimeError(
                f"unexpected ONNX outputs {out_names}; expected ['logits','pred_boxes']"
            )
        self.input_size = int(input_size)
        self.default_conf = float(conf_threshold)
        self.max_aspect_ratio = float(max_aspect_ratio)
        self.max_box_area_frac = float(max_box_area_frac)

    def detect(
        self,
        frame_bgr: np.ndarray,
        conf: Optional[float] = None,
        max_dim: Optional[int] = None,
        jpeg_quality: Optional[int] = None,  # unused — kept for protocol parity
    ) -> list[Detection]:
        if frame_bgr is None or frame_bgr.size == 0:
            return []
        H, W = frame_bgr.shape[:2]
        if H == 0 or W == 0:
            return []

        threshold = float(conf if conf is not None else self.default_conf)

        S = self.input_size
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (S, S), interpolation=cv2.INTER_LINEAR)
        x = resized.astype(np.float32) / 255.0
        x = np.transpose(x, (2, 0, 1))[None, ...]
        x = np.ascontiguousarray(x)

        logits, pred_boxes = self.session.run(
            ["logits", "pred_boxes"], {self.input_name: x}
        )
        logits = logits[0]
        boxes_cxcywh = pred_boxes[0]

        scores = _sigmoid(logits)
        cls_ids = np.argmax(scores, axis=1)
        cls_scores = scores[np.arange(scores.shape[0]), cls_ids]

        keep = (cls_ids == COCO_PERSON_CLS) & (cls_scores >= threshold)
        if not np.any(keep):
            return []
        boxes_cxcywh = boxes_cxcywh[keep]
        cls_scores = cls_scores[keep]

        cx, cy, bw, bh = (
            boxes_cxcywh[:, 0],
            boxes_cxcywh[:, 1],
            boxes_cxcywh[:, 2],
            boxes_cxcywh[:, 3],
        )
        x1 = (cx - bw / 2.0) * W
        y1 = (cy - bh / 2.0) * H
        x2 = (cx + bw / 2.0) * W
        y2 = (cy + bh / 2.0) * H

        widths = np.maximum(1.0, x2 - x1)
        heights = np.maximum(1.0, y2 - y1)
        aspects = np.maximum(widths / heights, heights / widths)
        areas = (widths * heights) / float(W * H)
        sane = (aspects <= self.max_aspect_ratio) & (areas <= self.max_box_area_frac)
        if not np.any(sane):
            return []

        x1 = x1[sane]; y1 = y1[sane]; x2 = x2[sane]; y2 = y2[sane]
        cls_scores = cls_scores[sane]

        x1 = np.clip(x1, 0, W)
        y1 = np.clip(y1, 0, H)
        x2 = np.clip(x2, 0, W)
        y2 = np.clip(y2, 0, H)

        out: list[Detection] = []
        for i in range(x1.shape[0]):
            out.append(Detection(
                x1=float(x1[i]),
                y1=float(y1[i]),
                x2=float(x2[i]),
                y2=float(y2[i]),
                conf=float(cls_scores[i]),
                cls=COCO_PERSON_CLS,
                name="person",
            ))
        return out

    def close(self) -> None:
        try:
            del self.session
        except Exception:
            pass


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return np.where(
        x >= 0,
        1.0 / (1.0 + np.exp(-x)),
        np.exp(x) / (1.0 + np.exp(x)),
    )
