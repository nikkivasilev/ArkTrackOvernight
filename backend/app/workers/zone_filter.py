"""Drop tracks / flashes inside operator-excluded zones from a state dict.

Used by the camera worker after ``CameraPipeline.process_frame`` returns and
before the state is folded into ``MetricsAggregator`` or broadcast over the
WS. Mutates the dict in place and rebuilds the derived counts so the chips,
status cards, timeline, metrics, and Analysis panel all stay consistent.
"""
from __future__ import annotations

from collections import defaultdict

from shapely.geometry import Point, Polygon


def _foot_point(bbox: list[int]) -> Point:
    """Bottom-center of a bbox in source-frame pixels — the worker's foot
    location. Used as the "worker is in zone" point. Workers stand on the
    floor, so foot-point is the semantically right anchor for an exclusion
    check (catches the cases where a worker walks half-into a zone)."""
    x1, y1, x2, y2 = bbox
    return Point((x1 + x2) / 2.0, float(y2))


def apply(state: dict, excluded_polys_px: list[list[tuple[float, float]]]) -> None:
    """If ``excluded_polys_px`` is non-empty, drop tracks and flashes whose
    foot-point / centroid falls inside any of the polygons, and recompute
    every derived count in ``state``."""
    if not excluded_polys_px:
        return
    polys = [Polygon(pts) for pts in excluded_polys_px if len(pts) >= 3]
    if not polys:
        return

    def in_any(p: Point) -> bool:
        return any(poly.covers(p) for poly in polys)

    # Tracks: foot-point check
    kept_tracks: list[dict] = []
    activity_counts: dict[str, int] = defaultdict(int)
    rollup_counts: dict[str, int] = defaultdict(int)
    for tr in state.get("tracks") or []:
        bbox = tr.get("bbox")
        if not bbox or len(bbox) != 4:
            kept_tracks.append(tr)
            continue
        if in_any(_foot_point(bbox)):
            continue
        kept_tracks.append(tr)
        # Recreate the activity / rollup counts the renderer would have
        # produced for the surviving tracks. Ghost tracks contribute nothing
        # to activity_counts but DO carry a rollup — pipeline_render now
        # inherits the last confident rollup for fresh ghosts and only falls
        # back to "unclear" for genuinely stale ones. Read whatever the
        # renderer wrote (default "unclear" if missing).
        if tr.get("ghost"):
            rollup_counts[str(tr.get("rollup") or "unclear")] += 1
        else:
            activity_counts[str(tr.get("activity") or "unknown")] += 1
            rollup_counts[str(tr.get("rollup") or "unclear")] += 1

    state["tracks"] = kept_tracks
    state["activity_counts"] = dict(activity_counts)
    state["rollup_counts"] = dict(rollup_counts)

    # Flashes: centroid check
    kept_flashes: list[dict] = []
    orphan_inside = 0
    for f in state.get("flashes") or []:
        if in_any(Point(float(f.get("cx", 0)), float(f.get("cy", 0)))):
            if f.get("orphan"):
                orphan_inside += 1
            continue
        kept_flashes.append(f)
    state["flashes"] = kept_flashes
    if "orphan_welding_count" in state:
        state["orphan_welding_count"] = max(
            0, int(state["orphan_welding_count"]) - orphan_inside
        )

    # Phantom counts are pipeline-internal; we don't try to filter
    # `n_phantoms` since phantoms are visible state and pruning them would
    # require recomputing which phantoms had their bbox inside a zone.
    # The track-level filter already drops phantom tracks (they live in
    # state.tracks with `phantom: true`), so the metric counts are correct.
