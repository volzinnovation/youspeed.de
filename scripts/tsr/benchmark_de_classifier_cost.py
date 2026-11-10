#!/usr/bin/env python3
"""Screen DE classifier architecture cost without making accuracy claims.

Requires an existing environment with torch, timm and Ultralytics 8.4.56.
No packages, weights or data are downloaded. Only the hash-pinned Panoramax
checkpoint is loaded; the MobileNet candidates have RANDOM weights. The two
new baseline head rows are also random. These models must not be deployed.

The same seeded RGB/255-shaped tensor is used for every architecture, with
all image decoding/preprocessing outside timing. Timings are host measurements,
not Core ML/LiteRT or phone performance. MACs cover Conv/Linear modules only,
excluding attention matmuls, activation, pooling, normalization and softmax.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import time
from typing import Any


MODEL_SHA256 = "f8277a3790fd3357b3ca31a086c7dc9f365785c7fa44bfd3b5c68834555699c7"
MODEL_REVISION = "5360aa6f4ef6c7b1998044b18d00b4d0b1a5a790"
BASELINE_PARAMETERS = 13_006_278
TIMM_MODELS = ("mobilenetv3_small_100", "mobilenetv3_large_100")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_checkpoint(path: Path) -> str:
    actual = sha256_file(path)
    if actual != MODEL_SHA256:
        raise ValueError(f"Baseline checkpoint SHA-256 mismatch: {actual}")
    return actual


def percentile(values: list[float], fraction: float) -> float:
    """Linear interpolation between ranks (N-1)*q, including endpoints."""
    if not values or not 0 <= fraction <= 1:
        raise ValueError("Need samples and a quantile in [0, 1]")
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("Latency samples must be finite and nonnegative")
    ordered = sorted(values)
    rank = (len(ordered) - 1) * fraction
    lower, upper = math.floor(rank), math.ceil(rank)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def latency_summary(values: list[float]) -> dict[str, Any]:
    return {
        "samples": len(values), "p50_ms": percentile(values, .5),
        "p95_ms": percentile(values, .95), "p99_ms": percentile(values, .99),
        "min_ms": min(values), "max_ms": max(values),
        "mean_ms": statistics.mean(values), "samples_ms": values,
        "quantile_method": "linear interpolation at (N-1)*q",
    }


def conv_macs(output_elements: int, input_channels: int,
              groups: int, kernel_size: tuple[int, ...]) -> int:
    if groups <= 0 or input_channels % groups:
        raise ValueError("Convolution groups must divide input channels")
    return output_elements * (input_channels // groups) * math.prod(kernel_size)


def linear_macs(output_elements: int, input_features: int) -> int:
    return output_elements * input_features


def profile_macs(model: Any, tensor: Any, torch: Any) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    hooks = []
    conv_types = (torch.nn.Conv1d, torch.nn.Conv2d, torch.nn.Conv3d)

    def make_hook(name: str):
        def hook(module: Any, inputs: Any, output: Any) -> None:
            if isinstance(module, conv_types):
                count = conv_macs(output.numel(), module.in_channels,
                                  module.groups, tuple(module.kernel_size))
            else:
                count = linear_macs(output.numel(), module.in_features)
            entries.append({"name": name, "type": type(module).__name__,
                            "output_shape": list(output.shape), "macs": count})
        return hook

    try:
        for name, module in model.named_modules():
            if isinstance(module, (*conv_types, torch.nn.Linear)):
                hooks.append(module.register_forward_hook(make_hook(name)))
        with torch.inference_mode():
            model(tensor)
    finally:
        for hook in hooks:
            hook.remove()
    return {
        "conv_linear_macs": sum(entry["macs"] for entry in entries),
        "counted_module_invocations": len(entries), "modules": entries,
        "convention": "One multiply-accumulate = one MAC; Conv1d/2d/3d and Linear only; bias additions excluded.",
        "excluded": ["attention matmul", "activation", "pooling", "normalization",
                     "softmax", "tensor transforms", "preprocessing"],
        "is_total_model_flops": False,
    }


def extend_head(model: Any, torch: Any) -> Any:
    extended = deepcopy(model)
    head = extended.model[-1]
    old = head.linear
    if old.in_features != 1280 or old.out_features != 134 or old.bias is None:
        raise ValueError("Expected the pinned 1280-to-134 classification head")
    replacement = torch.nn.Linear(1280, 136)
    with torch.no_grad():
        replacement.weight[:134].copy_(old.weight)
        replacement.bias[:134].copy_(old.bias)
    head.linear = replacement
    extended.names = {**dict(extended.names), 134: "city:start", 135: "city:end"}
    if hasattr(extended, "nc"):
        extended.nc = 136
    if hasattr(extended, "yaml"):
        extended.yaml = {**extended.yaml, "nc": 136}
    return extended.eval()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="JSON result file")
    parser.add_argument("--device", default="cpu", help="cpu, cuda, cuda:N, or all (CPU plus available CUDA)")
    parser.add_argument("--cpu-threads", type=int, nargs="+", default=[1, 4])
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20261109)
    args = parser.parse_args(argv)
    valid_device = args.device in {"cpu", "cuda", "all"} or (
        args.device.startswith("cuda:") and args.device[5:].isdigit())
    if not valid_device:
        parser.error("--device must be cpu, cuda, cuda:N, or all")
    if args.warmup < 1 or args.iterations < 2 or any(value < 1 for value in args.cpu_threads):
        parser.error("Require warmup>=1, iterations>=2 and positive CPU thread counts")
    args.cpu_threads = list(dict.fromkeys(args.cpu_threads))
    return args


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def run(args: argparse.Namespace) -> dict[str, Any]:
    # Verify bytes before importing the loader or deserializing its checkpoint.
    digest = verify_checkpoint(args.model)
    import torch
    import timm
    import ultralytics
    from ultralytics import YOLO

    if ultralytics.__version__ != "8.4.56":
        raise ValueError(f"Expected Ultralytics 8.4.56, got {ultralytics.__version__}")
    torch.manual_seed(args.seed)
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
        torch.backends.cudnn.benchmark = False
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False

    class ProbabilityOutput(torch.nn.Module):
        def __init__(self, network: Any, needs_softmax: bool):
            super().__init__()
            self.network = network
            self.needs_softmax = needs_softmax

        def forward(self, images: Any) -> Any:
            result = self.network(images)
            if isinstance(result, (tuple, list)):
                result = result[0]  # Ultralytics eval returns probabilities, logits.
            return result.softmax(dim=1) if self.needs_softmax else result

    original = YOLO(str(args.model)).model.float().eval()
    if sum(parameter.numel() for parameter in original.parameters()) != BASELINE_PARAMETERS:
        raise ValueError("Pinned checkpoint has an unexpected parameter count")
    candidates = [
        ("panoramax_yolo26l_134", original, False, 134, "pinned original weights"),
        ("panoramax_yolo26l_136", extend_head(original, torch), False, 136,
         "original weights with two RANDOM output rows; not trained"),
    ]
    for name in TIMM_MODELS:
        candidates.append((name + "_136", timm.create_model(name, pretrained=False, num_classes=136),
                           True, 136, "RANDOM weights; architecture cost only"))
    tensor = torch.rand((1, 3, 224, 224), generator=torch.Generator().manual_seed(args.seed))
    profiles = []
    if args.device in {"cpu", "all"}:
        profiles.extend({"device": "cpu", "dtype": "float32", "threads": count}
                        for count in args.cpu_threads)
    cuda_requested = args.device == "all" or args.device.startswith("cuda")
    if cuda_requested and torch.cuda.is_available():
        device = args.device if args.device.startswith("cuda:") else "cuda:0"
        profiles.extend({"device": device, "dtype": dtype, "threads": 1}
                        for dtype in ["float32", "float16"])
    elif args.device.startswith("cuda"):
        raise RuntimeError("CUDA requested but torch reports it unavailable")

    report: dict[str, Any] = {
        "schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "running", "scope": "architecture cost only, not accuracy or device acceptance",
        "checkpoint_sha256": digest, "checkpoint_revision": MODEL_REVISION,
        "script_sha256": sha256_file(Path(__file__)),
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        "machine": platform.machine(), "cpu_logical_count": os.cpu_count(),
                        "cpu_affinity_count": len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
                        "torch": torch.__version__, "timm": timm.__version__,
                        "ultralytics": ultralytics.__version__, "cuda_runtime": torch.version.cuda,
                        "cuda_available": torch.cuda.is_available(),
                        "cuda_devices": [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())],
                        "interop_threads": 1, "tf32_enabled": False, "cudnn_benchmark": False},
        "configuration": {"input_shape": [1, 3, 224, 224], "input": "seeded Float32 RGB/255-range random tensor shared across candidates",
                          "input_tensor_sha256": hashlib.sha256(tensor.numpy().tobytes()).hexdigest(),
                          "seed": args.seed, "warmup": args.warmup, "iterations": args.iterations,
                          "profiles": profiles, "preprocessing_in_timing": False,
                          "softmax_included": True, "compilation": "none; PyTorch eager",
                          "timing": "perf_counter_ns around batch1 forward; CUDA synchronize before and after every sample",
                          "cuda_skipped": cuda_requested and not torch.cuda.is_available()},
        "limitations": [
            "No F1, accuracy or learned capability measured; random candidates are not recognition models.",
            "Conv/Linear MACs omit attention matmul and other operations; not total FLOPs.",
            "Host CPU/CUDA timings do not predict mobile CoreML/LiteRT latency, energy or thermal behavior.",
            "Image decoding, crop/resize, normalization, transfer, model construction and cold-start are excluded.",
            "Parameter bytes are theoretical storage, not process or accelerator peak memory.",
        ],
        "models": [],
    }
    write_json(args.output, report)
    for name, network, needs_softmax, class_count, provenance in candidates:
        model = ProbabilityOutput(network.float().eval(), needs_softmax).eval()
        with torch.inference_mode():
            output = model(tensor)
            if tuple(output.shape) != (1, class_count) or not bool(torch.isfinite(output).all()):
                raise ValueError(f"Unexpected output shape or nonfinite output: {name}")
        parameters = sum(parameter.numel() for parameter in model.parameters())
        result = {"id": name, "class_count": class_count, "weights": provenance,
                  "parameters": parameters, "fp32_parameter_bytes": parameters * 4,
                  "fp16_parameter_bytes": parameters * 2, "int8_parameter_bytes_theoretical": parameters,
                  "operations": profile_macs(model, tensor, torch), "latency": []}
        report["models"].append(result)
        for profile in profiles:
            torch.set_num_threads(profile["threads"])
            dtype = getattr(torch, profile["dtype"])
            current = deepcopy(model).to(device=profile["device"], dtype=dtype).eval()
            images = tensor.to(device=profile["device"], dtype=dtype)
            is_cuda = profile["device"].startswith("cuda")

            def sync() -> None:
                if is_cuda:
                    torch.cuda.synchronize(profile["device"])

            durations = []
            with torch.inference_mode():
                for _ in range(args.warmup):
                    current(images)
                sync()
                for _ in range(args.iterations):
                    sync()
                    before = time.perf_counter_ns()
                    current(images)
                    sync()
                    durations.append((time.perf_counter_ns() - before) / 1_000_000)
            result["latency"].append({**profile, **latency_summary(durations)})
            write_json(args.output, report)
            print(json.dumps({"model": name, **profile, "p50_ms": percentile(durations, .5),
                              "p95_ms": percentile(durations, .95)}), flush=True)
            del current, images
            gc.collect()
            if is_cuda:
                torch.cuda.empty_cache()
        del model
    report["status"] = "complete"
    report["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    write_json(args.output, report)
    return report


if __name__ == "__main__":
    run(parse_args())
