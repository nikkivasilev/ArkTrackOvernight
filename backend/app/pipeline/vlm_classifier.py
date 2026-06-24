"""VLM-based activity classifier.

Sends a short tracklet (a 3×2 mosaic of the most recent crops of a tracked
person) to the OpenAI-compatible vLLM endpoint and asks it to pick one
activity label from a fixed list, plus output a one-line justification.

Trade-offs:
  * VLM call latency is ~1 s per request, far slower than the pipeline frame
    rate. We run at most one VLM call in flight at a time and revisit each
    track every `revisit_s` seconds (default 5).
  * The mosaic encodes time progression in a single image so the model can
    see "this person did X then Y then Z" without us paying for a video clip.
  * If the VLM returns an unparseable label, we fall back to "unknown".

Vocabulary kept short and bucket-able into the existing rollup categories.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np
import requests

logger = logging.getLogger(__name__)

from tracklet import TrackletBuffer, TrackletFrame

# ----------------------------------------------------------------------
# Vocabulary
# ----------------------------------------------------------------------

# Closed activity vocabulary. The VLM is forced to pick one of these.
# Keep aligned with the rollup buckets used elsewhere in the app.
ACTIVITY_VOCAB: list[str] = [
    "welding",
    "grinding",
    "drilling",
    "assembling",
    "inspecting",
    "lifting_or_carrying",
    "walking",
    "standing_idle",
    "sitting",
    "on_phone",
    "chatting",
    "sleeping",
    "unknown",
    # Destructive verdict: the bbox does not contain a person at all (false
    # detection from the upstream detector). Once promoted on a track this
    # causes pipeline_vlm to set hist.vlm_marked_false; renderer + group
    # detector then short-circuit so the track stops surfacing anywhere.
    "not_a_person",
]

# Rollup mapping — every activity belongs to exactly one bucket.
# Operator policy: VLM `unknown` (the model couldn't decide / returned
# out-of-vocab) defaults to `working`. Same rationale as the heuristic
# `unknown` in activity.py — until something is proven moving/idle, the
# worker is counted as productive.
VLM_ROLLUP: dict[str, str] = {
    # Generic "doing manual work" — a broad working attractor for SigLIP so
    # active labor doesn't fragment across the fine classes and lose to idle.
    "working":             "working",
    "welding":             "working",
    "grinding":            "working",
    "drilling":            "working",
    "assembling":          "working",
    "inspecting":          "working",
    "lifting_or_carrying": "working",
    "walking":             "moving",
    "standing_idle":       "idle",
    "sitting":             "idle",
    "on_phone":            "idle",
    "chatting":            "idle",
    "sleeping":            "idle",
    "unknown":             "working",
    # never actually counted — the track is filtered before rollup buckets
    # see this value. Keep an entry so VLM_ROLLUP[…] lookup doesn't KeyError.
    "not_a_person":        "unclear",
}


# ----------------------------------------------------------------------
# VlmClassifier
# ----------------------------------------------------------------------

@dataclass
class VlmResult:
    activity: str           # one of ACTIVITY_VOCAB
    rollup: str             # one of working / moving / idle / unclear
    rationale: str          # one short sentence
    confidence: float = 0.0
    latency_ms: float = 0.0


class VlmClassifier:
    def __init__(
        self,
        base_url: str = "http://10.0.0.2:8000",
        model: str = "/models/qwen3-next",
        timeout: float = 25.0,
        # Single-frame mode (session 5): cols=rows=1 sends one square crop to
        # the VLM instead of a 3×2 mosaic of stitched panes. Cheaper per call
        # (~6× smaller payload), generally classifies activities just as well,
        # and lets us bump per-side resolution to 384 px so the model sees more
        # of the worker. Setting cols/rows >1 reverts to the old grid layout.
        mosaic_cols: int = 1,
        mosaic_rows: int = 1,
        mosaic_tile_size: int = 384,
        jpeg_quality: int = 70,
        revisit_s: float = 5.0,
        max_inflight: int = 1,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.mosaic_cols = mosaic_cols
        self.mosaic_rows = mosaic_rows
        self.mosaic_tile_size = mosaic_tile_size
        self.jpeg_quality = jpeg_quality
        self.revisit_s = revisit_s
        self.max_inflight = max_inflight

        self.session = requests.Session()
        self.session.headers["Content-Type"] = "application/json"

        self._inflight: int = 0
        self._enabled: bool = True
        self._reachable: Optional[bool] = None
        self._last_error: Optional[str] = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, on: bool):
        self._enabled = bool(on)

    @property
    def status(self) -> dict:
        return {
            "enabled": self._enabled,
            "reachable": self._reachable,
            "inflight": self._inflight,
            "last_error": self._last_error,
        }

    # ------------------------------------------------------------------

    def can_fire(self) -> bool:
        return self._enabled and self._inflight < self.max_inflight

    def should_revisit(self, last_t: float, t_now: float) -> bool:
        return (t_now - last_t) >= self.revisit_s

    # ------------------------------------------------------------------

    def _build_mosaic(self, frames: list[TrackletFrame]) -> Optional[bytes]:
        """Stitch tracklet crops into a 3×2 mosaic, JPEG-encode."""
        if not frames:
            return None
        cols, rows = self.mosaic_cols, self.mosaic_rows
        ts = self.mosaic_tile_size
        tiles = frames[: cols * rows]
        # Pad with last frame if fewer than cols*rows
        while len(tiles) < cols * rows:
            tiles.append(tiles[-1])

        mosaic = np.zeros((rows * ts, cols * ts, 3), dtype=np.uint8)
        for i, tf in enumerate(tiles):
            r = i // cols; c = i % cols
            crop = tf.crop
            # Letterbox to ts×ts so aspect is preserved
            ch, cw = crop.shape[:2]
            scale = min(ts / max(1, cw), ts / max(1, ch))
            new_w = max(2, int(cw * scale))
            new_h = max(2, int(ch * scale))
            resized = cv2.resize(crop, (new_w, new_h), interpolation=cv2.INTER_AREA)
            ox = (ts - new_w) // 2; oy = (ts - new_h) // 2
            mosaic[r * ts + oy: r * ts + oy + new_h,
                   c * ts + ox: c * ts + ox + new_w] = resized

        ok, buf = cv2.imencode(".jpg", mosaic, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        if not ok:
            return None
        return buf.tobytes()

    @staticmethod
    def _build_prompt() -> str:
        labels = ", ".join(ACTIVITY_VOCAB)
        return (
            "You are looking at a single worker in a train-chassis factory. "
            "The image is a recent crop of one worker. Pick the worker's MOST "
            "LIKELY current activity from this exact list:\n"
            f"  {labels}\n\n"
            "Respond ONLY with a single JSON object on one line, no prose, of the form:\n"
            '  {"activity": "<one of the labels>", "rationale": "<short sentence>", "confidence": <0.0-1.0>}\n'
            "Be conservative: pick \"unknown\" if you are unsure what activity a real "
            "person is doing. "
            "Use \"not_a_person\" ONLY if the crop clearly shows no person at all — "
            "e.g. machinery, walls, shadows, empty floor, parts of equipment, or "
            "stationary tools incorrectly framed as a worker. This rules out false "
            "detections so they stop being tracked."
        )

    @staticmethod
    def _parse(reply: str) -> Optional[dict]:
        """Parse JSON from a model reply that may include surrounding markdown/prose."""
        s = reply.strip()
        # Strip ```json fences if present
        if s.startswith("```"):
            s = s.strip("`").lstrip("json").strip()
        # Find first { ... } block
        i = s.find("{"); j = s.rfind("}")
        if i < 0 or j <= i:
            return None
        try:
            return json.loads(s[i: j + 1])
        except Exception:
            return None

    # ------------------------------------------------------------------

    async def classify(self, tracklet: TrackletBuffer) -> Optional[VlmResult]:
        """Run one VLM classification on the given tracklet. Returns None on
        failure or when the tracklet is too thin.
        """
        if not self._enabled:
            return None
        if not tracklet.frames:
            return None
        # Single-frame mode: send the MOST RECENT crop (sharpest, reflects the
        # worker's current state). When mosaic_cols/rows >1 the existing
        # _build_mosaic stitches a grid using `sampled` instead.
        if self.mosaic_cols == 1 and self.mosaic_rows == 1:
            frames = [tracklet.frames[-1]]
        else:
            frames = tracklet.sampled(self.mosaic_cols * self.mosaic_rows)
            if len(frames) < 2:
                return None

        mosaic_jpeg = self._build_mosaic(frames)
        if mosaic_jpeg is None:
            return None
        b64 = base64.b64encode(mosaic_jpeg).decode("ascii")

        payload = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    {"type": "text", "text": self._build_prompt()},
                ],
            }],
            "max_tokens": 120,
            "temperature": 0.0,
        }

        self._inflight += 1
        t0 = time.time()
        try:
            loop = asyncio.get_running_loop()
            r = await loop.run_in_executor(
                None,
                lambda: self.session.post(
                    f"{self.base_url}/v1/chat/completions",
                    data=json.dumps(payload),
                    timeout=self.timeout,
                ),
            )
            self._reachable = True
            r.raise_for_status()
            out = r.json()
            content = out["choices"][0]["message"]["content"]
            parsed = self._parse(content)
            if not parsed or "activity" not in parsed:
                self._last_error = f"unparseable: {content[:80]}"
                return None
            label = str(parsed.get("activity", "")).strip().lower()
            if label not in ACTIVITY_VOCAB:
                # Soft snap-to-vocabulary
                self._last_error = f"out-of-vocab: {label!r}"
                label = "unknown"
            self._last_error = None
            return VlmResult(
                activity=label,
                rollup=VLM_ROLLUP.get(label, "working"),
                rationale=str(parsed.get("rationale", ""))[:200],
                confidence=float(parsed.get("confidence", 0.0) or 0.0),
                latency_ms=(time.time() - t0) * 1000,
            )
        except Exception as e:
            self._reachable = False
            self._last_error = f"{type(e).__name__}: {str(e)[:120]}"
            logger.warning(
                "vlm classify failed in %.0f ms: %s",
                (time.time() - t0) * 1000, self._last_error,
            )
            return None
        finally:
            self._inflight = max(0, self._inflight - 1)
