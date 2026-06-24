"""Vendored ModelTesting pipeline.

These modules were copied verbatim from
`C:\\Users\\Office2\\Desktop\\ModelTesting\\backend\\` on 2026-05-21. They use
flat imports (``from activity import ...``); to keep the diff against
ModelTesting minimal we prepend this directory to ``sys.path`` so the
flat imports resolve.

Phase-1 stubs:
  - dfine_detector, hog_detector, vlm_classifier: no-op classes; the
    Pipeline cfg has matching ``*_enabled`` flags set False so they're
    never constructed.
  - group_detector, zone_detector, pipeline_vlm, pipeline_zones,
    pipeline_tuning: no-op modules satisfying the mixin contract.

Phase 2/3 replaces the stubs with the real ModelTesting modules.
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
