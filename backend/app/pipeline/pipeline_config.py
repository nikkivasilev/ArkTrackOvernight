"""Pure-data module — config dataclasses + tunable-detector registry.

Extracted from pipeline.py during the 2026-05-09 refactor to keep that file's
size manageable. Nothing here imports from the rest of the pipeline; it is
safe to import this module from anywhere (mixins, tests, scripts).

Public exports:
  * PipelineConfig — single source of truth for runtime config.
  * FrameOut — per-frame artefact published by the pipeline.
  * DETECTOR_REGISTRY — metadata describing every tunable detector knob.
                       Frontend tuning panels render directly from this.
  * BUILT_IN_PRESETS — named overrides applied on top of factory defaults.
  * _param_value_type — runtime type inference for registry coercion.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ----------------------------------------------------------------------
# Runtime config
# ----------------------------------------------------------------------


@dataclass
class PipelineConfig:
    video_path: str
    yolo_url: str
    yolo_key: str
    # Optional named alternates the operator can switch to live (e.g.
    # {"local": "http://yolo-local:8011"}). The primary `yolo_url` above is
    # always available and called "prod" in the active-source dropdown.
    yolo_sources_extra: dict = field(default_factory=dict)
    # Default active source is `prod` — the remote D-FINE-L HTTP server on
    # the WireGuard mesh (configured via `yolo_url` / `yolo_key`). The
    # in-process `dfine-l` source (when `dfine_enabled=True`) stays
    # registered as a hot fallback the operator can switch to via the
    # dashboard if the mesh is unreachable.
    yolo_source_active: str = "prod"
    target_fps: float = 20.0
    detect_every_n: int = 4
    conf: float = 0.10
    display_width: int = 1280
    jpeg_quality: int = 65       # MJPEG sent to browser (output)
    # Upload settings: cap the long side of the image we send to YOLO.
    # The model resamples internally, so anything beyond ~1280 mostly costs network bytes.
    detect_max_dim: int = 1280   # full-frame upload
    tile_max_dim: int = 0        # SAHI tile upload (0 = no downscale; tiles are already crops)
    # Upload JPEG quality. Tiles get higher quality because they carry the
    # small-object signal — extra ~20% bytes is worth it for crisper edges.
    upload_jpeg_quality: int = 65
    tile_jpeg_quality: int = 80
    sahi_enabled: bool = False
    sahi_cols: int = 2
    sahi_rows: int = 2
    sahi_overlap: float = 0.25
    sahi_conf: float = 0.10
    sahi_nms_iou: float = 0.45
    # Smart SAHI: when True, the tile grid only fires when `sahi_refresh_s`
    # seconds have elapsed since the last grid pass. Full-frame still runs
    # every cycle. `sahi_enabled` must also be True for this to take effect.
    sahi_smart: bool = False
    sahi_refresh_s: float = 5.0
    # VLM activity classifier
    vlm_enabled: bool = True
    # Backend: "siglip" = local in-process SigLIP-2 zero-shot (GPU, no network);
    # "qwen" = remote generative Qwen3-next over HTTP (vlm_url/vlm_model). Both
    # satisfy the same classify()/can_fire()/should_revisit() seam.
    vlm_backend: str = "siglip"
    vlm_url: str = "http://10.0.0.2:8000"
    vlm_model: str = "/models/qwen3-next"
    # Local SigLIP-2 (so400m-NaFlex). ONNX vision tower + precomputed label
    # text-embedding matrix from tools/export_siglip_onnx.py.
    siglip_onnx_path: str = "checkpoints/siglip2_so400m_naflex_vision.onnx"
    siglip_labels_path: str = "checkpoints/siglip2_labels.npy"
    siglip_execution_provider: str = "cuda"
    siglip_temperature: float = 0.05     # softmax temp over cosine sims (confidence)
    siglip_min_person_conf: float = 0.0  # below this → "unknown" (0 = disabled)
    # Asymmetric idle gate: if an idle label wins but its cosine margin over the
    # best working label is below this, emit "unknown" (→ working). Biases the
    # ambiguous stationary call toward working — the safe error for occupancy.
    # 0.03 was over-aggressive (live → ~0% idle, sitting workers flipped to
    # unknown); 0.012 lets clearly-idle workers (sitting/standing-around with a
    # real margin) register while still nudging near-ties toward working.
    siglip_idle_margin: float = 0.012
    vlm_revisit_s: float = 5.0
    vlm_min_age_s: float = 1.0         # don't classify a track until it's settled
    vlm_min_height_full: int = 60      # too small → mosaic is useless
    # Max concurrent VLM requests in flight per camera. Raising this above 1
    # lets the inflight slot serve two new tracks at once instead of one,
    # cutting first-verdict latency when many tracks arrive simultaneously.
    # Keep low enough that the remote VLM server isn't overwhelmed.
    vlm_max_inflight: int = 2
    # Stability hysteresis: a new activity label only replaces the displayed
    # one after this many consecutive same-class calls. 1 = no hysteresis
    # (every call sticks immediately, original behavior).
    vlm_stability_k: int = 1
    # Smart targeting (session 5): once a track has been classified, skip the
    # revisit if the heuristic activity is in this confident set AND matches
    # the last VLM verdict AND has been stable for >= vlm_confident_stability_s.
    # Frees the single-inflight slot for new / transitioning / unknown tracks.
    # Narrow set on purpose: "standing" is excluded because false-positive
    # machinery hits the same heuristic label and needs VLM "not_a_person"
    # filtering — keep that path alive.
    vlm_heuristic_confident_labels: list[str] = field(
        default_factory=lambda: ["walking", "welding"]
    )
    vlm_confident_stability_s: float = 4.0
    # Switch 3: high-conf full-frame mode. When `conf_high_enabled` is True the
    # full-frame YOLO call uses `conf_high` instead of `conf`. SAHI tile conf
    # (`sahi_conf`) is unaffected — small-object recall still depends on it.
    # Default OFF so production behaviour is unchanged until the switch flips.
    conf_high_enabled: bool = False
    conf_high: float = 0.15
    # OpenCV HOG human-detection layer. When enabled, registers an in-process
    # source named `opencv-hog` alongside the remote YOLO source. Operator
    # switches between them via `/control/yolo_source`. Defaults OFF so the
    # behaviour for existing deployments is unchanged.
    opencv_hog_enabled: bool = False
    hog_max_dim: int = 1280
    hog_scale: float = 1.05
    hog_hit_threshold: float = 0.0
    hog_win_stride: int = 8
    hog_nms_iou: float = 0.45
    # D-FINE-L (Objects365 + COCO finetuned) Apache-2.0 person detector
    # running in-process via onnxruntime. This is the PRIMARY detector;
    # `prod` (the remote YOLO HTTP server) is now an optional alternate.
    # ONNX file comes from `tools/download_models.{sh,ps1}` (auto-invoked
    # by `run.sh` on first boot). If the file is missing at boot the
    # source is silently skipped and the active-source fallback in
    # backend/pipeline.py reverts to `prod`.
    dfine_enabled: bool = True
    dfine_onnx_path: str = "checkpoints/dfine_l_obj2coco.onnx"
    dfine_input_size: int = 640
    dfine_conf_threshold: float = 0.40
    # Execution provider for onnxruntime. Default "cpu" — DirectML on
    # Windows + AMD RX 6600 was observed to produce numerically degraded
    # results for D-FINE-L's attention layers (max conf 0.11 vs CPU's
    # 0.89 on the same frame). Future hardware or onnxruntime versions
    # may fix this; setting "auto" prefers DirectML when available.
    dfine_execution_provider: str = "cpu"
    # Sanity-cap geometric filters. D-FINE shouldn't emit pathological boxes
    # but cheap insurance against weird outputs.
    dfine_max_aspect_ratio: float = 3.0
    dfine_max_box_area_frac: float = 0.85


@dataclass
class FrameOut:
    frame_idx: int
    t: float
    jpeg: bytes
    state: dict


# ----------------------------------------------------------------------
# Detector tuning registry
# ----------------------------------------------------------------------
#
# One entry per tunable detector. The frontend's tuning panels are rendered
# entirely from this metadata — to add a new tunable, append it to the
# matching detector's `params` dict and (if needed) extend Pipeline._read_param /
# _write_param to know where the value lives.
#
# `bounds` are clamped server-side; `step` is the slider granularity. Each
# value's runtime type (int/float/bool) is inferred from `default`.
DETECTOR_REGISTRY: dict = {
    "welding": {
        "title": "Welding (FlashDetector)",
        "params": {
            "min_area_far":         {"default": 350,   "bounds": (50, 5000),    "step": 25,
                                     "label": "Min area (far / top)",
                                     "help": "Smallest blob area accepted at the top of the frame. Lower → catches tinier far-field arcs but admits more reflections."},
            "min_area_near":        {"default": 1500,  "bounds": (200, 10000),  "step": 50,
                                     "label": "Min area (near / bottom)",
                                     "help": "Smallest blob area accepted at the bottom. Raise → rejects floor / chassis reflections; lower → may catch small near-field arcs."},
            "min_blob_bmr":         {"default": 80.0,  "bounds": (0.0, 200.0),  "step": 5,
                                     "label": "Min blue tint (B − R)",
                                     "help": "Average B-minus-R inside the blob. Real arcs ≥ 100; reflections drop to 50–90."},
            "min_blob_compactness": {"default": 0.40,  "bounds": (0.0, 1.0),    "step": 0.05,
                                     "label": "Min compactness",
                                     "help": "Filled fraction of bbox. Real arcs > 0.4; fragmented streaks < 0.3."},
            "per_pixel_bmr":        {"default": 30,    "bounds": (0, 100),      "step": 5,
                                     "label": "Per-pixel B − R threshold",
                                     "help": "Pixel must have at least this much blue dominance to enter the mask."},
            "per_pixel_v":          {"default": 235,   "bounds": (150, 255),    "step": 5,
                                     "label": "Per-pixel brightness (V)",
                                     "help": "Pixel V (HSV brightness) must exceed this. Lower admits dimmer reflections."},
            "persist_frames":       {"default": 2,     "bounds": (1, 10),       "step": 1,
                                     "label": "Persistence (frames)",
                                     "help": "How many observations before a flash is reported. Filters one-frame flicker."},
            "merge_dist":           {"default": 120.0, "bounds": (10.0, 1000.0),"step": 10,
                                     "label": "Merge distance (px)",
                                     "help": "Two arcs within this distance share the same flash id across frames."},
            # Switch 1: temporal V-channel variance gate.
            "temporal_variance_enabled": {"default": False, "bounds": (0, 1), "step": 1,
                                     "label": "Temporal V-variance gate (0/1)",
                                     "help": "1 = require per-pixel V to swing by ≥ threshold over the last 3 frames. Real arcs flicker; static cyan PPE / paint doesn't. 0 = off (default)."},
            "temporal_variance_min": {"default": 30,    "bounds": (5, 100),      "step": 5,
                                     "label": "V-variance min Δ",
                                     "help": "Pixel-wise (max V − min V) over the buffer must reach this for the pixel to enter the arc mask."},
        },
    },
    "yolo": {
        "title": "YOLO + ByteTrack + Stillness",
        "params": {
            "detect_every_n":       {"default": 14,    "bounds": (1, 30),       "step": 1,
                                     "label": "Detect every N frames",
                                     "help": "Run YOLO once every N source frames. Lower → more frequent detections but more YOLO load."},
            "conf":                 {"default": 0.05,  "bounds": (0.01, 0.5),   "step": 0.01,
                                     "label": "Full-frame confidence",
                                     "help": "Confidence threshold for the full-frame YOLO pass."},
            "sahi_conf":            {"default": 0.03,  "bounds": (0.01, 0.5),   "step": 0.01,
                                     "label": "SAHI tile confidence",
                                     "help": "Confidence threshold for per-tile passes (lower than full-frame to catch small objects)."},
            "sahi_overlap":         {"default": 0.30,  "bounds": (0.0, 0.5),    "step": 0.05,
                                     "label": "SAHI tile overlap",
                                     "help": "Fraction of tile dimension that adjacent tiles share. More overlap → fewer edge misses, more compute."},
            "sahi_cols":            {"default": 3,     "bounds": (1, 5),        "step": 1,
                                     "label": "SAHI columns",
                                     "help": "Number of horizontal tile columns. Higher → smaller tiles, more YOLO calls per cycle."},
            "sahi_rows":            {"default": 2,     "bounds": (1, 4),        "step": 1,
                                     "label": "SAHI rows",
                                     "help": "Number of vertical tile rows."},
            "sahi_nms_iou":         {"default": 0.45,  "bounds": (0.2, 0.7),    "step": 0.05,
                                     "label": "NMS IoU threshold",
                                     "help": "When merging tile detections, drop boxes overlapping a higher-confidence one by more than this IoU."},
            # Switch 3: high-conf full-frame mode.
            "conf_high_enabled":    {"default": False, "bounds": (0, 1),        "step": 1,
                                     "label": "High-conf full-frame mode (0/1)",
                                     "help": "1 = full-frame YOLO uses `conf_high` instead of `conf`. Cuts low-confidence false-positives that the tracker has to filter; recall stays via SAHI tiles (which keep `sahi_conf`). 0 = off (default)."},
            "conf_high":            {"default": 0.15, "bounds": (0.05, 0.5),    "step": 0.01,
                                     "label": "High-conf value",
                                     "help": "Full-frame confidence used when high-conf mode is on."},
        },
    },
    "id_recovery": {
        "title": "ID recovery (post-ByteTrack remap)",
        "params": {
            "embedding_enabled":    {"default": False, "bounds": (0, 1),        "step": 1,
                                     "label": "LAB-augmented signature (0/1)",
                                     "help": "1 = signature is HSV + LAB joint histograms (per upper/lower body region), distance is a weighted blend. Catches PPE hue differences that pure HSV misses on similar uniforms. 0 = HSV-only (default)."},
            "lab_weight":           {"default": 0.4,  "bounds": (0.0, 1.0),     "step": 0.05,
                                     "label": "LAB blend weight",
                                     "help": "0 = HSV-only contribution; 1 = LAB-only. Only matters when embedding_enabled=1."},
            "pos_threshold":        {"default": 280.0, "bounds": (50.0, 1000.0),"step": 10,
                                     "label": "Position threshold (px)",
                                     "help": "An orphan further than this from a new track is never matched, regardless of appearance."},
            "time_threshold":       {"default": 10.0, "bounds": (1.0, 60.0),    "step": 0.5,
                                     "label": "Orphan retention (s)",
                                     "help": "Drop orphans not re-matched within this many seconds."},
            "hist_weight":          {"default": 0.6,  "bounds": (0.0, 2.0),     "step": 0.1,
                                     "label": "Appearance weight in score",
                                     "help": "Score = spatial + hist_weight × appearance_dist. Higher → trust appearance more."},
            "accept_score":         {"default": 1.2,  "bounds": (0.5, 3.0),     "step": 0.1,
                                     "label": "Accept threshold",
                                     "help": "Best score must be below this to accept a re-match."},
        },
    },
    "vlm": {
        "title": "VLM activity classifier",
        "params": {
            "vlm_revisit_s":        {"default": 5.0,  "bounds": (0.5, 60.0),    "step": 0.5,
                                     "label": "Revisit interval (s)",
                                     "help": "How often to re-classify each track. Lower → fresher but more VLM load."},
            "vlm_min_age_s":        {"default": 1.0,  "bounds": (0.0, 10.0),    "step": 0.5,
                                     "label": "Min track age (s)",
                                     "help": "Don't classify a track until it's been alive at least this long (avoids flicker on noisy fresh tracks)."},
            "vlm_min_height_full":  {"default": 60,   "bounds": (20, 300),      "step": 10,
                                     "label": "Min bbox height",
                                     "help": "Skip tracks shorter than this — the mosaic crops are too small for the VLM to read."},
            "vlm_stability_k":      {"default": 1,    "bounds": (1, 5),         "step": 1,
                                     "label": "Stability K (consecutive same-class)",
                                     "help": "A new activity label only replaces the displayed one after this many consecutive same-class calls. 1 = no hysteresis. Higher reduces flicker on subtle classes (chatting, sleeping, on_phone)."},
        },
    },
    "dfine": {
        "title": "D-FINE-L (Objects365 + COCO)",
        "params": {
            "dfine_input_size":       {"default": 640,  "bounds": (320, 1280), "step": 32,
                                       "label": "Input size (px)",
                                       "help": "ONNX inference resolution (square). Higher → better small-object recall, slower. Changing this rebuilds the onnxruntime session on the next cycle."},
            "dfine_conf_threshold":   {"default": 0.40, "bounds": (0.05, 0.95), "step": 0.05,
                                       "label": "Confidence floor",
                                       "help": "Minimum softmax score for a person query. D-FINE-L is well-calibrated; 0.4 is a sensible default."},
            "dfine_max_aspect_ratio": {"default": 3.0,  "bounds": (1.0, 6.0),  "step": 0.1,
                                       "label": "Max aspect ratio (w/h)",
                                       "help": "Sanity cap — drop boxes wider than this multiple of their height. D-FINE shouldn't emit pathological boxes; this is insurance."},
            "dfine_max_box_area_frac":{"default": 0.85, "bounds": (0.1, 1.0),  "step": 0.05,
                                       "label": "Max box area (fraction of frame)",
                                       "help": "Sanity cap — drop boxes covering more than this fraction of the input frame."},
        },
    },
    "hog": {
        "title": "OpenCV HOG detector",
        "params": {
            "hog_max_dim":       {"default": 1280, "bounds": (320, 2560), "step": 64,
                                  "label": "Working resolution (px)",
                                  "help": "Downscale long side before HOG. Lower → faster but smaller workers get missed. Only used when 'opencv-hog' is the active source."},
            "hog_scale":         {"default": 1.05, "bounds": (1.01, 1.5), "step": 0.01,
                                  "label": "Multi-scale step",
                                  "help": "How aggressively HOG scans across scales. Closer to 1.0 → more scales tried (slower, better recall on size variation)."},
            "hog_hit_threshold": {"default": 0.0,  "bounds": (-1.0, 2.0), "step": 0.05,
                                  "label": "SVM score floor",
                                  "help": "Raw HOG-SVM score required to emit a candidate. Higher → fewer false positives, lower recall."},
            "hog_win_stride":    {"default": 8,    "bounds": (4, 16),     "step": 1,
                                  "label": "Window stride (px)",
                                  "help": "Sliding-window step. Smaller → more windows checked (slower, more recall). 8 is the OpenCV default."},
            "hog_nms_iou":       {"default": 0.45, "bounds": (0.1, 0.9),  "step": 0.05,
                                  "label": "NMS IoU threshold",
                                  "help": "When merging multi-scale boxes for one person, drop overlapping boxes above this IoU."},
        },
    },
    "groups": {
        "title": "Idle-group detector",
        "params": {
            "proximity_px":     {"default": 250,  "bounds": (50, 1000), "step": 25,
                                 "label": "Proximity (px)",
                                 "help": "Two workers within this many pixels of each other are considered nearby. ~250 px ≈ 2-3 m on this camera."},
            "min_members":      {"default": 2,    "bounds": (2, 8),     "step": 1,
                                 "label": "Min members",
                                 "help": "Smallest cluster size considered a group."},
            "min_duration_s":   {"default": 5.0,  "bounds": (1.0, 60.0),"step": 0.5,
                                 "label": "Min duration (s)",
                                 "help": "How long the same set of members must stay together before being reported as a group."},
            "max_velocity_pxs": {"default": 30.0, "bounds": (0.0, 200.0),"step": 5,
                                 "label": "Max velocity (px/s)",
                                 "help": "Members moving faster than this are excluded — they're walking, not standing."},
            "idle_only":        {"default": 1,    "bounds": (0, 1),     "step": 1,
                                 "label": "Idle-only filter (0/1)",
                                 "help": "1 = only consider workers labelled idle/chatting/standing/on_phone. 0 = any stationary track. (Toggle as 0 or 1.)"},
            "chatting_min_duration_s": {"default": 10.0, "bounds": (1.0, 120.0), "step": 1.0,
                                 "label": "Chatting min duration (s)",
                                 "help": "Once an idle group has persisted this long it is flagged as `chatting` in the state. Should be ≥ Min duration."},
        },
    },
}


def _param_value_type(default):
    """Infer the runtime type a registry default expects.

    Used by the live-tuning surface to coerce/clamp incoming values.
    """
    if isinstance(default, bool):
        return bool
    if isinstance(default, int):
        return int
    return float


# ----------------------------------------------------------------------
# Built-in presets — partial snapshots applied on top of factory defaults.
# Apply flow: reset every detector to defaults, then apply the preset's
# overrides. Missing keys → stay at default. "Default" is an empty preset.
# ----------------------------------------------------------------------
BUILT_IN_PRESETS: dict = {
    "Default": {},
    "High recall": {
        "welding": {
            "min_area_far": 200, "min_area_near": 800,
            "min_blob_bmr": 50, "min_blob_compactness": 0.30,
            "per_pixel_v": 220,
        },
        "yolo": {
            "detect_every_n": 8, "conf": 0.03, "sahi_conf": 0.02,
            "sahi_cols": 4, "sahi_rows": 3, "sahi_overlap": 0.40,
        },
        "vlm": {
            "vlm_revisit_s": 3.0, "vlm_min_age_s": 0.5,
        },
    },
    "High precision": {
        "welding": {
            "min_area_far": 500, "min_area_near": 2000,
            "min_blob_bmr": 100, "min_blob_compactness": 0.50,
            "per_pixel_v": 240,
        },
        "yolo": {
            "conf": 0.10, "sahi_conf": 0.05,
            "sahi_cols": 2, "sahi_rows": 2, "sahi_nms_iou": 0.50,
        },
        "vlm": {
            "vlm_min_age_s": 2.0,
        },
    },
    "Performance": {
        "yolo": {
            "detect_every_n": 20,
            "sahi_cols": 2, "sahi_rows": 2,
        },
        "vlm": {
            "vlm_revisit_s": 15.0, "vlm_min_age_s": 2.0,
        },
    },
}
