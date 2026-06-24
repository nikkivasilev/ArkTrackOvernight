"""One-time exporter for the local SigLIP-2 zero-shot activity classifier.

Produces three files under backend/checkpoints/:
  siglip2_so400m_naflex_vision.onnx  — the vision tower (pixel_values +
      pixel_attention_mask + spatial_shapes → 1152-d pooled image embedding),
      run on the GPU at inference via ONNX Runtime.
  siglip2_labels.npy                 — [num_labels, 1152] L2-normalized text
      embeddings (one row per label, prompt-ensemble averaged).
  siglip2_labels.json                — manifest: ordered label names +
      which rows are "no-person" (→ not_a_person) + embed dim + max_patches.

The text tower runs once here (CPU torch is fine) so only the vision tower
needs to run on the GPU at inference. Mirrors tools/export_dfine_onnx.py.

Run from backend/:
    .venv\\Scripts\\python.exe tools\\export_siglip_onnx.py

Re-run after editing SIGLIP_PROMPTS to refresh the label embeddings.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from transformers import AutoProcessor, Siglip2Model

ROOT = Path(__file__).resolve().parent.parent          # backend/
CKPT = ROOT / "checkpoints"
MODEL_ID = "google/siglip2-so400m-patch16-naflex"
MAX_PATCHES = 256
EMBED_DIM = 1152

ONNX_OUT = CKPT / "siglip2_so400m_naflex_vision.onnx"
NPY_OUT = CKPT / "siglip2_labels.npy"
MANIFEST_OUT = CKPT / "siglip2_labels.json"

# Prompt ensemble per label (averaged → one row per label). Design notes from
# the bias diagnostic (sitting/standing_idle had ~2-7x the cosine of working
# classes and swallowed 21/22 crops):
#   - `walking` is REMOVED — motion (classify_motion velocity) owns it; SigLIP
#     can't see movement in one frame and only mislabels walkers as idle.
#   - WORKING classes get many strong, broad "hands engaged / bent over a task"
#     templates + a generic `working` attractor so active labor competes.
#   - IDLE classes require absence-of-activity cues ("empty hands", "arms at
#     sides", "not working") so an actively-working person matches them LESS.
#   - `unknown` is absent (runtime low-confidence / margin fallback).
#   - `not_a_person` = explicit no-person prompts (flagged in manifest).
SIGLIP_PROMPTS: dict[str, list[str]] = {
    "working": [
        "a worker actively performing manual labor with their hands",
        "a worker bent over a workpiece, hands busy on a task",
        "a worker using a tool on a piece of equipment",
        "a worker focused on a hands-on task at a workstation",
        "a worker leaning in and manipulating an object with both hands",
        "a person doing physical work, body engaged in a task",
    ],
    "welding": [
        "a factory worker welding metal with a bright arc and sparks",
        "a person operating a welding torch on a workpiece",
        "a welder crouched over a seam, sparks flying",
    ],
    "grinding": [
        "a worker grinding metal with an angle grinder, sparks flying",
        "a person pressing a handheld grinder onto a workpiece",
    ],
    "drilling": [
        "a worker drilling into metal with a power drill",
        "a person pressing a drill into a workpiece",
    ],
    "assembling": [
        "a worker assembling parts, both hands fitting components together",
        "a person bolting and joining components by hand",
    ],
    "inspecting": [
        "a worker leaning in to closely inspect a workpiece",
        "a person measuring and checking a part with a tool",
    ],
    "lifting_or_carrying": [
        "a worker lifting and carrying a heavy object",
        "a person hauling material across the floor, body loaded",
    ],
    "standing_idle": [
        "a worker standing still with empty hands and arms at their sides, not working",
        "a person standing in place doing nothing, idle, hands free",
        "a worker just standing and looking around, not engaged in any task",
    ],
    "sitting": [
        "a worker sitting down resting, not working",
        "a person seated idle on a chair or the floor, hands free",
    ],
    "on_phone": [
        "a worker standing and looking at a mobile phone, not working",
        "a person distracted by a smartphone",
    ],
    "chatting": [
        "two idle workers standing close together talking, not working",
        "people chatting with each other, hands free",
    ],
    "sleeping": [
        "a worker lying down resting or sleeping on the ground",
        "a person lying motionless on the floor",
    ],
    "not_a_person": [
        "an empty factory floor with no people",
        "industrial machinery and equipment, no person",
        "a bare wall or floor, no person present",
        "a parked vehicle or object, not a person",
    ],
}
NO_PERSON_LABEL = "not_a_person"


class _VisionWrapper(torch.nn.Module):
    """Vision tower → pooled 1152-d embedding (== model.get_image_features)."""

    def __init__(self, vision_model):
        super().__init__()
        self.vm = vision_model

    def forward(self, pixel_values, pixel_attention_mask, spatial_shapes):
        return self.vm(
            pixel_values=pixel_values,
            pixel_attention_mask=pixel_attention_mask,
            spatial_shapes=spatial_shapes,
        ).pooler_output


SQUARE = 256  # letterbox target; 256/patch16 = 16x16 = 256 patches (== MAX_PATCHES)


def _letterbox_square(img: Image.Image, size: int = SQUARE) -> Image.Image:
    """Resize preserving aspect into a `size`x`size` canvas, padding the short
    side with neutral gray. Keeps the person's proportions (the standing-vs-
    sitting aspect cue) while fixing geometry so the NaFlex grid is always
    16x16 — which lets torch.onnx bake spatial_shapes=[16,16] correctly for
    every crop (TorchScript itemizes spatial_shapes, so it can't stay dynamic).
    """
    w, h = img.size
    s = size / max(w, h)
    nw, nh = max(1, round(w * s)), max(1, round(h * s))
    resized = img.resize((nw, nh), Image.BILINEAR)
    canvas = Image.new("RGB", (size, size), (128, 128, 128))
    canvas.paste(resized, ((size - nw) // 2, (size - nh) // 2))
    return canvas


def _proc_image(proc, img: Image.Image):
    return proc(images=[_letterbox_square(img)], max_num_patches=MAX_PATCHES, return_tensors="pt")


def _disable_interpolate_antialias() -> None:
    """NaFlex resizes its positional embedding grid with antialiased bilinear
    interpolation (aten::_upsample_bilinear2d_aa), which torch.onnx's
    TorchScript exporter cannot emit at any opset. Force antialias=False so it
    becomes plain bilinear (exportable). Minor smoothing difference, negligible
    for the pooled embedding. Patched for export AND the validation torch run
    so the ONNX-vs-torch comparison stays apples-to-apples.
    """
    import torch.nn.functional as _tf
    _orig = _tf.interpolate

    def _no_aa(*args, **kwargs):
        if kwargs.get("antialias"):
            kwargs["antialias"] = False
        return _orig(*args, **kwargs)

    _tf.interpolate = _no_aa


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels-only", action="store_true",
                    help="Regenerate only the label text embeddings + manifest "
                         "(skip the 1.6 GB vision ONNX export). Use this when "
                         "iterating SIGLIP_PROMPTS — the vision graph is unchanged.")
    args = ap.parse_args()

    CKPT.mkdir(parents=True, exist_ok=True)
    _disable_interpolate_antialias()
    print(f"Loading {MODEL_ID} (CPU torch; one-time)...")
    proc = AutoProcessor.from_pretrained(MODEL_ID)
    model = Siglip2Model.from_pretrained(MODEL_ID).eval()

    # ---- 1. Text label embeddings (prompt-ensemble averaged, normalized) ----
    labels = list(SIGLIP_PROMPTS.keys())
    rows = np.zeros((len(labels), EMBED_DIM), dtype=np.float32)
    with torch.no_grad():
        for i, label in enumerate(labels):
            tok = proc(text=SIGLIP_PROMPTS[label], return_tensors="pt", padding="max_length")
            emb = model.get_text_features(**tok).pooler_output          # [k, 1152]
            emb = F.normalize(emb, dim=-1).mean(dim=0)                  # ensemble mean
            emb = F.normalize(emb, dim=-1)                             # renormalize
            rows[i] = emb.numpy()
    np.save(NPY_OUT, rows)
    manifest = {
        "labels": labels,
        "no_person_label": NO_PERSON_LABEL,
        "embed_dim": EMBED_DIM,
        "max_patches": MAX_PATCHES,
        "model_id": MODEL_ID,
        # Runtime MUST letterbox crops to this square before the processor —
        # the ONNX baked spatial_shapes=[16,16] for this fixed geometry.
        "input_mode": "letterbox_square",
        "square_size": SQUARE,
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2))
    print(f"  wrote {NPY_OUT.name} {rows.shape} + {MANIFEST_OUT.name} ({len(labels)} labels)")

    if args.labels_only:
        if not ONNX_OUT.exists():
            print(f"  WARNING: {ONNX_OUT.name} does not exist — run without --labels-only once.")
        print("labels-only: skipped vision ONNX export (graph unchanged).")
        return 0

    # ---- 2. Vision tower → ONNX (static 256-patch shape) ----
    wrapper = _VisionWrapper(model.vision_model).eval()
    ex = _proc_image(proc, Image.fromarray((np.random.rand(240, 96, 3) * 255).astype(np.uint8)))
    args = (ex["pixel_values"], ex["pixel_attention_mask"], ex["spatial_shapes"])
    print(f"Exporting vision tower → {ONNX_OUT.name} (dynamo)...")
    # Use the torch.export-based (dynamo) exporter, not legacy TorchScript:
    # TorchScript itemizes spatial_shapes into constants and bakes inconsistent
    # reshapes in the attention-pooling head (ORT then fails at session init).
    # dynamo tracks shapes symbolically and produces a consistent graph.
    with torch.no_grad():
        torch.onnx.export(
            wrapper, args, str(ONNX_OUT),
            input_names=["pixel_values", "pixel_attention_mask", "spatial_shapes"],
            output_names=["image_embed"],
            opset_version=18,
            dynamo=True,
        )
    print(f"  wrote {ONNX_OUT.name} ({ONNX_OUT.stat().st_size/1e6:.1f} MB)")

    # ---- 3. Validate ONNX == torch across aspect ratios ----
    # spatial_shapes varies with aspect; this is the NaFlex export risk. If the
    # exported graph baked in one geometry, off-aspect crops will diverge here.
    import onnxruntime as ort
    sess = ort.InferenceSession(str(ONNX_OUT), providers=["CPUExecutionProvider"])
    onnx_inputs = [i.name for i in sess.get_inputs()]
    print(f"ONNX inputs (spatial_shapes is baked → pruned): {onnx_inputs}")
    # Sanity: letterboxed square always yields the baked 16x16 grid, full mask.
    chk = _proc_image(proc, Image.fromarray((np.random.rand(256, 96, 3) * 255).astype(np.uint8)))
    print(f"  spatial_shapes for a letterboxed crop: {chk['spatial_shapes'].tolist()[0]} "
          f"(expect [16, 16]); mask sum {int(chk['pixel_attention_mask'].sum())}/256")

    print("Validating ONNX vs torch on varied content (fixed geometry)...")
    ok = True
    for name, (h, w) in {"tall": (256, 96), "square": (192, 192), "wide": (96, 256)}.items():
        img = Image.fromarray((np.random.rand(h, w, 3) * 255).astype(np.uint8))
        pi = _proc_image(proc, img)
        with torch.no_grad():
            t = wrapper(pi["pixel_values"], pi["pixel_attention_mask"], pi["spatial_shapes"]).numpy()
        feed = {k: pi[k].numpy() for k in onnx_inputs}   # only inputs the graph kept
        o = sess.run(["image_embed"], feed)[0]
        tn = t / np.linalg.norm(t); on = o / np.linalg.norm(o)
        cos = float((tn * on).sum())
        flag = "OK" if cos > 0.999 else "FAIL"
        if cos <= 0.999:
            ok = False
        print(f"  {name:6s} cos={cos:.5f} maxd={float(np.abs(t - o).max()):.4f} {flag}")

    print("\nVALIDATION:", "PASS — ONNX matches torch at the fixed letterbox-square geometry"
          if ok else "FAIL — ONNX diverges from torch")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
