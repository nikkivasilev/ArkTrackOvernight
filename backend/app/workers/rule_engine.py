from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from shapely.geometry import Point, Polygon

from app.inference.dfine_client import Detection

logger = logging.getLogger(__name__)

DETECTION_DEBOUNCE_SECONDS = 5.0

STUB_TRIGGERS = {"duration", "absence", "resting_worker"}

# Staffing-COUNT triggers. Operator policy: these are used for the staffing
# METRIC (the under/over-staffing signal lives in the zone-occupancy panel,
# which is computed independently of rules) — they must NOT fire picture
# alerts. Skipped here so they never create Alert rows / thumbnails. The
# count_min/count_max branches below are retained (unreachable) for easy
# re-enable if alerting is ever wanted.
METRIC_ONLY_TRIGGERS = {"count_min", "count_max"}


@dataclass
class RuleSpec:
    """Projection of a Rule row used by the evaluator."""

    id: UUID
    name: str
    trigger_type: str
    severity: str
    params: dict[str, Any]
    polygon: list[list[float]] | None
    zone_id: UUID | None
    camera_id: UUID | None


@dataclass
class AlertIntent:
    """What the worker should persist + broadcast for one rule firing."""

    rule: RuleSpec
    detection: Detection | None       # None for count_*/absence transitions
    confidence: float | None          # None when not single-detection-derived
    transition: str                   # "fire" or "resolve"


@dataclass
class RuleState:
    """Per-rule, per-worker-run scratch state."""

    last_fired_at: float = 0.0        # monotonic timestamp; for detection debounce
    count_below: bool = False         # count_min: currently below threshold?
    count_above: bool = False         # count_max: currently above threshold?
    open_alert_id: UUID | None = None # last unresolved alert id, for end_timestamp updates


def _polygon_contains(poly_pts: list[list[float]], x: float, y: float) -> bool:
    if len(poly_pts) < 3:
        return False
    poly = Polygon(poly_pts)
    return poly.covers(Point(x, y))


def _detections_in_scope(detections: list[Detection], rule: RuleSpec) -> list[Detection]:
    target = rule.params.get("target_class", "person")
    min_conf = float(rule.params.get("min_confidence", 0.5))
    in_scope: list[Detection] = []
    for det in detections:
        if det.name != target:
            continue
        if det.confidence < min_conf:
            continue
        if rule.polygon is not None and not _polygon_contains(rule.polygon, det.cx, det.cy):
            continue
        in_scope.append(det)
    return in_scope


def evaluate_frame(
    detections: list[Detection],
    rules: list[RuleSpec],
    state: dict[UUID, RuleState],
) -> list[AlertIntent]:
    """Evaluate all rules against the current frame. Mutates state in place."""
    now = time.monotonic()
    intents: list[AlertIntent] = []

    for rule in rules:
        if rule.trigger_type in STUB_TRIGGERS or rule.trigger_type in METRIC_ONLY_TRIGGERS:
            continue
        st = state.setdefault(rule.id, RuleState())

        if rule.trigger_type == "detection":
            matches = _detections_in_scope(detections, rule)
            if not matches:
                continue
            if now - st.last_fired_at < DETECTION_DEBOUNCE_SECONDS:
                continue
            # Pick the highest-confidence detection as the alert subject.
            best = max(matches, key=lambda d: d.confidence)
            st.last_fired_at = now
            intents.append(AlertIntent(rule=rule, detection=best, confidence=best.confidence, transition="fire"))

        elif rule.trigger_type == "count_min":
            threshold = int(rule.params.get("threshold", 1))
            count = len(_detections_in_scope(detections, rule))
            below = count < threshold
            if below and not st.count_below:
                st.count_below = True
                intents.append(AlertIntent(rule=rule, detection=None, confidence=None, transition="fire"))
            elif not below and st.count_below:
                st.count_below = False
                if st.open_alert_id is not None:
                    intents.append(AlertIntent(rule=rule, detection=None, confidence=None, transition="resolve"))

        elif rule.trigger_type == "count_max":
            threshold = int(rule.params.get("threshold", 1))
            count = len(_detections_in_scope(detections, rule))
            above = count > threshold
            if above and not st.count_above:
                st.count_above = True
                intents.append(AlertIntent(rule=rule, detection=None, confidence=None, transition="fire"))
            elif not above and st.count_above:
                st.count_above = False
                if st.open_alert_id is not None:
                    intents.append(AlertIntent(rule=rule, detection=None, confidence=None, transition="resolve"))

        else:
            logger.debug("unhandled trigger_type %s", rule.trigger_type)

    return intents
