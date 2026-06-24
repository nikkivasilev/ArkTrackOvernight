"""In-process SigLIP-2 zero-shot activity classifier (local GPU).

A drop-in alternative to the remote generative `VlmClassifier`: same duck-typed
seam (`classify`/`can_fire`/`should_revisit`/`set_enabled`/`revisit_s`/`status`),
so the pipeline's VLM producer (`pipeline_vlm.py`) is unchanged.

SigLIP-2 is contrastive (CLIP-family), not generative: we embed the crop and
compare against a fixed matrix of label-prompt text embeddings (precomputed by
`tools/export_siglip_onnx.py`). Classification = argmax cosine similarity.

Runs co-located with D-FINE-L on the same GPU: the vision tower ONNX runs via
ONNX Runtime (CUDA EP) through the shared bounded `_DFINE_EXECUTOR`, so SigLIP
inference *serializes* with D-FINE rather than competing for the GPU. The text
side is precomputed, so per-crop cost is one image-encode + a tiny matmul.

Geometry is fixed: crops are letterboxed to a square (manifest `square_size`),
which the NaFlex processor maps to a 16x16 patch grid — matching what the ONNX
was exported + validated against.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

# Registers the cuDNN/cuBLAS DLL dirs so ORT's CUDA EP can load (Windows).
# Importing dfine_detector runs _register_nvidia_dlls() at import time.
from dfine_detector import _register_nvidia_dlls
import onnxruntime as ort  # noqa: E402

from pipeline_detection import _DFINE_EXECUTOR
from vlm_classifier import VLM_ROLLUP, VlmResult

logger = logging.getLogger(__name__)

_SIGLIP_MEAN = 0.5
_SIGLIP_STD = 0.5


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else Path.cwd() / p


class SiglipClassifier:
    """Zero-shot activity classifier backed by a local SigLIP-2 vision ONNX."""

    def __init__(
        self,
        onnx_path: str,
        labels_path: str,
        temperature: float = 0.05,
        min_person_conf: float = 0.0,
        idle_margin: float = 0.0,
        revisit_s: float = 5.0,
        max_inflight: int = 2,
        execution_provider: str = "cuda",
    ):
        self.revisit_s = float(revisit_s)
        self.max_inflight = int(max_inflight)
        self.temperature = float(temperature)
        self.min_person_conf = float(min_person_conf)
        self.idle_margin = float(idle_margin)

        self._inflight = 0
        self._enabled = True
        self._reachable: Optional[bool] = None
        self._last_error: Optional[str] = None

        # ---- label matrix + manifest ----
        npy = _resolve(labels_path)
        manifest_path = npy.with_suffix(".json")
        self.label_mat = np.load(npy).astype(np.float32)        # [L, dim], L2-normalized
        manifest = json.loads(manifest_path.read_text())
        self.labels: list[str] = manifest["labels"]
        self.no_person_label: str = manifest.get("no_person_label", "not_a_person")
        # Row indices by rollup bucket — for the asymmetric idle-margin gate.
        self._idle_idx = [i for i, l in enumerate(self.labels) if VLM_ROLLUP.get(l) == "idle"]
        self._working_idx = [i for i, l in enumerate(self.labels) if VLM_ROLLUP.get(l) == "working"]
        self.square_size: int = int(manifest.get("square_size", 256))
        self.model_id: str = manifest["model_id"]

        # ---- ORT vision session (CUDA EP, CPU fallback) ----
        path = _resolve(onnx_path)
        if not path.exists():
            raise FileNotFoundError(
                f"SigLIP vision ONNX not found at {path}. Run tools/export_siglip_onnx.py."
            )
        ep = (execution_provider or "cpu").strip().lower()
        avail = set(ort.get_available_providers())
        providers: list = []
        if ep == "cuda" and "CUDAExecutionProvider" in avail:
            providers.append(("CUDAExecutionProvider", {"device_id": 0}))
        providers.append("CPUExecutionProvider")
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(path), sess_options=opts, providers=providers)
        self.active_providers = self.session.get_providers()
        self._input_names = [i.name for i in self.session.get_inputs()]
        logger.info("siglip vision session ready (providers: %s, inputs: %s)",
                    self.active_providers, self._input_names)

        # ---- image processor (CPU, numpy) — correct NaFlex patchification ----
        from transformers import AutoImageProcessor
        self.proc = AutoImageProcessor.from_pretrained(self.model_id, local_files_only=True)

    # ------------------------------------------------------------------
    # VlmClassifier-compatible seam
    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, on: bool) -> None:
        self._enabled = bool(on)

    @property
    def status(self) -> dict:
        return {
            "enabled": self._enabled,
            "reachable": self._reachable,
            "inflight": self._inflight,
            "last_error": self._last_error,
            "backend": "siglip",
            "providers": self.active_providers,
        }

    def can_fire(self) -> bool:
        return self._enabled and self._inflight < self.max_inflight

    def should_revisit(self, last_t: float, t_now: float) -> bool:
        return (t_now - last_t) >= self.revisit_s

    # ------------------------------------------------------------------
    def _letterbox(self, crop_bgr: np.ndarray):
        """BGR crop → letterboxed square RGB PIL image (proportions preserved)."""
        from PIL import Image
        rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        s = self.square_size / max(1, max(w, h))
        nw, nh = max(1, round(w * s)), max(1, round(h * s))
        resized = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_AREA)
        canvas = np.full((self.square_size, self.square_size, 3), 128, dtype=np.uint8)
        oy, ox = (self.square_size - nh) // 2, (self.square_size - nw) // 2
        canvas[oy:oy + nh, ox:ox + nw] = resized
        return Image.fromarray(canvas)

    def _classify_sync(self, crop_bgr: np.ndarray) -> Optional[VlmResult]:
        t0 = time.time()
        try:
            img = self._letterbox(crop_bgr)
            pi = self.proc(images=[img], max_num_patches=self.square_size // 16 * (self.square_size // 16),
                           return_tensors="np")
            feed = {n: np.asarray(pi[n]) for n in self._input_names if n in pi}
            emb = self.session.run(["image_embed"], feed)[0][0]      # [dim]
            emb = emb / (np.linalg.norm(emb) + 1e-8)
            sims = self.label_mat @ emb                              # [L] cosine
            j = int(np.argmax(sims))
            # softmax confidence over the candidate set
            z = sims / max(1e-6, self.temperature)
            z -= z.max()
            probs = np.exp(z); probs /= probs.sum()
            conf = float(probs[j])
            label = self.labels[j]
            if label == self.no_person_label:
                activity = "not_a_person"
            elif conf < self.min_person_conf:
                activity = "unknown"
            elif (
                VLM_ROLLUP.get(label) == "idle"
                and self._working_idx
                and (sims[j] - float(sims[self._working_idx].max())) < self.idle_margin
            ):
                # Idle won, but only narrowly over the best working class —
                # bias the ambiguous call toward working (unknown → working).
                activity = "unknown"
            else:
                activity = label
            self._reachable = True
            self._last_error = None
            return VlmResult(
                activity=activity,
                rollup=VLM_ROLLUP.get(activity, "working"),
                rationale=f"siglip:{label} sim={float(sims[j]):.3f}",
                confidence=conf,
                latency_ms=(time.time() - t0) * 1000.0,
            )
        except Exception as e:
            self._reachable = False
            self._last_error = f"{type(e).__name__}: {str(e)[:120]}"
            logger.warning("siglip classify failed in %.0f ms: %s",
                           (time.time() - t0) * 1000.0, self._last_error)
            return None

    async def classify(self, tracklet) -> Optional[VlmResult]:
        if not self._enabled or not tracklet.frames:
            return None
        crop = tracklet.frames[-1].crop
        self._inflight += 1
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(_DFINE_EXECUTOR, self._classify_sync, crop)
        finally:
            self._inflight = max(0, self._inflight - 1)
