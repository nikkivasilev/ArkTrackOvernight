"""Phase-1 stub for the zone detector.

Phase-2 vendors the real ZoneDetector + ZoneEval + Zone. Phase-1 keeps
``zones_enabled=False`` at runtime so ``step()`` is never called.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Zone:
    id: str = ""
    name: str = ""
    polygon: list = field(default_factory=list)
    rules: list = field(default_factory=list)
    membership: str = "foot"


@dataclass
class ZoneEval:
    zone_id: str = ""
    zone_name: str = ""
    count: int = 0
    members: list[int] = field(default_factory=list)
    in_breach: bool = False
    rules: list[dict] = field(default_factory=list)


class ZoneDetector:
    def __init__(self, *args, **kwargs):
        self.zones: list[Zone] = []

    def step(self, *args, **kwargs) -> list[ZoneEval]:
        return []

    def list_zones(self) -> list:
        return []
