"""
Re-identify a worker after a tracker drops them.

ByteTrack is motion-only — when a worker is occluded or vanishes into an arc-flash
for longer than the lost-track buffer, the next detection becomes a *new* internal
id. This layer wraps the tracker output and remaps internal ids to a stable
"public" id by matching new tracks against recently-orphaned ones using:

  * spatial proximity to the orphan's last known position
  * colour-histogram similarity of the bbox crops

Two signature modes (Switch 2 — `embedding_enabled`):
  * OFF (default): HSV joint-histogram per body region (upper/lower). Cheap.
  * ON:  HSV + LAB joint histogram per region, distance is a weighted blend.
         LAB separates lightness from chroma, which catches PPE hue
         differences (grey vs dark blue jackets) that HSV alone struggles
         with at low brightness. Still no learned model — same opencv-python
         dependency, ~2× the compute per signature.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

# Per-region histogram shape, used for both HSV and LAB.
_HIST_BINS = (8, 8)


@dataclass
class _Signature:
    """Per-region appearance descriptor.

    Always carries an HSV stack (upper/lower body, 8×8 joint hist).
    When `embedding_enabled` was True at signature time, also carries a
    LAB stack of the same shape. Distance code falls back gracefully when
    only one side has the LAB component (after a switch-flip mid-flight).
    """
    hsv: np.ndarray            # shape (2, 8, 8) float32
    lab: Optional[np.ndarray] = None  # shape (2, 8, 8) float32 when richer mode is on


@dataclass
class _State:
    t: float
    cx: float
    cy: float
    w: float
    h: float
    sig: Optional[_Signature]


class IdRecovery:
    def __init__(
        self,
        pos_threshold: float = 280.0,
        time_threshold: float = 10.0,
        hist_weight: float = 0.6,
        accept_score: float = 1.2,
        embedding_enabled: bool = False,
        lab_weight: float = 0.4,
    ):
        self.pos_threshold = pos_threshold
        self.time_threshold = time_threshold
        self.hist_weight = hist_weight
        self.accept_score = accept_score
        # Switch 2: richer per-region signature. Default OFF preserves the
        # current HSV-only behaviour exactly.
        self.embedding_enabled = bool(embedding_enabled)
        self.lab_weight = float(lab_weight)

        self._next_pid: int = 1
        self._iid_to_pid: dict[int, int] = {}
        self._live_state: dict[int, _State] = {}
        self._orphans: dict[int, _State] = {}

    # Public bins shape — kept for back-compat with any importer that read it.
    HIST_BINS = _HIST_BINS

    @staticmethod
    def _hist_hsv(region: np.ndarray) -> np.ndarray:
        hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        h = cv2.calcHist([hsv], [0, 1], None, list(_HIST_BINS), [0, 180, 0, 256])
        cv2.normalize(h, h, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
        return h.astype(np.float32)

    @staticmethod
    def _hist_lab(region: np.ndarray) -> np.ndarray:
        lab = cv2.cvtColor(region, cv2.COLOR_BGR2LAB)
        # Joint hist over a* and b* channels; ignores L (lightness) so the
        # descriptor is more robust to per-camera-zone illumination changes.
        h = cv2.calcHist([lab], [1, 2], None, list(_HIST_BINS), [0, 256, 0, 256])
        cv2.normalize(h, h, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
        return h.astype(np.float32)

    def _signature(self, frame: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> Optional[_Signature]:
        H, W = frame.shape[:2]
        x1 = max(0, x1); y1 = max(0, y1)
        x2 = min(W, x2); y2 = min(H, y2)
        if x2 - x1 < 12 or y2 - y1 < 28:
            return None
        crop = frame[y1:y2, x1:x2]
        hh = crop.shape[0]
        upper = crop[: hh // 2]
        lower = crop[hh // 2 :]
        hsv_stack = np.stack([self._hist_hsv(upper), self._hist_hsv(lower)], axis=0)
        if not self.embedding_enabled:
            return _Signature(hsv=hsv_stack)
        lab_stack = np.stack([self._hist_lab(upper), self._hist_lab(lower)], axis=0)
        return _Signature(hsv=hsv_stack, lab=lab_stack)

    def _hist_dist(self, a: Optional[_Signature], b: Optional[_Signature]) -> float:
        if a is None or b is None:
            return 1.0
        # HSV distance is always available (Bhattacharyya, averaged over regions).
        d_hsv_upper = float(cv2.compareHist(a.hsv[0], b.hsv[0], cv2.HISTCMP_BHATTACHARYYA))
        d_hsv_lower = float(cv2.compareHist(a.hsv[1], b.hsv[1], cv2.HISTCMP_BHATTACHARYYA))
        d_hsv = 0.5 * (d_hsv_upper + d_hsv_lower)
        # If both sides carry LAB (current `embedding_enabled` path), blend it in.
        if a.lab is not None and b.lab is not None:
            d_lab_upper = float(cv2.compareHist(a.lab[0], b.lab[0], cv2.HISTCMP_BHATTACHARYYA))
            d_lab_lower = float(cv2.compareHist(a.lab[1], b.lab[1], cv2.HISTCMP_BHATTACHARYYA))
            d_lab = 0.5 * (d_lab_upper + d_lab_lower)
            w = max(0.0, min(1.0, self.lab_weight))
            return (1.0 - w) * d_hsv + w * d_lab
        return d_hsv

    def _match_orphan(self, t: float, cx: float, cy: float, sig: Optional[_Signature]) -> Optional[int]:
        best_pid = None
        best_score = self.accept_score
        for pid, st in self._orphans.items():
            if t - st.t > self.time_threshold:
                continue
            d = ((cx - st.cx) ** 2 + (cy - st.cy) ** 2) ** 0.5
            if d > self.pos_threshold:
                continue
            spatial = d / self.pos_threshold
            appearance = self._hist_dist(sig, st.sig)
            score = spatial + self.hist_weight * appearance
            if score < best_score:
                best_score = score
                best_pid = pid
        return best_pid

    def step(
        self,
        t: float,
        current_iids: list[int],
        boxes: list[tuple[float, float, float, float]],
        frame: np.ndarray,
    ) -> dict[int, int]:
        """Return mapping internal_id -> public_id for the current frame."""
        active = set(current_iids)

        # Internal ids that just disappeared → move to orphans
        for iid in list(self._iid_to_pid.keys()):
            if iid not in active:
                pid = self._iid_to_pid.pop(iid)
                state = self._live_state.pop(pid, None)
                if state is not None:
                    self._orphans[pid] = state

        # Drop very old orphans
        for pid in [p for p, s in self._orphans.items() if t - s.t > self.time_threshold]:
            self._orphans.pop(pid, None)

        result: dict[int, int] = {}
        for iid, box in zip(current_iids, boxes):
            x1, y1, x2, y2 = box
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            w, h = x2 - x1, y2 - y1
            sig = self._signature(frame, int(x1), int(y1), int(x2), int(y2))

            if iid not in self._iid_to_pid:
                matched = self._match_orphan(t, cx, cy, sig)
                if matched is not None:
                    self._orphans.pop(matched, None)
                    pid = matched
                else:
                    pid = self._next_pid
                    self._next_pid += 1
                self._iid_to_pid[iid] = pid

            pid = self._iid_to_pid[iid]
            self._live_state[pid] = _State(t=t, cx=cx, cy=cy, w=w, h=h, sig=sig)
            result[iid] = pid

        return result

    @property
    def n_live(self) -> int:
        return len(self._live_state)

    @property
    def n_orphans(self) -> int:
        return len(self._orphans)
