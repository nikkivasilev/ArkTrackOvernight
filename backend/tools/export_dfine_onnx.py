"""One-time exporter: pull the D-FINE-L PyTorch checkpoint from HuggingFace
(`ustc-community/dfine-large-obj2coco`) and write an ONNX file that
onnxruntime + CUDA can serve for in-process detection.

Run once after installing torch + transformers + timm; the resulting ONNX
file lives under ``backend/checkpoints/`` and is loaded at runtime by
``DfineDetector``. Torch/transformers are not needed at inference time —
they can be uninstalled after the export to slim the venv.

Usage:
    cd backend
    .venv/Scripts/python.exe tools/export_dfine_onnx.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch
from transformers import AutoModelForObjectDetection


# The HF community port only exposes obj2coco variants up to "medium";
# the Large variant exists only as -coco (trained directly on COCO, no
# Objects365 pretrain). Functionally equivalent for person detection.
HF_MODEL_ID = "ustc-community/dfine-large-coco"


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--out",
        default="checkpoints/dfine_l_obj2coco.onnx",
        help="Output ONNX path (relative to backend/)",
    )
    p.add_argument(
        "--size",
        type=int,
        default=640,
        help="Input H=W in pixels (D-FINE is trained at 640)",
    )
    p.add_argument(
        "--opset",
        type=int,
        default=17,
        help="ONNX opset version",
    )
    args = p.parse_args()

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[export] loading {HF_MODEL_ID} from HuggingFace...", flush=True)
    model = AutoModelForObjectDetection.from_pretrained(HF_MODEL_ID)
    model.eval()
    # Float32 CPU — the runtime side does CUDA via ORT.
    model = model.to(torch.float32)

    H = W = int(args.size)
    dummy = torch.randn(1, 3, H, W, dtype=torch.float32)

    # D-FINE's HF forward returns a ModelOutput dataclass; torch.onnx.export
    # wants a tuple of plain tensors. Wrap it.
    class _ExportWrapper(torch.nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, pixel_values):
            out = self.m(pixel_values=pixel_values)
            # logits: (B, num_queries, num_classes)
            # pred_boxes: (B, num_queries, 4) — cxcywh in [0, 1]
            return out.logits, out.pred_boxes

    wrapper = _ExportWrapper(model).eval()

    print(f"[export] tracing -> {out_path} (input {H}x{W}, opset {args.opset})...", flush=True)
    with torch.no_grad():
        # Torch 2.12 defaults to the dynamo-based exporter, which trips on
        # D-FINE's `aten._is_all_true`. Force the legacy tracer-based path.
        torch.onnx.export(
            wrapper,
            (dummy,),
            str(out_path),
            input_names=["pixel_values"],
            output_names=["logits", "pred_boxes"],
            dynamic_axes={
                "pixel_values": {0: "batch"},
                "logits": {0: "batch"},
                "pred_boxes": {0: "batch"},
            },
            opset_version=args.opset,
            do_constant_folding=True,
            dynamo=False,
        )

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"[export] done: {out_path} ({size_mb:.1f} MB)", flush=True)

    # ------------------------------------------------------------------
    # ORT 1.26's GPU package ships a CPU EP without a float64 Cos kernel,
    # and the CUDA EP has no float64 Cos either. HF's D-FINE position
    # embeddings compute frequencies in float64 internally — Einsum+Cos+Sin
    # all show up as DOUBLE in the exported graph. Downcast every DOUBLE
    # tensor in the graph to FLOAT once at export time so ORT can run it.
    # ------------------------------------------------------------------
    import numpy as np
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    print("[export] downcasting float64 -> float32 for ORT compat...", flush=True)
    m = onnx.load(str(out_path))

    def _fix_type(t):
        if t.HasField("tensor_type") and t.tensor_type.elem_type == TensorProto.DOUBLE:
            t.tensor_type.elem_type = TensorProto.FLOAT
            return True
        return False

    # 1) Initializers
    new_inits = []
    n_inits = 0
    for init in m.graph.initializer:
        if init.data_type == TensorProto.DOUBLE:
            arr = numpy_helper.to_array(init).astype(np.float32)
            new = numpy_helper.from_array(arr, name=init.name)
            new_inits.append(new)
            n_inits += 1
        else:
            new_inits.append(init)
    del m.graph.initializer[:]
    m.graph.initializer.extend(new_inits)

    # 2) value_info / inputs / outputs
    n_vi = 0
    for vi in list(m.graph.value_info) + list(m.graph.input) + list(m.graph.output):
        if _fix_type(vi.type):
            n_vi += 1

    # 3) Cast nodes that target DOUBLE -> target FLOAT
    n_casts = 0
    for node in m.graph.node:
        if node.op_type == "Cast":
            for attr in node.attribute:
                if attr.name == "to" and attr.i == TensorProto.DOUBLE:
                    attr.i = TensorProto.FLOAT
                    n_casts += 1
        # Constants with raw_data
        if node.op_type == "Constant":
            for attr in node.attribute:
                if attr.name == "value" and attr.t.data_type == TensorProto.DOUBLE:
                    arr = numpy_helper.to_array(attr.t).astype(np.float32)
                    attr.t.CopyFrom(numpy_helper.from_array(arr))

    onnx.save(m, str(out_path))
    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(
        f"[export] downcast complete: {n_inits} initializers, "
        f"{n_vi} value_infos, {n_casts} Cast ops -> float32. "
        f"final size: {size_mb:.1f} MB",
        flush=True,
    )


if __name__ == "__main__":
    sys.exit(main() or 0)
