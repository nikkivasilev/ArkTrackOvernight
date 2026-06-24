"""Live operator-tuning surface — detector params + presets.

Mixin extracted from pipeline.py during the 2026-05-09 refactor. The methods
here read/write through `self` (a Pipeline instance), so the mixin assumes
these attributes exist:

    self.cfg              : PipelineConfig
    self.flash            : FlashDetector
    self.vlm              : VlmClassifier | None
    self.group_detector   : GroupDetector
    self.id_recovery      : IdRecovery
    self.detector_hog     : HogDetector | None
    self.detector_dfine   : DfineDetector | None
    self._user_presets    : dict[str, dict]
    self._broadcast       : (event: dict) → coroutine
    self._persist_safe    : () → None

`_read_param` / `_write_param` are the central dispatchers that map registry
keys to either cfg fields or live detector attributes — extending the
registry usually means adding one branch here.
"""

from __future__ import annotations

from typing import Optional

from pipeline_config import (
    BUILT_IN_PRESETS,
    DETECTOR_REGISTRY,
    _param_value_type,
)


class _TuningMixin:
    """Mixed into Pipeline — provides the per-detector live tuning + presets."""

    # ------------------------------------------------------------------
    # Per-detector live tuning
    # ------------------------------------------------------------------

    def list_detectors(self) -> list[str]:
        return list(DETECTOR_REGISTRY.keys())

    def get_detector_params(self, name: str) -> dict:
        """Current values + slider metadata for one detector. Shape is everything
        the UI needs to render a panel (defaults, bounds, labels, steps, helps)."""
        if name not in DETECTOR_REGISTRY:
            raise KeyError(f"unknown detector: {name}")
        spec = DETECTOR_REGISTRY[name]
        return {
            "name": name,
            "title": spec["title"],
            "values": {k: self._read_param(name, k) for k in spec["params"]},
            "defaults": {k: meta["default"] for k, meta in spec["params"].items()},
            "bounds":   {k: list(meta["bounds"]) for k, meta in spec["params"].items()},
            "labels":   {k: meta["label"] for k, meta in spec["params"].items()},
            "steps":    {k: meta["step"]  for k, meta in spec["params"].items()},
            "helps":    {k: meta["help"]  for k, meta in spec["params"].items()},
        }

    def get_all_detector_params(self) -> dict:
        return {name: self.get_detector_params(name) for name in DETECTOR_REGISTRY}

    async def set_detector_params(self, name: str, updates: dict) -> dict:
        """Apply a partial dict of params for one detector. Each value is
        coerced to its declared type, clamped to its bound, and written to the
        right runtime object. Broadcasts a `detector_params` WS message so other
        UIs stay in sync, and triggers persistence."""
        if name not in DETECTOR_REGISTRY:
            raise KeyError(f"unknown detector: {name}")
        spec = DETECTOR_REGISTRY[name]["params"]
        applied: dict = {}
        for k, v in updates.items():
            meta = spec.get(k)
            if meta is None or v is None:
                continue
            lo, hi = meta["bounds"]
            t = _param_value_type(meta["default"])
            if t is int:
                v = int(round(float(v)))
            elif t is bool:
                v = bool(v)
            else:
                v = float(v)
            v = max(lo, min(hi, v))
            self._write_param(name, k, v)
            applied[k] = v
        if applied:
            await self._broadcast({"type": "detector_params", "detector": name, "values": applied})
            # The active preset may have flipped (or unflipped to "Custom") —
            # broadcast the new active so chip highlighting stays in sync.
            await self._broadcast({"type": "active_preset", "name": self.active_preset_name()})
            self._persist_safe()
        return self.get_detector_params(name)

    async def reset_detector_params(self, name: str) -> dict:
        """Restore defaults for one detector."""
        if name not in DETECTOR_REGISTRY:
            raise KeyError(f"unknown detector: {name}")
        defaults = {k: meta["default"] for k, meta in DETECTOR_REGISTRY[name]["params"].items()}
        return await self.set_detector_params(name, defaults)

    # ------------------------------------------------------------------
    # Presets
    # ------------------------------------------------------------------
    # `_user_presets` is a dict[name -> {detector -> {key -> value}}].
    # Built-in preset names are reserved and cannot be overwritten.

    def list_presets(self) -> dict:
        """Return all known presets + which one (if any) currently matches state."""
        return {
            "builtin": list(BUILT_IN_PRESETS.keys()),
            "user": list(self._user_presets.keys()),
            "active": self.active_preset_name(),
        }

    def active_preset_name(self) -> Optional[str]:
        """Name of the preset whose values exactly match the current state, or
        None if the state is 'Custom'. Built-ins are checked first; user presets
        are full snapshots (every key) so they only match when nothing has been
        nudged since the snapshot was taken."""
        current = {
            det: dict(self.get_detector_params(det)["values"])
            for det in DETECTOR_REGISTRY
        }

        def _values_match(expected: dict, actual: dict) -> bool:
            if set(expected.keys()) != set(actual.keys()):
                return False
            for k in expected:
                e, a = expected[k], actual[k]
                if isinstance(e, float) or isinstance(a, float):
                    try:
                        if abs(float(e) - float(a)) > 1e-6:
                            return False
                    except Exception:
                        return False
                elif e != a:
                    return False
            return True

        def _matches_full(snapshot: dict) -> bool:
            for det in DETECTOR_REGISTRY:
                if not _values_match(snapshot.get(det, {}), current[det]):
                    return False
            return True

        # Built-ins: defaults + overrides
        for name, overrides in BUILT_IN_PRESETS.items():
            expected = {
                det: {k: meta["default"] for k, meta in spec["params"].items()}
                for det, spec in DETECTOR_REGISTRY.items()
            }
            for det, ov in overrides.items():
                if det in expected:
                    expected[det].update(ov)
            if _matches_full(expected):
                return name

        # User presets (full snapshots)
        for name, snap in self._user_presets.items():
            if _matches_full(snap):
                return name
        return None

    async def apply_preset(self, name: str) -> dict:
        """Apply a named preset. Always resets every detector to defaults first
        and then layers the preset's overrides — so behaviour is predictable
        whether the preset is partial (built-ins) or a full snapshot (user)."""
        preset = BUILT_IN_PRESETS.get(name)
        if preset is None:
            preset = self._user_presets.get(name)
        if preset is None:
            raise KeyError(f"unknown preset: {name}")

        # 1. Reset everything to factory defaults
        for det_name in DETECTOR_REGISTRY:
            await self.reset_detector_params(det_name)

        # 2. Apply preset overrides
        for det_name, params in preset.items():
            if det_name in DETECTOR_REGISTRY and isinstance(params, dict):
                await self.set_detector_params(det_name, params)

        await self._broadcast({"type": "preset_applied", "name": name})
        # Make the active-preset chip update on every connected client
        await self._broadcast({"type": "active_preset", "name": self.active_preset_name()})
        return self.get_all_detector_params()

    async def save_preset(self, name: str) -> dict:
        """Snapshot current detector params under `name`. Built-in names are reserved."""
        name = (name or "").strip()
        if not name:
            raise ValueError("preset name cannot be empty")
        if name in BUILT_IN_PRESETS:
            raise ValueError(f"cannot overwrite built-in preset: {name!r}")
        if len(name) > 40:
            raise ValueError("preset name too long (max 40 chars)")
        snapshot = {
            det: dict(self.get_detector_params(det)["values"])
            for det in DETECTOR_REGISTRY
        }
        self._user_presets[name] = snapshot
        self._persist_safe()
        await self._broadcast({"type": "presets_changed", "presets": self.list_presets()})
        return self.list_presets()

    async def delete_preset(self, name: str) -> dict:
        if name in BUILT_IN_PRESETS:
            raise ValueError(f"cannot delete built-in preset: {name!r}")
        if name not in self._user_presets:
            raise KeyError(f"unknown user preset: {name!r}")
        self._user_presets.pop(name, None)
        self._persist_safe()
        await self._broadcast({"type": "presets_changed", "presets": self.list_presets()})
        return self.list_presets()

    # ------------------------------------------------------------------
    # Per-detector read/write dispatchers
    # ------------------------------------------------------------------
    # Most params live on self.cfg or directly on the detector instance.
    # A few vlm keys are mirrored to BOTH the cfg field (so persistence
    # round-trips) AND the live VlmClassifier instance.

    def _read_param(self, det: str, key: str):
        if det == "welding":
            return getattr(self.flash, key)
        if det == "yolo":
            return getattr(self.cfg, key)
        if det == "vlm":
            if key == "vlm_revisit_s" and self.vlm is not None:
                return self.vlm.revisit_s
            return getattr(self.cfg, key)
        if det == "groups":
            v = getattr(self.group_detector, key)
            # idle_only is a bool internally; the registry models it as int(0/1).
            return int(v) if isinstance(v, bool) else v
        if det == "id_recovery":
            v = getattr(self.id_recovery, key)
            return int(v) if isinstance(v, bool) else v
        if det == "hog":
            # HOG params are mirrored: cfg holds the persisted snapshot,
            # the live detector instance holds the working value. Read from
            # the detector when it exists so live tuning round-trips correctly.
            if self.detector_hog is not None:
                # registry keys (hog_*) map to detector attrs (hog_max_dim → max_dim, …)
                attr = key[len("hog_"):] if key.startswith("hog_") else key
                return getattr(self.detector_hog, attr)
            return getattr(self.cfg, key)
        if det == "dfine":
            # Mirror pattern matching HOG. Registry keys (`dfine_input_size`,
            # `dfine_conf_threshold`, ...) map to detector attrs by stripping
            # the `dfine_` prefix.
            if self.detector_dfine is not None:
                attr = key[len("dfine_"):] if key.startswith("dfine_") else key
                v = getattr(self.detector_dfine, attr)
                return int(v) if isinstance(v, bool) else v
            return getattr(self.cfg, key)
        raise KeyError(f"unknown detector: {det}")

    def _write_param(self, det: str, key: str, value):
        if det == "welding":
            setattr(self.flash, key, value)
            return
        if det == "yolo":
            setattr(self.cfg, key, value)
            return
        if det == "vlm":
            if key in self.cfg.__dataclass_fields__:
                setattr(self.cfg, key, value)
            if key == "vlm_revisit_s" and self.vlm is not None:
                self.vlm.revisit_s = value
            return
        if det == "groups":
            # idle_only stored on the detector as bool, exposed as int 0/1
            if key == "idle_only":
                value = bool(int(value))
            setattr(self.group_detector, key, value)
            return
        if det == "id_recovery":
            if key == "embedding_enabled":
                value = bool(int(value))
            setattr(self.id_recovery, key, value)
            return
        if det == "hog":
            # Mirror to cfg (so persistence round-trips) and to the detector
            # if it exists (so the change takes effect on the next frame).
            if key in self.cfg.__dataclass_fields__:
                setattr(self.cfg, key, value)
            if self.detector_hog is not None:
                attr = key[len("hog_"):] if key.startswith("hog_") else key
                setattr(self.detector_hog, attr, value)
            return
        if det == "dfine":
            if key in self.cfg.__dataclass_fields__:
                setattr(self.cfg, key, value)
            if self.detector_dfine is not None:
                attr = key[len("dfine_"):] if key.startswith("dfine_") else key
                setattr(self.detector_dfine, attr, value)
                # input_size changes require a session rebuild on next detect.
                if key == "dfine_input_size":
                    self.detector_dfine._needs_rebuild = True
            return
        raise KeyError(f"unknown detector: {det}")
