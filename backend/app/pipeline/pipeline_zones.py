"""Zone CRUD + per-frame zone evaluation — extracted from pipeline.py.

Mixin for the Pipeline class. Assumes these attributes exist on `self`:

    self.zone_detector        : ZoneDetector
    self.phantom_tracker      : PhantomTracker
    self.tracks               : dict[int, TrackHistory]
    self.source_dim           : tuple[int, int] | None
    self._broadcast           : (event: dict) → coroutine
    self._persist_safe        : () → None
"""

from __future__ import annotations

from typing import Optional

from activity import phantom_track_id
from zone_detector import Zone, ZoneEval


class _ZonesMixin:
    """Zone CRUD endpoints and per-frame evaluation."""

    # ------------------------------------------------------------------
    # CRUD — surfaced via /control/zones
    # ------------------------------------------------------------------

    def list_zones(self) -> list[dict]:
        return [z.to_dict() for z in self.zone_detector.list_zones()]

    def get_zone(self, zone_id: str) -> Optional[dict]:
        z = self.zone_detector.get_zone(zone_id)
        return z.to_dict() if z is not None else None

    async def upsert_zone(self, zone_payload: dict) -> dict:
        """Create or replace a zone by id. Validates polygon (≥ 3 pts) +
        rule types + membership kind, persists, and returns the stored shape."""
        zone = Zone.from_dict(zone_payload)
        if len(zone.polygon) < 3:
            raise ValueError("zone polygon must have at least 3 points")
        for r in zone.rules:
            if r.type not in ("count_over", "count_under", "count_outside"):
                raise ValueError(f"unknown rule type: {r.type!r}")
            if r.threshold < 0:
                raise ValueError("rule threshold must be ≥ 0")
            if r.type == "count_outside":
                if r.threshold_max is None:
                    raise ValueError("count_outside rule needs threshold_max")
                if r.threshold > r.threshold_max:
                    raise ValueError("count_outside threshold must be ≤ threshold_max")
        self.zone_detector.upsert_zone(zone)
        await self._broadcast({"type": "zones", "zones": self.list_zones()})
        self._persist_safe()
        return zone.to_dict()

    async def delete_zone(self, zone_id: str) -> bool:
        """Remove a zone. Returns True if it existed, False otherwise."""
        ok = self.zone_detector.delete_zone(zone_id)
        if ok:
            await self._broadcast({"type": "zones", "zones": self.list_zones()})
            self._persist_safe()
        return ok

    async def replace_zones(self, payload: list[dict]) -> list[dict]:
        """Bulk-replace the entire zone list (used on state restore)."""
        zones = [Zone.from_dict(d) for d in payload]
        self.zone_detector.set_zones(zones)
        await self._broadcast({"type": "zones", "zones": self.list_zones()})
        self._persist_safe()
        return self.list_zones()

    # ------------------------------------------------------------------
    # Per-frame evaluation
    # ------------------------------------------------------------------

    async def _step_zones(
        self,
        seen_pids: set[int],
        visible_phantom_ids: set[int],
        t_video: float,
    ) -> list[ZoneEval]:
        """Build the per-frame track view, run ZoneDetector.step, emit
        zone.breach.entered / zone.breach.exited events on transitions.

        Track sources counted toward zone rules:
          1. `active_real` — confirmed YOLO + BoT-SORT person tracks. Bbox
             from TrackHistory.last_bbox.
          2. phantom welders — arc-light-only tracks. The arc is direct
             evidence of a person doing welding; we synthesise a person-
             shaped bbox around the arc centroid using the same depth-
             aware sizing the renderer uses, so foot-point membership lands
             roughly where the welder is standing.

        Motion-only tracks are still excluded (could be carts, not people).
        """
        track_views: list[dict] = []
        # 1. active_real
        for pid in seen_pids:
            th = self.tracks.get(pid)
            if th is None or th.last_bbox is None:
                continue
            track_views.append({"track_id": pid, "bbox": th.last_bbox})
        # 2. phantom welders — count as workers (operator decision 2026-05-09)
        H_full = self.source_dim[1] if self.source_dim is not None else 1520
        for pid in visible_phantom_ids:
            ps = self.phantom_tracker.active.get(pid)
            if ps is None:
                continue
            # Same sizing math as the renderer (depth-aware circle around
            # the arc centroid).
            depth_factor = max(0.0, min(1.0, ps.cy / max(1, H_full)))
            raw = (ps.area ** 0.5) * 0.35
            min_r = 18 + 12 * depth_factor   # 18 (far) → 30 (near)
            max_r = 35 + 60 * depth_factor   # 35 (far) → 95 (near)
            radius = int(max(min_r, min(max_r, raw)))
            tid = phantom_track_id(pid)
            track_views.append({
                "track_id": tid,
                "bbox": (
                    int(ps.cx - radius), int(ps.cy - radius),
                    int(ps.cx + radius), int(ps.cy + radius),
                ),
            })
        evals = self.zone_detector.step(track_views, t_video)
        for ze in evals:
            for re_ in ze.rules:
                if re_.transition is None:
                    continue
                event_type = (
                    "zone.breach.entered" if re_.transition == "entered"
                    else "zone.breach.exited"
                )
                await self._broadcast({
                    "type": event_type,
                    "zone_id": ze.zone_id,
                    "zone_name": ze.zone_name,
                    "rule_id": re_.rule_id,
                    "rule_type": re_.rule_type,
                    "threshold": re_.threshold,
                    "threshold_max": re_.threshold_max,
                    "count": ze.count,
                    "members": ze.members,
                    "sustained_for_s": round(re_.sustained_for_s, 2),
                    "t": round(t_video, 2),
                })
        return evals
